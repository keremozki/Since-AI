"""The second code reader for PDFs (app.drawing): door tags, corridors, and ramps with their written values.

It keeps the trust rule the pipeline uses. A value counts only when two independent readings agree, so each one
it finds is read again by OCR of its line. The label and value are tied by position, so the best this can give is
tier B, and only when the pairing was clear. Everything else stays below B and has to be confirmed by an engineer.
"""
from __future__ import annotations

import re

from .. import drawing
from ..models import Box, Evidence, Fact, Reading, Tier
from ..units import is_length_unit, to_mm
from .second_reading import ocr_line

AGREE_MM = 0.5  # readings of a written value must match; this only absorbs rounding from unit conversion
SURE_OCR = 0.8  # below this, an OCR reading that differs is more likely a poor reading than a real difference
MAX_SECOND_READINGS = 500  # per file; a sheet with more values leaves the rest at one reading
_PAGE = re.compile(r"page\s+(\d+)", re.IGNORECASE)
_NUMBER = re.compile(r"\d+(?:[.,]\d+)?")


def _same(a: Fact, b: Fact) -> bool:
    if isinstance(a.value, str) or isinstance(b.value, str):
        return str(a.value).strip().lower() == str(b.value).strip().lower()
    if is_length_unit(a.unit) and is_length_unit(b.unit):
        return abs(to_mm(float(a.value), a.unit) - to_mm(float(b.value), b.unit)) <= AGREE_MM
    return a.unit == b.unit and abs(float(a.value) - float(b.value)) < 1e-6


def _numbers(text: str) -> list[str]:
    return [n.replace(",", ".") for n in _NUMBER.findall(text)]


def _holds(seen: list[str], wanted: list[str]) -> bool:
    return bool(wanted) and any(seen[i:i + len(wanted)] == wanted for i in range(len(seen) - len(wanted) + 1))


def grade(fact: Fact, data: bytes, ocr=ocr_line) -> Fact:
    """Read the value a second way and set its tier. The fact keeps its first reading as evidence either way.

    The digits are compared as written, because OCR is reliable on digits and poor on marks: it can read 32" as 32'.
    The unit comes from the text layer, the first reading.
    """
    page, box_values = _PAGE.search(fact.source.locator), fact.meta.get("box")
    first = Reading(method="text_layer", text=str(fact.meta.get("raw", fact.source.quote)), value=fact.value, unit=fact.unit)

    def graded(tier: Tier, readings: list[Reading], **details) -> Fact:
        evidence = dict(file=fact.source.file, quote=fact.source.quote)
        if page is not None and box_values is not None:
            evidence.update(page=int(page.group(1)), box=box)
        return fact.model_copy(update={"tier": tier, "evidence": Evidence(**evidence, readings=readings, **details)})

    box = None
    if page is None or box_values is None:
        return graded(Tier.C, [first], checks=["no position kept for a second reading"])
    x0, y0, x1, y1 = box_values
    box = Box(page=int(page.group(1)), x0=x0, y0=y0, x1=x1, y1=y1)
    if fact.meta.get("ocr_text"):
        return graded(Tier.C, [first], checks=["the page's text is itself OCR, so a second OCR isn't independent"])
    try:
        second = ocr(data, box.page, box)
    except Exception as error:  # OCR can fail on odd pages; the value then simply has one reading
        return graded(Tier.C, [first], checks=[f"no second reading ({type(error).__name__})"])
    text, confidence = str(second.get("text", "")), second.get("confidence")
    reading = Reading(method="ocr", text=text, confidence=confidence)
    seen = _numbers(text)
    if not seen:
        return graded(Tier.C, [first, reading], checks=["OCR of the line found no number, so there is one reading"])
    if not _holds(seen, _numbers(first.text)):
        # "D40130" for tag D401 and width 30: OCR ran them together. That isn't a second reading, and isn't a disagreement.
        if any(number.endswith(_numbers(first.text)[-1]) for number in seen):
            return graded(Tier.C, [first, reading], checks=["OCR ran the label and value together, so there is one reading"])
        if (confidence or 0) < SURE_OCR:
            return graded(Tier.C, [first, reading], checks=["OCR of the line was too poor to compare, so there is one reading"])
        return graded(Tier.D, [first, reading], problems=[f"second reading (ocr) disagrees: it read '{text}', the text layer has '{first.text}'"])
    agreed = reading.model_copy(update={"value": fact.value, "unit": fact.unit})
    if fact.meta.get("ambiguous_pairing") or fact.confidence == "low":
        return graded(Tier.C, [first, agreed], checks=["second reading (ocr) agrees on the digits"],
                      problems=["the label and value are paired ambiguously"])
    return graded(Tier.B, [first, agreed], checks=["second reading (ocr) agrees on the digits"])


def extra_facts(name: str, data: bytes, pages: list[int] | None, already: list[Fact], ocr=ocr_line) -> list[Fact]:
    """What this reader adds to the pipeline's facts. A value both found stays once; a difference stays as a conflict."""
    out: list[Fact] = []
    checked = 0
    for fact in drawing.read_pdf(data, name, pages).facts:
        twins = [f for f in already if f.key() == fact.key()]
        if any(_same(twin, fact) for twin in twins):
            continue
        if isinstance(fact.value, str):  # "shown on page 2": it says a label exists, and backs no result
            out.append(fact)
        elif checked >= MAX_SECOND_READINGS:
            out.append(fact.model_copy(update={"tier": Tier.C}))
        else:
            checked += 1
            out.append(grade(fact, data, ocr))
    return out
