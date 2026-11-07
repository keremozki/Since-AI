"""The checks decide every result, so these guard above all against false passes."""
from pathlib import Path

from app.checks import check_bridge_visibility, check_door_clear_width, check_masthead_height, check_raft_capacity, check_stair_width
from app.engine import report_text, run
from app.models import Fact, Rule, ShipProfile, Source, SourceKind, Status
from app.parts import door_numbers, facts_from_parts
from app.profiles import PROFILES
from app.rules import load_rules
from app.store import FactStore

ROOT = Path(__file__).resolve().parents[2]
HAS_IMO_TEXTS = (ROOT / "docs" / "rules" / "imo" / "rule-quotes.yaml").exists()  # local files, not in the public repo
PASSENGER = PROFILES["passenger-test"]
SRC = Source(kind=SourceKind.CHAT)


def door_part(name, description=None, z=336.7, y=10.0, item=None):
    part = {"name": name, "x_in": -600.0, "y_in": y, "z_in": z}
    if description:
        part["description"] = description
    if item:
        part["item"] = item
    return part


def fact(subject, prop, value, unit=""):
    return Fact(subject=subject, property=prop, value=value, unit=unit, source=SRC)


DOOR_RULE = Rule(id="D", title="Door", area="A", source="S", check="door_clear_width", params={"min_in": 32, "min_mm": 815})
STAIR_RULE = Rule(id="S", title="Stair", area="A", source="S", check="stair_width", params={"min_mm": 900, "handrail_allowance_mm": 100})
RAFT_RULE = Rule(id="R", title="Raft", area="A", source="S", check="raft_capacity", params={"each_side_fraction": 1.0})
BRIDGE_RULE = Rule(id="B", title="Bridge", area="A", source="S", check="bridge_visibility", params={"max_ship_lengths": 2, "max_metres": 500})
MAST_RULE = Rule(id="M", title="Mast", area="A", source="S", check="masthead_height", params={"min_m": 6, "cap_m": 12})


def doors(*parts, extra=()):
    store = FactStore(facts_from_parts("model", list(parts)) + list(extra))
    return check_door_clear_width(DOOR_RULE, store, PASSENGER)


def test_door_narrower_than_limit_fails_with_gap():
    finding = doors(door_part("B-CLASS DOOR (RI)-225", "CLEAR OPENING 26x78"))[0]
    assert finding.status == Status.FAIL
    assert finding.gap.startswith("6.0 in")
    assert finding.label == "Door 225"


def test_door_at_32_inches_passes():
    # 32 in is 812.8 mm, under the rounded 815 mm figure. The inch value governs.
    assert doors(door_part("A-CLASS DOOR (LI)-212", "CLEAR OPENNG 32x78"))[0].status == Status.PASS


def test_door_at_813_mm_passes_and_says_why():
    finding = doors(door_part("WATERTIGHT STEEL DOOR 201", "LIGHT OPENING 813x1981"))[0]
    assert finding.status == Status.PASS and finding.confidence == "medium"
    assert any("815 mm" in text for text in finding.assumptions)


def test_door_just_under_32_inches_fails():
    assert doors(door_part("A-CLASS DOOR (LI)-212", "CLEAR OPENNG 31.9x78"))[0].status == Status.FAIL


def test_metric_door_compared_against_metric_limit():
    assert doors(door_part("WATERTIGHT STEEL DOOR 516", "LIGHT OPENING 762x1981"))[0].status == Status.FAIL
    assert doors(door_part("WATERTIGHT STEEL DOOR 501", "LIGHT OPENING 914x1981"))[0].status == Status.PASS


def test_door_without_width_is_cant_tell_never_pass():
    finding = doors(door_part("SLIDING W/T DOOR FLUSH R", "SLIDING WATERTIGHT DOOR, FLUSH SILL"))[0]
    assert finding.status == Status.CANT_TELL
    assert "clear width" in finding.question


def test_width_for_a_part_type_answers_the_question():
    extra = [fact("door-type:SLIDING W/T DOOR FLUSH R", "clear_width", 30.0, "in")]
    assert doors(door_part("SLIDING W/T DOOR FLUSH R"), extra=extra)[0].status == Status.FAIL


def test_no_door_data_is_cant_tell_not_silence():
    finding = check_door_clear_width(DOOR_RULE, FactStore(), PASSENGER)[0]
    assert finding.status == Status.CANT_TELL and finding.measured == "No doors in the design data"


def test_no_stair_data_is_cant_tell_not_silence():
    finding = check_stair_width(STAIR_RULE, FactStore(), PASSENGER)[0]
    assert finding.status == Status.CANT_TELL and finding.measured == "No stairs in the design data"


def test_service_access_doors_are_not_checked():
    assert doors(door_part("ACCESS DOOR CEILING TJMB0- C/O 23.625x17.72")) == []


def test_two_widths_for_one_door_number_is_a_conflict():
    findings = doors(door_part("B-CLASS DOOR (RI)-223", "CLEAR OPENING 30x78"),
                     door_part("WATERTIGHT STEEL DOOR 223", "LIGHT OPENING 610x1829", item="6231-223"))
    assert [f.status for f in findings] == [Status.CONFLICT]
    assert "30 in" in findings[0].measured and "610 mm" in findings[0].measured


def test_part_listing_several_doors_keeps_only_this_deck():
    assert door_numbers(door_part("B-CLASS DOOR (RI-LO)-205,207,304", z=336.7)) == ["205", "207"]
    assert door_numbers(door_part("B-CLASS DOOR (RI-LO)-205,207,304", z=444.7)) == ["304"]


def stairs(length_description):
    part = {"name": "STAIR TREADS INTERIOR 1", "x_in": 0.0, "y_in": 0.0, "z_in": 200.0}
    if length_description:
        part["description"] = length_description
    return check_stair_width(STAIR_RULE, FactStore(facts_from_parts("model", [part])), PASSENGER)[0]


def test_stair_tread_shorter_than_limit_fails():
    assert stairs('MODEL 30"L x 9"W').status == Status.FAIL


def test_stair_within_handrail_margin_is_cant_tell_not_pass():
    assert stairs('MODEL 36"L x 9"W').status == Status.CANT_TELL


def test_stair_well_above_limit_still_needs_the_persons_served():
    # FSS 13 2.1.1 adds 10 mm per person over 90, so no width can pass without the persons served.
    finding = stairs('MODEL 40"L x 9"W')
    assert finding.status == Status.CANT_TELL and "persons" in finding.question


def test_stair_with_persons_served_passes_or_fails_on_the_fss_formula():
    def with_persons(n, tread='MODEL 40"L x 9"W'):
        part = {"name": "STAIR TREADS INTERIOR 1", "x_in": 0.0, "y_in": 0.0, "z_in": 200.0, "description": tread}
        facts = facts_from_parts("model", [part])
        subject = next(f.subject for f in facts if f.subject.startswith("stair:"))
        return check_stair_width(STAIR_RULE, FactStore(facts + [fact(subject, "persons_served", float(n))]), PASSENGER)[0]

    assert with_persons(60).status == Status.PASS  # 1016 mm against 900 mm, with the 100 mm handrail margin
    assert with_persons(100).status == Status.CANT_TELL  # 1016 mm against 1000 mm: inside the handrail margin
    finding = with_persons(150)  # needs 1500 mm
    assert finding.status == Status.FAIL and finding.gap == "484 mm short"


def test_stair_without_dimension_is_cant_tell():
    assert stairs(None).status == Status.CANT_TELL


def rafts(*extra):
    racks = [door_part("LIFERAFT DOUBLE RACK", y=-200.0), door_part("LIFERAFT SINGLE RACK", y=200.0)]
    return check_raft_capacity(RAFT_RULE, FactStore(facts_from_parts("model", racks) + list(extra)), PASSENGER)


def test_raft_capacity_unknown_names_what_is_missing():
    finding = rafts()[0]
    assert finding.status == Status.CANT_TELL
    assert "rated capacity" in finding.question and "persons" in finding.question


def test_raft_capacity_is_checked_per_side():
    results = {f.subject: f.status for f in rafts(fact("ship", "persons_on_board", 29.0), fact("liferaft", "capacity_persons", 16.0))}
    assert results == {"liferaft:port": Status.FAIL, "liferaft:starboard": Status.PASS}


def test_persons_on_board_is_asked_for_never_added_up():
    finding = rafts(fact("ship", "crew_complement", 12.0), fact("ship", "science_complement", 16.0),
                    fact("liferaft", "capacity_persons", 16.0))[0]
    assert finding.status == Status.CANT_TELL
    assert "How many persons" in finding.question


def test_disagreeing_persons_on_board_block_the_raft_check():
    finding = rafts(fact("ship", "persons_on_board", 28.0), fact("ship", "persons_on_board", 29.0),
                    fact("liferaft", "capacity_persons", 16.0))[0]
    assert finding.status == Status.CONFLICT
    assert "persons on board" in finding.measured


def test_conflict_shows_each_value_once_and_ties_sources_to_values():
    def stated(value, file):
        return Fact(subject="ship", property="length_overall", value=value, unit="ft",
                    source=Source(kind=SourceKind.DOCUMENT, file=file))

    store = FactStore([stated(199.5, "a.pdf"), stated(192.8, "b.pdf"), stated(199.5, "c.pdf")])
    finding = run(store, [], PROFILES["rcrv"]).findings[0]
    assert finding.label == "Overall length"
    assert finding.measured == "199.5 ft vs. 192.8 ft"
    assert finding.sources == ["199.5 ft: Document: a.pdf", "192.8 ft: Document: b.pdf", "199.5 ft: Document: c.pdf"]


def test_disagreeing_input_blocks_the_check():
    finding = rafts(fact("ship", "persons_on_board", 29.0), fact("ship", "persons_on_board", 33.0),
                    fact("liferaft", "capacity_persons", 16.0))[0]
    assert finding.status == Status.CONFLICT


def bridge(eye, obstruction, distance=10.0, bow=20.0, length=60.0):
    store = FactStore([fact("bridge", "eye_height_above_water", eye, "m"),
                       fact("bridge", "obstruction_height_above_water", obstruction, "m"),
                       fact("bridge", "eye_to_obstruction", distance, "m"), fact("bridge", "eye_to_bow", bow, "m"),
                       fact("ship", "length_overall", length, "m")])
    return check_bridge_visibility(BRIDGE_RULE, store, PASSENGER)[0]


def test_bridge_blind_zone_calculation():
    # 10 m to the obstruction, with 15 m eye and 10 m obstruction heights: 30 m, minus 20 m to the bow.
    assert bridge(15.0, 10.0).measured.startswith("10 m")
    assert bridge(15.0, 10.0).status == Status.PASS


def test_bridge_uses_two_lengths_when_under_500_m():
    finding = bridge(15.0, 14.5, distance=10.0)  # 300 m to the water, 280 m past the bow, limit 120 m.
    assert finding.status == Status.FAIL and "limit here: 120 m" in finding.required


def test_bridge_obstruction_above_eye_fails():
    assert bridge(10.0, 12.0).status == Status.FAIL


def test_bridge_missing_inputs_ask_for_them():
    finding = check_bridge_visibility(BRIDGE_RULE, FactStore(), PASSENGER)[0]
    assert finding.status == Status.CANT_TELL and "conning position" in finding.question


def test_masthead_limit_follows_beam_up_to_cap():
    def status(height, beam):
        store = FactStore([fact("masthead_forward", "height_above_hull", height, "m"), fact("ship", "beam", beam, "m")])
        return check_masthead_height(MAST_RULE, store, PASSENGER)[0].status

    assert status(11.0, 12.5) == Status.FAIL  # Beam 12.5 m, capped at 12 m.
    assert status(12.0, 12.5) == Status.PASS
    # COLREG Rule 3(j) uses greatest breadth, which can exceed the moulded beam. With only a 5.0 m beam
    # known, a 6.0 m light passes only if the greatest breadth is 6 m or less, so this can't be a pass.
    assert status(6.0, 5.0) == Status.CANT_TELL
    assert status(5.9, 5.0) == Status.FAIL


def test_masthead_uses_greatest_breadth_when_stated():
    def check(height, greatest, beam=None):
        facts = [fact("masthead_forward", "height_above_hull", height, "m"), fact("ship", "breadth_greatest", greatest, "m")]
        if beam is not None:
            facts.append(fact("ship", "beam", beam, "m"))
        return check_masthead_height(MAST_RULE, FactStore(facts), PASSENGER)[0]

    assert check(6.0, 5.8, beam=5.0).status == Status.PASS
    finding = check(6.2, 6.5, beam=6.0)  # passes on the moulded beam, fails on the greatest breadth
    assert finding.status == Status.FAIL and finding.gap == "0.3 m short"
    assert check(12.0, 37.4).status == Status.PASS  # capped at 12 m


def test_masthead_between_beam_and_cap_asks_for_greatest_breadth():
    store = FactStore([fact("masthead_forward", "height_above_hull", 8.0, "m"), fact("ship", "beam", 7.5, "m")])
    finding = check_masthead_height(MAST_RULE, store, PASSENGER)[0]
    assert finding.status == Status.CANT_TELL and "greatest breadth" in finding.question


def rules():
    return load_rules(ROOT / "rules" / "rules.yaml", ROOT / "docs" / "rules")


def test_scope_excludes_passenger_rules_for_the_research_vessel():
    result = run(FactStore(), rules(), PROFILES["rcrv"])
    excluded = {d.rule_id for d in result.scope if not d.applies}
    assert excluded == {"PVAG-V404.2.3", "PVAG-V403.5.1", "PVAG-V405.2", "FSS-13-STAIR", "MSC.1-CIRC.1533",
                        "SOLAS-III-21-LIFEBOATS", "SOLAS-III-21-LIFERAFTS", "SOLAS-II-2-13.3.2.7"}
    assert not any(f.rule_id in excluded for f in result.findings)


def test_unknown_data_never_produces_a_pass():
    result = run(FactStore(), rules(), PASSENGER)
    assert result.counts["pass"] == 0
    assert "No issues found" not in result.summary


def test_all_clear_message_only_when_everything_passes():
    profile = ShipProfile(id="x", name="x", ship_type="research")
    rule = Rule(id="M", title="Mast", area="A", source="S", check="masthead_height", params={"min_m": 6, "cap_m": 12})
    store = FactStore([fact("masthead_forward", "height_above_hull", 12.0, "m"), fact("ship", "beam", 12.0, "m")])
    result = run(store, [rule], profile)
    assert result.summary.startswith("No issues found in 1 checks")
    assert "final call" in result.summary


def test_conflict_between_sources_is_flagged():
    store = FactStore([fact("ship", "lightship_weight", 2600.0, "LT"), fact("ship", "lightship_weight", 2510.0, "LT")])
    result = run(store, [], PROFILES["rcrv"])
    assert result.counts["conflict"] == 1
    assert "2600 LT vs. 2510 LT" in result.findings[0].measured


def test_rules_without_a_found_quote_are_provisional():
    assert all(not rule.verified for rule in rules() if not rule.quote)
    findings = run(FactStore(), rules(), PASSENGER).findings
    assert any(f.provisional for f in findings)
    assert "not yet confirmed" in report_text(run(FactStore(), rules(), PASSENGER))


def test_labels_name_the_rule_text_we_could_not_get():
    findings = run(FactStore(), rules(), PASSENGER).findings
    labels = {f.rule_id: f.unconfirmed_label for f in findings}
    assert labels["SOLAS-III-RAFTS"] == "Limit not yet confirmed: SOLAS III not retrieved"
    assert labels["COLREG-ANNEX-I"] == ""
    # The local IMO texts hold the quotes of these rules. A fresh clone doesn't have them, and says so.
    assert labels["SOLAS-V-22"] == ("" if HAS_IMO_TEXTS else "Limit not yet confirmed: SOLAS V/22 not retrieved")
    assert labels["MSC.1-CIRC.1533"] == ("" if HAS_IMO_TEXTS else "Limit not yet confirmed: MSC.1/Circ.1533 not retrieved")
    text = report_text(run(FactStore(), rules(), PASSENGER))
    assert "Note: Limit not yet confirmed: SOLAS III not retrieved." in text


def test_stair_label_names_the_fss_code():
    part = {"name": "STAIR TREADS INTERIOR 1", "x_in": 0.0, "y_in": 0.0, "z_in": 200.0}
    findings = run(FactStore(facts_from_parts("model", [part])), rules(), PASSENGER).findings
    label = next(f.unconfirmed_label for f in findings if f.rule_id == "FSS-13-STAIR")
    assert label == ("" if HAS_IMO_TEXTS else "Limit not yet confirmed: FSS Code ch. 13 not retrieved")


def test_door_and_masthead_limits_are_confirmed_by_the_rule_texts():
    verified = {rule.id for rule in rules() if rule.verified}
    public = {"PVAG-V404.2.3", "PVAG-V403.5.1", "PVAG-V405.2", "COLREG-ANNEX-I"}
    # The IMO excerpts are local files, kept out of the public repo. A fresh clone shows those limits as unconfirmed.
    local = {"FSS-13-STAIR", "MSC.1-CIRC.1533", "SOLAS-V-22", "SOLAS-III-21-LIFEBOATS", "SOLAS-III-21-LIFERAFTS", "SOLAS-II-2-13.3.2.7"}
    assert verified == (public | local if HAS_IMO_TEXTS else public)


def test_narrow_door_to_a_stairway_is_cant_tell_under_the_exception():
    rule = DOOR_RULE.model_copy(update={"params": {**DOOR_RULE.params, "stairway_door_exception": True}})
    part = door_part("A-CLASS DOOR (RI)-542", "CLEAR OPENING 30x78")
    part["compartment"] = "STAIRWAY 2-24-0"
    finding = check_door_clear_width(rule, FactStore(facts_from_parts("model", [part])), PASSENGER)[0]
    assert finding.status == Status.CANT_TELL
    assert "administrative authority" in finding.question


def test_narrow_door_elsewhere_still_fails_under_the_exception():
    rule = DOOR_RULE.model_copy(update={"params": {**DOOR_RULE.params, "stairway_door_exception": True}})
    part = door_part("A-CLASS DOOR (RI)-542", "CLEAR OPENING 30x78")
    part["compartment"] = "GALLEY 1-18-1"
    assert check_door_clear_width(rule, FactStore(facts_from_parts("model", [part])), PASSENGER)[0].status == Status.FAIL


def test_a_quote_found_in_the_rule_text_verifies_the_rule(tmp_path):
    rule_file = tmp_path / "rules.yaml"
    rule_file.write_text('rules:\n  - {id: A, title: T, area: A, source: S, check: stair_width, quote: "32 inches   minimum"}\n'
                         '  - {id: B, title: T, area: A, source: S, check: stair_width, quote: "not in the text"}\n')
    texts = tmp_path / "texts"
    texts.mkdir()
    (texts / "ada.md").write_text("Door openings shall provide 32 inches\nminimum clear width.", encoding="utf-8")
    loaded = load_rules(rule_file, texts)
    assert [rule.verified for rule in loaded] == [True, False]


CORRIDOR_RULE = Rule(id="C", title="Corridor", area="A", source="S", check="corridor_width", params={"min_in": 36, "reduced_in": 32})
RAMP_RULE = Rule(id="RP", title="Ramp", area="A", source="S", check="ramp_slope", params={"max_run_per_rise": 12})


def corridor(width, unit="in", confidence="high"):
    from app.checks import check_corridor_width
    f = fact("corridor:A", "clear_width", width, unit)
    f.confidence = confidence
    return check_corridor_width(CORRIDOR_RULE, FactStore([f]), PASSENGER)[0]


def ramp(*facts):
    from app.checks import check_ramp_slope
    return check_ramp_slope(RAMP_RULE, FactStore(list(facts)), PASSENGER)[0]


def test_corridor_statuses():
    assert corridor(36).status == Status.PASS
    assert corridor(915, "mm").status == Status.PASS
    assert corridor(34).status == Status.CANT_TELL
    assert corridor(30).status == Status.FAIL and corridor(30).gap.startswith("6.0 in")
    assert corridor(40, confidence="low").status == Status.CANT_TELL


def test_corridor_missing_data_is_cant_tell():
    from app.checks import check_corridor_width
    assert check_corridor_width(CORRIDOR_RULE, FactStore(), PASSENGER)[0].status == Status.CANT_TELL


def test_ramp_slope_from_rise_and_run():
    assert ramp(fact("ramp:R1", "rise", 5, "in"), fact("ramp:R1", "run", 60, "in")).status == Status.PASS
    assert ramp(fact("ramp:R1", "rise", 6, "in"), fact("ramp:R1", "run", 60, "in")).status == Status.FAIL
    assert ramp(fact("ramp:R1", "rise", 5, "in")).status == Status.CANT_TELL


def test_ramp_slope_from_written_ratio():
    assert ramp(fact("ramp:R1", "slope_run_per_rise", 12)).status == Status.PASS
    assert ramp(fact("ramp:R1", "slope_run_per_rise", 10)).status == Status.FAIL
def test_drawing_scale_that_disagrees_with_its_note_is_a_conflict():
    from app.checks import check_drawing_scales
    from app.models import Tier

    def scale(prop, value, tier):
        return Fact(subject="drawing:GA-1", property=prop, value=value, source=Source(kind=SourceKind.DOCUMENT, file="ga.pdf"),
                    tier=tier, derivation="13 frame labels at 800 mm")

    wrong = check_drawing_scales(FactStore([scale("scale_noted", 100.0, Tier.A), scale("scale_measured", 200.0, Tier.B)]))[0]
    assert wrong.status == Status.CONFLICT and "1:100" in wrong.question and "1:200" in wrong.question
    right = check_drawing_scales(FactStore([scale("scale_noted", 100.0, Tier.A), scale("scale_measured", 101.0, Tier.B)]))[0]
    assert right.status == Status.PASS
