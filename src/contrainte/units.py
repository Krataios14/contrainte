from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any

from .canonical import decimal_text
from .errors import DimensionalityError, InputError


@dataclass(frozen=True)
class UnitDefinition:
    code: str
    kind: str
    si_factor: Decimal


_UNITS = {
    "1": UnitDefinition("1", "dimensionless", Decimal(1)),
    "m": UnitDefinition("m", "length", Decimal(1)),
    "mm": UnitDefinition("mm", "length", Decimal("0.001")),
    "cm": UnitDefinition("cm", "length", Decimal("0.01")),
    "m2": UnitDefinition("m2", "area", Decimal(1)),
    "mm2": UnitDefinition("mm2", "area", Decimal("0.000001")),
    "m3": UnitDefinition("m3", "volume", Decimal(1)),
    "mm3": UnitDefinition("mm3", "volume", Decimal("0.000000001")),
    "kg": UnitDefinition("kg", "mass", Decimal(1)),
    "g": UnitDefinition("g", "mass", Decimal("0.001")),
    "kg/m3": UnitDefinition("kg/m3", "density", Decimal(1)),
    "N": UnitDefinition("N", "force", Decimal(1)),
    "kN": UnitDefinition("kN", "force", Decimal(1000)),
    "Pa": UnitDefinition("Pa", "pressure", Decimal(1)),
    "kPa": UnitDefinition("kPa", "pressure", Decimal(1000)),
    "MPa": UnitDefinition("MPa", "pressure", Decimal(1000000)),
    "GPa": UnitDefinition("GPa", "pressure", Decimal(1000000000)),
    "s": UnitDefinition("s", "time", Decimal(1)),
    "min": UnitDefinition("min", "time", Decimal(60)),
    "h": UnitDefinition("h", "time", Decimal(3600)),
}


@dataclass(frozen=True)
class Quantity:
    value: Decimal
    unit: str
    kind: str

    def __post_init__(self) -> None:
        definition = _UNITS.get(self.unit)
        if definition is None:
            raise InputError(f"unsupported unit: {self.unit!r}")
        if definition.kind != self.kind:
            raise DimensionalityError(
                f"unit {self.unit!r} has kind {definition.kind!r}, not {self.kind!r}"
            )
        if not self.value.is_finite():
            raise InputError("quantity values must be finite")

    @classmethod
    def from_dict(cls, raw: Any, *, field: str = "quantity") -> Quantity:
        if not isinstance(raw, dict):
            raise InputError(f"{field} must be an object")
        unknown = sorted(set(raw) - {"value", "unit", "kind"})
        if unknown:
            raise InputError(
                f"{field} contains unsupported fields: {', '.join(unknown)}"
            )
        value = raw.get("value")
        unit = raw.get("unit")
        kind = raw.get("kind")
        if not isinstance(value, str):
            raise InputError(f"{field}.value must be a decimal string")
        if not isinstance(unit, str) or not isinstance(kind, str):
            raise InputError(f"{field}.unit and {field}.kind must be strings")
        try:
            parsed = Decimal(value)
        except InvalidOperation as exc:
            raise InputError(
                f"{field}.value is not a valid decimal: {value!r}"
            ) from exc
        return cls(parsed, unit, kind)

    @classmethod
    def si(cls, value: Decimal, kind: str) -> Quantity:
        unit = {
            "dimensionless": "1",
            "length": "m",
            "area": "m2",
            "volume": "m3",
            "mass": "kg",
            "density": "kg/m3",
            "force": "N",
            "pressure": "Pa",
            "time": "s",
        }.get(kind)
        if unit is None:
            raise InputError(f"no canonical SI unit configured for {kind!r}")
        return cls(value, unit, kind)

    @property
    def si_value(self) -> Decimal:
        return self.value * _UNITS[self.unit].si_factor

    def to(self, unit: str) -> Quantity:
        target = _UNITS.get(unit)
        if target is None:
            raise InputError(f"unsupported target unit: {unit!r}")
        if target.kind != self.kind:
            raise DimensionalityError(
                f"cannot convert {self.kind!r} quantity to {target.kind!r} unit {unit!r}"
            )
        return Quantity(self.si_value / target.si_factor, unit, self.kind)

    def require_positive(self, field: str) -> None:
        if self.value <= 0:
            raise InputError(f"{field} must be greater than zero")

    def as_dict(self) -> dict[str, str]:
        return {"value": decimal_text(self.value), "unit": self.unit, "kind": self.kind}
