"""Every API route is called once, offline, with no API key. None may answer 500."""
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.llm import Claude, Ledger
from app.main import AppState, create_app

ROOT = Path(__file__).resolve().parents[2]
P = "passenger-test"
DEMO_PDF = ROOT / "data" / "demo_offline_SYNTHETIC" / "SYNTHETIC_demo_2_FAIL.pdf"
POINT = {"x": 0, "y": 0, "z": 0}

# (method, path, kwargs, expected status). The order matters: the upload comes before the routes that use it.
CALLS = [
    ("GET", "/api/profiles", {}, 200),
    ("GET", f"/api/run/{P}", {}, 200),
    ("GET", f"/api/report/{P}", {}, 200),
    ("GET", "/api/facts", {}, 200),
    ("GET", "/api/accuracy", {}, 200),
    ("GET", "/api/vocabulary", {}, 200),
    ("GET", "/api/inputs", {}, 200),
    ("POST", "/api/upload", {"data": {"profile": P}, "files": {"file": (DEMO_PDF.name, DEMO_PDF.read_bytes(), "application/pdf")}}, 200),
    ("GET", "/api/evidence", {"params": {"file": DEMO_PDF.name, "locator": "page 1"}}, 200),
    ("GET", "/api/confidence", {}, 200),
    ("GET", f"/api/review-queue/{P}", {}, 200),
    ("POST", "/api/feedback", {"json": {"profile": P, "rule_id": "PVAG-V404.2.3", "subject": "door-number:201", "decision": "accept"}}, 200),
    ("DELETE", "/api/feedback", {"params": {"profile": P, "key": "no-such-key"}}, 404),
    ("POST", "/api/chat", {"json": {"profile": P, "message": "What failed?"}}, 503),  # no key: a clear 503
    ("POST", "/api/measure", {"params": {"profile": P}, "json": {"subject": "bridge", "property": "eye_to_bow", "value": 24,
                                                                 "unit": "m", "a": POINT, "b": POINT}}, 400),  # no 3D model here
    ("DELETE", "/api/inputs/files", {"params": {"profile": P, "name": DEMO_PDF.name}}, 200),
    ("DELETE", "/api/inputs/group/chat", {"params": {"profile": P}}, 200),
    ("DELETE", "/api/inputs/model", {"params": {"profile": P}}, 200),
    ("POST", "/api/inputs/model/restore", {"params": {"profile": P}}, 200),
    ("POST", "/api/inputs/model", {"data": {"profile": P}, "files": {"file": ("m.nwd", b"not a model", "application/octet-stream")}}, 400),
    ("GET", "/model/meta", {}, 404),
    ("GET", "/model/bin", {}, 404),
    ("POST", "/api/reset", {}, 200),
]


@pytest.fixture
def api(tmp_path, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("CROSS_CHECK_READERS", raising=False)
    data = tmp_path / "data"
    data.mkdir()
    (data / "accuracy.json").write_text(json.dumps({"note": "test"}))
    state = AppState(data, ROOT / "rules" / "rules.yaml", ROOT / "docs" / "rules", claude=Claude(Ledger(data / "u.json", 4.0)))
    return TestClient(create_app(state), raise_server_exceptions=False)


def test_every_route_answers_without_a_crash(api):
    for method, path, kwargs, expected in CALLS:
        response = api.request(method, path, **kwargs)
        assert response.status_code == expected, (method, path, response.text[:300])
        if response.status_code >= 400:
            assert response.json()["detail"], (method, path)


def test_every_route_is_in_the_smoke_test(api):
    templates = {"/api/run/{profile_id}": f"/api/run/{P}", "/api/report/{profile_id}": f"/api/report/{P}",
                 "/api/review-queue/{profile_id}": f"/api/review-queue/{P}", "/api/inputs/group/{group}": "/api/inputs/group/chat"}
    routes = {(m, templates.get(r.path, r.path)) for r in api.app.routes for m in (getattr(r, "methods", None) or [])
              if r.path.startswith(("/api", "/model"))}
    assert routes == {(m, p) for m, p, _k, _e in CALLS}
