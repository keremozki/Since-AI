"""Trust tiers. Code decides the tier of every fact; the AI never does.

A pass or a fail needs every input at tier A or B. A tier C input (a single reading) holds the result back
to "can't tell" with a request to confirm the reading, and tier D (conflicting, placeholder, unreadable)
never backs anything.
"""
from __future__ import annotations

from .models import Fact, Finding, SourceKind, Status, Tier

# Structured sources: the value is stated in a field, not read off a picture.
_BY_SOURCE = {
    SourceKind.MODEL_3D: Tier.A,  # a part attribute in the 3D model
    SourceKind.MEASUREMENT: Tier.A,  # the engineer picked the points and saved the value
    SourceKind.CHAT: Tier.A,  # the engineer stated the value
    SourceKind.ENGINEER: Tier.A,  # the engineer corrected a misread
    SourceKind.DEMO_SEED: Tier.A,  # labelled test data, never shown as real
}
BACKS_VERDICT = {Tier.A, Tier.B}


def tier_of(fact: Fact) -> Tier:
    if fact.confirmed_by:
        return Tier.A
    if fact.tier is not None:
        return fact.tier
    if fact.source.kind in _BY_SOURCE:
        return _BY_SOURCE[fact.source.kind]
    # A document or image value read by one model reading of the whole page, with no second reading.
    return Tier.C


def fact_input(fact: Fact) -> dict:
    """What a finding records about each fact it used."""
    entry = {"id": fact.uid(), "subject": fact.subject, "property": fact.property, "value": fact.value, "unit": fact.unit,
             "tier": tier_of(fact).value, "source": fact.source.describe(), "quote": fact.source.quote,
             "file": fact.source.file, "locator": fact.source.locator}
    if fact.evidence is not None:
        entry["evidence"] = fact.evidence.model_dump(mode="json")
    if fact.derivation:
        entry["derivation"] = fact.derivation
    return entry


def gate(finding: Finding) -> Finding:
    """Hold back a pass or fail that rests on an input below tier B. The finding says which reading to confirm."""
    if finding.status not in (Status.PASS, Status.FAIL, Status.NOT_APPLICABLE):
        return finding
    weak = [i for i in finding.inputs if i.get("tier") in (Tier.C.value, Tier.D.value)]
    if not weak:
        return finding
    named = "; ".join(f"{i['subject']} {i['property'].replace('_', ' ')} = {i['value']}{(' ' + i['unit']) if i['unit'] else ''}"
                      f" (tier {i['tier']}, {i['source']})" for i in weak)
    would = {Status.PASS: "pass", Status.FAIL: "fail", Status.NOT_APPLICABLE: "be not applicable"}[finding.status]
    question = ("Confirm or correct these readings: " + named +
                ". Each was read only one way, so it can't back a verdict yet.")
    return finding.model_copy(update={
        "status": Status.CANT_TELL,
        "gate": f"Would {would}, but rests on a reading that isn't confirmed: {named}.",
        "question": (finding.question + " " if finding.question else "") + question,
        "gap": "",
        # An engineer can settle it: "read correctly" confirms the reading, "misread" corrects it.
        "reviewable": True,
        "original_status": finding.original_status or finding.status,
        "read_quote": finding.read_quote or weak[0].get("quote", ""),
        "read_file": finding.read_file or weak[0].get("file", ""),
        "read_locator": finding.read_locator or weak[0].get("locator", ""),
    })
