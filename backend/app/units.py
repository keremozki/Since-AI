"""Unit conversion to a common base, so that checks never mix units by accident."""
from __future__ import annotations

_TO_MM = {"mm": 1.0, "cm": 10.0, "m": 1000.0, "in": 25.4, "ft": 304.8}


def to_mm(value: float, unit: str) -> float:
    return float(value) * _TO_MM[unit.strip().lower()]


def from_mm(value: float, unit: str) -> float:
    return value / _TO_MM[unit.strip().lower()]


def is_length_unit(unit: str) -> bool:
    return unit.strip().lower() in _TO_MM


def fmt_length(value: float, unit: str) -> str:
    """Show a length in its source unit, with the metric or imperial equivalent."""
    unit = unit.strip().lower()
    mm = to_mm(value, unit)
    if unit == "in":
        return f"{value:g} in ({mm:.0f} mm)"
    if unit == "mm":
        return f"{value:g} mm ({mm / 25.4:.1f} in)"
    return f"{value:g} {unit}"
