"""units.py: conversion, refusals, and display."""
import math

import pytest

from app.units import UnitError, fmt_length, from_mm, is_length_unit, length_problem, to_mm


@pytest.mark.parametrize("value, unit, mm", [(1, "mm", 1), (1, "cm", 10), (1, "m", 1000), (1, "in", 25.4), (1, "ft", 304.8),
                                             (32, " IN ", 812.8), ("915", "mm", 915)])
def test_to_mm(value, unit, mm):
    assert to_mm(value, unit) == pytest.approx(mm)


def test_round_trip():
    assert from_mm(to_mm(36, "in"), "in") == pytest.approx(36)


@pytest.mark.parametrize("unit", ["furlong", "", "inch", "mm2", None])
def test_unknown_unit_is_a_clear_error(unit):
    with pytest.raises(UnitError, match="Unknown length unit"):
        to_mm(1, unit)
    assert not is_length_unit(unit)


@pytest.mark.parametrize("value", [math.nan, math.inf, -math.inf])
def test_non_finite_values_are_refused(value):
    with pytest.raises(UnitError):
        to_mm(value, "mm")


@pytest.mark.parametrize("value, unit, words", [(0, "in", "not possible"), (-3, "mm", "not possible"),
                                                (30, "", "no unit"), (30, "yd", "not a length unit"),
                                                ("30", "in", "not a number"), (math.nan, "in", "finite"), (True, "in", "not a number")])
def test_length_problem_names_the_problem(value, unit, words):
    assert words in length_problem(value, unit)


def test_good_length_has_no_problem():
    assert length_problem(34.5, "in") == "" and length_problem(1, "m") == ""


def test_fmt_length_shows_both_systems():
    assert fmt_length(32, "in") == "32 in (813 mm)"
    assert fmt_length(815, "mm") == "815 mm (32.1 in)"
    assert fmt_length(1.2, "m") == "1.2 m"
