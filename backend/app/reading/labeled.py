"""The deterministic reading path: a dictionary label, then the value next to it, parsed by code. No AI.

The same helpers verify what the AI points at (pointing.py) and what a second reader returns (second_reading.py),
so every path applies one set of rules. A wrong value is far worse than a missing one, so any doubt gives no value:
a lookalike label, a label in the middle of a sentence, a number followed by other words, a unit nobody stated.
"""
from __future__ import annotations

import re
from bisect import bisect_left, bisect_right
from dataclasses import dataclass

from .. import dictionary
from ..dictionary import FactDef
from ..models import Box
from .model import DocumentMap, FactCandidate, Line
from .parse import TO_MM, parse_date, parse_length, parse_number, to_mm

ROW_TOLERANCE = 0.6  # same row: vertical centers within this many line heights
MAX_REGION = 0.5  # a value must start within this fraction of the page width from its label's start
STACK_GAP = 1.0  # a value stacked below its label: at most this many line heights of gap
LOW_OCR = 0.5  # OCR confidence under this is a problem
MAX_VALUE_TEXT = 120
# "7 x 350 persons = 2,450 persons": a count times a rating, with the total stated. Code checks the product.
_PERSONS = r"(?:persons?|pers\.?|p)"
# OCR often drops the "=", so it is optional: the product check still has to hold.
_PRODUCT = re.compile(rf"(\d{{1,4}})\s*[x×X]\s*(\d{{1,5}})\s*(?:{_PERSONS}\b)?\s*(?:=\s*)?(\d{{1,3}}(?:,\d{{3}})+|\d+)()\s*(?:{_PERSONS}\b)?", re.I)
# Subjects that name one of a few fixed items, like lifeboats:(port|starboard). The line must say which one.
_CLOSED_SUBJECT = re.compile(r"([A-Za-z_][\w-]*):\(([A-Za-z_|]+)\)")
_ITEM_WORDS = {"port": ("PORT", "PORT SIDE", "PS"), "starboard": ("STARBOARD", "STARBOARD SIDE", "STBD", "SB")}
SKIP_FACTS = {"evacuation.analysis_present"}  # a presence fact: a document exists, no value to read

# Words allowed after a number: units, and "persons". Anything else ("7 DOUBLE S/R") means it isn't the value.
TAIL_WORDS = {"mm", "cm", "m", "in", "ft", "inch", "inches", "feet", "persons", "person", "pers", "pax",
              "people", "gt", "grt", "t", "tonnes", "tons", "min", "mins", "minutes"}

_MARKS = str.maketrans({"‘": "'", "’": "'", "′": "'", "´": "'", "`": "'",
                        "“": '"', "”": '"', "″": '"'})
_UNIT = r"(mm|millimet(?:re|er)s?|cm|centimet(?:re|er)s?|met(?:re|er)s?|m|inch(?:es)?|in|feet|foot|ft)"
_BRACKET_UNIT = re.compile(rf"[(\[]\s*{_UNIT}\s*[)\]]", re.I)
_PHRASE_UNIT = re.compile(rf"\b(?:DIMENSIONS?|DIMS?|UNITS?)\b[^|\n]{{0,30}}?(?:\bIN\b|[:=])\s*{_UNIT}\b", re.I)
_UNIT_NAMES = {"mm": "mm", "cm": "cm", "m": "m", "in": "in", "ft": "ft", "inch": "in", "inches": "in",
               "feet": "ft", "foot": "ft"}
_UNIT_WORDS = [
    (re.compile(r"(?<=\d)\s*millimet(?:re|er)s?\b", re.I), " mm"),
    (re.compile(r"(?<=\d)\s*centimet(?:re|er)s?\b", re.I), " cm"),
    (re.compile(r"(?<=\d)\s*met(?:re|er)s?\b", re.I), " m"),
    (re.compile(r"(?<=\d)\s*(?:feet|foot|ft)\b\.?", re.I), "'"),
]
_LEAD_SEPARATORS = re.compile(r"^(?:[\s:=|;·…_]+|[.,](?!\d)|[-–—](?=\s))")
_LEAD_PARENTHETICAL = re.compile(r"^(?:\([^()\d]*\)|\[[^\[\]\d]*\])")
_PARENTHETICAL = re.compile(r"\([^()\d]*\)|\[[^\[\]\d]*\]")


@dataclass(frozen=True)
class Parsed:
    value: float | str
    unit: str
    text: str  # the exact characters the value was parsed from
    shown: str  # how code read them, for the checks list: 199'-6" = 2394 in


def normalize_marks(text: str) -> str:
    """Primes and quotes as one form, so OCR's curly marks and doubled apostrophes parse like the real ones."""
    return text.translate(_MARKS).replace("''", '"')


def norm(text: str) -> str:
    """The dictionary's own normal form: upper case, runs of punctuation as one space."""
    return re.sub(r"[^A-Z0-9]+", " ", text.upper()).strip()


def after_label(text: str) -> str:
    """Drop the separators and digit-free parentheses (units, qualifiers) between a label and its value."""
    text = text.strip()
    while True:
        new = _LEAD_SEPARATORS.sub("", text)
        new = _LEAD_PARENTHETICAL.sub("", new).lstrip()
        if new == text:
            return text
        text = new


def locate_label(text: str, label: str) -> tuple[int, int] | None:
    """Where a listed label sits in the raw text, tolerant of the punctuation the dictionary normalizes away."""
    tokens = norm(label).split()
    if not tokens:
        return None
    pattern = r"(?<![A-Za-z0-9])" + r"[^A-Za-z0-9]+".join(re.escape(t) for t in tokens) + r"(?![A-Za-z0-9])"
    match = re.search(pattern, text, re.I)
    if not match:
        return None
    end = match.end()
    if "(" in label or "[" in label:
        while end < len(text) and text[end] in ")]":
            end += 1  # "BEAM (MLD)": the closing bracket belongs to the label
    return match.start(), end


def lookalike_in(defn: FactDef, text: str) -> str:
    """The first lookalike of this fact written in the text, or an empty string."""
    normal = f" {norm(text)} "
    return next((bad for bad in defn.lookalikes if f" {norm(bad)} " in normal), "")


def holds_a_label(text: str) -> bool:
    """Whether the text holds a listed label of any fact (one-letter labels don't count: too common)."""
    normal = f" {norm(text)} "
    return any(f" {norm(l)} " in normal and len(norm(l)) > 1 and dictionary.label_matches(d, text)
               for d in dictionary.load() for l in d.labels)


def literal_subject(defn: FactDef) -> str | None:
    """The subject when it is one fixed word (ship); None for door-number:<n> and the like, which text can't name."""
    return defn.subject if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", defn.subject) else None


def range_unit(defn: FactDef) -> str:
    """The unit of a length fact's range: meters, except mm-scale facts (the dictionary gives mm as unit_hint, or
    ranges like 300-6000 with no hint, as for stair width)."""
    if defn.unit_hint == "mm" or (defn.range is not None and defn.range[1] > 1000):
        return "mm"
    return "m"


def range_result(defn: FactDef, value: float | str, unit: str) -> tuple[str, str]:
    """(check, problem) for the plausibility range in SI. Both empty when the fact has no range to apply."""
    if defn.range is None or defn.kind not in ("length", "number") or isinstance(value, str):
        return "", ""
    low, high = defn.range
    if defn.kind == "length":
        if unit.lower() not in TO_MM:
            return "", f"unit '{unit}' is not a length unit"
        shown_unit = range_unit(defn)
        si = to_mm(value, unit) / (1.0 if shown_unit == "mm" else 1000.0)
        where = f"{low:g}-{high:g} {shown_unit}"
        if not defn.in_range(si):
            return "", f"{si:.10g} {shown_unit} is outside the plausible range {where}"
        return f"in range {where}", ""
    if not defn.in_range(float(value)):
        return "", f"{value:.10g} is outside the plausible range {low:g}-{high:g}"
    return f"in range {low:g}-{high:g}", ""


def _canon_unit(word: str) -> str:
    word = word.lower()
    for prefix, unit in (("millimet", "mm"), ("centimet", "cm"), ("met", "m")):
        if word.startswith(prefix):
            return unit
    return _UNIT_NAMES[word]


def stated_unit(text: str, phrase_only: bool = False) -> str:
    """The unit the text states for its dimensions: "(mm)" or "DIMENSIONS IN MM". Two different units give none."""
    patterns = (_PHRASE_UNIT,) if phrase_only else (_PHRASE_UNIT, _BRACKET_UNIT)
    found = {_canon_unit(m.group(1)) for pattern in patterns for m in pattern.finditer(text)}
    return found.pop() if len(found) == 1 else ""


def normalize_units(text: str) -> str:
    for pattern, replacement in _UNIT_WORDS:
        text = pattern.sub(replacement, text)
    return text


def _value_span(parse, text: str, full) -> tuple[int, int]:
    """Where the parsed value sits in the text: the shortest prefix that parses to it, and the latest start."""
    end = next((k for k in range(1, len(text) + 1) if parse(text[:k]) == full), len(text))
    start = next((j for j in range(end - 1, -1, -1) if parse(text[j:end]) == full), 0)
    return start, end


def _tail_problem(tail: str) -> str:
    """Why the text after a value shows it is not a clean value (a second number, other words), or empty."""
    rest = _PARENTHETICAL.sub(" ", tail).strip(" \t\"'.,;:|)]")
    if not rest:
        return ""
    if re.search(r"\d", rest):
        return f"a second number follows the value: '{tail.strip()}'"
    words = re.findall(r"[A-Za-z]+", rest)
    if re.search(r"[^A-Za-z\s.,;:]", rest) or not all(w.lower() in TAIL_WORDS for w in words):
        return f"other words follow the value: '{tail.strip()}'"
    return ""


def _imo_valid(digits: str) -> bool:
    return sum(int(d) * w for d, w in zip(digits[:6], range(7, 1, -1))) % 10 == int(digits[6])


_LENGTH_UNITS = {"MM", "M", "CM", "IN", "FT", "METRES", "METERS", "MILLIMETRES", "MILLIMETERS", "INCHES", "FEET", "INCH"}
_PERSON_UNITS = {"PERSONS", "PERSON", "P", "PERS", "PAX"}
_MINUTE_UNITS = {"MIN", "MINS", "MINUTES"}


def _allowed_qualifiers(defn: FactDef) -> set[str]:
    """The only words a parenthesis between a label and its value may hold: the fact's own unit."""
    if defn.kind == "length":
        return _LENGTH_UNITS
    if defn.property.endswith("minutes"):
        return _MINUTE_UNITS
    if "persons" in defn.property or defn.property in ("crew_complement", "passengers", "persons_on_board", "science_complement"):
        return _PERSON_UNITS
    if defn.property == "gross_tonnage":
        return {"GT"}
    return set()


def qualifier_problem(defn: FactDef, text: str) -> str:
    """A parenthesis that qualifies the label changes what the value means: "(BERTHS)", "(EXCL. CREW)", "(HRS)",
    "(EXTREME)". Only the fact's own unit may stand there, so anything else refuses the value."""
    for group in _PARENTHETICAL.findall(text):  # before or after the value: "(BERTHS) 24" and "24 (BERTHS)" alike
        inner = norm(group)
        if inner and inner not in _allowed_qualifiers(defn) | {norm(q) for q in defn.qualifiers}:
            return f"the label is qualified by '{group.strip()}', so the value may not be {defn.id}"
    return ""


def parse_value(defn: FactDef, text: str, hint: str = "") -> tuple[Parsed | None, str]:
    """Parse the value that starts the text (the part after a label, or a value cell). (value, "") or (None, why)."""
    qualified = qualifier_problem(defn, normalize_marks(text))
    if qualified:
        return None, qualified
    rest = after_label(normalize_marks(text))[:MAX_VALUE_TEXT]
    if not rest:
        return None, "nothing follows the label"
    bad = lookalike_in(defn, rest)
    if bad:
        return None, f"the value text holds the lookalike '{bad}'"
    if defn.kind in ("length", "number"):
        if not rest[0].isdigit():
            return None, f"the text after the label does not start with a number: '{rest[:30]}'"
        return _parse_numeric(defn, rest, hint)
    if defn.kind == "date":
        return _parse_date(rest)
    return _parse_text(defn, rest)


def _parse_numeric(defn: FactDef, rest: str, hint: str) -> tuple[Parsed | None, str]:
    if defn.kind == "length":
        rest = normalize_units(rest)
        result = parse_length(rest, hint)
        if result is None:
            return None, f"'{rest[:30]}' is not a length code can read without guessing (no stated unit, or ambiguous)"
        start, end = _value_span(lambda t: parse_length(t, hint), rest, result)
        while end < len(rest) and rest[end] == '"':
            end += 1  # the inch mark belongs to the value
        value, unit = float(result[0]), result[1]
        text = rest[start:end].strip()
        shown = f"{text} = {value:g} {unit}"
    else:
        product = _PRODUCT.match(rest)
        if product:
            count, each, total = (parse_number(product.group(i)) for i in (1, 2, 3))
            if None in (count, each, total):
                return None, f"'{product.group(0)}' holds a number code can't read without guessing"
            if count * each != total:
                return None, f"the stated total {total:g} is not {count:g} x {each:g} = {count * each:g}"
            text = product.group(0).strip()
            problem = _tail_problem(rest[product.end():])
            if problem:
                return None, problem
            return Parsed(float(total), "", text, f"{text}: {count:g} x {each:g} = {total:g}, checked by code"), ""
        number = parse_number(rest)
        if number is None:
            return None, f"'{rest[:30]}' is not a number code can read without guessing"
        start, end = _value_span(parse_number, rest, number)
        value, unit = float(number), ""
        text = rest[start:end].strip()
        shown = f"{text} = {value:g}"
    if start:
        return None, f"the value is not at the start of the text: '{rest[:40]}'"
    problem = _tail_problem(rest[end:])
    if problem:
        return None, problem
    return Parsed(value, unit, text, shown), ""


def _parse_date(rest: str) -> tuple[Parsed | None, str]:
    months = ("JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC")
    if not (rest[0].isdigit() or rest[:3].upper() in months):
        return None, f"the text after the label does not start a date: '{rest[:30]}'"
    found = parse_date(rest)
    if found is None:
        return None, f"'{rest[:30]}' is not a date code can read without guessing (day-first or written months only)"
    end = _value_span(parse_date, rest, found)[1]
    if re.search(r"\d", rest[end:]):
        return None, f"more digits follow the date: '{rest[end:].strip()}'"
    text = rest[:end].strip()
    return Parsed(found.isoformat(), "", text, f"{text} = {found.isoformat()}"), ""


def _parse_text(defn: FactDef, rest: str) -> tuple[Parsed | None, str]:
    value = re.sub(r"\s+", " ", rest).strip(" .,;:|")
    if not value or len(value) > 60:
        return None, "no short text follows the label"
    if defn.property == "imo_number":
        match = re.fullmatch(r"(?:NO\.?\s*)?(\d{7})", value, re.I)
        if not match:
            return None, f"'{value}' is not a 7-digit IMO number"
        value = match.group(1)
        if not _imo_valid(value):
            return None, f"IMO number {value} fails its check digit"
    else:
        for other in dictionary.load():
            if other.id != defn.id and any(len(norm(l)) > 1 for l in other.labels) and dictionary.label_matches(other, value):
                return None, f"the text holds another label ({other.id}): '{value}'"
        listed = dictionary.allowed_value(defn, value)
        if listed is None:
            # A heading like "4. Registry and dates" holds a label but no value: only a listed value is accepted.
            return None, f"'{value}' is not one of the values listed for {defn.id}"
        value = listed
    return Parsed(value, "", value, f"{value}"), ""


# -- geometry --------------------------------------------------------------------------------------------------

def line_height(line: Line) -> float:
    return max(line.box.y1 - line.box.y0, 1.0)


def page_width(dm: DocumentMap, page: int) -> float:
    for info in dm.pages:
        if info.page == page:
            return info.width_pt
    return max((l.box.x1 for l in dm.lines if l.page == page), default=612.0)


def relation(label: Line, value: Line, width: float, max_gap_lines: float = STACK_GAP) -> str | None:
    """How a value line sits with its label: "same line", "same row" (to the right), "below", or None (not near)."""
    if label.id == value.id:
        return "same line"
    if label.page != value.page:
        return None
    h = line_height(label)
    lb, vb = label.box, value.box
    if abs((lb.y0 + lb.y1) / 2 - (vb.y0 + vb.y1) / 2) <= ROW_TOLERANCE * h:
        # The value must start within the region; a long value may run past it ("7 x 350 persons = 2,450 persons").
        if vb.x0 >= lb.x1 - 1.0 and vb.x0 - lb.x0 <= MAX_REGION * width:
            return "same row"
        return None
    below = (vb.y0 + vb.y1) / 2 > (lb.y0 + lb.y1) / 2 and vb.y0 >= lb.y1 - 0.25 * h
    aligned = min(lb.x1, vb.x1) > max(lb.x0, vb.x0) or abs(vb.x0 - lb.x0) <= 4 * h
    if below and aligned and vb.y0 - lb.y1 <= max_gap_lines * h:
        return "below"
    return None


def _has_text(line: Line) -> bool:
    return bool(re.search(r"[A-Za-z0-9]", line.text))


class LineIndex:
    """The lines of each page sorted by vertical center, so a label finds its neighbors without scanning the page."""

    def __init__(self, dm: DocumentMap):
        self.dm = dm
        self.lines: dict[int, list[Line]] = {}
        self.centers: dict[int, list[float]] = {}
        self.half: dict[int, float] = {}
        for page in {l.page for l in dm.lines}:
            ordered = sorted((l for l in dm.lines if l.page == page), key=lambda l: l.box.y0 + l.box.y1)
            self.lines[page] = ordered
            self.centers[page] = [(l.box.y0 + l.box.y1) / 2 for l in ordered]
            self.half[page] = max((l.box.y1 - l.box.y0) / 2 for l in ordered)

    def near(self, label: Line, max_gap_lines: float = STACK_GAP) -> list[Line]:
        """Lines that could be on the label's row or just below it."""
        h = line_height(label)
        low = (label.box.y0 + label.box.y1) / 2 - ROW_TOLERANCE * h
        high = label.box.y1 + max_gap_lines * h + self.half.get(label.page, 0.0)
        centers = self.centers.get(label.page, [])
        return self.lines.get(label.page, [])[bisect_left(centers, low):bisect_right(centers, high)]


def find_value_line(dm: DocumentMap, label: Line, index: LineIndex | None = None) -> tuple[Line | None, str, str]:
    """The line holding the value of a label whose own line has none: (line, relation, why not)."""
    width = page_width(dm, label.page)
    near = (index or LineIndex(dm)).near(label)
    others = [l for l in near if l.id != label.id and _has_text(l)]
    row = sorted((l for l in others if relation(label, l, width) == "same row"), key=lambda l: l.box.x0)
    if row:
        return row[0], "same row", ""  # only the nearest: a cell that isn't the value blocks, it is never skipped
    below = sorted((l for l in others if relation(label, l, width) == "below"), key=lambda l: l.box.y0)
    if below:
        return below[0], "below", ""
    return None, "", "no value on the same row or directly below the label"


def stated_unit_for(dm: DocumentMap, lines: list[Line], notes: dict[int, tuple[str, str]]) -> tuple[str, str]:
    """The unit the document states for these lines: on a line, in the column header above, or in a page note."""
    for line in lines:
        unit = stated_unit(line.text)
        if unit:
            return unit, line.text
    value = lines[-1]
    h = line_height(value)
    above = sorted((l for l in dm.lines if l.page == value.page and l.box.y1 <= value.box.y0 + 0.25 * h
                    and value.box.y0 - l.box.y1 <= 6 * h and min(l.box.x1, value.box.x1) > max(l.box.x0, value.box.x0)),
                   key=lambda l: value.box.y0 - l.box.y1)
    for line in above[:3]:
        unit = stated_unit(line.text)
        if unit:
            return unit, line.text
    if value.page not in notes:
        units = {stated_unit(l.text, phrase_only=True): l.text for l in dm.lines if l.page == value.page}
        units.pop("", None)
        notes[value.page] = next(iter(units.items())) if len(units) == 1 else ("", "")
    return notes[value.page]


def parse_in_context(dm: DocumentMap, defn: FactDef, text: str, lines: list[Line],
                     notes: dict[int, tuple[str, str]]) -> tuple[Parsed | None, str, str, str]:
    """Parse the value; only a bare number looks for a stated unit. (parsed, why not, unit hint used, where stated)."""
    parsed, why = parse_value(defn, text, "")
    if parsed is not None or defn.kind != "length":
        return parsed, why, "", ""
    hint, source = stated_unit_for(dm, lines, notes)
    if not hint:
        return None, why, "", ""
    parsed, why = parse_value(defn, text, hint)
    return parsed, why, hint if parsed else "", source if parsed else ""


def union_box(lines: list[Line]) -> Box:
    return Box(page=lines[0].page, x0=min(l.box.x0 for l in lines), y0=min(l.box.y0 for l in lines),
               x1=max(l.box.x1 for l in lines), y1=max(l.box.y1 for l in lines))


def finish_candidate(defn: FactDef, subject: str, label: str, label_line: Line, value_line: Line, rel: str,
                     parsed: Parsed, hint: str, hint_source: str, method: str,
                     extra_checks: list[str] | None = None) -> tuple[FactCandidate | None, list[str]]:
    """The range and placeholder checks, then the candidate with its evidence. (candidate, []) or (None, reasons)."""
    reasons: list[str] = []
    if dictionary.is_placeholder(defn, parsed.text) or dictionary.is_placeholder(defn, str(parsed.value)):
        reasons.append(f"'{parsed.text}' is a placeholder, not a value")
    range_check, range_problem = range_result(defn, parsed.value, parsed.unit)
    if range_problem:
        reasons.append(range_problem)
    if reasons:
        return None, reasons
    lines = [label_line] if value_line.id == label_line.id else [label_line, value_line]
    checks = [f"label '{label}' is a listed label for {defn.id}", "no lookalike label in the cited text",
              {"same line": "the value is on the same line as the label",
               "same row": "the value is on the same row as the label, to its right",
               "below": "the value is directly below the label"}[rel]]
    checks.append(f"value parsed by code: {parsed.shown}")
    if hint and defn.kind == "length" and parse_length(parsed.text, "") is None:
        checks.append(f"unit {hint} stated in '{hint_source[:60]}'")
    if range_check:
        checks.append(range_check)
    if extra_checks:
        checks += extra_checks
    problems = [f"OCR confidence {l.confidence:.2f} on line {l.id} is low" for l in lines
                if l.source == "ocr" and l.confidence is not None and l.confidence < LOW_OCR]
    reading = {"method": value_line.source, "text": parsed.text, "value": parsed.value, "unit": parsed.unit,
               "confidence": value_line.confidence}
    return FactCandidate(
        fact_id=defn.id, subject=subject, property=defn.property, value=parsed.value, unit=parsed.unit,
        page=label_line.page, line_ids=[l.id for l in lines], label_text=label,
        quote=" ".join(l.text for l in lines), box=union_box(lines), method=method, readings=[reading],
        checks=checks, problems=problems), []


# -- the scan --------------------------------------------------------------------------------------------------

def _scannable() -> list[tuple[FactDef, str, list[str]]]:
    """(definition, subject, labels). The subject is "" for a closed subject, decided per line by subject_in_line."""
    out = []
    for defn in dictionary.load():
        subject = literal_subject(defn) or ("" if _CLOSED_SUBJECT.fullmatch(defn.subject) else None)
        if subject is not None and defn.id not in SKIP_FACTS:
            out.append((defn, subject, [norm(l) for l in defn.labels]))
    return out


def _item_words(item: str) -> tuple[str, ...]:
    return _ITEM_WORDS.get(item, (item.upper(),))


def subject_in_line(defn: FactDef, text: str) -> str | None:
    """For lifeboats:(port|starboard) and the like: the one item the line names, or None if it names none or several."""
    match = _CLOSED_SUBJECT.fullmatch(defn.subject)
    if not match:
        return None
    normal = f" {norm(text)} "
    named = [item for item in match.group(2).split("|") if any(f" {norm(w)} " in normal for w in _item_words(item))]
    return f"{match.group(1)}:{named[0]}" if len(named) == 1 else None


def _only_item_words(defn: FactDef, rest: str) -> bool:
    """Whether the text after a label holds only the item it names (", port side"), so the value is on another line."""
    match = _CLOSED_SUBJECT.fullmatch(defn.subject)
    if not match:
        return False
    words = set(norm(rest).split())
    allowed = {"SIDE"} | {w for item in match.group(2).split("|") for phrase in _item_words(item) for w in norm(phrase).split()}
    return bool(words) and words <= allowed


def read_label_line(dm: DocumentMap, line: Line, defn: FactDef, subject: str, label: str,
                    notes: dict[int, tuple[str, str]], index: LineIndex | None = None
                    ) -> tuple[FactCandidate | None, list[str]]:
    span = locate_label(line.text, label)
    if span is None:
        return None, [f"label '{label}' not found in the line's raw text"]
    start, end = span
    if re.search(r"[A-Za-z]", line.text[:start]):
        return None, ["the label is not at the start of the line, so the line may be about something else"]
    rest = line.text[end:]
    if after_label(normalize_marks(rest)) and not _only_item_words(defn, after_label(normalize_marks(rest))):
        value_line, rel, text = line, "same line", rest
    elif len(norm(label)) <= 1:
        return None, [f"'{label}' is a one-letter label, accepted only with its value on the same line"]
    else:
        value_line, rel, why = find_value_line(dm, line, index)
        if value_line is None:
            return None, [why]
        text = value_line.text
    parsed, why, hint, source = parse_in_context(dm, defn, text, [line] if value_line.id == line.id else [line, value_line],
                                                 notes)
    if parsed is None:
        return None, [why]
    return finish_candidate(defn, subject, label, line, value_line, rel, parsed, hint, source, "labeled_rule")


def scan_labeled(dm: DocumentMap, pages: list[int] | None = None) -> tuple[list[FactCandidate], list[dict]]:
    """Candidates found by dictionary labels, and the label lines refused, each with its reasons."""
    wanted = set(pages) if pages else None
    scannable, notes, index = _scannable(), {}, LineIndex(dm)
    found: list[FactCandidate] = []
    refused: list[dict] = []
    seen: set[tuple] = set()
    for line in dm.lines:
        if wanted and line.page not in wanted:
            continue
        normal = f" {norm(line.text)} "
        for defn, subject, labels in scannable:
            if not any(f" {l} " in normal for l in labels):
                continue
            label = dictionary.label_matches(defn, line.text)
            if label is None:
                continue
            if subject == "":
                subject = subject_in_line(defn, line.text)
                if subject is None:
                    refused.append({"fact_id": defn.id, "label": label, "line_ids": [line.id], "text": line.text,
                                    "reasons": [f"the line doesn't name exactly one of the items in {defn.subject}"]})
                    subject = ""
                    continue
            candidate, reasons = read_label_line(dm, line, defn, subject, label, notes, index)
            if candidate is None:
                refused.append({"fact_id": defn.id, "label": label, "line_ids": [line.id], "text": line.text,
                                "reasons": reasons})
                continue
            key = (candidate.fact_id, tuple(candidate.line_ids))
            if key not in seen:
                seen.add(key)
                found.append(candidate)
    return found, refused


def extract_labeled(dm: DocumentMap, pages: list[int] | None = None) -> list[FactCandidate]:
    """Every value that sits next to a listed label, parsed by code. Lookalikes and doubts give no candidate."""
    return scan_labeled(dm, pages)[0]
