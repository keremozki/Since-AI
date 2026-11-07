"""The fact dictionary: one YAML per fact in rules/facts/. Every check and reader asks for the same defined quantity.

Each entry gives the fact's meaning, the wordings found on real drawings (`labels`), the lookalikes a reader
must refuse (`not`), where it usually appears, and a plausibility range in SI units.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
FACTS_DIR = ROOT / "rules" / "facts"


@dataclass(frozen=True)
class FactDef:
    id: str
    subject: str  # regex for the subject, e.g. "ship" or r"door-number:[\w.-]+"
    property: str
    kind: str  # length, number, text, date
    meaning: str
    labels: tuple[str, ...] = ()
    lookalikes: tuple[str, ...] = ()
    usually_on: tuple[str, ...] = ()
    range: tuple[float, float] | None = None
    unit_hint: str = ""
    used_by: tuple[str, ...] = ()
    placeholders: tuple[str, ...] = field(default=())
    # For text facts: the only values a reader may accept (case and spacing ignored). Empty: any short text.
    values: tuple[str, ...] = field(default=())
    # Words a parenthesis beside the value may hold without changing its meaning, besides the fact's unit.
    qualifiers: tuple[str, ...] = field(default=())
    # False: the AI is never asked to point at this fact. The drawing reader finds it by code.
    ai_pointing: bool = True

    def matches(self, subject: str, prop: str) -> bool:
        return prop == self.property and re.fullmatch(self.subject, subject) is not None

    def in_range(self, value_si: float) -> bool:
        """value_si: metres for lengths (or mm when unit_hint is mm), plain number otherwise."""
        if self.range is None:
            return True
        low, high = self.range
        return low <= value_si <= high


def _normal(text: str) -> str:
    return re.sub(r"[^A-Z0-9]+", " ", text.upper()).strip()


@lru_cache(maxsize=4)
def load(directory: str = str(FACTS_DIR)) -> tuple[FactDef, ...]:
    defs = []
    for path in sorted(Path(directory).glob("*.yaml")):
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
        defs.append(FactDef(
            id=raw["id"], subject=raw["subject"], property=raw["property"], kind=raw["kind"], meaning=raw["meaning"],
            labels=tuple(raw.get("labels", [])), lookalikes=tuple(raw.get("not", [])),
            usually_on=tuple(raw.get("usually_on", [])),
            range=tuple(raw["range"]) if raw.get("range") else None,
            unit_hint=raw.get("unit_hint", ""), used_by=tuple(raw.get("used_by", [])),
            placeholders=tuple(raw.get("placeholders", [])), values=tuple(raw.get("values", [])),
            qualifiers=tuple(raw.get("qualifiers", [])), ai_pointing=raw.get("ai_pointing", True)))
    return tuple(defs)


def by_id(fact_id: str) -> FactDef | None:
    return next((d for d in load() if d.id == fact_id), None)


def for_fact(subject: str, prop: str) -> FactDef | None:
    return next((d for d in load() if d.matches(subject, prop)), None)


def label_matches(definition: FactDef, text: str) -> str | None:
    """The listed label found in the text, or None. A lookalike in the text wins over a weaker label match."""
    normal = f" {_normal(text)} "
    for bad in sorted(definition.lookalikes, key=len, reverse=True):
        if f" {_normal(bad)} " in normal:
            # e.g. "SIDE DECK LENGTH" must never be read as length overall.
            longest_good = max((l for l in definition.labels if f" {_normal(l)} " in normal), key=len, default="")
            if len(_normal(bad)) >= len(_normal(longest_good)):
                return None
    for label in sorted(definition.labels, key=len, reverse=True):
        if f" {_normal(label)} " in normal:
            return label
    return None


def allowed_value(definition: FactDef, value: str) -> str | None:
    """The listed value the text is, or None. Without a list, any text is allowed and comes back as is."""
    if not definition.values:
        return value
    normal = _normal(value)
    return next((v for v in definition.values if _normal(v) == normal), None)


def add_label(fact_id: str, label: str, approved_by: str, note: str = "", directory: Path = FACTS_DIR) -> FactDef:
    """Add an approved wording to a fact's labels in its YAML file, with who approved it, and reload the dictionary."""
    path = Path(directory) / f"{fact_id}.yaml"
    if not path.exists():
        raise ValueError(f"No fact {fact_id} in the dictionary.")
    definition = next(d for d in load(str(directory)) if d.id == fact_id)
    clean = " ".join(label.split()).upper()
    if not clean or any(ch.isdigit() for ch in clean):
        raise ValueError("A label is words, without numbers.")
    if any(_normal(clean) == _normal(existing) for existing in definition.labels):
        return definition
    if any(_normal(clean) == _normal(bad) for bad in definition.lookalikes):
        raise ValueError(f"'{clean}' is listed as a lookalike for {fact_id}, so it can't be a label.")
    lines = path.read_text(encoding="utf-8").splitlines()
    entry = f"- {clean}  # approved by {approved_by}" + (f": {note}" if note else "")
    if "labels:" in lines:
        at = lines.index("labels:") + 1
        while at < len(lines) and lines[at].startswith("- "):
            at += 1
        lines.insert(at, entry)
    else:
        lines += ["labels:", entry]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")  # text insert keeps the file's comments
    load.cache_clear()
    return next(d for d in load(str(directory)) if d.id == fact_id)


def is_placeholder(definition: FactDef, value: str) -> bool:
    return _normal(str(value)) in {_normal(p) for p in definition.placeholders}
