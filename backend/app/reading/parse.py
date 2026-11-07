"""Parse values from the exact text they were read from. Code parses; the AI never types a number.

Ambiguous text gives None, never a guess: a wrong value is far worse than a missing one.
"""
from __future__ import annotations

import re
from datetime import date

# Primes and quotes as they appear in CAD text and OCR output.
FEET = "'’′´`"
INCH = '"”″'
_DASH = "-–—−"

_FT_IN = re.compile(
    rf"(?<![\d.])(\d{{1,4}})\s*[{FEET}]\s*[{_DASH}]?\s*(\d{{1,2}})(?:\s+(\d)\s*/\s*(\d{{1,2}}))?\s*(?:[{INCH}]|'')?(?![\d.])")
_FT_ONLY = re.compile(rf"(?<![\d.])(\d{{1,4}})\s*[{FEET}](?!\s*[{_DASH}]?\s*\d)")
_IN_ONLY = re.compile(rf"(?<![\d.\w])(\d{{1,3}}(?:\.\d+)?)\s*(?:[{INCH}]|IN\b|INCH(?:ES)?\b)", re.I)
_METRIC = re.compile(r"(?<![\d.,])(\d{1,3}(?:[ ,]\d{3})+|\d+)(?:([.,])(\d+))?\s*(MM|CM|M)\b", re.I)
_NUMBER = re.compile(r"(?<![\d.,])(\d{1,3}(?:[ ,]\d{3})+|\d+)(?:([.,])(\d+))?(?![\d])")


def _metric_value(whole: str, sep: str | None, frac: str | None, unit: str) -> float | None:
    """Comma or point decimals, and spaces or commas as thousands separators.

    "69,80 m" is 69.80 m. "1,100 mm" is 1100 mm. "12,600" with no unit is ambiguous and rejected upstream.
    """
    digits = whole.replace(" ", "")
    if "," in digits:
        groups = digits.split(",")
        if not all(len(g) == 3 for g in groups[1:]):
            return None
        if unit.lower() in ("m", "cm") and len(groups) == 2 and not sep:
            return None  # "12,600 m": 12.6 m with a decimal comma, or 12,600 m? Ambiguous, so no value.
        digits = "".join(groups)  # thousands separators
    value = float(digits)
    if sep and frac:
        if sep == "," and len(frac) == 3 and unit.lower() == "mm":
            return float(digits + frac)  # "1,100 mm" split oddly; a comma before three digits is thousands
        value = float(f"{digits}.{frac}")
    return value


def parse_length(text: str, unit_hint: str = "") -> tuple[float, str] | None:
    """The first length in the text, in its own unit ("in", "ft", "mm", "cm", "m"). Feet-inches become inches.

    unit_hint applies only to a bare number when the context states the unit (a "CLEAR WIDTH (mm)" column).
    """
    if not text:
        return None
    match = _FT_IN.search(text)
    if match:
        feet, inches = int(match.group(1)), int(match.group(2))
        if inches >= 12:
            return None
        fraction = 0.0
        if match.group(3):
            num, den = int(match.group(3)), int(match.group(4))
            if den == 0 or num >= den:
                return None
            fraction = num / den
        return feet * 12 + inches + fraction, "in"
    match = _METRIC.search(text)
    if match:
        value = _metric_value(match.group(1), match.group(2), match.group(3), match.group(4))
        if value is None:
            return None
        return value, match.group(4).lower()
    match = _FT_ONLY.search(text)
    if match:
        return float(match.group(1)), "ft"
    match = _IN_ONLY.search(text)
    if match:
        return float(match.group(1)), "in"
    if unit_hint:
        number = parse_number(text)
        if number is not None:
            return number, unit_hint.lower()
    return None


def parse_number(text: str) -> float | None:
    """The first plain number. Thousands separators are accepted only in groups of three; "12.600" is ambiguous."""
    if not text:
        return None
    match = _NUMBER.search(text)
    if not match:
        return None
    whole, sep, frac = match.group(1), match.group(2), match.group(3)
    digits = whole.replace(" ", "")
    if "," in digits:
        groups = digits.split(",")
        if not all(len(g) == 3 for g in groups[1:]):
            return None
        digits = "".join(groups)
    if sep and frac:
        if len(frac) == 3 and sep in ",." and "," not in whole and " " not in whole:
            return None  # "12.600" or "12,600": thousands or decimals? Can't tell, so no value.
        return float(f"{digits}.{frac}")
    return float(digits)


_MONTHS = {m: i for i, m in enumerate(["JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"], 1)}


def parse_date(text: str) -> date | None:
    """ISO dates, "15 Feb 2027", and day-first "15.02.2027". A slash date like 02/03/2027 is ambiguous: None."""
    if not text:
        return None
    m = re.search(r"\b(\d{4})-(\d{2})-(\d{2})\b", text)
    if m:
        return _safe_date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    m = re.search(r"\b(\d{1,2})\s+([A-Za-z]{3})[a-z]*\.?\s+(\d{4})\b", text)
    if m and m.group(2).upper()[:3] in _MONTHS:
        return _safe_date(int(m.group(3)), _MONTHS[m.group(2).upper()[:3]], int(m.group(1)))
    m = re.search(r"\b([A-Za-z]{3})[a-z]*\.?\s+(\d{1,2}),?\s+(\d{4})\b", text)
    if m and m.group(1).upper()[:3] in _MONTHS:
        return _safe_date(int(m.group(3)), _MONTHS[m.group(1).upper()[:3]], int(m.group(2)))
    m = re.search(r"\b(\d{1,2})\.(\d{1,2})\.(\d{4})\b", text)
    if m:
        return _safe_date(int(m.group(3)), int(m.group(2)), int(m.group(1)))
    return None


def _safe_date(year: int, month: int, day: int) -> date | None:
    try:
        return date(year, month, day)
    except ValueError:
        return None


def parse_scale(text: str) -> float | None:
    """A scale note as the ratio N in 1:N. '1/8"=1\'-0"' is 1:96. "NONE" or "NTS" gives None."""
    if not text:
        return None
    m = re.search(r"\b1\s*:\s*(\d{1,5}(?:\.\d+)?)\b", text)
    if m:
        return float(m.group(1))
    m = re.search(rf"(\d+)\s*/\s*(\d+)\s*[{INCH}]\s*=\s*1\s*[{FEET}]\s*[{_DASH}]?\s*0?\s*[{INCH}]?", text)
    if m and int(m.group(1)):
        inches_per_foot = int(m.group(1)) / int(m.group(2))
        return 12.0 / inches_per_foot
    m = re.search(rf"(\d+(?:\.\d+)?)\s*[{INCH}]\s*=\s*1\s*[{FEET}]\s*[{_DASH}]?\s*0?\s*[{INCH}]?", text)
    if m and float(m.group(1)):
        return 12.0 / float(m.group(1))
    return None


TO_MM = {"mm": 1.0, "cm": 10.0, "m": 1000.0, "in": 25.4, "ft": 304.8}


def to_mm(value: float, unit: str) -> float:
    return value * TO_MM[unit.lower()]
