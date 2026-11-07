"""The one door to the AI model. Three modes, set by AI_MODE:

- offline (default): no network. Each request is saved with a stable hash. If a recorded answer exists it is
  replayed; otherwise the request waits in ship-data/ai/pending/<hash>/ for an answer, and the app says so.
  Tonight the answers come from closed agents acting as the API (see docs/ai-offline.md and tools/ai_offline.py).
- api: the real Claude API through app.llm.Claude, with the spending cap.
- record: the real API, and every answer is also saved, so it replays offline later at no cost.

Whatever the mode, the same prompt, content, and schema go in, and the answer is validated against the schema
before any code uses it. The AI never decides a result: it only reads, points, and explains.
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path

from .llm import MODEL, Claude, Ledger, ModelRefused

MODES = ("offline", "api", "record")


class AIResponsePending(Exception):
    """Offline mode: the request is saved and waits for an answer. Nothing is guessed meanwhile."""

    def __init__(self, request_id: str, folder: Path):
        self.request_id, self.folder = request_id, folder
        super().__init__(
            f"The AI is in offline mode, so this request is saved as {request_id} and waits for an answer. "
            "Answer it with tools/ai_offline.py, or set AI_MODE=api to use the real API.")


class SchemaError(ModelRefused):
    pass


def _canonical(system: str, content: list[dict] | str, schema: dict, effort: str, max_tokens: int) -> tuple[dict, list[tuple[str, bytes, str]]]:
    """A stable form of the request. Images are replaced by their hash, and returned separately."""
    blocks = content if isinstance(content, list) else [{"type": "text", "text": content}]
    canon_blocks, images = [], []
    for block in blocks:
        if block.get("type") == "image":
            data = base64.standard_b64decode(block["source"]["data"])
            digest = hashlib.sha256(data).hexdigest()
            name = f"image-{len(images) + 1}-{digest[:12]}.{'png' if 'png' in block['source']['media_type'] else 'jpg'}"
            images.append((name, data, block["source"]["media_type"]))
            canon_blocks.append({"type": "image", "sha256": digest, "file": name})
        else:
            canon_blocks.append({"type": "text", "text": block.get("text", "")})
    request = {"model": MODEL, "system": system, "content": canon_blocks, "schema": schema,
               "effort": effort, "max_tokens": max_tokens}
    return request, images


def request_id(request: dict) -> str:
    return hashlib.sha256(json.dumps(request, sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:20]


def validate(instance, schema: dict, path: str = "$") -> None:
    """Validate the JSON-schema subset the app uses. Raises SchemaError on the first mismatch."""
    kinds = schema.get("type")
    kinds = [kinds] if isinstance(kinds, str) else (kinds or [])
    py = {"object": dict, "array": list, "string": str, "integer": int, "boolean": bool, "null": type(None)}
    if kinds:
        ok = False
        for kind in kinds:
            if kind == "number":
                ok |= isinstance(instance, (int, float)) and not isinstance(instance, bool)
            elif kind == "integer":
                ok |= isinstance(instance, int) and not isinstance(instance, bool)
            else:
                ok |= isinstance(instance, py[kind])
        if not ok:
            raise SchemaError(f"{path}: expected {kinds}, got {type(instance).__name__}")
    if "enum" in schema and instance not in schema["enum"]:
        raise SchemaError(f"{path}: {instance!r} is not one of {schema['enum']}")
    if isinstance(instance, dict):
        props = schema.get("properties", {})
        for key in schema.get("required", []):
            if key not in instance:
                raise SchemaError(f"{path}: missing {key}")
        if schema.get("additionalProperties") is False:
            extra = set(instance) - set(props)
            if extra:
                raise SchemaError(f"{path}: unexpected {sorted(extra)}")
        for key, value in instance.items():
            if key in props:
                validate(value, props[key], f"{path}.{key}")
    if isinstance(instance, list) and "items" in schema:
        for index, item in enumerate(instance):
            validate(item, schema["items"], f"{path}[{index}]")


class OfflineAI:
    """Replays recorded answers, and saves unanswered requests for a closed answerer. Spends nothing."""

    mode = "offline"

    def __init__(self, store: Path, ledger: Ledger | None = None):
        self.store = store
        self.ledger = ledger
        self.replayed = 0
        self.used: set[str] = set()  # ids of the answers replayed, for proof bundles

    @property
    def pending_dir(self) -> Path:
        return self.store / "pending"

    @property
    def responses_dir(self) -> Path:
        return self.store / "responses"

    def structured(self, system: str, content, schema: dict, effort: str = "low", max_tokens: int = 8000) -> dict:
        request, images = _canonical(system, content, schema, effort, max_tokens)
        rid = request_id(request)
        answer = self.responses_dir / f"{rid}.json"
        if answer.exists():
            saved = json.loads(answer.read_text(encoding="utf-8"))
            validate(saved["response"], schema)
            self.replayed += 1
            self.used.add(rid)
            return saved["response"]
        folder = self.pending_dir / rid
        folder.mkdir(parents=True, exist_ok=True)
        for name, data, _media in images:
            (folder / name).write_bytes(data)
        (folder / "request.json").write_text(json.dumps(
            {**request, "id": rid, "created": datetime.now(timezone.utc).isoformat(timespec="seconds")},
            indent=1, ensure_ascii=False), encoding="utf-8")
        raise AIResponsePending(rid, folder)

    def status(self) -> dict:
        pending = sorted(p.name for p in self.pending_dir.glob("*") if p.is_dir() and not (self.responses_dir / f"{p.name}.json").exists())
        answered = sorted(p.stem for p in self.responses_dir.glob("*.json"))
        return {"mode": self.mode, "pending": pending, "answered": len(answered), "replayed_this_run": self.replayed}


def save_answer(store: Path, rid: str, response: dict, answered_by: str) -> Path:
    """Store an answer for a saved request after validating it against that request's schema."""
    request_file = store / "pending" / rid / "request.json"
    request = json.loads(request_file.read_text(encoding="utf-8"))
    validate(response, request["schema"])
    out = store / "responses" / f"{rid}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({"id": rid, "response": response, "answered_by": answered_by,
                               "answered": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                               "model_requested": request["model"], "effort": request["effort"]},
                              indent=1, ensure_ascii=False), encoding="utf-8")
    return out


class RecordingAI:
    """The real API, with every answer saved so it replays offline later."""

    mode = "record"

    def __init__(self, store: Path, claude: Claude):
        self.store, self.claude = store, claude
        self.used: set[str] = set()

    def structured(self, system: str, content, schema: dict, effort: str = "low", max_tokens: int = 8000) -> dict:
        request, _images = _canonical(system, content, schema, effort, max_tokens)
        rid = request_id(request)
        answer = self.store / "responses" / f"{rid}.json"
        self.used.add(rid)
        if answer.exists():
            return json.loads(answer.read_text(encoding="utf-8"))["response"]
        response = self.claude.structured(system, content, schema, effort=effort, max_tokens=max_tokens)
        validate(response, schema)
        answer.parent.mkdir(parents=True, exist_ok=True)
        answer.write_text(json.dumps({"id": rid, "response": response, "answered_by": f"api:{MODEL}"}, indent=1), encoding="utf-8")
        return response


class ApiAI:
    mode = "api"

    def __init__(self, claude: Claude):
        self.claude = claude

    def structured(self, system: str, content, schema: dict, effort: str = "low", max_tokens: int = 8000) -> dict:
        response = self.claude.structured(system, content, schema, effort=effort, max_tokens=max_tokens)
        validate(response, schema)
        return response


def make_ai(data_dir: Path, ledger: Ledger, mode: str | None = None):
    mode = (mode or os.environ.get("AI_MODE", "offline")).strip().lower()
    store = data_dir / "ai"
    if mode == "api":
        return ApiAI(Claude(ledger))
    if mode == "record":
        return RecordingAI(store, Claude(ledger))
    return OfflineAI(store, ledger)
