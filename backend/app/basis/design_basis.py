"""The design basis: for one ship card, which rules and editions apply and what each requires, as numbers.

Applicability comes from rules/applicability.yaml, run by app.basis.conditions. Required values are computed here, in
code, from the card's own fields, so a check and the basis always use exactly the same number.
"""
from __future__ import annotations

import math
from functools import lru_cache
from pathlib import Path
from typing import Callable, Literal

import yaml
from pydantic import BaseModel, Field

from .conditions import evaluate, validate
from .shipcard import ShipCard, format_value, label_for, num

ROOT = Path(__file__).resolve().parents[3]
APPLICABILITY_PATH = ROOT / "rules" / "applicability.yaml"

# Door clear width (2010 ADA 404.2.3, PVAG V404.2.3): inches govern, so a depth of 610 mm counts as over 24 in.
DOOR_MIN_MM, DOOR_DEEP_MM, DOOR_DEEP_LIMIT_IN = 815.0, 915.0, 24.0
STAIR_BASE_MM, STAIR_FREE_PERSONS, STAIR_STEP_MM = 900.0, 90, 10.0
MAST_MIN_M, MAST_CAP_M = 6.0, 12.0
BRIDGE_SHIP_LENGTHS, BRIDGE_CAP_M = 2.0, 500.0
LIFEBOAT_SHARE, PASSENGER_RAFT_SHARE, CARGO_RAFT_SHARE = 0.5, 0.25, 1.0
SPS_PASSENGER_RULES_ABOVE = 60  # persons on board, SPS Code 8.2 and 8.4
EVAC_MINUTES, EVAC_MINUTES_LARGE, EVAC_LARGE_ABOVE_ZONES = 60.0, 80.0, 3

ASK = {
    "ship_type": "What is the SOLAS ship type: passenger, ro-ro passenger, cargo or special purpose?",
    "persons_on_board": "How many persons on board is the ship certified to carry (passengers or special personnel, plus crew)?",
    "breadth_greatest_m": "What is the ship's greatest breadth (extreme breadth, not the moulded beam)?",
    "length_overall_m": "What is the ship's length overall?",
    "main_vertical_zones": "How many main vertical zones does the ship have?",
    "voyage": "Does the ship make international voyages that are not short, short international voyages, or domestic voyages?",
}


class Requirement(BaseModel):
    """What one rule requires of this ship. `value` is None when it can't be computed or depends on the item checked."""

    required: str = ""
    value: float | None = None
    unit: str = ""
    formula: str = ""
    bounds: tuple[float | None, float | None] | None = None  # the requirement lies in this range even when value is None
    per_item: bool = False  # depends on the stair, door or other item: call requirement_for with its inputs
    per_side: bool | None = None  # True: on each side; False: in total; None: not a capacity
    inputs: list[str] = Field(default_factory=list)  # card fields used
    missing: list[str] = Field(default_factory=list)
    questions: list[str] = Field(default_factory=list)  # one per missing item, same order
    note: str = ""


class BasisItem(BaseModel):
    rule_id: str
    title: str
    status: Literal["applies", "not_applicable", "cant_tell"]
    applicability: Literal["applies", "not_applicable", "cant_tell"]  # from the conditions alone
    reasons: list[str] = Field(default_factory=list)
    questions: list[str] = Field(default_factory=list)
    missing: list[str] = Field(default_factory=list)
    required: str = ""
    required_value: float | None = None
    unit: str = ""
    formula: str = ""
    bounds: tuple[float | None, float | None] | None = None
    per_item: bool = False
    per_side: bool | None = None
    inputs: list[dict] = Field(default_factory=list)  # card fields used: field, value, unit, tier, source, confirmed
    provisional: list[str] = Field(default_factory=list)  # decisive values that are only one reading
    clause: str = ""
    edition: str = ""
    source: str = ""
    verified: bool = False
    note: str = ""
    status_note: str = ""  # legal status, e.g. a proposed rule that is not in force


def _blocked(required: str, missing: dict[str, str], **kw: object) -> Requirement:
    return Requirement(required=required, missing=list(missing), questions=list(missing.values()), **kw)


def _masthead(card: ShipCard) -> Requirement:
    breadth, beam = card.number("breadth_greatest_m"), card.number("beam_m")
    formula = f"min(max({MAST_MIN_M:g} m, greatest breadth), {MAST_CAP_M:g} m)"
    base = ("Uses the greatest breadth (COLREG Rule 3(j)), never the moulded beam. Height is above the uppermost continuous "
            "deck, measured vertically beneath the light (Annex I 1), not above the baseline.")
    if breadth is None:
        beam_note = f" Only the moulded beam ({num(beam)} m) is known, and it is not used." if beam is not None else ""
        return _blocked(
            f"At least {MAST_MIN_M:g} m above the hull, and at least the greatest breadth if that is more than {MAST_MIN_M:g} m, "
            f"but never more than {MAST_CAP_M:g} m. The greatest breadth is not known, so the exact height can't be computed.",
            {"breadth_greatest_m": ASK["breadth_greatest_m"]}, unit="m", formula=formula, bounds=(MAST_MIN_M, MAST_CAP_M),
            note=f"{base} A forward masthead light {MAST_CAP_M:g} m or more above the hull meets this rule whatever the breadth, "
                 f"because the requirement never exceeds {MAST_CAP_M:g} m; one below {MAST_MIN_M:g} m fails whatever the breadth.{beam_note}")
    value = min(max(MAST_MIN_M, breadth), MAST_CAP_M)
    return Requirement(
        required=f"Forward masthead light at least {num(value)} m above the hull (greatest breadth {num(breadth)} m; "
                 f"limits {MAST_MIN_M:g} m to {MAST_CAP_M:g} m).",
        value=value, unit="m", formula=formula, bounds=(value, value), inputs=["breadth_greatest_m"], note=base)


def _bridge(card: ShipCard) -> Requirement:
    loa = card.number("length_overall_m")
    formula = f"min({BRIDGE_SHIP_LENGTHS:g} x length overall, {BRIDGE_CAP_M:g} m)"
    if loa is None:
        return _blocked("The forward blind zone is limited to the lesser of two ship lengths and 500 m. The length overall is not known.",
                        {"length_overall_m": ASK["length_overall_m"]}, unit="m", formula=formula)
    two = BRIDGE_SHIP_LENGTHS * loa
    value = min(two, BRIDGE_CAP_M)
    governs = f"{BRIDGE_CAP_M:g} m governs" if two >= BRIDGE_CAP_M else "two ship lengths governs"
    return Requirement(
        required=f"The sea surface ahead of the bow may be hidden for no more than {num(value)} m, out to 10 degrees on either side, "
                 f"under all conditions of draught, trim and deck cargo (two ship lengths = {num(two)} m; {governs}).",
        value=value, unit="m", formula=formula, inputs=["length_overall_m"],
        note="SOLAS V/22.1.1, seen from the conning position. Ship length is the length overall (V/2.4).")


def _stair(card: ShipCard, persons_served: float | None = None) -> Requirement:
    formula = (f"{STAIR_BASE_MM:g} mm + {STAIR_STEP_MM:g} mm x (persons served - {STAIR_FREE_PERSONS}), "
               f"for persons served above {STAIR_FREE_PERSONS}")
    note = ("Persons served are two thirds of the crew plus all passengers in the areas served (FSS 13/2.1.1), taken from the "
            "means of escape calculation. Each started person above 90 counts. The width must also not be less than the 2.1.2 "
            "calculation, which can be larger.")
    if persons_served is None:
        return Requirement(
            required=f"Each escape stair: at least {STAIR_BASE_MM:g} mm clear width between handrails, plus {STAIR_STEP_MM:g} mm for "
                     f"every person above {STAIR_FREE_PERSONS} that it serves. The persons served by each stair decide the number.",
            unit="mm", formula=formula, bounds=(STAIR_BASE_MM, None), per_item=True, note=note)
    if persons_served < 0:
        raise ValueError("persons_served can't be negative")
    extra = max(0, math.ceil(round(persons_served - STAIR_FREE_PERSONS, 9)))
    value = STAIR_BASE_MM + STAIR_STEP_MM * extra
    return Requirement(
        required=f"At least {num(value)} mm clear width between handrails for {num(persons_served)} persons served "
                 f"({STAIR_BASE_MM:g} mm + {STAIR_STEP_MM:g} mm x {extra}).",
        value=value, unit="mm", formula=formula, bounds=(STAIR_BASE_MM, None), per_item=True, note=note)


def _door(card: ShipCard, opening_depth_mm: float | None = None) -> Requirement:
    formula = f"{DOOR_MIN_MM:g} mm; {DOOR_DEEP_MM:g} mm if the opening is more than {DOOR_DEEP_LIMIT_IN:g} in deep"
    note = ("Clear width is measured between the face of the door and the stop, door open 90 degrees. Depth is compared in inches, "
            "so 610 mm counts as over 24 in (609.6 mm) and the stricter 915 mm applies.")
    if opening_depth_mm is None:
        return Requirement(
            required=f"At least {DOOR_MIN_MM:g} mm (32 in) clear width; {DOOR_DEEP_MM:g} mm (36 in) when the opening is more than "
                     f"610 mm (24 in) deep. The opening depth decides which.",
            unit="mm", formula=formula, bounds=(DOOR_MIN_MM, DOOR_DEEP_MM), per_item=True, note=note)
    deep = round(opening_depth_mm, 6) > round(DOOR_DEEP_LIMIT_IN * 25.4, 6)
    value = DOOR_DEEP_MM if deep else DOOR_MIN_MM
    return Requirement(
        required=f"At least {value:g} mm ({'36' if deep else '32'} in) clear width for an opening {num(opening_depth_mm)} mm deep.",
        value=value, unit="mm", formula=formula, bounds=(DOOR_MIN_MM, DOOR_DEEP_MM), per_item=True, note=note)


def _persons(card: ShipCard) -> tuple[float | None, dict[str, str]]:
    pob = card.number("persons_on_board")
    return pob, ({} if pob is not None else {"persons_on_board": ASK["persons_on_board"]})


def _lifeboats(card: ShipCard) -> Requirement:
    pob, missing = _persons(card)
    formula = f"{LIFEBOAT_SHARE:.0%} of persons on board, on each side"
    if pob is None:
        return _blocked(f"Lifeboats on each side for at least {LIFEBOAT_SHARE:.0%} of the persons on board. Persons on board is not known.",
                        missing, unit="persons", formula=formula, per_side=True)
    value = LIFEBOAT_SHARE * pob
    return Requirement(
        required=f"Lifeboats on each side with room for at least {num(value)} persons ({LIFEBOAT_SHARE:.0%} of {num(pob)} persons on board).",
        value=value, unit="persons", formula=formula, per_side=True, inputs=["persons_on_board"])


def _passenger_liferafts(card: ShipCard) -> Requirement:
    pob, missing = _persons(card)
    formula = f"{PASSENGER_RAFT_SHARE:.0%} of persons on board, in total"
    if pob is None:
        return _blocked(f"Liferafts for at least {PASSENGER_RAFT_SHARE:.0%} of the persons on board, in addition to the lifeboats. "
                        "Persons on board is not known.", missing, unit="persons", formula=formula, per_side=False)
    value = PASSENGER_RAFT_SHARE * pob
    return Requirement(
        required=f"Liferafts with room for at least {num(value)} persons in total ({PASSENGER_RAFT_SHARE:.0%} of {num(pob)} persons "
                 "on board), in addition to the lifeboats, served by a launching appliance on each side.",
        value=value, unit="persons", formula=formula, per_side=False, inputs=["persons_on_board"])


def _survival_regime(card: ShipCard) -> tuple[str | None, dict[str, str]]:
    """Passenger-ship or cargo-ship lifesaving rules. A special purpose ship follows SPS Code 8.2 or 8.4 by persons on board."""
    ship_type = card.text("ship_type")
    if ship_type is None:
        return None, {"ship_type": ASK["ship_type"]}
    if ship_type in ("passenger", "ro_ro_passenger"):
        return "passenger", {}
    if ship_type == "cargo":
        return "cargo", {}
    pob, missing = _persons(card)
    if pob is None:
        return None, missing
    return ("passenger" if pob > SPS_PASSENGER_RULES_ABOVE else "cargo"), {}


def _rafts(card: ShipCard) -> Requirement:
    regime, missing = _survival_regime(card)
    if regime is None:
        return _blocked("Liferaft capacity depends on the ship type and, for a special purpose ship, on the persons on board.", missing, unit="persons")
    pob, pob_missing = _persons(card)
    if pob is None:
        return _blocked("Liferaft capacity is a share of the persons on board, which is not known.", pob_missing, unit="persons")
    if regime == "cargo":
        value = CARGO_RAFT_SHARE * pob
        return Requirement(
            required=f"Liferafts with room for at least {num(value)} persons ({CARGO_RAFT_SHARE:.0%} of {num(pob)} persons on board).",
            value=value, unit="persons", formula=f"{CARGO_RAFT_SHARE:.0%} of persons on board", per_side=False, inputs=["persons_on_board"],
            note="Cargo-ship rule (SOLAS III/31.1.1.2, or SPS Code 8.4 for 60 persons or fewer). If the rafts are not under 185 kg "
                 "and stowed for easy side-to-side transfer, the capacity on each side must cover everyone on board.")
    voyage = card.text("voyage")
    if voyage is None:
        return _blocked("Passenger-ship liferaft capacity depends on the voyage type.", {"voyage": ASK["voyage"]}, unit="persons")
    if voyage != "international":
        return _blocked("Passenger ships on short international voyages follow SOLAS III/21.1.2, and domestic voyages national rules; "
                        "neither is modelled here.", {"liferaft rule for this voyage type": "Which liferaft rule applies to this ship's "
                        "short international or domestic voyages? This engine does not model SOLAS III/21.1.2."}, unit="persons")
    return _passenger_liferafts(card)


def _evacuation_time(card: ShipCard) -> Requirement:
    ship_type, zones = card.text("ship_type"), card.number("main_vertical_zones")
    formula = "1.25(R+T) + 2/3(E+L) <= n, and (E+L) <= 30 min; n = 60 min, or 80 min for a non-ro-ro passenger ship with more than 3 main vertical zones"
    if ship_type == "ro_ro_passenger":
        n = EVAC_MINUTES
        inputs, note = ["ship_type"], "Ro-ro passenger ships use n = 60 whatever the number of main vertical zones."
    elif ship_type == "passenger" and zones is not None:
        n = EVAC_MINUTES_LARGE if zones > EVAC_LARGE_ABOVE_ZONES else EVAC_MINUTES
        inputs, note = ["ship_type", "main_vertical_zones"], ""
    elif ship_type == "passenger":
        return _blocked(f"Evacuation time at most {EVAC_MINUTES:g} min with {EVAC_LARGE_ABOVE_ZONES} or fewer main vertical zones, "
                        f"{EVAC_MINUTES_LARGE:g} min with more. The number of zones is not known.",
                        {"main_vertical_zones": ASK["main_vertical_zones"]}, unit="min", formula=formula,
                        bounds=(EVAC_MINUTES, EVAC_MINUTES_LARGE),
                        note="An analysis time of 60 min or less meets the limit and one over 80 min fails it, whatever the zone count.")
    else:
        return _blocked("Evacuation time limit depends on the ship type.", {"ship_type": ASK["ship_type"]}, unit="min", formula=formula)
    zone_text = f" with {num(zones)} main vertical zones" if ship_type == "passenger" and zones is not None else ""
    return Requirement(required=f"Evacuation time (1.25(R+T) + 2/3(E+L)) at most {n:g} min{zone_text}; (E+L) at most 30 min.",
                       value=n, unit="min", formula=formula, inputs=inputs, note=note)


def _evacuation_analysis(card: ShipCard) -> Requirement:
    return Requirement(required="An evacuation analysis of the escape routes, done early in the design process (guidelines: MSC.1/Circ.1533).",
                       note="Check that the package contains the analysis.")


def _sps_lifesaving(card: ShipCard) -> Requirement:
    return Requirement(required="Follow SOLAS chapter III for passenger ships on international voyages that are not short, reading "
                                "'passenger' as 'special personnel' (SPS Code 8.2 and 8.6).")


def _sps_status(card: ShipCard) -> Requirement:
    return Requirement(required="Treated as a special purpose ship under the SPS Code 2008.")


# rule_id -> (formula, names of per-item inputs it accepts)
_REQUIREMENTS: dict[str, tuple[Callable[..., Requirement], tuple[str, ...]]] = {
    "COLREG-ANNEX-I": (_masthead, ()),
    "SOLAS-V-22": (_bridge, ()),
    "FSS-13-STAIR": (_stair, ("persons_served",)),
    "PVAG-V404.2.3": (_door, ("opening_depth_mm",)),
    "ADA-404.2.3": (_door, ("opening_depth_mm",)),
    "SOLAS-III-21-LIFEBOATS": (_lifeboats, ()),
    "SOLAS-III-21-LIFERAFTS": (_passenger_liferafts, ()),
    "SOLAS-III-RAFTS": (_rafts, ()),
    "MSC.1-CIRC.1533": (_evacuation_time, ()),
    "SOLAS-II-2-13.3.2.7": (_evacuation_analysis, ()),
    "SPS-CODE-8.2": (_sps_lifesaving, ()),
    "SPS-CODE-1.3.12": (_sps_status, ()),
}


def requirement_for(rule_id: str, card: ShipCard, **item_inputs: float) -> Requirement:
    """What the rule requires of this ship, computed from the card. Checks call this so they use the same number.

    Per-item rules take the item's own inputs: persons_served (FSS-13-STAIR) and opening_depth_mm (the door rules).
    It does not decide whether the rule applies: that is `compute_basis`.
    """
    if rule_id not in _REQUIREMENTS:
        raise KeyError(f"No requirement formula for {rule_id}")
    compute, accepted = _REQUIREMENTS[rule_id]
    unexpected = set(item_inputs) - set(accepted)
    if unexpected:
        raise TypeError(f"{rule_id} takes {', '.join(accepted) or 'no item inputs'}, not {', '.join(sorted(unexpected))}")
    return compute(card, **item_inputs)


@lru_cache(maxsize=4)
def load_entries(path: str = str(APPLICABILITY_PATH)) -> dict[str, dict]:
    """The applicability entries by rule id. A bad condition fails here, loudly, not in the middle of a run."""
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    entries: dict[str, dict] = {}
    for entry in data["entries"]:
        for key in ("rule_id", "title", "clause", "edition", "conditions"):
            if key not in entry:
                raise ValueError(f"Applicability entry {entry.get('rule_id', '?')} lacks '{key}'")
        if entry["rule_id"] in entries:
            raise ValueError(f"Duplicate applicability entry {entry['rule_id']}")
        validate(entry["conditions"])
        entries[entry["rule_id"]] = entry
    return entries


def _input_rows(card: ShipCard, keys: list[str]) -> list[dict]:
    rows = []
    for key in dict.fromkeys(keys):
        item = card.field(key)
        if item is None or item.value is None or item.tier == "D":
            continue
        rows.append({"field": key, "label": label_for(key), "value": item.value if not hasattr(item.value, "isoformat") else item.value.isoformat(),
                     "shown": format_value(key, item.value), "unit": item.unit, "tier": item.tier, "source": item.source,
                     "confirmed": item.confirmed, "confirmed_by": item.confirmed_by})
    return rows


def _basis_item(entry: dict, card: ShipCard) -> BasisItem:
    rule_id = entry["rule_id"]
    decision = evaluate(entry["conditions"], card, why=entry.get("why", ""))
    requirement = requirement_for(rule_id, card) if rule_id in _REQUIREMENTS and decision.status != "not_applicable" else Requirement()
    status = decision.status
    reasons, missing, questions = list(decision.reasons), list(decision.missing), list(decision.questions)
    for key, question in zip(requirement.missing, requirement.questions, strict=True):
        if key not in missing:
            missing.append(key)
            questions.append(question)
    required, value, bounds = "", None, None
    if decision.status == "applies":
        required, value, bounds = requirement.required, requirement.value, requirement.bounds
        if requirement.missing and not requirement.per_item:
            status = "cant_tell"
            reasons.append("The rule applies, but what it requires can't be computed yet: "
                           + ", ".join(label_for(k) for k in requirement.missing) + " not known.")
    elif decision.status == "cant_tell" and requirement.required:
        required = f"If it applies: {requirement.required}"
    keys = decision.used + requirement.inputs
    provisional = list(decision.provisional)
    for row in _input_rows(card, keys):
        if row["tier"] == "C" and not row["confirmed"]:
            message = f"{row['label']} {row['shown']} is a single reading (tier C)"
            if message not in provisional and row["field"] in requirement.inputs:
                provisional.append(message)
    note = " ".join(part for part in (requirement.note, entry.get("note", "")) if part)
    return BasisItem(
        rule_id=rule_id, title=entry["title"], status=status, applicability=decision.status, reasons=reasons,
        questions=questions, missing=missing, required=required, required_value=value if status == "applies" else None,
        unit=requirement.unit, formula=requirement.formula, bounds=bounds,
        per_item=requirement.per_item, per_side=requirement.per_side, inputs=_input_rows(card, keys), provisional=provisional,
        clause=entry["clause"], edition=entry["edition"], source=entry.get("source", ""), verified=bool(entry.get("verified", False)),
        note=" ".join(note.split()), status_note=" ".join(entry.get("status_note", "").split()))


def _no_data(rule_id: str) -> BasisItem:
    return BasisItem(
        rule_id=rule_id, title=rule_id, status="cant_tell", applicability="cant_tell",
        reasons=["No applicability data is loaded for this rule, so which hulls it covers is not known."],
        questions=[f"Which ship types, sizes and dates does {rule_id} apply to?"], missing=[f"applicability of {rule_id}"])


def compute_basis(card: ShipCard, rule_ids: list[str] | None = None) -> list[BasisItem]:
    """One item per rule: applies, not applicable, or can't tell, with the reasons, the questions, and the required numbers."""
    entries = load_entries()
    return [_basis_item(entries[rule_id], card) if rule_id in entries else _no_data(rule_id)
            for rule_id in (rule_ids if rule_ids is not None else list(entries))]


def missing_inputs(items: list[BasisItem]) -> list[dict]:
    """What is missing across the whole basis, once per input, with the rules that wait for it."""
    grouped: dict[str, dict] = {}
    for item in items:
        for key, question in zip(item.missing, item.questions, strict=True):
            entry = grouped.setdefault(key, {"field": key, "question": question, "rules": []})
            if item.rule_id not in entry["rules"]:
                entry["rules"].append(item.rule_id)
    return list(grouped.values())
