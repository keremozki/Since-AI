"""The offline AI gateway: nothing leaves the machine, nothing is guessed, and answers replay exactly."""
import base64

import pytest

from app.ai_gateway import AIResponsePending, OfflineAI, SchemaError, request_id, _canonical, save_answer, validate

SCHEMA = {"type": "object", "additionalProperties": False, "required": ["facts"],
          "properties": {"facts": {"type": "array", "items": {"type": "object", "required": ["quote"],
                                                               "properties": {"quote": {"type": "string"},
                                                                              "value": {"type": ["number", "null"]}}}}}}
PNG = base64.standard_b64encode(b"\x89PNG fake image bytes").decode()
CONTENT = [{"type": "text", "text": "[Page 1]"},
           {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": PNG}}]


def test_unanswered_request_waits_and_saves_everything_needed(tmp_path):
    ai = OfflineAI(tmp_path)
    with pytest.raises(AIResponsePending) as pending:
        ai.structured("system text", CONTENT, SCHEMA, effort="medium")
    folder = pending.value.folder
    assert (folder / "request.json").exists()
    assert len(list(folder.glob("image-1-*.png"))) == 1
    assert ai.status()["pending"] == [pending.value.request_id]


def test_saved_answer_replays_and_same_request_has_same_id(tmp_path):
    ai = OfflineAI(tmp_path)
    with pytest.raises(AIResponsePending) as pending:
        ai.structured("system text", CONTENT, SCHEMA, effort="medium")
    rid = pending.value.request_id
    save_answer(tmp_path, rid, {"facts": [{"quote": "LOA 299.80 m", "value": 299.8}]}, "closed agent")
    assert ai.structured("system text", CONTENT, SCHEMA, effort="medium") == {"facts": [{"quote": "LOA 299.80 m", "value": 299.8}]}
    assert ai.status()["pending"] == []
    # A different effort is a different request: it never reuses another request's answer.
    with pytest.raises(AIResponsePending):
        ai.structured("system text", CONTENT, SCHEMA, effort="high")


def test_answers_that_break_the_schema_are_refused(tmp_path):
    ai = OfflineAI(tmp_path)
    with pytest.raises(AIResponsePending) as pending:
        ai.structured("s", "plain text", SCHEMA)
    with pytest.raises(SchemaError):
        save_answer(tmp_path, pending.value.request_id, {"facts": [{"value": 3}]}, "closed agent")
    with pytest.raises(SchemaError):
        save_answer(tmp_path, pending.value.request_id, {"facts": [], "verdict": "pass"}, "closed agent")


def test_request_id_ignores_image_encoding_but_not_image_bytes():
    request, _ = _canonical("s", CONTENT, SCHEMA, "low", 100)
    other = [CONTENT[0], {"type": "image", "source": {"type": "base64", "media_type": "image/png",
                                                     "data": base64.standard_b64encode(b"other").decode()}}]
    request2, _ = _canonical("s", other, SCHEMA, "low", 100)
    assert request_id(request) != request_id(request2)


def test_validate_checks_types_enums_and_required():
    schema = {"type": "object", "required": ["kind"], "properties": {"kind": {"type": "string", "enum": ["a", "b"]}}}
    validate({"kind": "a"}, schema)
    with pytest.raises(SchemaError):
        validate({"kind": "c"}, schema)
    with pytest.raises(SchemaError):
        validate({"kind": True}, {"type": "object", "properties": {"kind": {"type": "integer"}}})
