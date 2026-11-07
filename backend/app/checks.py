"""Deterministic compliance checks. No AI here: code alone decides every result.

Each check takes a rule, the fact store, and the ship profile, and returns findings.
Missing data gives "can't tell", never a pass. A false pass is the worst possible result.
"""
from __future__ import annotations

from collections import defaultdict
from typing import Callable

from .models import Evidence, Fact, Finding, Rule, ShipProfile, Status
from .store import FactStore
from .units import fmt_length, is_length_unit, to_mm

CONSISTENCY_RULE = Rule(
    id="CROSS-CHECK",
    title="Sources must agree",
    area="Consistency",
    source="Cross-check between design sources",
    check="consistency",
    verified=True,
)
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
}


def _plain(prop: str) -> str:
    return PLAIN_NAMES.get(prop, prop.replace("_", " ").capitalize())


def describe_fact(fact: Fact) -> str:
    """A recorded fact in plain words, like "Crew count: 12 persons"."""
    door = f"Door {fact.subject.split(':', 1)[1]} " if fact.subject.startswith("door-number:") else ""
    name = _plain(fact.property)
    return f"{door}{name.lower() if door else name}: {_show(fact)}"


def _finding(rule: Rule, status: Status, subject: str, label: str, **fields) -> Finding:
    return Finding(rule_id=rule.id, rule_title=rule.title, area=rule.area, rule_source=rule.source,
                   status=status, subject=subject, label=label, provisional=not rule.verified,
                   unconfirmed_label=rule.unconfirmed_label(), **fields)


def _sources(*facts: Fact | None) -> list[str]:
    return list(dict.fromkeys(f.source.describe() for f in facts if f))


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


def _value(store: FactStore, subject: str, prop: str) -> Fact | None:
    if _disagreement(store, subject, prop):
        raise _Blocked(subject, prop)
    return store.one(subject, prop)


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


def _drawing_doors(rule: Rule, store: FactStore, conflicts: dict, required: str, assumptions: list[str],
                   why: str) -> list[Finding]:
    """Doors known only from a drawing or chat, by number, that the 3D model doesn't already cover."""
    in_model = {number for subject in store.subjects("door:") if (numbers := store.one(subject, "numbers")) and numbers.value
                for number in str(numbers.value).split(",")}
    min_in, min_mm = float(rule.params["min_in"]), float(rule.params["min_mm"])
    door_assumptions = assumptions + ["Door known from a drawing by its number. Its use isn't stated, so it's treated as a passage door."]
    findings = []
    for subject in store.subjects("door-number:"):
        number = subject.split(":", 1)[1]
        if number in in_model or number in conflicts:
            continue
        width, label = store.one(subject, "clear_width"), f"Door {number}"
        if width is None:
            shown = store.one(subject, "shown_on")
            findings.append(_finding(rule, Status.CANT_TELL, subject, label, measured="Clear width not written on the drawing",
                                     required=required, why=why, sources=_sources(shown), assumptions=door_assumptions,
                                     question=f"What is the clear width of door {number}?"))
            continue
        passed, width_mm, limit_mm, gap, note = _width_verdict(width, min_in, min_mm)
        if passed and width.confidence == "low":
            # An uncertain reading must never pass: a false pass is the worst result.
            findings.append(_finding(rule, Status.CANT_TELL, subject, label,
                                     measured=f"{fmt_length(float(width.value), width.unit)} clear width, read with low confidence",
                                     required=required, why=why, sources=_sources(width), location=width.location,
                                     confidence="low", assumptions=door_assumptions,
                                     question=f"Confirm the clear width of door {number}: the reading is uncertain."))
            continue
        findings.append(_finding(
            rule, Status.PASS if passed else Status.FAIL, subject, label,
            measured=f"{fmt_length(float(width.value), width.unit)} clear width", required=required, gap=gap, why=why,
            sources=_sources(width), location=width.location, confidence=width.confidence,
            assumptions=door_assumptions + note,
            evidence=Evidence(measured=width_mm, limit=limit_mm, limit_unit="in", facts=[width])))
    return findings


def check_door_clear_width(rule: Rule, store: FactStore, profile: ShipProfile) -> list[Finding]:
    min_in, min_mm = float(rule.params["min_in"]), float(rule.params["min_mm"])
    required = f"At least {min_in:g} in ({min_mm:g} mm) clear width"
    assumptions = ["Opening depth isn't stated. Openings more than 24 in deep need 36 in, which this doesn't test."]
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
        if (not passed and rule.params.get("stairway_door_exception") and compartment
                and "STAIR" in str(compartment.value).upper()):
            # The rule lets this door follow another authority's limit, which we don't have.
            status = Status.CANT_TELL
            question = f"This door leads to a stairway, so the rule defers to the administrative authority. What width does it require for {label}?"
        findings.append(_finding(
            rule, status, subject, label,
            where=str(deck.value) if deck else "", measured=f"{fmt_length(float(width.value), width.unit)} clear width",
            required=required, gap=gap if status == Status.FAIL else "", why=why, sources=_sources(width), location=width.location,
            confidence="medium", assumptions=door_assumptions, question=question,
            evidence=Evidence(measured=width_mm, limit=limit_mm, limit_unit="in", facts=[width])))
    findings += _drawing_doors(rule, store, conflicts, required, assumptions, why)
    for number, widths in sorted(conflicts.items()):
        findings.append(_finding(
            rule, Status.CONFLICT, f"door-number:{number}", f"Door {number}",
            measured=" vs. ".join(_show(w) for w in widths), required=required,
            why="The 3D model gives this door number two different clear widths, so one record is wrong.",
            sources=_sources(*widths), location=widths[0].location,
            question=f"Which clear width is correct for door {number}?"))
    for name, subjects in sorted(missing.items()):
        first = store.one(subjects[0], "name")
        findings.append(_finding(
            rule, Status.CANT_TELL, subjects[0], f"{name} ({len(subjects)} in the model)",
            measured="Clear width not stated", required=required, why=why, sources=_sources(first),
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
        name, deck = store.one(subject, "name"), store.one(subject, "deck")
        tread = store.one(subject, "tread_length")
        common = dict(where=str(deck.value) if deck else "", required=required, assumptions=assumptions,
                      why="Passenger ship escape stairs have a minimum clear width.")
        place = "exterior" if "EXTERIOR" in str(name.value).upper() else "interior"
        label = f"Stair {subject.split(':')[1]} ({place})"
        if tread is None:
            findings.append(_finding(rule, Status.CANT_TELL, subject, label, measured="Tread length not stated",
                                     sources=_sources(name), location=name.location,
                                     question=f"What is the clear width of stair {subject.split(':')[1]} ({name.value})?",
                                     **common))
            continue
        mm = to_mm(float(tread.value), tread.unit)
        measured = f"{fmt_length(float(tread.value), tread.unit)} tread length"
        sources, location = _sources(tread), tread.location
        if mm < min_mm:
            findings.append(_finding(rule, Status.FAIL, subject, label, measured=measured,
                                     gap=f"{min_mm - mm:.0f} mm short", sources=sources, location=location,
                                     confidence="high", evidence=Evidence(measured=mm, limit=min_mm, limit_unit="mm", facts=[tread]),
                                     **common))
        elif mm >= min_mm + allowance:
            findings.append(_finding(rule, Status.PASS, subject, label, measured=measured, sources=sources,
                                     location=location, confidence="medium", **common))
        else:
            findings.append(_finding(rule, Status.CANT_TELL, subject, label, measured=measured, sources=sources,
                                     location=location,
                                     question=f"What is the clear width between handrails on stair {subject.split(':')[1]}?",
                                     **common))
    return findings


def _persons_on_board(store: FactStore) -> Fact | None:
    """A stated total, or crew plus science when both are stated. Code does the sum, never the AI."""
    stated = _value(store, "ship", "persons_on_board")
    if stated:
        return stated
    crew, science = _value(store, "ship", "crew_complement"), _value(store, "ship", "science_complement")
    if crew is None or science is None:
        return None
    source = crew.source.model_copy(update={"locator": f"{crew.value:g} crew + {science.value:g} science"})
    return Fact(subject="ship", property="persons_on_board", value=float(crew.value) + float(science.value), source=source)


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
                         sources=_sources(persons, capacity), question="Add a 3D model that shows the liferaft racks.")]
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
                         sources=_sources(*first_rack.values(), persons), location=where.location if where else None,
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
            sources=_sources(rack, persons, capacity), location=rack.location if rack else None))
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
    sources = _sources(*facts.values(), length)
    if obstruction >= eye:
        return [_finding(rule, Status.FAIL, "bridge", label, measured="The obstruction is at or above eye height, so the view is fully blocked",
                         required=f"{required} (limit here: {limit:.0f} m)", why=why, sources=sources)]
    # Similar triangles: the sight line over the obstruction meets the water here.
    blind = to_obstruction * eye / (eye - obstruction) - to_bow
    passed = blind <= limit
    return [_finding(rule, Status.PASS if passed else Status.FAIL, "bridge", label,
                     measured=f"{blind:.0f} m blind zone ahead of the bow", required=f"{required} (limit here: {limit:.0f} m)",
                     gap="" if passed else f"{blind - limit:.0f} m over", why=why, sources=sources,
                     assumptions=["Calculated for the waterline these heights were given at. Check all loading conditions."])]


def check_masthead_height(rule: Rule, store: FactStore, profile: ShipProfile) -> list[Finding]:
    label = "Forward masthead light height"
    minimum, cap = float(rule.params["min_m"]), float(rule.params["cap_m"])
    try:
        height, beam = _value(store, "masthead_forward", "height_above_hull"), _value(store, "ship", "beam")
    except _Blocked as blocked:
        return _waiting(rule, blocked, label)
    why = "A power-driven ship's forward masthead light has a minimum height above the hull."
    if height is None or beam is None:
        lights = [store.one(s, "height_above_baseline") for s in store.subjects("nav_light:")]
        heights = ", ".join(f"{l.value:g}" for l in sorted(lights, key=lambda f: f.value))
        found = (f"The model has {len(lights)} navigation lights, not labelled by role, at {heights} m above baseline."
                 if lights else "No navigation lights in the design data")
        needs = []
        if height is None:
            needs.append("Which light is the forward masthead light, and how high is it above the uppermost continuous deck, measured vertically beneath the light?")
        if beam is None:
            needs.append("What is the ship's beam?")
        return [_finding(rule, Status.CANT_TELL, "masthead_forward", label,
                         measured=found,
                         required=f"At least {minimum:g} m, or the beam if larger, up to {cap:g} m", why=why,
                         sources=_sources(*lights[:1]), question=" ".join(needs))]
    beam_m = to_mm(float(beam.value), beam.unit) / 1000
    need = min(max(minimum, beam_m), cap)
    have = to_mm(float(height.value), height.unit) / 1000
    passed = have >= need
    return [_finding(rule, Status.PASS if passed else Status.FAIL, "masthead_forward", label,
                     measured=f"{have:.1f} m above the hull", required=f"At least {need:.1f} m for a {beam_m:.1f} m beam",
                     gap="" if passed else f"{need - have:.1f} m short", why=why, sources=_sources(height, beam),
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
        return [_finding(rule, Status.CANT_TELL, "evacuation", label, measured="No evacuation analysis provided",
                         required=f"{rule.params['max_minutes']:g} minutes, or {rule.params['max_minutes_large']:g} with more than {rule.params['large_zone_count']:g} fire zones",
                         why=why, question=" ".join(needs))]
    large = float(zones.value) > float(rule.params["large_zone_count"])
    limit = float(rule.params["max_minutes_large"] if large else rule.params["max_minutes"])
    passed = float(time.value) <= limit
    return [_finding(rule, Status.PASS if passed else Status.FAIL, "evacuation", label,
                     measured=f"{time.value:g} minutes", required=f"At most {limit:g} minutes with {zones.value:g} fire zones",
                     gap="" if passed else f"{float(time.value) - limit:g} minutes over", why=why, sources=_sources(time, zones))]


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


CHECKS: dict[str, Callable[[Rule, FactStore, ShipProfile], list[Finding]]] = {
    "door_clear_width": check_door_clear_width,
    "stair_width": check_stair_width,
    "raft_capacity": check_raft_capacity,
    "bridge_visibility": check_bridge_visibility,
    "masthead_height": check_masthead_height,
    "evacuation_time": check_evacuation_time,
}
