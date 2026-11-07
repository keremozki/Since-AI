"""Benchmark the drawing reader and the confidence gate on hard SYNTHETIC deck plans.

Each sheet is generated with a known clear width for every door, written in mixed units, with labels
sometimes placed far from their door (closer to a neighbour), some doors without a width, door
schedules that disagree with the plan, rotated text, sheet-note units, and scanned sheets with OCR-style
character errors. The real reader (backend/app/drawing.py) reads each sheet, the real door check judges
it, and every fail is labelled against the truth: real fail (1) or misread (0).

These labels come from real reader mistakes, but on SYNTHETIC drawings. They are flagged synthetic,
and the app trains on them only with CONFIDENCE_ALLOW_SYNTHETIC=1.

    .venv/Scripts/python tools/reader_benchmark.py --sheets 60
    .venv/Scripts/python tools/reader_benchmark.py --sheets 60 --seed-pool ship-data/confidence
    .venv/Scripts/python tools/reader_benchmark.py --sheets 3 --keep data/synthetic/bench   # look at the PDFs
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pymupdf

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.checks import check_door_clear_width  # noqa: E402
from app.confidence import (MIN_LABELS, TAU, LabelPool, cross_validated, features, new_model,  # noqa: E402
                            scores_at, shown_status, to_matrix)
from app.drawing import read_pdf  # noqa: E402
from app.models import Rule, Status  # noqa: E402
from app.profiles import PROFILES  # noqa: E402
from app.store import FactStore  # noqa: E402

DOOR_RULE = Rule(id="PVAG-V404.2.3", title="Door clear width", area="Accessibility", source="PVAG V404.2.3 (proposed)",
                 check="door_clear_width", params={"min_in": 32, "min_mm": 815})
LIMIT_MM = 32 * 25.4
OCR_SWAPS = {"3": "8", "8": "3", "1": "7", "6": "5", "0": "6"}


def width_text(mm: float, style: str) -> str:
    inches = mm / 25.4
    if style == "mm":
        return f"{round(mm / 5) * 5:.0f} mm"
    if style == "bare":
        return f"{round(mm / 5) * 5:.0f}"
    if style == "ftin":
        whole = round(inches * 2) / 2
        ft, rest = divmod(whole, 12)
        return f"{int(ft)}'-{rest:g}\"".replace(".5", " 1/2")
    eighths = round(inches * 8)
    whole, frac = divmod(eighths, 8)
    if frac == 0:
        return f'{whole}"'
    from math import gcd
    g = gcd(frac, 8)
    return f'{whole} {frac // g}/{8 // g}"'


def as_written_mm(text: str) -> float:
    """What the label literally says, in mm, for scoring against the reader."""
    from app.drawing import find_lengths
    found = find_lengths(text, "mm") or find_lengths("CL OPG " + text, "mm")
    return found[0].value * {"mm": 1, "cm": 10, "m": 1000, "in": 25.4}[found[0].unit] if found else float("nan")


def make_sheet(rng: np.random.Generator, index: int) -> tuple[bytes, dict]:
    doc = pymupdf.open()
    page = doc.new_page(width=1190, height=842)
    scanned = rng.random() < 0.2
    sheet_mm = rng.random() < 0.25
    if scanned:
        # A grey picture under the text, the way a scanned and OCR'd sheet looks.
        pix = pymupdf.Pixmap(pymupdf.csGRAY, pymupdf.IRect(0, 0, 119, 84), False)
        pix.set_rect(pix.irect, (235,))
        page.insert_image(page.rect, pixmap=pix)
    page.insert_text((620, 760), f"SYNTHETIC BENCHMARK SHEET {index} - NOT A REAL SHIP", fontsize=11)
    if rng.random() < 0.7:
        page.insert_text((620, 776), "SCALE 1:50", fontsize=9)
    if sheet_mm:
        page.insert_text((620, 792), "ALL DIMENSIONS IN MM", fontsize=9)
    doors, number0 = [], 100 * (index % 9 + 1)
    cols, rows = int(rng.integers(4, 7)), int(rng.integers(2, 4))
    dx, dy = 1000 / cols, 560 / rows
    for r in range(rows):
        for c in range(cols):
            number = str(number0 + r * cols + c + 1)
            x, y = 80 + c * dx, 120 + r * dy
            # Widths cluster around the limit, where misreads matter most.
            true_mm = float(np.clip(rng.normal(LIMIT_MM + 20, 70), 650, 1100))
            style = "bare" if sheet_mm and rng.random() < 0.6 else str(rng.choice(["in", "in", "mm", "ftin"]))
            text = width_text(true_mm, style)
            # The truth is what the drawing states (rounded to how it is written), not the unrounded number.
            true_mm = as_written_mm(text)
            shown = rng.random() > 0.08
            rotate = 90 if rng.random() < 0.1 else 0
            page.draw_rect(pymupdf.Rect(x, y, x + dx * 0.8, y + dy * 0.6), color=(0, 0, 0), width=0.6)
            page.insert_text((x + 8, y + 18), f"CABIN {number}", fontsize=8)
            tag_at = (x + dx * 0.35, y + dy * 0.6 + 12)
            page.insert_text(tag_at, f"D{number}", fontsize=9)
            label = f"CL OPG {text}"
            written = text
            if scanned and rng.random() < 0.4:
                digits = [i for i, ch in enumerate(label) if ch in OCR_SWAPS]
                if digits:
                    i = int(rng.choice(digits))
                    label = label[:i] + OCR_SWAPS[label[i]] + label[i + 1:]
                    written = label[len("CL OPG "):]
            if shown:
                # Usually right under the tag; sometimes pushed toward the next door.
                far = rng.random() < 0.15
                off = (dx * rng.uniform(0.45, 0.7), 4) if far else (0, -12 if rng.random() < 0.5 else 12)
                page.insert_text((tag_at[0] + off[0], tag_at[1] + off[1]), label, fontsize=8, rotate=rotate)
            doors.append({"number": number, "true_mm": true_mm, "written": written if shown else None,
                          "label_written_mm": as_written_mm(written) if shown else None,
                          "far_label": bool(shown and far), "scanned": scanned})
    schedule = [d for d in doors if rng.random() < 0.15]
    if schedule:
        page.insert_text((900, 60), "DOOR SCHEDULE", fontsize=9)
        for k, d in enumerate(schedule):
            agree = rng.random() < 0.7
            mm = d["true_mm"] if agree else d["true_mm"] + float(rng.choice([-60, 60]))
            text = width_text(mm, "in")
            d["schedule_mm"] = as_written_mm(text)
            if agree:
                d["true_mm"] = d["schedule_mm"]  # one stated value, in two places
            page.insert_text((900, 76 + 12 * k), f"D{d['number']}    {text}", fontsize=8)
    return doc.tobytes(), {"sheet": index, "scanned": scanned, "sheet_mm": sheet_mm, "doors": doors}


def judge_sheet(data: bytes, truth: dict) -> tuple[list[dict], dict]:
    read = read_pdf(data, f"bench_{truth['sheet']}.pdf")
    store = FactStore(read.facts)
    findings = check_door_clear_width(DOOR_RULE, store, PROFILES["passenger-test"])
    by_number = {d["number"]: d for d in truth["doors"]}
    rows, tally = [], {"doors": len(truth["doors"]), "true_fails": sum(d["true_mm"] < LIMIT_MM for d in truth["doors"]),
                       "fail": 0, "pass": 0, "conflict": 0, "cant_tell": 0, "false_pass": 0, "misread_fail": 0}
    for f in findings:
        number = f.subject.split(":")[-1]
        door = by_number.get(number)
        if door is None:
            continue
        tally[f.status.value] += 1
        real_fail = door["true_mm"] < LIMIT_MM
        if f.status == Status.PASS and real_fail:
            tally["false_pass"] += 1
        if f.status == Status.FAIL and f.evidence is not None:
            tally["misread_fail"] += int(not real_fail)
            rows.append({"features": features(f, store), "label": int(real_fail), "sheet": truth["sheet"],
                         "door": number, "read_mm": f.evidence.measured, "true_mm": door["true_mm"]})
    return rows, tally


def curve(rows: list[dict], test: list[dict], tau: float) -> list[dict]:
    y_test = np.array([r["label"] for r in test])
    points = []
    for n in range(10, len(rows) + 1, 10):
        train = rows[:n]
        y = np.array([r["label"] for r in train])
        model = new_model().fit(to_matrix([r["features"] for r in train]), y) if n >= MIN_LABELS and len(set(y)) == 2 else None
        shown = []
        for r in test:
            p = None if model is None else float(model.predict_proba(to_matrix([r["features"]]))[0, 1])
            shown.append(shown_status(Status.FAIL, r["features"]["extraction_confidence"], p, tau)[0] == Status.FAIL)
        s = scores_at(y_test, np.array(shown, dtype=float), 0.5)
        points.append({"labels": n, "mode": "model" if model is not None else "cold_start", **s})
    return points


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--sheets", type=int, default=60)
    parser.add_argument("--seed", type=int, default=1)
    parser.add_argument("--keep", type=Path, help="also write the generated PDFs and truth here")
    parser.add_argument("--seed-pool", type=Path, help="write the labels (flagged synthetic) to this confidence folder")
    args = parser.parse_args()
    rng = np.random.default_rng(args.seed)
    rows, totals = [], {}
    for i in range(args.sheets):
        data, truth = make_sheet(rng, i)
        if args.keep:
            args.keep.mkdir(parents=True, exist_ok=True)
            (args.keep / f"bench_{i:03d}.pdf").write_bytes(data)
            (args.keep / f"bench_{i:03d}.truth.json").write_text(json.dumps({"synthetic": True, **truth}, indent=1))
        sheet_rows, tally = judge_sheet(data, truth)
        rows += sheet_rows
        for k, v in tally.items():
            totals[k] = totals.get(k, 0) + v

    y = np.array([r["label"] for r in rows])
    print(f"SYNTHETIC benchmark: {args.sheets} sheets, {totals['doors']} doors, {totals['true_fails']} truly too narrow")
    print(f"  results: {totals['fail']} fail, {totals['pass']} pass, {totals['conflict']} conflict, {totals['cant_tell']} can't tell")
    print(f"  FALSE PASSES (worst case): {totals['false_pass']}")
    print(f"  fails that are misreads: {totals['misread_fail']} of {totals['fail']}  -> raw precision {y.mean():.2f}")

    split = int(len(rows) * 0.6)
    order = np.random.default_rng(0).permutation(len(rows))
    stream, test = [rows[i] for i in order[:split]], [rows[i] for i in order[split:]]
    points = curve(stream, test, TAU)
    print(f"\nLearning curve on held-out fails (tau {TAU}):")
    print("  labels  mode        precision  false-alarm  recall  coverage")
    for p in points:
        print(f"  {p['labels']:6d}  {p['mode']:10s}  {p['precision'] or 0:9.2f}  {p['false_alarm_rate'] or 0:11.2f}  {p['recall'] or 0:6.2f}  {p['coverage']:8.2f}")
    p_oof = cross_validated(to_matrix([r["features"] for r in rows]), y)
    tau_table = [scores_at(y, p_oof, t) for t in (0.5, 0.6, 0.7, 0.8, 0.9)] if p_oof is not None else []
    if tau_table:
        print("\nCross-validated threshold table (all labels):")
        for s in tau_table:
            print(f"  tau {s['tau']:.1f}: precision {s['precision'] or 0:.2f}  recall {s['recall'] or 0:.2f}  false-alarm {s['false_alarm_rate'] or 0:.2f}")
    model = new_model().fit(to_matrix([r["features"] for r in rows]), y) if len(set(y)) == 2 else None
    weights = dict(zip(rows[0]["features"], map(float, model[-1].coef_[0]))) if model else {}
    report = {"SYNTHETIC": True, "note": "Real reader and checks, synthetic drawings. Not a measure of accuracy on real ships.",
              "sheets": args.sheets, "totals": totals, "learning_curve": points, "tau_cross_validated": tau_table,
              "weights": weights}
    (ROOT / "data" / "reports" / "reader_benchmark_SYNTHETIC.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print("\nReport: data/reports/reader_benchmark_SYNTHETIC.json")

    if args.seed_pool:
        pool = LabelPool(args.seed_pool / "labels.jsonl")
        now = datetime.now(timezone.utc).isoformat(timespec="seconds")
        for r in rows:
            pool.add({"key": f"benchmark|{args.seed}|{r['sheet']}|{r['door']}", "label": r["label"],
                      "decision": "accept" if r["label"] else "reject", "features": r["features"], "rule_id": DOOR_RULE.id,
                      "subject": f"door-number:{r['door']}", "measured": f"{r['read_mm']:.0f} mm", "corrected_value": None,
                      "corrected_unit": "", "note": "synthetic benchmark, labelled from truth", "synthetic": True, "created": now})
        print(f"Wrote {len(rows)} SYNTHETIC labels to {pool.path} (used only with CONFIDENCE_ALLOW_SYNTHETIC=1).")


if __name__ == "__main__":
    main()
