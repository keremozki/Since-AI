"""Deterministic compliance checks. No AI here: code alone decides every result.

Each check takes a rule, the fact store, and the ship profile, and returns findings.
Missing data gives "can't tell", never a pass. A false pass is the worst possible result.
"""
from __future__ import annotations

import math
from collections import defaultdict
from typing import Callable

from .models import CheckBasis, Fact, Finding, Rule, ShipProfile, Status
from .store import FactStore
from .tiers import fact_input, tier_of
from .units import fmt_length, is_length_unit, length_problem, to_mm
from .vocabulary import VOCABULARY

CONSISTENCY_RULE = Rule(
    id="CROSS-CHECK",
    title="Sources must agree",
    area="Consistency",
    source="Cross-check between design sources",
    check="consistency",
    verified=True,
)
SCALE_RULE = Rule(
    id="SCALE-CHECK",
    title="Drawing scale matches its note",
    area="Consistency",
    source="Drawing calibration: frame ruler and deck heights",
    check="scale",
    verified=True,
)
SCALE_TOLERANCE = 0.02  # a measured scale within 2% of the note agrees with it
RELATIVE_TOLERANCE = 0.005
LENGTH_TOLERANCE_MM = 10.0
PLAIN_NAMES = {
    "crew_complement": "Crew count",
    "science_complement": "Science team count",
    "persons_on_board": "Persons on board",
    "length_overall": "Overall length",
    "beam": "Beam",
    "lightship_weight": "Lightship weight",
    "main_vertical_zones": "Fire zone count",
    "capacity_persons": "Liferaft capacity",
    "height_above_hull": "Masthead light height",
    "time_minutes": "Evacuation time",
    "eye_height_above_water": "Conning position eye height",
    "obstruction_height_above_water": "Forward obstruction height",
    "eye_to_obstruction": "Distance to forward obstruction",
    "eye_to_bow": "Distance to bow",
    "clear_width": "Clear width",
    "rise": "Rise",
    "run": "Run",
    "slope_run_per_rise": "Run per unit of rise",
    "opening_depth": "Opening depth",
    "persons_served": "Persons served",
    "breadth_greatest": "Greatest breadth",
    "count": "Number",
    "accessible_route": "On accessible route",
}
NAMED_SUBJECTS = {"door-number": "Door", "corridor": "Corridor", "ramp": "Ramp"}


def _plain(prop: str) -> str:
    return PLAIN_NAMES.get(prop, prop.replace("_", " ").capitalize())


def describe_fact(fact: Fact) -> str:
    """A recorded fact in plain words, like "Crew count: 12 persons" or "Corridor C2 clear width: 30 in"."""
    kind, _, label = fact.subject.partition(":")
    owner = f"{NAMED_SUBJECTS[kind]} {label} " if label and kind in NAMED_SUBJECTS else ""
    name = _plain(fact.property)
    return f"{owner}{name.lower() if owner else name}: {_show(fact)}"


# Unit conversion in floating point: 4 in / 48 in becomes 101.6 mm / 1219.2 mm and can land a hair
# above 1/12. This only absorbs rounding error; it is far below any value a drawing can state.
FLOAT_SLACK = 1e-9


INPUT_RULE = Rule(
    id="INPUT-CHECK",
    title="Input value can be used",
    area="Consistency",
    source="Input validation before the checks",
    check="input_values",
    verified=True,
)
# Properties that must be a positive length, and numbers that can't be negative (a count can be 0).
LENGTH_PROPERTIES = {p for _s, p, kind, _m in VOCABULARY if kind == "length"} | {"tread_length", "height_above_baseline"}
NUMBER_PROPERTIES = {p for _s, p, kind, _m in VOCABULARY if kind == "number"}
POSITIVE_NUMBERS = {"slope_run_per_rise", "capacity_persons", "persons_on_board", "time_minutes", "lightship_weight"}


def unusable_facts(store: FactStore) -> list[tuple[Fact, str]]:
    """Facts no check may use: a length with no or an unknown unit, zero, negative, or not a number.

    They come from chat, measurements, saved files, or a misread. Using them could make a made-up
    fail or a false pass, so they are taken out and reported as can't tell with the reason.
    """
    bad = []
    for fact in store.facts:
        if fact.property in LENGTH_PROPERTIES:
            problem = length_problem(fact.value, fact.unit)
        elif fact.property in NUMBER_PROPERTIES:
            value = fact.value
            if isinstance(value, bool) or not isinstance(value, (int, float)) or value != value or value in (float("inf"), float("-inf")):
                problem = f"the value {value!r} is not a number"
            elif value < 0 or (value == 0 and fact.property in POSITIVE_NUMBERS):
                problem = f"{value:g} is not possible here"
            else:
                problem = ""
        else:
            problem = ""
        if problem:
            bad.append((fact, problem))
    return bad


def input_findings(bad: list[tuple[Fact, str]]) -> list[Finding]:
    return [_finding(INPUT_RULE, Status.CANT_TELL, fact.subject, f"{fact.subject} {fact.property.replace('_', ' ')}",
                     measured=f"Not used: {problem}.", required="A positive number with a unit (mm, cm, m, in, ft)",
                     why="A value that can't be right is never used to pass or fail a check.",
                     sources=_sources(fact), location=fact.location,
                     question=f"What is the correct {fact.property.replace('_', ' ')} of {fact.subject}?")
            for fact, problem in bad]


def _finding(rule: Rule, status: Status, subject: str, label: str, inputs: tuple = (), **fields) -> Finding:
    """One result. `inputs` are the facts the result rests on: their tiers decide whether it may stand."""
    facts = [f for f in inputs if f is not None]
    if facts and "sources" not in fields:
        fields["sources"] = _sources(*facts)
    boxes = [f.evidence.box for f in facts if f.evidence and f.evidence.box]
    if status == Status.FAIL and rule.fix and "fix" not in fields:
        fields["fix"] = rule.fix
    return Finding(rule_id=rule.id, rule_title=rule.title, area=rule.area, rule_source=rule.source,
                   status=status, subject=subject, label=label, provisional=not rule.verified,
                   unconfirmed_label=rule.unconfirmed_label(), inputs=[fact_input(f) for f in facts],
                   evidence_boxes=boxes, **fields)


def _sources(*facts: Fact | None) -> list[str]:
    return list(dict.fromkeys(f.source.describe() for f in facts if f))


def _not_written(rule: Rule, subject: str, label: str, shown: Fact | None, what: str, **fields) -> Finding:
    """Can't tell for a labelled object with no usable value. It names the text found, where, and why
    the value next to it wasn't used, so the engineer knows exactly what to look at."""
    measured = f"{what} not written on the drawing"
    extra = {}
    if shown is not None:
        reason = shown.meta.get("missing") or f"no {what.lower()} is written next to it"
        measured = f"{what} not readable: label '{shown.source.quote}' is on {shown.value}, but {reason}."
        extra = dict(read_quote=shown.source.quote, read_file=shown.source.file, read_locator=shown.source.locator)
    return _finding(rule, Status.CANT_TELL, subject, label, measured=measured, sources=_sources(shown), **extra, **fields)


def _values_differ(a: Fact, b: Fact) -> bool:
    if isinstance(a.value, str) or isinstance(b.value, str):
        return str(a.value).strip().lower() != str(b.value).strip().lower()
    if is_length_unit(a.unit) and is_length_unit(b.unit):
        return abs(to_mm(a.value, a.unit) - to_mm(b.value, b.unit)) > LENGTH_TOLERANCE_MM
    largest = max(abs(a.value), abs(b.value))
    return largest > 0 and abs(a.value - b.value) / largest > RELATIVE_TOLERANCE


def _show(fact: Fact) -> str:
    if isinstance(fact.value, str):
        return fact.value
    if is_length_unit(fact.unit):
        return fmt_length(fact.value, fact.unit)
    return f"{fact.value:g} {fact.unit}".strip()


def _disagreement(store: FactStore, subject: str, prop: str) -> list[Fact]:
    facts = store.get(subject, prop)
    return facts if any(_values_differ(facts[0], other) for other in facts[1:]) else []


class _Blocked(Exception):
    """A check needs a value that its sources disagree on."""

    def __init__(self, subject: str, prop: str):
        self.subject, self.prop = subject, prop


_TIER_RANK = {"A": 0, "B": 1, "C": 2, "D": 3}


def _best(store: FactStore, subject: str, prop: str) -> Fact | None:
    """Of the facts that state this value, the most trusted one, so an agreeing drawing reading never hides a schedule cell."""
    facts = store.get(subject, prop)
    return min(facts, key=lambda f: _TIER_RANK[tier_of(f).value]) if facts else None


INPUT_LENGTH_TOLERANCE_MM = 1.0  # a check's inputs must agree this closely; the cross-check report keeps its own tolerance


def _inputs_differ(facts: list[Fact]) -> bool:
    """Whether any two facts a check would use differ at all: a 9 mm difference can flip a pass at the limit."""
    numeric = [f for f in facts if not isinstance(f.value, str)]
    texts = {str(f.value).strip().lower() for f in facts if isinstance(f.value, str)}
    if len(texts) > 1 or (texts and numeric):
        return True
    if len(numeric) < 2:
        return False
    if all(is_length_unit(f.unit) for f in numeric):
        values = [to_mm(float(f.value), f.unit) for f in numeric]
        return max(values) - min(values) > INPUT_LENGTH_TOLERANCE_MM
    values = [float(f.value) for f in numeric]
    return max(values) - min(values) > 1e-9 * max(1.0, max(abs(v) for v in values))


def _value(store: FactStore, subject: str, prop: str) -> Fact | None:
    if _disagreement(store, subject, prop) or _inputs_differ(store.get(subject, prop)):
        raise _Blocked(subject, prop)
    return _best(store, subject, prop)


def _waiting(rule: Rule, blocked: _Blocked, label: str) -> list[Finding]:
    return [_finding(rule, Status.CONFLICT, blocked.subject, label,
                     measured=f"On hold: sources disagree on {_plain(blocked.prop).lower()}.",
                     required="One agreed value", why="This check can't run until the conflict is resolved.")]


def door_label(store: FactStore, subject: str) -> str:
    numbers = store.one(subject, "numbers")
    listed = str(numbers.value).split(",") if numbers and numbers.value else []
    if len(listed) == 1:
        return f"Door {listed[0]}"
    if listed:
        return f"One of doors {', '.join(listed)}"
    name = store.one(subject, "name")
    return str(name.value) if name else subject


def door_number_conflicts(store: FactStore) -> dict[str, list[Fact]]:
    """Door numbers that the model gives two different clear widths."""
    by_number: dict[str, list[Fact]] = defaultdict(list)
    for subject in store.subjects("door:"):
        numbers, width = store.one(subject, "numbers"), store.one(subject, "clear_width")
        if numbers and numbers.value and width:
            for number in str(numbers.value).split(","):
                by_number[number].append(width)
    # Values from drawings, chat, or measurement are stated against a door number.
    for subject in store.subjects("door-number:"):
        by_number[subject.split(":", 1)[1]].extend(store.get(subject, "clear_width"))
    return {number: widths for number, widths in by_number.items()
            if any(_values_differ(widths[0], other) for other in widths[1:])}


def _width_verdict(width: Fact, min_in: float, min_mm: float) -> tuple[bool, float, float, str, list[str]]:
    """The inch figure governs. The metric one is a rounded conversion: 32 in is 812.8 mm, not 815 mm."""
    width_mm = to_mm(float(width.value), width.unit)
    limit_mm = to_mm(min_in, "in")
    passed = width_mm >= limit_mm
    note = []
    if passed and width_mm < min_mm:
        note.append(f"Meets {min_in:g} in, but is under the rule's rounded {min_mm:g} mm figure. The inch value is used.")
    gap = "" if passed else f"{(limit_mm - width_mm) / 25.4:.1f} in ({limit_mm - width_mm:.0f} mm) short"
    return passed, width_mm, limit_mm, gap, note


def check_door_clear_width(rule: Rule, store: FactStore, profile: ShipProfile) -> list[Finding]:
    min_in, min_mm = float(rule.params["min_in"]), float(rule.params["min_mm"])
    required = f"At least {min_in:g} in ({min_mm:g} mm) clear width"
    assumptions = ["Opening depth isn't stated. Openings more than 24 in deep need 36 in; this ship's approved assumption is that its door openings aren't that deep."]
    if profile.accessible_route_all_passage_doors:
        assumptions.append("Every passage door is treated as on an accessible route. The model doesn't mark routes.")
    why = "The door is treated as on an accessible route."
    conflicts = door_number_conflicts(store)
    findings: list[Finding] = []
    if not store.subjects("door:") and not store.subjects("door-number:"):
        return [_finding(rule, Status.CANT_TELL, "doors", "Doors", measured="No doors in the design data",
                         required=required, why=why, question="Add a 3D model or a drawing that shows the doors.")]
    missing: dict[str, list[str]] = defaultdict(list)
    for subject in store.subjects("door:"):
        kind = store.one(subject, "kind")
        if not kind or kind.value != "passage":
            continue
        name, deck, width = store.one(subject, "name"), store.one(subject, "deck"), store.one(subject, "clear_width")
        numbers = store.one(subject, "numbers")
        if width is None:
            # An engineer or drawing can state the width for a whole part type.
            width = store.one(f"door-type:{name.value}", "clear_width")
        if width is None:
            missing[str(name.value)].append(subject)
            continue
        if numbers and numbers.value in conflicts:
            continue
        label = door_label(store, subject)
        passed, width_mm, limit_mm, gap, note = _width_verdict(width, min_in, min_mm)
        door_assumptions = assumptions + note
        compartment = store.one(subject, "compartment")
        status, question = Status.PASS if passed else Status.FAIL, ""
        deep_limit_mm = to_mm(float(rule.params.get("deep_min_in", 36)), "in")
        depth = _best(store, f"door-number:{numbers.value}", "opening_depth") if numbers and numbers.value else None
        if passed and width_mm < deep_limit_mm and "openings_not_deep" not in profile.approved_assumptions:
            # Without the approved assumption, a door between 32 and 36 in passes only if its opening isn't deep.
            if depth is None or to_mm(float(depth.value), depth.unit) > to_mm(float(rule.params.get("deep_opening_in", 24)), "in"):
                status = Status.CANT_TELL if depth is None else Status.FAIL
                question = "" if depth is not None else (
                    f"How deep is the opening of {label}? Openings more than {rule.params.get('deep_opening_in', 24):g} in deep need "
                    f"{rule.params.get('deep_min_in', 36):g} in ({deep_limit_mm:.0f} mm) clear.")
                if depth is not None:
                    gap = f"{(deep_limit_mm - width_mm) / 25.4:.1f} in ({deep_limit_mm - width_mm:.0f} mm) short of the deep-opening limit"
            door_assumptions = [a for a in door_assumptions if not a.startswith("Opening depth isn't stated")]
        elif width_mm >= deep_limit_mm:
            door_assumptions = [a for a in door_assumptions if not a.startswith("Opening depth isn't stated")]
        if (not passed and rule.params.get("stairway_door_exception") and compartment
                and "STAIR" in str(compartment.value).upper()):
            # The rule lets this door follow another authority's limit, which we don't have.
            status = Status.CANT_TELL
            question = f"This door leads to a stairway, so the rule defers to the administrative authority. What width does it require for {label}?"
        decided_by = (width, depth) if passed and width_mm < deep_limit_mm and "openings_not_deep" not in profile.approved_assumptions else (width,)
        findings.append(_finding(
            rule, status, subject, label,
            where=str(deck.value) if deck else "", measured=f"{fmt_length(float(width.value), width.unit)} clear width",
            required=required, gap=gap if status == Status.FAIL else "", why=why, inputs=decided_by, location=width.location,
            confidence="medium", assumptions=door_assumptions, question=question,
            evidence=CheckBasis(measured=width_mm, limit=limit_mm, limit_unit="in", facts=[width])))
    for number, widths in sorted(conflicts.items()):
        findings.append(_finding(
            rule, Status.CONFLICT, f"door-number:{number}", f"Door {number}",
            # Each value once, and each source tied to its value, as in the cross-check.
            measured=" vs. ".join(dict.fromkeys(_show(w) for w in widths)), required=required,
            sources=[f"{_show(w)}: {w.source.describe()}" for w in widths],
            why="Sources give this door number different clear widths, so one record is wrong.",
            inputs=tuple(widths), location=widths[0].location,
            question=f"Which clear width is correct for door {number}?"))
    model_numbers = {n for s in store.subjects("door:") for n in str(getattr(store.one(s, "numbers"), "value", "") or "").split(",") if n}
    for subject in store.subjects("door-number:"):
        number = subject.split(":", 1)[1]
        if number not in model_numbers and number not in conflicts:
            findings.append(_listed_door(rule, store, profile, subject, number, min_in, min_mm, required))
    for name, subjects in sorted(missing.items()):
        first = store.one(subjects[0], "name")
        findings.append(_finding(
            rule, Status.CANT_TELL, subjects[0], f"{name} ({len(subjects)} in the model)",
            measured="Clear width not stated", required=required, why=why, inputs=(first,),
            location=first.location if first else None, assumptions=assumptions,
            question=f'What is the clear width of "{name}"?'))
    return findings


def check_stair_width(rule: Rule, store: FactStore, profile: ShipProfile) -> list[Finding]:
    min_mm, allowance = float(rule.params["min_mm"]), float(rule.params["handrail_allowance_mm"])
    required = f"At least {min_mm:g} mm clear width"
    assumptions = ["Every stair with treads in the model is treated as an escape stair.",
                   f"Width is read from tread length. A pass needs {allowance:g} mm extra to allow for handrails."]
    findings: list[Finding] = []
    if not store.subjects("stair:"):
        return [_finding(rule, Status.CANT_TELL, "stairs", "Stairs", measured="No stairs in the design data",
                         required=required, why="Passenger ship escape stairs have a minimum clear width.",
                         question="Add a 3D model that shows the stairs.")]
    for subject in store.subjects("stair:"):
        if store.get(subject, "clear_width"):
            findings.append(_stated_stair(rule, store, subject, min_mm))
            continue
        name, deck = store.one(subject, "name"), store.one(subject, "deck")
        tread = store.one(subject, "tread_length")
        common = dict(where=str(deck.value) if deck else "", required=required, assumptions=assumptions,
                      why="Passenger ship escape stairs have a minimum clear width.")
        place = "exterior" if "EXTERIOR" in str(name.value).upper() else "interior"
        label = f"Stair {subject.split(':')[1]} ({place})"
        if tread is None:
            findings.append(_finding(rule, Status.CANT_TELL, subject, label, measured="Tread length not stated",
                                     inputs=(name,), location=name.location,
                                     question=f"What is the clear width of stair {subject.split(':')[1]} ({name.value})?",
                                     **common))
            continue
        mm = to_mm(float(tread.value), tread.unit)
        measured = f"{fmt_length(float(tread.value), tread.unit)} tread length"
        location = tread.location
        persons = _best(store, subject, "persons_served")
        need = _stair_need(rule, min_mm, persons)
        if mm < need:
            findings.append(_finding(rule, Status.FAIL, subject, label, measured=measured,
                                     gap=f"{need - mm:.0f} mm short", inputs=(tread, persons), location=location,
                                     confidence="high", evidence=CheckBasis(measured=mm, limit=need, limit_unit="mm", facts=[tread]),
                                     **common))
        elif persons is None:
            # FSS 13 2.1.1 adds 10 mm for every person over 90, so no width passes without the persons served.
            findings.append(_finding(rule, Status.CANT_TELL, subject, label, measured=measured, inputs=(tread,),
                                     location=location, **common,
                                     question=f"How many persons does stair {subject.split(':')[1]} serve? FSS Code 13 2.1.1 "
                                              f"adds 10 mm of width for every person over 90."))
        elif mm >= need + allowance:
            findings.append(_finding(rule, Status.PASS, subject, label, measured=measured, inputs=(tread, persons),
                                     location=location, confidence="medium", **common))
        else:
            findings.append(_finding(rule, Status.CANT_TELL, subject, label, measured=measured, inputs=(tread,),
                                     location=location,
                                     question=f"What is the clear width between handrails on stair {subject.split(':')[1]}?",
                                     **common))
    return findings


def check_corridor_width(rule: Rule, store: FactStore, profile: ShipProfile) -> list[Finding]:
    min_in, reduced_in = float(rule.params["min_in"]), float(rule.params["reduced_in"])
    required = f"At least {min_in:g} in clear width"
    why = "Walking surfaces have a minimum clear width."
    subjects = store.subjects("corridor:")
    if not subjects:
        return [_finding(rule, Status.CANT_TELL, "corridors", "Corridors", measured="No corridor widths in the design data",
                         required=required, why=why, question="Add a drawing that gives corridor clear widths.")]
    exceptions = ["Exceptions allow 32 in for short segments, or on a ship whose largest deck is under 3,000 sq ft. "
                  "Segment length and deck area aren't known."]
    findings = []
    for subject in subjects:
        name = subject.split(":", 1)[1]
        label = f"Corridor {name}"
        try:
            width = _value(store, subject, "clear_width")
        except _Blocked as blocked:
            findings += _waiting(rule, blocked, label)
            continue
        if width is None:
            shown = store.one(subject, "shown_on")
            findings.append(_not_written(rule, subject, label, shown, "Clear width", required=required, why=why,
                                         question=f"What is the clear width of corridor {name}?"))
            continue
        mm, limit = to_mm(float(width.value), width.unit), to_mm(min_in, "in") * (1 - FLOAT_SLACK)
        common = dict(measured=f"{fmt_length(float(width.value), width.unit)} clear width", required=required, why=why,
                      inputs=(width,), location=width.location, confidence=width.confidence)
        evidence = CheckBasis(measured=mm, limit=limit, limit_unit="in", facts=[width])
        if mm >= limit and width.confidence == "low" and not width.confirmed_by:
            # An uncertain reading must never pass.
            findings.append(_finding(rule, Status.CANT_TELL, subject, label, **common,
                                     question=f"Confirm the clear width of corridor {name}: the reading is uncertain."))
        elif mm >= limit:
            findings.append(_finding(rule, Status.PASS, subject, label, **common, evidence=evidence))
        elif mm >= to_mm(reduced_in, "in") * (1 - FLOAT_SLACK):
            findings.append(_finding(rule, Status.CANT_TELL, subject, label, **common, assumptions=exceptions,
                                     question=f"Corridor {name} is under {min_in:g} in but at least {reduced_in:g} in. "
                                              "Is it a short segment, or is the largest deck under 3,000 sq ft?"))
        else:
            findings.append(_finding(rule, Status.FAIL, subject, label, **common, evidence=evidence,
                                     gap=f"{(limit - mm) / 25.4:.1f} in ({limit - mm:.0f} mm) short"))
    return findings


def _ramp_slope(store: FactStore, subject: str) -> tuple[float, list[Fact]] | None:
    """Running slope as rise over run. Code does the division, never the AI."""
    rise, run = _value(store, subject, "rise"), _value(store, subject, "run")
    if rise and run and to_mm(float(run.value), run.unit) > 0:
        return to_mm(float(rise.value), rise.unit) / to_mm(float(run.value), run.unit), [rise, run]
    ratio = _value(store, subject, "slope_run_per_rise")
    if ratio and float(ratio.value) > 0:
        return 1 / float(ratio.value), [ratio]
    return None


def check_ramp_slope(rule: Rule, store: FactStore, profile: ShipProfile) -> list[Finding]:
    steepest = float(rule.params["max_run_per_rise"])
    required = f"No steeper than 1:{steepest:g}"
    why = "Ramp runs have a maximum running slope."
    subjects = store.subjects("ramp:")
    if not subjects:
        return [_finding(rule, Status.CANT_TELL, "ramps", "Ramps", measured="No ramps in the design data",
                         required=required, why=why, question="Add a drawing that gives ramp rise and run, or slope.")]
    assumptions = ["In alterations, steeper slopes up to 1:8 are allowed for small rises (Table V405.2). New construction is assumed."]
    findings = []
    for subject in subjects:
        name = subject.split(":", 1)[1]
        label = f"Ramp {name}"
        try:
            found = _ramp_slope(store, subject)
        except _Blocked as blocked:
            findings += _waiting(rule, blocked, label)
            continue
        if found is None:
            findings.append(_not_written(rule, subject, label, store.one(subject, "shown_on"), "Slope, or rise and run,",
                                         required=required, why=why,
                                         question=f"What is the slope of ramp {name}, or its rise and run?"))
            continue
        slope, facts = found
        unsure = any(f.confidence == "low" and not f.confirmed_by for f in facts)
        common = dict(measured=f"Slope 1:{1 / slope:.1f}" if slope > 0 else "Level", required=required, why=why,
                      inputs=tuple(facts), location=facts[0].location,
                      confidence="low" if unsure else facts[0].confidence, assumptions=assumptions)
        within = slope <= (1 / steepest) * (1 + FLOAT_SLACK)
        if within and unsure:
            findings.append(_finding(rule, Status.CANT_TELL, subject, label, **common,
                                     question=f"Confirm the slope of ramp {name}: the reading is uncertain."))
        elif within:
            findings.append(_finding(rule, Status.PASS, subject, label, **common))
        else:
            findings.append(_finding(rule, Status.FAIL, subject, label, **common,
                                     gap=f"{slope * steepest - 1:.0%} steeper than 1:{steepest:g}"))
    return findings
def _stair_need(rule: Rule, min_mm: float, persons: Fact | None) -> float:
    """FSS 13 2.1.1: 900 mm, plus 10 mm for every person over 90. Persons count whole, rounded up."""
    if persons is None:
        return min_mm
    over = max(0, math.ceil(round(float(persons.value) - float(rule.params.get("base_persons", 90)), 9)))
    return min_mm + float(rule.params.get("per_person_mm", 10)) * over


def _persons_on_board(store: FactStore) -> Fact | None:
    """The stated total only. Adding crew and science could undercount, which would lower the requirement."""
    return _value(store, "ship", "persons_on_board")


def check_raft_capacity(rule: Rule, store: FactStore, profile: ShipProfile) -> list[Finding]:
    label = "Liferaft capacity"
    fraction = float(rule.params["each_side_fraction"])
    try:
        persons, capacity = _persons_on_board(store), _value(store, "liferaft", "capacity_persons")
    except _Blocked as blocked:
        return _waiting(rule, blocked, label)
    rafts_by_side: dict[str, float] = defaultdict(float)
    first_rack: dict[str, Fact] = {}
    for subject in store.subjects("raft_rack:"):
        side, count = store.one(subject, "side"), store.one(subject, "raft_count")
        rafts_by_side[str(side.value)] += float(count.value)
        first_rack.setdefault(str(side.value), count)
    required = f"Capacity on each side of at least {fraction:.0%} of persons on board"
    racks = ", ".join(f"{n:g} rafts on {side}" for side, n in sorted(rafts_by_side.items()))
    if not rafts_by_side:
        # No racks means no data, not a ship without rafts, so this can't be a fail.
        return [_finding(rule, Status.CANT_TELL, "liferaft", label, measured="No liferaft racks in the design data",
                         required=required, why="Survival craft capacity must cover everyone on board.",
                         inputs=(persons, capacity), question="Add a 3D model that shows the liferaft racks.")]
    if persons is None or capacity is None:
        needs, missing_parts = [], []
        if persons is None:
            needs.append("How many persons does the ship carry at most?")
            missing_parts.append("persons on board")
        if capacity is None:
            needs.append("What is the rated capacity of each liferaft, in persons?")
            missing_parts.append("liferaft capacity")
        where = first_rack.get("port") or first_rack.get("starboard")
        return [_finding(rule, Status.CANT_TELL, "liferaft", label,
                         measured=f"Racks in the 3D model: {racks}. Not stated: {' and '.join(missing_parts)}.",
                         required=required, why="Survival craft capacity must cover everyone on board.",
                         inputs=(*first_rack.values(), persons), location=where.location if where else None,
                         question=" ".join(needs))]
    findings = []
    need = float(persons.value) * fraction
    for side in ("port", "starboard"):
        total = rafts_by_side.get(side, 0) * float(capacity.value)
        passed = total >= need
        rack = first_rack.get(side)
        findings.append(_finding(
            rule, Status.PASS if passed else Status.FAIL, f"liferaft:{side}", f"Liferaft capacity, {side}",
            measured=f"{rafts_by_side.get(side, 0):g} rafts x {capacity.value:g} persons = {total:g} persons",
            required=f"{need:g} persons ({fraction:.0%} of {persons.value:g} on board)",
            gap="" if passed else f"{need - total:g} persons short",
            why="Survival craft capacity must cover everyone on board.",
            inputs=(rack, persons, capacity), location=rack.location if rack else None))
    return findings


BRIDGE_INPUTS = {
    "eye_height_above_water": "height of the conning position eye line above the waterline",
    "obstruction_height_above_water": "height of the highest forward obstruction above the waterline",
    "eye_to_obstruction": "horizontal distance from the conning position to that obstruction",
    "eye_to_bow": "horizontal distance from the conning position to the bow",
}


def check_bridge_visibility(rule: Rule, store: FactStore, profile: ShipProfile) -> list[Finding]:
    label = "Blind zone ahead of the bow"
    max_lengths, max_metres = float(rule.params["max_ship_lengths"]), float(rule.params["max_metres"])
    try:
        facts = {name: _value(store, "bridge", name) for name in BRIDGE_INPUTS}
        length = _value(store, "ship", "length_overall")
    except _Blocked as blocked:
        return _waiting(rule, blocked, label)
    missing = [text for name, text in BRIDGE_INPUTS.items() if facts[name] is None]
    if length is None:
        missing.append("overall length of the ship")
    required = f"At most {max_lengths:g} ship lengths or {max_metres:g} m, whichever is less"
    why = "The sea surface ahead must be visible from the conning position."
    if missing:
        return [_finding(rule, Status.CANT_TELL, "bridge", label, measured="Sight line inputs not stated",
                         required=required, why=why, question="Please give the " + "; the ".join(missing) + ".")]
    eye = to_mm(float(facts["eye_height_above_water"].value), facts["eye_height_above_water"].unit) / 1000
    obstruction = to_mm(float(facts["obstruction_height_above_water"].value), facts["obstruction_height_above_water"].unit) / 1000
    to_obstruction = to_mm(float(facts["eye_to_obstruction"].value), facts["eye_to_obstruction"].unit) / 1000
    to_bow = to_mm(float(facts["eye_to_bow"].value), facts["eye_to_bow"].unit) / 1000
    limit = min(max_lengths * to_mm(float(length.value), length.unit) / 1000, max_metres)
    used = (*facts.values(), length)
    if obstruction >= eye:
        return [_finding(rule, Status.FAIL, "bridge", label, measured="The obstruction is at or above eye height, so the view is fully blocked",
                         required=f"{required} (limit here: {limit:.0f} m)", why=why, inputs=used)]
    # Similar triangles: the sight line over the obstruction meets the water here.
    blind = to_obstruction * eye / (eye - obstruction) - to_bow
    passed = blind <= limit
    return [_finding(rule, Status.PASS if passed else Status.FAIL, "bridge", label,
                     measured=f"{blind:.0f} m blind zone ahead of the bow", required=f"{required} (limit here: {limit:.0f} m)",
                     gap="" if passed else f"{blind - limit:.0f} m over", why=why, inputs=used,
                     assumptions=["Calculated for the waterline these heights were given at. Check all loading conditions.",
                                  "Dead ahead only. V/22.1.1 also covers 10 degrees either side of the bow, and 22.1.2 the blind sectors."])]


def check_masthead_height(rule: Rule, store: FactStore, profile: ShipProfile) -> list[Finding]:
    """COLREG Annex I 2(a)(i). Breadth means greatest breadth (Rule 3(j)), never the moulded beam.

    Greatest breadth is never less than the moulded beam, so the moulded beam gives a safe lower bound:
    a light below it fails for certain, a light at the 12 m cap passes for certain, and anything between
    needs the greatest breadth.
    """
    label = "Forward masthead light height"
    minimum, cap = float(rule.params["min_m"]), float(rule.params["cap_m"])
    try:
        height = _value(store, "masthead_forward", "height_above_hull")
        greatest, beam = _value(store, "ship", "breadth_greatest"), _value(store, "ship", "beam")
    except _Blocked as blocked:
        return _waiting(rule, blocked, label)
    why = "A power-driven ship's forward masthead light has a minimum height above the hull."
    required_text = f"At least {minimum:g} m, or the greatest breadth if larger, up to {cap:g} m"
    if height is None:
        lights = [store.one(s, "height_above_baseline") for s in store.subjects("nav_light:")]
        heights = ", ".join(f"{l.value:g}" for l in sorted(lights, key=lambda f: f.value))
        found = (f"The model has {len(lights)} navigation lights, not labelled by role, at {heights} m above baseline."
                 if lights else "No navigation lights in the design data")
        needs = ["Which light is the forward masthead light, and how high is it above the uppermost continuous deck, measured vertically beneath the light?"]
        if greatest is None:
            needs.append("What is the ship's greatest breadth?")
        return [_finding(rule, Status.CANT_TELL, "masthead_forward", label, measured=found, required=required_text,
                         why=why, inputs=tuple(lights[:1]), question=" ".join(needs))]
    have = to_mm(float(height.value), height.unit) / 1000
    if greatest is not None:
        breadth_m = to_mm(float(greatest.value), greatest.unit) / 1000
        need = min(max(minimum, breadth_m), cap)
        passed = have >= need
        return [_finding(rule, Status.PASS if passed else Status.FAIL, "masthead_forward", label,
                         measured=f"{have:.1f} m above the hull", required=f"At least {need:.1f} m for a {breadth_m:.2f} m greatest breadth",
                         gap="" if passed else f"{need - have:.1f} m short", why=why, inputs=(height, greatest),
                         location=height.location)]
    if have >= cap:
        return [_finding(rule, Status.PASS, "masthead_forward", label, measured=f"{have:.1f} m above the hull",
                         required=f"At least {cap:g} m whatever the breadth (the rule's cap)", why=why, inputs=(height,),
                         location=height.location)]
    floor = min(max(minimum, to_mm(float(beam.value), beam.unit) / 1000), cap) if beam is not None else minimum
    if have < floor:
        basis = f"the {to_mm(float(beam.value), beam.unit) / 1000:.2f} m moulded beam" if beam is not None and floor > minimum else f"the {minimum:g} m minimum"
        return [_finding(rule, Status.FAIL, "masthead_forward", label, measured=f"{have:.1f} m above the hull",
                         required=f"At least {floor:.1f} m ({basis}; greatest breadth can only raise it)",
                         gap=f"{floor - have:.1f} m short", why=why, inputs=(height, beam) if beam is not None and floor > minimum else (height,),
                         location=height.location)]
    return [_finding(rule, Status.CANT_TELL, "masthead_forward", label, measured=f"{have:.1f} m above the hull",
                     required=required_text, why=why, inputs=(height, beam),
                     question="What is the ship's greatest breadth? COLREG Rule 3(j) uses greatest breadth, not the moulded beam, and the limit here depends on it.",
                     location=height.location)]


def check_evacuation_time(rule: Rule, store: FactStore, profile: ShipProfile) -> list[Finding]:
    label = "Evacuation time"
    try:
        time, zones = _value(store, "evacuation", "time_minutes"), _value(store, "ship", "main_vertical_zones")
    except _Blocked as blocked:
        return _waiting(rule, blocked, label)
    why = "Passenger ships need an evacuation analysis within the time limit."
    if time is None or zones is None:
        needs = []
        if time is None:
            needs.append("What total evacuation time does the analysis give, in minutes?")
        if zones is None:
            needs.append("How many main vertical fire zones does the ship have?")
        missing = [text for fact, text in ((time, "the total evacuation time"), (zones, "the number of main vertical zones"))
                   if fact is None]
        return [_finding(rule, Status.CANT_TELL, "evacuation", label, measured="Not stated: " + " and ".join(missing),
                         required=f"{rule.params['max_minutes']:g} minutes, or {rule.params['max_minutes_large']:g} with more than {rule.params['large_zone_count']:g} fire zones",
                         why=why, question=" ".join(needs))]
    # MSC.1/Circ.1533 5.2: 80 minutes only for a passenger ship that isn't ro-ro and has more than three zones.
    over_zones = float(zones.value) > float(rule.params["large_zone_count"])
    small, large = float(rule.params["max_minutes"]), float(rule.params["max_minutes_large"])
    if over_zones and profile.ship_type == "passenger":
        limit = large
    elif profile.ship_type == "ro_ro_passenger" or not over_zones:
        limit = small
    elif float(time.value) <= small:
        limit = small  # passes even the stricter limit, so the ship type doesn't matter
    else:
        return [_finding(rule, Status.CANT_TELL, "evacuation", label, measured=f"{time.value:g} minutes",
                         required=f"At most {small:g} minutes for a ro-ro passenger ship, {large:g} for other passenger ships "
                                  f"with {zones.value:g} zones", why=why, inputs=(time, zones),
                         question="Is the ship a ro-ro passenger ship? MSC.1/Circ.1533 allows 80 minutes only for other "
                                  "passenger ships with more than three main vertical zones.")]
    # 5.1 sets a second standard: (E+L) at most 30 minutes. A pass needs both.
    el, el_limit = _best(store, "evacuation", "e_plus_l_minutes"), float(rule.params.get("max_e_plus_l_minutes", 30))
    total_ok = float(time.value) <= limit
    required = f"At most {limit:g} minutes with {zones.value:g} fire zones, and (E+L) at most {el_limit:g} minutes"
    if not total_ok:
        return [_finding(rule, Status.FAIL, "evacuation", label, measured=f"{time.value:g} minutes", required=required,
                         gap=f"{float(time.value) - limit:g} minutes over", why=why, inputs=(time, zones))]
    if el is None:
        return [_finding(rule, Status.CANT_TELL, "evacuation", label, measured=f"{time.value:g} minutes total; E+L not stated",
                         required=required, why=why, inputs=(time, zones),
                         question="What embarkation and launching time (E+L) does the analysis give, in minutes? "
                                  "MSC.1/Circ.1533 5.1 also requires (E+L) of 30 minutes or less.")]
    el_ok = float(el.value) <= el_limit
    return [_finding(rule, Status.PASS if el_ok else Status.FAIL, "evacuation", label,
                     measured=f"{time.value:g} minutes total, (E+L) {float(el.value):g} minutes", required=required,
                     gap="" if el_ok else f"(E+L) {float(el.value) - el_limit:g} minutes over", why=why, inputs=(time, zones, el))]


def _yes(fact: Fact | None) -> bool | None:
    if fact is None:
        return None
    text = str(fact.value).strip().lower()
    if text in ("yes", "y", "true", "1"):
        return True
    if text in ("no", "n", "false", "0"):
        return False
    return None


def _listed_door(rule: Rule, store: FactStore, profile: ShipProfile, subject: str, number: str,
                 min_in: float, min_mm: float, required: str) -> Finding:
    """A door stated by number, with the two limits that apply to every kind of reading."""
    finding = _listed_door_verdict(rule, store, profile, subject, number, min_in, min_mm, required)
    width = store.one(subject, "clear_width")
    if width is not None and finding.status == Status.PASS and width.confidence == "low" and not width.confirmed_by:
        # An uncertain reading must never pass: a false pass is the worst result.
        return finding.model_copy(update={
            "status": Status.CANT_TELL, "measured": f"{finding.measured}, read with low confidence", "confidence": "low",
            "question": f"Confirm the clear width of door {number}: the reading is uncertain."})
    if store.one(subject, "accessible_route") is None and profile.accessible_route_all_passage_doors:
        note = "Door known by its number. Its use isn't stated, so it's treated as a passage door on an accessible route."
        return finding.model_copy(update={"assumptions": [*finding.assumptions, note]})
    return finding


def _listed_door_verdict(rule: Rule, store: FactStore, profile: ShipProfile, subject: str, number: str,
                         min_in: float, min_mm: float, required: str) -> Finding:
    """A door stated by number in a schedule, drawing, or IFC model rather than the 3D model's parts.

    PVAG V404.2.3 (proposed): 32 in (815 mm) clear, or 36 in (915 mm) when the opening is more than 24 in (610 mm) deep.
    """
    label = f"Door {number}"
    try:
        route, width, depth = (_value(store, subject, "accessible_route"), _value(store, subject, "clear_width"),
                               _value(store, subject, "opening_depth"))
    except _Blocked as blocked:
        facts = store.get(subject, blocked.prop)
        return _finding(rule, Status.CONFLICT, subject, label, measured=" vs. ".join(dict.fromkeys(_show(f) for f in facts)),
                        required=required, why="Sources disagree on this door, so the check waits.", inputs=tuple(facts),
                        question=f"Which {_plain(blocked.prop).lower()} is correct for door {number}?")
    on_route = _yes(route)
    deep_in, deep_min_in = float(rule.params.get("deep_opening_in", 24)), float(rule.params.get("deep_min_in", 36))
    why = "Doors on accessible routes need a minimum clear width."
    if on_route is False:
        return _finding(rule, Status.NOT_APPLICABLE, subject, label, measured="Not on an accessible route",
                        required=required, why="The rule covers doors on accessible routes only.", inputs=(route,))
    if on_route is None and not profile.accessible_route_all_passage_doors:
        return _finding(rule, Status.CANT_TELL, subject, label, measured="Route not stated", required=required, why=why,
                        inputs=(width,), question=f"Is door {number} on an accessible route?")
    if width is None:
        # Says which text on the drawing caused this, when a label was found with no usable value beside it.
        return _not_written(rule, subject, label, store.one(subject, "shown_on"), "Clear width", required=required,
                            why=why, inputs=(route,), question=f"What is the clear width of door {number}?")
    width_mm, limit_mm, deep_limit_mm = to_mm(float(width.value), width.unit), to_mm(min_in, "in"), to_mm(deep_min_in, "in")
    measured = f"{fmt_length(float(width.value), width.unit)} clear width"
    # The team's rule: the inch figure governs (32 in is 812.8 mm, not the printed 815 mm). Say so when it matters.
    inch_notes = [f"Meets {lim_in:g} in, but is under the rule's printed {lim_mm:g} mm. The inch value is used."
                  for lim_in, lim_mm in ((min_in, min_mm), (deep_min_in, float(rule.params.get("deep_min_mm", 915))))
                  if to_mm(lim_in, "in") <= width_mm < lim_mm]
    if depth is not None:
        # "More than 24 in": 609.6 mm exactly is not deep (rounded, so 24 x 25.4 = 609.5999... can't tip it).
        deep = round(to_mm(float(depth.value), depth.unit), 6) > round(to_mm(deep_in, "in"), 6)
        need = deep_limit_mm if deep else limit_mm
        need_text = (f"At least {deep_min_in:g} in ({deep_limit_mm:.0f} mm): the opening is {fmt_length(float(depth.value), depth.unit)} deep, "
                     f"over {deep_in:g} in ({to_mm(deep_in, 'in'):.0f} mm)") if deep else required
        passed = width_mm >= need
        return _finding(rule, Status.PASS if passed else Status.FAIL, subject, label, measured=measured, required=need_text,
                        gap="" if passed else f"{need - width_mm:.0f} mm short", why=why, inputs=(width, depth, route),
                        assumptions=inch_notes if passed else [],
                        evidence=CheckBasis(measured=width_mm, limit=need, limit_unit="in", facts=[width]))
    if width_mm >= deep_limit_mm:
        return _finding(rule, Status.PASS, subject, label, measured=measured,
                        required=f"{required}; meets even the {deep_min_in:g} in limit for deep openings", why=why, inputs=(width, route),
                        assumptions=inch_notes,
                        evidence=CheckBasis(measured=width_mm, limit=deep_limit_mm, limit_unit="in", facts=[width]))
    if width_mm < limit_mm:
        return _finding(rule, Status.FAIL, subject, label, measured=measured, required=required,
                        gap=f"{(limit_mm - width_mm) / 25.4:.1f} in ({limit_mm - width_mm:.0f} mm) short", why=why, inputs=(width, route),
                        evidence=CheckBasis(measured=width_mm, limit=limit_mm, limit_unit="in", facts=[width]))
    if "openings_not_deep" in profile.approved_assumptions:
        return _finding(rule, Status.PASS, subject, label, measured=measured, required=required, why=why, inputs=(width, route),
                        assumptions=["Opening depth isn't stated; this ship's approved assumption is that openings aren't over 24 in deep.",
                                     *inch_notes],
                        evidence=CheckBasis(measured=width_mm, limit=limit_mm, limit_unit="in", facts=[width]))
    return _finding(rule, Status.CANT_TELL, subject, label, measured=measured, required=required, why=why, inputs=(width, route),
                    question=f"How deep is the opening of door {number}? Openings more than {deep_in:g} in ({to_mm(deep_in, 'in'):.0f} mm) deep need {deep_min_in:g} in ({deep_limit_mm:.0f} mm) clear.")


def _stated_stair(rule: Rule, store: FactStore, subject: str, min_mm: float) -> Finding:
    """A stair with a stated clear width. FSS Code ch. 13: 900 mm, plus 10 mm per person over 90."""
    name = subject.split(":", 1)[1]
    label = f"Stair {name}"
    per_person, base = float(rule.params.get("per_person_mm", 10)), float(rule.params.get("base_persons", 90))
    why = "Passenger ship escape stairs have a minimum clear width that grows with the persons they serve."
    try:
        width, persons = _value(store, subject, "clear_width"), _value(store, subject, "persons_served")
    except _Blocked as blocked:
        facts = store.get(subject, blocked.prop)
        return _finding(rule, Status.CONFLICT, subject, label, measured=" vs. ".join(dict.fromkeys(_show(f) for f in facts)),
                        required="One agreed value", why="Sources disagree on this stair, so the check waits.",
                        inputs=tuple(facts), question=f"Which {_plain(blocked.prop).lower()} is correct for stair {name}?")
    if width is None:
        return _finding(rule, Status.CANT_TELL, subject, label, measured="Clear width not stated",
                        required=f"At least {min_mm:g} mm clear width", why=why, inputs=(persons,),
                        question=f"What is the clear width of stair {name}?")
    w = to_mm(float(width.value), width.unit)
    measured = f"{fmt_length(float(width.value), width.unit)} clear width"
    if persons is None:
        if w < min_mm:
            return _finding(rule, Status.FAIL, subject, label, measured=measured, required=f"At least {min_mm:g} mm whatever the persons served",
                            gap=f"{min_mm - w:.0f} mm short", why=why, inputs=(width,),
                            evidence=CheckBasis(measured=w, limit=min_mm, limit_unit="mm", facts=[width]))
        return _finding(rule, Status.CANT_TELL, subject, label, measured=measured, required=f"At least {min_mm:g} mm, more above {base:g} persons",
                        why=why, inputs=(width,),
                        question=f"How many persons does stair {name} serve? The required width grows by {per_person:g} mm per person over {base:g}.")
    n = float(persons.value)
    need = _stair_need(rule, min_mm, persons)
    extra = f": {min_mm:g} mm plus {per_person:g} mm for each of the {n - base:g} persons over {base:g}" if n > base else f" for {n:g} persons"
    passed = w >= need
    return _finding(rule, Status.PASS if passed else Status.FAIL, subject, label, measured=measured,
                    required=f"At least {need:g} mm{extra}", gap="" if passed else f"{need - w:.0f} mm short", why=why,
                    inputs=(width, persons), evidence=CheckBasis(measured=w, limit=need, limit_unit="mm", facts=[width]),
                    assumptions=["Checked against FSS 13 2.1.1 only. The deck-by-deck calculation of 2.1.2 may need more."] if passed else [])


def check_lifeboat_capacity(rule: Rule, store: FactStore, profile: ShipProfile) -> list[Finding]:
    """SOLAS III/21.1.1.1: lifeboats on each side for at least 50% of the total persons on board."""
    fraction = float(rule.params["each_side_fraction"])
    why = "Lifeboats on each side must hold the required share of everyone on board."
    try:
        persons = _value(store, "ship", "persons_on_board")
        sides = {side: _value(store, f"lifeboats:{side}", "capacity_persons") for side in ("port", "starboard")}
    except _Blocked as blocked:
        return _waiting(rule, blocked, "Lifeboat capacity")
    if persons is None:
        return [_finding(rule, Status.CANT_TELL, "lifeboats", "Lifeboat capacity", measured="Persons on board not stated",
                         required=f"Each side at least {fraction:.0%} of persons on board", why=why,
                         inputs=tuple(f for f in sides.values() if f),
                         question="What total number of persons is the ship certified to carry? Berths don't count.")]
    findings = []
    need = float(persons.value) * fraction
    for side, cap in sides.items():
        label = f"Lifeboat capacity, {side}"
        if cap is None:
            findings.append(_finding(rule, Status.CANT_TELL, f"lifeboats:{side}", label, measured="Capacity not stated",
                                     required=f"{need:g} persons", why=why, inputs=(persons,),
                                     question=f"What is the total lifeboat capacity on the {side} side, in persons?"))
            continue
        have = float(cap.value)
        passed = have >= need
        findings.append(_finding(rule, Status.PASS if passed else Status.FAIL, f"lifeboats:{side}", label,
                                 measured=f"{have:g} persons", required=f"{need:g} persons ({fraction:.0%} of {float(persons.value):g} on board)",
                                 gap="" if passed else f"{need - have:g} persons short", why=why, inputs=(cap, persons)))
    return findings


def check_liferaft_total(rule: Rule, store: FactStore, profile: ShipProfile) -> list[Finding]:
    """SOLAS III/21.1.1: in addition to lifeboats, liferafts for at least 25% of the total persons on board."""
    fraction = float(rule.params["total_fraction"])
    label = "Liferaft capacity"
    why = "Passenger ships carry liferafts for a further share of everyone on board."
    try:
        persons, count, each = _value(store, "ship", "persons_on_board"), _value(store, "liferafts", "count"), _value(store, "liferaft", "capacity_persons")
    except _Blocked as blocked:
        return _waiting(rule, blocked, label)
    missing = [text for fact, text in ((persons, "the certified persons on board"), (count, "the number of liferafts"),
                                       (each, "the rated capacity of each liferaft")) if fact is None]
    required = f"Total at least {fraction:.0%} of persons on board"
    if missing:
        return [_finding(rule, Status.CANT_TELL, "liferafts", label, measured="Not stated: " + ", ".join(missing),
                         required=required, why=why, inputs=(persons, count, each),
                         question="Please state " + " and ".join(missing) + ".")]
    have, need = float(count.value) * float(each.value), float(persons.value) * fraction
    passed = have >= need
    return [_finding(rule, Status.PASS if passed else Status.FAIL, "liferafts", label,
                     measured=f"{float(count.value):g} liferafts x {float(each.value):g} persons = {have:g} persons",
                     required=f"{need:g} persons ({fraction:.0%} of {float(persons.value):g} on board)",
                     gap="" if passed else f"{need - have:g} persons short", why=why, inputs=(count, each, persons))]


def check_evacuation_analysis_exists(rule: Rule, store: FactStore, profile: ShipProfile) -> list[Finding]:
    """SOLAS II-2/13.3.2.7: escape routes evaluated by an evacuation analysis early in the design process.

    Presence can be proven by a document; absence can't be proven from a partial package, so it is never a fail.
    """
    present = _best(store, "evacuation", "analysis_present")
    label = "Evacuation analysis"
    why = "New passenger ships need an evacuation analysis early in the design process."
    if present is not None and _yes(present):
        return [_finding(rule, Status.PASS, "evacuation", label, measured=f"Found: {present.source.describe()}",
                         required="An evacuation analysis in the package", why=why, inputs=(present,))]
    return [_finding(rule, Status.CANT_TELL, "evacuation", label, measured="No evacuation analysis in the uploaded files",
                     required="An evacuation analysis in the package", why=why,
                     question="Upload the evacuation analysis (SOLAS II-2/13.3.2.7, MSC.1/Circ.1533).")]


def check_consistency(store: FactStore) -> list[Finding]:
    """Flag any value that two sources give differently."""
    findings = []
    keys = {fact.key() for fact in store.facts}
    for subject, prop in sorted(keys):
        facts = _disagreement(store, subject, prop)
        if facts:
            located = next((f.location for f in facts if f.location), None)
            values = list(dict.fromkeys(_show(f) for f in facts))
            findings.append(_finding(CONSISTENCY_RULE, Status.CONFLICT, f"{subject}.{prop}", _plain(prop),
                                     measured=" vs. ".join(values), required="One agreed value",
                                     why="Sources disagree, so at least one is wrong.",
                                     sources=[f"{_show(f)}: {f.source.describe()}" for f in facts], location=located,
                                     question=f"Which {_plain(prop).lower()} is correct?"))
    return findings


def check_drawing_scales(store: FactStore) -> list[Finding]:
    """A sheet whose scale note disagrees with the scale it's really drawn at: anything scaled off it would be wrong."""
    findings = []
    for subject in store.subjects("drawing:"):
        noted, measured = _best(store, subject, "scale_noted"), _best(store, subject, "scale_measured")
        if noted is None or measured is None:
            continue
        name = subject.split(":", 1)[1]
        agrees = abs(float(noted.value) - float(measured.value)) <= SCALE_TOLERANCE * float(measured.value)
        findings.append(_finding(
            SCALE_RULE, Status.PASS if agrees else Status.CONFLICT, subject, f"Scale of drawing {name}",
            measured=f"Drawn at 1:{float(measured.value):g}", required=f"The note's 1:{float(noted.value):g}",
            why="Any distance scaled off the sheet with the wrong scale is wrong by the same factor.",
            inputs=(noted, measured),
            question="" if agrees else (f"The sheet says 1:{float(noted.value):g} but measures 1:{float(measured.value):g} "
                                        f"({measured.derivation}) Which is right? Until then, nothing is scaled off this sheet.")))
    return findings


CHECKS: dict[str, Callable[[Rule, FactStore, ShipProfile], list[Finding]]] = {
    "door_clear_width": check_door_clear_width,
    "stair_width": check_stair_width,
    "corridor_width": check_corridor_width,
    "ramp_slope": check_ramp_slope,
    "raft_capacity": check_raft_capacity,
    "bridge_visibility": check_bridge_visibility,
    "masthead_height": check_masthead_height,
    "evacuation_time": check_evacuation_time,
    "lifeboat_capacity": check_lifeboat_capacity,
    "liferaft_total": check_liferaft_total,
    "evacuation_analysis_exists": check_evacuation_analysis_exists,
}
