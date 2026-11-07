"""Unit conversion to a common base, so that checks never mix units by accident."""
from __future__ import annotations

import math

_TO_MM = {"mm": 1.0, "cm": 10.0, "m": 1000.0, "in": 25.4, "ft": 304.8}
UNIT_NAMES = ", ".join(_TO_MM)


class UnitError(ValueError):
    """A length that can't be converted: unknown unit, or not a finite number."""


def _factor(unit: str) -> float:
    key = (unit or "").strip().lower()
    if key not in _TO_MM:
        raise UnitError(f"Unknown length unit {unit!r}. Use one of: {UNIT_NAMES}.")
    return _TO_MM[key]


def to_mm(value: float, unit: str) -> float:
    number = float(value)
    if not math.isfinite(number):
        raise UnitError(f"{value!r} is not a finite number.")
    return number * _factor(unit)


def from_mm(value: float, unit: str) -> float:
    return value / _factor(unit)


def is_length_unit(unit: str) -> bool:
    return isinstance(unit, str) and unit.strip().lower() in _TO_MM


def length_problem(value, unit: str) -> str:
    """Why a value can't be used as a length, or "" when it can. Zero or negative is never a real width."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return f"the value {value!r} is not a number"
    if not math.isfinite(value):
        return f"the value {value!r} is not a finite number"
    if not is_length_unit(unit):
        return f"the unit {unit!r} is not a length unit ({UNIT_NAMES})" if unit else "no unit is given"
    if value <= 0:
        return f"a length of {value:g} {unit} is not possible"
    return ""


def fmt_length(value: float, unit: str) -> str:
    """Show a length in its source unit, with the metric or imperial equivalent."""
    unit = unit.strip().lower()
    mm = to_mm(value, unit)
    if unit == "in":
        return f"{value:g} in ({mm:.0f} mm)"
    if unit == "mm":
        return f"{value:g} mm ({mm / 25.4:.1f} in)"
    return f"{value:g} {unit}"
