"""Read vector PDF drawings with code, no AI: text with positions, dimension strings, door tags, schedules.

Rules, the same as for the AI reader:
- Report only values written on the drawing. Never scale a size off the lines: a missing value is
  better than a wrong one. The scale is read only as a signal for the confidence model.
- Every fact says how it was read (`meta`), so the confidence model can learn which readings fail:
  how far the tag was from the dimension, whether the pairing was ambiguous, whether the text layer
  is OCR, whether the unit was written or came from a sheet note, whether it came from a schedule.
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass, field

import pymupdf

from .models import Fact, Source, SourceKind

# Pairing distances in PDF points (1/72 in on paper).
MAX_GAP_PT = 40.0
FAR_GAP_PT = 18.0
AMBIGUITY_RATIO = 1.6
RIVAL_SLACK_PT = 8.0  # a second tag within ~3 mm on paper is always a real rival
SCHEDULE_REACH_PT = 260.0

_Q_FT = "['’′]"
_Q_IN = "(?:\"|”|″|'')"
_FRAC = r"(\d+)\s*/\s*(\d+)"
FT_IN = re.compile(rf"(?<![\d.])(\d+)\s*{_Q_FT}\s*[-–—]?\s*(?:(\d+)(?:\s+{_FRAC})?|{_FRAC})?\s*{_Q_IN}?")
INCH = re.compile(rf"(?<![\d.'/])(\d+(?:\.\d+)?)(?:\s+{_FRAC})?\s*(?:{_Q_IN}|\s?in\b|\s?inch(?:es)?\b)", re.IGNORECASE)
METRIC = re.compile(r"(?<![\d.])(\d+(?:[.,]\d+)?)\s?(mm|cm|m)\b", re.IGNORECASE)
BARE = re.compile(r"(?<![\d.'/:-])(\d{2,4}(?:\.\d+)?)(?![\d.'\"/:-]|\s?(?:mm|cm|m|in)\b)")

DOOR_TAG = re.compile(r"\b(?:D|DR|DOOR)\s?-?\s?(\d{2,5})(?![-\d])", re.IGNORECASE)
WIDTH_WORDS = re.compile(r"\b(CL\.?\s?OPG\.?|CLR\.?\s?OPG\.?|CLEAR\s+OPENING|CLEAR\s+OPG\.?|CLR\s+OPENING)\b", re.IGNORECASE)
OTHER_THINGS = re.compile(r"\b(CORRIDOR|PASSAGE(?!\s+DOOR)|RAMP|STAIR|LADDER|HATCH)\b", re.IGNORECASE)
SCHEDULE_WORD = re.compile(r"\bDOOR\s+SCHEDULE\b", re.IGNORECASE)
SCALE_RATIO = re.compile(r"\bSCALE\s*:?\s*1\s*:\s*(\d+)", re.IGNORECASE)
SCALE_IMPERIAL = re.compile(rf"(\d+(?:/\d+)?)\s*{_Q_IN}?\s*=\s*1\s*{_Q_FT}\s*-?\s*0", re.IGNORECASE)
SHEET_UNIT = re.compile(r"\b(?:ALL\s+)?DIMENSIONS\s+(?:ARE\s+)?IN\s+(MM|MILLIMET(?:RE|ER)S|INCHES|IN)\b", re.IGNORECASE)
SHIP_WORDS = [  # (pattern before the value, subject, property)
    (re.compile(r"\b(?:LENGTH\s+OVER\s*ALL|LENGTH,?\s+OVERALL|L\.?O\.?A\.?)\b[\s.:,]*", re.IGNORECASE), "ship", "length_overall"),
    (re.compile(r"\b(?:BEAM,?\s+MO(?:U)?LDED|MO(?:U)?LDED\s+BEAM)\b[\s.:,]*", re.IGNORECASE), "ship", "beam"),
]


@dataclass
class Length:
    value: float
    unit: str
    raw: str
    start: int
    end: int
    unit_written: bool = True


@dataclass
class Line:
    text: str
    bbox: tuple[float, float, float, float]
    page: int

    @property
    def centre(self) -> tuple[float, float]:
        x0, y0, x1, y1 = self.bbox
        return (x0 + x1) / 2, (y0 + y1) / 2


@dataclass
class PageInfo:
    number: int
    lines: list[Line]
    scale: str = ""
    sheet_unit: str = ""
    ocr: bool = False
    text_chars: int = 0


@dataclass
class ReadResult:
    facts: list[Fact] = field(default_factory=list)
    pages: list[dict] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)  # things seen but not reported, and why


# ---------- dimension text ----------

VALID_DENOMINATORS = {2, 4, 8, 16, 32, 64}


class BadFraction(ValueError):
    """Drawings use proper fractions over 2, 4, 8, 16, 32, 64. Anything else is a misread (often OCR)."""


def _frac(n: str | None, d: str | None) -> float:
    if not (n and d):
        return 0.0
    num, den = int(n), int(d)
    if den not in VALID_DENOMINATORS or not 0 < num < den:
        raise BadFraction(f"{n}/{d}")
    return num / den


def find_lengths(text: str, sheet_unit: str = "") -> list[Length]:
    """Every length written in the text, as one number and one unit. Feet-and-inches become inches."""
    found: list[Length] = []
    taken: list[tuple[int, int]] = []

    def free(a: int, b: int) -> bool:
        return all(b <= s or a >= e for s, e in taken)

    for m in FT_IN.finditer(text):
        feet, inches, n1, d1, n2, d2 = m.groups()
        if not free(m.start(), m.end()):
            continue
        taken.append((m.start(), m.end()))
        try:
            value = float(feet) * 12 + (float(inches) if inches else 0) + _frac(n1, d1) + _frac(n2, d2)
        except BadFraction:
            continue  # the span stays taken, so no shorter wrong reading is made from it
        if inches and float(inches) >= 12:
            continue
        found.append(Length(value, "in", m.group(0).strip(), m.start(), m.end()))
    for m in INCH.finditer(text):
        if free(m.start(), m.end()):
            whole, n, d = m.groups()
            taken.append((m.start(), m.end()))
            try:
                found.append(Length(float(whole) + _frac(n, d), "in", m.group(0).strip(), m.start(), m.end()))
            except BadFraction:
                continue
    for m in METRIC.finditer(text):
        if free(m.start(), m.end()):
            found.append(Length(float(m.group(1).replace(",", ".")), m.group(2).lower(), m.group(0).strip(), m.start(), m.end()))
            taken.append((m.start(), m.end()))
    if sheet_unit:
        # A bare number counts only after a width keyword, with the unit from the sheet note.
        for m in BARE.finditer(text):
            if free(m.start(), m.end()) and WIDTH_WORDS.search(text[:m.start()]):
                found.append(Length(float(m.group(1)), sheet_unit, m.group(0), m.start(), m.end(), unit_written=False))
                taken.append((m.start(), m.end()))
    return sorted(found, key=lambda length: length.start)


# ---------- page analysis ----------

def _looks_ocr(text: str) -> bool:
    if not text:
        return False
    odd = text.count("�") + len(re.findall(r"[^\x00-\x7f’”″′°±×]", text))
    return odd / len(text) > 0.002


def _scanned(page: pymupdf.Page) -> bool:
    """A page that is mostly one picture: any text on it is OCR, which misreads characters."""
    area = page.rect.width * page.rect.height
    covered = sum(abs(pymupdf.Rect(i["bbox"]) & page.rect) for i in page.get_image_info())
    return area > 0 and covered / area > 0.5


def analyse_page(page: pymupdf.Page, number: int) -> PageInfo:
    lines = []
    for block in page.get_text("dict")["blocks"]:
        for line in block.get("lines", []):
            text = " ".join(span["text"] for span in line["spans"]).strip()
            if text:
                lines.append(Line(text, tuple(line["bbox"]), number))
    joined = "\n".join(line.text for line in lines)
    scale = ""
    if m := SCALE_RATIO.search(joined):
        scale = f"1:{m.group(1)}"
    elif m := SCALE_IMPERIAL.search(joined):
        scale = m.group(0)
    unit = ""
    if m := SHEET_UNIT.search(joined):
        unit = "mm" if m.group(1).upper().startswith("M") else "in"
    return PageInfo(number, lines, scale, unit, _scanned(page) or _looks_ocr(joined), len(joined))


def _gap(a: tuple, b: tuple) -> float:
    """Shortest distance between two boxes, 0 if they touch."""
    dx = max(a[0] - b[2], b[0] - a[2], 0.0)
    dy = max(a[1] - b[3], b[1] - a[3], 0.0)
    return math.hypot(dx, dy)


# ---------- facts ----------

def _fact(file: str, info: PageInfo, subject: str, prop: str, length: Length, quote: str, where: str,
          bbox: tuple, *, gap_pt: float = 0.0, ambiguous: bool = False, keyword: bool = True,
          from_table: bool = False) -> Fact:
    confidence = "high"
    if not length.unit_written or gap_pt > FAR_GAP_PT or not keyword:
        confidence = "medium"
    if ambiguous or info.ocr:
        confidence = "low"
    meta = {"reader": "vector", "pairing_gap_in": round(gap_pt / 72, 3), "ambiguous_pairing": ambiguous,
            "ocr_text": info.ocr, "scale_known": bool(info.scale), "scale": info.scale, "from_table": from_table,
            "unit_written": length.unit_written, "keyword": keyword}
    locator = f"page {info.number}, {where} at ({bbox[0]:.0f}, {bbox[1]:.0f}) pt"
    return Fact(subject=subject, property=prop, value=length.value, unit=length.unit, confidence=confidence,
                source=Source(kind=SourceKind.DOCUMENT, file=file, locator=locator, quote=quote), meta=meta)


def _door_widths(file: str, info: PageInfo, result: ReadResult) -> None:
    schedule_tops = [l.bbox[1] for l in info.lines if SCHEDULE_WORD.search(l.text)]
    tags: list[tuple[Line, str]] = []        # a door tag with no width on its own line
    widths: list[tuple[Line, Length, bool]] = []  # a width with no tag on its own line
    for line in info.lines:
        if OTHER_THINGS.search(line.text):
            continue
        door_tags = DOOR_TAG.findall(line.text)
        lengths = find_lengths(line.text, info.sheet_unit)
        keyword = bool(WIDTH_WORDS.search(line.text))
        if len(door_tags) == 1 and lengths:
            in_schedule = any(0 < line.bbox[1] - top < SCHEDULE_REACH_PT for top in schedule_tops)
            if len(lengths) > 1:
                result.skipped.append(f"page {info.number}: {line.text!r} has several lengths for one door")
                continue
            result.facts.append(_fact(file, info, f"door-number:{door_tags[0]}", "clear_width", lengths[0], line.text,
                                      "door schedule" if in_schedule else "door label", line.bbox,
                                      keyword=keyword or in_schedule, from_table=in_schedule))
        elif len(door_tags) == 1:
            tags.append((line, door_tags[0]))
        elif not door_tags and lengths and keyword and len(lengths) == 1:
            widths.append((line, lengths[0], keyword))
        elif len(door_tags) > 1:
            result.skipped.append(f"page {info.number}: {line.text!r} names several doors, so no width is assigned")

    pairs = sorted(((_gap(t.bbox, w.bbox), ti, wi) for ti, (t, _) in enumerate(tags)
                    for wi, (w, _, _) in enumerate(widths)), key=lambda p: p[0])
    used_t, used_w = set(), set()
    for gap, ti, wi in pairs:
        if gap > MAX_GAP_PT or ti in used_t or wi in used_w:
            continue
        # Ambiguous: another width is nearly as close to this tag, or another tag to this width.
        rivals = [g for g, t2, w2 in pairs if (t2 == ti) != (w2 == wi) and (t2 == ti or w2 == wi)
                  and g <= gap * AMBIGUITY_RATIO + RIVAL_SLACK_PT and t2 not in used_t and w2 not in used_w]
        used_t.add(ti)
        used_w.add(wi)
        (tag_line, number), (width_line, length, keyword) = tags[ti], widths[wi]
        result.facts.append(_fact(file, info, f"door-number:{number}", "clear_width", length,
                                  f"{tag_line.text} | {width_line.text}", "door label", tag_line.bbox,
                                  gap_pt=gap, ambiguous=bool(rivals), keyword=keyword))
    for ti, (line, number) in enumerate(tags):
        if ti not in used_t and not any(f.subject == f"door-number:{number}" for f in result.facts):
            # The door is on the sheet, but no width is written: the check then says can't tell.
            result.facts.append(Fact(subject=f"door-number:{number}", property="shown_on", value=f"page {info.number}",
                                     confidence="high", meta={"reader": "vector"},
                                     source=Source(kind=SourceKind.DOCUMENT, file=file, quote=line.text,
                                                   locator=f"page {info.number}, door tag at ({line.bbox[0]:.0f}, {line.bbox[1]:.0f}) pt")))
    for wi, (line, _, _) in enumerate(widths):
        if wi not in used_w:
            result.skipped.append(f"page {info.number}: {line.text!r} has no door tag close enough")


def _vertical(box: tuple) -> bool:
    return (box[3] - box[1]) > 2 * (box[2] - box[0])


def _same_row(a: tuple, b: tuple) -> bool:
    """Two lines in one table row: they overlap across the reading direction (text may be rotated)."""
    lo, hi = (0, 2) if _vertical(a) else (1, 3)
    overlap = min(a[hi], b[hi]) - max(a[lo], b[lo])
    return overlap > 0.6 * min(a[hi] - a[lo], b[hi] - b[lo])


def _ship_values(file: str, info: PageInfo, result: ReadResult) -> None:
    for line in info.lines:
        for pattern, subject, prop in SHIP_WORDS:
            m = pattern.search(line.text)
            if not m or any(f.subject == subject and f.property == prop for f in result.facts):
                continue
            lengths = [l for l in find_lengths(line.text) if l.start >= m.end() - 1]
            if lengths:
                result.facts.append(_fact(file, info, subject, prop, lengths[0], line.text, "text", line.bbox))
                continue
            # A table: the label in one column, the value further along the same row.
            mates = [(_gap(line.bbox, other.bbox), other, found[0]) for other in info.lines
                     if other is not line and _same_row(line.bbox, other.bbox)
                     and len(found := find_lengths(other.text)) == 1 and len(other.text) < 20]
            if mates:
                gap, other, length = min(mates, key=lambda mate: mate[0])
                result.facts.append(_fact(file, info, subject, prop, length, f"{line.text} | {other.text}",
                                          "table row", line.bbox, gap_pt=gap, keyword=True, from_table=True))


def read_pdf(data: bytes, file: str, pages: list[int] | None = None) -> ReadResult:
    document = pymupdf.open(stream=data, filetype="pdf")
    wanted = pages or list(range(1, len(document) + 1))
    result = ReadResult()
    for number in wanted:
        if not 1 <= number <= len(document):
            continue
        info = analyse_page(document[number - 1], number)
        before = len(result.facts)
        _door_widths(file, info, result)
        _ship_values(file, info, result)
        result.pages.append({"page": number, "text_chars": info.text_chars, "scale": info.scale,
                             "sheet_unit": info.sheet_unit, "ocr": info.ocr, "facts": len(result.facts) - before})
    return result
