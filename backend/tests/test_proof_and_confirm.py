"""A single reading can't back a verdict until an engineer confirms it, and a proof bundle replays exactly."""
import io
import sys
import zipfile
from pathlib import Path

import pymupdf
from fastapi.testclient import TestClient

from app.ai_gateway import OfflineAI
from app.main import AppState, create_app
from app.models import Evidence, Fact, Source, SourceKind, Status
from app.proof import read_bundle

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))
import verify_proof  # noqa: E402

PROFILE = "passenger"
QUOTE = "FWD MASTHEAD LIGHT 12.5 m ABOVE UPPERMOST CONTINUOUS DECK"


def spec_pdf() -> bytes:
    document = pymupdf.open()
    page = document.new_page()
    page.insert_text((72, 100), QUOTE, fontsize=10)
    return document.tobytes()


def read_fact(value=12.5) -> Fact:
    # One reading of a document: tier C, so it may not back a pass on its own.
    return Fact(subject="masthead_forward", property="height_above_hull", value=value, unit="m",
                source=Source(kind=SourceKind.DOCUMENT, file="spec.pdf", locator="page 1", quote=QUOTE),
                evidence=Evidence(file="spec.pdf", page=1, quote=QUOTE))


def client(tmp_path):
    state = AppState(tmp_path, ROOT / "rules" / "rules.yaml", ROOT / "docs" / "rules", claude=OfflineAI(tmp_path / "ai"))
    state.store_upload("spec.pdf", spec_pdf())
    state.add_file("spec.pdf")
    state.add_facts([read_fact()])
    return state, TestClient(create_app(state))


def masthead(result: dict) -> dict:
    return next(f for f in result["findings"] if f["rule_id"] == "COLREG-ANNEX-I")


def test_single_reading_is_held_back_until_confirmed(tmp_path):
    state, api = client(tmp_path)
    finding = masthead(api.get(f"/api/run/{PROFILE}").json()["result"])
    assert finding["status"] == Status.CANT_TELL.value
    assert finding["gate"].startswith("Would pass")
    assert "Confirm or correct" in finding["question"]
    uid = finding["inputs"][0]["id"]
    confirmed = api.post(f"/api/facts/confirm?profile={PROFILE}", json={"id": uid, "by": "J. Engineer"}).json()
    assert masthead(confirmed["result"])["status"] == Status.PASS.value


def test_correction_replaces_the_reading_and_keeps_it_on_record(tmp_path):
    state, api = client(tmp_path)
    uid = masthead(api.get(f"/api/run/{PROFILE}").json()["result"])["inputs"][0]["id"]
    after = api.post(f"/api/facts/confirm?profile={PROFILE}",
                     json={"id": uid, "by": "J. Engineer", "value": 11.0, "unit": "m", "note": "drawing misprint"}).json()
    finding = masthead(after["result"])
    # The corrected value is the engineer's, so nothing is held back: 11.0 m with no breadth known is
    # a real "can't tell" (it depends on the greatest breadth), not a gated one.
    assert finding["status"] == Status.CANT_TELL.value and finding["gate"] == ""
    assert finding["measured"].startswith("11.0 m") and "greatest breadth" in finding["question"]
    facts = api.get("/api/facts").json()
    assert any(f["superseded_by"] for f in facts) and any(f["confirmed_by"] == "J. Engineer" for f in facts)


def test_confirm_needs_a_name(tmp_path):
    state, api = client(tmp_path)
    uid = state.added[0].uid()
    assert api.post(f"/api/facts/confirm?profile={PROFILE}", json={"id": uid, "by": " "}).status_code == 400


def test_proof_bundle_verifies_and_detects_tampering(tmp_path):
    state, api = client(tmp_path)
    state.confirm_fact(state.added[0].uid(), "J. Engineer")
    data = api.get(f"/api/proof/{PROFILE}").content
    bundle, files, problems = read_bundle(data)
    assert problems == [] and "spec.pdf" in files
    evidence_problems, manual, found = verify_proof.check_evidence(bundle, files)
    assert evidence_problems == [] and found == 1
    replay_problems, total = verify_proof.replay(bundle)
    assert replay_problems == [] and total == len(bundle["findings"])
    # Change one byte of the bundled evidence file: the manifest catches it.
    source = zipfile.ZipFile(io.BytesIO(data))
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w") as tampered:
        for name in source.namelist():
            body = source.read(name)
            tampered.writestr(name, body + b"%changed" if name == "files/spec.pdf" else body)
    _bundle, _files, problems = read_bundle(out.getvalue())
    assert any("spec.pdf" in p for p in problems)


def test_evidence_crop_is_a_png(tmp_path):
    state, api = client(tmp_path)
    response = api.get("/api/evidence/crop", params={"file": "spec.pdf", "page": 1, "x0": 70, "y0": 90, "x1": 300, "y1": 104})
    assert response.status_code == 200 and response.content[:4] == b"\x89PNG"


def test_engineer_answers_a_question_directly(tmp_path):
    state, api = client(tmp_path)
    response = api.post(f"/api/facts/state?profile={PROFILE}",
                        json={"subject": "ship", "property": "breadth_greatest", "value": 11.5, "unit": "m", "by": "J. Engineer"})
    assert response.status_code == 200
    facts = api.get("/api/facts").json()
    assert any(f["property"] == "breadth_greatest" and f["tier"] == "A" for f in facts)
    bad = api.post(f"/api/facts/state?profile={PROFILE}", json={"subject": "ship", "property": "favorite_color", "value": "red", "by": "J"})
    assert bad.status_code == 400
