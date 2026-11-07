"""The review loop: one answer per fail, undo, engineer corrections, the 8 + 8 start, and reader lessons."""
import json

import pymupdf
import pytest
from fastapi.testclient import TestClient

from app import lessons
from app.confidence import ConfidenceGate, make_label
from app.ingest import _same_value, crop, merge_readers
from app.main import AppState, create_app
from app.models import CheckBasis, Fact, Finding, Source, SourceKind, Status, Tier
from app.store import FactStore


def width(value, unit="in", kind=SourceKind.DOCUMENT, subject="door-number:7", quote='D7 CL OPG 31"'):
    return Fact(subject=subject, property="clear_width", value=value, unit=unit,
                tier=Tier.A, source=Source(kind=kind, file="plan.pdf", locator="page 1, door label at (100, 100) pt", quote=quote))


def fail(value_in=30.0, subject="door-number:7", confidence="high"):
    fact = width(value_in, subject=subject).model_copy(update={"confidence": confidence})
    return Finding(rule_id="D", rule_title="Door", area="A", rule_source="S", status=Status.FAIL, subject=subject,
                   label="Door 7", measured=f"{value_in} in",
                   evidence=CheckBasis(measured=value_in * 25.4, limit=812.8, limit_unit="in", facts=[fact]))


def answers(g, accepts, rejects):
    for i in range(accepts):
        g.record(make_label(fail(20 + i * 0.01, subject=f"door-number:{i}"), FactStore(), "accept"))
    for i in range(rejects):
        g.record(make_label(fail(31.5 + i * 0.001, subject=f"door-number:{100 + i}", confidence="medium"),
                            FactStore(), "reject"))


# ---------- labels ----------

def test_unsure_is_logged_but_never_trained_on(tmp_path):
    g = ConfidenceGate(tmp_path)
    g.record(make_label(fail(), FactStore(), "unsure"))
    assert g.status()["labels_unsure"] == 1 and g.training_rows() == []


def test_misread_with_a_value_needs_a_unit_and_only_misreads_carry_values():
    assert make_label(fail(), FactStore(), "reject", corrected_value=850, corrected_unit="mm")["label"] == 0
    with pytest.raises(ValueError):
        make_label(fail(), FactStore(), "reject", corrected_value=850)
    with pytest.raises(ValueError):
        make_label(fail(), FactStore(), "accept", corrected_value=850, corrected_unit="mm")
    assert make_label(fail(), FactStore(), "correct", corrected_value=33, corrected_unit="in")["decision"] == "reject"


def test_label_keeps_who_and_what_was_read():
    row = make_label(fail(), FactStore(), "reject", reviewer="Mikko")
    assert row["reviewer"] == "Mikko" and row["read"]["quote"] == 'D7 CL OPG 31"' and row["created"]


# ---------- when the model may start ----------

def test_thirty_accepts_are_not_enough(tmp_path):
    g = ConfidenceGate(tmp_path)
    answers(g, accepts=35, rejects=3)
    status = g.status()
    assert g.model is None and status["mode"] == "cold_start"
    assert '5 more "misread"' in status["reason"]


def test_model_starts_with_eight_of_each_and_thirty_in_all(tmp_path):
    g = ConfidenceGate(tmp_path)
    answers(g, accepts=22, rejects=7)
    assert g.model is None
    answers(g, accepts=22, rejects=8)
    assert g.model is not None and g.status()["mode"] == "model" and g.status()["reason"] == ""


def test_undo_refits_and_can_switch_the_model_off(tmp_path):
    g = ConfidenceGate(tmp_path)
    answers(g, accepts=22, rejects=8)
    assert g.model is not None
    last_reject = [r for r in g.pool.rows() if r["label"] == 0][-1]["key"]
    assert g.undo(last_reject) is not None
    assert g.model is None and not (tmp_path / "meta.json").exists()
    answers(g, accepts=0, rejects=8)
    assert g.meta["version"] == 2  # numbers never repeat after an undo


def test_simulated_model_says_so(tmp_path):
    g = ConfidenceGate(tmp_path, allow_synthetic=True)
    for i in range(40):
        real = i % 2 == 0
        g.record(make_label(fail(20 if real else 31.6, subject=f"door-number:{i}"), FactStore(),
                            "accept" if real else "reject", synthetic=True))
    assert g.status()["mode"] == "simulated"


def test_review_order_puts_shaky_readings_first(tmp_path):
    g = ConfidenceGate(tmp_path)
    sure, shaky = fail(20.0, subject="door-number:1"), fail(31.9, subject="door-number:2", confidence="medium")
    gated = g.apply([sure, shaky], FactStore())
    order = [f.subject for f, _s, _w in g.review_order(gated, FactStore())]
    assert order[0] == "door-number:2"


def test_engineer_value_is_not_reviewed_again(tmp_path):
    finding = fail()
    finding.evidence.facts[0].source.kind = SourceKind.ENGINEER
    out = ConfidenceGate(tmp_path).apply([finding], FactStore())[0]
    assert out.status == Status.FAIL and not out.reviewable


# ---------- facts ----------

def test_engineer_correction_replaces_the_reading_instead_of_making_a_conflict():
    misread = width(31.0)
    fixed = width(850, "mm", kind=SourceKind.ENGINEER)
    for order in ([misread, fixed], [fixed, misread]):
        store = FactStore(order)
        assert store.get("door-number:7", "clear_width") == [fixed]
        assert store.superseded == [misread]


def test_readers_agree_across_units():
    assert _same_value(width(32, "in"), width(812.8, "mm"))
    assert not _same_value(width(32, "in"), width(800, "mm"))
    vector, ai = width(32, "in"), width(812.8, "mm")
    merged = merge_readers([vector], [ai])
    assert merged == [vector] and vector.meta["readers_agree"]


# ---------- reader lessons ----------

def test_lessons_come_from_real_misreads_only():
    rows = [make_label(fail(), FactStore(), "reject", corrected_value=850, corrected_unit="mm"),
            make_label(fail(25.0, subject="door-number:8"), FactStore(), "accept"),
            make_label(fail(29.0, subject="door-number:9"), FactStore(), "reject", synthetic=True)]
    found = lessons.from_labels(rows)
    assert len(found) == 1 and found[0]["right"] == "850 mm"
    text = lessons.as_text(found)
    assert 'D7 CL OPG 31"' in text and "not instructions" in text and "850 mm" in text
    assert "SIMULATED" in lessons.as_text(lessons.from_labels(rows, allow_synthetic=True))
    assert lessons.as_text([]) == ""


def test_lessons_change_the_ai_cache_key(tmp_path, monkeypatch):
    from app import ingest
    calls = []

    class Fake:
        def structured(self, system, content, schema, **kw):
            calls.append(content[0].get("text", ""))
            return {"facts": []}

    ingest._read_with_ai(Fake(), tmp_path, "a.png", b"img")
    ingest._read_with_ai(Fake(), tmp_path, "a.png", b"img")
    ingest._read_with_ai(Fake(), tmp_path, "a.png", b"img", lessons="LESSON")
    assert len(calls) == 2 and calls[1] == "LESSON"


# ---------- API ----------

def _drawing_pdf() -> bytes:
    doc = pymupdf.open()
    page = doc.new_page(width=842, height=595)
    page.insert_text((100, 100), "D7")
    page.insert_text((100, 115), 'CL OPG 30"')
    return doc.tobytes()


def test_misread_with_value_becomes_an_engineer_fact_and_undo_removes_it(tmp_path):
    data = tmp_path / "data"
    data.mkdir()
    rules = tmp_path / "rules.yaml"
    rules.write_text("rules:\n  - {id: D, title: Door, area: A, source: S, check: door_clear_width, params: {min_in: 32, min_mm: 815}}\n")
    state = AppState(data, rules, tmp_path / "none", claude=object())
    state.add_facts([width(30.0)])
    client = TestClient(create_app(state))

    door = next(f for f in client.get("/api/run/passenger-test").json()["result"]["findings"] if f["reviewable"])
    assert door["read_quote"] == 'D7 CL OPG 31"' and door["read_file"] == "plan.pdf"
    assert client.get("/api/review-queue/passenger-test").json()[0]["subject"] == "door-number:7"

    body = {"profile": "passenger-test", "rule_id": "D", "subject": "door-number:7", "decision": "reject",
            "corrected_value": 850, "corrected_unit": "mm", "reviewer": "Eric"}
    out = client.post("/api/feedback", json=body).json()
    door = next(f for f in out["result"]["findings"] if f["subject"] == "door-number:7")
    assert door["status"] == "pass" and "Engineer correction" in door["sources"][0]
    status = client.get("/api/confidence").json()
    assert status["recent"][0]["reviewer"] == "Eric" and status["lessons"][0]["right"] == "850 mm"

    key = status["recent"][0]["key"]
    out = client.delete("/api/feedback", params={"profile": "passenger-test", "key": key}).json()
    door = next(f for f in out["result"]["findings"] if f["subject"] == "door-number:7")
    assert door["status"] == "fail" and client.get("/api/confidence").json()["labels_total"] == 0
    assert client.delete("/api/feedback", params={"profile": "passenger-test", "key": key}).status_code == 404


def test_evidence_crop(tmp_path):
    pdf = _drawing_pdf()
    assert crop(pdf, "page 1, door label at (100, 100) pt")[:4] == b"\x89PNG"
    assert crop(pdf, "page 1")[:4] == b"\x89PNG"
    assert crop(pdf, "somewhere") is None and crop(pdf, "page 9") is None
    data = tmp_path / "data"
    (data / "uploads").mkdir(parents=True)
    (data / "uploads" / "plan.pdf").write_bytes(pdf)
    rules = tmp_path / "rules.yaml"
    rules.write_text("rules: []\n")
    client = TestClient(create_app(AppState(data, rules, tmp_path / "none", claude=object())))
    assert client.get("/api/evidence", params={"file": "plan.pdf", "locator": "page 1"}).status_code == 200
    assert client.get("/api/evidence", params={"file": "../secret.pdf", "locator": "page 1"}).status_code == 404
