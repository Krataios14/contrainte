"""Typed dimensional quantities with exact rational SI factors.

This registry is deliberately separate from :mod:`contrainte.units`. The legacy
scalar ``Quantity`` keeps its own kinds, units and behaviour unchanged.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from fractions import Fraction
from typing import Any

from ..errors import DimensionalityError, InputError

QUANTITY_SCHEMA = "contrainte.dimensional-quantity/0.1"

# Dimension exponents over (length, mass, time, temperature).
Dimension = tuple[int, int, int, int]
DIMENSIONLESS: Dimension = (0, 0, 0, 0)

_EXACT = re.compile(r"^-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?(?:[eE][+-]?[0-9]{1,2})?$")
_MAX_SIGNIFICAND_DIGITS = 40

KINDS: dict[str, Dimension] = {
    "dimensionless": (0, 0, 0, 0),
    "strain": (0, 0, 0, 0),
    "length": (1, 0, 0, 0),
    "area": (2, 0, 0, 0),
    "second_moment_of_area": (4, 0, 0, 0),
    "mass": (0, 1, 0, 0),
    "density": (-3, 1, 0, 0),
    "velocity": (1, 0, -1, 0),
    "dynamic_viscosity": (-1, 1, -1, 0),
    "kinematic_viscosity": (2, 0, -1, 0),
    "time": (0, 0, 1, 0),
    "frequency": (0, 0, -1, 0),
    "force": (1, 1, -2, 0),
    "stress": (-1, 1, -2, 0),
    "absolute_pressure": (-1, 1, -2, 0),
    "gauge_pressure": (-1, 1, -2, 0),
    "thermodynamic_temperature": (0, 0, 0, 1),
    "temperature_difference": (0, 0, 0, 1),
    "heat_transfer_coefficient": (0, 1, -3, -1),
    "thermal_conductivity": (1, 1, -3, -1),
    "heat_flux": (0, 1, -3, 0),
}


@dataclass(frozen=True)
class UnitDefinition:
    code: str
    dimension: Dimension
    si_factor: Fraction


def _unit(code: str, kind: str, factor: Fraction | int) -> UnitDefinition:
    return UnitDefinition(code, KINDS[kind], Fraction(factor))


UNITS: dict[str, UnitDefinition] = {
    item.code: item
    for item in (
        _unit("1", "dimensionless", 1),
        _unit("m", "length", 1),
        _unit("mm", "length", Fraction(1, 10**3)),
        _unit("cm", "length", Fraction(1, 10**2)),
        _unit("km", "length", 1000),
        _unit("um", "length", Fraction(1, 10**6)),
        _unit("nm", "length", Fraction(1, 10**9)),
        _unit("m2", "area", 1),
        _unit("cm2", "area", Fraction(1, 10**4)),
        _unit("mm2", "area", Fraction(1, 10**6)),
        _unit("m4", "second_moment_of_area", 1),
        _unit("cm4", "second_moment_of_area", Fraction(1, 10**8)),
        _unit("mm4", "second_moment_of_area", Fraction(1, 10**12)),
        _unit("kg", "mass", 1),
        _unit("g", "mass", Fraction(1, 10**3)),
        _unit("kg/m3", "density", 1),
        _unit("g/cm3", "density", 1000),
        _unit("m/s", "velocity", 1),
        _unit("mm/s", "velocity", Fraction(1, 10**3)),
        _unit("km/h", "velocity", Fraction(5, 18)),
        _unit("Pa.s", "dynamic_viscosity", 1),
        _unit("mPa.s", "dynamic_viscosity", Fraction(1, 10**3)),
        _unit("m2/s", "kinematic_viscosity", 1),
        _unit("mm2/s", "kinematic_viscosity", Fraction(1, 10**6)),
        _unit("s", "time", 1),
        _unit("ms", "time", Fraction(1, 10**3)),
        _unit("min", "time", 60),
        _unit("h", "time", 3600),
        _unit("Hz", "frequency", 1),
        _unit("N", "force", 1),
        _unit("kN", "force", 1000),
        _unit("Pa", "stress", 1),
        _unit("kPa", "stress", 10**3),
        _unit("MPa", "stress", 10**6),
        _unit("GPa", "stress", 10**9),
        _unit("bar", "stress", 10**5),
        _unit("K", "thermodynamic_temperature", 1),
        _unit("W/(m2.K)", "heat_transfer_coefficient", 1),
        _unit("W/(m.K)", "thermal_conductivity", 1),
        _unit("W/m2", "heat_flux", 1),
    )
}


def parse_exact(raw: Any, field: str) -> Fraction:
    """Parse an exact decimal string into a rational without rounding."""

    if not isinstance(raw, str):
        raise InputError(
            f"{field} must be an exact decimal string, not {type(raw).__name__}"
        )
    if not _EXACT.fullmatch(raw):
        raise InputError(f"{field} is not an exact finite decimal string: {raw!r}")
    significand = re.split(r"[eE]", raw, maxsplit=1)[0]
    digits = significand.lstrip("-").replace(".", "")
    if len(digits) > _MAX_SIGNIFICAND_DIGITS:
        raise InputError(
            f"{field} has more than {_MAX_SIGNIFICAND_DIGITS} significand digits"
        )
    value = Fraction(raw)
    if value == 0 and raw.startswith("-"):
        raise InputError(f"{field} must not be negative zero")
    return value


def rational_text(value: Fraction) -> str:
    if value.denominator == 1:
        return str(value.numerator)
    return f"{value.numerator}/{value.denominator}"


def terminating_decimal(value: Fraction) -> str | None:
    """Return the exact decimal expansion, or ``None`` if it does not terminate."""

    denominator = value.denominator
    twos = fives = 0
    while denominator % 2 == 0:
        denominator //= 2
        twos += 1
    while denominator % 5 == 0:
        denominator //= 5
        fives += 1
    if denominator != 1:
        return None
    places = max(twos, fives)
    scaled = value * 10**places
    assert scaled.denominator == 1
    sign = "-" if scaled < 0 else ""
    digits = str(abs(scaled.numerator)).rjust(places + 1, "0")
    if places == 0:
        return sign + digits
    whole, fraction = digits[:-places], digits[-places:].rstrip("0")
    return sign + whole + ("." + fraction if fraction else "")


def exact_value(value: Fraction) -> dict[str, str | None]:
    return {"rational": rational_text(value), "decimal": terminating_decimal(value)}


@dataclass(frozen=True)
class DimensionalQuantity:
    value_text: str
    value: Fraction
    unit: str
    kind: str

    @classmethod
    def from_dict(cls, raw: Any, *, field: str) -> DimensionalQuantity:
        if not isinstance(raw, dict):
            raise InputError(f"{field} must be an object")
        unknown = sorted(set(raw) - {"value", "unit", "kind"})
        if unknown:
            raise InputError(
                f"{field} contains unsupported fields: {', '.join(unknown)}"
            )
        missing = sorted({"value", "unit", "kind"} - set(raw))
        if missing:
            raise InputError(
                f"{field} is missing required fields: {', '.join(missing)}"
            )
        value = parse_exact(raw["value"], f"{field}.value")
        unit, kind = raw["unit"], raw["kind"]
        if not isinstance(kind, str) or kind not in KINDS:
            raise InputError(f"{field}.kind is unsupported: {kind!r}")
        if not isinstance(unit, str) or unit not in UNITS:
            raise InputError(f"{field}.unit is unsupported: {unit!r}")
        if UNITS[unit].dimension != KINDS[kind]:
            raise DimensionalityError(
                f"{field}: unit {unit!r} is incompatible with quantity kind {kind!r}"
            )
        return cls(raw["value"], value, unit, kind)

    @property
    def dimension(self) -> Dimension:
        return KINDS[self.kind]

    @property
    def si_value(self) -> Fraction:
        return self.value * UNITS[self.unit].si_factor

    def as_dict(self) -> dict[str, str]:
        return {"value": self.value_text, "unit": self.unit, "kind": self.kind}


def unit_registry_description() -> dict[str, Any]:
    return {
        "schema_version": QUANTITY_SCHEMA,
        "dimension_basis": ["length", "mass", "time", "temperature"],
        "kinds": {name: list(dimension) for name, dimension in sorted(KINDS.items())},
        "units": {
            code: {
                "dimension": list(item.dimension),
                "si_factor": rational_text(item.si_factor),
            }
            for code, item in sorted(UNITS.items())
        },
    }
