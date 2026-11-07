"""Write the offline demo set: one small SYNTHETIC drawing per finding type, no API and no network needed.

    .venv/Scripts/python tools/make_offline_demo.py     -> data/demo_offline_SYNTHETIC/

Upload a file in the app with the "passenger-test" profile. Vector PDFs are read by code
(backend/app/drawing.py), so no API key is used. Limits (PVAG, proposed, not in force):
door 32 in V404.2.3, corridor 36 in (32 in under exceptions) V403.5.1, ramp 1:12 V405.2.
"""
from __future__ import annotations

import json
from pathlib import Path

import pymupdf

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "demo_offline_SYNTHETIC"
DOOR, CORRIDOR, RAMP = "PVAG-V404.2.3", "PVAG-V403.5.1", "PVAG-V405.2"

# Facts a perfect reader returns: (subject, property, value, unit).
FACTS = {
    "SYNTHETIC_demo_1_PASS": [("door-number:101", "clear_width", 34, "in"), ("corridor:C1", "clear_width", 1200, "mm"),
                              ("ramp:R1", "slope_run_per_rise", 14, "")],
    "SYNTHETIC_demo_2_FAIL": [("door-number:201", "clear_width", 30, "in"), ("corridor:C2", "clear_width", 30, "in"),
                              ("ramp:R2", "rise", 150, "mm"), ("ramp:R2", "run", 1500, "mm")],
    "SYNTHETIC_demo_3_CANT_TELL": [("corridor:C3", "clear_width", 34, "in")],
    "SYNTHETIC_demo_4_CONFLICT": [("door-number:401", "clear_width", 34, "in"), ("door-number:401", "clear_width", 30, "in")],
}

# name -> (texts as (text, x, y, rotate), expected results). Expected comes from the written values
# and the rule limits above, not from running the checker.
DEMOS = {
    "SYNTHETIC_demo_1_PASS": (
        [("D101", 80, 100, 0), ('CL OPG 34"', 80, 112, 0),
         ("CORRIDOR C1  CLEAR WIDTH 1200 mm", 80, 220, 0),
         ("RAMP R1  SLOPE 1:14", 80, 320, 0)],
        [("door-number:101", DOOR, "pass", "34 in >= 32 in"),
         ("corridor:C1", CORRIDOR, "pass", "1200 mm >= 36 in (914.4 mm)"),
         ("ramp:R1", RAMP, "pass", "1:14 is shallower than 1:12")]),
    "SYNTHETIC_demo_2_FAIL": (
        [("D201", 80, 100, 0), ('CL OPG 30"', 80, 112, 0),
         ("CORRIDOR C2", 80, 220, 0), ("CLR WIDTH 2'-6\"", 80, 232, 0),
         ("RAMP R2", 80, 320, 0), ("RISE 150 mm  RUN 1500 mm", 80, 332, 0)],
        [("door-number:201", DOOR, "fail", "30 in < 32 in"),
         ("corridor:C2", CORRIDOR, "fail", "30 in < 32 in, below even the exception width"),
         ("ramp:R2", RAMP, "fail", "1:10 is steeper than 1:12")]),
    "SYNTHETIC_demo_3_CANT_TELL": (
        [("D301", 80, 100, 0),
         ('CORRIDOR C3  CLEAR WIDTH 34"', 80, 220, 0),
         ("RAMP R3", 80, 320, 0), ("SLOPE 1:12", 200, 400, 90)],
        [("door-number:301", DOOR, "cant_tell", "door tagged, no width written"),
         ("corridor:C3", CORRIDOR, "cant_tell", "34 in: under 36 in, but V403.5.1 exceptions allow 32 in for short segments"),
         ("ramp:R3", RAMP, "cant_tell", "slope text is rotated away from the ramp label, so it isn't used")]),
    "SYNTHETIC_demo_4_CONFLICT": (
        [("D401", 80, 100, 0), ('CL OPG 34"', 80, 112, 0),
         ("DOOR SCHEDULE", 600, 80, 0), ('D401    30"', 600, 94, 0)],
        [("door-number:401", DOOR, "conflict", "plan says 34 in, door schedule says 30 in")]),
}


def write_demo(name: str, texts: list, expected: list, out: Path) -> None:
    doc = pymupdf.open()
    page = doc.new_page(width=842, height=595)
    doc.set_metadata({"title": f"{name} - SYNTHETIC demo drawing", "subject": "SYNTHETIC - not a real ship",
                      "keywords": "SYNTHETIC", "creator": "tools/make_offline_demo.py"})
    page.draw_rect(pymupdf.Rect(15, 15, 827, 580), color=(0, 0, 0), width=1)
    page.insert_text((420, 540), f"{name.replace('_', ' ')} - NOT A REAL SHIP", fontsize=10)
    page.insert_text((420, 556), "SINCE AI HACKATHON 2026 - SYNTHETIC DEMO DATA    SCALE 1:50", fontsize=8)
    for text, x, y, rotate in texts:
        page.insert_text((x, y), text, fontsize=9, rotate=rotate)
    (out / f"{name}.pdf").write_bytes(doc.tobytes())
    truth = {"synthetic": True, "file": f"{name}.pdf", "profile_in_app": "passenger-test",
             "profile": {"ship_type": "passenger", "passengers": 200, "flag": "US"},
             "facts": [{"subject": su, "property": pr, "value": v, "unit": u} for su, pr, v, u in FACTS[name]],
             "expected": [{"subject": s, "rule_id": r, "expected": e, "note": n, "violation": e != "pass"}
                                       for s, r, e, n in expected]}
    (out / f"{name}.truth.json").write_text(json.dumps(truth, indent=2), encoding="utf-8")


def main(out: Path = OUT) -> None:
    out.mkdir(parents=True, exist_ok=True)
    for name, (texts, expected) in DEMOS.items():
        write_demo(name, texts, expected, out)
        print("wrote", name)


if __name__ == "__main__":
    main()
