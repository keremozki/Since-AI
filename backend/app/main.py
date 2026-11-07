"""Web API. Runs locally: nothing here is meant for public hosting."""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import tempfile
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import chat as chat_module
from . import confidence
from . import ingest, nwd
from .engine import report_text, run
from .llm import DEFAULT_CAP_USD, BudgetExceeded, Claude, Ledger, ModelRefused, load_env
from .models import Fact, Point, RunResult, Source, SourceKind, Status
from .parts import facts_from_parts, load_parts
from .profiles import PROFILES, demo_faults
from .rules import load_rules
from .store import FactStore
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
        self.last_model: str | None = None
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
        self.ledger = Ledger(data_dir / "usage.json", float(os.environ.get("BUDGET_USD", DEFAULT_CAP_USD)))
        self.claude = claude or Claude(self.ledger)
        self.history: list[dict] = []
        # Checking quotes means reading every rule text, so do it once at startup.
        self.rules = load_rules(rules_file, rule_texts_dir)
        self.gate = confidence.ConfidenceGate(
            data_dir / "confidence", tau=float(os.environ.get("CONFIDENCE_TAU", confidence.TAU)),
            allow_synthetic=os.environ.get("CONFIDENCE_ALLOW_SYNTHETIC") == "1")

    def _load_inputs(self) -> None:
        if self.inputs_file.exists():
            saved = json.loads(self.inputs_file.read_text(encoding="utf-8"))
            self.active_model, self.last_model = saved["active_model"], saved["last_model"]
            self.geometry_for, self.files = saved["geometry_for"], saved["files"]
            return
        # First run: the model set up on disk is active, and the viewer's geometry belongs to it.
        if (self.data_dir / DEFAULT_PARTS).exists():
            self.active_model = DEFAULT_PARTS
            if (self.data_dir / "model.bin").exists():
                self.geometry_for = _digest(load_parts(self.data_dir / DEFAULT_PARTS)[1])

    def _save_inputs(self) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.inputs_file.write_text(json.dumps({
            "active_model": self.active_model, "last_model": self.last_model,
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

    def remove_model(self) -> None:
        """The files stay on disk, so the model can be restored without reading it again."""
        if self.active_model is not None:
            self.last_model, self.active_model = self.active_model, None
            self._save_inputs()
            self._load_active_model()

    def restore_model(self) -> None:
        if self.active_model is None and self.last_model is not None:
            self.active_model = self.last_model
            self._save_inputs()
            self._load_active_model()

    def import_model(self, path: Path, name: str) -> None:
        """Replace the active model. Measurements belong to a model, so a different ship drops them."""
        parts = nwd.decode(path)
        if not parts:
            raise ValueError(f"No named parts could be read from {name}. The file may be a format we don't support.")
        digest = _digest(parts)
        previous = self.model_digest or self._last_model_digest()
        stored = Path("models") / f"{digest}.json"
        (self.data_dir / "models").mkdir(parents=True, exist_ok=True)
        (self.data_dir / stored).write_text(json.dumps({"source": name, "parts": parts}), encoding="utf-8")
        self.active_model, self.last_model = stored.as_posix(), None
        self._save_inputs()
        self._load_active_model()
        if digest != previous:
            self.remove_group(SourceKind.MEASUREMENT)

    def _last_model_digest(self) -> str:
        if self.last_model is None:
            return ""
        return _digest(load_parts(self.data_dir / self.last_model)[1])

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
                      "active": self.active_model is not None, "restorable": self.active_model is None and self.last_model is not None},
            "files": [{"name": name, "facts": sum(f.source.kind in FILE_KINDS and f.source.file == name for f in self.added)}
                      for name in self.file_names()],
            "measurements": count(SourceKind.MEASUREMENT) if self.active_model is not None else 0,
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
        # A measurement came from the model, so it can't count while the model is removed.
        added = [f for f in self.added if self.active_model is not None or f.source.kind != SourceKind.MEASUREMENT]
        return FactStore(self.model_facts + added + (demo_faults() if profile.use_demo_faults else []))


class ChatRequest(BaseModel):
    profile: str
    message: str


class FeedbackRequest(BaseModel):
    profile: str
    rule_id: str
    subject: str
    decision: str  # accept, reject, or correct
    corrected_value: float | None = None
    corrected_unit: str = ""
    note: str = ""


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
    app = FastAPI(title="Ship compliance checker")
    app.state.compliance = state

    def spend() -> dict:
        return {"spent_usd": round(state.ledger.spent, 4), "cap_usd": state.ledger.cap, "calls": state.ledger.calls}

    def rerun(before: RunResult, profile: str, **extra) -> dict:
        after = state.result(profile)
        return {"recorded": [], "changes": _changes(before, after), "result": after, "spend": spend(),
                "inputs": state.inputs(), **extra}

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

    @app.post("/api/inputs/model/restore")
    def restore_model(profile: str):
        before = state.result(profile)
        state.restore_model()
        return rerun(before, profile)

    @app.post("/api/inputs/model")
    def import_model(profile: str = Form(...), file: UploadFile = File(...)):
        name = file.filename or "model"
        if Path(name).suffix.lower() != ".nwd":
            raise HTTPException(400, f"Can't import {name}. The app reads Navisworks .nwd files only.")
        before = state.result(profile)
        state.data_dir.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(dir=state.data_dir, suffix=".nwd", delete=False) as temporary:
            shutil.copyfileobj(file.file, temporary)
        try:
            state.import_model(Path(temporary.name), name)
        except ValueError as error:
            raise HTTPException(400, str(error)) from error
        finally:
            Path(temporary.name).unlink(missing_ok=True)
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
        try:
            reply, facts, dropped = chat_module.respond(state.claude, before, state.history, request.message)
        except (BudgetExceeded, ModelRefused) as error:
            raise HTTPException(503, str(error)) from error
        state.history += [{"role": "engineer", "text": request.message}, {"role": "assistant", "text": reply}]
        state.add_facts(facts)
        return rerun(before, request.profile, reply=reply, recorded=facts, dropped=dropped)

    @app.post("/api/upload")
    async def upload(profile: str = Form(...), file: UploadFile = File(...), pages: str = Form("")):
        before = state.result(profile)
        name = file.filename or "upload"
        page_list = [int(p) for p in pages.replace(" ", "").split(",") if p.isdigit()] or None
        try:
            facts, cached, dropped = ingest.read_file(state.claude, state.data_dir / "extract-cache",
                                                      name, await file.read(), page_list)
        except (BudgetExceeded, ModelRefused, ingest.TooManyPages, ValueError) as error:
            raise HTTPException(400, str(error)) from error
        known = {(f.subject, f.property, f.value, f.source.file) for f in state.added}
        fresh = [f for f in facts if (f.subject, f.property, f.value, f.source.file) not in known]
        state.add_file(name)
        state.add_facts(fresh)
        return rerun(before, profile, recorded=fresh, cached=cached, dropped=dropped)

    @app.get("/api/confidence")
    def confidence_status():
        return state.gate.status()

    @app.post("/api/feedback")
    def feedback(request: FeedbackRequest):
        """An engineer's verdict on a fail. These are the only labels the model ever learns from."""
        before = state.result(request.profile)
        finding = next((f for f in before.findings if f.rule_id == request.rule_id and f.subject == request.subject
                        and f.reviewable), None)
        if finding is None:
            raise HTTPException(404, "No reviewable fail matches that rule and subject.")
        try:
            row = confidence.make_label(finding, state.store(request.profile), request.decision,
                                        corrected_value=request.corrected_value,
                                        corrected_unit=request.corrected_unit, note=request.note)
        except ValueError as error:
            raise HTTPException(400, str(error)) from error
        retrained = state.gate.record(row)
        return rerun(before, request.profile, retrained=retrained, confidence=state.gate.status())

    @app.post("/api/measure")
    def measure(profile: str, request: MeasureRequest):
        if state.active_model is None:
            raise HTTPException(400, "There's no 3D model to measure.")
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
    if gone:
        changes.append(f"No longer checked: {len(gone)} result(s).")
    if len(changes) > MAX_LISTED_CHANGES:
        changes = changes[:MAX_LISTED_CHANGES] + [f"And {len(changes) - MAX_LISTED_CHANGES} more."]
    return changes


app = create_app()
