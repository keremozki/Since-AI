"""Where the two builds meet: the drawing reader under the trust rule, both gates, one review flow, and scope."""
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.engine import run
from app.main import AppState, create_app
from app.models import Fact, Rule, Source, SourceKind, Status, Tier
from app.profiles import PROFILES
from app.reading.code_reader import extra_facts, grade
from app.store import FactStore

ROOT = Path(__file__).resolve().parents[2]
P = "passenger-test"


def read_value(value=34.0, unit="in", raw='34"', **meta):
    return Fact(subject="door-number:7", property="clear_width", value=value, unit=unit,
                source=Source(kind=SourceKind.DOCUMENT, file="plan.pdf", locator="page 1, door label at (10, 10) pt", quote=f"D7 | CL OPG {raw}"),
                meta={"reader": "vector", "box": [10, 10, 60, 20], "raw": raw, **meta})


def ocr_says(text, confidence=0.99):
    return lambda _data, _page, _box: {"method": "ocr", "text": text, "confidence": confidence}


@pytest.mark.parametrize("text, confidence, tier", [
    ('CL OPG 34"', 0.99, Tier.B),
    ("CL OPG 34'", 0.99, Tier.B),  # OCR is poor on marks, so the digits decide
    ('CL OPG 84"', 0.99, Tier.D),  # a clear disagreement
    ('CL 0PG 8', 0.40, Tier.C),  # too poor to compare
    ("CL OPG", 0.99, Tier.C),  # no number seen
    ('D734"', 0.99, Tier.C),  # the label and value ran together
])
def test_second_reading_sets_the_tier(text, confidence, tier):
    assert grade(read_value(), b"", ocr_says(text, confidence)).tier == tier


def test_a_reading_can_never_reach_tier_b_when_its_pairing_is_ambiguous():
    assert grade(read_value(ambiguous_pairing=True), b"", ocr_says('CL OPG 34"')).tier == Tier.C


def test_a_page_whose_text_is_itself_ocr_has_only_one_reading():
    assert grade(read_value(ocr_text=True), b"", ocr_says('CL OPG 34"')).tier == Tier.C


def test_second_reading_keeps_both_readings_as_evidence():
    graded = grade(read_value(), b"", ocr_says('CL OPG 34"'))
    assert [r.method for r in graded.evidence.readings] == ["text_layer", "ocr"]
    assert graded.evidence.box is not None and graded.evidence.page == 1


def test_drawing_reader_adds_nothing_the_pipeline_already_read(monkeypatch):
    from app import drawing
    from app.reading import code_reader

    same, other = read_value(), read_value(value=40.0, raw='40"')
    monkeypatch.setattr(drawing, "read_pdf", lambda *_a: drawing.ReadResult(facts=[same]))
    assert code_reader.extra_facts("plan.pdf", b"", None, [same], ocr_says('34"')) == []
    monkeypatch.setattr(drawing, "read_pdf", lambda *_a: drawing.ReadResult(facts=[other]))
    assert len(code_reader.extra_facts("plan.pdf", b"", None, [same], ocr_says('40"'))) == 1  # a difference stays, as a conflict


DOOR = Rule(id="D", title="Door", area="A", source="S", check="door_clear_width", params={"min_in": 32, "min_mm": 815})


def test_tier_gate_holds_a_drawing_door_that_would_fail_and_says_so():
    weak = read_value(value=30.0, raw='30"')
    finding = run(FactStore([weak]), [DOOR], PROFILES[P]).findings[0]
    assert finding.status == Status.CANT_TELL and finding.gate.startswith("Would fail") and finding.reviewable


@pytest.mark.parametrize("tier, status", [(Tier.A, Status.FAIL), (Tier.B, Status.FAIL), (Tier.C, Status.CANT_TELL), (Tier.D, Status.CANT_TELL)])
def test_only_a_or_b_readings_back_a_fail(tier, status):
    fact = read_value(value=30.0, raw='30"').model_copy(update={"tier": tier})
    assert run(FactStore([fact]), [DOOR], PROFILES[P]).findings[0].status == status


@pytest.fixture
def app_state(tmp_path):
    data = tmp_path / "data"
    data.mkdir()
    state = AppState(data, ROOT / "rules" / "rules.yaml", ROOT / "docs" / "rules", claude=object())
    return state, TestClient(create_app(state))


def door_result(body):
    return next(f for f in body["result"]["findings"] if f["subject"] == "door-number:7" and f["rule_id"] == "PVAG-V404.2.3")


def answer(client, decision, **extra):
    response = client.post("/api/feedback", json={"profile": P, "rule_id": "PVAG-V404.2.3", "subject": "door-number:7",
                                                  "decision": decision, "reviewer": "Eric", **extra})
    assert response.status_code == 200, response.text
    return response.json()


def test_read_correctly_confirms_a_held_fail_trains_the_model_and_undo_restores_it(app_state):
    state, client = app_state
    state.add_facts([read_value(value=30.0, raw='30"')])
    assert door_result(client.get(f"/api/run/{P}").json())["status"] == "cant_tell"
    body = answer(client, "accept")
    door = door_result(body)
    assert door["status"] == "fail" and door["answer"] == "accept" and door["inputs"][0]["tier"] == "A"
    assert client.get("/api/confidence").json()["labels_used"] == 1
    undone = client.delete("/api/feedback", params={"profile": P, "key": door["answer_key"]}).json()
    assert door_result(undone)["status"] == "cant_tell" and door_result(undone)["answer"] == ""
    assert state.added[0].confirmed_by == ""


def test_read_correctly_on_a_held_pass_confirms_it_but_never_trains_the_model(app_state):
    state, client = app_state
    state.add_facts([read_value()])
    assert door_result(client.get(f"/api/run/{P}").json())["gate"].startswith("Would pass")
    door = door_result(answer(client, "accept"))
    assert door["status"] == "pass" and door["answer"] == "accept"
    status = client.get("/api/confidence").json()
    assert status["labels_used"] == 0 and status["labels_unsure"] == 0 and status["recent"][0]["decision"] == "accept"


def test_misread_with_a_value_corrects_a_held_pass_and_undo_removes_the_correction(app_state):
    state, client = app_state
    state.add_facts([read_value()])
    door = door_result(answer(client, "reject", corrected_value=30, corrected_unit="in"))
    assert door["status"] == "fail" and door["inputs"][0]["tier"] == "A"
    key = client.get("/api/confidence").json()["recent"][0]["key"]
    assert door_result(client.delete("/api/feedback", params={"profile": P, "key": key}).json())["status"] == "cant_tell"


def test_answering_a_fail_twice_replaces_the_first_answer(app_state):
    state, client = app_state
    state.add_facts([read_value(value=30.0, raw='30"')])
    answer(client, "accept")
    assert state.added[0].confirmed_by == "Eric"
    answer(client, "unsure")
    assert state.added[0].confirmed_by == "" and len(client.get("/api/confidence").json()["recent"]) == 1


def test_a_settled_pass_needs_undo_before_it_can_be_answered_again(app_state):
    state, client = app_state
    state.add_facts([read_value()])
    answer(client, "accept")
    response = client.post("/api/feedback", json={"profile": P, "rule_id": "PVAG-V404.2.3", "subject": "door-number:7", "decision": "reject"})
    assert response.status_code == 409 and "Undo" in response.json()["detail"]


@pytest.mark.parametrize("a, b, value, ok", [
    ({"x": 0, "y": 0, "z": 0}, {"x": 30, "y": 40, "z": 120}, 130, True),  # straight
    ({"x": 0, "y": 0, "z": 0}, {"x": 30, "y": 40, "z": 120}, 120, True),  # vertical only
    ({"x": 0, "y": 0, "z": 0}, {"x": 30, "y": 40, "z": 120}, 50, True),  # horizontal only
    ({"x": 0, "y": 0, "z": 0}, {"x": 30, "y": 40, "z": 120}, 80, False),  # none of them
])
def test_a_measurement_must_be_a_distance_between_the_picked_points(app_state, a, b, value, ok):
    state, client = app_state
    state.active_model = "parts.json"
    response = client.post("/api/measure", params={"profile": P}, json={"subject": "door-number:7", "property": "clear_width",
                                                                         "value": value, "unit": "in", "a": a, "b": b})
    assert (response.status_code == 200) == ok


@pytest.mark.parametrize("rule_id", ["PVAG-V403.5.1", "PVAG-V405.2"])
def test_the_ship_card_decides_corridors_and_ramps_like_doors(app_state, rule_id):
    state, client = app_state
    state.confirm_card("ship_type", "passenger", "", "Eric")
    state.confirm_card("passengers", 3000, "", "Eric")
    decision = next(d for d in client.get("/api/run/card").json()["result"]["scope"] if d["rule_id"] == rule_id)
    assert decision["status"] == "applies" and "V201.1.1" in decision["clause"]


def test_starting_over_clears_ship_card_answers_so_they_cant_reach_the_next_ship(app_state):
    state, client = app_state
    state.confirm_card("length_overall_m", 299.8, "m", "Eric")
    assert client.get("/api/shipcard").json()["card"]["fields"]["length_overall_m"]["value"] == 299.8
    assert client.post("/api/reset").status_code == 200
    assert "length_overall_m" not in client.get("/api/shipcard").json()["card"]["fields"]
    again = AppState(state.data_dir, ROOT / "rules" / "rules.yaml", ROOT / "docs" / "rules", claude=object())
    assert again.card_confirmed == []  # also after a restart


def test_starting_over_keeps_review_answers_because_they_teach_about_drawings(app_state):
    state, client = app_state
    state.add_facts([read_value(value=30.0, raw='30"')])
    answer(client, "accept")
    client.post("/api/reset")
    assert client.get("/api/confidence").json()["labels_used"] == 1


@pytest.mark.parametrize("subject, label", [
    ("door-number:5110", "Door 5110 clear width"), ("stair:C", "Stair C clear width"), ("ship", "Clear width")])
def test_a_conflict_says_whose_value_it_is(subject, label):
    from app.checks import check_consistency

    def stated(value, file):
        return Fact(subject=subject, property="clear_width", value=value, unit="mm", source=Source(kind=SourceKind.DOCUMENT, file=file))

    assert check_consistency(FactStore([stated(1000.0, "a.pdf"), stated(900.0, "b.pdf")]))[0].label == label


def test_a_scan_code_cant_read_still_falls_back_to_the_whole_page_ai_read(app_state, monkeypatch):
    from app import ingest
    from app.reading import pipeline

    state, client = app_state
    monkeypatch.setattr(pipeline, "read_upload", lambda *a, **k: pipeline.ReadResult(file="scan.png", kind="drawing"))
    fact = Fact(subject="ship", property="length_overall", value=60.0, unit="m", source=Source(kind=SourceKind.IMAGE, file="scan.png"))
    monkeypatch.setattr(ingest, "read_file", lambda *a, **k: ([fact], False, 0))
    response = client.post("/api/upload", data={"profile": P}, files={"file": ("scan.png", b"\x89PNG not checked", "image/png")})
    assert response.status_code == 200 and [f["value"] for f in client.get("/api/facts").json()] == [60.0]
    assert client.get("/api/facts").json()[0]["tier"] == "C"  # one AI reading can't back a verdict


def test_the_synthetic_demo_drawing_reaches_verdicts_through_the_real_ocr():
    data = (ROOT / "data" / "demo_offline_SYNTHETIC" / "SYNTHETIC_demo_2_FAIL.pdf").read_bytes()
    facts = extra_facts("SYNTHETIC_demo_2_FAIL.pdf", data, None, [])
    assert {f.tier for f in facts if not isinstance(f.value, str)} == {Tier.B}
