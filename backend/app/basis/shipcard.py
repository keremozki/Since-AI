"""The ship card: the particulars that decide which rules apply to one hull, each with where it came from.

A value on the card is stated, read from a fact, or confirmed by a person. Nothing is derived silently:
a total such as persons on board is only ever a suggestion until a person confirms it.
"""
from __future__ import annotations

import math
import re
from collections import defaultdict
from dataclasses import dataclass
from datetime import date

from pydantic import BaseModel, Field, model_validator

from .. import dictionary
from ..models import Fact, ShipProfile, SourceKind
from ..reading.parse import parse_date, parse_length, parse_number
from ..units import is_length_unit, to_mm


@dataclass(frozen=True)
class FieldDef:
    key: str
    label: str  # short noun phrase for reasons and questions
    kind: str  # text, number, length (stored in m), date
    meaning: str
    unit: str = ""
    choices: tuple[str, ...] = ()


def _defs(*items: FieldDef) -> dict[str, FieldDef]:
    return {item.key: item for item in items}


FIELDS = _defs(
    FieldDef("ship_type", "ship type", "text",
             "The SOLAS ship type that decides which chapters apply: passenger (a ship carrying more than 12 passengers), "
             "cargo, special_purpose (SPS Code: a ship carrying more than 12 special personnel), or ro_ro_passenger.",
             choices=("passenger", "cargo", "special_purpose", "ro_ro_passenger")),
    FieldDef("passengers", "number of passengers", "number",
             "Passengers the ship is certified to carry. Excludes crew and special personnel; not persons on board."),
    FieldDef("special_personnel", "number of special personnel", "number",
             "Special personnel (SPS Code 1.3.11): persons who are not passengers or crew and are carried because of the "
             "ship's special purpose, such as scientists and technicians."),
    FieldDef("crew", "crew complement", "number", "Number of crew, as stated."),
    FieldDef("persons_on_board", "persons on board", "number",
             "Total persons the ship is certified to carry (passengers, special personnel and crew), as stated on the LSA "
             "plan or Record of Equipment. Never a berth count and never summed silently."),
    FieldDef("length_overall_m", "length overall", "length",
             "Length overall, extreme, in meters. The length of COLREG Rule 3(j) and SOLAS V/2.4. Not LBP, waterline "
             "length or Load Line length.", unit="m"),
    FieldDef("load_line_length_m", "Load Line length", "length",
             "Load Line length L in meters (SOLAS III/3.12): 96% of the total length on a waterline at 85% of the least "
             "moulded depth, or stem to rudder stock axis if greater.", unit="m"),
    FieldDef("breadth_greatest_m", "greatest breadth", "length",
             "Greatest breadth in meters (COLREG Rule 3(j)). Not the moulded beam.", unit="m"),
    FieldDef("beam_m", "moulded beam", "length", "Moulded beam at the main deck, in meters. Not used for COLREG light heights.",
             unit="m"),
    FieldDef("gross_tonnage", "gross tonnage", "number", "Gross tonnage under the Tonnage Convention 1969.", unit="GT"),
    FieldDef("flag", "flag", "text", "Flag state, as stated. Context only: no rule here changes with the flag."),
    FieldDef("contract_date", "contract date", "date",
             "Date the building contract was signed between the prospective owner and the shipbuilder "
             "(MSC.1/Circ.1350/Rev.1, footnote)."),
    FieldDef("keel_date", "keel-laying date", "date",
             "Date the keel was laid or the ship was at a similar stage of construction (SOLAS 'constructed'): construction "
             "identifiable with the ship has begun and assembly of at least 50 tonnes or 1% of the estimated structural mass "
             "has started. Not the contract, launch or delivery date."),
    FieldDef("delivery_date", "delivery date", "date", "Date the ship is, or is planned to be, delivered."),
    FieldDef("voyage", "voyage type", "text",
             "international: international voyages that are not short; short_international: short international voyages "
             "as SOLAS defines them; domestic: not international.",
             choices=("international", "short_international", "domestic")),
    FieldDef("propulsion", "propulsion", "text",
             "power_driven or sailing, as COLREG defines them. A power-driven vessel is not a sailing vessel under sail.",
             choices=("power_driven", "sailing")),
    FieldDef("main_vertical_zones", "number of main vertical zones", "number",
             "Number of main vertical zones: sections of the hull, superstructure and deckhouses divided by A class "
             "divisions (SOLAS II-2/3, definition 32)."),
    FieldDef("overnight_passengers", "number of overnight passengers", "number",
             "Overnight passengers the vessel is permitted to carry (PVAG V201.1.1 counts more than 49)."),
    FieldDef("ada_2010_named", "ADA 2010 in the compliance basis", "text",
             "yes or no: whether the owner's compliance basis names the 2010 ADA Standards for this ship. The Standards "
             "are written for buildings and sites, so they are not assumed to bind a ship.", choices=("yes", "no")),
    FieldDef("installation_date", "installation date", "date",
             "Date the equipment an amendment is about was or will be installed. Per equipment item, not per ship."),
)

MEANINGS = {key: item.meaning for key, item in FIELDS.items()}

# Spelled-out forms a document might use for each allowed text value.
_SYNONYMS = {
    "ship_type": {"passenger": ["passenger ship", "passenger vessel"],
                  "cargo": ["cargo ship"],
                  "special_purpose": ["special purpose ship", "sps", "sps ship"],
                  "ro_ro_passenger": ["roro passenger", "ro ro passenger ship", "roro passenger ship", "ro pax", "ropax"]},
    "voyage": {"international": ["international voyage", "international voyages"],
               "short_international": ["short international voyage", "short international voyages"],
               "domestic": ["domestic voyage"]},
    "propulsion": {"power_driven": ["power driven vessel", "powered"], "sailing": ["sailing vessel", "sail"]},
}

# Card keys and the ship facts that feed them (fact subject is always "ship").
_FACT_KEYS = {
    "ship_type": "ship_type", "passengers": "passengers", "special_personnel": "special_personnel",
    "crew_complement": "crew", "persons_on_board": "persons_on_board", "length_overall": "length_overall_m",
    "load_line_length": "load_line_length_m", "breadth_greatest": "breadth_greatest_m", "beam": "beam_m",
    "gross_tonnage": "gross_tonnage", "flag": "flag", "contract_date": "contract_date", "keel_date": "keel_date",
    "delivery_date": "delivery_date", "main_vertical_zones": "main_vertical_zones", "voyage": "voyage",
    "propulsion": "propulsion",
}

_TIER_RANK = {"A": 0, "B": 1, "C": 2}


class CardField(BaseModel):
    value: float | str | date | None = None
    unit: str = ""
    source: str = ""
    tier: str = ""
    confirmed: bool = False
    confirmed_by: str = ""
    note: str = ""


class Suggestion(BaseModel):
    """Something a person must confirm. It is never used as a value until they do."""

    field: str
    text: str
    candidate: float | str | None = None


class ShipCard(BaseModel):
    name: str = ""
    fields: dict[str, CardField] = Field(default_factory=dict)
    suggestions: list[Suggestion] = Field(default_factory=list)

    @model_validator(mode="after")
    def _dates_are_dates(self) -> ShipCard:
        for key, item in self.fields.items():
            if key in FIELDS and FIELDS[key].kind == "date" and isinstance(item.value, str):
                try:
                    item.value = date.fromisoformat(item.value.strip())
                except ValueError as error:
                    raise ValueError(f"{key} must be a date as YYYY-MM-DD, not {item.value!r}") from error
        return self

    def field(self, key: str) -> CardField | None:
        return self.fields.get(key)

    def get(self, key: str) -> float | str | date | None:
        """The usable value, or None when it is missing or marked unusable (tier D)."""
        item = self.fields.get(key)
        return None if item is None or item.tier == "D" else item.value

    def number(self, key: str) -> float | None:
        value = self.get(key)
        return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else None

    def get_date(self, key: str) -> date | None:
        value = self.get(key)
        return value if isinstance(value, date) else None

    def text(self, key: str) -> str | None:
        value = self.get(key)
        return value if isinstance(value, str) else None


def label_for(field: str) -> str:
    if field == "constructed":
        return "construction date (keel laid or similar stage)"
    return FIELDS[field].label if field in FIELDS else field.replace("_", " ")


def num(value: float) -> str:
    """A number for people: thousands separators, no trailing zeros."""
    return f"{value:,.3f}".rstrip("0").rstrip(".")


def cap(text: str) -> str:
    return text[:1].upper() + text[1:]


def pretty(text: str) -> str:
    return text.replace("ro_ro", "ro-ro").replace("_", " ")


def format_value(field: str, value: float | str | date | None) -> str:
    if value is None:
        return "not known"
    if isinstance(value, date):
        return f"{value.day} {value:%B %Y}"
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        unit = FIELDS[field].unit if field in FIELDS else ""
        return f"{num(float(value))} {unit}".strip()
    return pretty(str(value))


def normalize_choice(field: str, raw: object) -> str | None:
    """The allowed value a document's wording stands for, or None. No guessing from partial matches."""
    definition = FIELDS.get(field)
    if definition is None or not definition.choices:
        return str(raw).strip() or None
    text = re.sub(r"[^a-z0-9]+", " ", str(raw).lower()).strip()
    for choice in definition.choices:
        spellings = [choice.replace("_", " ")] + _SYNONYMS.get(field, {}).get(choice, [])
        if text in spellings:
            return choice
    return None


def constructed_date(card: ShipCard) -> date | None:
    """When the ship was 'constructed' for SOLAS: the keel-laying date, or the date of a similar stage of construction.

    SOLAS II-2/1 and III/1.1-1.3: ships 'constructed' means keels laid or at a similar stage of construction, where a
    similar stage is construction identifiable with the ship plus assembly of at least 50 tonnes or 1% of the
    estimated structural mass, whichever is less. SOLAS V/2.1 lists the same stages as alternatives. The contract and
    delivery dates are different dates for different rules. A cargo ship converted to a passenger ship counts as
    constructed on the day the conversion begins: the card has no conversion date, so enter that date as the keel date.
    """
    return card.get_date("keel_date")


# ---- reading a card from facts -----------------------------------------------------------------------------


@dataclass
class _Reading:
    value: float | str | date | None
    source: str
    tier: str
    confirmed_by: str = ""
    problem: str = ""


def _tier_of(fact: Fact) -> str:
    if fact.confirmed_by:
        return "A"
    if fact.tier is not None:
        return fact.tier.value
    # No tier assigned: a stated value is exact; anything else is one reading until shown otherwise.
    return "A" if fact.source.kind == SourceKind.CHAT else "C"


def _value_from_fact(key: str, fact: Fact) -> tuple[float | str | date | None, str]:
    """The fact's value in the card's own terms (meters for lengths), or why it can't be used."""
    kind = FIELDS[key].kind
    raw = fact.value
    if kind == "length":
        if isinstance(raw, str):
            parsed = parse_length(raw, unit_hint=fact.unit)
            if parsed is None:
                return None, f"'{raw}' is not a length"
            value, unit = parsed
        else:
            value, unit = float(raw), fact.unit
        if not is_length_unit(unit):
            return None, f"read as {num(value)} with no usable unit; confirm the unit"
        meters = to_mm(value, unit) / 1000.0
        definition = dictionary.for_fact("ship", fact.property)
        if definition and not definition.in_range(meters):
            return None, f"read as {num(meters)} m, outside the plausible range {definition.range[0]:g}-{definition.range[1]:g} m; check the unit"
        return meters, ""
    if kind == "number":
        value = float(raw) if not isinstance(raw, str) else parse_number(raw)
        if value is None or value < 0:
            return None, f"'{raw}' is not a usable count"
        definition = dictionary.for_fact("ship", fact.property)
        if definition and not definition.in_range(value):
            return None, f"read as {num(value)}, outside the plausible range {definition.range[0]:g}-{definition.range[1]:g}"
        return value, ""
    if kind == "date":
        parsed = parse_date(raw) if isinstance(raw, str) else None
        return (parsed, "") if parsed else (None, f"'{raw}' is not a date I can read without guessing")
    if FIELDS[key].choices:
        choice = normalize_choice(key, raw)
        return (choice, "") if choice else (None, f"'{raw}' is not one of {', '.join(FIELDS[key].choices)}")
    text = str(raw).strip()
    return (text, "") if text else (None, "empty")


def _same(key: str, a: object, b: object) -> bool:
    if isinstance(a, float) and isinstance(b, float):
        return math.isclose(a, b, rel_tol=1e-6, abs_tol=1e-9)
    return str(a).strip().lower() == str(b).strip().lower()


def _resolve(key: str, readings: list[_Reading]) -> tuple[CardField | None, Suggestion | None]:
    usable = [r for r in readings if r.value is not None and r.tier in _TIER_RANK]
    problems = [f"{r.source}: {r.problem}" for r in readings if r.problem]
    if not usable:
        if not problems:
            return None, None
        note = "No usable reading. " + "; ".join(problems)
        return CardField(tier="D", note=note), Suggestion(field=key, text=f"{cap(FIELDS[key].label)}: {note}")
    best = min(_TIER_RANK[r.tier] for r in usable)
    top = [r for r in usable if _TIER_RANK[r.tier] == best]
    distinct: list[list[_Reading]] = []
    for reading in top:
        for group in distinct:
            if _same(key, group[0].value, reading.value):
                group.append(reading)
                break
        else:
            distinct.append([reading])
    unit = FIELDS[key].unit if FIELDS[key].kind == "length" else ""
    if len(distinct) > 1:
        shown = "; ".join(f"{format_value(key, g[0].value)} ({g[0].source})" for g in distinct)
        note = f"Sources disagree, so no value is used until a person confirms one: {shown}"
        return CardField(tier="D", unit=unit, note=note), Suggestion(field=key, text=f"{cap(FIELDS[key].label)}: {note}.")
    chosen = distinct[0]
    others = [r for r in usable if r not in top and not _same(key, r.value, chosen[0].value)]
    if others and not any(r.confirmed_by for r in chosen):
        # A weaker reading that disagrees still counts: one of the two is wrong, and the card decides which rules
        # apply. Nothing is used until a person confirms (an engineer's confirmed value settles it).
        shown = "; ".join(f"{format_value(key, r.value)} ({r.source}, tier {r.tier})" for r in [chosen[0], *others])
        note = f"Sources disagree, so no value is used until a person confirms one: {shown}"
        return CardField(tier="D", unit=unit, note=note), Suggestion(field=key, text=f"{cap(FIELDS[key].label)}: {note}.")
    notes = [f"Also read as {format_value(key, r.value)} from {r.source} (tier {r.tier})" for r in others]
    notes += [f"Ignored: {p}" for p in problems]
    confirmed_by = next((r.confirmed_by for r in chosen if r.confirmed_by), "")
    return CardField(value=chosen[0].value, unit=unit, source="; ".join(r.source for r in chosen), tier=chosen[0].tier,
                     confirmed=bool(confirmed_by), confirmed_by=confirmed_by, note=". ".join(notes)), None


def propose_card(facts: list[Fact], profile: ShipProfile | None = None) -> ShipCard:
    """Map ship facts and the profile to card fields, keeping each value's source and tier.

    Where sources disagree the field is left empty and a suggestion asks a person to pick one. Persons on board is
    never added up here: if only its parts exist, the card carries a suggestion, not a value.
    """
    readings: dict[str, list[_Reading]] = defaultdict(list)
    suggestions: list[Suggestion] = []
    science: list[Fact] = []
    if profile is not None:
        stated = {"ship_type": profile.ship_type or None, "passengers": profile.passengers, "flag": profile.flag or None}
        for key, raw in stated.items():
            if raw is None:
                continue
            value = normalize_choice(key, raw) if FIELDS[key].choices else (float(raw) if key == "passengers" else raw)
            if value is None:
                suggestions.append(Suggestion(
                    field=key, text=f"The ship profile gives {FIELDS[key].label} '{raw}', which is not one of "
                                    f"{', '.join(FIELDS[key].choices)}. Confirm which applies; it is not assumed."))
                continue
            readings[key].append(_Reading(value, "ship profile", "A"))
    for fact in facts:
        if fact.subject != "ship" or fact.superseded_by:
            continue
        if fact.property == "science_complement":
            science.append(fact)
            continue
        key = _FACT_KEYS.get(fact.property)
        if key is None:
            continue
        value, problem = _value_from_fact(key, fact)
        readings[key].append(_Reading(value, fact.source.describe(), _tier_of(fact), fact.confirmed_by, problem))
    card_fields: dict[str, CardField] = {}
    for key, items in readings.items():
        item, suggestion = _resolve(key, items)
        if item is not None:
            card_fields[key] = item
        if suggestion is not None:
            suggestions.append(suggestion)
    card = ShipCard(fields=card_fields, suggestions=suggestions)
    return card.model_copy(update={"suggestions": suggestions + _total_suggestions(card, science)})


def _total_suggestions(card: ShipCard, science: list[Fact]) -> list[Suggestion]:
    out: list[Suggestion] = []
    if card.number("persons_on_board") is None and card.number("crew") is not None:
        parts = [(label, card.number(key)) for label, key in
                 (("passengers", "passengers"), ("special personnel", "special_personnel"), ("crew", "crew"))
                 if card.number(key) is not None]
        if len(parts) >= 2:
            total = sum(value for _, value in parts)
            sums = " + ".join(f"{label} {num(value)}" for label, value in parts)
            out.append(Suggestion(
                field="persons_on_board", candidate=total,
                text=f"Persons on board is not stated. The parts add up to {num(total)} ({sums}). A person must confirm the "
                     "total against the LSA plan or certificate, which may list other persons; it is not used until then."))
    if card.number("special_personnel") is None and science:
        values = ", ".join(f"{num(float(f.value))}" for f in science if not isinstance(f.value, str))
        out.append(Suggestion(
            field="special_personnel",
            text=f"Science complement is stated ({values}). Special personnel (SPS Code 1.3.11) may be the same number or "
                 "larger, so a person must confirm it."))
    return out


def confirm(card: ShipCard, field: str, value: float | str | date, unit: str = "", by: str = "") -> ShipCard:
    """A new card with one value confirmed by a person: tier A, marked confirmed, with the name kept."""
    definition = FIELDS.get(field)
    if definition is None:
        raise ValueError(f"Unknown ship card field {field!r}")
    if not by.strip():
        raise ValueError("Say who confirmed the value")
    if definition.kind == "length":
        unit = unit.strip() or "m"
        if not is_length_unit(unit):
            raise ValueError(f"{unit!r} is not a length unit")
        if not math.isfinite(float(value)) or float(value) <= 0:
            raise ValueError(f"{field} must be a positive length")
        stored: float | str | date = to_mm(float(value), unit) / 1000.0
        stored_unit = "m"
    elif definition.kind == "number":
        stored, stored_unit = float(value), definition.unit
        if not math.isfinite(stored) or stored < 0:
            raise ValueError(f"{field} must be zero or more")
    elif definition.kind == "date":
        parsed = value if isinstance(value, date) else (parse_date(str(value)) if value else None)
        if parsed is None:
            raise ValueError(f"{field} needs a date such as 2027-02-15, not {value!r}")
        stored, stored_unit = parsed, ""
    else:
        stored, stored_unit = str(value).strip(), ""
        if definition.choices:
            choice = normalize_choice(field, value)
            if choice is None:
                raise ValueError(f"{field} must be one of {', '.join(definition.choices)}")
            stored = choice
    old = card.fields.get(field)
    replaced = f"Replaced {format_value(field, old.value)}" if old is not None and old.value is not None else ""
    updated = card.model_copy(deep=True)
    updated.fields[field] = CardField(value=stored, unit=stored_unit, source=f"confirmed by {by}", tier="A",
                                      confirmed=True, confirmed_by=by, note=replaced)
    updated.suggestions = [s for s in updated.suggestions if s.field != field]
    return updated
