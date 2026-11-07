"""Core data types shared by the engine, the API, and the AI layer."""
from __future__ import annotations

import hashlib
import json
from enum import Enum

from pydantic import BaseModel, Field


class Status(str, Enum):
    PASS = "pass"
    FAIL = "fail"
    CONFLICT = "conflict"
    CANT_TELL = "cant_tell"
    # A rule written in words: the AI's opinion waits for an engineer. Never a pass.
    NEEDS_REVIEW = "needs_review"
    # The rule doesn't cover this ship or item, and the finding says why.
    NOT_APPLICABLE = "not_applicable"


class Tier(str, Enum):
    """How far a value can be trusted. Only A and B can back a pass or a fail.

    A: exact source (model attribute, spreadsheet cell, IFC property, verified PDF text layer,
       or a value an engineer stated or confirmed).
    B: two independent readings agree, the layout ties label to value, and no other file disagrees.
    C: one reading only (one OCR or model reading, or a measurement from one calibration).
    D: unusable (conflicting, placeholder, marked TBD, or unreadable).
    """

    A = "A"
    B = "B"
    C = "C"
    D = "D"


class Box(BaseModel):
    """A highlight box on a PDF page, in points, in the page's displayed (rotated) coordinates."""

    page: int
    x0: float
    y0: float
    x1: float
    y1: float


class Reading(BaseModel):
    """One independent reading of a value. Two readings by the same method never count as two."""

    method: str  # text_layer, ocr, ai_transcription, glyph_shapes, geometry, cell, ifc_property, model_attribute, engineer
    text: str = ""
    value: float | str | None = None
    unit: str = ""
    confidence: float | None = None


class Evidence(BaseModel):
    """Where a fact was read, so an engineer can verify it at a glance."""

    file: str = ""
    doc_id: str = ""
    revision: str = ""
    page: int | None = None
    box: Box | None = None
    quote: str = ""
    element_ids: list[str] = Field(default_factory=list)
    readings: list[Reading] = Field(default_factory=list)
    checks: list[str] = Field(default_factory=list)  # verification steps that passed, in plain words
    problems: list[str] = Field(default_factory=list)  # verification steps that failed or traps found


class SourceKind(str, Enum):
    MODEL_3D = "3d_model"
    MEASUREMENT = "3d_measurement"
    DOCUMENT = "document"
    IMAGE = "image"
    CHAT = "chat"
    DEMO_SEED = "demo_seed"
    # A value an engineer typed while marking a reading as wrong. It replaces that reading.
    ENGINEER = "engineer_review"


SOURCE_LABELS = {
    SourceKind.ENGINEER: "Engineer correction",
    SourceKind.MODEL_3D: "3D model",
    SourceKind.MEASUREMENT: "3D measurement",
    SourceKind.DOCUMENT: "Document",
    SourceKind.IMAGE: "Image",
    SourceKind.CHAT: "Engineer in chat",
    SourceKind.DEMO_SEED: "Seeded demo fault",
}


class Source(BaseModel):
    kind: SourceKind
    file: str = ""
    locator: str = ""
    quote: str = ""

    def describe(self) -> str:
        details = ", ".join(part for part in (self.file, self.locator) if part)
        label = SOURCE_LABELS[self.kind]
        return f"{label}: {details}" if details else label


class Point(BaseModel):
    """Position in inches, in the 3D model's own axes."""

    x: float
    y: float
    z: float


class Fact(BaseModel):
    subject: str
    property: str
    value: float | str
    unit: str = ""
    source: Source
    confidence: str = "high"
    location: Point | None = None
    # How the value was read (reader, pairing distance, OCR, ...). Inputs for the confidence model.
    meta: dict = Field(default_factory=dict)
    # Reading design additions. All optional, so older saved facts still load.
    evidence: Evidence | None = None
    tier: Tier | None = None  # None: decided by app.tiers from the source and evidence
    derived_from: list[str] = Field(default_factory=list)  # "subject.property" of the inputs, for derived values
    derivation: str = ""  # the calculation, in plain words, when the value is derived by code
    confirmed_by: str = ""  # engineer who confirmed or corrected the reading
    superseded_by: str = ""  # newer revision of the same document that replaced this fact

    def key(self) -> tuple[str, str]:
        return self.subject, self.property

    def uid(self) -> str:
        """A stable id for this exact statement: the same value from the same place always gets the same id."""
        raw = [self.subject, self.property, self.value, self.unit, self.source.kind.value, self.source.file,
               self.source.locator, self.source.quote]
        return hashlib.sha256(json.dumps(raw, ensure_ascii=False).encode()).hexdigest()[:12]


class ShipProfile(BaseModel):
    id: str
    name: str
    ship_type: str
    passengers: int | None = None
    flag: str = ""
    note: str = ""
    accessible_route_all_passage_doors: bool = False
    use_demo_faults: bool = False
    # Assumptions the team approved for this ship, by name. A check may use one only if it is listed here,
    # and every result that relies on one says so. "openings_not_deep": door openings aren't over 24 in deep.
    approved_assumptions: list[str] = Field(default_factory=list)


class RuleScope(BaseModel):
    ship_types: list[str] = Field(default_factory=list)
    min_passengers: int | None = None
    flags: list[str] = Field(default_factory=list)
    reason: str = ""


class Rule(BaseModel):
    id: str
    title: str
    area: str
    source: str
    check: str
    params: dict = Field(default_factory=dict)
    scope: RuleScope = Field(default_factory=RuleScope)
    quote: str = ""
    verified: bool = False
    # The official text we couldn't get, named in the label on this rule's results.
    missing_text: str = ""
    # Applicability by ship card fields and dates, evaluated by app.basis. Empty: only `scope` applies.
    applies_if: list[dict] = Field(default_factory=list)
    edition: str = ""
    fix: str = ""  # suggested fix shown on a fail

    def unconfirmed_label(self) -> str:
        if self.verified:
            return ""
        if self.missing_text:
            return f"Limit not yet confirmed: {self.missing_text} not retrieved"
        return "Limit not yet confirmed against the rule text"


class CheckBasis(BaseModel):
    """What a numeric check compared, kept for the confidence model. Never sent to the browser."""

    measured: float
    limit: float
    limit_unit: str = ""
    facts: list[Fact] = Field(default_factory=list)


class Finding(BaseModel):
    rule_id: str
    rule_title: str
    area: str
    rule_source: str
    status: Status
    subject: str
    label: str
    where: str = ""
    measured: str = ""
    required: str = ""
    gap: str = ""
    why: str = ""
    sources: list[str] = Field(default_factory=list)
    confidence: str = "high"
    question: str = ""
    assumptions: list[str] = Field(default_factory=list)
    location: Point | None = None
    provisional: bool = False
    unconfirmed_label: str = ""
    # What a numeric check compared, kept for the confidence model. Never sent to the browser.
    evidence: CheckBasis | None = Field(default=None, exclude=True)
    # Set by the confidence gate. It can only turn a fail into can't tell, never the other way.
    original_status: Status | None = None
    p_real: float | None = None
    gate_note: str = ""
    # An engineer can answer "was this read correctly?". True for fails, and for anything held back by a weak reading.
    reviewable: bool = False
    answer: str = ""  # the engineer's saved answer to that question, when there is one
    answer_key: str = ""  # what to send to take the answer back
    # Where the reviewed value was read, so the engineer can check it against the drawing.
    read_quote: str = ""
    read_file: str = ""
    read_locator: str = ""
    # Reading design additions.
    inputs: list[dict] = Field(default_factory=list)  # each: subject, property, value, unit, tier, source, evidence
    overlay: dict | None = None  # the rule drawn on the drawing: file, page, shapes, labels
    fix: str = ""
    gate: str = ""  # why a pass or fail was held back to "can't tell" (inputs below tier B)
    evidence_boxes: list[Box] = Field(default_factory=list)


class ScopeDecision(BaseModel):
    rule_id: str
    title: str
    area: str
    source: str
    applies: bool
    reason: str
    # From the ship card's design basis: "applies", "not_applicable", or "cant_tell". A rule whose applicability
    # can't be told still runs, and a separate "can't tell" result asks the questions that would settle it.
    status: str = ""
    questions: list[str] = Field(default_factory=list)
    clause: str = ""
    edition: str = ""


class RunResult(BaseModel):
    profile: ShipProfile
    findings: list[Finding]
    scope: list[ScopeDecision]
    counts: dict[str, int]
    summary: str
    fact_count: int
