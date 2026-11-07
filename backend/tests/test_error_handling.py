"""Bad input and missing configuration give a clear message and the right status, never a crash or a pass."""
from pathlib import Path
from types import SimpleNamespace

import anthropic
import httpx
import pymupdf
import pytest
from fastapi.testclient import TestClient

from app import ingest
from app.engine import run
from app.llm import AIUnavailable, Claude, Ledger, env_float
from app.main import AppState, create_app
from app.models import Fact, Rule, ShipProfile, Source, SourceKind, Status
from app.store import FactStore

ROOT = Path(__file__).resolve().parents[2]
DEMO = ROOT / "data" / "demo_offline_SYNTHETIC"
PROFILE = "passenger-test"


@pytest.fixture
def offline(tmp_path, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("CROSS_CHECK_READERS", raising=False)
    data = tmp_path / "data"
    data.mkdir()
    state = AppState(data, ROOT / "rules" / "rules.yaml", ROOT / "docs" / "rules", claude=Claude(Ledger(data / "u.json", 4.0)))
    return TestClient(create_app(state), raise_server_exceptions=False), state


def upload(api, name, data, pages=""):
    return api.post("/api/upload", data={"profile": PROFILE, "pages": pages}, files={"file": (name, data, "application/pdf")})


def pdf_with(text='D101 CL OPG 30"', pages=1, **save):
    doc = pymupdf.open()
    for _ in range(pages):
        doc.new_page(width=300, height=300).insert_text((40, 40), text)
    return doc.tobytes(**save)


def scanned_pdf():
    doc = pymupdf.open()
    page = doc.new_page()
    pix = pymupdf.Pixmap(pymupdf.csGRAY, pymupdf.IRect(0, 0, 40, 40), False)
    pix.set_rect(pix.irect, (210,))
    page.insert_image(page.rect, pixmap=pix)
    return doc.tobytes()


# ---------- files ----------

@pytest.mark.parametrize("name, data, words", [
    ("broken.pdf", pdf_with()[:200], "damaged"),
    ("garbage.pdf", b"%PDF-1.7\nnot really a pdf", "damaged"),
    ("empty.pdf", b"", "empty (0 bytes)"),
    ("notes.pdf", b"door 101 is 30 inches wide\n" * 20, "renamed text file"),
    ("locked.pdf", pdf_with(encryption=pymupdf.PDF_ENCRYPT_AES_256, user_pw="u", owner_pw="o"), "password-protected"),
    ("plan.docx", b"PK\x03\x04 zip", "Unsupported file type"),
])
def test_bad_files_are_refused_with_a_reason(offline, name, data, words):
    api, state = offline
    response = upload(api, name, data)
    assert response.status_code == 400 and words in response.json()["detail"]
    assert state.added == [] and state.files == []
    assert api.get(f"/api/run/{PROFILE}").status_code == 200  # the app keeps working


def test_too_many_pages_has_a_documented_limit(offline):
    api, _ = offline
    response = upload(api, "set.pdf", pdf_with(pages=ingest.MAX_PDF_PAGES + 1))
    assert response.status_code == 413 and str(ingest.MAX_PDF_PAGES) in response.json()["detail"]
    # Choosing pages gets under the limit.
    assert upload(api, "set.pdf", pdf_with(pages=ingest.MAX_PDF_PAGES + 1), pages="1-3").status_code == 200


def test_too_large_file_is_413(offline, monkeypatch):
    api, _ = offline
    monkeypatch.setattr(ingest, "MAX_UPLOAD_BYTES", 1000)
    response = upload(api, "big.pdf", pdf_with() + b" " * 2000)
    assert response.status_code == 413 and "limit" in response.json()["detail"]


@pytest.mark.parametrize("pages, words", [("abc", "numbers like"), ("5", "Page 5 doesn't exist"), ("3-1", "numbers like")])
def test_bad_page_choice_is_explained(offline, pages, words):
    api, _ = offline
    response = upload(api, "plan.pdf", pdf_with(), pages=pages)
    assert response.status_code == 400 and words in response.json()["detail"]


def test_page_ranges_parse():
    assert ingest.parse_pages("1, 3,5-7") == [1, 3, 5, 6, 7]
    assert ingest.parse_pages("") is None


def test_scanned_pdf_without_key_says_a_key_is_needed(offline):
    api, _ = offline
    response = upload(api, "scan.pdf", scanned_pdf())
    detail = response.json()["detail"]
    assert response.status_code == 503 and "scanned" in detail and "ANTHROPIC_API_KEY" in detail
    # A vector drawing still works in the same session.
    assert upload(api, "demo.pdf", (DEMO / "SYNTHETIC_demo_2_FAIL.pdf").read_bytes()).status_code == 200


def test_image_without_key_says_a_key_is_needed(offline):
    api, _ = offline
    response = api.post("/api/upload", data={"profile": PROFILE}, files={"file": ("plan.png", b"\x89PNG....", "image/png")})
    assert response.status_code == 503 and "ANTHROPIC_API_KEY" in response.json()["detail"]


def test_chat_without_key_is_503_and_checks_keep_working(offline):
    api, _ = offline
    response = api.post("/api/chat", json={"profile": PROFILE, "message": "Door 7 is 30 in"})
    assert response.status_code == 503 and "ANTHROPIC_API_KEY" in response.json()["detail"]
    assert api.get(f"/api/report/{PROFILE}").status_code == 200


# ---------- API key, timeout, rate limit ----------

REQUEST = httpx.Request("POST", "https://api.anthropic.com/v1/messages")


def status_error(cls, code):
    return cls("x", response=httpx.Response(code, request=REQUEST), body=None)


def ok_response(text='{"facts": []}'):
    return SimpleNamespace(usage=SimpleNamespace(input_tokens=1, output_tokens=1, cache_read_input_tokens=0),
                           stop_reason="end_turn", content=[SimpleNamespace(type="text", text=text)])


def claude_with(*outcomes, tmp_path):
    calls = []

    def create(**_request):
        calls.append(1)
        outcome = outcomes[len(calls) - 1]
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    client = SimpleNamespace(beta=SimpleNamespace(messages=SimpleNamespace(create=create)))
    return Claude(Ledger(tmp_path / "u.json", 4.0), client=client, retry_delay=0), calls


@pytest.mark.parametrize("error", [anthropic.APITimeoutError(request=REQUEST), status_error(anthropic.RateLimitError, 429),
                                   status_error(anthropic.InternalServerError, 500)])
def test_one_retry_then_success(tmp_path, error):
    claude, calls = claude_with(error, ok_response(), tmp_path=tmp_path)
    assert claude.structured("s", "c", {}) == {"facts": []} and len(calls) == 2


@pytest.mark.parametrize("error, words", [(anthropic.APITimeoutError(request=REQUEST), "timed out"),
                                          (status_error(anthropic.RateLimitError, 429), "rate limit")])
def test_two_failures_give_a_clear_message(tmp_path, error, words):
    claude, calls = claude_with(error, error, error, tmp_path=tmp_path)
    with pytest.raises(AIUnavailable, match=words):
        claude.structured("s", "c", {})
    assert len(calls) == 2  # exactly one retry


def test_invalid_key_is_not_retried(tmp_path):
    claude, calls = claude_with(status_error(anthropic.AuthenticationError, 401), tmp_path=tmp_path)
    with pytest.raises(AIUnavailable, match="ANTHROPIC_API_KEY"):
        claude.structured("s", "c", {})
    assert len(calls) == 1


def test_missing_key_is_named(tmp_path, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    with pytest.raises(AIUnavailable, match="No API key"):
        Claude(Ledger(tmp_path / "u.json", 4.0)).structured("s", "c", {})


def test_upload_maps_api_trouble_to_503(tmp_path, monkeypatch):
    data = tmp_path / "data"
    data.mkdir()
    timeout = anthropic.APITimeoutError(request=REQUEST)
    claude, _ = claude_with(timeout, timeout, tmp_path=tmp_path)
    state = AppState(data, ROOT / "rules" / "rules.yaml", ROOT / "docs" / "rules", claude=claude)
    response = upload(TestClient(create_app(state)), "scan.pdf", scanned_pdf())
    assert response.status_code == 503 and "after one retry" in response.json()["detail"]


def test_bad_number_in_environment_falls_back(monkeypatch):
    monkeypatch.setenv("BUDGET_USD", "four")
    assert env_float("BUDGET_USD", 4.0) == 4.0


# ---------- values: units, zero, negative, missing label ----------

DOOR = Rule(id="D", title="Door", area="A", source="S", check="door_clear_width", params={"min_in": 32, "min_mm": 815})
CORRIDOR = Rule(id="C", title="Corridor", area="A", source="S", check="corridor_width", params={"min_in": 36, "reduced_in": 32})
RAMP = Rule(id="RP", title="Ramp", area="A", source="S", check="ramp_slope", params={"max_run_per_rise": 12})
PASSENGER = ShipProfile(id="p", name="p", ship_type="passenger", passengers=400)


def fact(subject, prop, value, unit="in"):
    return Fact(subject=subject, property=prop, value=value, unit=unit, source=Source(kind=SourceKind.CHAT))


@pytest.mark.parametrize("bad", [fact("door-number:7", "clear_width", 30, "furlong"),
                                 fact("door-number:7", "clear_width", 30, ""),
                                 fact("door-number:7", "clear_width", 0),
                                 fact("door-number:7", "clear_width", -34),
                                 fact("door-number:7", "clear_width", float("nan")),
                                 fact("corridor:A", "clear_width", -40),
                                 fact("ramp:R", "slope_run_per_rise", 0, "")])
def test_unusable_values_are_cant_tell_with_a_reason(bad):
    result = run(FactStore([bad]), [DOOR, CORRIDOR, RAMP], PASSENGER)
    mine = [f for f in result.findings if f.subject == bad.subject]
    assert mine and all(f.status == Status.CANT_TELL for f in mine)
    assert any(f.measured.startswith("Not used:") for f in mine)
    assert not any(f.status in (Status.PASS, Status.FAIL) for f in result.findings)


def test_missing_label_is_cant_tell():
    result = run(FactStore([fact("corridor:B", "shown_on", "page 1", "")]), [CORRIDOR], PASSENGER)
    assert [f.status for f in result.findings] == [Status.CANT_TELL]


def test_a_check_that_crashes_is_cant_tell_not_a_pass(monkeypatch):
    from app import checks

    def broken(rule, store, profile):
        raise RuntimeError("boom")

    monkeypatch.setitem(checks.CHECKS, "door_clear_width", broken)
    result = run(FactStore([fact("door-number:7", "clear_width", 40)]), [DOOR], PASSENGER)
    assert [f.status for f in result.findings] == [Status.CANT_TELL] and "boom" in result.findings[0].measured


def test_measure_rejects_unknown_unit_and_nonpositive_values(offline):
    api, state = offline
    state.active_model = "parts.json"  # pretend a model is loaded; the value checks come first
    body = {"subject": "corridor:X", "property": "clear_width", "value": 900, "unit": "furlong",
            "a": {"x": 0, "y": 0, "z": 0}, "b": {"x": 1, "y": 0, "z": 0}}
    assert api.post("/api/measure", params={"profile": PROFILE}, json=body).status_code == 400
    response = api.post("/api/measure", params={"profile": PROFILE}, json=body | {"unit": "mm", "value": -5})
    assert response.status_code == 400 and "more than 0" in response.json()["detail"]


# ---------- feedback ----------

def test_feedback_unknown_finding_and_bad_decision(offline):
    api, _ = offline
    body = {"profile": PROFILE, "rule_id": "PVAG-V404.2.3", "subject": "door-number:999", "decision": "accept"}
    assert api.post("/api/feedback", json=body).status_code == 404
    assert api.post("/api/feedback", json=body | {"decision": "maybe"}).status_code == 422
    bad_value = body | {"decision": "reject", "corrected_value": -3, "corrected_unit": "in"}
    assert api.post("/api/feedback", json=bad_value).status_code == 400


def test_repeated_decision_counts_once_and_a_closed_finding_says_so(offline):
    api, state = offline
    assert upload(api, "fail.pdf", (DEMO / "SYNTHETIC_demo_2_FAIL.pdf").read_bytes()).status_code == 200
    body = {"profile": PROFILE, "rule_id": "PVAG-V404.2.3", "subject": "door-number:201", "decision": "accept"}
    assert api.post("/api/feedback", json=body).status_code == 200
    assert api.post("/api/feedback", json=body | {"decision": "unsure"}).status_code == 200
    rows = [r for r in state.gate.pool.rows() if r["subject"] == "door-number:201"]
    assert len(rows) == 1 and rows[0]["decision"] == "unsure"
    # A correction replaces the reading, so the finding is closed: answering again is a 409 with the way out.
    fix = body | {"decision": "reject", "corrected_value": 33, "corrected_unit": "in"}
    assert api.post("/api/feedback", json=fix).status_code == 200
    again = api.post("/api/feedback", json=body)
    assert again.status_code == 409 and "Undo" in again.json()["detail"]

