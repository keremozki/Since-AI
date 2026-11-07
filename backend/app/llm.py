"""Claude API access with a hard spending cap. Every call goes through here."""
from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from pathlib import Path

import anthropic

MODEL = "claude-sonnet-5-5"
# US dollars per million tokens.
PRICE_INPUT = 2.0
PRICE_OUTPUT = 10.0
PRICE_CACHE_READ = 0.20
DEFAULT_CAP_USD = 4.00
REQUEST_TIMEOUT_S = 120.0
RETRY_DELAY_S = 2.0  # one retry after a timeout, rate limit, or server error
NO_KEY = ("No API key is set, so the AI reader and chat are off. Add ANTHROPIC_API_KEY=... to the .env file "
          "and restart the app. Vector PDFs, the checks, and the offline demo work without a key.")


class BudgetExceeded(Exception):
    pass


class ModelRefused(Exception):
    pass


class AIUnavailable(Exception):
    """The AI service can't be used now: no key, a rejected key, or no answer after one retry."""


def env_float(name: str, default: float) -> float:
    """A number from the environment. A typo there falls back to the default instead of stopping the app."""
    raw = os.environ.get(name, "")
    try:
        return float(raw) if raw.strip() else default
    except ValueError:
        print(f"Warning: {name}={raw!r} is not a number, so {default:g} is used.")
        return default


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
    def __init__(self, ledger: Ledger, client: anthropic.Anthropic | None = None, retry_delay: float = RETRY_DELAY_S):
        self.ledger = ledger
        self._client = client
        self.retry_delay = retry_delay

    @property
    def available(self) -> bool:
        return self._client is not None or bool(os.environ.get("ANTHROPIC_API_KEY", "").strip())

    @property
    def client(self) -> anthropic.Anthropic:
        if self._client is None:
            if not self.available:
                raise AIUnavailable(NO_KEY)
            # The SDK's own retries are off: we retry once ourselves, so the wait stays short and known.
            self._client = anthropic.Anthropic(timeout=REQUEST_TIMEOUT_S, max_retries=0)
        return self._client

    def _create(self, **request):
        for attempt in (1, 2):
            try:
                return self.client.beta.messages.create(**request)
            except (anthropic.AuthenticationError, anthropic.PermissionDeniedError) as error:
                raise AIUnavailable("The API key was rejected (HTTP %s). Check ANTHROPIC_API_KEY in .env and restart. "
                                    "The checks keep working without AI." % getattr(error, "status_code", "401")) from error
            except (anthropic.RateLimitError, anthropic.APITimeoutError, anthropic.APIConnectionError,
                    anthropic.InternalServerError) as error:
                if attempt == 2:
                    what = {anthropic.RateLimitError: "rate limit reached", anthropic.APITimeoutError: "timed out",
                            anthropic.APIConnectionError: "no connection"}.get(type(error), "server error")
                    raise AIUnavailable(f"The AI service didn't answer ({what}), also after one retry. Try again in a "
                                        "minute. Nothing was recorded; the checks keep working.") from error
                time.sleep(self.retry_delay)
            except anthropic.APIStatusError as error:
                raise AIUnavailable(f"The AI service rejected the request (HTTP {error.status_code}). "
                                    "Nothing was recorded. Try fewer pages or a smaller file.") from error

    def structured(self, system: str, content: list[dict] | str, schema: dict, effort: str = "low",
                   max_tokens: int = 8000) -> dict:
        """One call that returns JSON matching the schema. Refusals raise, and never become results."""
        self.ledger.require_budget()
        response = self._create(
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
        text = next((block.text for block in response.content if block.type == "text"), None)
        try:
            return json.loads(text) if text else {}
        except json.JSONDecodeError as error:
            raise ModelRefused("The model's answer wasn't valid JSON, so it wasn't used.") from error
