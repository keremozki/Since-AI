"""Web API. Runs locally: nothing here is meant for public hosting."""
from __future__ import annotations

import hashlib
import json
import math
import os
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse, PlainTextResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import chat as chat_module
from . import confidence
from . import dictionary, evidence, ingest, lessons, nwd, proof, revisions, sightline
from .reading import code_reader
from .reading import pipeline as reading_pipeline
from .checks import describe_fact
from .engine import report_text, run
from .ai_gateway import AIResponsePending, make_ai
from .llm import DEFAULT_CAP_USD, AIUnavailable, BudgetExceeded, Claude, Ledger, ModelRefused, env_float, load_env
from .models import Fact, Point, RunResult, Source, SourceKind, Status
from .parts import facts_from_parts, load_parts
from .basis.design_basis import compute_basis, missing_inputs
from .basis.scope import CARD_PROFILE_ID, basis_scope, card_profile
from .basis.shipcard import FIELDS as CARD_FIELDS
from .basis.shipcard import ShipCard, confirm as confirm_card_field, propose_card
from .basis.whatif import amendments_for, compare
from .profiles import PROFILES, demo_faults
from .rules import load_rules
from .store import FactStore
from .tiers import tier_of
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
        self.uploads_dir = data_dir / "uploads"  # kept so evidence can be shown and proof bundles carry the files
        self.card_file = data_dir / "shipcard.json"  # values an engineer confirmed on the ship card
        self.overlays_file = data_dir / "overlays.json"  # rules drawn on drawings, keyed "rule_id|subject"
        self.overlays: dict[str, dict] = (json.loads(self.overlays_file.read_text(encoding="utf-8"))
                                          if self.overlays_file.exists() else {})
        self.suggestions_file = data_dir / "label_suggestions.json"
        self.label_suggestions: list[dict] = (json.loads(self.suggestions_file.read_text(encoding="utf-8"))
                                              if self.suggestions_file.exists() else [])
        self.card_confirmed: list[dict] = (json.loads(self.card_file.read_text(encoding="utf-8"))
                                           if self.card_file.exists() else [])
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
        # Offline by default: nothing leaves the machine until AI_MODE=api or record is set (see .env.example).
        self.claude = claude or make_ai(data_dir, self.ledger)
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

    def add_facts(self, facts: list[Fact]) -> list[dict]:
        """Add facts. A newer revision of a drawing replaces the older one's facts; the notes say what changed."""
        before = list(self.added)
        self.added, facts, notes = revisions.supersede(self.added, facts)
        self.added.extend(facts)
        self._save_added()
        return revisions.revision_impact(before, notes, facts) + [n for n in notes if "question" in n]

    def drop_correction(self, label_key: str) -> None:
        """Remove the engineer correction made with one answer (when it is answered again or undone)."""
        kept = [f for f in self.added if not (f.source.kind == SourceKind.ENGINEER and f.meta.get("label_key") == label_key)]
        if len(kept) != len(self.added):
            self.added = kept
            self._save_added()

    def confirm_readings(self, ids: list[str], by: str) -> list[str]:
        """Confirm readings the engineer checked. Returns those newly confirmed, so an undo restores exactly them."""
        done = []
        for uid in ids:
            fact = self.find_added(uid)
            if fact is not None and not fact.confirmed_by:
                self.confirm_fact(uid, by)
                done.append(uid)
        return done

    def unconfirm_answer(self, key: str) -> None:
        """Take back the confirmations one saved answer made."""
        row = next((r for r in self.gate.pool.rows() if r["key"] == key), None)
        ids = set(row.get("confirmed_ids", [])) if row else set()
        if ids:
            self.added = [f.model_copy(update={"confirmed_by": ""}) if f.uid() in ids else f for f in self.added]
            self._save_added()

    def lessons_text(self) -> str:
        return lessons.as_text(lessons.from_labels(self.gate.pool.rows(), allow_synthetic=self.gate.allow_synthetic))

    def add_file(self, name: str) -> None:
        if name not in self.files:
            self.files.append(name)
            self._save_inputs()

    def add_read_facts(self, name: str, facts: list[Fact], replace: bool = False) -> tuple[list[Fact], list[dict]]:
        """Add what a file read gave. With replace, the file's earlier facts go, but an engineer's confirmation of
        the same reading (same value, same place, same quote) carries over."""
        if replace:
            kept = {f.uid(): f for f in self.added if f.source.file == name}
            self.added = [f for f in self.added if f.source.file != name]
            facts = [f.model_copy(update={"confirmed_by": kept[f.uid()].confirmed_by,
                                          "superseded_by": kept[f.uid()].superseded_by})
                     if f.uid() in kept else f for f in facts]
            corrections = [f for f in kept.values() if f.source.kind == SourceKind.CHAT]
            facts += corrections
        known = {f.uid() for f in self.added}
        fresh = [f for f in facts if f.uid() not in known]
        return fresh, self.add_facts(fresh)

    def add_label_suggestions(self, items: list[dict]) -> None:
        known = {(s["fact_id"], s["label"].upper()) for s in self.label_suggestions}
        self.label_suggestions += [i for i in items if (i["fact_id"], i["label"].upper()) not in known]
        self.save_label_suggestions()

    def save_label_suggestions(self) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.suggestions_file.write_text(json.dumps(self.label_suggestions, indent=1), encoding="utf-8")

    def store_upload(self, name: str, data: bytes) -> Path:
        path = self.uploads_dir / Path(name).name
        self.uploads_dir.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        return path

    def upload_bytes(self, name: str) -> bytes | None:
        path = self.uploads_dir / Path(name).name
        return path.read_bytes() if path.exists() else None

    def active_added(self) -> list[Fact]:
        """Added facts still in force: a newer revision or an engineer's correction replaces a fact."""
        return [f for f in self.added if not f.superseded_by]

    def find_added(self, uid: str) -> Fact | None:
        return next((f for f in self.added if f.uid() == uid), None)

    def confirm_fact(self, uid: str, by: str) -> Fact:
        fact = self.find_added(uid)
        if fact is None:
            raise HTTPException(404, f"No recorded fact with id {uid}. Facts from the 3D model are exact already.")
        confirmed = fact.model_copy(update={"confirmed_by": by})
        self.added = [confirmed if f is fact else f for f in self.added]
        self._save_added()
        return confirmed

    def correct_fact(self, uid: str, value: float | str, unit: str, by: str, note: str = "") -> Fact:
        """The engineer's value replaces the reading. The reading stays on record, marked as replaced."""
        fact = self.find_added(uid)
        if fact is None:
            raise HTTPException(404, f"No recorded fact with id {uid}.")
        value, unit = checked_value(fact.subject, fact.property, value, unit)
        was = f"{fact.value:g}" if isinstance(fact.value, float) else str(fact.value)
        quote = f"Corrected by {by}: was {was} {fact.unit}".strip() + (f". {note}" if note else "")
        corrected = Fact(subject=fact.subject, property=fact.property, value=value, unit=unit,
                         source=Source(kind=SourceKind.CHAT, file=fact.source.file, locator=fact.source.locator, quote=quote),
                         evidence=fact.evidence, confirmed_by=by, location=fact.location)
        self.added = [f.model_copy(update={"superseded_by": f"correction by {by}"}) if f is fact else f for f in self.added]
        self.added.append(corrected)
        self._save_added()
        return corrected

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

        def file_entry(name: str) -> dict:
            read = [f for f in self.added if f.source.kind in FILE_KINDS and f.source.file == name]
            return {"name": name, "facts": len(read), "read": [describe_fact(f) for f in read]}

        return {
            "model": {"name": self.model_name, "parts": self.model_parts, "has_view": self.has_view,
                      "active": self.active_model is not None},
            "files": [file_entry(name) for name in self.file_names()],
            "measurements": count(SourceKind.MEASUREMENT),
            "chat": count(SourceKind.CHAT),
        }

    def reset(self) -> None:
        self.added, self.history, self.files = [], [], []
        self.added_file.unlink(missing_ok=True)
        self._save_inputs()

    def ship_card(self, extra: list[dict] | None = None) -> ShipCard:
        """Proposed from the facts, then every confirmed value applied on top. `extra` is a what-if on top of that."""
        card = propose_card(self.model_facts + self.active_added())
        for item in self.card_confirmed + (extra or []):
            card = confirm_card_field(card, item["field"], item["value"], item.get("unit", ""), item["by"])
        return card

    def confirm_card(self, field: str, value, unit: str, by: str) -> ShipCard:
        card = confirm_card_field(self.ship_card(), field, value, unit, by)  # raises ValueError on a bad value
        self.card_confirmed = [c for c in self.card_confirmed if c["field"] != field] + [
            {"field": field, "value": value, "unit": unit, "by": by}]
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.card_file.write_text(json.dumps(self.card_confirmed, default=str), encoding="utf-8")
        return card

    def profile_and_scope(self, profile_id: str, card: ShipCard | None = None):
        if profile_id == CARD_PROFILE_ID:
            card = card or self.ship_card()
            return card_profile(card), basis_scope(card)
        profile = PROFILES.get(profile_id)
        if profile is None:
            raise HTTPException(404, f"Unknown ship profile: {profile_id}")
        return profile, None

    def result(self, profile_id: str, card: ShipCard | None = None) -> RunResult:
        profile, scope_fn = self.profile_and_scope(profile_id, card)
        result = run(FactStore(self.run_facts(profile)), self.rules, profile, scope_fn=scope_fn, gate=self.gate)
        answers = {row["key"]: row for row in self.gate.pool.rows()}
        for finding in result.findings:
            overlay = self.overlays.get(f"{finding.rule_id}|{finding.subject}")
            if overlay is not None:
                finding.overlay = overlay
            answer = answers.get(confidence.review_key(finding))
            if answer is not None:
                finding.answer, finding.answer_key = answer["decision"], answer["key"]
        return result

    def store(self, profile_id: str) -> FactStore:
        profile, _scope = self.profile_and_scope(profile_id)
        return FactStore(self.run_facts(profile))

    def derive_sightline(self, request: "sightline.SightlineRequest") -> list[Fact]:
        """Bridge facts measured on a calibrated profile from the engineer's three points. Replaces earlier ones."""
        from .reading.calibrate import calibrate_page
        from .reading.pagemap import build_document_map

        data = self.upload_bytes(request.file)
        if data is None:
            raise HTTPException(404, f"{request.file} isn't stored. Upload it first.")
        dm = build_document_map(data, request.file, cache_dir=self.data_dir / "page-maps")
        facts = FactStore(self.model_facts + self.active_added())
        spacing = facts.get("ship", "frame_spacing")
        spacing = next((f for f in spacing if tier_of(f).value in ("A", "B")), None)
        from .units import to_mm as length_mm
        cal = calibrate_page(dm, request.page, data, length_mm(float(spacing.value), spacing.unit) if spacing else None)
        if request.draught_m is not None:
            draught, where = request.draught_m, f"stated by {request.by.strip()}"
        else:
            stated = next((f for f in facts.get("ship", "design_draft") if tier_of(f).value in ("A", "B")), None)
            if stated is None:
                raise HTTPException(400, "No confirmed design draught. State the draught for this check (draught_m).")
            draught, where = length_mm(float(stated.value), stated.unit) / 1000.0, stated.source.describe()
        try:
            derived, overlay = sightline.derive(request, cal, draught, where, dm.title_block.drawing_no, dm.title_block.revision)
        except sightline.SightlineError as error:
            raise HTTPException(400, str(error)) from error
        self.added = [f for f in self.added if not (f.subject == "bridge" and "picked by" in f.source.locator)]
        self.add_facts(derived)
        self.overlays["SOLAS-V-22|bridge"] = overlay
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.overlays_file.write_text(json.dumps(self.overlays), encoding="utf-8")
        return derived

    def run_facts(self, profile) -> list[Fact]:
        return self.model_facts + self.active_added() + (demo_faults() if profile.use_demo_faults else [])

    def proof_bundle(self, profile_id: str) -> bytes:
        profile, _scope = self.profile_and_scope(profile_id)
        result = self.result(profile_id)
        # Every fact the run saw, not only those a finding names: cross-checks and scope depend on the rest too.
        facts = self.run_facts(profile)
        names = {f.source.file for f in facts if f.source.file} | {f.evidence.file for f in facts if f.evidence and f.evidence.file}
        files = {name: data for name in sorted(names) if (data := self.upload_bytes(name)) is not None}
        return proof.build_bundle(result, facts, self.rules, files, sorted(getattr(self.claude, "used", set())), ROOT)


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
class CardConfirmRequest(BaseModel):
    field: str
    value: float | str
    unit: str = ""
    by: str


class WhatIfRequest(BaseModel):
    """Card values to try, not saved: {field: value} or {field: {"value": v, "unit": u}}. A sister hull is a what-if
    on its dates (keel, contract, delivery)."""

    changes: dict[str, float | str | dict]


class StateRequest(BaseModel):
    """An engineer answers a question with a value, without the AI. It must be a fact the dictionary defines."""

    subject: str
    property: str
    value: float | str
    unit: str = ""
    by: str
    note: str = ""


class LabelApproval(BaseModel):
    fact_id: str
    label: str
    by: str


class ConfirmRequest(BaseModel):
    """An engineer confirms a reading as it is, or corrects it. Either way the value becomes tier A."""

    id: str
    by: str
    value: float | str | None = None  # set to correct the value
    unit: str = ""
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
    app = FastAPI(title="Dynamis SCC")
    app.state.compliance = state

    def spend() -> dict:
        return {"spent_usd": round(state.ledger.spent, 4), "cap_usd": state.ledger.cap, "calls": state.ledger.calls,
                "ai_mode": getattr(state.claude, "mode", "api")}

    def rerun(before: RunResult, profile: str, recorded: list[Fact] | None = None, **extra) -> dict:
        after = state.result(profile)
        return {"recorded": recorded or [], "recorded_text": [describe_fact(f) for f in recorded or []],
                "changes": _changes(before, after), "result": after, "spend": spend(), "inputs": state.inputs(), **extra}

    @app.get("/api/profiles")
    def profiles():
        return [*PROFILES.values(), card_profile(state.ship_card())]

    @app.get("/api/shipcard")
    def ship_card():
        card = state.ship_card()
        basis = compute_basis(card)
        return {"card": card, "fields": {k: {"label": f.label, "meaning": f.meaning, "kind": f.kind, "choices": list(f.choices)}
                                         for k, f in CARD_FIELDS.items()},
                "missing": missing_inputs(basis)}

    @app.post("/api/shipcard/confirm")
    def confirm_ship_card(request: CardConfirmRequest):
        before = state.result(CARD_PROFILE_ID)
        try:
            card = state.confirm_card(request.field, request.value, request.unit, request.by.strip())
        except ValueError as error:
            raise HTTPException(400, str(error)) from error
        return {**rerun(before, CARD_PROFILE_ID), "card": card}

    @app.get("/api/basis")
    def design_basis():
        """Which rules and editions apply to this hull, why, what each requires as numbers, and what's missing."""
        card = state.ship_card()
        items = compute_basis(card)
        return {"card": card, "items": items, "missing": missing_inputs(items), "amendments": amendments_for(card)}

    @app.post("/api/whatif")
    def what_if(request: WhatIfRequest):
        """Try card values without saving them: which rules switch on or off, which requirements move, which
        results change. Code decides all of it, exactly as for the real card."""
        extra = []
        for field, raw in request.changes.items():
            value, unit = (raw.get("value"), str(raw.get("unit", ""))) if isinstance(raw, dict) else (raw, "")
            if value is None:
                raise HTTPException(400, f"Give a value for {field}.")
            extra.append({"field": field, "value": value, "unit": unit, "by": "what-if"})
        try:
            card_a, card_b = state.ship_card(), state.ship_card(extra)
        except (ValueError, TypeError) as error:
            raise HTTPException(400, str(error)) from error
        before, after = state.result(CARD_PROFILE_ID, card_a), state.result(CARD_PROFILE_ID, card_b)
        return {"rule_changes": compare(card_a, card_b), "result_changes": _changes(before, after),
                "before": before.counts, "after": after.counts, "card": card_b}

    @app.get("/api/run/{profile_id}")
    def run_checks(profile_id: str):
        return {"result": state.result(profile_id), "spend": spend()}

    @app.get("/api/report/{profile_id}", response_class=PlainTextResponse)
    def report(profile_id: str):
        return report_text(state.result(profile_id))

    @app.get("/api/ai/status")
    def ai_status():
        status = state.claude.status() if hasattr(state.claude, "status") else {"mode": getattr(state.claude, "mode", "api")}
        return {**status, "spend": spend()}

    @app.get("/api/facts")
    def added_facts():
        # The tier code decides goes last, so the stored field (often empty) can't hide it.
        return [{**f.model_dump(mode="json"), "id": f.uid(), "tier": tier_of(f).value} for f in state.added]

    @app.post("/api/facts/confirm")
    def confirm_fact(profile: str, request: ConfirmRequest):
        """The engineer's word is the final say: a confirmed or corrected value can back a pass or a fail."""
        if not request.by.strip():
            raise HTTPException(400, "Say who confirms the value.")
        before = state.result(profile)
        if request.value is None:
            fact = state.confirm_fact(request.id, request.by.strip())
        else:
            fact = state.correct_fact(request.id, request.value, request.unit, request.by.strip(), request.note)
        return rerun(before, profile, recorded=[fact])

    @app.post("/api/facts/state")
    def state_fact(profile: str, request: StateRequest):
        """Answer a "can't tell" question directly. The value is the engineer's, so it is tier A, with their name."""
        if not request.by.strip():
            raise HTTPException(400, "Say who states the value.")
        value, _unit = checked_value(request.subject, request.property, request.value, request.unit)
        before = state.result(profile)
        quote = f"Stated by {request.by.strip()}" + (f": {request.note}" if request.note else "")
        fact = Fact(subject=request.subject, property=request.property, value=value, unit=request.unit.strip().lower(),
                    source=Source(kind=SourceKind.CHAT, locator="stated in the app", quote=quote),
                    confirmed_by=request.by.strip())
        state.add_facts([fact])
        return rerun(before, profile, recorded=[fact])

    @app.get("/api/proof/{profile_id}")
    def proof_bundle(profile_id: str):
        data = state.proof_bundle(profile_id)
        import io as _io
        import zipfile as _zipfile
        digest = proof.sha256(_zipfile.ZipFile(_io.BytesIO(data)).read("bundle.json"))
        # The digest travels apart from the zip: a verifier compares it, so a bundle rebuilt from scratch shows.
        return Response(data, media_type="application/zip",
                        headers={"Content-Disposition": f'attachment; filename="proof-{profile_id}.zip"',
                                 "X-Bundle-SHA256": digest})

    @app.post("/api/sightline")
    def sightline_from_drawing(profile: str, request: sightline.SightlineRequest):
        """SOLAS V/22.1.1 measured on a calibrated profile drawing from three points the engineer picks."""
        before = state.result(profile)
        derived = state.derive_sightline(request)
        return rerun(before, profile, recorded=derived)

    @app.get("/api/sightline.png")
    def sightline_png():
        overlay = state.overlays.get("SOLAS-V-22|bridge")
        data = state.upload_bytes(overlay["file"]) if overlay else None
        if overlay is None or data is None:
            raise HTTPException(404, "No sight line has been measured yet.")
        return Response(sightline.overlay_png(data, overlay), media_type="image/png")

    @app.get("/api/evidence/crop")
    def evidence_crop(file: str, page: int, x0: float, y0: float, x1: float, y1: float, margin: float = 40.0):
        """The cited part of the page, with the evidence box drawn on it, so a reading can be checked at a glance."""
        data = state.upload_bytes(file)
        if data is None:
            raise HTTPException(404, f"{file} isn't stored, so its evidence can't be shown.")
        return Response(evidence.crop_png(data, file, page, (x0, y0, x1, y1), margin), media_type="image/png")

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
        except AIResponsePending as pending:
            raise HTTPException(503, {"message": str(pending), "pending": pending.request_id}) from pending
        except (BudgetExceeded, ModelRefused, AIUnavailable) as error:
            raise HTTPException(503, str(error)) from error
        state.history += [{"role": "engineer", "text": request.message}, {"role": "assistant", "text": reply}]
        state.add_facts(facts)
        return rerun(before, request.profile, reply=reply, recorded=facts, dropped=dropped)

    @app.post("/api/upload")
    async def upload(profile: str = Form(...), file: UploadFile = File(...), pages: str = Form("")):
        """Read a file into facts. Drawings, schedules and IFC models go through the reading pipeline: code reads,
        the AI only points and transcribes, and every value carries its evidence and tier."""
        before = state.result(profile)
        name = Path(file.filename or "upload").name
        data = await file.read(ingest.MAX_UPLOAD_BYTES + 1)  # never hold more than the limit in memory
        try:
            page_list = ingest.parse_pages(pages)
            ingest.check_file(name, data, page_list)
        except ingest.FileTooLarge as error:
            raise HTTPException(413, str(error)) from error
        except ValueError as error:
            raise HTTPException(400, str(error)) from error
        again = name in state.file_names()
        if reading_pipeline.can_read(name):
            try:
                read = await run_in_threadpool(reading_pipeline.read_upload, state.claude, name, data,
                                               state.data_dir / "page-maps", page_list, lessons=state.lessons_text())
            except ValueError as error:
                raise HTTPException(400, str(error)) from error
            if Path(name).suffix.lower() == ".pdf":
                # The second code reader finds what the first doesn't: door tags, corridors, and ramps.
                read.facts += await run_in_threadpool(code_reader.extra_facts, name, data, page_list, read.facts)
            if read.facts or Path(name).suffix.lower() not in ingest.WHOLE_PAGE_AI_TYPES:
                state.store_upload(name, data)
                state.add_file(name)
                fresh, notes = state.add_read_facts(name, read.facts, replace=again)
                state.add_label_suggestions(read.label_suggestions)
                return rerun(before, profile, recorded=fresh, reading=read.summary(), revisions=notes)
            # Code found nothing, like on a clean scan: the AI reads the whole page. Its values stay at one reading (tier C).
        try:
            facts, cached, dropped = ingest.read_file(state.claude, state.data_dir / "extract-cache",
                                                      name, data, page_list, lessons=state.lessons_text())
        except ingest.FileTooLarge as error:
            raise HTTPException(413, str(error)) from error
        except AIResponsePending as pending:
            raise HTTPException(503, {"message": str(pending), "pending": pending.request_id}) from pending
        except (AIUnavailable, BudgetExceeded) as error:
            # Missing key, rejected key, no answer after a retry, or the cap: the rest of the app keeps working.
            raise HTTPException(503, str(error)) from error
        except (ModelRefused, ingest.TooManyPages, ValueError) as error:
            raise HTTPException(400, str(error)) from error
        state.store_upload(name, data)
        state.add_file(name)
        fresh, notes = state.add_read_facts(name, facts)
        return rerun(before, profile, recorded=fresh, cached=cached, dropped=dropped, revisions=notes)

    @app.post("/api/inputs/reread")
    def reread(profile: str, name: str):
        """Read a stored file again, for example after offline AI answers arrived. Confirmations are kept."""
        data = state.upload_bytes(name)
        if data is None or not reading_pipeline.can_read(name):
            raise HTTPException(404, f"{name} isn't stored as a readable file.")
        before = state.result(profile)
        read = reading_pipeline.read_upload(state.claude, name, data, state.data_dir / "page-maps", lessons=state.lessons_text())
        if Path(name).suffix.lower() == ".pdf":
            read.facts += code_reader.extra_facts(name, data, None, read.facts)
        fresh, notes = state.add_read_facts(name, read.facts, replace=True)
        state.add_label_suggestions(read.label_suggestions)
        return rerun(before, profile, recorded=fresh, reading=read.summary(), revisions=notes)

    @app.get("/api/dictionary/suggestions")
    def label_suggestions():
        """Wordings the AI pointed at that the fact dictionary doesn't list. Never used until an engineer approves one."""
        return state.label_suggestions

    @app.post("/api/dictionary/approve")
    def approve_label(request: LabelApproval):
        """Teach the reader a label. From then on code reads it itself, on every document; the AI isn't needed for it."""
        if not request.by.strip():
            raise HTTPException(400, "Say who approves the label.")
        source = next((s for s in state.label_suggestions if s["fact_id"] == request.fact_id
                       and s["label"].upper() == request.label.upper()), None)
        note = f"suggested by the AI pointer on {source['file']} page {source['page']}" if source else ""
        try:
            definition = dictionary.add_label(request.fact_id, request.label, request.by.strip(), note)
        except ValueError as error:
            raise HTTPException(400, str(error)) from error
        state.label_suggestions = [s for s in state.label_suggestions
                                   if not (s["fact_id"] == request.fact_id and s["label"].upper() == request.label.upper())]
        state.save_label_suggestions()
        return {"fact_id": definition.id, "labels": list(definition.labels),
                "next": "Read the files again (POST /api/inputs/reread) so code reads the new label."}

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
    def evidence_near(file: str, locator: str = ""):
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
        weak = [i for i in finding.inputs if i.get("tier") in ("C", "D") and i.get("id")]
        # Only a fail teaches the model. Other answers, like one on a held-back pass, are kept but never trained on.
        trainable = (finding.original_status == Status.FAIL and finding.evidence is not None
                     and bool(finding.evidence.facts) and finding.evidence.limit != 0)
        try:
            if trainable:
                row = confidence.make_label(finding, state.store(request.profile), request.decision,
                                            corrected_value=request.corrected_value,
                                            corrected_unit=request.corrected_unit, note=request.note,
                                            reviewer=request.reviewer)
            else:
                row = confidence.plain_answer(finding, request.decision, _read_of(weak),
                                              corrected_value=request.corrected_value,
                                              corrected_unit=request.corrected_unit, note=request.note,
                                              reviewer=request.reviewer)
        except ValueError as error:
            raise HTTPException(400, str(error)) from error
        by = request.reviewer.strip() or "Engineer"
        state.unconfirm_answer(row["key"])  # a second answer replaces the first
        row["confirmed_ids"] = state.confirm_readings([i["id"] for i in weak], by) if request.decision == "accept" else []
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
        state.unconfirm_answer(key)
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
        # The value must come from the two points: their straight, vertical, or horizontal distance.
        dx, dy, dz = request.a.x - request.b.x, request.a.y - request.b.y, request.a.z - request.b.z
        picked = [math.sqrt(dx * dx + dy * dy + dz * dz) * 25.4, abs(dz) * 25.4, math.hypot(dx, dy) * 25.4]
        from .units import to_mm as length_mm
        if not math.isfinite(request.value) or all(abs(length_mm(request.value, request.unit) - mm) > max(5.0, 0.01 * mm) for mm in picked):
            raise HTTPException(400, f"The value doesn't match the picked points: they are {picked[0]:.0f} mm apart.")
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


def _read_of(weak: list[dict]) -> dict | None:
    """What was read, in the shape a saved answer keeps, from a finding's first unconfirmed input."""
    if not weak:
        return None
    first = weak[0]
    return {"subject": first["subject"], "property": first["property"], "value": first["value"], "unit": first["unit"],
            "quote": first.get("quote", ""), "file": first.get("file", ""), "locator": first.get("locator", ""), "reader": ""}


def checked_value(subject: str, prop: str, value, unit: str):
    """A value an engineer gives, checked before it is saved: a defined fact, a finite number, a length unit."""
    definition = dictionary.for_fact(subject, prop)
    if definition is None:
        raise HTTPException(400, f"{subject} {prop} isn't a fact the checks know.")
    if definition.kind in ("length", "number"):
        try:
            value = float(value)
        except (TypeError, ValueError) as error:
            raise HTTPException(400, f"{prop.replace('_', ' ')} needs a number, not {value!r}.") from error
        if not math.isfinite(value) or value < 0:
            raise HTTPException(400, f"{prop.replace('_', ' ')} must be a finite number, zero or more.")
        if definition.kind == "length" and not is_length_unit(unit):
            raise HTTPException(400, "Give a length unit: mm, cm, m, in or ft.")
    return value, unit.strip().lower()


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
