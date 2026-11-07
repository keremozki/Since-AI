"""Chat with the engineer. The AI explains results and records stated facts, but never decides one."""
from __future__ import annotations

import re

from .llm import Claude, ModelRefused
from .reading.parse import parse_length, parse_number
from .units import is_length_unit, to_mm
from .models import Fact, RunResult, Source, SourceKind, Status
from .vocabulary import FACT_SCHEMA, to_fact, vocabulary_text

HISTORY_TURNS = 6
MAX_LISTED_PASSES = 0

SYSTEM = f"""You are the assistant in a ship compliance checking tool, talking to a shipyard engineer.
Coded tests decide every result. You never decide or change a result, and you never state a rule limit
or clause that isn't in the results you're given. If the results don't answer the question, say so.

Your two jobs:
1. Answer questions, using only the results below, in short and plain language.
2. When the engineer states a design value, record it as a fact. The tests rerun by themselves after
   your reply, so never predict the outcome, and say only that the value is recorded.

Record a fact only if the engineer clearly states the value. If they're unsure, or are asking
"what if", don't record it, and ask them to confirm. If a value is ambiguous, ask one short question.
Facts must fit this list:
{vocabulary_text()}

For each fact, put the engineer's own words in quote, and leave locator empty."""

RESPONSE_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["reply", "facts"],
    "properties": {"reply": {"type": "string"}, "facts": {"type": "array", "items": FACT_SCHEMA}},
}


def results_context(result: RunResult) -> str:
    lines = [f"Ship profile: {result.profile.name}. {result.profile.note}", f"Summary: {result.summary}", ""]
    for finding in result.findings:
        if finding.status == Status.PASS:
            continue
        line = f"[{finding.status.value}] {finding.label} | {finding.rule_title} ({finding.rule_source})"
        for name, value in (("found", finding.measured), ("required", finding.required), ("gap", finding.gap),
                            ("where", finding.where), ("needed", finding.question)):
            if value:
                line += f" | {name}: {value}"
        if finding.assumptions:
            line += " | assumptions: " + " ".join(finding.assumptions)
        if finding.unconfirmed_label:
            line += f" | {finding.unconfirmed_label}"
        lines.append(line)
    passed = [f.label for f in result.findings if f.status == Status.PASS]
    lines.append(f"Passed ({len(passed)}): " + ", ".join(passed))
    not_in_scope = [f"{d.title}: {d.reason}" for d in result.scope if not d.applies]
    if not_in_scope:
        lines.append("Not in scope: " + " ".join(not_in_scope))
    return "\n".join(lines)


def respond(claude: Claude, result: RunResult, history: list[dict], message: str) -> tuple[str, list[Fact], int]:
    """Return (reply, accepted facts, facts dropped by validation)."""
    recent = history[-HISTORY_TURNS:]
    transcript = "\n".join(f"{turn['role'].capitalize()}: {turn['text']}" for turn in recent)
    content = (f"Current results:\n{results_context(result)}\n\n"
               f"Conversation so far:\n{transcript or '(none)'}\n\nEngineer: {message}")
    output = claude.structured(SYSTEM, content, RESPONSE_SCHEMA, effort="low", max_tokens=2000)
    reply, raw_facts = output.get("reply"), output.get("facts") or []
    if not isinstance(reply, str) or not reply.strip() or not isinstance(raw_facts, list):
        # Recording facts without the reply that states them would change results silently.
        raise ModelRefused("The AI answer was incomplete, so nothing was recorded. Ask again.")
    template = Source(kind=SourceKind.CHAT, locator="chat")
    facts = [fact for fact in (to_fact(raw, template) for raw in raw_facts if isinstance(raw, dict))
             if fact and in_engineers_words(fact, message)]
    return reply, facts, len(raw_facts) - len(facts)


def in_engineers_words(fact: Fact, message: str) -> bool:
    """A recorded value must be one the engineer wrote. The AI may pick it out, but never type or convert it."""
    if isinstance(fact.value, str):
        return fact.value.strip().lower() in message.lower()
    if is_length_unit(fact.unit):
        stated = [parse_length(piece) for piece in _pieces(message)]
        return any(found and abs(to_mm(found[0], found[1]) - to_mm(float(fact.value), fact.unit)) < 0.5 for found in stated)
    numbers = [parse_number(piece) for piece in _pieces(message)]
    return any(n is not None and abs(n - float(fact.value)) < 1e-9 for n in numbers)


def _pieces(message: str) -> list[str]:
    """Every run of text that starts at a digit, so each number is parsed with the unit written after it."""
    return [message[m.start():] for m in re.finditer(r"(?<![\d.,])\d", message)]
