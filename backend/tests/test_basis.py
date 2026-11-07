"""Ship card and design basis: which rules apply by type, size, persons and dates, and what each requires.

The product rule behind every test: a missing input is "can't tell" with a question, never an assumed answer.
"""
import json
from datetime import date

import pytest

from app.basis.conditions import ConditionError, evaluate
from app.basis.design_basis import compute_basis, load_entries, missing_inputs, requirement_for
from app.basis.shipcard import ShipCard, confirm, constructed_date, propose_card
from app.basis.whatif import amendments_for, compare, load_amendments
from app.models import Fact, ShipProfile, Source, SourceKind, Tier


def card(**values) -> ShipCard:
    """A card of confirmed values. Keys ending in _m are meters."""
    result = ShipCard()
    for key, value in values.items():
        result = confirm(result, key, value, "m" if key.endswith("_m") else "", "test")
    return result


CRUISE = dict(ship_type="passenger", passengers=3300, crew=1450, persons_on_board=4750, length_overall_m=299.80,
              breadth_greatest_m=37.40, main_vertical_zones=7, keel_date="2027-02-15", contract_date="2025-03-01",
              voyage="international")
RCRV = dict(ship_type="special_purpose", length_overall_m=60.81, persons_on_board=29, flag="US", voyage="international")


def basis(ship: ShipCard, *rule_ids: str):
    return {item.rule_id: item for item in compute_basis(ship, list(rule_ids) or None)}


def fact(prop, value, unit="", **kw):
    return Fact(subject="ship", property=prop, value=value, unit=unit, source=Source(kind=SourceKind.DOCUMENT, file="spec.pdf"), **kw)


# ---- the evaluator ------------------------------------------------------------------------------------------------

TRUE = {"field": "passengers", "op": ">", "value": 36}
FALSE = {"field": "crew", "op": ">", "value": 1000}
UNKNOWN = {"field": "gross_tonnage", "op": ">=", "value": 500, "ask": "What is the gross tonnage?"}


@pytest.mark.parametrize("conditions, expected", [
    ([TRUE, TRUE], "applies"),
    ([TRUE, UNKNOWN], "cant_tell"),
    ([FALSE, UNKNOWN], "not_applicable"),  # one definite false settles an all_of even with an unknown beside it
    ({"any_of": [TRUE, UNKNOWN]}, "applies"),  # one definite true settles an any_of
    ({"any_of": [FALSE, UNKNOWN]}, "cant_tell"),
    ({"any_of": [FALSE, FALSE]}, "not_applicable"),
    ({"all_of": [TRUE, {"any_of": [FALSE, UNKNOWN]}]}, "cant_tell"),
    ({"all_of": [TRUE, {"any_of": [TRUE, UNKNOWN]}]}, "applies"),
    ({"all_of": [TRUE, {"any_of": [FALSE, FALSE]}]}, "not_applicable"),
    ([], "applies"),
])
def test_three_valued_logic(conditions, expected):
    assert evaluate(conditions, card(passengers=100, crew=10)).status == expected


def test_unknown_gives_the_question_and_the_field():
    decision = evaluate([TRUE, UNKNOWN], card(passengers=100))
    assert decision.missing == ["gross_tonnage"]
    assert decision.questions == ["What is the gross tonnage?"]


def test_definite_false_cites_the_clause_and_names_the_failed_condition():
    condition = {"field": "length_overall_m", "op": ">=", "value": 55, "clause": "SOLAS V/2.4, V/22.1"}
    decision = evaluate([condition], card(length_overall_m=40))
    assert decision.status == "not_applicable"
    assert decision.reasons == ["SOLAS V/2.4, V/22.1: length overall is 40 m, but it must be at least 55 m."]
    assert decision.failed["clause"] == "SOLAS V/2.4, V/22.1" and decision.failed["have"] == 40.0


@pytest.mark.parametrize("condition, expected", [
    ({"field": "passengers", "op": "==", "value": 100}, "applies"),
    ({"field": "passengers", "op": "!=", "value": 100}, "not_applicable"),
    ({"field": "passengers", "op": "<", "value": 100}, "not_applicable"),
    ({"field": "passengers", "op": "<=", "value": 100}, "applies"),
    ({"field": "passengers", "op": ">", "value": 99}, "applies"),
    ({"field": "passengers", "op": ">=", "value": 101}, "not_applicable"),
    ({"field": "ship_type", "op": "in", "value": ["cargo", "passenger"]}, "applies"),
    ({"field": "ship_type", "op": "not_in", "value": ["cargo", "passenger"]}, "not_applicable"),
    ({"field": "ship_type", "op": "exists"}, "applies"),
    ({"field": "flag", "op": "exists"}, "cant_tell"),  # a missing input is never "false"
    ({"field": "keel_date", "op": "on_or_after", "value": "2020-01-01"}, "applies"),
    ({"field": "keel_date", "op": "before", "value": "2020-01-01"}, "not_applicable"),
    ({"field": "keel_date", "op": "before", "value": "2020-01-02"}, "applies"),
    ({"field": "constructed", "op": "on_or_after", "value": "2020-01-01"}, "applies"),  # "constructed" is the keel date
    ({"field": "contract_date", "op": "before", "value": "2030-01-01"}, "cant_tell"),
])
def test_every_operator(condition, expected):
    ship = card(passengers=100, ship_type="passenger", keel_date="2020-01-01")
    assert evaluate([condition], ship).status == expected


@pytest.mark.parametrize("bad", [
    {"field": "passengers", "op": "approximately", "value": 3},
    {"field": "passengers", "op": ">"},
    {"op": ">", "value": 3},
    {"field": "keel_date", "op": "on_or_after", "value": "1 Jan 2020"},
    {"field": "ship_type", "op": "in", "value": "passenger"},
])
def test_bad_condition_data_fails_loudly(bad):
    with pytest.raises(ConditionError):
        evaluate([bad], card(passengers=1))


def test_manual_condition_is_always_cant_tell():
    decision = evaluate([{"manual": "Which regime applies?", "needs": "regime"}], card(passengers=1), why="It matters.")
    assert (decision.status, decision.missing, decision.questions) == ("cant_tell", ["regime"], ["Which regime applies? It matters."])


# ---- the ship card ------------------------------------------------------------------------------------------------

def test_missing_keel_date_is_cant_tell_with_the_right_question():
    item = basis(card(ship_type="passenger", passengers=3300), "SOLAS-II-2-13.3.2.7")["SOLAS-II-2-13.3.2.7"]
    assert item.status == "cant_tell" and item.required_value is None
    assert item.missing == ["keel_date"]
    assert item.questions == ["What is the keel-laying date? SOLAS II-2/13.3.2.7 requires an evacuation analysis for "
                              "passenger ships constructed on or after 1 January 2020."]


def test_constructed_is_the_keel_date_not_the_contract_date():
    ship = card(keel_date="2027-02-15", contract_date="2025-03-01", delivery_date="2029-06-01")
    assert constructed_date(ship) == date(2027, 2, 15)
    assert constructed_date(card(contract_date="2025-03-01")) is None


def test_propose_card_converts_lengths_and_keeps_source_and_tier():
    facts = [fact("length_overall", 299800.0, "mm", tier=Tier.A), fact("passengers", 3300.0, tier=Tier.B),
             fact("keel_date", "15 Feb 2027", tier=Tier.A)]
    proposed = propose_card(facts)
    loa = proposed.field("length_overall_m")
    assert loa.value == pytest.approx(299.8) and loa.unit == "m" and loa.tier == "A" and loa.source == "Document: spec.pdf"
    assert proposed.field("passengers").tier == "B"
    assert proposed.get("keel_date") == date(2027, 2, 15)


def test_persons_on_board_is_a_suggestion_never_a_value():
    proposed = propose_card([fact("passengers", 3300.0, tier=Tier.A), fact("crew_complement", 1450.0, tier=Tier.A)])
    assert proposed.get("persons_on_board") is None
    suggestion = next(s for s in proposed.suggestions if s.field == "persons_on_board")
    assert suggestion.candidate == 4750.0 and "confirm" in suggestion.text
    confirmed = confirm(proposed, "persons_on_board", 4750, by="J. Smith")
    assert confirmed.get("persons_on_board") == 4750.0
    assert not any(s.field == "persons_on_board" for s in confirmed.suggestions)
    assert proposed.get("persons_on_board") is None  # confirm returns a new card


def test_stated_persons_on_board_needs_no_suggestion():
    proposed = propose_card([fact("persons_on_board", 4750.0, tier=Tier.A), fact("crew_complement", 1450.0, tier=Tier.A)])
    assert proposed.get("persons_on_board") == 4750.0 and proposed.suggestions == []


def test_profile_supplies_only_what_it_states():
    profile = ShipProfile(id="p", name="P", ship_type="passenger", passengers=400, flag="US")
    proposed = propose_card([], profile)
    assert {k: (f.value, f.source) for k, f in proposed.fields.items()} == {
        "ship_type": ("passenger", "ship profile"), "passengers": (400.0, "ship profile"), "flag": ("US", "ship profile")}


def test_profile_ship_type_outside_the_solas_types_is_not_guessed():
    profile = ShipProfile(id="r", name="R", ship_type="research", passengers=0, flag="US")
    proposed = propose_card([], profile)
    assert proposed.get("ship_type") is None and proposed.get("passengers") == 0.0
    assert any(s.field == "ship_type" and "research" in s.text for s in proposed.suggestions)


def test_disagreeing_sources_leave_the_field_empty_until_a_person_picks():
    proposed = propose_card([fact("length_overall", 299.8, "m", tier=Tier.A), fact("length_overall", 301.2, "m", tier=Tier.A)])
    assert proposed.get("length_overall_m") is None
    assert proposed.field("length_overall_m").tier == "D" and "disagree" in proposed.field("length_overall_m").note
    # A weaker reading that disagrees still leaves the field empty: one of the two is wrong, and the field decides
    # which rules apply (an LOA of 50 m against 299.8 m would switch SOLAS V/22 off). A person picks.
    mixed = propose_card([fact("length_overall", 299.8, "m", tier=Tier.A), fact("length_overall", 301.2, "m", tier=Tier.C)])
    assert mixed.get("length_overall_m") is None and "301.2" in mixed.field("length_overall_m").note


def test_implausible_unit_is_unusable_not_converted_silently():
    proposed = propose_card([fact("length_overall", 299.8, "mm", tier=Tier.A)])  # 0.2998 m
    assert proposed.get("length_overall_m") is None and "plausible range" in proposed.field("length_overall_m").note


def test_a_fact_with_no_tier_is_one_reading_until_confirmed():
    proposed = propose_card([fact("length_overall", 299.8, "m")])
    assert proposed.field("length_overall_m").tier == "C"
    stated = propose_card([Fact(subject="ship", property="length_overall", value=299.8, unit="m", source=Source(kind=SourceKind.CHAT))])
    assert stated.field("length_overall_m").tier == "A"


def test_superseded_fact_is_ignored():
    assert propose_card([fact("passengers", 100.0, tier=Tier.A, superseded_by="rev B")]).get("passengers") is None


def test_confirm_makes_tier_a_and_converts_units():
    updated = confirm(ShipCard(), "length_overall_m", 984, "ft", "J. Smith")
    item = updated.field("length_overall_m")
    assert item.value == pytest.approx(299.9232) and (item.tier, item.confirmed, item.confirmed_by) == ("A", True, "J. Smith")
    with pytest.raises(ValueError):
        confirm(ShipCard(), "ship_type", "yacht", by="x")
    with pytest.raises(ValueError):
        confirm(ShipCard(), "passengers", 5, by="")
    with pytest.raises(ValueError):
        confirm(ShipCard(), "wingspan", 5, by="x")
    with pytest.raises(ValueError):
        confirm(ShipCard(), "keel_date", "someday", by="x")


def test_card_round_trips_through_json_with_dates():
    ship = card(**CRUISE)
    again = ShipCard.model_validate_json(ship.model_dump_json())
    assert again.get("keel_date") == date(2027, 2, 15) and again.get("persons_on_board") == 4750.0


# ---- the synthetic cruise ship ------------------------------------------------------------------------------------

def test_cruise_ship_design_basis():
    items = basis(card(**CRUISE))
    v22 = items["SOLAS-V-22"]
    assert v22.status == "applies" and v22.required_value == 500.0  # 2 x 299.8 = 599.6, so 500 m governs
    assert "599.6" in v22.required and "500 m governs" in v22.required
    assert items["SOLAS-II-2-13.3.2.7"].status == "applies"
    pvag = items["PVAG-V404.2.3"]
    assert pvag.status == "applies" and "PROPOSED" in pvag.status_note and "not in force" in pvag.status_note
    assert items["SOLAS-III-21-LIFEBOATS"].required_value == 2375.0 and items["SOLAS-III-21-LIFEBOATS"].per_side is True
    assert items["SOLAS-III-21-LIFERAFTS"].required_value == 1187.5 and items["SOLAS-III-21-LIFERAFTS"].per_side is False
    assert items["SOLAS-III-RAFTS"].required_value == 1187.5
    evac = items["MSC.1-CIRC.1533"]
    assert evac.status == "applies" and evac.required_value == 80.0 and evac.unit == "min"
    assert items["SPS-CODE-8.2"].status == "not_applicable"
    assert items["FSS-13-STAIR"].status == "applies" and items["FSS-13-STAIR"].required_value is None  # per stair
    assert items["FSS-13-STAIR"].bounds == (900.0, None) and items["FSS-13-STAIR"].per_item


def test_every_item_cites_its_clause_and_edition():
    for item in compute_basis(card(**CRUISE)):
        assert item.clause and item.edition, item.rule_id


def test_inputs_show_the_card_fields_used():
    lifeboats = basis(card(**CRUISE), "SOLAS-III-21-LIFEBOATS")["SOLAS-III-21-LIFEBOATS"]
    used = {row["field"]: row for row in lifeboats.inputs}
    assert {"ship_type", "voyage", "persons_on_board"} <= set(used)
    assert used["persons_on_board"]["tier"] == "A" and used["persons_on_board"]["confirmed"] is True


def test_evacuation_limit_follows_ship_type_and_zone_count():
    def limit(**kw):
        return basis(card(**{**CRUISE, **kw}), "MSC.1-CIRC.1533")["MSC.1-CIRC.1533"]

    assert limit(main_vertical_zones=3).required_value == 60.0  # more than three is the line
    assert limit(main_vertical_zones=4).required_value == 80.0
    assert limit(ship_type="ro_ro_passenger", main_vertical_zones=7).required_value == 60.0  # n = 60 for ro-ro, any zones
    unknown_zones = {k: v for k, v in CRUISE.items() if k != "main_vertical_zones"}
    item = basis(card(**unknown_zones), "MSC.1-CIRC.1533")["MSC.1-CIRC.1533"]
    assert item.status == "cant_tell" and item.required_value is None and item.bounds == (60.0, 80.0)
    assert item.missing == ["main_vertical_zones"]


def test_evacuation_analysis_dates_and_passenger_threshold():
    def status(**kw):
        return basis(card(**{**CRUISE, **kw}), "SOLAS-II-2-13.3.2.7")["SOLAS-II-2-13.3.2.7"].status

    assert status(keel_date="2019-12-31") == "not_applicable"
    assert status(keel_date="2020-01-01") == "applies"
    assert status(passengers=36) == "not_applicable"  # more than 36 passengers, and persons on board don't count
    assert status(passengers=37) == "applies"
    assert status(ship_type="ro_ro_passenger", keel_date="1999-07-01") == "applies"
    assert status(ship_type="ro_ro_passenger", keel_date="1999-06-30") == "not_applicable"
    assert status(ship_type="cargo") == "not_applicable"


def test_pvag_scope_counts_passengers_or_overnight_passengers():
    small = {**CRUISE, "passengers": 120}
    item = basis(card(**small), "PVAG-V404.2.3")["PVAG-V404.2.3"]
    assert item.status == "cant_tell" and item.missing == ["overnight_passengers"]
    assert basis(card(**small, overnight_passengers=10), "PVAG-V404.2.3")["PVAG-V404.2.3"].status == "not_applicable"
    assert basis(card(**small, overnight_passengers=50), "PVAG-V404.2.3")["PVAG-V404.2.3"].status == "applies"


def test_ada_is_a_benchmark_until_the_compliance_basis_names_it():
    item = basis(card(**CRUISE), "ADA-404.2.3")["ADA-404.2.3"]
    assert item.status == "cant_tell" and item.missing == ["ada_2010_named"] and item.required_value is None
    named = basis(card(**CRUISE, ada_2010_named="yes"), "ADA-404.2.3")["ADA-404.2.3"]
    assert named.status == "applies" and named.bounds == (815.0, 915.0)


# ---- the research vessel and the what-if --------------------------------------------------------------------------

def test_rcrv_without_keel_date_cant_tell_on_v22_and_asks_for_it():
    items = basis(card(**RCRV))
    v22 = items["SOLAS-V-22"]
    assert v22.status == "cant_tell" and v22.required_value is None
    assert v22.missing == ["keel_date"] and v22.questions[0].startswith("What is the keel-laying date?")
    assert "if it applies" in v22.required.lower()
    assert items["SPS-CODE-8.2"].status == "not_applicable"  # 29 persons: cargo-ship lifesaving rules (SPS Code 8.4)
    assert items["SOLAS-III-21-LIFEBOATS"].status == "not_applicable"
    assert items["PVAG-V404.2.3"].status == "not_applicable"
    assert {row["field"] for row in missing_inputs(list(items.values()))} >= {"keel_date", "special_personnel", "gross_tonnage"}


def test_v22_does_not_apply_below_55_m_or_before_july_1998():
    assert basis(card(**{**RCRV, "length_overall_m": 54.9, "keel_date": "2021-01-01"}), "SOLAS-V-22")["SOLAS-V-22"].status == "not_applicable"
    assert basis(card(**{**RCRV, "keel_date": "1998-06-30"}), "SOLAS-V-22")["SOLAS-V-22"].status == "not_applicable"
    item = basis(card(**{**RCRV, "length_overall_m": 40.0, "keel_date": "2021-01-01"}), "SOLAS-V-22")["SOLAS-V-22"]
    assert "SOLAS V/2.4, V/22.1" in item.reasons[0]


def test_v22_limit_is_two_ship_lengths_for_a_shorter_ship():
    item = basis(card(**{**RCRV, "length_overall_m": 120.0, "keel_date": "2021-01-01"}), "SOLAS-V-22")["SOLAS-V-22"]
    assert item.required_value == 240.0 and "two ship lengths governs" in item.required


def test_raising_persons_from_29_to_61_switches_to_passenger_ship_lifesaving():
    before = card(**RCRV)
    after = confirm(before, "persons_on_board", 61, by="what-if")
    ids = ["SPS-CODE-8.2", "SOLAS-III-21-LIFEBOATS", "SOLAS-III-21-LIFERAFTS", "SOLAS-III-RAFTS"]
    changes = {c.rule_id: c for c in compare(before, after, ids)}
    assert set(changes) == set(ids)
    sps = changes["SPS-CODE-8.2"]
    assert (sps.from_status, sps.to_status) == ("not_applicable", "applies")
    assert "Persons on board was 29, now 61" in sps.why and "more than 60" in sps.why
    boats = changes["SOLAS-III-21-LIFEBOATS"]
    assert (boats.from_status, boats.to_status) == ("not_applicable", "applies")
    assert "30.5 persons" in boats.to_required
    rafts = changes["SOLAS-III-RAFTS"]
    assert (rafts.from_status, rafts.to_status) == ("applies", "applies")
    assert "29 persons" in rafts.from_required and "100%" in rafts.from_required  # cargo-ship rule at 29 persons
    assert "15.25 persons" in rafts.to_required and "25%" in rafts.to_required  # passenger-ship rule at 61
    assert "changes from" in rafts.why
    assert requirement_for("SOLAS-III-21-LIFEBOATS", after).value == 30.5


def test_special_purpose_at_exactly_60_persons_stays_on_cargo_rules():
    ship = card(**{**RCRV, "persons_on_board": 60})
    assert basis(ship, "SPS-CODE-8.2")["SPS-CODE-8.2"].status == "not_applicable"
    assert basis(ship, "SOLAS-III-RAFTS")["SOLAS-III-RAFTS"].required_value == 60.0


def test_special_purpose_status_needs_special_personnel_and_gross_tonnage():
    item = basis(card(**RCRV, special_personnel=13, gross_tonnage=499), "SPS-CODE-1.3.12")["SPS-CODE-1.3.12"]
    assert item.status == "not_applicable" and "SPS Code Preamble 3" in item.reasons[0]
    assert basis(card(**RCRV, special_personnel=13, gross_tonnage=500), "SPS-CODE-1.3.12")["SPS-CODE-1.3.12"].status == "applies"
    assert basis(card(**RCRV, special_personnel=12, gross_tonnage=900), "SPS-CODE-1.3.12")["SPS-CODE-1.3.12"].status == "not_applicable"


def test_special_purpose_fire_rules_are_not_assumed_between_61_and_240_persons():
    item = basis(card(**{**RCRV, "persons_on_board": 100, "keel_date": "2021-01-01"}), "FSS-13-STAIR")["FSS-13-STAIR"]
    assert item.status == "cant_tell" and "II-2 requirement set for the special purpose ship" in item.missing
    assert basis(card(**RCRV), "FSS-13-STAIR")["FSS-13-STAIR"].status == "not_applicable"


# ---- sister hulls and amendments ----------------------------------------------------------------------------------

def test_sister_hull_with_later_keel_shows_the_2028_amendments():
    hull_a = card(**CRUISE)
    hull_b = confirm(hull_a, "keel_date", "2028-03-01", by="yard")
    changes = {c.rule_id: c for c in compare(hull_a, hull_b)}
    guard_rails = changes["MSC.591(111)"]
    assert guard_rails.kind == "amendment" and (guard_rails.from_status, guard_rails.to_status) == ("not_applicable", "applies")
    assert "Keel-laying date was 15 February 2027" in guard_rails.why
    assert "now 1 March 2028" in guard_rails.why and "In force 2028-01-01" in guard_rails.why
    # Rules that depend only on other inputs don't move with the keel date.
    assert not {"SOLAS-V-22", "SOLAS-III-21-LIFEBOATS", "MSC.1-CIRC.1533"} & set(changes)


def test_sister_hull_with_the_keel_before_2020_loses_the_evacuation_analysis():
    hull_b = confirm(card(**CRUISE), "keel_date", "2019-06-01", by="yard")
    changes = {c.rule_id: c for c in compare(card(**CRUISE), hull_b)}
    assert (changes["SOLAS-II-2-13.3.2.7"].from_status, changes["SOLAS-II-2-13.3.2.7"].to_status) == ("applies", "not_applicable")
    assert (changes["MSC.404(96)"].from_status, changes["MSC.404(96)"].to_status) == ("applies", "not_applicable")


def test_amendments_by_trigger_date():
    by_id = {a["id"]: a for a in amendments_for(card(**CRUISE))}
    assert by_id["MSC.404(96)"]["status"] == "applies"
    assert by_id["MSC.591(111)"]["status"] == "not_applicable"
    assert by_id["MSC.550(108)"]["status"] == "not_applicable"  # not a ro-ro passenger ship
    assert by_id["SOLAS-V-23-PILOT"]["status"] == "cant_tell"  # installation date is per equipment item
    assert by_id["SOLAS-V-23-PILOT"]["questions"][0].startswith("On what date is the pilot transfer arrangement installed?")
    assert by_id["MSC.589(111)"]["status"] == "cant_tell" and by_id["MSC.589(111)"]["trigger_unconfirmed"] is True
    assert by_id["MSC.216(82)-SRTP"]["status"] == "applies"  # seven main vertical zones
    assert by_id["MSC.1/Circ.1350/Rev.1"]["status"] == "applies"  # contracted after 2011, 299.8 m, constructed after 1998
    installed = confirm(card(**CRUISE), "installation_date", "2028-02-01", by="yard")
    assert {a["id"]: a for a in amendments_for(installed)}["SOLAS-V-23-PILOT"]["status"] == "applies"


def test_noise_code_contract_and_delivery_date_trap():
    def status(contract, delivery, keel="2012-05-01", ship_type="passenger"):
        ship = card(ship_type=ship_type, gross_tonnage=100000, contract_date=contract, keel_date=keel, delivery_date=delivery)
        found = {a["id"]: a["status"] for a in amendments_for(ship)}
        return found["MSC.338(91)"], found["MSC.338(91)-TRANSITIONAL"]

    # Contracted in 2012: the full Noise Code or only machinery-space measures, by delivery date alone.
    assert status("2012-03-01", "2019-01-01") == ("applies", "not_applicable")
    assert status("2012-03-01", "2017-01-01") == ("not_applicable", "applies")
    assert status("2012-03-01", "2018-07-01")[0] == "applies" and status("2012-03-01", "2018-06-30")[0] == "not_applicable"
    assert status("2014-07-01", "2016-01-01", keel="2015-06-01")[0] == "applies"
    unknown_delivery = card(gross_tonnage=100000, contract_date="2012-03-01", keel_date="2012-05-01")
    found = {a["id"]: a for a in amendments_for(unknown_delivery)}
    assert found["MSC.338(91)"]["status"] == "cant_tell" and found["MSC.338(91)"]["missing"] == ["delivery_date"]
    assert "delivery date" in found["MSC.338(91)"]["questions"][0].lower()


# ---- required values ----------------------------------------------------------------------------------------------

def test_masthead_uses_greatest_breadth_not_the_moulded_beam():
    base = dict(propulsion="power_driven", length_overall_m=100.0)
    item = basis(card(**base, beam_m=7.0, breadth_greatest_m=10.0), "COLREG-ANNEX-I")["COLREG-ANNEX-I"]
    assert item.status == "applies" and item.required_value == 10.0 and item.inputs[-1]["field"] == "breadth_greatest_m"
    assert requirement_for("COLREG-ANNEX-I", card(beam_m=30.0, breadth_greatest_m=8.0)).value == 8.0
    assert requirement_for("COLREG-ANNEX-I", card(breadth_greatest_m=5.0)).value == 6.0  # never below 6 m
    assert requirement_for("COLREG-ANNEX-I", card(breadth_greatest_m=37.4)).value == 12.0  # never above 12 m


def test_masthead_with_only_the_beam_is_cant_tell_and_says_what_would_pass_anyway():
    item = basis(card(propulsion="power_driven", length_overall_m=100.0, beam_m=30.0), "COLREG-ANNEX-I")["COLREG-ANNEX-I"]
    assert item.status == "cant_tell" and item.applicability == "applies" and item.required_value is None
    assert item.missing == ["breadth_greatest_m"] and "not the moulded beam" in item.questions[0]
    assert item.bounds == (6.0, 12.0)  # the range is known even though the exact height is not
    requirement = requirement_for("COLREG-ANNEX-I", card(beam_m=30.0))
    assert requirement.bounds == (6.0, 12.0) and requirement.value is None
    assert "12 m or more above the hull meets this rule whatever the breadth" in requirement.note
    assert "moulded beam (30 m) is known, and it is not used" in requirement.note


def test_colreg_needs_propulsion_and_length():
    assert "propulsion" in basis(card(length_overall_m=100.0), "COLREG-ANNEX-I")["COLREG-ANNEX-I"].missing
    assert basis(card(propulsion="sailing", length_overall_m=100.0), "COLREG-ANNEX-I")["COLREG-ANNEX-I"].status == "not_applicable"
    assert basis(card(propulsion="power_driven", length_overall_m=19.9), "COLREG-ANNEX-I")["COLREG-ANNEX-I"].status == "not_applicable"


def test_stair_minimum_depends_on_persons_served():
    assert requirement_for("FSS-13-STAIR", card()).value is None and requirement_for("FSS-13-STAIR", card()).bounds == (900.0, None)
    assert requirement_for("FSS-13-STAIR", card(), persons_served=90).value == 900.0
    assert requirement_for("FSS-13-STAIR", card(), persons_served=91).value == 910.0
    assert requirement_for("FSS-13-STAIR", card(), persons_served=250).value == 2500.0
    assert requirement_for("FSS-13-STAIR", card(), persons_served=100.4).value == 1010.0  # each started person counts
    assert "900 mm + 10 mm x (persons served - 90)" in requirement_for("FSS-13-STAIR", card()).formula


def test_door_minimum_depends_on_opening_depth():
    for rule in ("ADA-404.2.3", "PVAG-V404.2.3"):
        assert requirement_for(rule, card(), opening_depth_mm=100).value == 815.0
        assert requirement_for(rule, card(), opening_depth_mm=609.6).value == 815.0  # exactly 24 in is not "more than"
        assert requirement_for(rule, card(), opening_depth_mm=610).value == 915.0  # inches govern: stricter
        assert requirement_for(rule, card(), opening_depth_mm=None).value is None


def test_item_inputs_are_checked():
    with pytest.raises(TypeError):
        requirement_for("SOLAS-V-22", card(**CRUISE), persons_served=5)
    with pytest.raises(KeyError):
        requirement_for("NO-SUCH-RULE", card())


def test_missing_persons_on_board_blocks_the_lifeboat_number_not_the_applicability():
    ship = card(**{k: v for k, v in CRUISE.items() if k != "persons_on_board"})
    item = basis(ship, "SOLAS-III-21-LIFEBOATS")["SOLAS-III-21-LIFEBOATS"]
    assert item.applicability == "applies" and item.status == "cant_tell" and item.required_value is None
    assert item.missing == ["persons_on_board"]


def test_cargo_ship_liferafts_cover_everyone_and_voyage_gaps_are_asked():
    cargo = card(ship_type="cargo", persons_on_board=24)
    assert requirement_for("SOLAS-III-RAFTS", cargo).value == 24.0
    assert basis(cargo, "SOLAS-III-21-LIFEBOATS")["SOLAS-III-21-LIFEBOATS"].status == "not_applicable"
    passenger = card(ship_type="passenger", persons_on_board=100)
    assert requirement_for("SOLAS-III-RAFTS", passenger).missing == ["voyage"]
    short = card(ship_type="passenger", persons_on_board=100, voyage="short_international")
    assert requirement_for("SOLAS-III-RAFTS", short).value is None and requirement_for("SOLAS-III-RAFTS", short).missing
    assert basis(short, "SOLAS-III-21-LIFEBOATS")["SOLAS-III-21-LIFEBOATS"].status == "not_applicable"


# ---- single readings must not switch rules off ---------------------------------------------------------------------

def test_a_single_reading_cannot_switch_a_rule_off():
    one_reading = propose_card([fact("length_overall", 40.0, "m", tier=Tier.C), fact("keel_date", "2021-01-01", tier=Tier.A)])
    item = basis(one_reading, "SOLAS-V-22")["SOLAS-V-22"]
    assert item.status == "cant_tell" and item.missing == ["length_overall_m"]
    assert "Please confirm the length overall" in item.questions[0]
    confirmed = confirm(one_reading, "length_overall_m", 40.0, "m", "J. Smith")
    assert basis(confirmed, "SOLAS-V-22")["SOLAS-V-22"].status == "not_applicable"


def test_a_single_reading_that_keeps_a_rule_on_is_marked_provisional():
    one_reading = propose_card([fact("length_overall", 60.0, "m", tier=Tier.C), fact("keel_date", "2021-01-01", tier=Tier.A)])
    item = basis(one_reading, "SOLAS-V-22")["SOLAS-V-22"]
    assert item.status == "applies" and item.provisional and "single reading" in item.provisional[0]


def test_unusable_value_counts_as_missing_and_keeps_the_note():
    proposed = propose_card([fact("length_overall", 299.8, "mm", tier=Tier.A), fact("keel_date", "2021-01-01", tier=Tier.A)])
    item = basis(proposed, "SOLAS-V-22")["SOLAS-V-22"]
    assert item.status == "cant_tell" and "plausible range" in item.questions[0]


# ---- the data files -----------------------------------------------------------------------------------------------

def test_unknown_rule_is_cant_tell_not_applies():
    item = compute_basis(card(**CRUISE), ["NEW-RULE-1"])[0]
    assert item.status == "cant_tell" and item.questions and item.verified is False


def test_applicability_entries_cover_the_rule_ids_and_load_cleanly():
    entries = load_entries()
    wanted = {"PVAG-V404.2.3", "FSS-13-STAIR", "MSC.1-CIRC.1533", "SOLAS-III-RAFTS", "SOLAS-V-22", "COLREG-ANNEX-I",
              "SOLAS-II-2-13.3.2.7", "SOLAS-III-21-LIFEBOATS", "SOLAS-III-21-LIFERAFTS", "ADA-404.2.3", "SPS-CODE-8.2"}
    assert wanted <= set(entries)
    for entry in entries.values():
        assert entry["clause"] and entry["edition"] and entry["conditions"] and isinstance(entry["verified"], bool), entry["rule_id"]
    assert entries["PVAG-V404.2.3"]["status_note"] and entries["COLREG-ANNEX-I"]["verified"] is True
    # Annex 1 5.1-5.2 is now quoted from the circular itself (docs/rules/imo/msc1-circ1533.md).
    assert entries["MSC.1-CIRC.1533"]["verified"] is True
    assert entries["SOLAS-III-RAFTS"]["verified"] is False  # regulation III/31 isn't in docs/rules yet


def test_amendments_all_have_sources_and_load_cleanly():
    entries = load_amendments()
    assert {"MSC.589(111)", "MSC.404(96)", "SOLAS-V-23-PILOT", "MSC.591(111)", "MSC.338(91)"} <= {e["id"] for e in entries}
    for entry in entries:
        assert entry["source"].startswith("https://") and entry["summary"] and entry["affects"], entry["id"]
        assert isinstance(entry["verified"], bool) and entry["in_force"], entry["id"]
    unconfirmed = [e for e in entries if e.get("trigger_unconfirmed")]
    assert unconfirmed and all(e["verified"] is False for e in unconfirmed)


def test_card_with_nothing_in_it_asks_instead_of_assuming():
    items = compute_basis(ShipCard())
    assert all(item.status == "cant_tell" and item.questions for item in items)
    assert json.loads(items[0].model_dump_json())["rule_id"] == items[0].rule_id
