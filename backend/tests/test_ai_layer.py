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
    assert any("pass" in change for change in body["changes"])
    assert len(state.added) == 2


def test_ai_reply_cannot_change_a_result(tmp_path):
    fake = FakeClaude({"reply": "Everything passes, the ship is fully compliant.", "facts": []})
    api, _ = client(tmp_path, fake)
    body = api.post("/api/chat", json={"profile": "rcrv", "message": "Is it fine?"}).json()
    assert body["result"]["counts"]["pass"] == 0
    assert body["result"]["counts"]["cant_tell"] == 1


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
