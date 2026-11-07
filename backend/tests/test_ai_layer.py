"""The AI layer, using a fake model: no test here spends money."""
import json

import pytest
from fastapi.testclient import TestClient

from app import ingest
from app.llm import BudgetExceeded, Claude, Ledger, Usage
from app.main import AppState, create_app
from app.models import Source, SourceKind
from app.vocabulary import to_fact


class FakeClaude:
    def __init__(self, *answers):
        self.answers = list(answers)
        self.calls = 0

    def structured(self, system, content, schema, effort="low", max_tokens=8000):
        self.calls += 1
        return self.answers.pop(0)


def raw(subject, prop, number, unit=""):
    return {"subject": subject, "property": prop, "value_number": number, "value_text": None, "unit": unit,
            "quote": "stated value", "locator": "", "confidence": "high"}


def rules_file(tmp_path):
    path = tmp_path / "rules.yaml"
    path.write_text("rules:\n  - {id: R, title: Rafts, area: L, source: SOLAS III, check: raft_capacity, params: {each_side_fraction: 1.0}}\n")
    return path


def client(tmp_path, fake):
    data = tmp_path / "data"
    data.mkdir()
    parts = [{"name": "LIFERAFT DOUBLE RACK", "x_in": 0.0, "y_in": -10.0, "z_in": 0.0},
             {"name": "LIFERAFT DOUBLE RACK", "x_in": 0.0, "y_in": 10.0, "z_in": 0.0}]
    (data / "parts.json").write_text(json.dumps({"source": "m.nwd", "parts": parts}))
    state = AppState(data, rules_file(tmp_path), tmp_path / "none", claude=fake)
    return TestClient(create_app(state)), state


def test_fact_outside_the_vocabulary_is_dropped():
    template = Source(kind=SourceKind.CHAT)
    assert to_fact(raw("ship", "colour", 1.0), template) is None
    assert to_fact(raw("door-number:abc", "clear_width", 32.0, "in"), template) is None


def test_length_without_a_unit_is_dropped():
    assert to_fact(raw("ship", "beam", 12.5, ""), Source(kind=SourceKind.CHAT)) is None


def test_missing_or_nonpositive_number_is_dropped():
    template = Source(kind=SourceKind.CHAT)
    assert to_fact(raw("liferaft", "capacity_persons", None), template) is None
    assert to_fact(raw("liferaft", "capacity_persons", 0), template) is None


def test_chat_answer_is_recorded_then_tests_rerun(tmp_path):
    fake = FakeClaude({"reply": "Recorded.", "facts": [raw("liferaft", "capacity_persons", 16, ""), raw("ship", "persons_on_board", 29, "")]})
    api, state = client(tmp_path, fake)
    assert api.get("/api/run/rcrv").json()["result"]["counts"]["cant_tell"] == 1
    body = api.post("/api/chat", json={"profile": "rcrv", "message": "Rafts are 16 persons, 29 on board"}).json()
    assert body["result"]["counts"]["pass"] == 2
    assert body["recorded"][0]["source"]["kind"] == "chat"
    assert body["recorded_text"] == ["Liferaft capacity: 16", "Persons on board: 29"]
    assert any("pass" in change for change in body["changes"])
    assert len(state.added) == 2


def test_cant_tell_names_only_the_value_still_missing(tmp_path):
    fake = FakeClaude({"reply": "Recorded.", "facts": [raw("liferaft", "capacity_persons", 16, "persons")]})
    api, _ = client(tmp_path, fake)
    body = api.post("/api/chat", json={"profile": "rcrv", "message": "Rafts are 16 persons"}).json()
    finding = body["result"]["findings"][0]
    assert finding["measured"].endswith("Not stated: persons on board.")
    assert "rated capacity" not in finding["question"]


def test_ai_reply_cannot_change_a_result(tmp_path):
    fake = FakeClaude({"reply": "Everything passes, the ship is fully compliant.", "facts": []})
    api, _ = client(tmp_path, fake)
    body = api.post("/api/chat", json={"profile": "rcrv", "message": "Is it fine?"}).json()
    assert body["result"]["counts"]["pass"] == 0
    assert body["result"]["counts"]["cant_tell"] == 1


def test_passenger_profile_has_no_seeded_faults(tmp_path):
    api, _ = client(tmp_path, FakeClaude())
    plain = api.get("/api/run/passenger").json()["result"]
    seeded = api.get("/api/run/passenger-test").json()["result"]
    assert plain["counts"]["conflict"] == 0
    assert seeded["counts"]["conflict"] == 1
    assert plain["profile"]["ship_type"] == "passenger"


def test_facts_survive_a_restart(tmp_path):
    fake = FakeClaude({"reply": "Recorded.", "facts": [raw("ship", "persons_on_board", 29, "")]})
    api, state = client(tmp_path, fake)
    api.post("/api/chat", json={"profile": "rcrv", "message": "29 on board"})
    reloaded = AppState(state.data_dir, state.rules_file, state.rule_texts_dir, claude=fake)
    assert [f.value for f in reloaded.added] == [29.0]


def test_upload_is_cached_so_a_second_read_is_free(tmp_path):
    fake = FakeClaude({"facts": [raw("liferaft", "capacity_persons", 16, "")]})
    api, state = client(tmp_path, fake)
    for expected_cached in (False, True):
        response = api.post("/api/upload", data={"profile": "rcrv"}, files={"file": ("note.txt", b"Rafts: 16 persons")})
        assert response.status_code == 200
        assert response.json()["cached"] is expected_cached
    assert fake.calls == 1
    assert len(state.added) == 1
    assert state.added[0].source.kind == SourceKind.DOCUMENT


def test_unsupported_upload_is_rejected(tmp_path):
    api, _ = client(tmp_path, FakeClaude())
    response = api.post("/api/upload", data={"profile": "rcrv"}, files={"file": ("model.step", b"x")})
    assert response.status_code == 400


def test_measurement_records_a_fact(tmp_path):
    api, state = client(tmp_path, FakeClaude())
    body = {"subject": "bridge", "property": "eye_to_bow", "value": 24.2, "unit": "m",
            "a": {"x": 0, "y": 0, "z": 0}, "b": {"x": 950, "y": 0, "z": 0}}
    assert api.post("/api/measure", params={"profile": "rcrv"}, json=body).status_code == 200
    assert state.added[0].source.kind == SourceKind.MEASUREMENT


def upload_note(api, name="note.txt"):
    return api.post("/api/upload", data={"profile": "rcrv"}, files={"file": (name, b"Rafts: 16 persons")})


def test_removing_a_file_removes_its_facts_and_reruns(tmp_path):
    api, state = client(tmp_path, FakeClaude({"facts": [raw("liferaft", "capacity_persons", 16, "")]}))
    upload_note(api)
    assert api.get("/api/inputs").json()["files"] == [{"name": "note.txt", "facts": 1}]
    body = api.delete("/api/inputs/files", params={"profile": "rcrv", "name": "note.txt"}).json()
    assert body["inputs"]["files"] == []
    assert state.added == []
    assert body["result"]["counts"]["cant_tell"] == 1


def test_a_file_with_no_facts_is_listed_and_removable(tmp_path):
    api, _ = client(tmp_path, FakeClaude({"facts": []}))
    upload_note(api)
    assert api.get("/api/inputs").json()["files"] == [{"name": "note.txt", "facts": 0}]
    api.delete("/api/inputs/files", params={"profile": "rcrv", "name": "note.txt"})
    assert api.get("/api/inputs").json()["files"] == []


def test_a_removed_file_costs_nothing_to_add_again(tmp_path):
    fake = FakeClaude({"facts": [raw("liferaft", "capacity_persons", 16, "")]})
    api, state = client(tmp_path, fake)
    upload_note(api)
    api.delete("/api/inputs/files", params={"profile": "rcrv", "name": "note.txt"})
    assert upload_note(api).json()["cached"] is True
    assert fake.calls == 1 and len(state.added) == 1


def test_removing_an_unknown_file_is_an_error(tmp_path):
    api, _ = client(tmp_path, FakeClaude())
    assert api.delete("/api/inputs/files", params={"profile": "rcrv", "name": "nope.png"}).status_code == 404


def test_removing_the_model_takes_it_out_completely(tmp_path, monkeypatch):
    api, state = client(tmp_path, FakeClaude())
    parts = [{"name": "LIFERAFT SINGLE RACK", "x_in": 0.0, "y_in": 5.0, "z_in": 0.0}]
    import_model(api, monkeypatch, parts)
    assert list((state.data_dir / "models").glob("*.json"))
    body = api.delete("/api/inputs/model", params={"profile": "rcrv"}).json()
    assert body["inputs"]["model"] == {"name": "", "parts": 0, "has_view": False, "active": False}
    raft = next(f for f in body["result"]["findings"] if f["rule_id"] == "R")
    assert raft["measured"] == "No liferaft racks in the design data"
    assert not list((state.data_dir / "models").glob("*.json"))


def test_there_is_no_restore_after_removing(tmp_path):
    api, _ = client(tmp_path, FakeClaude())
    api.delete("/api/inputs/model", params={"profile": "rcrv"})
    assert api.post("/api/inputs/model/restore", params={"profile": "rcrv"}).status_code in (404, 405)
    assert api.get("/api/inputs").json()["model"]["active"] is False


def test_the_same_model_can_be_uploaded_again_after_removing(tmp_path, monkeypatch):
    api, _ = client(tmp_path, FakeClaude())
    api.delete("/api/inputs/model", params={"profile": "rcrv"})
    parts = [{"name": "LIFERAFT DOUBLE RACK", "x_in": 0.0, "y_in": 10.0, "z_in": 0.0}]
    assert import_model(api, monkeypatch, parts).json()["inputs"]["model"]["parts"] == 1


def test_an_older_save_with_a_restorable_model_cleans_it_up(tmp_path):
    api, state = client(tmp_path, FakeClaude())
    stored = state.data_dir / "models" / "old.json"
    stored.parent.mkdir()
    stored.write_text("{}")
    (state.data_dir / "inputs.json").write_text(json.dumps({
        "active_model": None, "last_model": "models/old.json", "geometry_for": None, "files": []}))
    reloaded = AppState(state.data_dir, state.rules_file, state.rule_texts_dir, claude=FakeClaude())
    assert reloaded.inputs()["model"]["active"] is False
    assert not stored.exists()


def test_removal_survives_a_restart(tmp_path):
    api, state = client(tmp_path, FakeClaude())
    api.delete("/api/inputs/model", params={"profile": "rcrv"})
    reloaded = AppState(state.data_dir, state.rules_file, state.rule_texts_dir, claude=FakeClaude())
    assert reloaded.inputs()["model"]["active"] is False
    assert reloaded.model_facts == []


def test_no_racks_with_known_capacity_is_cant_tell_not_fail(tmp_path):
    fake = FakeClaude({"reply": "Recorded.", "facts": [raw("liferaft", "capacity_persons", 16, ""), raw("ship", "persons_on_board", 29, "")]})
    api, _ = client(tmp_path, fake)
    api.delete("/api/inputs/model", params={"profile": "rcrv"})
    counts = api.post("/api/chat", json={"profile": "rcrv", "message": "16 persons, 29 on board"}).json()["result"]["counts"]
    assert counts["cant_tell"] == 1 and counts["fail"] == 0


def measurement_body():
    return {"subject": "bridge", "property": "eye_to_bow", "value": 24.2, "unit": "m",
            "a": {"x": 0, "y": 0, "z": 0}, "b": {"x": 950, "y": 0, "z": 0}}


def test_measuring_needs_a_model(tmp_path):
    api, _ = client(tmp_path, FakeClaude())
    api.delete("/api/inputs/model", params={"profile": "rcrv"})
    assert api.post("/api/measure", params={"profile": "rcrv"}, json=measurement_body()).status_code == 400


def test_removing_the_model_deletes_its_measurements(tmp_path):
    api, state = client(tmp_path, FakeClaude())
    api.post("/api/measure", params={"profile": "rcrv"}, json=measurement_body())
    api.delete("/api/inputs/model", params={"profile": "rcrv"})
    assert state.inputs()["measurements"] == 0
    assert state.added == []


def test_measurements_and_chat_can_be_removed_as_groups(tmp_path):
    api, state = client(tmp_path, FakeClaude({"reply": "Ok.", "facts": [raw("ship", "persons_on_board", 29, "")]}))
    api.post("/api/measure", params={"profile": "rcrv"}, json=measurement_body())
    api.post("/api/chat", json={"profile": "rcrv", "message": "29 on board"})
    api.delete("/api/inputs/group/measurements", params={"profile": "rcrv"})
    assert [f.source.kind for f in state.added] == [SourceKind.CHAT]
    assert api.delete("/api/inputs/group/chat", params={"profile": "rcrv"}).json()["inputs"]["chat"] == 0


def import_model(api, monkeypatch, parts, name="other.nwd"):
    monkeypatch.setattr("app.nwd.decode_bytes", lambda data: parts)
    return api.post("/api/inputs/model", params={"profile": "rcrv", "name": name}, content=b"data")


def test_importing_a_different_model_replaces_it_and_drops_measurements(tmp_path, monkeypatch):
    api, state = client(tmp_path, FakeClaude())
    api.post("/api/measure", params={"profile": "rcrv"}, json=measurement_body())
    parts = [{"name": "LIFERAFT SINGLE RACK", "x_in": 0.0, "y_in": 5.0, "z_in": 0.0}]
    body = import_model(api, monkeypatch, parts).json()
    assert body["inputs"]["model"]["name"] == "other.nwd" and body["inputs"]["model"]["parts"] == 1
    assert state.added == []


def test_only_the_model_the_geometry_belongs_to_has_a_3d_view(tmp_path, monkeypatch):
    data = tmp_path / "data"
    data.mkdir()
    original = [{"name": "LIFERAFT DOUBLE RACK", "x_in": 0.0, "y_in": 10.0, "z_in": 0.0}]
    (data / "parts.json").write_text(json.dumps({"source": "ship.nwd", "parts": original}))
    (data / "model.bin").write_bytes(b"x")
    (data / "model-meta.json").write_text("{}")
    state = AppState(data, rules_file(tmp_path), tmp_path / "none", claude=FakeClaude())
    api = TestClient(create_app(state))
    assert api.get("/api/inputs").json()["model"]["has_view"] is True
    assert api.get("/model/meta").status_code == 200
    other = import_model(api, monkeypatch, [{"name": "LIFERAFT SINGLE RACK", "x_in": 0.0, "y_in": 5.0, "z_in": 0.0}])
    assert other.json()["inputs"]["model"]["has_view"] is False
    assert api.get("/model/meta").status_code == 404
    same = import_model(api, monkeypatch, original, name="ship.nwd")
    assert same.json()["inputs"]["model"]["has_view"] is True


def test_a_file_with_no_readable_parts_keeps_the_current_model(tmp_path, monkeypatch):
    api, state = client(tmp_path, FakeClaude())
    response = import_model(api, monkeypatch, [])
    assert response.status_code == 400
    assert state.inputs()["model"]["parts"] == 2


def test_only_nwd_files_import_as_3d_models(tmp_path):
    api, _ = client(tmp_path, FakeClaude())
    response = api.post("/api/inputs/model", params={"profile": "rcrv", "name": "model.step"}, content=b"x")
    assert response.status_code == 400 and "nwd" in response.json()["detail"]


def test_scanned_pdf_with_too_many_pages_must_choose_pages():
    import pymupdf
    document = pymupdf.open()
    for _ in range(ingest.MAX_PDF_IMAGE_PAGES + 1):
        document.new_page()
    with pytest.raises(ingest.TooManyPages):
        ingest.build_content("ga.pdf", document.tobytes())
    blocks = ingest.build_content("ga.pdf", document.tobytes(), pages=[2])
    assert [b["type"] for b in blocks] == ["text", "image", "text"]


def test_budget_cap_stops_calls_before_any_spend(tmp_path):
    ledger = Ledger(tmp_path / "usage.json", cap_usd=0.01)
    ledger.record(Usage(input_tokens=10_000, output_tokens=0, cache_read_tokens=0))
    with pytest.raises(BudgetExceeded):
        Claude(ledger, client=object()).structured("s", "c", {})
    assert Ledger(tmp_path / "usage.json", cap_usd=0.01).spent == pytest.approx(0.02)
