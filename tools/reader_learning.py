"""Does the AI reader get better from corrections? Measured on drawings the corrections did NOT come from.

    .venv/Scripts/python tools/reader_learning.py            # needs ANTHROPIC_API_KEY; writes data/reports/reader_learning.json
    .venv/Scripts/python tools/reader_learning.py --dry-run  # shows the split and the cost estimate, no API calls

Method (2-fold, by file, so no drawing is ever both teacher and test):
1. Split the drawings that have a truth file into fold A and fold B.
2. Read every drawing with the AI reader, no lessons (baseline).
3. Turn the baseline mistakes on fold A into corrections, exactly as an engineer's "misread" answer
   would be stored (the truth file stands in for the engineer). Build lessons from them.
4. Read fold B again with those lessons, and score it. Then swap A and B.
5. Report baseline vs with-lessons on the held-out fold: correct, wrong value, missed, invented.

Honesty: the corrections come from the team's truth files, not from Meyer engineers. Say so.
Repeated runs are free: every AI read is cached by drawing + lessons.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app import ingest, lessons  # noqa: E402
from app.llm import Claude, Ledger, load_env  # noqa: E402
from app.models import Fact  # noqa: E402
from app.units import is_length_unit, to_mm  # noqa: E402

DATA = ROOT / "data"
REPORTS = DATA / "reports"
SUFFIXES = {".pdf", ".png", ".jpg", ".jpeg", ".webp"}


def drawings() -> list[tuple[Path, dict]]:
    found = []
    for truth_path in sorted(DATA.rglob("*.truth.json")) + sorted((DATA / "ground_truth").glob("*.json")):
        truth = json.loads(truth_path.read_text(encoding="utf-8"))
        file = next((p for p in DATA.rglob(truth["file"]) if p.suffix.lower() in SUFFIXES), None)
        if file and truth.get("facts") is not None:
            found.append((file, truth))
    return found


def same(a: Fact, b: Fact) -> bool:
    try:
        if is_length_unit(a.unit) and is_length_unit(b.unit):
            mm = to_mm(float(a.value), a.unit)
            return abs(mm - to_mm(float(b.value), b.unit)) <= max(10.0, 0.01 * mm)
        return float(a.value) == float(b.value)
    except (TypeError, ValueError):
        return str(a.value).strip().lower() == str(b.value).strip().lower()


def score(truth: dict, read: list[Fact]) -> tuple[dict, list[dict]]:
    """Counts, plus the mistakes as engineer-style "misread" rows."""
    gold = [Fact(**f) for f in truth["facts"]]
    keys = {g.key() for g in gold}
    counts = {"gold": len(gold), "correct": 0, "wrong_value": 0, "missed": 0, "invented": 0}
    mistakes = []
    for g in gold:
        hits = [r for r in read if r.key() == g.key()]
        if any(same(g, r) for r in hits):
            counts["correct"] += 1
        elif hits:
            counts["wrong_value"] += 1
            mistakes.append(_row(hits[0], g))
        else:
            counts["missed"] += 1
    for r in read:
        if r.key() not in keys and (r.subject.startswith("door") or r.property in {g.property for g in gold}):
            counts["invented"] += 1
            mistakes.append(_row(r, None))
    return counts, mistakes


def _row(read: Fact, right: Fact | None) -> dict:
    return {"decision": "reject", "synthetic": False,
            "read": {"subject": read.subject, "property": read.property, "value": read.value, "unit": read.unit,
                     "quote": read.source.quote, "file": read.source.file, "locator": read.source.locator},
            "corrected_value": None if right is None else right.value,
            "corrected_unit": "" if right is None else right.unit}


def total(entries: list[dict], key: str) -> dict:
    out: dict[str, int] = {}
    for e in entries:
        for k, v in e[key].items():
            out[k] = out.get(k, 0) + v
    return out


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    load_env(ROOT / ".env")
    items = drawings()
    folds = [items[0::2], items[1::2]]
    print(f"{len(items)} drawings with a truth file. Fold A: {len(folds[0])}, fold B: {len(folds[1])}.")
    print(f"AI reads needed: about {2 * len(items)} (baseline + with lessons). Cached reads are free.")
    if args.dry_run or not items:
        for name, fold in zip("AB", folds):
            print(f"  fold {name}: " + ", ".join(p.name for p, _ in fold))
        return
    if not os.environ.get("ANTHROPIC_API_KEY"):
        sys.exit("Set ANTHROPIC_API_KEY in .env first (BUDGET_USD caps the spend).")

    claude = Claude(Ledger(REPORTS / "usage.json", float(os.environ.get("BUDGET_USD", "4.00"))))
    cache = REPORTS / "cache"

    def read(path: Path, lesson_text: str = "") -> list[Fact]:
        facts, _cached, _dropped = ingest._read_with_ai(claude, cache, path.name, path.read_bytes(), None, lesson_text)
        return facts

    baseline = {path.name: score(truth, read(path)) for path, truth in items}
    report = {"method": "2-fold by file; corrections from team truth files standing in for engineer answers",
              "synthetic_drawings": sum(bool(t.get("synthetic")) for _, t in items), "folds": []}
    for teach, test, name in ((folds[0], folds[1], "A teaches B"), (folds[1], folds[0], "B teaches A")):
        rows = [m for path, _ in teach for m in baseline[path.name][1]]
        lesson_text = lessons.as_text(lessons.from_labels(rows))
        entries = []
        for path, truth in test:
            after, _ = score(truth, read(path, lesson_text)) if lesson_text else baseline[path.name]
            entries.append({"file": path.name, "baseline": baseline[path.name][0], "with_lessons": after})
        report["folds"].append({"name": name, "n_lessons": lesson_text.count("\n- ") + bool(lesson_text.startswith("- ")),
                                "lessons": lesson_text, "files": entries,
                                "baseline": total(entries, "baseline"), "with_lessons": total(entries, "with_lessons")})

    all_entries = [e for f in report["folds"] for e in f["files"]]
    report["held_out_total"] = {"baseline": total(all_entries, "baseline"), "with_lessons": total(all_entries, "with_lessons")}
    report["spend_usd"] = round(claude.ledger.spent, 4) if hasattr(claude, "ledger") else None
    REPORTS.mkdir(parents=True, exist_ok=True)
    (REPORTS / "reader_learning.json").write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")

    print(f"\n{'held-out drawings':20s} {'correct':>8s} {'wrong':>6s} {'missed':>7s} {'invented':>9s}")
    for label in ("baseline", "with_lessons"):
        t = report["held_out_total"][label]
        print(f"{label:20s} {t.get('correct', 0):>5d}/{t.get('gold', 0):<3d} {t.get('wrong_value', 0):>5d} "
              f"{t.get('missed', 0):>7d} {t.get('invented', 0):>9d}")
    print("\nCorrections came from the team's truth files, standing in for engineer answers.")
    print("Full detail: data/reports/reader_learning.json")


if __name__ == "__main__":
    main()
