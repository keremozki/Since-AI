"""Fact store: model facts plus anything added by documents, images, chat, or measurement."""
from __future__ import annotations

from collections import defaultdict

from .models import Fact


class FactStore:
    def __init__(self, facts: list[Fact] | None = None):
        self.facts: list[Fact] = []
        self._index: dict[tuple[str, str], list[Fact]] = defaultdict(list)
        for fact in facts or []:
            self.add(fact)

    def add(self, fact: Fact) -> None:
        self.facts.append(fact)
        self._index[fact.key()].append(fact)

    def get(self, subject: str, prop: str) -> list[Fact]:
        return list(self._index.get((subject, prop), []))

    def one(self, subject: str, prop: str) -> Fact | None:
        found = self._index.get((subject, prop))
        return found[0] if found else None

    def subjects(self, prefix: str) -> list[str]:
        return list(dict.fromkeys(f.subject for f in self.facts if f.subject.startswith(prefix)))
