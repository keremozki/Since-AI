"""A tiny safe condition evaluator for applicability. YAML in, three-valued answer out, and no eval().

A condition is a mapping such as
    {field: length_overall_m, op: ">=", value: 55, clause: "SOLAS V/2.4, V/22.1", ask: "What is the ship's length overall?"}
and groups nest: {any_of: [...]} and {all_of: [...]}. A plain list means all_of.

Each condition is true, false, or unknown (the card lacks the input). A rule applies only when every condition is true,
is not applicable only when one is definitely false, and is "can't tell" otherwise: a missing input is never assumed.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Literal

from pydantic import BaseModel, Field

from .shipcard import FIELDS, ShipCard, cap, format_value, label_for, pretty

OPS = {"==", "!=", "<", "<=", ">", ">=", "in", "not_in", "exists", "on_or_after", "before"}
_ALIASES = {"constructed": "keel_date"}  # SOLAS "constructed" is the keel-laying date or a similar stage


class ConditionError(ValueError):
    """The condition data itself is wrong (a typo in the YAML), which must never pass quietly."""


class Decision(BaseModel):
    status: Literal["applies", "not_applicable", "cant_tell"]
    reasons: list[str] = Field(default_factory=list)
    missing: list[str] = Field(default_factory=list)  # card fields (or other inputs) that would settle it
    questions: list[str] = Field(default_factory=list)  # one per missing item, same order
    failed: dict | None = None  # the condition that made it not applicable
    provisional: list[str] = Field(default_factory=list)  # decisive values that are only one reading
    used: list[str] = Field(default_factory=list)  # card fields consulted


@dataclass
class _Node:
    value: bool | None
    reasons: list[str] = field(default_factory=list)
    questions: dict[str, str] = field(default_factory=dict)
    failed: dict | None = None
    provisional: list[str] = field(default_factory=list)
    used: list[str] = field(default_factory=list)


def validate(conditions: object) -> None:
    """Raise ConditionError for an unknown op, a missing key, or a date that doesn't parse."""
    if isinstance(conditions, list):
        for item in conditions:
            validate(item)
        return
    if not isinstance(conditions, dict):
        raise ConditionError(f"A condition must be a mapping or a list, not {conditions!r}")
    for group in ("all_of", "any_of"):
        if group in conditions:
            if not isinstance(conditions[group], list):
                raise ConditionError(f"{group} needs a list")
            validate(conditions[group])
            return
    if "manual" in conditions:
        return
    for key in ("field", "op"):
        if key not in conditions:
            raise ConditionError(f"Condition {conditions} needs '{key}'")
    op = conditions["op"]
    if op not in OPS:
        raise ConditionError(f"Unknown op {op!r}; use one of {sorted(OPS)}")
    key = _ALIASES.get(conditions["field"], conditions["field"])
    if key not in FIELDS:
        raise ConditionError(f"Unknown ship card field {conditions['field']!r}; use one of {sorted(FIELDS)}")
    if op == "exists":
        return
    if "value" not in conditions:
        raise ConditionError(f"Condition {conditions} needs 'value'")
    if FIELDS[key].kind == "text" and op in ("<", "<=", ">", ">="):
        raise ConditionError(f"{op} compares numbers or dates, not {conditions['field']}")
    listed = op in ("in", "not_in")
    if listed and not isinstance(conditions["value"], list):
        raise ConditionError(f"{op} needs a list value")
    if op in ("on_or_after", "before") or FIELDS[key].kind == "date":
        for want in conditions["value"] if listed else [conditions["value"]]:
            if _coerce("date", want) is None:
                raise ConditionError(f"{want!r} is not a date (use YYYY-MM-DD) in {conditions}")


def _coerce(kind: str, raw: object) -> float | str | date | None:
    if raw is None:
        return None
    if kind == "date":
        if isinstance(raw, date):
            return raw
        try:
            return date.fromisoformat(raw.strip()) if isinstance(raw, str) else None
        except ValueError:
            return None
    if kind in ("number", "length"):
        if isinstance(raw, bool):
            return None
        if isinstance(raw, (int, float)):
            return float(raw)
        try:
            return float(raw) if isinstance(raw, str) else None
        except ValueError:
            return None
    return str(raw).strip().lower()


def _kind(key: str, want: object) -> str:
    if key in FIELDS:
        return FIELDS[key].kind
    return "date" if isinstance(want, date) else "number" if isinstance(want, (int, float)) else "text"


def _want(kind: str, raw: object) -> float | str | date:
    value = _coerce(kind, raw)
    if value is None:
        raise ConditionError(f"{raw!r} is not a valid {kind} value in a condition")
    return value


def _holds(op: str, have: float | str | date, want: object, kind: str) -> bool:
    if op in ("in", "not_in"):
        hit = have in [_want(kind, w) for w in want]
        return hit if op == "in" else not hit
    right = _want(kind, want)
    if op == "on_or_after":
        return have >= right
    if op == "before":
        return have < right
    if op in ("==", "!="):
        return (have == right) == (op == "==")
    if kind == "text":
        raise ConditionError(f"{op} compares numbers or dates, not text")
    return {"<": have < right, "<=": have <= right, ">": have > right, ">=": have >= right}[op]


def _must_be(op: str, want: object, kind: str, key: str) -> str:
    def show(w: object) -> str:
        return pretty(str(w)) if kind == "text" else format_value(key, _want(kind, w))

    if op == "exists":
        return "stated"
    if op in ("in", "not_in"):
        return ("one of " if op == "in" else "none of ") + ", ".join(show(w) for w in want)
    words = {"==": "", "!=": "not ", "<": "less than ", "<=": "at most ", ">": "more than ", ">=": "at least ",
             "on_or_after": "on or after ", "before": "before "}
    return words[op] + show(want)


def _sentence(clause: str, text: str) -> str:
    return f"{clause}: {text}" if clause else cap(text)


def _unknown(key: str, cond: dict, why: str, extra: str = "") -> _Node:
    label = label_for(cond.get("field", key))
    ask = cond.get("ask") or f"What is the ship's {label}?"
    reason = cond.get("why") or why
    return _Node(None, questions={key: " ".join(part for part in (ask, reason, extra) if part)}, used=[key])


def _leaf(cond: dict, card: ShipCard, why: str) -> _Node:
    if "manual" in cond:
        # An input the card can't hold: always can't tell, with the question to a person.
        text = " ".join(part for part in (cond["manual"], cond.get("why") or why) if part)
        return _Node(None, questions={cond.get("needs", cond["manual"]): text})
    name, op, clause = cond["field"], cond["op"], cond.get("clause", "")
    key = _ALIASES.get(name, name)
    label = label_for(name)
    item = card.field(key)
    have = card.get(key)
    note = f"({item.note})" if item is not None and item.note else ""
    if have is None:
        return _unknown(key, cond, why, note)
    kind = _kind(key, cond.get("value"))
    left = _coerce(kind, have)
    shown = format_value(key, left if left is not None else have)
    if left is None:
        return _unknown(key, cond, why, f"(The stored {label} '{have}' is not usable as a {kind}.)")
    if op == "exists":
        result, want = True, None
    else:
        want = cond["value"]
        result = _holds(op, left, want, kind)
    must = _must_be(op, want, kind, key)
    weak = item is not None and item.tier == "C" and not item.confirmed
    if weak and result is False:
        # A single reading must not switch a rule off: ask a person to confirm it.
        return _Node(None, used=[key], provisional=[f"{label} {shown} is a single reading"], questions={
            key: f"Please confirm the {label}: the only reading is {shown}, and it decides whether {clause or 'this rule'} applies."})
    if result:
        reason = _sentence(clause, f"{label} is {shown} (must be {must}).")
        return _Node(True, [reason], used=[key], provisional=[f"{label} {shown} is a single reading"] if weak else [])
    reason = _sentence(clause, f"{label} is {shown}, but it must be {must}.")
    failed = {"field": name, "op": op, "value": want, "have": left, "clause": clause}
    return _Node(False, [reason], failed=failed, used=[key])


def _merge(nodes: list[_Node], source: list[_Node]) -> tuple[dict[str, str], list[str], list[str]]:
    questions: dict[str, str] = {}
    for node in nodes:
        for key, text in node.questions.items():
            questions.setdefault(key, text)
    used = [k for node in nodes for k in node.used]
    provisional = [p for node in source for p in node.provisional]
    return questions, list(dict.fromkeys(used)), list(dict.fromkeys(provisional))


def _group(kind: str, items: list, card: ShipCard, why: str) -> _Node:
    children = [_eval(item, card, why) for item in items]
    false = [c for c in children if c.value is False]
    true = [c for c in children if c.value is True]
    unknown = [c for c in children if c.value is None]
    if kind == "all_of":
        if false:
            questions, used, provisional = _merge(children, false)
            return _Node(False, [r for c in false for r in c.reasons], failed=false[0].failed, used=used, provisional=provisional)
        value, source = (None if unknown else True), true
    else:
        if true:
            questions, used, provisional = _merge(children, true)
            return _Node(True, [r for c in true for r in c.reasons], used=used, provisional=provisional)
        if not unknown and false:
            questions, used, provisional = _merge(children, false)
            return _Node(False, [r for c in false for r in c.reasons], failed={"any_of": [c.failed for c in false]},
                         used=used, provisional=provisional)
        value, source = None, false
    questions, used, provisional = _merge(children, children)
    if value is None:
        return _Node(None, [r for c in source for r in c.reasons], questions=questions, used=used, provisional=provisional)
    return _Node(True, [r for c in true for r in c.reasons], used=used, provisional=provisional)


def _eval(cond: object, card: ShipCard, why: str) -> _Node:
    if isinstance(cond, list):
        return _group("all_of", cond, card, why)
    if "all_of" in cond:
        return _group("all_of", cond["all_of"], card, why)
    if "any_of" in cond:
        return _group("any_of", cond["any_of"], card, why)
    return _leaf(cond, card, why)


def evaluate(conditions: object, card: ShipCard, why: str = "") -> Decision:
    """Decide whether a rule applies to this card.

    `why` is the rule's own one-line reason, added to each question so the person knows why it matters, unless the
    condition carries its own `why`.
    """
    conditions = conditions or []
    validate(conditions)
    node = _eval(conditions, card, why)
    if node.value is True and not node.reasons:
        node.reasons = ["No applicability conditions are set, so this applies to every ship."]
    status = {True: "applies", False: "not_applicable", None: "cant_tell"}[node.value]
    return Decision(status=status, reasons=node.reasons, missing=list(node.questions), questions=list(node.questions.values()),
                    failed=node.failed, provisional=node.provisional, used=list(dict.fromkeys(node.used)))
