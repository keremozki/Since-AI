"""Document revisions. A newer revision of the same drawing replaces the older one's facts, and the impact of
the change is reported value by value, so an engineer sees what a revision broke or fixed.

A document is identified by the drawing number read from its title block (evidence.doc_id). Revisions are
ordered only when they are of the same kind: letters (A < B < ... < Z < AA), numbers (0 < 1 < 2), or a letter
prefix with a number (P1 < P2). Anything else can't be ordered, so both stay in force and any value they
disagree on shows up as a conflict. Nothing is replaced on a guess.
"""
from __future__ import annotations

import re

from .models import Fact


def revision_key(revision: str) -> tuple[str, int] | None:
    """(kind, rank) for ordering, or None when the revision can't be ordered."""
    text = revision.strip().upper().removeprefix("REV").strip(" .:")
    if re.fullmatch(r"[A-Z]{1,2}", text):
        rank = 0
        for char in text:
            rank = rank * 26 + (ord(char) - 64)
        return "letter", rank
    if re.fullmatch(r"\d{1,3}", text):
        return "number", int(text)
    match = re.fullmatch(r"([A-Z])(\d{1,3})", text)
    if match:
        return f"prefix-{match.group(1)}", int(match.group(2))
    return None


def newer(a: str, b: str) -> bool | None:
    """Whether revision a is newer than b. None when they can't be compared."""
    ka, kb = revision_key(a), revision_key(b)
    if ka is None or kb is None or ka[0] != kb[0]:
        return None
    return ka[1] > kb[1]


def _doc(fact: Fact) -> tuple[str, str] | None:
    evidence = fact.evidence
    if evidence is None or not evidence.doc_id or not evidence.revision:
        return None
    return evidence.doc_id, evidence.revision


def supersede(existing: list[Fact], incoming: list[Fact]) -> tuple[list[Fact], list[Fact], list[dict]]:
    """(existing, incoming, notes) with superseded_by set where a newer revision of the same drawing exists.

    Each note: {doc_id, old, new, replaced, file} or, when two revisions can't be ordered, {doc_id, revisions, question}.
    """
    incoming_docs = {d for d in map(_doc, incoming) if d}
    notes: list[dict] = []
    updated_existing = list(existing)
    updated_incoming = list(incoming)
    for doc_id, revision in sorted(incoming_docs):
        new_file = next((f.evidence.file or f.source.file for f in incoming if _doc(f) == (doc_id, revision)), "")
        for old_revision in sorted({d[1] for d in map(_doc, existing) if d and d[0] == doc_id and d[1] != revision}):
            order = newer(revision, old_revision)
            if order is None:
                notes.append({"doc_id": doc_id, "revisions": [old_revision, revision],
                              "question": f"Which revision of drawing {doc_id} is current, {old_revision} or {revision}? "
                                          "Both stay in force until you say."})
                continue
            stale, current = (old_revision, revision) if order else (revision, old_revision)
            marker = f"{doc_id} revision {current}"
            count = 0
            if order:
                for i, fact in enumerate(updated_existing):
                    if _doc(fact) == (doc_id, stale) and not fact.superseded_by:
                        updated_existing[i] = fact.model_copy(update={"superseded_by": marker})
                        count += 1
            else:
                for i, fact in enumerate(updated_incoming):
                    if _doc(fact) == (doc_id, stale) and not fact.superseded_by:
                        updated_incoming[i] = fact.model_copy(update={"superseded_by": marker})
                        count += 1
            notes.append({"doc_id": doc_id, "old": stale, "new": current, "replaced": count, "file": new_file})
    return updated_existing, updated_incoming, notes


def _show(fact: Fact) -> str:
    value = f"{fact.value:g}" if isinstance(fact.value, float) else str(fact.value)
    return f"{value} {fact.unit}".strip()


def value_changes(old: list[Fact], new: list[Fact]) -> list[dict]:
    """What a revision changed, by subject and property: changed, added, or removed values."""
    before = {f.key(): f for f in old}
    after = {f.key(): f for f in new}
    changes = []
    for key in sorted(before.keys() | after.keys()):
        a, b = before.get(key), after.get(key)
        if a is not None and b is not None and _show(a) == _show(b):
            continue
        kind = "changed" if a is not None and b is not None else "added" if b is not None else "removed"
        changes.append({"subject": key[0], "property": key[1], "change": kind,
                        "old": _show(a) if a else "", "new": _show(b) if b else "",
                        "quote_old": a.source.quote if a else "", "quote_new": b.source.quote if b else ""})
    return changes


def revision_impact(existing_before: list[Fact], notes: list[dict], incoming: list[Fact]) -> list[dict]:
    """For each replaced revision: the value changes between the old and the new revision of the drawing."""
    impact = []
    for note in notes:
        if "old" not in note:
            continue
        old = [f for f in existing_before + incoming if _doc(f) == (note["doc_id"], note["old"])]
        new = [f for f in existing_before + incoming if _doc(f) == (note["doc_id"], note["new"])]
        impact.append({**note, "value_changes": value_changes(old, new)})
    return impact
