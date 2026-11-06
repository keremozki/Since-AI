"""Claude API access with a hard spending cap. Every call goes through here."""
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path

import anthropic

MODEL = "claude-sonnet-5-5"
# US dollars per million tokens.
PRICE_INPUT = 2.0
PRICE_OUTPUT = 10.0
PRICE_CACHE_READ = 0.20
DEFAULT_CAP_USD = 4.00


class BudgetExceeded(Exception):
    pass


class ModelRefused(Exception):
    pass


def load_env(path: Path) -> None:
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        if "=" in line and not line.lstrip().startswith("#"):
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip())


@dataclass
class Usage:
    input_tokens: int
    output_tokens: int
    cache_read_tokens: int

    @property
    def cost(self) -> float:
        return (self.input_tokens * PRICE_INPUT + self.output_tokens * PRICE_OUTPUT
                + self.cache_read_tokens * PRICE_CACHE_READ) / 1_000_000


class Ledger:
    """Saved on disk so the cap holds across restarts."""

    def __init__(self, path: Path, cap_usd: float):
        self.path, self.cap = path, cap_usd
        self.spent, self.calls = 0.0, 0
        if path.exists():
            data = json.loads(path.read_text(encoding="utf-8"))
            self.spent, self.calls = data["spent_usd"], data["calls"]

    def require_budget(self) -> None:
        if self.spent >= self.cap:
            raise BudgetExceeded(
                f"The ${self.cap:.2f} spending cap is used up (${self.spent:.2f} spent). AI features are paused; "
                "the checks themselves cost nothing and keep working.")

    def record(self, usage: Usage) -> None:
        self.spent += usage.cost
        self.calls += 1
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps({"spent_usd": round(self.spent, 6), "calls": self.calls}), encoding="utf-8")


class Claude:
    def __init__(self, ledger: Ledger, client: anthropic.Anthropic | None = None):
        self.ledger = ledger
        self._client = client

    @property
    def client(self) -> anthropic.Anthropic:
        if self._client is None:
            self._client = anthropic.Anthropic()
        return self._client

    def structured(self, system: str, content: list[dict] | str, schema: dict, effort: str = "low",
                   max_tokens: int = 8000) -> dict:
        """One call that returns JSON matching the schema. Refusals raise, and never become results."""
        self.ledger.require_budget()
        response = self.client.beta.messages.create(
            model=MODEL,
            max_tokens=max_tokens,
            system=system,
            messages=[{"role": "user", "content": content}],
            output_config={"effort": effort, "format": {"type": "json_schema", "schema": schema}},
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",
        )
        usage = response.usage
        self.ledger.record(Usage(usage.input_tokens, usage.output_tokens, getattr(usage, "cache_read_input_tokens", 0) or 0))
        if response.stop_reason == "refusal":
            raise ModelRefused("The model declined this request.")
        if response.stop_reason == "max_tokens":
            raise ModelRefused("The model's answer was cut off, so it wasn't used.")
        text = next(block.text for block in response.content if block.type == "text")
        return json.loads(text)
