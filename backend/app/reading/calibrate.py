"""Calibration: turn a drawing into a measuring instrument by fitting its own labels.

Two rulers are fitted from text the page already carries: the frame ruler (frame numbers along the hull) gives
points per frame, and the deck-height ladder ("45'-6" ABL" labels) gives real length per point. Each is fitted
robustly, so a label that OCR misread lands off the line and is reported instead of bending the fit.
The sheet's own scale note is never trusted: it is only compared with the measurement.
"""
from __future__ import annotations

import re
from typing import Callable

import numpy as np
import pymupdf

from .model import Calibration, DocumentMap, LadderFit, Line, RulerFit, Word
from .parse import parse_length, parse_scale, to_mm
from .titleblock import find_scale_notes

RULER_TOLERANCE_PT = 1.5
LADDER_TOLERANCE_PT = 1.0
MIN_RULER_LABELS = 5
MIN_LADDER_LABELS = 3
FRAME_RANGE = (-99, 399)
RULER_PT_PER_FRAME = (1.5, 80.0)  # a frame is 1.5 to 80 points wide on a sheet; a zone grid (about 150) isn't a ruler
LADDER_IN_PER_PT = (0.028, 28.0)  # sheet scales from about 1:2 to 1:2000
NOTE_TOLERANCE = 0.02  # a scale note matches within 2%
AGREE_TOLERANCE = 0.005  # two methods agree within 0.5%
LEADER_LENGTH_PT = (10.0, 60.0)
LEADER_MAX_GAP_PT = 60.0
MM_PER_PT = 25.4 / 72.0

_FRAME_LABEL = re.compile(r"[-−–—]?\d{1,3}")
_ABL = re.compile(r"\bA\.?\s?B\.?\s?L\b\.?", re.I)


# ---------------------------------------------------------------- robust line

def _robust_line(values: np.ndarray, positions: np.ndarray, tolerance: np.ndarray,
                 slope_ok: Callable[[float], bool]) -> tuple[float, float, np.ndarray] | None:
    """position = a + b * value, fitted by RANSAC over pairs and refined by least squares on the inliers.

    Each point has its own tolerance. Inliers must have distinct values: two labels with one value can't both be
    right. Returns (a, b, inlier mask), or None when no pair gives a plausible slope.
    """
    n = len(values)
    best: tuple[int, float, np.ndarray] | None = None
    for i in range(n):
        for j in range(i + 1, n):
            dv = values[j] - values[i]
            if dv == 0:
                continue
            b = (positions[j] - positions[i]) / dv
            if not slope_ok(b):
                continue
            a = positions[i] - b * values[i]
            inliers = _distinct(values, positions, a, b, tolerance)
            score = (int(inliers.sum()), -float(np.sum((positions[inliers] - a - b * values[inliers]) ** 2)))
            if best is None or score > best[:2]:
                best = (score[0], score[1], inliers)
    if best is None:
        return None
    inliers = best[2]
    a = b = 0.0
    for _ in range(4):  # least squares, then re-judge every point against the refined line
        if inliers.sum() < 2:
            return None
        b, a = np.polyfit(values[inliers], positions[inliers], 1)
        if not slope_ok(b):
            return None
        refined = _distinct(values, positions, a, b, tolerance)
        if np.array_equal(refined, inliers):
            break
        inliers = refined
    return float(a), float(b), inliers


def _distinct(values: np.ndarray, positions: np.ndarray, a: float, b: float, tolerance: np.ndarray) -> np.ndarray:
    """Points within tolerance of the line, keeping only the closest one for each value."""
    residual = np.abs(positions - (a + b * values))
    mask = residual <= tolerance
    for value in np.unique(values[mask]):
        same = np.flatnonzero(mask & (values == value))
        if len(same) > 1:
            mask[same] = False
            mask[same[np.argmin(residual[same])]] = True
    return mask


# ---------------------------------------------------------------- frame ruler

def _frame_labels(dm: DocumentMap, page: int) -> list[tuple[Word, int]]:
    out = []
    for word in dm.words:
        text = word.text.strip()
        if word.page != page or not _FRAME_LABEL.fullmatch(text):
            continue
        value = int(re.sub(r"[−–—]", "-", text))
        if FRAME_RANGE[0] <= value <= FRAME_RANGE[1]:
            out.append((word, value))
    return out


def _rows(labels: list[tuple[Word, int]]) -> list[list[tuple[Word, int]]]:
    """Labels grouped by the line they sit on."""
    ordered = sorted(labels, key=lambda l: (l[0].box.y0 + l[0].box.y1) / 2)
    rows: list[list[tuple[Word, int]]] = []
    for word, value in ordered:
        yc = (word.box.y0 + word.box.y1) / 2
        height = max(word.box.y1 - word.box.y0, 1.0)
        if rows:
            first = rows[-1][0][0]
            if yc - (first.box.y0 + first.box.y1) / 2 <= 0.6 * height:
                rows[-1].append((word, value))
                continue
        rows.append([(word, value)])
    return rows


def _fit_row(page: int, row: list[tuple[Word, int]]) -> RulerFit | None:
    values = np.array([v for _, v in row], float)
    xs = np.array([(w.box.x0 + w.box.x1) / 2 for w, _ in row])
    fit = _robust_line(values, xs, np.full(len(row), RULER_TOLERANCE_PT),
                       lambda b: RULER_PT_PER_FRAME[0] <= abs(b) <= RULER_PT_PER_FRAME[1])
    if fit is None:
        return None
    a, b, inliers = fit
    used = int(inliers.sum())
    if used < MIN_RULER_LABELS or used < 0.5 * len(row):
        return None
    residual = np.abs(xs - (a + b * values))
    rejected = [{"text": w.text, "confidence": w.confidence, "box": w.box.model_dump(),
                 "position_says_frame": round(float((x - a) / b), 1), "word_id": w.id}
                for (w, _), x, ok in zip(row, xs, inliers) if not ok]
    # x = x_at_frame0 - pt_per_frame * frame, so the number is positive when frames grow toward the left of the page.
    return RulerFit(page=page, labels=len(row), used=used, pt_per_frame=-b, x_at_frame0=a,
                    max_residual_pt=float(residual[inliers].max()), rejected=rejected)


def fit_frame_ruler(dm: DocumentMap, page: int) -> RulerFit | None:
    """Fit label position against frame number along the best row of numbers: x = x_at_frame0 - pt_per_frame * frame.

    Rows with fewer than 5 labels on one line, or fewer than half of whose labels agree, are not rulers. If another
    row fits with a different scale (views at different scales), the page is ambiguous and gives None.
    """
    fits = [f for row in _rows(_frame_labels(dm, page)) if len(row) >= MIN_RULER_LABELS and (f := _fit_row(page, row))]
    if not fits:
        return None
    best = max(fits, key=lambda f: (f.used, -f.max_residual_pt))
    for other in fits:
        if other is not best and other.used >= 0.6 * best.used \
                and abs(other.pt_per_frame - best.pt_per_frame) > 0.01 * abs(best.pt_per_frame):
            return None
    return best


# ---------------------------------------------------------------- deck ladder

def _height_in(text: str) -> float | None:
    """The height in inches written in an "ABL" label; None for anything but exactly one length."""
    if not _ABL.search(text):
        return None
    if len(re.findall(r"['’′´`]", text)) > 1 or len(re.findall(r"\d\s*(?:mm|cm|m)\b", text, re.I)) > 1:
        return None
    parsed = parse_length(text)
    if parsed is None:
        return None
    return to_mm(*parsed) / 25.4


def _leaders(pdf_bytes: bytes, page: int, window: tuple[float, float, float, float]) -> list[tuple[float, float, float]]:
    """Short horizontal strokes (x0, x1, y) in the displayed frame inside the window: candidates for level leaders."""
    doc = pymupdf.open(stream=pdf_bytes, filetype="pdf")
    pdf_page = doc[page - 1]
    m = pdf_page.rotation_matrix
    x_min, y_min, x_max, y_max = window
    out = []
    for path in pdf_page.get_cdrawings():
        for item in path["items"]:
            if item[0] != "l":
                continue
            (ax, ay), (bx, by) = item[1], item[2]
            x0, y0 = m.a * ax + m.c * ay + m.e, m.b * ax + m.d * ay + m.f
            x1, y1 = m.a * bx + m.c * by + m.e, m.b * bx + m.d * by + m.f
            length = abs(x1 - x0)
            if abs(y1 - y0) < 0.05 and LEADER_LENGTH_PT[0] <= length <= LEADER_LENGTH_PT[1] \
                    and x_min <= min(x0, x1) and max(x0, x1) <= x_max and y_min <= y0 <= y_max:
                out.append((min(x0, x1), max(x0, x1), (y0 + y1) / 2))
    return out


def _snap_to_leader(line: Line, leaders: list[tuple[float, float, float]]) -> float | None:
    """y of the leader stroke that ends just left of the label, level with its top; None if none or several."""
    h = line.box.y1 - line.box.y0
    near = [(line.box.x0 - x1, y) for x0, x1, y in leaders
            if -3.0 <= line.box.x0 - x1 <= LEADER_MAX_GAP_PT and line.box.y0 - 0.5 * h <= y <= line.box.y0 + 0.5 * h]
    if not near:
        return None
    gap = min(g for g, _ in near)
    closest = sorted(y for g, y in near if g <= gap + 2.0)
    return closest[0] if closest[-1] - closest[0] <= 0.3 else None


def fit_deck_ladder(dm: DocumentMap, page: int, pdf_bytes: bytes | None = None) -> LadderFit | None:
    """Fit label position against written height: y = baseline_y_pt - height_in / in_per_pt.

    The level's position is the leader stroke beside the label when the PDF is given, else the label's top edge.
    """
    labels = [(l, h) for l in dm.page_lines(page) if (h := _height_in(l.text)) is not None]
    if len(labels) < MIN_LADDER_LABELS:
        return None
    leaders: list[tuple[float, float, float]] = []
    if pdf_bytes:
        window = (min(l.box.x0 for l, _ in labels) - LEADER_MAX_GAP_PT - 5, min(l.box.y0 for l, _ in labels) - 10,
                  max(l.box.x1 for l, _ in labels), max(l.box.y1 for l, _ in labels) + 10)
        leaders = _leaders(pdf_bytes, page, window)
    ys, methods = [], []
    for line, _ in labels:
        snapped = _snap_to_leader(line, leaders) if leaders else None
        ys.append(snapped if snapped is not None else line.box.y0)
        methods.append("leader" if snapped is not None else "text_top")
    heights = np.array([h for _, h in labels], float)
    ys_a = np.array(ys)
    fit = _robust_line(heights, ys_a, np.full(len(labels), LADDER_TOLERANCE_PT),
                       lambda b: b < 0 and LADDER_IN_PER_PT[0] <= -1.0 / b <= LADDER_IN_PER_PT[1])
    if fit is None:
        return None
    a, b, inliers = fit
    used = int(inliers.sum())
    if used < MIN_LADDER_LABELS:
        return None
    in_per_pt = -1.0 / b
    levels, rejected = [], []
    for (line, height), y, method, ok in zip(labels, ys, methods, inliers):
        base = {"name": _level_name(line.text), "value_in": round(height, 3), "y_pt": round(y, 2), "line_id": line.id,
                "position_from": method, "confidence": line.confidence}
        if ok:
            levels.append(base)
        else:
            rejected.append({**base, "text": line.text, "box": line.box.model_dump(),
                             "position_says_height_in": round(float((y - a) / b), 1)})
    residual = np.abs(ys_a - (a + b * heights))[inliers]
    return LadderFit(page=page, labels=len(labels), used=used, in_per_pt=in_per_pt, baseline_y_pt=a,
                     max_residual_in=float(residual.max() * in_per_pt), levels=levels, rejected=rejected)


def _level_name(text: str) -> str:
    """The label as written ("45'-6\" ABL"), which is how an engineer names the level."""
    return re.sub(r"\s+", " ", text).strip()


# ---------------------------------------------------------------- the calibration of a page

def _page_notes(dm: DocumentMap, page: int) -> list[str]:
    notes: list[str] = []
    for line in dm.page_lines(page):
        for note in find_scale_notes(line.text):
            if note not in notes:
                notes.append(note)
    return notes or list(dm.title_block.scale_notes)


def calibrate_page(dm: DocumentMap, page: int, pdf_bytes: bytes | None = None,
                   stated_frame_spacing_mm: float | None = None) -> Calibration:
    """The measured scale of a page, checked against the sheet's own note and, when both fits exist, against itself.

    The deck ladder gives millimeters per point directly. The frame ruler gives it only with a stated frame spacing.
    When both exist and a spacing is stated, they must agree within 0.5% or no scale is reported.
    """
    ruler = fit_frame_ruler(dm, page)
    ladder = fit_deck_ladder(dm, page, pdf_bytes)
    cal = Calibration(page=page, ruler=ruler, ladder=ladder, scale_noted=_page_notes(dm, page),
                      stated_frame_spacing_mm=stated_frame_spacing_mm)

    from_ladder = ladder.in_per_pt * 25.4 if ladder else None
    # The ruler's sign says which way frames run across the sheet; only its size says how wide a frame is.
    from_ruler = stated_frame_spacing_mm / abs(ruler.pt_per_frame) if ruler and stated_frame_spacing_mm else None
    if from_ladder is not None and ruler is not None:
        cal.implied_frame_spacing_mm = abs(ruler.pt_per_frame) * from_ladder
    if cal.implied_frame_spacing_mm is not None and stated_frame_spacing_mm:
        gap = abs(cal.implied_frame_spacing_mm - stated_frame_spacing_mm)
        cal.methods_agree = gap <= AGREE_TOLERANCE * stated_frame_spacing_mm

    if cal.methods_agree is not False:
        cal.real_mm_per_pt = from_ladder if from_ladder is not None else from_ruler
    if cal.real_mm_per_pt:
        scale = cal.real_mm_per_pt / MM_PER_PT
        cal.scale_measured = f"1:{scale:.1f}"
        ratios = [r for r in (parse_scale(n) for n in cal.scale_noted) if r]
        if ratios:
            cal.noted_matches = any(abs(r - scale) <= NOTE_TOLERANCE * scale for r in ratios)
    cal.certificate = _certificate(cal, from_ladder, from_ruler)
    return cal


def _certificate(cal: Calibration, from_ladder: float | None, from_ruler: float | None) -> str:
    ladder, ruler = cal.ladder, cal.ruler
    if not ladder and not ruler:
        return "No scale could be measured on this page: no frame ruler and no deck-height labels were fitted."
    if cal.methods_agree is False:
        return (f"The deck heights and the frame ruler disagree: they imply a frame spacing of "
                f"{_spacing(cal.implied_frame_spacing_mm)} against the stated {_spacing(cal.stated_frame_spacing_mm)}, "
                f"so no scale is reported.")
    if cal.real_mm_per_pt is None:
        return (f"A frame ruler was found ({ruler.used} labels, {abs(ruler.pt_per_frame):.2f} points per frame) but there are "
                f"no deck heights and no stated frame spacing, so the scale can't be measured.")
    basis = (f"{ladder.used} deck-height labels" if from_ladder is not None
             else f"{ruler.used} frame labels at the stated frame spacing")
    text = f"Sheet scale measured {cal.scale_measured} from {basis}"
    ratios = sorted({r for r in (parse_scale(n) for n in cal.scale_noted) if r})
    if ratios:
        said = " and ".join(f"1:{r:g}" for r in ratios)
        text += f"; the note says {said}" + (" and agrees" if cal.noted_matches else ", so the note is not used")
    text += "."
    if cal.implied_frame_spacing_mm is not None:
        if cal.methods_agree:
            text += f" Frame ruler and deck heights agree: implied frame spacing {_spacing(cal.implied_frame_spacing_mm)}."
        else:
            text += (f" Frame ruler and deck heights imply a frame spacing of {_spacing(cal.implied_frame_spacing_mm)}; "
                     f"no frame spacing was stated to check it against.")
    return text


def _spacing(mm: float | None) -> str:
    return "unknown" if mm is None else f"{mm:.0f} mm ({mm / 25.4:.2f} in)"
