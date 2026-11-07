"""Check a proof bundle without trusting the app that made it.

    python tools/verify_proof.py proof.zip

1. Integrity: every file in the zip matches the manifest, and every input file matches the hash of the run.
2. Evidence: every quoted fact is found in its cited file, on its cited page for PDFs with a text layer.
   A quote read by OCR from a picture can't be found in a text layer; it is listed for a person to check
   against the highlighted crop instead.
3. Replay: the deterministic checks rerun on the bundled facts, rules, and scope give the same results.

Exit code 0 only if all three hold.
"""
from __future__ import annotations

import csv
import io
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.engine import run  # noqa: E402
from app.models import Fact, Rule, ScopeDecision, ShipProfile  # noqa: E402
from app.proof import read_bundle  # noqa: E402
from app.store import FactStore  # noqa: E402


def _norm(text: str) -> str:
    text = text.replace("’", "'").replace("′", "'").replace("”", '"').replace("″", '"')
    return re.sub(r"\s+", " ", text).strip().lower()


def _file_text(name: str, data: bytes, page: int | None) -> tuple[str | None, str]:
    """(searchable text, how it was read). None when the file has no text to search."""
    suffix = Path(name).suffix.lower()
    if suffix == ".pdf":
        import pymupdf
        document = pymupdf.open(stream=data, filetype="pdf")
        pages = [page] if page and 1 <= page <= len(document) else range(1, len(document) + 1)
        text = " ".join(document[n - 1].get_text() for n in pages)
        return (text, f"text layer of page {page}" if page else "text layer") if text.strip() else (None, "no text layer")
    if suffix == ".xlsx":
        import openpyxl
        book = openpyxl.load_workbook(io.BytesIO(data), data_only=True, read_only=True)
        cells = [str(c) for sheet in book.worksheets for row in sheet.iter_rows(values_only=True) for c in row if c is not None]
        return " | ".join(cells), "cell values"
    if suffix == ".csv":
        rows = csv.reader(io.StringIO(data.decode("utf-8-sig", errors="replace")))
        return " | ".join(c for row in rows for c in row), "cell values"
    if suffix in (".ifc", ".txt", ".md"):
        return data.decode("utf-8", errors="replace"), "file text"
    return None, "not a text format"


def _ifc_number(value: str, text: str) -> bool:
    """Whether the number of an IFC property value appears in the STEP text, written as IFC writes it (900. or 900.0)."""
    try:
        number = float(value)
    except ValueError:
        return f"'{value}'" in text or value in text
    forms = {f"{number:g}.", f"{number:.1f}", f"{number}"} | ({f"{int(number)}"} if number.is_integer() else set())
    return any(re.search(rf"[(,]{re.escape(form)}[),]", text) for form in forms)


def check_evidence(bundle: dict, files: dict[str, bytes]) -> tuple[list[str], list[str], int]:
    """(problems, for a person to check, quotes found)."""
    problems, manual, found = [], [], 0
    for fact in bundle.get("facts", []):
        evidence = fact.get("evidence") or {}
        quote, name = evidence.get("quote") or fact["source"].get("quote"), evidence.get("file") or fact["source"].get("file")
        if not quote or not name or fact.get("derivation") or fact["source"].get("kind") in ("chat", "3d_model", "demo_seed"):
            continue  # derived by code (rerun in step 3), stated by an engineer, or a model attribute: no quote to find
        if name not in files:
            manual.append(f"{fact['subject']} {fact['property']}: {name} isn't in the bundle, so its quote can't be checked.")
            continue
        text, how = _file_text(name, files[name], evidence.get("page"))
        methods = {r.get("method") for r in evidence.get("readings", [])}
        if text is None:
            manual.append(f"{fact['subject']} {fact['property']} = {fact['value']}: {how} in {name}; check the quote "
                          f"\"{quote}\" against the highlighted crop.")
            continue
        # Cell values are the parts of a quote like "Sheet1!C7: 815": accept either the whole or the value cell.
        pieces = [quote] + ([quote.split(": ", 1)[1]] if ": " in quote else [])
        parts = [p for p in quote.split(" / ")] if " / " in quote else []  # a tag and its value, cited together
        ifc = re.fullmatch(r"([\w.]+)\.(\w+) = (.+)", quote.strip()) if Path(name).suffix.lower() == ".ifc" else None
        if any(_norm(piece) in _norm(text) for piece in pieces) or (parts and all(_norm(p) in _norm(text) for p in parts)):
            found += 1
        elif ifc and f"'{ifc.group(2)}'" in text and _ifc_number(ifc.group(3), text):
            found += 1  # an IFC property: its name and its value are both in the model file
        elif ifc and ifc.group(1).upper().startswith("IFC") and _ifc_number(ifc.group(3), "\n".join(
                l for l in text.splitlines() if ifc.group(1).upper() in l.upper())):
            found += 1  # an entity attribute such as IfcDoor.OverallWidth: the value is on a line of that entity
        elif "ocr" in methods and "text_layer" not in methods:
            manual.append(f"{fact['subject']} {fact['property']} = {fact['value']}: read by OCR, not in the {how}; "
                          f"check \"{quote}\" against the crop.")
        else:
            problems.append(f"{fact['subject']} {fact['property']} = {fact['value']}: quote \"{quote}\" not found in the {how} of {name}.")
    return problems, manual, found


def replay(bundle: dict) -> tuple[list[str], int]:
    facts = [Fact(**{k: v for k, v in raw.items() if k != "id"}) for raw in bundle["facts"]]
    rules = [Rule(**{k: v for k, v in raw.items() if k != "quote_found_in_rule_text"}) for raw in bundle["rules"]]
    decisions = {d["rule_id"]: ScopeDecision(**d) for d in bundle["scope"]}
    profile = ShipProfile(**bundle["profile"])
    result = run(FactStore(facts), rules, profile, scope_fn=lambda rule, _p: decisions[rule.id])
    key = lambda f: (f["rule_id"], f["subject"], f["label"])  # noqa: E731
    rerun_list = [x.model_dump(mode="json") for x in result.findings]
    problems = []
    for name, items in (("bundle", bundle["findings"]), ("rerun", rerun_list)):
        keys = [key(f) for f in items]
        if len(keys) != len(set(keys)):
            problems.append(f"The {name} holds two results for the same rule and item, so one could hide the other.")
    if len(bundle["findings"]) != len(rerun_list):
        problems.append(f"The bundle has {len(bundle['findings'])} results; the rerun gives {len(rerun_list)}.")
    recorded = {key(f): f for f in bundle["findings"]}
    rerun = {key(f): f for f in rerun_list}
    for k in recorded.keys() | rerun.keys():
        a, b = recorded.get(k), rerun.get(k)
        if a is None or b is None:
            problems.append(f"{k[2]} ({k[0]}): {'only in the rerun' if a is None else 'missing from the rerun'}.")
            continue
        for field in ("status", "measured", "required", "gap", "gate"):
            if a.get(field, "") != b.get(field, ""):
                problems.append(f"{k[2]} ({k[0]}): {field} was \"{a.get(field)}\", the rerun gives \"{b.get(field)}\".")
    return problems, len(recorded)


def main() -> int:
    if len(sys.argv) != 2:
        print(__doc__)
        return 2
    data = Path(sys.argv[1]).read_bytes()
    bundle, files, integrity = read_bundle(data)
    import zipfile, io, hashlib
    body = zipfile.ZipFile(io.BytesIO(data)).read("bundle.json")
    print(f"bundle.json sha256 {hashlib.sha256(body).hexdigest()} (compare with the X-Bundle-SHA256 the app sent at download;"
          " without that, a bundle rebuilt from scratch can't be told apart)")
    print(f"Bundle for {bundle.get('profile', {}).get('name', '?')}, made {bundle.get('created', '?')} by code {bundle.get('code_version', '?')}")
    print(f"1. Integrity: {'OK' if not integrity else 'FAILED'}")
    for line in integrity:
        print("   -", line)
    evidence_problems, manual, found = check_evidence(bundle, files)
    print(f"2. Evidence: {found} quotes found in their files, {len(evidence_problems)} not found, {len(manual)} for a person to check")
    for line in evidence_problems + manual:
        print("   -", line)
    replay_problems, total = replay(bundle)
    print(f"3. Replay: {total} results, {'all the same' if not replay_problems else f'{len(replay_problems)} differ'}")
    for line in replay_problems:
        print("   -", line)
    ok = not integrity and not evidence_problems and not replay_problems
    print("VERIFIED" if ok else "NOT VERIFIED")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
