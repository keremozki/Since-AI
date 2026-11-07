"""Generate synthetic GA deck plans (vector PDF) with known, injected accessibility faults.

Every plan gets a truth file in data/synthetic/: the facts a perfect reader would return
(same shape as app.models.Fact) and the result we expect per object. All of it is SYNTHETIC.

Limits come only from verified rule texts in docs/rules (PVAG, proposed, not in force):
  door clear width   >= 32 in (815 mm)   PVAG V404.2.3  (checked by the app: door_clear_width)
  walking surface    >= 36 in (915 mm)   PVAG V403.5.1  (no check in the app yet)
  ramp running slope <= 1:12             PVAG V405.2    (no check in the app yet)

Usage: python tools/make_synthetic_ga.py   (writes data/synthetic/*.pdf and *.truth.json)
"""
from __future__ import annotations

import json
from pathlib import Path

from reportlab.lib.pagesizes import A3, landscape
from reportlab.pdfgen import canvas

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "synthetic"
DOOR_RULE, CORRIDOR_RULE, RAMP_RULE = "PVAG-V404.2.3", "PVAG-V403.5.1", "PVAG-V405.2"
SCALE = 50  # drawing scale 1:50 -> 1 mm on paper = 50 mm real
MM = 72 / 25.4  # points per paper mm


def to_in(text: str) -> float | None:
    """Inches from the label text, for the expected result only (the app does its own maths)."""
    t = text.strip()
    if t.endswith("mm"):
        return float(t[:-2]) / 25.4
    if "'" in t:
        ft, rest = t.split("'")
        rest = rest.strip("-\" ")
        return float(ft) * 12 + (float(rest) if rest else 0)
    t = t.rstrip('"')
    if " " in t:
        whole, frac = t.split(" ")
        n, d = frac.split("/")
        return float(whole) + float(n) / float(d)
    return float(t)


def unit_value(text: str) -> tuple[float, str]:
    """How a perfect reader states it: one number and one unit, as the app's reader prompt asks."""
    t = text.strip()
    if t.endswith("mm"):
        return float(t[:-2]), "mm"
    return round(to_in(t), 4), "in"


PLANS = [
    {
        "name": "syn_01_mixed",
        "title": "SYNTHETIC PASSENGER DECK 3 - MIXED",
        "doors": [  # number, label text or None (width not shown), note
            ("301", '34"', "compliant"), ("302", '30"', "INJECTED: too narrow"),
            ("303", '36"', "compliant"), ("304", '31"', "INJECTED: too narrow"),
            ("305", '33 1/2"', "compliant"), ("306", '28"', "INJECTED: too narrow"),
            ("307", '32"', "compliant, exactly at limit"), ("308", None, "INJECTED: width not shown"),
        ],
        "corridors": [("C3-1", '42"', "compliant"), ("C3-2", '34"', "INJECTED: too narrow")],
        "ramps": [("R3-1", "1:12", "compliant, exactly at limit"), ("R3-2", "1:10", "INJECTED: too steep")],
        "schedule": {},
    },
    {
        "name": "syn_02_units_conflict",
        "title": "SYNTHETIC PASSENGER DECK 4 - UNITS AND CONFLICT",
        "doors": [
            ("401", "815 mm", "compliant (815 mm is the rule's printed metric figure)"),
            ("402", "800 mm", "INJECTED: too narrow"),
            ("403", "2'-8\"", "compliant (32 in)"), ("404", "2'-6\"", "INJECTED: too narrow"),
            ("405", '31 7/8"', "INJECTED: too narrow by 1/8 in"),
            ("406", "900 mm", "compliant"), ("407", '34"', "INJECTED: schedule says 30 in -> conflict"),
            ("408", '36"', "compliant"),
        ],
        "corridors": [("C4-1", "1000 mm", "compliant")],
        "ramps": [],
        "schedule": {"407": '30"', "408": '36"'},  # door schedule table on the same sheet
    },
    {
        "name": "syn_03_compliant_control",
        "title": "SYNTHETIC PASSENGER DECK 5 - COMPLIANT CONTROL",
        "doors": [("501", '32"', "compliant"), ("502", '34"', "compliant"), ("503", '36"', "compliant"),
                  ("504", "865 mm", "compliant"), ("505", "3'-0\"", "compliant"), ("506", '33"', "compliant")],
        "corridors": [("C5-1", '48"', "compliant"), ("C5-2", '36"', "compliant, exactly at limit")],
        "ramps": [("R5-1", "1:14", "compliant")],
        "schedule": {},
    },
]


def draw_plan(plan: dict, pdf_path: Path) -> list[dict]:
    """Draw the plan; return the facts a perfect reader would report, with their locators."""
    w, h = landscape(A3)
    c = canvas.Canvas(str(pdf_path), pagesize=(w, h))
    c.setTitle(plan["title"] + " (synthetic test data)")
    facts: list[dict] = []
    # frame, hull outline, title block
    c.setLineWidth(1.2)
    c.rect(15 * MM, 15 * MM, w - 30 * MM, h - 30 * MM)
    c.setLineWidth(2)
    x0, y0, x1, y1 = 40 * MM, 80 * MM, w - 80 * MM, h - 60 * MM
    p = c.beginPath()
    p.moveTo(x0, y0); p.lineTo(x1, y0); p.curveTo(x1 + 50 * MM, y0, x1 + 60 * MM, (y0 + y1) / 2, x1 + 60 * MM, (y0 + y1) / 2)
    p.curveTo(x1 + 60 * MM, (y0 + y1) / 2, x1 + 50 * MM, y1, x1, y1); p.lineTo(x0, y1); p.close()
    c.drawPath(p)
    c.setFont("Helvetica-Bold", 14)
    c.drawString(w - 200 * MM, 35 * MM, plan["title"])
    c.setFont("Helvetica", 9)
    c.drawString(w - 200 * MM, 29 * MM, "SYNTHETIC TEST DRAWING - NOT A REAL SHIP - SINCE AI HACKATHON 2026")
    c.drawString(w - 200 * MM, 24 * MM, f"SCALE 1:{SCALE}    ALL DOOR WIDTHS ARE CLEAR OPENINGS")
    # scale bar: 5 m real = 100 mm paper at 1:50
    c.setLineWidth(1)
    bx, by = 30 * MM, 30 * MM
    for i in range(5):
        c.setFillGray(0 if i % 2 == 0 else 1)
        c.rect(bx + i * 20 * MM, by, 20 * MM, 3 * MM, fill=1)
    c.setFillGray(0)
    c.drawString(bx, by + 5 * MM, "0")
    c.drawString(bx + 100 * MM - 6, by + 5 * MM, "5 m")
    # central corridor
    cy0, cy1 = (y0 + y1) / 2 - 12 * MM, (y0 + y1) / 2 + 12 * MM
    c.setLineWidth(1.5)
    c.line(x0, cy0, x1, cy0)
    c.line(x0, cy1, x1, cy1)
    # cabins with doors on the corridor
    doors = plan["doors"]
    n_top = (len(doors) + 1) // 2
    pitch = (x1 - x0) / max(n_top, 1)
    for i, (number, label, _note) in enumerate(doors):
        top = i < n_top
        k = i if top else i - n_top
        cx = x0 + k * pitch
        cyw = cy1 if top else cy0
        c.setLineWidth(1)
        c.line(cx, cyw, cx, y1 if top else y0)  # cabin wall
        c.setFont("Helvetica", 8)
        c.drawString(cx + 6 * MM, (y1 - 15 * MM) if top else (y0 + 10 * MM), f"CABIN {number}")
        # door opening with swing arc
        dx = cx + pitch / 2 - 8 * MM
        gap = 16 * MM
        c.setStrokeGray(1); c.setLineWidth(3); c.line(dx, cyw, dx + gap, cyw); c.setStrokeGray(0); c.setLineWidth(0.8)
        sign = 1 if top else -1
        c.line(dx, cyw, dx, cyw + sign * gap)
        c.arc(dx - gap, cyw - gap, dx + gap, cyw + gap, startAng=0 if top else -90, extent=90)
        ty = cyw + sign * (gap + 4 * MM)
        c.setFont("Helvetica-Bold", 9)
        c.drawString(dx, ty, f"D{number}")
        if label:
            c.setFont("Helvetica", 8)
            c.drawString(dx, ty + sign * 4 * MM, f"CL OPG {label}")
            value, unit = unit_value(label)
            facts.append({"subject": f"door-number:{number}", "property": "clear_width", "value": value, "unit": unit,
                          "source": {"kind": "document", "file": pdf_path.name, "locator": "page 1, deck plan",
                                     "quote": f"D{number} CL OPG {label}"}, "confidence": "high", "location": None})
    # corridor and ramp labels (no app check yet, kept for future checks)
    c.setFont("Helvetica", 8)
    for j, (cid, width, _n) in enumerate(plan["corridors"]):
        c.drawString(x0 + 10 * MM + j * 120 * MM, (cy0 + cy1) / 2 - 1 * MM, f"CORRIDOR {cid}  CLEAR WIDTH {width}")
    for j, (rid, slope, _n) in enumerate(plan["ramps"]):
        rx = x1 - 60 * MM - j * 50 * MM
        c.rect(rx, cy1 + 2 * MM, 30 * MM, 8 * MM)
        c.drawString(rx + 1 * MM, cy1 + 5 * MM, f"RAMP {rid} {slope}")
    # optional door schedule table
    if plan["schedule"]:
        tx, ty = 120 * MM, h - 22 * MM
        c.setFont("Helvetica-Bold", 9)
        c.drawString(tx, ty, "DOOR SCHEDULE")
        c.setFont("Helvetica", 8)
        c.drawString(tx, ty - 5 * MM, "DOOR    CLEAR OPENING")
        for r, (num, lab) in enumerate(plan["schedule"].items()):
            c.drawString(tx, ty - (10 + 5 * r) * MM, f"D{num}    {lab}")
            value, unit = unit_value(lab)
            facts.append({"subject": f"door-number:{num}", "property": "clear_width", "value": value, "unit": unit,
                          "source": {"kind": "document", "file": pdf_path.name, "locator": "page 1, door schedule",
                                     "quote": f"D{num}    {lab}"}, "confidence": "high", "location": None})
    c.showPage()
    c.save()
    return facts


def expected_results(plan: dict) -> list[dict]:
    rows = []
    sched = plan["schedule"]
    for number, label, note in plan["doors"]:
        if label is None:
            status = "cant_tell"
        elif number in sched and abs(to_in(sched[number]) - to_in(label)) * 25.4 > 10:
            status = "conflict"
        else:
            status = "pass" if to_in(label) * 25.4 >= 32 * 25.4 - 1e-6 else "fail"
        rows.append({"subject": f"door-number:{number}", "rule_id": DOOR_RULE, "expected": status,
                     "violation": status != "pass", "note": note, "app_has_check": True})
    for cid, width, note in plan["corridors"]:
        ok = to_in(width) >= 36 - 1e-6
        rows.append({"subject": f"corridor:{cid}", "rule_id": CORRIDOR_RULE, "expected": "pass" if ok else "fail",
                     "violation": not ok, "note": note, "app_has_check": False, "stated": width})
    for rid, slope, note in plan["ramps"]:
        run = float(slope.split(":")[1])
        ok = run >= 12
        rows.append({"subject": f"ramp:{rid}", "rule_id": RAMP_RULE, "expected": "pass" if ok else "fail",
                     "violation": not ok, "note": note, "app_has_check": False, "stated": slope})
    return rows


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    for plan in PLANS:
        pdf = OUT / f"{plan['name']}.pdf"
        facts = draw_plan(plan, pdf)
        truth = {
            "synthetic": True,
            "file": pdf.name,
            "profile": {"ship_type": "passenger", "passengers": 400, "flag": "US",
                        "note": "Synthetic passenger ship; PVAG V201.1.1 scope (> 150 passengers) is met."},
            "limits": {DOOR_RULE: "32 in (815 mm) min", CORRIDOR_RULE: "36 in (915 mm) min", RAMP_RULE: "1:12 max"},
            "facts": facts,
            "expected": expected_results(plan),
        }
        (OUT / f"{plan['name']}.truth.json").write_text(json.dumps(truth, indent=2), encoding="utf-8")
        print("wrote", pdf.name, len(facts), "facts,", sum(r["violation"] for r in truth["expected"]), "violations")


if __name__ == "__main__":
    main()
