"""SOLAS V/22.1.1 on the drawing itself: the engineer picks three points on a calibrated profile, code measures.

The engineer picks the conning position eye, the top of the highest obstruction forward of it, and the bow. The
calibrated page (deck-height ladder for heights, frame ruler for lengths, and the two checked against each other)
turns the points into the four bridge facts the check needs, and the design draught gives the waterline. Code does
all of the arithmetic and records it. The overlay draws the sight line on the sheet, so the result can be checked at
a glance.

Tier: B when the two calibration methods agree, else C, so a scale checked only one way can't back a verdict.
"""
from __future__ import annotations

from pydantic import BaseModel

from .models import Box, Evidence, Fact, Reading, Source, SourceKind, Tier
from .reading.model import Calibration

PICK_BOX_PT = 4.0  # half size of the evidence box around a picked point


class Pick(BaseModel):
    x: float  # page points, displayed frame
    y: float


class SightlineRequest(BaseModel):
    file: str
    page: int
    eye: Pick  # the eye at the conning position, or a point on its deck when eye_above_deck_m is given
    obstruction: Pick  # top of the highest obstruction forward of the eye
    bow: Pick  # the forward-most point of the bow
    eye_above_deck_m: float | None = None  # SOLAS gives no eye height: the engineer states it, or picks the eye itself
    draught_m: float | None = None  # the waterline; without it the design draught fact is used
    by: str


class SightlineError(ValueError):
    pass


def _box(page: int, pick: Pick) -> Box:
    return Box(page=page, x0=pick.x - PICK_BOX_PT, y0=pick.y - PICK_BOX_PT, x1=pick.x + PICK_BOX_PT, y1=pick.y + PICK_BOX_PT)


def derive(request: SightlineRequest, cal: Calibration, draught_m: float, draught_source: str,
           doc_id: str = "", revision: str = "") -> tuple[list[Fact], dict]:
    """(bridge facts, overlay). Raises SightlineError when the page can't be measured both ways."""
    if cal.ladder is None or not cal.real_mm_per_pt:
        raise SightlineError("This page has no measured scale with deck heights, so heights can't be read off it. "
                             + cal.certificate)
    if not request.by.strip():
        raise SightlineError("Say who picked the points.")
    mm_per_pt_up = cal.ladder.in_per_pt * 25.4
    mm_per_pt_along = cal.real_mm_per_pt
    base_y = cal.ladder.baseline_y_pt

    def height_m(y: float) -> float:  # above the baseline
        return (base_y - y) * mm_per_pt_up / 1000.0

    eye_z = height_m(request.eye.y) + (request.eye_above_deck_m or 0.0)
    obstruction_z, bow_z = height_m(request.obstruction.y), height_m(request.bow.y)
    to_obstruction = abs(request.obstruction.x - request.eye.x) * mm_per_pt_along / 1000.0
    to_bow = abs(request.bow.x - request.eye.x) * mm_per_pt_along / 1000.0
    if not (to_bow >= to_obstruction > 0):
        raise SightlineError("The obstruction must lie between the eye and the bow. Check the three points.")
    tier = Tier.B if cal.methods_agree else Tier.C
    scale = (f"page {request.page} measured {cal.scale_measured}; deck heights {cal.ladder.in_per_pt:.4f} in per point; "
             f"{'frame ruler and deck heights agree' if cal.methods_agree else 'checked one way only'}")
    picked = f"points picked by {request.by.strip()}"
    eye_text = f"eye {eye_z:.2f} m above baseline" + (f" ({request.eye_above_deck_m:g} m above the picked deck, as stated)"
                                                       if request.eye_above_deck_m else "")
    common = dict(file=request.file, doc_id=doc_id, revision=revision, page=request.page)

    def fact(prop: str, value_m: float, derivation: str, picks: list[Pick]) -> Fact:
        evidence = Evidence(**common, box=_box(request.page, picks[0]), quote=derivation,
                            readings=[Reading(method="geometry", text=f"{value_m:.2f} m", value=round(value_m, 3), unit="m")],
                            checks=[scale, picked])
        return Fact(subject="bridge", property=prop, value=round(value_m, 3), unit="m", tier=tier, evidence=evidence,
                    source=Source(kind=SourceKind.DOCUMENT, file=request.file, locator=f"page {request.page}, {picked}",
                                  quote=derivation),
                    derivation=derivation, derived_from=["calibration", "ship.design_draft"])

    facts = [
        fact("eye_height_above_water", eye_z - draught_m,
             f"{eye_text}, less {draught_m:g} m draught ({draught_source})", [request.eye]),
        fact("obstruction_height_above_water", obstruction_z - draught_m,
             f"obstruction top {obstruction_z:.2f} m above baseline, less {draught_m:g} m draught", [request.obstruction]),
        fact("eye_to_obstruction", to_obstruction, f"{to_obstruction:.2f} m horizontally from eye to obstruction", [request.obstruction]),
        fact("eye_to_bow", to_bow, f"{to_bow:.2f} m horizontally from eye to bow", [request.bow]),
    ]
    # Where the sight line over the obstruction meets the water, in page points, for the overlay.
    water_y = base_y - draught_m * 1000.0 / mm_per_pt_up
    eye_y = request.eye.y - (request.eye_above_deck_m or 0.0) * 1000.0 / mm_per_pt_up
    run = (request.obstruction.x - request.eye.x) * (water_y - eye_y) / (request.obstruction.y - eye_y) \
        if request.obstruction.y != eye_y else None
    overlay = {"file": request.file, "page": request.page,
               "points": [{"x": request.eye.x, "y": eye_y, "label": "Eye"},
                          {"x": request.obstruction.x, "y": request.obstruction.y, "label": "Obstruction"},
                          {"x": request.bow.x, "y": request.bow.y, "label": "Bow"}],
               "lines": [], "waterline_y": water_y, "picked_by": request.by.strip(), "scale": scale}
    if run is not None:
        overlay["lines"].append({"from": {"x": request.eye.x, "y": eye_y}, "to": {"x": request.eye.x + run, "y": water_y},
                                 "label": "Sight line over the obstruction"})
        overlay["lines"].append({"from": {"x": request.bow.x, "y": water_y}, "to": {"x": request.eye.x + run, "y": water_y},
                                 "label": "Sea surface hidden ahead of the bow"})
    return facts, overlay


def overlay_png(pdf_bytes: bytes, overlay: dict, margin_pt: float = 30.0, dpi: int = 150) -> bytes:
    """The part of the sheet the sight line crosses, with the line, the points, and the hidden sea drawn on it."""
    import pymupdf

    document = pymupdf.open(stream=pdf_bytes, filetype="pdf")
    page = document[overlay["page"] - 1]
    xs = [p["x"] for p in overlay["points"]] + [l["to"]["x"] for l in overlay["lines"]]
    ys = [p["y"] for p in overlay["points"]] + [overlay["waterline_y"]]
    clip = pymupdf.Rect(min(xs) - margin_pt, min(ys) - margin_pt, max(xs) + margin_pt, max(ys) + margin_pt) & page.rect
    shape = page.new_shape()
    unrotate = page.derotation_matrix
    for line in overlay["lines"]:
        start = pymupdf.Point(line["from"]["x"], line["from"]["y"]) * unrotate
        end = pymupdf.Point(line["to"]["x"], line["to"]["y"]) * unrotate
        shape.draw_line(start, end)
        hidden = line["label"].startswith("Sea surface")
        shape.finish(color=(0.80, 0.18, 0.25) if hidden else (0.12, 0.43, 0.55), width=2.0 if hidden else 1.2)
    for point in overlay["points"]:
        shape.draw_circle(pymupdf.Point(point["x"], point["y"]) * unrotate, 2.5)
        shape.finish(color=(0.07, 0.15, 0.23), fill=(1, 1, 1), width=1.0)
    shape.commit()
    png = page.get_pixmap(dpi=dpi, clip=clip).tobytes("png")
    document.close()
    return png
