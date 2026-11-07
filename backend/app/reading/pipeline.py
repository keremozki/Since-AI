"""Read one uploaded file into facts, each with its evidence and tier. Code reads; the AI only points and transcribes.

PDF or image: page map (text layer, OCR where there is none) -> title block -> labeled values found by code ->
the AI points at lines for facts code didn't find, and code verifies every pointer -> a second, independent
reading of every value (OCR of the crop for text-layer values, AI transcription of the crop for OCR values) ->
facts, tiered by how their readings agree.
Spreadsheet or CSV schedule: cells -> facts (tier A, the value is stored as data).
IFC model: properties -> facts (tier A). OverallWidth is the door leaf opening, never the clear width.

In offline mode an AI step that has no recorded answer yet is skipped and named in `pending`, so the file is
still read by code and nothing waits on a guess.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from .. import dictionary
from ..ai_gateway import AIResponsePending
from ..evidence import IMAGE_SUFFIXES, image_as_pdf
from ..llm import AIUnavailable, BudgetExceeded, ModelRefused
from ..models import Box, Evidence, Fact, Reading, Source, SourceKind, Tier
from .model import DocumentMap, FactCandidate
from .pagemap import build_document_map
from .calibrate import calibrate_page
from .labeled import SKIP_FACTS, extract_labeled, norm
from .parse import parse_scale, to_mm
from .pointing import point_facts
from .readers import read_ifc, read_table_file
from .second_reading import add_second_readings, attach_reading, ocr_box, render_crop, transcription_request
from .to_facts import facts_from_candidates

TABLE_SUFFIXES = {".xlsx", ".csv"}
DRAWING_SUFFIXES = {".pdf"} | IMAGE_SUFFIXES
MAX_TRANSCRIPTIONS = 40  # AI transcriptions per file; more are left at one reading, so tier C
AI_STOPPED = (AIUnavailable, BudgetExceeded, ModelRefused)  # no key, API down, cap reached: code's own reading still stands


@dataclass
class ReadResult:
    file: str
    kind: str  # drawing, table, ifc
    facts: list[Fact] = field(default_factory=list)
    status: str = "read"  # read, partly read, couldn't be read
    notes: list[str] = field(default_factory=list)
    title_block: dict | None = None
    pages: list[dict] = field(default_factory=list)
    rejected: list[dict] = field(default_factory=list)  # AI pointers code refused, with the reasons
    label_suggestions: list[dict] = field(default_factory=list)  # wordings the AI found that the dictionary lacks
    pending: list[str] = field(default_factory=list)  # AI requests waiting for an answer
    calibrations: list[dict] = field(default_factory=list)  # the drawing as a measuring tool, page by page
    document_map: DocumentMap | None = None

    def summary(self) -> dict:
        tiers: dict[str, int] = {}
        for fact in self.facts:
            key = fact.tier.value if fact.tier else "?"
            tiers[key] = tiers.get(key, 0) + 1
        return {"file": self.file, "kind": self.kind, "status": self.status, "facts": len(self.facts), "tiers": tiers,
                "notes": self.notes, "title_block": self.title_block, "pages": self.pages,
                "rejected_pointers": self.rejected, "pending": self.pending, "calibrations": self.calibrations,
                "label_suggestions": self.label_suggestions}


def can_read(name: str) -> bool:
    suffix = Path(name).suffix.lower()
    return suffix in TABLE_SUFFIXES | DRAWING_SUFFIXES | {".ifc"}


MIN_RULER_FOR_TIER_B = 8  # frame labels on the fitted line before a measured scale counts as two-way checked


def scale_facts(dm: DocumentMap, name: str, pdf_bytes: bytes, facts: list[Fact], kind: SourceKind,
                result: ReadResult) -> list[Fact]:
    """The scale each page is really drawn at, measured by code, next to the scale its note states.

    The frame ruler gives points per frame; the frame spacing stated on the same document turns that into a scale.
    A ruler with many labels on one straight line and a spacing read at tier A gives tier B; anything less is C.
    """
    spacing = next((f for f in facts if f.subject == "ship" and f.property == "frame_spacing" and f.tier in (Tier.A, Tier.B)), None)
    spacing_mm = to_mm(float(spacing.value), spacing.unit) if spacing is not None else None
    doc = dm.title_block.drawing_no or Path(name).stem
    out: list[Fact] = []
    for info in dm.pages:
        cal = calibrate_page(dm, info.page, pdf_bytes, stated_frame_spacing_mm=spacing_mm)
        if cal.ruler is None and cal.ladder is None:
            continue
        result.calibrations.append(cal.model_dump(exclude={"ruler": {"rejected"}, "ladder": {"rejected", "levels"}}))
        base = dict(subject=f"drawing:{doc}", source=Source(kind=kind, file=name, locator=f"page {info.page}"))
        evidence = dict(file=name, doc_id=dm.title_block.drawing_no, revision=dm.title_block.revision, page=info.page)
        ratios = sorted({r for r in (parse_scale(n) for n in cal.scale_noted) if r})
        if len(ratios) == 1:
            note = next(n for n in cal.scale_noted if parse_scale(n) == ratios[0])
            out.append(Fact(**{**base, "source": base["source"].model_copy(update={"quote": note})}, property="scale_noted",
                            value=ratios[0], tier=Tier.A if dm.pages[info.page - 1].kind == "vector_text" else Tier.C,
                            evidence=Evidence(**evidence, quote=note, checks=["scale note read from the sheet's text"])))
        if cal.real_mm_per_pt and cal.scale_measured:
            measured = abs(float(cal.scale_measured.split(":", 1)[1]))  # frames may run either way along the sheet
            strong = (cal.methods_agree is True or (cal.ruler is not None and cal.ruler.used >= MIN_RULER_FOR_TIER_B
                                                     and spacing is not None and spacing.tier == Tier.A))
            derived_from = ["ship.frame_spacing"] if spacing is not None else []
            certificate = cal.certificate.replace(cal.scale_measured, f"1:{measured:.1f}")
            out.append(Fact(**{**base, "source": base["source"].model_copy(update={"quote": certificate})},
                            property="scale_measured", value=round(measured, 1), tier=Tier.B if strong else Tier.C,
                            derived_from=derived_from, derivation=certificate,
                            evidence=Evidence(**evidence, quote=certificate,
                                              readings=[Reading(method="geometry", text=f"1:{measured:.1f}", value=round(measured, 1))],
                                              checks=[certificate])))
    return out


MAX_SUGGESTED_LABEL = 40
TAG_RADIUS_PT = 60.0  # a value this close to its tag, measured between box centers
TAG_RATIO = 1.4  # the next nearest value must be this much farther, or the link is ambiguous
_DOOR_TAG = re.compile(r"\d{4}")
_STAIR_TAG = re.compile(r"STAIR\s+([A-Z0-9]{1,3})")
_PLAIN = re.compile(r"\d{3,4}")
_PERSONS = re.compile(r"(\d{1,4})\s*P")


def _center(line):
    return (line.box.x0 + line.box.x1) / 2, (line.box.y0 + line.box.y1) / 2


def _distance(a, b) -> float:
    (ax, ay), (bx, by) = _center(a), _center(b)
    return ((ax - bx) ** 2 + (ay - by) ** 2) ** 0.5


def _sheet_says(lines, *phrases) -> object:
    return next((l for l in lines if all(p in norm(l.text) for p in phrases)), None)


def tag_candidates(dm: DocumentMap) -> list[FactCandidate]:
    """Values a drawing writes beside a tag, read only when the sheet itself says what they mean.

    The legend must say what a tag is (DOOR ... TAG = DOOR NUMBER; STAIR: CLEAR WIDTH (MM), PERSONS SERVED (P)), and a
    note must say the widths are clear widths and the unit. A value is linked to a tag only if it is the only one near
    the tag, and the tag is the nearest tag to it. These links are made by position, so they stay at one reading
    (tier C): they can raise a conflict or show a revision's change, but never back a pass or fail on their own.
    """
    out: list[FactCandidate] = []
    for info in dm.pages:
        lines = [l for l in dm.page_lines(info.page) if l.text.strip()]
        unit_note = _sheet_says(lines, "DIMENSIONS IN MM")
        clear_note = _sheet_says(lines, "WIDTHS SHOWN ARE CLEAR WIDTHS")
        if unit_note is None or clear_note is None:
            continue
        door_legend = _sheet_says(lines, "DOOR", "TAG", "DOOR NUMBER")
        stair_legend = _sheet_says(lines, "STAIR", "CLEAR WIDTH", "MM", "PERSONS SERVED")
        plain = [l for l in lines if _PLAIN.fullmatch(l.text.strip())]
        door_tags = [l for l in plain if _DOOR_TAG.fullmatch(l.text.strip()) and not 500 <= int(l.text) <= 3000] if door_legend else []
        stair_tags = [l for l in lines if _STAIR_TAG.fullmatch(l.text.strip())] if stair_legend else []
        tags = door_tags + stair_tags

        def link(tag, pool):
            near = sorted(((d, l) for l in pool if l.id != tag.id and (d := _distance(tag, l)) <= TAG_RADIUS_PT), key=lambda x: x[0])
            if not near or (len(near) > 1 and near[1][0] < TAG_RATIO * near[0][0]):
                return None
            value = near[0][1]
            nearest_tag = min(tags, key=lambda t: _distance(t, value))
            return value if nearest_tag.id == tag.id else None

        def add(fact_id, subject, tag, value_line, value, unit, legend, extra):
            defn = dictionary.by_id(fact_id)
            if defn is None:
                return
            cited = [tag, value_line, legend, clear_note, unit_note]
            out.append(FactCandidate(
                fact_id=fact_id, subject=subject, property=defn.property, value=float(value), unit=unit, page=info.page,
                line_ids=[l.id for l in cited], label_text=tag.text, quote=f"{tag.text} / {value_line.text}",
                box=Box(page=info.page, x0=min(tag.box.x0, value_line.box.x0), y0=min(tag.box.y0, value_line.box.y0),
                        x1=max(tag.box.x1, value_line.box.x1), y1=max(tag.box.y1, value_line.box.y1)),
                method="drawing_tag",
                readings=[{"method": value_line.source, "text": value_line.text, "value": float(value), "unit": unit}],
                checks=[f"the sheet's legend says: '{legend.text}'", f"note: '{clear_note.text}'", f"note: '{unit_note.text}'",
                        f"'{value_line.text}' is the only value within {TAG_RADIUS_PT:g} pt of '{tag.text}', and that is its "
                        f"nearest tag", *extra]))

        widths = [l for l in plain if l not in door_tags and 500 <= int(l.text) <= 3000]
        for tag in door_tags:
            value = link(tag, widths)
            if value is not None:
                add("door.clear_width", f"door-number:{tag.text.strip()}", tag, value, int(value.text), "mm", door_legend, [])
        persons = [l for l in lines if _PERSONS.fullmatch(l.text.strip())]
        for tag in stair_tags:
            name = _STAIR_TAG.fullmatch(tag.text.strip()).group(1)
            value = link(tag, widths)
            if value is not None:
                add("stair.clear_width", f"stair:{name}", tag, value, int(value.text), "mm", stair_legend, [])
            count = link(tag, persons)
            if count is not None:
                add("stair.persons_served", f"stair:{name}", tag, count, int(_PERSONS.fullmatch(count.text.strip()).group(1)),
                    "", stair_legend, ["'P' means persons served, per the legend"])
    return out


def _sheet_tag_note() -> str:
    return "Values written beside door and stair tags, linked by position as the sheet's legend defines them (one reading)."


def label_suggestions(dm: DocumentMap, name: str, rejected: list[dict]) -> list[dict]:
    """A pointer refused only because its label isn't in the dictionary may show a wording the dictionary lacks.

    It becomes a suggestion for an engineer, never a value: once a person approves the wording, code reads that
    label itself on every document from then on. Only short label lines with words and no digits qualify.
    """
    out, seen = [], set()
    for item in rejected:
        pointer, reasons = item.get("pointer", {}), item.get("reasons", [])
        if not any(r.startswith("the label line holds no listed label") for r in reasons):
            continue
        line = dm.line((pointer.get("label_line_ids") or [""])[0])
        value = dm.line((pointer.get("value_line_ids") or [""])[0])
        if line is None or value is None:
            continue
        text = " ".join(line.text.split()).strip(" :.-")
        if not text or len(text) > MAX_SUGGESTED_LABEL or any(ch.isdigit() for ch in text) or not any(ch.isalpha() for ch in text):
            continue
        key = (pointer.get("fact_id"), text.upper())
        if key in seen:
            continue
        seen.add(key)
        out.append({"fact_id": pointer.get("fact_id"), "label": text, "file": name, "page": line.page,
                    "label_line": line.id, "value_text": value.text[:80], "why": pointer.get("note", "")})
    return out


def presence_candidates(dm: DocumentMap, pdf_bytes: bytes) -> list[FactCandidate]:
    """Documents that must exist, like an evacuation analysis: found when the document's own title names one.

    Only the title counts (the first line of page 1, or the title block title). A mention elsewhere, such as
    "Evacuation analysis: see EA-101" in a specification, is a reference, not the document. The title is read
    twice, from the text layer and by OCR of its crop, so the finding has two independent readings.
    """
    page_one = [l for l in dm.page_lines(1) if l.text.strip()]
    titles = page_one[:1] + [l for l in dm.lines if dm.title_block.title and norm(l.text) == norm(dm.title_block.title)]
    out = []
    for fact_id in sorted(SKIP_FACTS):
        defn = dictionary.by_id(fact_id)
        if defn is None:
            continue
        for line in titles:
            label = dictionary.label_matches(defn, line.text)
            if label is None:
                continue
            readings = [{"method": line.source, "text": line.text, "value": "yes"}]
            checks = [f"the document's title names it: '{line.text[:80]}'"]
            if line.source == "text_layer":
                second = ocr_box(pdf_bytes, line.page, line.box)
                named = dictionary.label_matches(defn, second.get("text", "")) is not None
                readings.append({"method": "ocr", "text": second.get("text", ""), "value": "yes" if named else None,
                                 "confidence": second.get("confidence")})
                if named:
                    checks.append(f"second reading (ocr) of the title also names it: '{second.get('text', '')[:80]}'")
            out.append(FactCandidate(fact_id=fact_id, subject=defn.subject, property=defn.property, value="yes",
                                     page=line.page, line_ids=[line.id], label_text=label, quote=line.text, box=line.box,
                                     method="document_title", readings=[r for r in readings if r["value"] is not None],
                                     checks=checks))
            break
    return out


def _key(candidate: FactCandidate) -> tuple:
    return candidate.fact_id, candidate.subject, tuple(candidate.line_ids)


def _merge(found: list[FactCandidate], pointed: list[FactCandidate]) -> list[FactCandidate]:
    """Code's own finds first. An AI pointer at the same lines adds nothing; a pointer elsewhere is a new candidate."""
    seen = {_key(c) for c in found}
    return found + [c for c in pointed if _key(c) not in seen]


def _only_ocr(candidate: FactCandidate) -> bool:
    methods = {r.get("method") for r in candidate.readings}
    return "ocr" in methods and "text_layer" not in methods and "ai_transcription" not in methods


def _transcribe(ai, candidates: list[FactCandidate], dm: DocumentMap, pdf_bytes: bytes,
                result: ReadResult) -> list[FactCandidate]:
    """The second reading of an OCR value: an AI transcription of the same crop, parsed and compared by code."""
    out, asked = [], 0
    for candidate in candidates:
        if not _only_ocr(candidate) or candidate.box is None or asked >= MAX_TRANSCRIPTIONS:
            out.append(candidate)
            continue
        asked += 1
        line = dm.line(candidate.line_ids[-1]) if candidate.line_ids else None
        box = line.box if line is not None else candidate.box
        system, content, schema = transcription_request(render_crop(pdf_bytes, candidate.page, box))
        try:
            answer = ai.structured(system, content, schema, effort="low")
        except AIResponsePending as pending:
            result.pending.append(pending.request_id)
            out.append(candidate)
            continue
        except AI_STOPPED as error:
            result.notes.append(f"The AI's second readings stopped ({error}), so the rest keep one reading.")
            return out + candidates[len(out):]
        if not answer.get("legible"):
            unread = candidate.model_copy(deep=True)
            unread.readings.append({"method": "ai_transcription", "text": "", "value": None, "unit": ""})
            out.append(unread)
            continue
        out.append(attach_reading(candidate, {"method": "ai_transcription", "text": answer.get("text", "")}))
    return out


def read_drawing(ai, name: str, data: bytes, cache_dir: Path | None, pages: list[int] | None = None,
                 use_ai: bool = True, lessons: str = "") -> ReadResult:
    result = ReadResult(file=name, kind="drawing")
    dm = build_document_map(data, name, cache_dir=cache_dir, pages=pages)
    result.document_map = dm
    result.status = dm.status
    result.pages = [p.model_dump(include={"page", "kind", "text_words", "ocr_used", "text_layer_agrees"}) for p in dm.pages]
    if dm.status_reason:
        result.notes.append(dm.status_reason)
    if dm.status == "couldn't be read":
        return result
    tb = dm.title_block
    result.title_block = tb.model_dump()
    found = extract_labeled(dm, pages)
    result.notes.append(f"Code found {len(found)} labeled value(s).")
    candidates = found
    if use_ai:
        # Presence facts come from a document's own title only (presence_candidates), never from a pointer.
        wanted = sorted({d.id for d in dictionary.load() if d.ai_pointing} - {c.fact_id for c in found} - SKIP_FACTS)
        try:
            pointed, rejected = point_facts(ai, dm, wanted, pages, lessons)
            result.rejected = rejected
            result.label_suggestions = label_suggestions(dm, name, rejected)
            result.notes.append(f"The AI pointed at {len(pointed) + len(rejected)} place(s); code verified {len(pointed)} "
                                f"and refused {len(rejected)}.")
            candidates = _merge(found, pointed)
        except AIResponsePending as pending:
            result.pending.append(pending.request_id)
            result.notes.append("The AI pointing step waits for an answer (offline mode); code's own finds are used meanwhile.")
        except AI_STOPPED as error:
            result.notes.append(f"The AI pointing step couldn't run ({error}); code's own finds are used.")
    pdf_bytes = data if Path(name).suffix.lower() == ".pdf" or data[:5] == b"%PDF-" else image_as_pdf(data)
    candidates = add_second_readings(candidates, dm, pdf_bytes)
    tagged = tag_candidates(dm)
    if tagged:
        result.notes.append(f"{len(tagged)} value(s) read beside door and stair tags, as the sheet's legend defines them.")
    candidates = _merge(candidates, tagged)
    present = presence_candidates(dm, pdf_bytes)
    if present:
        result.notes.append("The document's title names it as: " + ", ".join(c.fact_id for c in present) + ".")
    candidates += present
    if use_ai:
        candidates = _transcribe(ai, candidates, dm, pdf_bytes, result)
    kind = SourceKind.IMAGE if Path(name).suffix.lower() in IMAGE_SUFFIXES else SourceKind.DOCUMENT
    result.facts = facts_from_candidates(candidates, name, doc_id=tb.drawing_no, revision=tb.revision, kind=kind)
    result.facts += scale_facts(dm, name, pdf_bytes, result.facts, kind, result)
    if result.pending:
        result.notes.append(f"{len(result.pending)} AI step(s) wait for an answer, so some values have one reading only.")
    return result


def read_upload(ai, name: str, data: bytes, cache_dir: Path | None = None, pages: list[int] | None = None,
                use_ai: bool = True, lessons: str = "") -> ReadResult:
    suffix = Path(name).suffix.lower()
    if suffix in TABLE_SUFFIXES:
        candidates, info = read_table_file(data, name)
        result = ReadResult(file=name, kind="table", facts=facts_from_candidates(candidates, name))
        result.notes.append(f"Read {len(candidates)} value(s) from table cells.")
        result.notes += [str(n) for n in info.get("notes", [])] if isinstance(info, dict) else []
        if isinstance(info, dict) and info.get("status"):
            result.status = info["status"]
        return result
    if suffix == ".ifc":
        candidates, info = read_ifc(data, name)
        result = ReadResult(file=name, kind="ifc", facts=facts_from_candidates(candidates, name))
        result.notes.append(f"Read {len(candidates)} value(s) from IFC properties.")
        result.notes += [str(n) for n in info.get("notes", [])] if isinstance(info, dict) else []
        if isinstance(info, dict) and info.get("status"):
            result.status = info["status"]
        return result
    if suffix in DRAWING_SUFFIXES:
        return read_drawing(ai, name, data, cache_dir, pages, use_ai, lessons)
    raise ValueError(f"Unsupported file type: {suffix or name}.")
