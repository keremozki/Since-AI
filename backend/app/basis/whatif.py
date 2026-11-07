"""What changes between two ship cards (a what-if, or a sister hull), and which amendments reach a hull."""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel

from .conditions import evaluate, validate
from .design_basis import BasisItem, ROOT, compute_basis, load_entries
from .shipcard import ShipCard, cap, format_value, label_for

AMENDMENTS_PATH = ROOT / "rules" / "amendments.yaml"
_REQUIRED_KEYS = ("id", "resolution", "in_force", "trigger", "summary", "affects", "source", "verified")


class Change(BaseModel):
    rule_id: str  # the rule id, or the amendment id when kind is "amendment"
    title: str
    kind: Literal["rule", "amendment"] = "rule"
    from_status: str
    to_status: str
    from_required: str = ""
    to_required: str = ""
    why: str = ""


@lru_cache(maxsize=4)
def load_amendments(path: str = str(AMENDMENTS_PATH)) -> list[dict]:
    """The amendments with their full conditions. A bad entry fails here, not in the middle of a run."""
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    entries, seen = [], set()
    for entry in data["amendments"]:
        for key in _REQUIRED_KEYS:
            if key not in entry:
                raise ValueError(f"Amendment {entry.get('id', '?')} lacks '{key}'")
        if entry["id"] in seen:
            raise ValueError(f"Duplicate amendment {entry['id']}")
        seen.add(entry["id"])
        conditions: list = []
        if entry.get("applies_like"):
            like = load_entries().get(entry["applies_like"])
            if like is None:
                raise ValueError(f"Amendment {entry['id']} reuses unknown rule {entry['applies_like']}")
            conditions.append({"all_of": like["conditions"]})
        conditions += entry.get("applies_if", [])
        if not conditions:
            raise ValueError(f"Amendment {entry['id']} has no conditions")
        validate(conditions)
        entries.append({**entry, "conditions": conditions})
    return entries


def amendments_for(card: ShipCard) -> list[dict]:
    """Every listed amendment with its status for this hull, decided by the date it keys on.

    Status is applies, not_applicable or cant_tell. An amendment whose trigger the sources don't state is always
    cant_tell, with the question, unless the ship type or size already rules it out.
    """
    out = []
    for entry in load_amendments():
        why = entry.get("why") or f"{entry['title']}: {' '.join(entry['summary'].split())}"
        decision = evaluate(entry["conditions"], card, why=why)
        out.append({
            "id": entry["id"], "resolution": entry["resolution"], "kind": entry.get("kind", "amendment"), "title": entry["title"],
            "adopted": entry.get("adopted"), "in_force": entry["in_force"], "trigger": entry["trigger"],
            "trigger_unconfirmed": bool(entry.get("trigger_unconfirmed", False)), "summary": " ".join(entry["summary"].split()),
            "affects": list(entry["affects"]), "rule_ids": list(entry.get("rule_ids", [])), "source": entry["source"],
            "verified": bool(entry["verified"]), "note": " ".join(entry.get("note", "").split()),
            "status": decision.status, "reasons": decision.reasons, "questions": decision.questions,
            "missing": decision.missing, "provisional": decision.provisional, "inputs": decision.used})
    return out


def _changed_inputs(card_a: ShipCard, card_b: ShipCard, keys: list[str]) -> list[str]:
    lines = []
    for key in dict.fromkeys(keys):
        a, b = card_a.get(key), card_b.get(key)
        if a != b:
            lines.append(f"{cap(label_for(key))} was {format_value(key, a)}, now {format_value(key, b)}")
    return lines


def _explain(from_status: str, to_status: str, to_reasons: list[str], to_questions: list[str], changed: list[str],
             from_required: str, to_required: str) -> str:
    parts = []
    if changed:
        parts.append("; ".join(changed) + ".")
    if from_status != to_status:
        if to_status == "applies":
            parts.append(" ".join(["It now applies.", *to_reasons]))
        elif to_status == "not_applicable":
            parts.append(" ".join(["It no longer applies.", *to_reasons]))
        else:
            parts.append(" ".join(["It can't be decided now.", *to_questions]))
    elif from_required != to_required:
        parts.append(f"The requirement changes from \"{from_required}\" to \"{to_required}\".")
    return " ".join(parts)


def _same(a: BasisItem, b: BasisItem) -> bool:
    if a.status != b.status:
        return False
    if a.status != "applies":
        return True
    same_numbers = a.required_value == b.required_value and a.bounds == b.bounds
    return same_numbers and (a.required_value is not None or a.required == b.required)


def compare(card_a: ShipCard, card_b: ShipCard, rule_ids: list[str] | None = None) -> list[Change]:
    """Rules and amendments whose status or required value differs between two cards, each explained in plain words.

    Use it for a what-if (the same hull with one input changed) or a sister hull (another hull, another set of dates).
    """
    items_a = {item.rule_id: item for item in compute_basis(card_a, rule_ids)}
    items_b = {item.rule_id: item for item in compute_basis(card_b, rule_ids)}
    changes = []
    for rule_id, a in items_a.items():
        b = items_b[rule_id]
        if _same(a, b):
            continue
        changed = _changed_inputs(card_a, card_b, [row["field"] for row in a.inputs + b.inputs])
        changes.append(Change(
            rule_id=rule_id, title=b.title, from_status=a.status, to_status=b.status, from_required=a.required, to_required=b.required,
            why=_explain(a.status, b.status, b.reasons, b.questions, changed, a.required, b.required)))
    amendments_b = {item["id"]: item for item in amendments_for(card_b)}
    for a in amendments_for(card_a):
        b = amendments_b[a["id"]]
        if a["status"] == b["status"]:
            continue
        if rule_ids is not None and not set(rule_ids) & set(b["rule_ids"]):
            continue
        changed = _changed_inputs(card_a, card_b, a["inputs"] + b["inputs"])
        context = f"In force {b['in_force']}. {b['summary']}"
        changes.append(Change(
            rule_id=b["id"], title=b["title"], kind="amendment", from_status=a["status"], to_status=b["status"],
            to_required=b["summary"] if b["status"] == "applies" else "",
            why=f"{_explain(a['status'], b['status'], b['reasons'], b['questions'], changed, '', '')} {context}".strip()))
    return changes
