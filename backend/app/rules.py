"""Rule library. A rule's limit counts as verified only when its quote is in the rule texts."""
from __future__ import annotations

import re
from pathlib import Path

import yaml

from .models import Rule, ScopeDecision, ShipProfile


def _normalise(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip().lower()


def load_rules(path: Path, rule_texts_dir: Path | None = None) -> list[Rule]:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    rules = [Rule(**item) for item in data["rules"]]
    corpus = ""
    if rule_texts_dir and rule_texts_dir.exists():
        texts = (p.read_text(encoding="utf-8", errors="ignore") for p in rule_texts_dir.rglob("*.md"))
        corpus = _normalise(" ".join(texts))
    # The IMO excerpts and their quotes are local files, not in the public repo. Without them, those limits show as unconfirmed.
    local = rule_texts_dir / "imo" / "rule-quotes.yaml" if rule_texts_dir else None
    quotes = yaml.safe_load(local.read_text(encoding="utf-8")) if local and local.exists() else {}
    for rule in rules:
        rule.quote = rule.quote or quotes.get(rule.id, "")
        rule.verified = bool(rule.quote) and _normalise(rule.quote) in corpus
    return rules


def decide_scope(rule: Rule, profile: ShipProfile) -> ScopeDecision:
    scope = rule.scope
    applies, reason = True, scope.reason or "Applies to this ship."
    if scope.ship_types and profile.ship_type not in scope.ship_types:
        applies = False
        reason = f"Not in scope: covers {', '.join(scope.ship_types)} ships, and this ship is {profile.ship_type}."
    elif scope.min_passengers is not None and (profile.passengers or 0) <= scope.min_passengers:
        applies = False
        reason = f"Not in scope: needs more than {scope.min_passengers} passengers, and this ship has {profile.passengers or 0}."
    elif scope.flags and profile.flag not in scope.flags:
        applies = False
        reason = f"Not in scope: covers {', '.join(scope.flags)} flag ships, and this ship is {profile.flag or 'unknown'} flag."
    return ScopeDecision(rule_id=rule.id, title=rule.title, area=rule.area, source=rule.source,
                         applies=applies, reason=reason)
