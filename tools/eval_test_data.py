"""Run test drawings through the app and score the results against truth files.

Two modes per truth file in data/synthetic/ and data/ground_truth/:
  oracle  - feed the truth facts straight into the engine. Tests the checks alone (no reading).
  reader  - read the PDF with the app's reader (app.ingest.read_file, needs ANTHROPIC_API_KEY),
            then run the engine. Tests reading + checks. Skipped without a key.
For every file it also reports which path the reader would take (text or page images).

Usage: python tools/eval_test_data.py   (writes data/reports/eval.json and prints a summary)
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.engine import run  # noqa: E402
from app.ingest import TooManyPages, build_content  # noqa: E402
from app.models import Fact, ShipProfile  # noqa: E402
from app.rules import load_rules  # noqa: E402
from app.store import FactStore  # noqa: E402

RULES = load_rules(ROOT / "rules" / "rules.yaml", ROOT / "docs" / "rules")
DATA = ROOT / "data"


def reader_path(pdf: Path) -> str:
    try:
        blocks = build_content(pdf.name, pdf.read_bytes())
    except TooManyPages as exc:
        return f"refused: {exc}"
    kinds = [b["type"] for b in blocks]
    return f"{kinds.count('image')} page images" if "image" in kinds else "text layer"


def profile_from(truth: dict) -> ShipProfile:
    p = truth["profile"]
    return ShipProfile(id="test", name=truth["file"], ship_type=p["ship_type"], passengers=p.get("passengers"),
                       flag=p.get("flag", ""))


def score(truth: dict, facts: list[Fact]) -> dict:
    result = run(FactStore(facts), RULES, profile_from(truth))
    got = {}
    for f in result.findings:
        got.setdefault(f.subject, f.status.value)
    rows, tp, fp, fn, tn = [], 0, 0, 0, 0
    for exp in truth["expected"]:
        if not exp.get("app_has_check", True):
            rows.append({**exp, "got": "no check in app"})
            continue
        status = got.get(exp["subject"], "no result")
        flagged = status in ("fail", "conflict", "cant_tell")
        if exp["violation"] and flagged:
            tp += 1
        elif exp["violation"]:
            fn += 1
        elif status == "fail":
            fp += 1
        else:
            tn += 1
        rows.append({**exp, "got": status, "match": status == exp["expected"]})
    checked = [r for r in rows if "match" in r]
    return {
        "exact_match": f"{sum(r['match'] for r in checked)}/{len(checked)}",
        "violations_caught": f"{tp}/{tp + fn}", "false_fails": fp,
        "precision_fail": round(tp / (tp + fp), 3) if tp + fp else None,
        "recall": round(tp / (tp + fn), 3) if tp + fn else None,
        "rows": rows, "summary": result.summary,
    }


def score_facts(expected: list[Fact], read: list[Fact]) -> dict:
    """Reading accuracy: gold facts found with the right value (1% or 10 mm), wrong, missed, extra."""
    from app.units import is_length_unit, to_mm

    def same(a: Fact, b: Fact) -> bool:
        if is_length_unit(a.unit) and is_length_unit(b.unit):
            return abs(to_mm(float(a.value), a.unit) - to_mm(float(b.value), b.unit)) <= max(10, 0.01 * to_mm(float(a.value), a.unit))
        return a.value == b.value

    found = wrong = 0
    for g in expected:
        hits = [r for r in read if r.key() == g.key()]
        if any(same(g, r) for r in hits):
            found += 1
        elif hits:
            wrong += 1
    keys = {g.key() for g in expected}
    return {"gold": len(expected), "found_correct": found, "wrong_value": wrong,
            "missed": len(expected) - found - wrong, "extra_facts": sum(r.key() not in keys for r in read)}


def main() -> None:
    from app.llm import Claude, Ledger, load_env
    load_env(ROOT / ".env")
    have_key = bool(os.environ.get("ANTHROPIC_API_KEY"))
    claude = Claude(Ledger(DATA / "reports" / "usage.json", float(os.environ.get("BUDGET_USD", "4.00"))))
    report = {}
    truths = sorted((DATA / "synthetic").glob("*.truth.json")) + sorted((DATA / "ground_truth").glob("*.json"))
    for path in truths:
        truth = json.loads(path.read_text(encoding="utf-8"))
        pdf = next((p for p in DATA.rglob(truth["file"]) if p.suffix == ".pdf"), None)
        facts = [Fact(**f) for f in truth["facts"]]
        entry = {"synthetic": truth.get("synthetic", False),
                 "reader_path": reader_path(pdf) if pdf else "file not present",
                 "oracle": score(truth, facts) if truth.get("expected") else "no expected results"}
        if have_key and pdf:
            from app.ingest import read_file
            read, _cached, dropped = read_file(claude, DATA / "reports" / "cache", pdf.name, pdf.read_bytes())
            entry["reader"] = {"facts_read": len(read), "dropped": dropped,
                               "reading": score_facts(facts, read), "score": score(truth, read)}
        else:
            entry["reader"] = "skipped: no ANTHROPIC_API_KEY"
        report[truth["file"]] = entry
        o = entry["oracle"]
        print(f"\n{truth['file']}  [{'SYNTHETIC' if entry['synthetic'] else 'real'}]  reader path: {entry['reader_path']}")
        if isinstance(o, dict):
            print(f"  oracle: exact {o['exact_match']}, violations caught {o['violations_caught']}, "
                  f"false fails {o['false_fails']}")
            for r in o["rows"]:
                print(f"    {r['subject']:<22} expected {r['expected']:<9} got {r['got']}")
        r = entry["reader"]
        print(f"  reader: {r if isinstance(r, str) else (r['reading'], r['score']['exact_match'])}")
    (DATA / "reports").mkdir(parents=True, exist_ok=True)
    (DATA / "reports" / "eval.json").write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")


if __name__ == "__main__":
    main()
