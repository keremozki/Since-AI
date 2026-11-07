"""Run the checks with the ship card deciding which rules apply, instead of a fixed profile.

The card's design basis says, per rule, applies / not applicable / can't tell, with clauses and questions. A rule
that can't be told still runs, so its findings show what would follow, and one "can't tell" result per rule asks
the questions that settle it. Nothing is assumed in or out of scope.
"""
from __future__ import annotations

from typing import Callable

from ..models import Rule, ScopeDecision, ShipProfile
from .design_basis import _survival_regime, compute_basis
from .shipcard import ShipCard

CARD_PROFILE_ID = "card"
# Legacy profile types: the checks only read ship_type for the evacuation limit (ro-ro passenger ships: 60 min).
_TYPES = {"passenger": "passenger", "ro_ro_passenger": "ro_ro_passenger", "cargo": "cargo", "special_purpose": "special_purpose"}


def card_profile(card: ShipCard) -> ShipProfile:
    ship_type = card.text("ship_type")
    passengers = card.number("passengers")
    name = card.name or "This ship"
    return ShipProfile(
        id=CARD_PROFILE_ID, name=f"{name} (rules chosen by the ship card)", ship_type=_TYPES.get(ship_type or "", "unknown"),
        passengers=int(passengers) if passengers is not None else None, flag=card.text("flag") or "",
        note=("Rules are chosen from the ship card: type, size, persons, voyage and dates, with the clause for each. "
              "No assumptions are approved for this ship, so every door and stair is checked exactly."))


def basis_scope(card: ShipCard) -> Callable[[Rule, ShipProfile], ScopeDecision]:
    items = {item.rule_id: item for item in compute_basis(card)}
    regime, regime_missing = _survival_regime(card)

    def decide(rule: Rule, _profile: ShipProfile) -> ScopeDecision:
        base = dict(rule_id=rule.id, title=rule.title, area=rule.area, source=rule.source)
        item = items.get(rule.id)
        if item is None:
            return ScopeDecision(**base, applies=True, status="cant_tell", reason="This rule has no applicability conditions yet.",
                                 questions=[f"Does {rule.title} ({rule.source}) apply to this ship?"])
        common = dict(clause=item.clause, edition=item.edition)
        if rule.id == "SOLAS-III-RAFTS" and item.applicability != "not_applicable":
            # The 100% liferaft check is the cargo-ship rule. Passenger-ship lifesaving has its own 25% check.
            if regime == "passenger":
                return ScopeDecision(**base, **common, applies=False, status="not_applicable",
                                     reason="Passenger-ship lifesaving applies (SOLAS III/21; SPS Code 8.2), so liferafts are "
                                            "checked by SOLAS-III-21-LIFERAFTS: 25% of persons on board in total.")
            if regime is None:
                return ScopeDecision(**base, **common, applies=True, status="cant_tell",
                                     reason="Which lifesaving rules apply depends on facts not yet known.",
                                     questions=list(regime_missing.values()))
        if item.applicability == "applies":
            return ScopeDecision(**base, **common, applies=True, status="applies", reason=" ".join(item.reasons) or "Applies to this ship.")
        if item.applicability == "not_applicable":
            return ScopeDecision(**base, **common, applies=False, status="not_applicable",
                                 reason=" ".join(item.reasons) or "Doesn't apply to this ship.")
        return ScopeDecision(**base, **common, applies=True, status="cant_tell",
                             reason=" ".join(item.reasons) or "Can't tell yet whether this rule applies.",
                             questions=list(item.questions))

    return decide
