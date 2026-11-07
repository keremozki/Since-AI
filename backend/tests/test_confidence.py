"""The confidence gate may only hold a fail back. It must never create a fail or hide a pass."""
import json

import pytest
from fastapi.testclient import TestClient

from app.confidence import ConfidenceGate, features, make_label, shown_status
from app.engine import run
from app.main import AppState, create_app
from app.models import Evidence, Fact, Finding, Rule, Source, SourceKind, Status
from app.profiles import PROFILES
from app.store import FactStore

DOOR_RULE = Rule(id="D", title="Door", area="A", source="S", check="door_clear_width", params={"min_in": 32, "min_mm": 815})


def width_fact(value_in, confidence="high", kind=SourceKind.DOCUMENT, quote=None, subject="door:1"):
    quote = f'D1 CL OPG {value_in}"' if quote is None else quote
    return Fact(subject=subject, property="clear_width", value=value_in, unit="in", confidence=confidence,
                source=Source(kind=kind, file="plan.pdf", quote=quote))


def fail(value_in=30.0, **kw):
    fact = width_fact(value_in, **kw)
    return Finding(rule_id="D", rule_title="Door", area="A", rule_source="S", status=Status.FAIL, subject=fact.subject,
                   label="Door 1", measured=f"{value_in} in",
                   evidence=Evidence(measured=value_in * 25.4, limit=32 * 25.4, limit_unit="in", facts=[fact]))


def gate(tmp_path, **kw):
    return ConfidenceGate(tmp_path / "conf", **kw)


def fill(g, n, synthetic=False):
    """Alternate labels: far-from-limit fails are real, near-limit ones are misreads."""
    for i in range(n):
        real = i % 2 == 0
        f = fail(20.0 + i * 0.01 if real else 31.5 + i * 0.001, confidence="high" if real else "medium")
        f.subject = f"door:{i}"
        g.record(make_label(f, FactStore(), "accept" if real else "reject", synthetic=synthetic))


@pytest.mark.parametrize("status", [Status.PASS, Status.CONFLICT, Status.CANT_TELL])
def test_policy_never_changes_anything_but_a_fail(status):
    for p in (None, 0.0, 1.0):
        assert shown_status(status, 0.1, p)[0] == status


def test_low_confidence_never_produces_fail_even_if_model_is_sure():
    assert shown_status(Status.FAIL, 0.4, 0.99)[0] == Status.CANT_TELL
    assert shown_status(Status.FAIL, 0.4, None)[0] == Status.CANT_TELL


def test_fail_below_threshold_becomes_cant_tell_with_a_reason():
    status, reason = shown_status(Status.FAIL, 0.9, 0.42, tau=0.7)
    assert status == Status.CANT_TELL and "0.42" in reason


def test_cold_start_keeps_a_confident_fail(tmp_path):
    out = gate(tmp_path).apply([fail(confidence="high")], FactStore())[0]
    assert out.status == Status.FAIL and out.reviewable and out.p_real is None


def test_cold_start_holds_back_a_low_confidence_fail(tmp_path):
    out = gate(tmp_path).apply([fail(confidence="low")], FactStore())[0]
    assert out.status == Status.CANT_TELL and out.original_status == Status.FAIL and out.question


def test_gate_leaves_passes_untouched(tmp_path):
    g = gate(tmp_path)
    fill(g, 40)
    passed = fail().model_copy(update={"status": Status.PASS})
    assert g.apply([passed], FactStore())[0] == passed


def test_engine_with_gate_never_adds_fails(tmp_path):
    g = gate(tmp_path)
    fill(g, 40)
    store = FactStore([Fact(subject="door:9", property="kind", value="passage", source=Source(kind=SourceKind.CHAT)),
                       Fact(subject="door:9", property="name", value="DOOR", source=Source(kind=SourceKind.CHAT)),
                       width_fact(31.9, subject="door:9", confidence="medium")])
    plain = run(store, [DOOR_RULE], PROFILES["passenger-test"])
    gated = run(store, [DOOR_RULE], PROFILES["passenger-test"], gate=g)
    assert gated.counts["fail"] <= plain.counts["fail"]
    assert gated.counts["pass"] == plain.counts["pass"]


def test_no_model_until_enough_labels_then_retrain_every_five(tmp_path):
    g = gate(tmp_path)
    fill(g, 29)
    assert g.status()["mode"] == "cold_start"
    fill(g, 30)
    assert g.meta["version"] == 1
    for i in range(4):
        g.record(make_label(fail(25.0), FactStore(), "accept") | {"key": f"extra{i}"})
    assert g.meta["version"] == 1
    g.record(make_label(fail(25.0), FactStore(), "accept") | {"key": "extra4"})
    assert g.meta["version"] == 2


def test_model_learns_the_pattern(tmp_path):
    g = gate(tmp_path)
    fill(g, 40)
    near, far = fail(31.6, confidence="medium"), fail(20.0, confidence="high")
    assert g.p_real(features(far)) > 0.7 > g.p_real(features(near))


def test_simulated_labels_are_not_used_unless_allowed(tmp_path):
    g = gate(tmp_path)
    fill(g, 40, synthetic=True)
    assert g.model is None and g.status()["labels_used"] == 0
    demo = gate(tmp_path, allow_synthetic=True)
    assert demo.maybe_retrain() and demo.meta["n_synthetic"] == 40
    held = demo.apply([fail(31.6, confidence="medium")], FactStore())[0]
    assert held.status == Status.CANT_TELL and "SIMULATED" in held.gate_note
    # Once simulated labels aren't allowed, the model fitted on them doesn't load.
    assert gate(tmp_path).model is None


def test_same_finding_reviewed_twice_counts_once(tmp_path):
    g = gate(tmp_path)
    g.record(make_label(fail(), FactStore(), "accept"))
    g.record(make_label(fail(), FactStore(), "reject"))
    rows = g.pool.rows()
    assert len(rows) == 1 and rows[0]["label"] == 0


def test_correct_is_a_misread_and_needs_the_value():
    assert make_label(fail(), FactStore(), "correct", corrected_value=33, corrected_unit="in")["label"] == 0
    with pytest.raises(ValueError):
        make_label(fail(), FactStore(), "correct")


def test_features_mark_pictures_without_dimension_text():
    row = features(fail(kind=SourceKind.IMAGE, quote=""))
    assert row["scale_known"] == 0 and row["value_is_stated"] == 0 and row["source_image"] == 1
    assert features(fail())["has_unit_text"] == 1


def test_feedback_endpoint_stores_an_engineer_label(tmp_path):
    data = tmp_path / "data"
    data.mkdir()
    parts = [{"name": "DOOR, PASSAGE", "description": "CLEAR OPENING 30 x 80", "x_in": 0.0, "y_in": 0.0, "z_in": 336.7}]
    (data / "parts.json").write_text(json.dumps({"source": "m.nwd", "parts": parts}))
    rules = tmp_path / "rules.yaml"
    rules.write_text("rules:\n  - {id: D, title: Door, area: A, source: S, check: door_clear_width, params: {min_in: 32, min_mm: 815}}\n")
    state = AppState(data, rules, tmp_path / "none", claude=object())
    client = TestClient(create_app(state))
    findings = client.get("/api/run/passenger-test").json()["result"]["findings"]
    door = next(f for f in findings if f["reviewable"])
    assert "evidence" not in door
    body = {"profile": "passenger-test", "rule_id": door["rule_id"], "subject": door["subject"], "decision": "reject"}
    assert client.post("/api/feedback", json=body).status_code == 200
    assert client.get("/api/confidence").json()["labels_total"] == 1
    assert client.post("/api/feedback", json=body | {"subject": "nope"}).status_code == 404
