"""Fact store: model facts plus anything added by documents, images, chat, or measurement."""
from __future__ import annotations

from collections import defaultdict

from .models import Fact, SourceKind


class FactStore:
    """An engineer's correction of a reading replaces every other value for that subject and property.

    The engineer saw the drawing and said the reading was wrong, so keeping the misread next to the
    correction would only turn a fixed value into a conflict.
    """

    def __init__(self, facts: list[Fact] | None = None):
        self.facts: list[Fact] = []
        self._index: dict[tuple[str, str], list[Fact]] = defaultdict(list)
        self.superseded: list[Fact] = []
        for fact in facts or []:
            self.add(fact)

    def add(self, fact: Fact) -> None:
        current = self._index[fact.key()]
        corrected = any(f.source.kind == SourceKind.ENGINEER for f in current)
        if fact.source.kind == SourceKind.ENGINEER and not corrected:
            self.superseded += current
            self.facts = [f for f in self.facts if f.key() != fact.key()]
            current.clear()
        elif corrected and fact.source.kind != SourceKind.ENGINEER:
            self.superseded.append(fact)
            return
        self.facts.append(fact)
        current.append(fact)

    def get(self, subject: str, prop: str) -> list[Fact]:
        return list(self._index.get((subject, prop), []))

    def one(self, subject: str, prop: str) -> Fact | None:
        found = self._index.get((subject, prop))
        return found[0] if found else None

    def subjects(self, prefix: str) -> list[str]:
        return list(dict.fromkeys(f.subject for f in self.facts if f.subject.startswith(prefix)))
