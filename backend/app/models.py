"""Core data types shared by the engine, the API, and the AI layer."""
from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field


class Status(str, Enum):
    PASS = "pass"
    FAIL = "fail"
    CONFLICT = "conflict"
    CANT_TELL = "cant_tell"


class SourceKind(str, Enum):
    MODEL_3D = "3d_model"
    MEASUREMENT = "3d_measurement"
    DOCUMENT = "document"
    IMAGE = "image"
    CHAT = "chat"
    DEMO_SEED = "demo_seed"


SOURCE_LABELS = {
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

    def key(self) -> tuple[str, str]:
        return self.subject, self.property


class ShipProfile(BaseModel):
    id: str
    name: str
    ship_type: str
    passengers: int | None = None
    flag: str = ""
    note: str = ""
    accessible_route_all_passage_doors: bool = False
    use_demo_faults: bool = False


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


class ScopeDecision(BaseModel):
    rule_id: str
    title: str
    area: str
    source: str
    applies: bool
    reason: str


class RunResult(BaseModel):
    profile: ShipProfile
    findings: list[Finding]
    scope: list[ScopeDecision]
    counts: dict[str, int]
    summary: str
    fact_count: int
