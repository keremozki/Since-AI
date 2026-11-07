"""What the app says it recorded must be in plain words, for every kind of named object."""
import pytest

from app.checks import describe_fact
from app.models import Fact, Source, SourceKind


def fact(subject, prop, value, unit):
    return Fact(subject=subject, property=prop, value=value, unit=unit, source=Source(kind=SourceKind.CHAT))


@pytest.mark.parametrize("subject, prop, value, unit, expected", [
    ("ship", "crew_complement", 12, "persons", "Crew count: 12 persons"),
    ("door-number:301", "clear_width", 34, "in", "Door 301 clear width"),
    ("corridor:C2", "clear_width", 30, "in", "Corridor C2 clear width"),
    ("ramp:R1", "rise", 150, "mm", "Ramp R1 rise"),
    ("ramp:R1", "run", 1500, "mm", "Ramp R1 run"),
    ("ramp:R1", "slope_run_per_rise", 14, "", "Ramp R1 run per unit of rise: 14"),
])
def test_describe_fact_names_the_object_and_the_value(subject, prop, value, unit, expected):
    assert describe_fact(fact(subject, prop, value, unit)).startswith(expected)


def test_an_unnamed_subject_keeps_the_plain_property_name():
    assert describe_fact(fact("liferaft", "capacity_persons", 16, "persons")) == "Liferaft capacity: 16 persons"
