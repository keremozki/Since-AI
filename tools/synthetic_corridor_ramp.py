"""Seeded SYNTHETIC deck sheets with corridors and ramps, and their truth files.

Called from tools/make_synthetic_ga.py --corridor-ramp-seed N. Every file name, PDF metadata field and
truth file says SYNTHETIC. Nothing here is a real ship.

Limits, from the rule texts in docs/rules/pvag/all-ship-types/accessibility.md (PVAG, proposed, not in force):
  V403.5.1  walking surface clear width 36 in (915 mm) minimum. Exceptions 1 and 2 allow 32 in (815 mm)
            for short segments or small decks, so 32 to under 36 in is "can't tell" without that data.
  V405.2    ramp running slope not steeper than 1:12.

Labels use the styles the reader already supports for door widths (inches with fractions, feet-inches,
mm, m, bare numbers under an "ALL DIMENSIONS IN MM" note) and the same table layout as the door
schedule. The truth is worked out from the generator's own inputs with exact fractions, never from the
checker. Cases per object type: compliant, violating, right at and just either side of each limit, and
unreadable (label missing, label rotated away from the tag, number without a unit) -> can't tell.
"""
from __future__ import annotations

import json
import random
from fractions import Fraction
from pathlib import Path

import pymupdf

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "synthetic"
CORRIDOR_RULE, RAMP_RULE = "PVAG-V403.5.1", "PVAG-V405.2"
SHEETS = 6

IN_MM = Fraction(254, 10)
CORRIDOR_MIN = 36 * IN_MM       # V403.5.1
CORRIDOR_REDUCED = 32 * IN_MM   # V403.5.1 exceptions 1 and 2
RAMP_MAX = Fraction(1, 12)      # V405.2

# style -> (mm per unit, smallest step the style writes)
STYLES = {"in": (IN_MM, Fraction(1, 8)), "ftin": (IN_MM, Fraction(1, 2)), "mm": (Fraction(1), Fraction(1)),
          "m": (Fraction(1000), Fraction(1, 100)), "bare": (Fraction(1), Fraction(5))}
CORRIDOR_CASES = ["compliant", "compliant", "violating", "violating", "exception_band", "exactly_36",
                  "just_above_36", "just_below_36", "just_above_32", "just_below_32",
                  "unreadable_missing", "unreadable_rotated", "unreadable_ambiguous_unit"]
RAMP_CASES = ["compliant", "compliant", "violating", "violating", "exactly_1_12", "just_steeper", "just_shallower",
              "unreadable_missing", "unreadable_rotated", "unreadable_ambiguous_unit"]


def _round_to(units: Fraction, step: Fraction, how: str) -> Fraction:
    q = units / step
    n = q.numerator // q.denominator if how == "down" else -((-q.numerator) // q.denominator)
    return n * step


def length_text(units: Fraction, style: str) -> str:
    """The label text for a length given in the style's own unit. Exact: units is a multiple of the step."""
    if style == "mm":
        return f"{units:.0f} mm"
    if style == "bare":
        return f"{units:.0f}"
    if style == "m":
        return f"{float(units):.2f} m"
    whole, frac = divmod(units, 1)
    frac_text = f" {frac.numerator}/{frac.denominator}" if frac else ""
    if style == "in":
        return f'{whole}{frac_text}"'
    ft, rest = divmod(whole, 12)
    return f"{ft}'-{rest}{frac_text}\""


def truth_unit(style: str) -> str:
    """How a perfect reader states the unit: feet-and-inches become inches, a bare number takes the sheet unit."""
    return {"in": "in", "ftin": "in", "mm": "mm", "bare": "mm", "m": "m"}[style]


def corridor_value(rng: random.Random, case: str, style: str) -> Fraction:
    """A width in the style's own unit, exactly writable in that style."""
    factor, step = STYLES[style]
    if case in ("exactly_36", "just_above_36", "just_below_36", "just_above_32", "just_below_32"):
        limit = (CORRIDOR_MIN if "36" in case else CORRIDOR_REDUCED) / factor
        if case == "exactly_36":
            assert limit % step == 0, "exactly_36 needs an inch style"
            return limit
        if "above" in case:
            v = _round_to(limit, step, "up")
            return v + step if v == limit else v
        v = _round_to(limit, step, "down")
        return v - step if v == limit else v
    lo, hi = {"compliant": (38, 60), "violating": (24, 31), "exception_band": (32.5, 35.5)}.get(case, (24, 60))
    return _round_to(Fraction(rng.uniform(lo, hi)) * IN_MM / factor, step, "down")


def corridor_expected(width_mm: Fraction) -> str:
    if width_mm >= CORRIDOR_MIN:
        return "pass"
    return "cant_tell" if width_mm >= CORRIDOR_REDUCED else "fail"


def ramp_value(rng: random.Random, case: str, style: str) -> tuple[Fraction, ...]:
    """(N,) for a written 1:N slope, or (rise, run) in the style's unit."""
    if style == "ratio":
        n = {"exactly_1_12": Fraction(12), "just_steeper": Fraction(23, 2), "just_shallower": Fraction(25, 2),
             "compliant": Fraction(rng.choice([13, 14, 15, 16, 18, 20])),
             "violating": Fraction(rng.choice([6, 8, 9, 10]))}.get(case, Fraction(rng.choice([8, 12, 16])))
        return (n,)
    if style == "riserun_in":
        rise = Fraction(rng.choice([4, 5, 6]))
        step = Fraction(1)
    else:
        rise = Fraction(rng.choice([120, 150, 180]))
        step = Fraction(10)
    run = {"exactly_1_12": rise * 12, "just_steeper": rise * 12 - step, "just_shallower": rise * 12 + step,
           "compliant": rise * rng.choice([13, 14, 16]), "violating": rise * rng.choice([8, 9, 10])}.get(case, rise * 12)
    return (rise / 1000, run / 1000) if style == "riserun_m" else (rise, run)


def ramp_label(style: str, value: tuple[Fraction, ...]) -> tuple[str, list[dict]]:
    """The written label and the facts a perfect reader would report (subject and source added later)."""
    if style == "ratio":
        n = value[0]
        text = f"1:{n.numerator}" if n.denominator == 1 else f"1:{float(n):g}"
        return f"SLOPE {text}", [{"property": "slope_run_per_rise", "value": float(n), "unit": ""}]
    rise, run = value
    if style == "riserun_in":
        rise_text, run_text, unit = length_text(rise, "in"), length_text(run, "ftin"), "in"
    elif style == "riserun_m":
        rise_text, run_text, unit = length_text(rise, "m"), length_text(run, "m"), "m"
    else:
        rise_text, run_text, unit = length_text(rise, "mm"), length_text(run, "mm"), "mm"
    return f"RISE {rise_text}  RUN {run_text}", [{"property": "rise", "value": float(rise), "unit": unit},
                                                 {"property": "run", "value": float(run), "unit": unit}]


def plan_cases(rng: random.Random, sheets: int) -> list[dict]:
    """Every case at least once per set, spread over the sheets. Odd-numbered sheets carry
    'ALL DIMENSIONS IN MM': bare numbers go only there, ambiguous-unit cases only on the others."""
    if sheets < 2:
        raise ValueError("A set needs at least 2 sheets: one with a sheet unit note and one without.")
    per_sheet = [{"note": i % 2 == 0, "corridors": [], "ramps": []} for i in range(sheets)]
    for kind, base, per in (("corridors", CORRIDOR_CASES, 6), ("ramps", RAMP_CASES, 4)):
        cases = base * max(1, -(-sheets * per // len(base)))
        rng.shuffle(cases)
        for k, case in enumerate(cases):
            wants_note = case != "unreadable_ambiguous_unit"
            options = [i for i in range(sheets) if per_sheet[i]["note"] == wants_note or wants_note]
            target = min(options, key=lambda i: (len(per_sheet[i][kind]), (i + k) % sheets))
            per_sheet[target][kind].append(case)
    return per_sheet


def draw_sheet(rng: random.Random, plan: dict, name: str, sheet_no: int) -> tuple[bytes, dict]:
    doc = pymupdf.open()
    page = doc.new_page(width=1190, height=842)
    doc.set_metadata({"title": f"{name} - SYNTHETIC test drawing", "subject": "SYNTHETIC - not a real ship",
                      "keywords": "SYNTHETIC", "creator": "tools/synthetic_corridor_ramp.py"})
    page.draw_rect(pymupdf.Rect(20, 20, 1170, 822), color=(0, 0, 0), width=1)
    page.insert_text((640, 770), f"SYNTHETIC CORRIDOR AND RAMP SHEET {sheet_no} - NOT A REAL SHIP", fontsize=11)
    page.insert_text((640, 786), "SINCE AI HACKATHON 2026 - SYNTHETIC TEST DATA", fontsize=8)
    page.insert_text((640, 800), "SCALE 1:50", fontsize=9)
    if plan["note"]:
        page.insert_text((640, 814), "ALL DIMENSIONS IN MM", fontsize=9)
    facts, expected, schedule = [], [], []

    def source(quote: str, where: str) -> dict:
        return {"kind": "document", "file": f"{name}.pdf", "locator": f"page 1, {where}", "quote": quote}

    # Corridors: horizontal bands on the left, one label each.
    for i, case in enumerate(plan["corridors"]):
        cid = f"C{sheet_no}-{i + 1}"
        y = 60 + i * 80
        page.draw_line((60, y), (560, y), width=1.2)
        page.draw_line((60, y + 34), (560, y + 34), width=1.2)
        tag = f"CORRIDOR {cid}"
        if case == "unreadable_ambiguous_unit":
            style = "bare"
        elif case == "exactly_36":
            style = rng.choice(["in", "ftin"])
        else:
            style = rng.choice(["in", "ftin", "mm", "m", "bare"] if plan["note"] else ["in", "ftin", "mm", "m"])
        units = corridor_value(rng, case, style)
        width_mm = units * STYLES[style][0]
        text = length_text(units, style)
        readable = not case.startswith("unreadable")
        layout = rng.choice(["one_line", "two_line", "schedule"]) if readable else case
        quote = ""
        if case == "unreadable_missing":
            page.insert_text((80, y + 21), tag, fontsize=8)
        elif case == "unreadable_rotated":
            page.insert_text((80, y + 21), tag, fontsize=8)
            page.insert_text((200, y + 70), f"CLR WIDTH {text}", fontsize=8, rotate=90)
        elif case == "unreadable_ambiguous_unit" or layout == "one_line":
            quote = f"{tag}  CLEAR WIDTH {text}"
            page.insert_text((80, y + 21), quote, fontsize=8)
        elif layout == "two_line":
            page.insert_text((80, y + 15), tag, fontsize=8)
            page.insert_text((80, y + 27), f"CLR WIDTH {text}", fontsize=8)
            quote = f"{tag} | CLR WIDTH {text}"
        else:
            page.insert_text((80, y + 21), tag, fontsize=8)
            schedule.append((cid, text))
            quote = f"{cid}    {text}"
        if readable:
            facts.append({"subject": f"corridor:{cid}", "property": "clear_width", "value": float(units),
                          "unit": truth_unit(style), "confidence": "high", "location": None,
                          "source": source(quote, "corridor schedule" if layout == "schedule" else "corridor label")})
        expected.append({
            "subject": f"corridor:{cid}", "rule_id": CORRIDOR_RULE,
            "expected": corridor_expected(width_mm) if readable else "cant_tell",
            "violation": width_mm < CORRIDOR_MIN, "case": case, "style": style, "layout": layout,
            "stated": None if case == "unreadable_missing" else text, "true_value_mm": round(float(width_mm), 2),
            "app_has_check": True,
            "note": "under 36 in but at least 32 in: V403.5.1 exceptions may apply" if corridor_expected(width_mm) == "cant_tell"
                    and readable else case.replace("_", " ")})
    if schedule:
        page.insert_text((640, 50), "CORRIDOR SCHEDULE", fontsize=9)
        page.insert_text((640, 64), "CORRIDOR    CLEAR WIDTH", fontsize=8)
        for r, (cid, text) in enumerate(schedule):
            page.insert_text((640, 78 + 12 * r), f"{cid}    {text}", fontsize=8)

    # Ramps: boxes on the right, below the schedule.
    for j, case in enumerate(plan["ramps"]):
        rid = f"R{sheet_no}-{j + 1}"
        x, y = 640 + (j % 2) * 260, 230 + (j // 2) * 110
        page.draw_rect(pymupdf.Rect(x, y, x + 200, y + 40), color=(0, 0, 0), width=1)
        page.draw_line((x + 10, y + 20), (x + 190, y + 20), width=0.6)
        tag = f"RAMP {rid}"
        style = rng.choice(["ratio", "riserun_mm", "riserun_in", "riserun_m"])
        if case == "unreadable_ambiguous_unit" and style == "ratio":
            style = "riserun_mm"  # a 1:N ratio has no unit, so it can't be ambiguous
        value = ramp_value(rng, case, style)
        label, ramp_facts = ramp_label(style, value)
        slope = 1 / value[0] if style == "ratio" else value[0] / value[1]
        readable = not case.startswith("unreadable")
        quote = ""
        if case == "unreadable_missing":
            page.insert_text((x + 6, y + 14), tag, fontsize=8)
        elif case == "unreadable_rotated":
            page.insert_text((x + 6, y + 14), tag, fontsize=8)
            page.insert_text((x + 215, y + 80), label, fontsize=8, rotate=90)
        elif case == "unreadable_ambiguous_unit":
            label = f"RISE {float(value[0]):g}  RUN {float(value[1]):g}"
            page.insert_text((x + 6, y + 14), tag, fontsize=8)
            page.insert_text((x + 6, y + 34), label, fontsize=8)
        elif rng.random() < 0.5:
            quote = f"{tag}  {label}"
            page.insert_text((x + 6, y + 14), quote, fontsize=8)
        else:
            page.insert_text((x + 6, y + 14), tag, fontsize=8)
            page.insert_text((x + 6, y + 34), label, fontsize=8)
            quote = f"{tag} | {label}"
        if readable:
            facts += [{"subject": f"ramp:{rid}", **f, "confidence": "high", "location": None,
                       "source": source(quote, "ramp label")} for f in ramp_facts]
        expected.append({
            "subject": f"ramp:{rid}", "rule_id": RAMP_RULE,
            "expected": ("pass" if slope <= RAMP_MAX else "fail") if readable else "cant_tell",
            "violation": slope > RAMP_MAX, "case": case, "style": style,
            "stated": None if case == "unreadable_missing" else label, "true_slope": f"1:{float(1 / slope):.4g}",
            "app_has_check": True, "note": case.replace("_", " ")})

    truth = {"synthetic": True, "SYNTHETIC": "Generated test drawing, not a real ship.", "file": f"{name}.pdf",
             "generator": "tools/synthetic_corridor_ramp.py",
             "profile": {"ship_type": "passenger", "passengers": 400, "flag": "US",
                         "note": "Synthetic passenger ship; PVAG V201.1.1 scope (> 150 passengers) is met."},
             "limits": {CORRIDOR_RULE: "36 in (915 mm) min; 32 in (815 mm) under exceptions 1 and 2 (V403.5.1)",
                        RAMP_RULE: "1:12 max (V405.2)"},
             "sheet_unit_note": "mm" if plan["note"] else None, "facts": facts, "expected": expected}
    return doc.tobytes(), truth


def make_corridor_ramp_set(seed: int, out: Path = OUT, sheets: int = SHEETS) -> Path:
    """Write a seeded SYNTHETIC set: one PDF and one truth JSON per sheet. Returns the folder."""
    rng = random.Random(seed)
    folder = out / f"SYNTHETIC_corridor_ramp_seed{seed}"
    folder.mkdir(parents=True, exist_ok=True)
    for k, plan in enumerate(plan_cases(rng, sheets), start=1):
        name = f"SYNTHETIC_cr_s{seed}_{k:02d}"
        data, truth = draw_sheet(rng, plan, name, k)
        (folder / f"{name}.pdf").write_bytes(data)
        (folder / f"{name}.truth.json").write_text(json.dumps(truth, indent=2), encoding="utf-8")
    return folder
