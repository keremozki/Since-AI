"""Check the code reader and the checks against every drawing we have, real and synthetic.

For each PDF under data/ (and ../test-data-paketi/ if it is there), duplicates skipped:
- with a truth file (synthetic sheets, hand-labelled real sheets): reader facts vs truth facts
  (exact values), and check results vs the expected result per object;
- without one: what the reader found, page by page, so a person can spot-check it.

    .venv/Scripts/python tools/validate_data.py      # writes data/reports/validation.json
"""
from __future__ import annotations

import hashlib
import json
import sys
import tempfile
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.confidence import ConfidenceGate  # noqa: E402
from app.drawing import read_pdf  # noqa: E402
from app.engine import run  # noqa: E402
from app.models import ShipProfile  # noqa: E402
from app.rules import load_rules  # noqa: E402
from app.store import FactStore  # noqa: E402
from app.units import is_length_unit, to_mm  # noqa: E402

VALUE_FACTS = {"clear_width", "length_overall", "beam", "persons_on_board", "crew_complement", "science_complement",
               "capacity_persons", "height_above_hull", "time_minutes", "lightship_weight"}


def norm(fact: dict) -> tuple[str, str, float]:
    value = float(fact["value"])
    if is_length_unit(fact.get("unit", "")):
        value = round(to_mm(value, fact["unit"]), 1)
    return fact["subject"], fact["property"], value


def truth_for(pdf: Path) -> dict | None:
    for candidate in (pdf.with_suffix(".truth.json"),
                      pdf.parents[1] / "ground_truth" / f"{pdf.stem}.json"):
        if candidate.exists():
            return json.loads(candidate.read_text(encoding="utf-8"))
    return None


def compare_facts(read: list[dict], truth: list[dict], absent: list[dict]) -> dict:
    got = Counter(norm(f) for f in read if f["property"] in VALUE_FACTS)
    want = Counter(norm(f) for f in truth)
    hit = sum((got & want).values())
    wrong = [list(k) for k in (got - want).elements()]
    missed = [list(k) for k in (want - got).elements()]
    forbidden = [w for w in wrong if any(w[1] == a["property"] and (a["subject"].endswith("*") and w[0].startswith(a["subject"][:-1])
                                                                        or w[0] == a["subject"]) for a in absent)]
    return {"truth": sum(want.values()), "read": sum(got.values()), "correct": hit,
            "precision": hit / sum(got.values()) if got else None, "recall": hit / sum(want.values()) if want else None,
            "wrong_or_extra": wrong, "missed": missed, "reported_but_not_on_drawing": forbidden}


def compare_results(facts, truth: dict, rules) -> dict:
    p = truth.get("profile", {})
    profile = ShipProfile(id="truth", name=truth["file"], ship_type=p.get("ship_type", ""), passengers=p.get("passengers"),
                          flag=p.get("flag", ""), accessible_route_all_passage_doors=True)
    with tempfile.TemporaryDirectory() as tmp:
        result = run(FactStore(facts), rules, profile, gate=ConfidenceGate(Path(tmp)))  # cold start, as in the app today
    got = {(f.rule_id, f.subject): f.status.value for f in result.findings}
    rows, tally = [], Counter()
    for e in truth.get("expected", []):
        if not e.get("app_has_check", True):
            tally["no_check_in_app"] += 1
            continue
        status = got.get((e["rule_id"], e["subject"]), "no result")
        ok = status == e["expected"]
        tally["match" if ok else "mismatch"] += 1
        if status == "pass" and e.get("violation"):
            tally["FALSE_PASS"] += 1
        if status == "fail" and not e.get("violation"):
            tally["false_fail"] += 1
        rows.append({"subject": e["subject"], "expected": e["expected"], "got": status, "ok": ok, "note": e.get("note", "")})
    return {"tally": dict(tally), "rows": rows}


def main() -> None:
    rules = load_rules(ROOT / "rules" / "rules.yaml", ROOT / "docs" / "rules")
    folders = [ROOT / "data", ROOT.parent / "test-data-paketi"]
    seen, report = set(), {}
    for pdf in sorted(p for folder in folders if folder.exists() for p in folder.rglob("*.pdf")):
        data = pdf.read_bytes()
        digest = hashlib.sha256(data).hexdigest()
        if digest in seen or "bench" in pdf.parts:
            continue
        seen.add(digest)
        read = read_pdf(data, pdf.name)
        facts = [f.model_dump(mode="json") for f in read.facts]
        entry = {"path": str(pdf.relative_to(ROOT.parent)), "pages": read.pages, "skipped": read.skipped,
                 "facts": [{k: f[k] for k in ("subject", "property", "value", "unit", "confidence")} | {"quote": f["source"]["quote"]}
                           for f in facts]}
        truth = truth_for(pdf)
        if truth:
            entry["synthetic"] = truth.get("synthetic")
            entry["reader"] = compare_facts(facts, truth.get("facts", []), truth.get("absent_facts", []))
            entry["checks"] = compare_results(read.facts, truth, rules)
        report[pdf.name] = entry

    (ROOT / "data" / "reports" / "validation.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"{'file':42s} {'kind':9s} {'reader correct':>15s} {'precision':>9s} {'recall':>6s}  checks")
    for name, e in report.items():
        kind = "no truth" if "reader" not in e else ("SYNTHETIC" if e["synthetic"] else "real")
        if "reader" in e:
            r, t = e["reader"], e["checks"]["tally"]
            checks = ", ".join(f"{k} {v}" for k, v in sorted(t.items())) or "no expected results"
            pr = f"{r['precision']:.2f}" if r["precision"] is not None else "-"
            rc = f"{r['recall']:.2f}" if r["recall"] is not None else "-"
            print(f"{name[:42]:42s} {kind:9s} {r['correct']:>7d} / {r['truth']:<5d} {pr:>9s} {rc:>6s}  {checks}")
            for w in r["wrong_or_extra"]:
                print(f"{'':54s}wrong/extra: {w}")
            for m in r["missed"]:
                print(f"{'':54s}missed: {m}")
            for row in e["checks"]["rows"]:
                if not row["ok"]:
                    print(f"{'':54s}{row['subject']}: expected {row['expected']}, got {row['got']} ({row['note']})")
        else:
            n_text = sum(p["text_chars"] > 50 for p in e["pages"])
            print(f"{name[:42]:42s} {kind:9s} {len(e['facts']):>7d} facts    pages with text {n_text}/{len(e['pages'])}")
    print("\nFull detail: data/reports/validation.json")


if __name__ == "__main__":
    main()
