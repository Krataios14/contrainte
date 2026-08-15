from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation, localcontext
from typing import Any

from .canonical import decimal_text
from .errors import ExecutionError, InputError
from .units import Quantity

KERNEL_REPORT_QUANTUM = Decimal("0.000000001")


def _length(raw: Any, field: str) -> Quantity:
    value = Quantity.from_dict(raw, field=field)
    if value.kind != "length":
        raise InputError(f"{field} must have kind 'length'")
    return value


def _angle(value: Any, field: str) -> Decimal:
    if not isinstance(value, str):
        raise InputError(f"{field} must be a decimal string in degrees")
    try:
        angle = Decimal(value)
    except InvalidOperation as exc:
        raise InputError(f"{field} is not a valid decimal angle") from exc
    if not angle.is_finite() or angle < -180 or angle > 180:
        raise InputError(f"{field} must be finite and within [-180, 180] degrees")
    return angle


@dataclass(frozen=True)
class RigidTransform:
    x: Quantity
    y: Quantity
    z: Quantity
    rotation_xyz_deg: tuple[Decimal, Decimal, Decimal]

    @classmethod
    def from_dict(cls, raw: Any, *, field: str) -> RigidTransform:
        if not isinstance(raw, dict):
            raise InputError(f"{field} must be an object")
        if set(raw) != {"translation", "rotation_xyz_deg"}:
            raise InputError(
                f"{field} must contain exactly translation and rotation_xyz_deg"
            )
        translation = raw.get("translation")
        if not isinstance(translation, dict) or set(translation) != {"x", "y", "z"}:
            raise InputError(f"{field}.translation must contain exactly x, y, and z")
        rotation = raw.get("rotation_xyz_deg")
        if not isinstance(rotation, list) or len(rotation) != 3:
            raise InputError(f"{field}.rotation_xyz_deg must contain three angles")
        parsed_rotation = tuple(
            _angle(item, f"{field}.rotation_xyz_deg[{index}]")
            for index, item in enumerate(rotation)
        )
        return cls(
            x=_length(translation["x"], f"{field}.translation.x"),
            y=_length(translation["y"], f"{field}.translation.y"),
            z=_length(translation["z"], f"{field}.translation.z"),
            rotation_xyz_deg=parsed_rotation,  # type: ignore[arg-type]
        )

    @classmethod
    def identity(cls) -> RigidTransform:
        zero = Quantity(Decimal(0), "mm", "length")
        return cls(zero, zero, zero, (Decimal(0), Decimal(0), Decimal(0)))

    def as_dict(self) -> dict[str, Any]:
        return {
            "translation": {
                "x": self.x.as_dict(),
                "y": self.y.as_dict(),
                "z": self.z.as_dict(),
            },
            "rotation_xyz_deg": [decimal_text(item) for item in self.rotation_xyz_deg],
        }


def kernel_measurement(value: Any) -> Decimal:
    measurement = value if isinstance(value, Decimal) else Decimal(str(value))
    if not measurement.is_finite():
        raise ExecutionError("Open CASCADE returned a non-finite measurement")
    with localcontext() as context:
        context.prec = 50
        return measurement.quantize(KERNEL_REPORT_QUANTUM)
