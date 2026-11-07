"""Turn verified candidates into Facts with their evidence and tier. The tier is decided here, from the readings."""
from __future__ import annotations

import math
import re

from ..models import Evidence, Fact, Reading, Source, SourceKind, Tier
from .model import FactCandidate
from .parse import TO_MM, to_mm

EXACT_METHODS = {"table_cell", "ifc_property"}  # the value is stored as data, not read from a picture
CONFIDENCE = {Tier.A: "high", Tier.B: "high", Tier.C: "medium", Tier.D: "low"}


def _plain(value) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(value).lower())


def _matches(candidate: FactCandidate, reading: dict) -> bool:
    """Whether a reading's value equals the candidate's, exactly, after unit conversion."""
    value = reading.get("value")
    if value is None:
        return False
    unit = (reading.get("unit") or candidate.unit).lower()
    if unit in TO_MM and candidate.unit.lower() in TO_MM and not isinstance(value, str) \
            and not isinstance(candidate.value, str):
        return math.isclose(to_mm(float(value), unit), to_mm(float(candidate.value), candidate.unit),
                            rel_tol=1e-9, abs_tol=1e-9)
    if isinstance(value, (int, float)) and isinstance(candidate.value, (int, float)):
        return math.isclose(float(value), float(candidate.value), rel_tol=1e-9, abs_tol=1e-9)
    return _plain(value) == _plain(candidate.value)


def tier_for(candidate: FactCandidate) -> Tier:
    """A: exact data, or a text layer confirmed by OCR. B: two different methods agree. C: one reading. D: a problem."""
    if candidate.problems:
        return Tier.D
    if any(r.get("value") is not None and not _matches(candidate, r) for r in candidate.readings):
        return Tier.D  # a reading with a different value is a disagreement even if nobody wrote it down
    if candidate.method in EXACT_METHODS:
        return Tier.A
    methods = {r.get("method") for r in candidate.readings if _matches(candidate, r)}
    if {"text_layer", "ocr"} <= methods:
        return Tier.A
    if len(methods) >= 2:
        return Tier.B
    return Tier.C


def _locator(candidate: FactCandidate) -> str:
    ids = ", ".join(candidate.line_ids)
    if candidate.method == "table_cell":
        return ids
    if candidate.method == "ifc_property":
        return f"IFC GlobalId {ids}"
    return f"page {candidate.page}, lines {ids}" if ids else f"page {candidate.page}"


def candidate_to_fact(candidate: FactCandidate, file: str, doc_id: str = "", revision: str = "",
                      kind: SourceKind = SourceKind.DOCUMENT) -> Fact:
    tier = tier_for(candidate)
    readings = [Reading(method=str(r.get("method", "")), text=str(r.get("text", "")), value=r.get("value"),
                        unit=str(r.get("unit") or ""), confidence=r.get("confidence"))
                for r in candidate.readings]
    evidence = Evidence(file=file, doc_id=doc_id, revision=revision, page=candidate.page, box=candidate.box,
                        quote=candidate.quote, element_ids=list(candidate.line_ids), readings=readings,
                        checks=list(candidate.checks), problems=list(candidate.problems))
    source = Source(kind=kind, file=file, locator=_locator(candidate), quote=candidate.quote)
    return Fact(subject=candidate.subject, property=candidate.property, value=candidate.value, unit=candidate.unit,
                source=source, confidence=CONFIDENCE[tier], evidence=evidence, tier=tier)


def facts_from_candidates(candidates: list[FactCandidate], file: str, doc_id: str = "", revision: str = "",
                          kind: SourceKind = SourceKind.DOCUMENT) -> list[Fact]:
    return [candidate_to_fact(c, file, doc_id, revision, kind) for c in candidates]
