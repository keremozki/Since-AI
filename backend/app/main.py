"""Web API. Runs locally: nothing here is meant for public hosting."""
from __future__ import annotations

import json
import os
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import chat as chat_module
from . import ingest
from .engine import report_text, run
from .llm import DEFAULT_CAP_USD, BudgetExceeded, Claude, Ledger, ModelRefused, load_env
from .models import Fact, Point, RunResult, Source, SourceKind
from .parts import facts_from_parts, load_parts
from .profiles import PROFILES, demo_faults
from .rules import load_rules
from .store import FactStore
from .vocabulary import VOCABULARY

ROOT = Path(__file__).resolve().parents[2]


class AppState:
    def __init__(self, data_dir: Path, rules_file: Path, rule_texts_dir: Path, claude: Claude | None = None):
        self.data_dir = data_dir
        self.rules_file, self.rule_texts_dir = rules_file, rule_texts_dir
        self.added_file = data_dir / "added_facts.json"
        parts_file = data_dir / "parts.json"
        self.model_facts: list[Fact] = []
        if parts_file.exists():
            name, parts = load_parts(parts_file)
            self.model_facts = facts_from_parts(name, parts)
        self.added: list[Fact] = []
        if self.added_file.exists():
            self.added = [Fact(**raw) for raw in json.loads(self.added_file.read_text(encoding="utf-8"))]
        self.ledger = Ledger(data_dir / "usage.json", float(os.environ.get("BUDGET_USD", DEFAULT_CAP_USD)))
        self.claude = claude or Claude(self.ledger)
        self.history: list[dict] = []
        # Checking quotes means reading every rule text, so do it once at startup.
        self.rules = load_rules(rules_file, rule_texts_dir)

    def add_facts(self, facts: list[Fact]) -> None:
        self.added.extend(facts)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.added_file.write_text(json.dumps([f.model_dump(mode="json") for f in self.added]), encoding="utf-8")

    def reset(self) -> None:
        self.added, self.history = [], []
        self.added_file.unlink(missing_ok=True)

    def result(self, profile_id: str) -> RunResult:
        profile = PROFILES.get(profile_id)
        if profile is None:
            raise HTTPException(404, f"Unknown ship profile: {profile_id}")
        facts = self.model_facts + self.added + (demo_faults() if profile.use_demo_faults else [])
        return run(FactStore(facts), self.rules, profile)


class ChatRequest(BaseModel):
    profile: str
    message: str


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

    @app.post("/api/chat")
    def chat(request: ChatRequest):
        before = state.result(request.profile)
        try:
            reply, facts, dropped = chat_module.respond(state.claude, before, state.history, request.message)
        except (BudgetExceeded, ModelRefused) as error:
            raise HTTPException(503, str(error)) from error
        state.history += [{"role": "engineer", "text": request.message}, {"role": "assistant", "text": reply}]
        state.add_facts(facts)
        after = state.result(request.profile)
        return {"reply": reply, "recorded": facts, "dropped": dropped, "changes": _changes(before, after),
                "result": after, "spend": spend()}

    @app.post("/api/upload")
    async def upload(profile: str = Form(...), file: UploadFile = File(...), pages: str = Form("")):
        before = state.result(profile)
        page_list = [int(p) for p in pages.replace(" ", "").split(",") if p.isdigit()] or None
        try:
            facts, cached, dropped = ingest.read_file(state.claude, state.data_dir / "extract-cache",
                                                      file.filename or "upload", await file.read(), page_list)
        except (BudgetExceeded, ModelRefused, ingest.TooManyPages, ValueError) as error:
            raise HTTPException(400, str(error)) from error
        known = {(f.subject, f.property, f.value, f.source.file) for f in state.added}
        fresh = [f for f in facts if (f.subject, f.property, f.value, f.source.file) not in known]
        state.add_facts(fresh)
        after = state.result(profile)
        return {"recorded": fresh, "cached": cached, "dropped": dropped, "changes": _changes(before, after),
                "result": after, "spend": spend()}

    @app.post("/api/measure")
    def measure(profile: str, request: MeasureRequest):
        before = state.result(profile)
        if not any(p == request.property for _, p, kind, _m in VOCABULARY if kind == "length"):
            raise HTTPException(400, f"Not a measurable property: {request.property}")
        locator = f"picked points ({request.a.x:.1f}, {request.a.y:.1f}, {request.a.z:.1f}) to ({request.b.x:.1f}, {request.b.y:.1f}, {request.b.z:.1f}) in"
        fact = Fact(subject=request.subject, property=request.property, value=request.value, unit=request.unit,
                    source=Source(kind=SourceKind.MEASUREMENT, locator=locator, quote=request.note),
                    confidence="medium", location=request.a)
        state.add_facts([fact])
        after = state.result(profile)
        return {"recorded": [fact], "changes": _changes(before, after), "result": after, "spend": spend()}

    data_dir = state.data_dir

    @app.get("/model/meta")
    def model_meta():
        return _ship_file(data_dir / "model-meta.json", "application/json")

    @app.get("/model/bin")
    def model_bin():
        return _ship_file(data_dir / "model.bin", "application/octet-stream")

    dist = ROOT / "frontend" / "dist"
    if dist.exists():
        app.mount("/", StaticFiles(directory=dist, html=True), name="frontend")
    return app


def _ship_file(path: Path, media_type: str) -> FileResponse:
    if not path.exists():
        raise HTTPException(404, "Ship data isn't set up. See the README.")
    return FileResponse(path, media_type=media_type)


def _changes(before: RunResult, after: RunResult) -> list[str]:
    """What the rerun changed, from the tests rather than the AI."""
    old = {(f.rule_id, f.subject): f for f in before.findings}
    new = {(f.rule_id, f.subject): f for f in after.findings}
    changes = []
    for key, finding in new.items():
        previous = old.get(key)
        if previous is None or previous.status != finding.status or previous.measured != finding.measured:
            changes.append(f"{finding.label}: {finding.status.value.replace('_', ' ')}. {finding.measured}".strip())
    return changes


app = create_app()
