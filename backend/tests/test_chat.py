"""chat.py: the AI explains and records stated facts, never decides, and a bad answer records nothing."""
import pytest

from app.chat import HISTORY_TURNS, respond, results_context
from app.engine import run
from app.llm import ModelRefused
from app.models import Fact, Rule, ShipProfile, Source, SourceKind
from app.store import FactStore

DOOR = Rule(id="D", title="Door clear width", area="A", source="PVAG V404.2.3", check="door_clear_width",
            params={"min_in": 32, "min_mm": 815})
PASSENGER = ShipProfile(id="p", name="Test ship", ship_type="passenger", passengers=400)


class Fake:
    def __init__(self, answer):
        self.answer, self.seen = answer, []

    def structured(self, system, content, schema, effort="low", max_tokens=8000):
        self.seen.append((system, content))
        return self.answer


def result(*facts):
    return run(FactStore(list(facts)), [DOOR], PASSENGER)


def width(number, value):
    return Fact(subject=f"door-number:{number}", property="clear_width", value=value, unit="in",
                source=Source(kind=SourceKind.DOCUMENT, file="plan.pdf"))


def raw(subject, prop, number, unit="in"):
    return {"subject": subject, "property": prop, "value_number": number, "value_text": None, "unit": unit,
            "quote": "door 7 is 30 inches", "locator": "", "confidence": "high"}


def test_context_lists_problems_and_names_passes():
    text = results_context(result(width(1, 30), width(2, 34)))
    assert "[fail] Door 1" in text and "Passed (1): Door 2" in text


def test_stated_value_is_recorded_as_a_chat_fact():
    fake = Fake({"reply": "Recorded.", "facts": [raw("door-number:7", "clear_width", 30)]})
    reply, facts, dropped = respond(fake, result(), [], "Door 7 is 30 inches")
    assert reply == "Recorded." and dropped == 0
    assert facts[0].source.kind == SourceKind.CHAT and facts[0].value == 30


def test_facts_outside_the_vocabulary_or_without_units_are_dropped():
    fake = Fake({"reply": "Noted.", "facts": [raw("door-number:7", "colour", 1), raw("door-number:7", "clear_width", 30, ""),
                                               raw("door-number:7", "clear_width", -2), "not a dict"]})
    _reply, facts, dropped = respond(fake, result(), [], "x")
    assert facts == [] and dropped == 4


@pytest.mark.parametrize("answer", [{}, {"reply": "", "facts": []}, {"reply": "ok", "facts": "door 7"}, {"facts": [raw("door-number:7", "clear_width", 30)]}])
def test_incomplete_answer_records_nothing(answer):
    with pytest.raises(ModelRefused):
        respond(Fake(answer), result(), [], "x")


def test_only_recent_history_is_sent():
    history = [{"role": "engineer", "text": f"turn {i}"} for i in range(HISTORY_TURNS + 4)]
    fake = Fake({"reply": "ok", "facts": []})
    respond(fake, result(), history, "now")
    content = fake.seen[0][1]
    assert "turn 0" not in content and f"turn {HISTORY_TURNS + 3}" in content and "Engineer: now" in content


def test_system_prompt_says_the_ai_never_decides():
    fake = Fake({"reply": "ok", "facts": []})
    respond(fake, result(), [], "x")
    assert "never decide" in fake.seen[0][0]
