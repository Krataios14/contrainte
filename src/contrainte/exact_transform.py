from __future__ import annotations

import re
from dataclasses import dataclass
from fractions import Fraction
from typing import Any

from .errors import InputError

EXACT_TRANSFORM_SCHEMA = "contrainte.exact-rigid-transform/0.1"
MAX_EXACT_SCALAR_CHARACTERS = 128

_AXES = ("x", "y", "z")
_BASIS_AXES = ("x_axis", "y_axis", "z_axis")
_RATIONAL_PATTERN = re.compile(r"^-?(?:0|[1-9][0-9]*)(?:/[1-9][0-9]*)?$")


def _rational_text(value: Fraction) -> str:
    if value.denominator == 1:
        return str(value.numerator)
    return f"{value.numerator}/{value.denominator}"


def _bounded_fraction(value: Any, field: str) -> Fraction:
    if type(value) is not Fraction:
        raise InputError(f"{field} must be an exact Fraction")
    if len(_rational_text(value)) > MAX_EXACT_SCALAR_CHARACTERS:
        raise InputError(
            f"{field} exceeds the {MAX_EXACT_SCALAR_CHARACTERS}-character "
            "exact scalar limit"
        )
    return value


def _parse_fraction(value: Any, field: str) -> Fraction:
    if (
        type(value) is not str
        or len(value) > MAX_EXACT_SCALAR_CHARACTERS
        or not _RATIONAL_PATTERN.fullmatch(value)
    ):
        raise InputError(
            f"{field} must be a canonical integer or reduced rational string"
        )
    numerator_text, separator, denominator_text = value.partition("/")
    parsed = Fraction(int(numerator_text), int(denominator_text) if separator else 1)
    if _rational_text(parsed) != value:
        raise InputError(f"{field} must be reduced and canonical")
    return parsed


def _require_exact_keys(raw: Any, expected: set[str], field: str) -> dict[str, Any]:
    if type(raw) is not dict:
        raise InputError(f"{field} must be an object")
    if any(type(key) is not str for key in raw):
        raise InputError(f"{field} field names must be strings")
    missing = sorted(expected - set(raw))
    unknown = sorted(set(raw) - expected)
    if missing:
        raise InputError(f"{field} is missing required fields: {', '.join(missing)}")
    if unknown:
        raise InputError(f"{field} contains unsupported fields: {', '.join(unknown)}")
    return raw


def _dot_coordinates(left: ExactVector3, right: ExactVector3) -> Fraction:
    return left.x * right.x + left.y * right.y + left.z * right.z


def _determinant_coordinates(
    x_axis: ExactVector3,
    y_axis: ExactVector3,
    z_axis: ExactVector3,
) -> Fraction:
    return (
        x_axis.x * (y_axis.y * z_axis.z - y_axis.z * z_axis.y)
        - x_axis.y * (y_axis.x * z_axis.z - y_axis.z * z_axis.x)
        + x_axis.z * (y_axis.x * z_axis.y - y_axis.y * z_axis.x)
    )


@dataclass(frozen=True, slots=True)
class ExactVector3:
    """A bounded, immutable three-dimensional rational vector."""

    x: Fraction
    y: Fraction
    z: Fraction

    def __init_subclass__(cls, **kwargs: Any) -> None:
        raise TypeError("ExactVector3 may not be subclassed")

    def __post_init__(self) -> None:
        for axis in _AXES:
            _bounded_fraction(getattr(self, axis), f"vector.{axis}")

    @classmethod
    def zero(cls) -> ExactVector3:
        return cls(Fraction(0), Fraction(0), Fraction(0))

    @classmethod
    def from_dict(cls, raw: Any, *, field: str) -> ExactVector3:
        values = _require_exact_keys(raw, set(_AXES), field)
        return cls(
            *(_parse_fraction(values[axis], f"{field}.{axis}") for axis in _AXES)
        )

    def as_dict(self) -> dict[str, str]:
        return {axis: _rational_text(getattr(self, axis)) for axis in _AXES}

    def __add__(self, other: ExactVector3) -> ExactVector3:
        if type(other) is not ExactVector3:
            return NotImplemented
        return ExactVector3(self.x + other.x, self.y + other.y, self.z + other.z)

    def __sub__(self, other: ExactVector3) -> ExactVector3:
        if type(other) is not ExactVector3:
            return NotImplemented
        return ExactVector3(self.x - other.x, self.y - other.y, self.z - other.z)

    def __neg__(self) -> ExactVector3:
        return ExactVector3(-self.x, -self.y, -self.z)

    def scale(self, scalar: Fraction) -> ExactVector3:
        factor = _bounded_fraction(scalar, "scalar")
        return ExactVector3(self.x * factor, self.y * factor, self.z * factor)

    def dot(self, other: ExactVector3) -> Fraction:
        if type(other) is not ExactVector3:
            raise InputError("dot product operand must be an ExactVector3")
        return _bounded_fraction(_dot_coordinates(self, other), "dot product result")

    def cross(self, other: ExactVector3) -> ExactVector3:
        if type(other) is not ExactVector3:
            raise InputError("cross product operand must be an ExactVector3")
        return ExactVector3(
            self.y * other.z - self.z * other.y,
            self.z * other.x - self.x * other.z,
            self.x * other.y - self.y * other.x,
        )


@dataclass(frozen=True, slots=True)
class ExactRotation3:
    """A proper rational orthonormal basis stored as column vectors."""

    x_axis: ExactVector3
    y_axis: ExactVector3
    z_axis: ExactVector3

    def __init_subclass__(cls, **kwargs: Any) -> None:
        raise TypeError("ExactRotation3 may not be subclassed")

    def __post_init__(self) -> None:
        axes = (self.x_axis, self.y_axis, self.z_axis)
        if not all(type(axis) is ExactVector3 for axis in axes):
            raise InputError("rotation basis axes must be ExactVector3 values")
        if any(_dot_coordinates(axis, axis) != 1 for axis in axes):
            raise InputError("rotation basis axes must be exact unit vectors")
        if any(
            _dot_coordinates(left, right) != 0
            for left, right in (
                (self.x_axis, self.y_axis),
                (self.x_axis, self.z_axis),
                (self.y_axis, self.z_axis),
            )
        ):
            raise InputError("rotation basis axes must be exactly orthogonal")
        if _determinant_coordinates(self.x_axis, self.y_axis, self.z_axis) != 1:
            raise InputError("rotation basis must be exactly right-handed")

    @classmethod
    def identity(cls) -> ExactRotation3:
        return cls(
            ExactVector3(Fraction(1), Fraction(0), Fraction(0)),
            ExactVector3(Fraction(0), Fraction(1), Fraction(0)),
            ExactVector3(Fraction(0), Fraction(0), Fraction(1)),
        )

    @classmethod
    def from_dict(cls, raw: Any, *, field: str) -> ExactRotation3:
        values = _require_exact_keys(raw, set(_BASIS_AXES), field)
        return cls(
            *(
                ExactVector3.from_dict(values[name], field=f"{field}.{name}")
                for name in _BASIS_AXES
            )
        )

    def as_dict(self) -> dict[str, dict[str, str]]:
        return {
            name: axis.as_dict()
            for name, axis in zip(
                _BASIS_AXES,
                (self.x_axis, self.y_axis, self.z_axis),
                strict=True,
            )
        }

    def apply(self, vector: ExactVector3) -> ExactVector3:
        if type(vector) is not ExactVector3:
            raise InputError("rotation operand must be an ExactVector3")
        return (
            self.x_axis.scale(vector.x)
            + self.y_axis.scale(vector.y)
            + self.z_axis.scale(vector.z)
        )

    def compose(self, other: ExactRotation3) -> ExactRotation3:
        """Return ``self * other``; ``other`` is applied first."""

        if type(other) is not ExactRotation3:
            raise InputError("rotation composition operand must be an ExactRotation3")
        return ExactRotation3(
            self.apply(other.x_axis),
            self.apply(other.y_axis),
            self.apply(other.z_axis),
        )

    def inverse(self) -> ExactRotation3:
        """Return the exact transpose, which is the inverse of a proper rotation."""

        return ExactRotation3(
            ExactVector3(self.x_axis.x, self.y_axis.x, self.z_axis.x),
            ExactVector3(self.x_axis.y, self.y_axis.y, self.z_axis.y),
            ExactVector3(self.x_axis.z, self.y_axis.z, self.z_axis.z),
        )


@dataclass(frozen=True, slots=True)
class ExactRigidTransform:
    """An exact local-to-parent rigid transform with millimetre translation."""

    translation: ExactVector3
    rotation: ExactRotation3
    unit: str = "mm"

    def __init_subclass__(cls, **kwargs: Any) -> None:
        raise TypeError("ExactRigidTransform may not be subclassed")

    def __post_init__(self) -> None:
        if type(self.translation) is not ExactVector3:
            raise InputError("transform.translation must be an ExactVector3")
        if type(self.rotation) is not ExactRotation3:
            raise InputError("transform.rotation must be an ExactRotation3")
        if type(self.unit) is not str or self.unit != "mm":
            raise InputError("transform.unit must be 'mm'")

    @classmethod
    def identity(cls) -> ExactRigidTransform:
        return cls(ExactVector3.zero(), ExactRotation3.identity())

    @classmethod
    def from_dict(cls, raw: Any, *, field: str = "transform") -> ExactRigidTransform:
        values = _require_exact_keys(
            raw, {"schema_version", "unit", "translation", "basis"}, field
        )
        if (
            type(values["schema_version"]) is not str
            or values["schema_version"] != EXACT_TRANSFORM_SCHEMA
        ):
            raise InputError(
                f"{field}.schema_version must be {EXACT_TRANSFORM_SCHEMA!r}"
            )
        if type(values["unit"]) is not str or values["unit"] != "mm":
            raise InputError(f"{field}.unit must be 'mm'")
        return cls(
            translation=ExactVector3.from_dict(
                values["translation"], field=f"{field}.translation"
            ),
            rotation=ExactRotation3.from_dict(values["basis"], field=f"{field}.basis"),
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema_version": EXACT_TRANSFORM_SCHEMA,
            "unit": self.unit,
            "translation": self.translation.as_dict(),
            "basis": self.rotation.as_dict(),
        }

    def apply_point(self, point: ExactVector3) -> ExactVector3:
        """Map a local point into this transform's parent frame."""

        if type(point) is not ExactVector3:
            raise InputError("point must be an ExactVector3")
        return self.rotation.apply(point) + self.translation

    def compose(self, other: ExactRigidTransform) -> ExactRigidTransform:
        """Return ``self * other``; ``other`` is applied first."""

        if type(other) is not ExactRigidTransform:
            raise InputError("composition operand must be an ExactRigidTransform")
        if self.unit != other.unit:  # pragma: no cover - only mm is constructible
            raise InputError("transform units must match for composition")
        return ExactRigidTransform(
            translation=self.apply_point(other.translation),
            rotation=self.rotation.compose(other.rotation),
            unit=self.unit,
        )

    def inverse(self) -> ExactRigidTransform:
        inverse_rotation = self.rotation.inverse()
        return ExactRigidTransform(
            translation=inverse_rotation.apply(-self.translation),
            rotation=inverse_rotation,
            unit=self.unit,
        )

    def relative_to(self, reference: ExactRigidTransform) -> ExactRigidTransform:
        """Express this transform in ``reference`` coordinates."""

        if type(reference) is not ExactRigidTransform:
            raise InputError("reference must be an ExactRigidTransform")
        return reference.inverse().compose(self)
