"""Web API. Runs locally: nothing here is meant for public hosting."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse, PlainTextResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import chat as chat_module
from . import confidence
from . import ingest, lessons, nwd
from .checks import describe_fact
from .engine import report_text, run
from .llm import DEFAULT_CAP_USD, AIUnavailable, BudgetExceeded, Claude, Ledger, ModelRefused, env_float, load_env
from .models import Fact, Point, RunResult, Source, SourceKind, Status
from .parts import facts_from_parts, load_parts
from .profiles import PROFILES, demo_faults
from .rules import load_rules
from .store import FactStore
from .units import is_length_unit
from .vocabulary import VOCABULARY

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_PARTS = "parts.json"
MAX_LISTED_CHANGES = 8
FILE_KINDS = {SourceKind.DOCUMENT, SourceKind.IMAGE}
FACT_GROUPS = {"measurements": SourceKind.MEASUREMENT, "chat": SourceKind.CHAT}


def _digest(parts: list[dict]) -> str:
    return hashlib.sha256(json.dumps(parts, sort_keys=True).encode()).hexdigest()[:24]


class AppState:
    def __init__(self, data_dir: Path, rules_file: Path, rule_texts_dir: Path, claude: Claude | None = None):
        self.data_dir = data_dir
        self.rules_file, self.rule_texts_dir = rules_file, rule_texts_dir
        self.added_file = data_dir / "added_facts.json"
        self.inputs_file = data_dir / "inputs.json"
        self.active_model: str | None = None
        self.geometry_for: str | None = None
        self.files: list[str] = []
        self._load_inputs()
        self.model_name, self.model_digest = "", ""
        self.model_parts = 0
        self.model_facts: list[Fact] = []
        self._load_active_model()
        self.added: list[Fact] = []
        if self.added_file.exists():
            self.added = [Fact(**raw) for raw in json.loads(self.added_file.read_text(encoding="utf-8"))]
        self.ledger = Ledger(data_dir / "usage.json", env_float("BUDGET_USD", DEFAULT_CAP_USD))
        self.claude = claude or Claude(self.ledger)
        self.history: list[dict] = []
        # Checking quotes means reading every rule text, so do it once at startup.
        self.rules = load_rules(rules_file, rule_texts_dir)
        self.gate = confidence.ConfidenceGate(
            data_dir / "confidence", tau=env_float("CONFIDENCE_TAU", confidence.TAU),
            allow_synthetic=os.environ.get("CONFIDENCE_ALLOW_SYNTHETIC") == "1")

    def _load_inputs(self) -> None:
        if self.inputs_file.exists():
            saved = json.loads(self.inputs_file.read_text(encoding="utf-8"))
            self.active_model = saved["active_model"]
            self.geometry_for, self.files = saved["geometry_for"], saved["files"]
            # Older saves could keep a removed model for restoring. That copy is no longer needed.
            if saved.get("last_model") and not self.active_model:
                self._delete_stored_model(saved["last_model"])
            return
        # First run: the model set up on disk is active, and the viewer's geometry belongs to it.
        if (self.data_dir / DEFAULT_PARTS).exists():
            self.active_model = DEFAULT_PARTS
            if (self.data_dir / "model.bin").exists():
                self.geometry_for = _digest(load_parts(self.data_dir / DEFAULT_PARTS)[1])

    def _save_inputs(self) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.inputs_file.write_text(json.dumps({
            "active_model": self.active_model,
            "geometry_for": self.geometry_for, "files": self.files}), encoding="utf-8")

    def _load_active_model(self) -> None:
        self.model_name, self.model_digest, self.model_parts, self.model_facts = "", "", 0, []
        if self.active_model is None:
            return
        name, parts = load_parts(self.data_dir / self.active_model)
        self.model_name, self.model_digest, self.model_parts = name, _digest(parts), len(parts)
        self.model_facts = facts_from_parts(name, parts)

    def _save_added(self) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.added_file.write_text(json.dumps([f.model_dump(mode="json") for f in self.added]), encoding="utf-8")

    def add_facts(self, facts: list[Fact]) -> None:
        self.added.extend(facts)
        self._save_added()

    def drop_correction(self, label_key: str) -> None:
        """Remove the engineer correction made with one answer (when it is answered again or undone)."""
        kept = [f for f in self.added if not (f.source.kind == SourceKind.ENGINEER and f.meta.get("label_key") == label_key)]
        if len(kept) != len(self.added):
            self.added = kept
            self._save_added()

    def lessons_text(self) -> str:
        return lessons.as_text(lessons.from_labels(self.gate.pool.rows(), allow_synthetic=self.gate.allow_synthetic))

    def add_file(self, name: str) -> None:
        if name not in self.files:
            self.files.append(name)
            self._save_inputs()

    def remove_file(self, name: str) -> bool:
        found = name in self.file_names()
        self.added = [f for f in self.added if not (f.source.kind in FILE_KINDS and f.source.file == name)]
        self.files = [known for known in self.files if known != name]
        self._save_added()
        self._save_inputs()
        return found

    def remove_group(self, kind: SourceKind) -> None:
        self.added = [f for f in self.added if f.source.kind != kind]
        self._save_added()

    def _delete_stored_model(self, stored: str) -> None:
        """Only imported copies are deleted. parts.json is set up by hand and used by the accuracy report."""
        if stored.startswith("models/"):
            (self.data_dir / stored).unlink(missing_ok=True)

    def remove_model(self) -> None:
        """Take the model out completely, along with the measurements taken on it."""
        if self.active_model is None:
            return
        self._delete_stored_model(self.active_model)
        self.active_model = None
        self._save_inputs()
        self._load_active_model()
        self.remove_group(SourceKind.MEASUREMENT)

    def import_model(self, data: bytes | bytearray, name: str) -> None:
        """Replace the active model. Measurements belong to a model, so a different ship drops them."""
        parts = nwd.decode_bytes(data)
        if not parts:
            raise ValueError(f"No named parts could be read from {name}. The file may be a format we don't support.")
        digest = _digest(parts)
        previous, replaced = self.model_digest, self.active_model
        stored = Path("models") / f"{digest}.json"
        (self.data_dir / "models").mkdir(parents=True, exist_ok=True)
        (self.data_dir / stored).write_text(json.dumps({"source": name, "parts": parts}), encoding="utf-8")
        self.active_model = stored.as_posix()
        self._save_inputs()
        self._load_active_model()
        if digest != previous:
            self.remove_group(SourceKind.MEASUREMENT)
            if replaced:
                self._delete_stored_model(replaced)

    @property
    def has_view(self) -> bool:
        return bool(self.model_digest) and self.model_digest == self.geometry_for and (self.data_dir / "model.bin").exists()

    def file_names(self) -> list[str]:
        named = [f.source.file for f in self.added if f.source.kind in FILE_KINDS]
        return list(dict.fromkeys(self.files + named))

    def inputs(self) -> dict:
        def count(kind: SourceKind) -> int:
            return sum(f.source.kind == kind for f in self.added)

        return {
            "model": {"name": self.model_name, "parts": self.model_parts, "has_view": self.has_view,
                      "active": self.active_model is not None},
            "files": [{"name": name, "facts": sum(f.source.kind in FILE_KINDS and f.source.file == name for f in self.added)}
                      for name in self.file_names()],
            "measurements": count(SourceKind.MEASUREMENT),
            "chat": count(SourceKind.CHAT),
        }

    def reset(self) -> None:
        self.added, self.history, self.files = [], [], []
        self.added_file.unlink(missing_ok=True)
        self._save_inputs()

    def result(self, profile_id: str) -> RunResult:
        profile = PROFILES.get(profile_id)
        if profile is None:
            raise HTTPException(404, f"Unknown ship profile: {profile_id}")
        return run(self.store(profile_id), self.rules, profile, gate=self.gate)

    def store(self, profile_id: str) -> FactStore:
        profile = PROFILES[profile_id]
        return FactStore(self.model_facts + self.added + (demo_faults() if profile.use_demo_faults else []))


class ChatRequest(BaseModel):
    profile: str
    message: str


class FeedbackRequest(BaseModel):
    profile: str
    rule_id: str
    subject: str
    decision: str  # accept (read correctly), reject (misread, value optional), or unsure
    corrected_value: float | None = None
    corrected_unit: str = ""
    note: str = ""
    reviewer: str = ""


class MeasureRequest(BaseModel):
    subject: str
    property: str
    value: float
    unit: str = "m"
    a: Point
    b: Point
    note: str = ""


def create_app(state: AppState | None = None) -> FastAPI:
    if state is None:
        load_env(ROOT / ".env")
        state = AppState(ROOT / "ship-data", ROOT / "rules" / "rules.yaml", ROOT / "docs" / "rules")
    app = FastAPI(title="Dynamis SCC")
    app.state.compliance = state

    def spend() -> dict:
        return {"spent_usd": round(state.ledger.spent, 4), "cap_usd": state.ledger.cap, "calls": state.ledger.calls}

    def rerun(before: RunResult, profile: str, recorded: list[Fact] | None = None, **extra) -> dict:
        after = state.result(profile)
        return {"recorded": recorded or [], "recorded_text": [describe_fact(f) for f in recorded or []],
                "changes": _changes(before, after), "result": after, "spend": spend(), "inputs": state.inputs(), **extra}

    @app.get("/api/profiles")
    def profiles():
        return list(PROFILES.values())

    @app.get("/api/run/{profile_id}")
    def run_checks(profile_id: str):
        return {"result": state.result(profile_id), "spend": spend()}

    @app.get("/api/report/{profile_id}", response_class=PlainTextResponse)
    def report(profile_id: str):
        return report_text(state.result(profile_id))

    @app.get("/api/facts")
    def added_facts():
        return state.added

    @app.get("/api/accuracy")
    def accuracy():
        path = state.data_dir / "accuracy.json"
        return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None

    @app.get("/api/vocabulary")
    def vocabulary():
        return [{"subject": s, "property": p, "kind": k, "meaning": m} for s, p, k, m in VOCABULARY if k == "length"]

    @app.post("/api/reset")
    def reset():
        state.reset()
        return {"ok": True}

    @app.get("/api/inputs")
    def inputs():
        return state.inputs()

    @app.delete("/api/inputs/model")
    def remove_model(profile: str):
        before = state.result(profile)
        state.remove_model()
        return rerun(before, profile)

    @app.post("/api/inputs/model")
    async def import_model(profile: str, name: str, request: Request):
        """The request body is the file itself. Sending it unwrapped makes a large upload much faster."""
        if Path(name).suffix.lower() != ".nwd":
            raise HTTPException(400, f"Can't import {name}. The app reads Navisworks .nwd files only.")
        before = state.result(profile)
        # Kept in memory: writing a large file to disk first would only add time.
        data = bytearray()
        async for chunk in request.stream():
            data += chunk
        try:
            await run_in_threadpool(state.import_model, data, name)
        except ValueError as error:
            raise HTTPException(400, str(error)) from error
        return rerun(before, profile)

    @app.delete("/api/inputs/files")
    def remove_file(profile: str, name: str):
        before = state.result(profile)
        if not state.remove_file(name):
            raise HTTPException(404, f"No file called {name} is loaded.")
        return rerun(before, profile)

    @app.delete("/api/inputs/group/{group}")
    def remove_group(group: str, profile: str):
        if group not in FACT_GROUPS:
            raise HTTPException(404, f"Unknown input group: {group}")
        before = state.result(profile)
        state.remove_group(FACT_GROUPS[group])
        return rerun(before, profile)

    @app.post("/api/chat")
    def chat(request: ChatRequest):
        before = state.result(request.profile)
        if not request.message.strip():
            raise HTTPException(400, "The message is empty.")
        try:
            reply, facts, dropped = chat_module.respond(state.claude, before, state.history, request.message)
        except (BudgetExceeded, ModelRefused, AIUnavailable) as error:
            raise HTTPException(503, str(error)) from error
        state.history += [{"role": "engineer", "text": request.message}, {"role": "assistant", "text": reply}]
        state.add_facts(facts)
        return rerun(before, request.profile, reply=reply, recorded=facts, dropped=dropped)

    @app.post("/api/upload")
    async def upload(profile: str = Form(...), file: UploadFile = File(...), pages: str = Form("")):
        before = state.result(profile)
        name = Path(file.filename or "upload").name
        data = await file.read(ingest.MAX_UPLOAD_BYTES + 1)  # never hold more than the limit in memory
        try:
            page_list = ingest.parse_pages(pages)
            facts, cached, dropped = ingest.read_file(state.claude, state.data_dir / "extract-cache",
                                                      name, data, page_list, lessons=state.lessons_text())
        except ingest.FileTooLarge as error:
            raise HTTPException(413, str(error)) from error
        except (AIUnavailable, BudgetExceeded) as error:
            # Missing key, rejected key, no answer after a retry, or the cap: the rest of the app keeps working.
            raise HTTPException(503, str(error)) from error
        except (ModelRefused, ingest.TooManyPages, ValueError) as error:
            raise HTTPException(400, str(error)) from error
        # Keep the file, so a reviewer can see the part of the drawing a value came from.
        (state.data_dir / "uploads").mkdir(parents=True, exist_ok=True)
        (state.data_dir / "uploads" / Path(name).name).write_bytes(data)
        known = {(f.subject, f.property, f.value, f.source.file) for f in state.added}
        fresh = [f for f in facts if (f.subject, f.property, f.value, f.source.file) not in known]
        state.add_file(name)
        state.add_facts(fresh)
        return rerun(before, profile, recorded=fresh, cached=cached, dropped=dropped)

    @app.get("/api/confidence")
    def confidence_status():
        return state.gate.status() | {"lessons": lessons.from_labels(state.gate.pool.rows(),
                                                                       allow_synthetic=state.gate.allow_synthetic)}

    @app.get("/api/review-queue/{profile_id}")
    def review_queue(profile_id: str, limit: int = 5):
        """Fails to review next, most useful for learning first."""
        result = state.result(profile_id)
        order = state.gate.review_order(result.findings, state.store(profile_id))
        return [{"rule_id": f.rule_id, "subject": f.subject, "label": f.label, "measured": f.measured,
                 "status": f.status, "why_now": why} for f, _score, why in order[:limit]]

    @app.get("/api/evidence")
    def evidence(file: str, locator: str = ""):
        """The part of an uploaded drawing that a value was read from, as a PNG."""
        path = state.data_dir / "uploads" / Path(file).name
        if not path.exists() or path.suffix.lower() != ".pdf":
            raise HTTPException(404, "The drawing for this value isn't stored.")
        png = ingest.crop(path.read_bytes(), locator)
        if png is None:
            raise HTTPException(404, "The location of this value isn't known.")
        return Response(content=png, media_type="image/png")

    @app.post("/api/feedback")
    def feedback(request: FeedbackRequest):
        """An engineer's answer: was this value read correctly? These are the only labels the model learns from."""
        if request.decision not in confidence.DECISIONS:
            raise HTTPException(422, f"Unknown decision: {request.decision!r}. Use accept, reject, or unsure.")
        if request.corrected_value is not None and not (request.corrected_value > 0 and is_length_unit(request.corrected_unit)):
            raise HTTPException(400, "A corrected value must be a positive length with a unit: mm, cm, m, in, or ft.")
        before = state.result(request.profile)
        finding = next((f for f in before.findings if f.rule_id == request.rule_id and f.subject == request.subject
                        and f.reviewable), None)
        if finding is None:
            answered = next((r for r in state.gate.pool.rows() if r.get("rule_id") == request.rule_id
                             and r.get("subject") == request.subject), None)
            if answered is not None:
                raise HTTPException(409, f"This finding was already answered ({answered['decision']}) and is no longer "
                                         "open for review. Undo that answer first to answer again.")
            raise HTTPException(404, f"No reviewable fail for rule {request.rule_id} and {request.subject}. "
                                     "Run the checks again: the finding may have changed.")
        try:
            row = confidence.make_label(finding, state.store(request.profile), request.decision,
                                        corrected_value=request.corrected_value,
                                        corrected_unit=request.corrected_unit, note=request.note,
                                        reviewer=request.reviewer)
        except ValueError as error:
            raise HTTPException(400, str(error)) from error
        recorded = []
        if row["corrected_value"] is not None and row["read"]:
            read = row["read"]
            recorded = [Fact(subject=read["subject"], property=read["property"], value=row["corrected_value"],
                             unit=row["corrected_unit"], confidence="high",
                             source=Source(kind=SourceKind.ENGINEER, file=read["file"],
                                           locator=f"review of {read['locator'] or read['file'] or 'the reading'}",
                                           quote=f"{request.reviewer or 'Engineer'}: was read as {read['value']} {read['unit']}"),
                             meta={"label_key": row["key"]})]
            state.drop_correction(row["key"])
            state.add_facts(recorded)
        retrained = state.gate.record(row)
        return rerun(before, request.profile, recorded=recorded, retrained=retrained, confidence=state.gate.status())

    @app.delete("/api/feedback")
    def undo_feedback(profile: str, key: str):
        """Take an answer back: the label leaves the pool, its correction leaves the facts, the model refits."""
        before = state.result(profile)
        if state.gate.undo(key) is None:
            raise HTTPException(404, "No saved answer has that key.")
        state.drop_correction(key)
        return rerun(before, profile, confidence=state.gate.status())

    @app.post("/api/measure")
    def measure(profile: str, request: MeasureRequest):
        if state.active_model is None:
            raise HTTPException(400, "There's no 3D model to measure.")
        if not is_length_unit(request.unit):
            raise HTTPException(400, f"Unknown unit {request.unit!r}. Use mm, cm, m, in, or ft.")
        if not request.value > 0:
            raise HTTPException(400, f"A measured length must be more than 0; got {request.value:g}.")
        before = state.result(profile)
        if not any(p == request.property for _, p, kind, _m in VOCABULARY if kind == "length"):
            raise HTTPException(400, f"Not a measurable property: {request.property}")
        locator = f"picked points ({request.a.x:.1f}, {request.a.y:.1f}, {request.a.z:.1f}) to ({request.b.x:.1f}, {request.b.y:.1f}, {request.b.z:.1f}) in"
        fact = Fact(subject=request.subject, property=request.property, value=request.value, unit=request.unit,
                    source=Source(kind=SourceKind.MEASUREMENT, locator=locator, quote=request.note),
                    confidence="medium", location=request.a)
        state.add_facts([fact])
        return rerun(before, profile, recorded=[fact])

    @app.get("/model/meta")
    def model_meta():
        return _ship_file(state, "model-meta.json", "application/json")

    @app.get("/model/bin")
    def model_bin():
        return _ship_file(state, "model.bin", "application/octet-stream")

    dist = ROOT / "frontend" / "dist"
    if dist.exists():
        app.mount("/", StaticFiles(directory=dist, html=True), name="frontend")
    return app


def _ship_file(state: AppState, name: str, media_type: str) -> FileResponse:
    if not state.has_view:
        raise HTTPException(404, "No 3D view is available for the current model.")
    return FileResponse(state.data_dir / name, media_type=media_type)


def _changes(before: RunResult, after: RunResult) -> list[str]:
    """What the rerun changed, from the tests rather than the AI."""
    old = {(f.rule_id, f.subject): f for f in before.findings}
    new = {(f.rule_id, f.subject): f for f in after.findings}
    changes = []
    for key, finding in new.items():
        previous = old.get(key)
        if previous is None or previous.status != finding.status or previous.measured != finding.measured:
            status = "can't tell" if finding.status == Status.CANT_TELL else finding.status.value
            changes.append(f"{finding.label}: {status}. {finding.measured}".strip())
    gone = [finding.label for key, finding in old.items() if key not in new]
    # When new results replace old ones, like one liferaft result becoming one per side, nothing was lost.
    if len(gone) > len(new.keys() - old.keys()):
        changes.append(f"No longer checked: {len(gone)} result(s).")
    if len(changes) > MAX_LISTED_CHANGES:
        changes = changes[:MAX_LISTED_CHANGES] + [f"And {len(changes) - MAX_LISTED_CHANGES} more."]
    return changes


app = create_app()
