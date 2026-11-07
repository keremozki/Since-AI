"""The offline demo set works through the real upload route with no API key and no network."""
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.llm import Claude, Ledger
from app.main import AppState, create_app

ROOT = Path(__file__).resolve().parents[2]
DEMO = ROOT / "data" / "demo_offline_SYNTHETIC"
FILES = sorted(DEMO.glob("*.pdf"))


def offline_client(tmp_path, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("CROSS_CHECK_READERS", raising=False)
    data = tmp_path / "data"
    data.mkdir()
    claude = Claude(Ledger(data / "usage.json", 0.0))  # no client and a zero budget: any API call would fail
    state = AppState(data, ROOT / "rules" / "rules.yaml", ROOT / "docs" / "rules", claude=claude)
    return TestClient(create_app(state)), state


def test_there_is_one_demo_per_finding_type():
    assert {p.stem.rsplit("_", 1)[-1] for p in FILES} >= {"PASS", "FAIL", "TELL", "CONFLICT"}


@pytest.mark.parametrize("pdf", FILES, ids=[p.stem for p in FILES])
def test_demo_drawing_gives_its_expected_results_offline(pdf, tmp_path, monkeypatch):
    api, state = offline_client(tmp_path, monkeypatch)
    truth = json.loads(pdf.with_suffix(".truth.json").read_text(encoding="utf-8"))
    assert truth["synthetic"] is True and "SYNTHETIC" in pdf.name
    response = api.post("/api/upload", data={"profile": truth["profile_in_app"]},
                        files={"file": (pdf.name, pdf.read_bytes(), "application/pdf")})
    assert response.status_code == 200, response.text
    got = {(f["rule_id"], f["subject"]): f["status"] for f in response.json()["result"]["findings"]}
    for e in truth["expected"]:
        assert got.get((e["rule_id"], e["subject"])) == e["expected"], e
    assert state.ledger.calls == 0
