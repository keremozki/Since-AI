"""The fixed list of facts that AI may report. Anything else is dropped by code."""
from __future__ import annotations

import re

from .models import Fact, Source
from .units import is_length_unit

# (subject pattern, property, kind, meaning). Kind: "length", "number", or "text".
VOCABULARY = [
    (r"door-number:\d+", "clear_width", "length", "clear opening width of the door with this number"),
    (r"door-number:\d+", "shown_on", "text", "sheet or page where the door is tagged, when no width is written for it"),
    (r"door-type:.+", "clear_width", "length", "clear opening width for a door part type, by its exact name"),
    (r"corridor:.+", "clear_width", "length", "clear width of a corridor or walking surface, by its label on the drawing"),
    (r"corridor:.+", "shown_on", "text", "sheet or page where the corridor is labelled, when no width is written for it"),
    (r"ramp:.+", "shown_on", "text", "sheet or page where the ramp is labelled, when no slope or rise and run is written for it"),
    (r"ramp:.+", "rise", "length", "vertical rise of a ramp run"),
    (r"ramp:.+", "run", "length", "horizontal length of a ramp run"),
    (r"ramp:.+", "slope_run_per_rise", "number", "N from a slope written 1:N on the drawing. Only if written, never computed"),
    (r"liferaft", "capacity_persons", "number", "rated capacity of each liferaft, in persons"),
    (r"ship", "persons_on_board", "number", "total persons the ship carries, only if stated as one total"),
    (r"ship", "crew_complement", "number", "number of crew, as stated, or crew berths if only those are given"),
    (r"ship", "science_complement", "number", "number of scientists and marine technicians, as stated"),
    (r"ship", "length_overall", "length", "overall length of the ship"),
    (r"ship", "beam", "length", "moulded beam at the main deck. Never use an overall beam"),
    (r"ship", "lightship_weight", "number", "lightship weight, with its unit (LT or t)"),
    (r"ship", "main_vertical_zones", "number", "number of main vertical fire zones"),
    (r"bridge", "eye_height_above_water", "length", "height of the conning position eye line above the waterline"),
    (r"bridge", "obstruction_height_above_water", "length", "height of the highest forward obstruction above the waterline"),
    (r"bridge", "eye_to_obstruction", "length", "horizontal distance from the conning position to that obstruction"),
    (r"bridge", "eye_to_bow", "length", "horizontal distance from the conning position to the bow"),
    (r"masthead_forward", "height_above_hull", "length", "height of the forward masthead light above the hull"),
    (r"evacuation", "time_minutes", "number", "total evacuation time from the analysis, in minutes"),
]

FACT_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["subject", "property", "value_number", "value_text", "unit", "quote", "locator", "confidence"],
    "properties": {
        "subject": {"type": "string"},
        "property": {"type": "string"},
        "value_number": {"type": ["number", "null"]},
        "value_text": {"type": ["string", "null"]},
        "unit": {"type": "string"},
        "quote": {"type": "string", "description": "The exact words or dimension text that this value was read from."},
        "locator": {"type": "string", "description": "Where it was found, like a page, sheet, zone, or table."},
        "confidence": {"type": "string", "enum": ["high", "medium", "low"]},
    },
}


def vocabulary_text() -> str:
    lines = []
    for subject, prop, _kind, meaning in VOCABULARY:
        shown = subject.replace(r"\d+", "<number>").replace("door-type:.+", "door-type:<exact part type name>").replace(".+", "<label on the drawing>")
        lines.append(f"- subject {shown}, property {prop}: {meaning}")
    return "\n".join(lines)


def to_fact(raw: dict, source_template: Source) -> Fact | None:
    """Accept an AI-reported fact only if it fits the vocabulary and carries its evidence."""
    subject, prop = str(raw.get("subject", "")).strip(), str(raw.get("property", "")).strip()
    entry = next((v for v in VOCABULARY if v[1] == prop and re.fullmatch(v[0], subject)), None)
    if entry is None:
        return None
    kind = entry[2]
    unit = str(raw.get("unit") or "").strip()
    if kind == "length":
        unit = unit.lower()
    number = raw.get("value_number")
    if kind == "text":
        value = raw.get("value_text")
    else:
        value = number
        if value is None or isinstance(value, bool):
            return None
        value = float(value)
        if value <= 0:
            return None
    if kind == "length" and not is_length_unit(unit):
        return None
    if not value and value != 0:
        return None
    source = source_template.model_copy(update={
        "locator": str(raw.get("locator") or source_template.locator),
        "quote": str(raw.get("quote") or ""),
    })
    return Fact(subject=subject, property=prop, value=value, unit=unit, source=source,
                confidence=raw.get("confidence", "medium") if raw.get("confidence") in ("high", "medium", "low") else "medium")
