from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from enum import Enum
from fractions import Fraction
from types import MappingProxyType
from typing import Any

from .canonical import decimal_text, digest
from .errors import InputError

COMPONENT_SCHEMA_V1 = "contrainte.component-manifest/0.1"
COMPONENT_SCHEMA = "contrainte.component-manifest/0.2"
COMPONENT_SCHEMA_V3 = "contrainte.component-manifest/0.3"
COMPONENT_SCHEMA_V4 = "contrainte.component-manifest/0.4"
_SUPPORTED_COMPONENT_SCHEMAS = {
    COMPONENT_SCHEMA_V1,
    COMPONENT_SCHEMA,
    COMPONENT_SCHEMA_V3,
    COMPONENT_SCHEMA_V4,
}
_DIGEST_PATTERN = re.compile(r"^sha256:[0-9a-f]{64}$")
_SAFE_FEATURE_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
_CANONICAL_DECIMAL_PATTERN = re.compile(r"^-?(?:0|[1-9][0-9]*)(?:\.[0-9]*[1-9])?$")
_RATIONAL_PATTERN = re.compile(r"^-?(?:0|[1-9][0-9]*)(?:/[1-9][0-9]*)?$")
_MAX_EXACT_SCALAR_CHARACTERS = 128
_MAX_ATTACHMENT_FEATURE_ID_CHARACTERS = 128
_MAX_COMPONENT_INTERFACES = 64


class LifecycleState(str, Enum):
    CONCEPT = "concept"
    RELEASED = "released"
    RETIRED = "retired"


class Qualification(str, Enum):
    UNQUALIFIED_DEMONSTRATION = "unqualified_demonstration"
    ENGINEERING_REVIEWED = "engineering_reviewed"
    QUALIFIED_FOR_INTENDED_USE = "qualified_for_intended_use"


class ArtifactRole(str, Enum):
    ENGINEERING_BUNDLE = "engineering_bundle"
    EXACT_GEOMETRY = "exact_geometry"
    DRAWING = "drawing"
    MESH = "mesh"
    SCENE = "scene"
    MATERIAL_RECORD = "material_record"
    SOLVER_CAPSULE = "solver_capsule"
    TEST_RECORD = "test_record"


class InterfaceKind(str, Enum):
    MECHANICAL = "mechanical"
    MATERIAL = "material"
    ELECTRICAL = "electrical"
    UTILITY = "utility"
    CONTROL = "control"
    SAFETY = "safety"
    SPATIAL = "spatial"


class InterfaceDirection(str, Enum):
    INPUT = "input"
    OUTPUT = "output"
    BIDIRECTIONAL = "bidirectional"


class InterfaceAttachmentKind(str, Enum):
    PRISMATIC_STOCK_FACE = "prismatic_stock_face"
    PRISMATIC_THROUGH_HOLE = "prismatic_through_hole"


class InterfaceAttachmentRole(str, Enum):
    NEGATIVE_X = "negative_x"
    POSITIVE_X = "positive_x"
    NEGATIVE_Y = "negative_y"
    POSITIVE_Y = "positive_y"
    NEGATIVE_Z = "negative_z"
    POSITIVE_Z = "positive_z"
    CYLINDRICAL_WALL = "cylindrical_wall"


class InterfaceAttachmentSurfaceType(str, Enum):
    PLANE = "plane"
    CYLINDER = "cylinder"


_PRISMATIC_STOCK_FACE_DIRECTIONS = {
    InterfaceAttachmentRole.NEGATIVE_X: (
        Fraction(-1),
        Fraction(0),
        Fraction(0),
    ),
    InterfaceAttachmentRole.POSITIVE_X: (
        Fraction(1),
        Fraction(0),
        Fraction(0),
    ),
    InterfaceAttachmentRole.NEGATIVE_Y: (
        Fraction(0),
        Fraction(-1),
        Fraction(0),
    ),
    InterfaceAttachmentRole.POSITIVE_Y: (
        Fraction(0),
        Fraction(1),
        Fraction(0),
    ),
    InterfaceAttachmentRole.NEGATIVE_Z: (
        Fraction(0),
        Fraction(0),
        Fraction(-1),
    ),
    InterfaceAttachmentRole.POSITIVE_Z: (
        Fraction(0),
        Fraction(0),
        Fraction(1),
    ),
}
_PRISMATIC_THROUGH_HOLE_DIRECTION = (
    Fraction(0),
    Fraction(0),
    Fraction(1),
)


def _required_string(raw: Mapping[str, Any], name: str, field: str) -> str:
    value = raw.get(name)
    if not isinstance(value, str) or not value:
        raise InputError(f"{field}.{name} must be a non-empty string")
    return value


def _reject_unknown_keys(raw: Mapping[str, Any], allowed: set[str], field: str) -> None:
    unknown = sorted(set(raw) - allowed)
    if unknown:
        raise InputError(f"{field} contains unsupported fields: {', '.join(unknown)}")


def _digest(value: str, field: str) -> str:
    if not _DIGEST_PATTERN.fullmatch(value):
        raise InputError(f"{field} must be a lowercase SHA-256 digest")
    return value


def _string_map(raw: Any, field: str) -> Mapping[str, str]:
    if not isinstance(raw, dict) or not all(
        isinstance(key, str) and isinstance(value, str) for key, value in raw.items()
    ):
        raise InputError(f"{field} must map strings to strings")
    return dict(raw)


def _finite_decimal(value: Any, field: str) -> Decimal:
    if not isinstance(value, str):
        raise InputError(f"{field} must be a decimal string")
    try:
        parsed = Decimal(value)
    except InvalidOperation as exc:
        raise InputError(f"{field} is not a valid decimal: {value!r}") from exc
    if not parsed.is_finite():
        raise InputError(f"{field} must be finite")
    return parsed


def _canonical_decimal(value: Any, field: str) -> Decimal:
    if (
        not isinstance(value, str)
        or len(value) > _MAX_EXACT_SCALAR_CHARACTERS
        or not _CANONICAL_DECIMAL_PATTERN.fullmatch(value)
    ):
        raise InputError(f"{field} must be a canonical decimal string")
    parsed = _finite_decimal(value, field)
    if decimal_text(parsed) != value:
        raise InputError(f"{field} must be a canonical decimal string")
    return parsed


def _exact_rational(value: Any, field: str) -> Fraction:
    if (
        not isinstance(value, str)
        or len(value) > _MAX_EXACT_SCALAR_CHARACTERS
        or not _RATIONAL_PATTERN.fullmatch(value)
    ):
        raise InputError(
            f"{field} must be a canonical integer or reduced rational string"
        )
    numerator_text, separator, denominator_text = value.partition("/")
    numerator = int(numerator_text)
    denominator = int(denominator_text) if separator else 1
    parsed = Fraction(numerator, denominator)
    if _rational_text(parsed) != value:
        raise InputError(f"{field} must be reduced and canonical")
    return parsed


def _rational_text(value: Fraction) -> str:
    if value.denominator == 1:
        return str(value.numerator)
    return f"{value.numerator}/{value.denominator}"


def _vector(raw: Any, field: str) -> tuple[Fraction, Fraction, Fraction]:
    if not isinstance(raw, dict) or set(raw) != {"x", "y", "z"}:
        raise InputError(f"{field} must contain exactly x, y, and z")
    return tuple(
        _exact_rational(raw[axis], f"{field}.{axis}") for axis in ("x", "y", "z")
    )  # type: ignore[return-value]


def _dot(
    left: tuple[Fraction, Fraction, Fraction],
    right: tuple[Fraction, Fraction, Fraction],
) -> Fraction:
    return sum((a * b for a, b in zip(left, right, strict=True)), Fraction(0))


def _determinant(
    x_axis: tuple[Fraction, Fraction, Fraction],
    y_axis: tuple[Fraction, Fraction, Fraction],
    z_axis: tuple[Fraction, Fraction, Fraction],
) -> Fraction:
    return (
        x_axis[0] * (y_axis[1] * z_axis[2] - y_axis[2] * z_axis[1])
        - x_axis[1] * (y_axis[0] * z_axis[2] - y_axis[2] * z_axis[0])
        + x_axis[2] * (y_axis[0] * z_axis[1] - y_axis[1] * z_axis[0])
    )


@dataclass(frozen=True)
class ExactInterfaceFrame:
    """An exact engineering-bundle-local origin and rational orthonormal basis."""

    reference: str
    unit: str
    origin: Mapping[str, Decimal]
    x_axis: tuple[Fraction, Fraction, Fraction]
    y_axis: tuple[Fraction, Fraction, Fraction]
    z_axis: tuple[Fraction, Fraction, Fraction]

    def __post_init__(self) -> None:
        if self.reference != "engineering_bundle":
            raise InputError("interface_frame.reference must be 'engineering_bundle'")
        if self.unit != "mm":
            raise InputError("interface_frame.unit must be 'mm'")
        if (
            not isinstance(self.origin, Mapping)
            or set(self.origin)
            != {
                "x",
                "y",
                "z",
            }
            or not all(
                isinstance(self.origin[axis], Decimal)
                and self.origin[axis].is_finite()
                and len(decimal_text(self.origin[axis])) <= _MAX_EXACT_SCALAR_CHARACTERS
                for axis in ("x", "y", "z")
            )
        ):
            raise InputError(
                "interface_frame.origin must contain finite Decimal x, y, and z values"
            )
        object.__setattr__(self, "origin", MappingProxyType(dict(self.origin)))
        axes = (self.x_axis, self.y_axis, self.z_axis)
        if any(
            not isinstance(vector, tuple)
            or len(vector) != 3
            or not all(isinstance(value, Fraction) for value in vector)
            for vector in axes
        ):
            raise InputError(
                "interface_frame basis axes must contain three exact Fraction values"
            )
        if any(
            len(_rational_text(value)) > _MAX_EXACT_SCALAR_CHARACTERS
            for vector in axes
            for value in vector
        ):
            raise InputError(
                "interface_frame basis values exceed the exact scalar size limit"
            )
        if any(_dot(vector, vector) != 1 for vector in axes):
            raise InputError("interface_frame basis axes must be exact unit vectors")
        if any(
            _dot(left, right) != 0
            for left, right in (
                (self.x_axis, self.y_axis),
                (self.x_axis, self.z_axis),
                (self.y_axis, self.z_axis),
            )
        ):
            raise InputError("interface_frame basis axes must be exactly orthogonal")
        if _determinant(self.x_axis, self.y_axis, self.z_axis) != 1:
            raise InputError("interface_frame basis must be exactly right-handed")

    @classmethod
    def from_dict(cls, raw: Any, *, field: str) -> ExactInterfaceFrame:
        if not isinstance(raw, dict):
            raise InputError(f"{field} must be an object")
        _reject_unknown_keys(raw, {"reference", "unit", "origin", "basis"}, field)
        reference = _required_string(raw, "reference", field)
        if reference != "engineering_bundle":
            raise InputError(f"{field}.reference must be 'engineering_bundle'")
        unit = _required_string(raw, "unit", field)
        if unit != "mm":
            raise InputError(f"{field}.unit must be 'mm'")
        origin_raw = raw.get("origin")
        if not isinstance(origin_raw, dict) or set(origin_raw) != {"x", "y", "z"}:
            raise InputError(f"{field}.origin must contain exactly x, y, and z")
        origin = {
            axis: _canonical_decimal(origin_raw[axis], f"{field}.origin.{axis}")
            for axis in ("x", "y", "z")
        }
        basis_raw = raw.get("basis")
        if not isinstance(basis_raw, dict) or set(basis_raw) != {
            "x_axis",
            "y_axis",
            "z_axis",
        }:
            raise InputError(
                f"{field}.basis must contain exactly x_axis, y_axis, and z_axis"
            )
        axes = {
            name: _vector(basis_raw[name], f"{field}.basis.{name}")
            for name in ("x_axis", "y_axis", "z_axis")
        }
        for name, vector in axes.items():
            if _dot(vector, vector) != 1:
                raise InputError(f"{field}.basis.{name} must be an exact unit vector")
        for left, right in (
            ("x_axis", "y_axis"),
            ("x_axis", "z_axis"),
            ("y_axis", "z_axis"),
        ):
            if _dot(axes[left], axes[right]) != 0:
                raise InputError(
                    f"{field}.basis.{left} and {right} must be exactly orthogonal"
                )
        if _determinant(axes["x_axis"], axes["y_axis"], axes["z_axis"]) != 1:
            raise InputError(f"{field}.basis must be exactly right-handed")
        return cls(
            reference,
            unit,
            origin,
            axes["x_axis"],
            axes["y_axis"],
            axes["z_axis"],
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "reference": self.reference,
            "unit": self.unit,
            "origin": {
                axis: decimal_text(self.origin[axis]) for axis in ("x", "y", "z")
            },
            "basis": {
                name: {
                    axis: _rational_text(value)
                    for axis, value in zip(("x", "y", "z"), vector, strict=True)
                }
                for name, vector in (
                    ("x_axis", self.x_axis),
                    ("y_axis", self.y_axis),
                    ("z_axis", self.z_axis),
                )
            },
        }

    def require_origin_within(self, bounds: ExactGeometryBounds, *, field: str) -> None:
        for axis in ("x", "y", "z"):
            if not bounds.minimum[axis] <= self.origin[axis] <= bounds.maximum[axis]:
                raise InputError(
                    f"{field}.origin.{axis} must lie within or on geometry_bounds"
                )


@dataclass(frozen=True)
class ExactGeometryBounds:
    """Axis-aligned bounds reproduced from the exact engineering geometry."""

    frame: str
    unit: str
    minimum: Mapping[str, Decimal]
    maximum: Mapping[str, Decimal]

    @classmethod
    def from_dict(
        cls, raw: Any, *, field: str, canonical: bool = False
    ) -> ExactGeometryBounds:
        if not isinstance(raw, dict):
            raise InputError(f"{field} must be an object")
        _reject_unknown_keys(raw, {"frame", "unit", "minimum", "maximum"}, field)
        frame = _required_string(raw, "frame", field)
        if frame != "engineering_bundle":
            raise InputError(f"{field}.frame must be 'engineering_bundle'")
        unit = _required_string(raw, "unit", field)
        if unit != "mm":
            raise InputError(f"{field}.unit must be 'mm'")
        axes: dict[str, Mapping[str, Decimal]] = {}
        for bound in ("minimum", "maximum"):
            values = raw.get(bound)
            if not isinstance(values, dict) or set(values) != {"x", "y", "z"}:
                raise InputError(f"{field}.{bound} must contain exactly x, y, and z")
            axes[bound] = {
                axis: (
                    _canonical_decimal(values[axis], f"{field}.{bound}.{axis}")
                    if canonical
                    else _finite_decimal(values[axis], f"{field}.{bound}.{axis}")
                )
                for axis in ("x", "y", "z")
            }
        for axis in ("x", "y", "z"):
            if axes["maximum"][axis] <= axes["minimum"][axis]:
                raise InputError(
                    f"{field}.maximum.{axis} must be greater than minimum.{axis}"
                )
        return cls(frame, unit, axes["minimum"], axes["maximum"])

    @property
    def size_mm(self) -> Mapping[str, Decimal]:
        return {
            axis: self.maximum[axis] - self.minimum[axis] for axis in ("x", "y", "z")
        }

    def as_dict(self) -> dict[str, Any]:
        return {
            "frame": self.frame,
            "unit": self.unit,
            "minimum": {
                axis: decimal_text(self.minimum[axis]) for axis in ("x", "y", "z")
            },
            "maximum": {
                axis: decimal_text(self.maximum[axis]) for axis in ("x", "y", "z")
            },
        }


@dataclass(frozen=True)
class ArtifactRef:
    artifact_id: str
    role: ArtifactRole
    media_type: str
    digest: str
    locator: str

    @classmethod
    def from_dict(cls, raw: Any, *, field: str) -> ArtifactRef:
        if not isinstance(raw, dict):
            raise InputError(f"{field} must be an object")
        _reject_unknown_keys(
            raw,
            {"artifact_id", "role", "media_type", "digest", "locator"},
            field,
        )
        artifact_id = _required_string(raw, "artifact_id", field)
        try:
            role = ArtifactRole(_required_string(raw, "role", field))
        except ValueError as exc:
            raise InputError(
                f"{field}.role is unsupported: {raw.get('role')!r}"
            ) from exc
        return cls(
            artifact_id=artifact_id,
            role=role,
            media_type=_required_string(raw, "media_type", field),
            digest=_digest(_required_string(raw, "digest", field), f"{field}.digest"),
            locator=_required_string(raw, "locator", field),
        )

    def as_dict(self) -> dict[str, str]:
        return {
            "artifact_id": self.artifact_id,
            "role": self.role.value,
            "media_type": self.media_type,
            "digest": self.digest,
            "locator": self.locator,
        }


@dataclass(frozen=True)
class InterfaceAttachmentSelector:
    """An authored prismatic feature and its canonical attachment role."""

    kind: InterfaceAttachmentKind
    feature_id: str
    role: InterfaceAttachmentRole

    def __post_init__(self) -> None:
        if not isinstance(self.kind, InterfaceAttachmentKind):
            raise InputError("attachment_selector.kind must be an attachment kind")
        if (
            not isinstance(self.feature_id, str)
            or not self.feature_id
            or len(self.feature_id) > _MAX_ATTACHMENT_FEATURE_ID_CHARACTERS
            or not _SAFE_FEATURE_ID_PATTERN.fullmatch(self.feature_id)
        ):
            raise InputError(
                "attachment_selector.feature_id must be a bounded safe identifier"
            )
        if not isinstance(self.role, InterfaceAttachmentRole):
            raise InputError("attachment_selector.role must be an attachment role")
        if self.kind is InterfaceAttachmentKind.PRISMATIC_STOCK_FACE:
            if self.feature_id != "stock":
                raise InputError(
                    "prismatic_stock_face attachment selector feature_id must be 'stock'"
                )
            if self.role not in _PRISMATIC_STOCK_FACE_DIRECTIONS:
                raise InputError(
                    "prismatic_stock_face attachment selector role is unsupported"
                )
        elif self.kind is InterfaceAttachmentKind.PRISMATIC_THROUGH_HOLE:
            if self.role is not InterfaceAttachmentRole.CYLINDRICAL_WALL:
                raise InputError(
                    "prismatic_through_hole attachment selector role must be "
                    "'cylindrical_wall'"
                )

    @classmethod
    def from_dict(cls, raw: Any, *, field: str) -> InterfaceAttachmentSelector:
        if not isinstance(raw, dict):
            raise InputError(f"{field} must be an object")
        _reject_unknown_keys(raw, {"kind", "feature_id", "role"}, field)
        try:
            kind = InterfaceAttachmentKind(_required_string(raw, "kind", field))
        except ValueError as exc:
            raise InputError(
                f"{field}.kind is unsupported: {raw.get('kind')!r}"
            ) from exc
        try:
            role = InterfaceAttachmentRole(_required_string(raw, "role", field))
        except ValueError as exc:
            raise InputError(
                f"{field}.role is unsupported: {raw.get('role')!r}"
            ) from exc
        return cls(
            kind=kind,
            feature_id=_required_string(raw, "feature_id", field),
            role=role,
        )

    def as_dict(self) -> dict[str, str]:
        return {
            "kind": self.kind.value,
            "feature_id": self.feature_id,
            "role": self.role.value,
        }


@dataclass(frozen=True)
class InterfaceAttachmentEvidence:
    """Strict derived evidence for one uniquely reproduced kernel face."""

    source_feature_digest: str
    matched_face_count: int
    surface_type: InterfaceAttachmentSurfaceType
    origin_on_surface: bool
    orientation_matches: bool
    characteristic_point_mm: tuple[Decimal, Decimal, Decimal]
    direction: tuple[Fraction, Fraction, Fraction]
    radius_mm: Decimal | None = None

    def __post_init__(self) -> None:
        if not isinstance(
            self.source_feature_digest, str
        ) or not _DIGEST_PATTERN.fullmatch(self.source_feature_digest):
            raise InputError(
                "attachment_evidence.source_feature_digest must be a lowercase "
                "SHA-256 digest"
            )
        if type(self.matched_face_count) is not int or self.matched_face_count != 1:
            raise InputError("attachment_evidence.matched_face_count must be exactly 1")
        if not isinstance(self.surface_type, InterfaceAttachmentSurfaceType):
            raise InputError(
                "attachment_evidence.surface_type must be an attachment surface type"
            )
        if type(self.origin_on_surface) is not bool or not self.origin_on_surface:
            raise InputError("attachment_evidence.origin_on_surface must be true")
        if type(self.orientation_matches) is not bool or not self.orientation_matches:
            raise InputError("attachment_evidence.orientation_matches must be true")
        if (
            not isinstance(self.characteristic_point_mm, tuple)
            or len(self.characteristic_point_mm) != 3
            or not all(
                isinstance(value, Decimal)
                and value.is_finite()
                and len(decimal_text(value)) <= _MAX_EXACT_SCALAR_CHARACTERS
                for value in self.characteristic_point_mm
            )
        ):
            raise InputError(
                "attachment_evidence.characteristic_point_mm must contain three "
                "bounded finite Decimals"
            )
        if (
            not isinstance(self.direction, tuple)
            or len(self.direction) != 3
            or not all(
                isinstance(value, Fraction)
                and len(_rational_text(value)) <= _MAX_EXACT_SCALAR_CHARACTERS
                for value in self.direction
            )
        ):
            raise InputError(
                "attachment_evidence.direction must contain three bounded exact "
                "Fractions"
            )
        if _dot(self.direction, self.direction) != 1:
            raise InputError(
                "attachment_evidence.direction must be an exact unit vector"
            )
        if self.radius_mm is not None and (
            not isinstance(self.radius_mm, Decimal)
            or not self.radius_mm.is_finite()
            or self.radius_mm <= 0
            or len(decimal_text(self.radius_mm)) > _MAX_EXACT_SCALAR_CHARACTERS
        ):
            raise InputError(
                "attachment_evidence.radius_mm must be a bounded positive finite Decimal"
            )
        if self.surface_type is InterfaceAttachmentSurfaceType.PLANE:
            if self.radius_mm is not None:
                raise InputError("plane attachment evidence cannot declare radius_mm")
        elif self.radius_mm is None:
            raise InputError("cylinder attachment evidence requires radius_mm")

    @classmethod
    def from_dict(cls, raw: Any, *, field: str) -> InterfaceAttachmentEvidence:
        if not isinstance(raw, dict):
            raise InputError(f"{field} must be an object")
        _reject_unknown_keys(
            raw,
            {
                "source_feature_digest",
                "matched_face_count",
                "surface_type",
                "origin_on_surface",
                "orientation_matches",
                "characteristic_point_mm",
                "direction",
                "radius_mm",
            },
            field,
        )
        source_feature_digest = _digest(
            _required_string(raw, "source_feature_digest", field),
            f"{field}.source_feature_digest",
        )
        matched_face_count = raw.get("matched_face_count")
        if type(matched_face_count) is not int or matched_face_count != 1:
            raise InputError(f"{field}.matched_face_count must be exactly 1")
        try:
            surface_type = InterfaceAttachmentSurfaceType(
                _required_string(raw, "surface_type", field)
            )
        except ValueError as exc:
            raise InputError(
                f"{field}.surface_type is unsupported: {raw.get('surface_type')!r}"
            ) from exc
        origin_on_surface = raw.get("origin_on_surface")
        if type(origin_on_surface) is not bool or not origin_on_surface:
            raise InputError(f"{field}.origin_on_surface must be true")
        orientation_matches = raw.get("orientation_matches")
        if type(orientation_matches) is not bool or not orientation_matches:
            raise InputError(f"{field}.orientation_matches must be true")
        point_raw = raw.get("characteristic_point_mm")
        if not isinstance(point_raw, dict) or set(point_raw) != {"x", "y", "z"}:
            raise InputError(
                f"{field}.characteristic_point_mm must contain exactly x, y, and z"
            )
        characteristic_point_mm = tuple(
            _canonical_decimal(
                point_raw[axis], f"{field}.characteristic_point_mm.{axis}"
            )
            for axis in ("x", "y", "z")
        )
        direction = _vector(raw.get("direction"), f"{field}.direction")
        radius_mm = (
            _canonical_decimal(raw["radius_mm"], f"{field}.radius_mm")
            if "radius_mm" in raw
            else None
        )
        return cls(
            source_feature_digest=source_feature_digest,
            matched_face_count=matched_face_count,
            surface_type=surface_type,
            origin_on_surface=origin_on_surface,
            orientation_matches=orientation_matches,
            characteristic_point_mm=characteristic_point_mm,  # type: ignore[arg-type]
            direction=direction,
            radius_mm=radius_mm,
        )

    def as_dict(self) -> dict[str, Any]:
        document = {
            "source_feature_digest": self.source_feature_digest,
            "matched_face_count": self.matched_face_count,
            "surface_type": self.surface_type.value,
            "origin_on_surface": self.origin_on_surface,
            "orientation_matches": self.orientation_matches,
            "characteristic_point_mm": {
                axis: decimal_text(value)
                for axis, value in zip(
                    ("x", "y", "z"), self.characteristic_point_mm, strict=True
                )
            },
            "direction": {
                axis: _rational_text(value)
                for axis, value in zip(("x", "y", "z"), self.direction, strict=True)
            },
        }
        if self.radius_mm is not None:
            document["radius_mm"] = decimal_text(self.radius_mm)
        return document


@dataclass(frozen=True)
class InterfaceAttachment:
    selector: InterfaceAttachmentSelector
    evidence: InterfaceAttachmentEvidence | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.selector, InterfaceAttachmentSelector):
            raise InputError("interface attachment selector has an invalid type")
        if self.evidence is not None and not isinstance(
            self.evidence, InterfaceAttachmentEvidence
        ):
            raise InputError("interface attachment evidence has an invalid type")
        if self.evidence is None:
            return
        if self.selector.kind is InterfaceAttachmentKind.PRISMATIC_STOCK_FACE:
            expected_surface = InterfaceAttachmentSurfaceType.PLANE
            expected_direction = _PRISMATIC_STOCK_FACE_DIRECTIONS[self.selector.role]
        else:
            expected_surface = InterfaceAttachmentSurfaceType.CYLINDER
            expected_direction = _PRISMATIC_THROUGH_HOLE_DIRECTION
        if self.evidence.surface_type is not expected_surface:
            raise InputError(
                "interface attachment evidence surface_type does not match its selector"
            )
        if self.evidence.direction != expected_direction:
            raise InputError(
                "interface attachment evidence direction does not match its canonical role"
            )

    @classmethod
    def from_dict(
        cls,
        raw: Any,
        *,
        field: str,
        evidence_required: bool | None = None,
    ) -> InterfaceAttachment:
        if evidence_required is not None and type(evidence_required) is not bool:
            raise InputError("attachment evidence context flag must be boolean or None")
        if not isinstance(raw, dict):
            raise InputError(f"{field} must be an object")
        allowed = {"selector"}
        if evidence_required is not False:
            allowed.add("evidence")
        _reject_unknown_keys(raw, allowed, field)
        if evidence_required is True and "evidence" not in raw:
            raise InputError(f"{field}.evidence is required")
        return cls(
            selector=InterfaceAttachmentSelector.from_dict(
                raw.get("selector"), field=f"{field}.selector"
            ),
            evidence=(
                InterfaceAttachmentEvidence.from_dict(
                    raw["evidence"], field=f"{field}.evidence"
                )
                if "evidence" in raw
                else None
            ),
        )

    def as_dict(self, *, include_evidence: bool = True) -> dict[str, Any]:
        if type(include_evidence) is not bool:
            raise InputError("include_evidence must be boolean")
        document = {"selector": self.selector.as_dict()}
        if include_evidence and self.evidence is not None:
            document["evidence"] = self.evidence.as_dict()
        return document


@dataclass(frozen=True)
class ComponentInterface:
    interface_id: str
    kind: InterfaceKind
    direction: InterfaceDirection
    medium: str
    properties: Mapping[str, str]
    frame: ExactInterfaceFrame | None = None
    attachment: InterfaceAttachment | None = None

    def __post_init__(self) -> None:
        if self.attachment is None:
            return
        if not isinstance(self.attachment, InterfaceAttachment):
            raise InputError("component interface attachment has an invalid type")
        if self.frame is None:
            raise InputError("a topology-backed interface attachment requires a frame")
        evidence = self.attachment.evidence
        if evidence is None:
            return
        frame_origin = tuple(self.frame.origin[axis] for axis in ("x", "y", "z"))
        if evidence.characteristic_point_mm != frame_origin:
            raise InputError(
                "interface attachment characteristic_point_mm must equal the frame origin"
            )
        if evidence.direction != self.frame.z_axis:
            raise InputError(
                "interface attachment direction must equal the frame z_axis"
            )

    @classmethod
    def from_dict(
        cls,
        raw: Any,
        *,
        field: str,
        frame_required: bool | None = None,
        attachment_required: bool | None = None,
        attachment_evidence_required: bool | None = None,
    ) -> ComponentInterface:
        for name, value in (
            ("frame_required", frame_required),
            ("attachment_required", attachment_required),
            ("attachment_evidence_required", attachment_evidence_required),
        ):
            if value is not None and type(value) is not bool:
                raise InputError(f"{name} context flag must be boolean or None")
        if attachment_required is False and attachment_evidence_required is True:
            raise InputError(
                "attachment evidence cannot be required when attachment is forbidden"
            )
        if attachment_evidence_required is True:
            attachment_required = True
        if not isinstance(raw, dict):
            raise InputError(f"{field} must be an object")
        allowed = {"interface_id", "kind", "direction", "medium", "properties"}
        if frame_required is not False:
            allowed.add("frame")
        if attachment_required is not False:
            allowed.add("attachment")
        _reject_unknown_keys(
            raw,
            allowed,
            field,
        )
        if frame_required is True and "frame" not in raw:
            raise InputError(f"{field}.frame is required")
        if attachment_required is True and "attachment" not in raw:
            raise InputError(f"{field}.attachment is required")
        try:
            kind = InterfaceKind(_required_string(raw, "kind", field))
        except ValueError as exc:
            raise InputError(
                f"{field}.kind is unsupported: {raw.get('kind')!r}"
            ) from exc
        try:
            direction = InterfaceDirection(_required_string(raw, "direction", field))
        except ValueError as exc:
            raise InputError(
                f"{field}.direction is unsupported: {raw.get('direction')!r}"
            ) from exc
        return cls(
            interface_id=_required_string(raw, "interface_id", field),
            kind=kind,
            direction=direction,
            medium=_required_string(raw, "medium", field),
            properties=_string_map(raw.get("properties", {}), f"{field}.properties"),
            frame=(
                ExactInterfaceFrame.from_dict(raw["frame"], field=f"{field}.frame")
                if "frame" in raw
                else None
            ),
            attachment=(
                InterfaceAttachment.from_dict(
                    raw["attachment"],
                    field=f"{field}.attachment",
                    evidence_required=attachment_evidence_required,
                )
                if "attachment" in raw
                else None
            ),
        )

    def as_dict(self, *, include_attachment_evidence: bool = True) -> dict[str, Any]:
        if type(include_attachment_evidence) is not bool:
            raise InputError("include_attachment_evidence must be boolean")
        document = {
            "interface_id": self.interface_id,
            "kind": self.kind.value,
            "direction": self.direction.value,
            "medium": self.medium,
            "properties": dict(self.properties),
        }
        if self.frame is not None:
            document["frame"] = self.frame.as_dict()
        if self.attachment is not None:
            document["attachment"] = self.attachment.as_dict(
                include_evidence=include_attachment_evidence
            )
        return document


@dataclass(frozen=True)
class ComponentManifest:
    schema_version: str
    component_id: str
    revision: str
    title: str
    lifecycle_state: LifecycleState
    qualification: Qualification
    source_bundle_digest: str
    artifacts: tuple[ArtifactRef, ...]
    interfaces: tuple[ComponentInterface, ...]
    capabilities: tuple[str, ...]
    geometry_bounds: ExactGeometryBounds | None
    metadata: Mapping[str, str]

    def __post_init__(self) -> None:
        if (
            self.schema_version == COMPONENT_SCHEMA_V4
            and len(self.interfaces) > _MAX_COMPONENT_INTERFACES
        ):
            raise InputError("component.interfaces exceeds its count limit")

    @classmethod
    def from_dict(cls, raw: Any, *, field: str = "component") -> ComponentManifest:
        if not isinstance(raw, dict):
            raise InputError(f"{field} must be an object")
        _reject_unknown_keys(
            raw,
            {
                "schema_version",
                "component_id",
                "revision",
                "title",
                "lifecycle_state",
                "qualification",
                "source_bundle_digest",
                "artifacts",
                "interfaces",
                "capabilities",
                "geometry_bounds",
                "metadata",
            },
            field,
        )
        schema_version = _required_string(raw, "schema_version", field)
        if schema_version not in _SUPPORTED_COMPONENT_SCHEMAS:
            raise InputError(f"unsupported component schema: {schema_version!r}")
        if schema_version == COMPONENT_SCHEMA_V1 and "geometry_bounds" in raw:
            raise InputError(
                f"{field}.geometry_bounds requires component schema {COMPONENT_SCHEMA!r}"
            )
        if schema_version == COMPONENT_SCHEMA and "geometry_bounds" not in raw:
            raise InputError(
                f"{field}.geometry_bounds is required by component schema {COMPONENT_SCHEMA!r}"
            )
        if schema_version == COMPONENT_SCHEMA_V3 and "geometry_bounds" not in raw:
            raise InputError(
                f"{field}.geometry_bounds is required by component schema {COMPONENT_SCHEMA_V3!r}"
            )
        if schema_version == COMPONENT_SCHEMA_V4 and "geometry_bounds" not in raw:
            raise InputError(
                f"{field}.geometry_bounds is required by component schema {COMPONENT_SCHEMA_V4!r}"
            )
        try:
            lifecycle_state = LifecycleState(
                _required_string(raw, "lifecycle_state", field)
            )
        except ValueError as exc:
            raise InputError(
                f"{field}.lifecycle_state is unsupported: {raw.get('lifecycle_state')!r}"
            ) from exc
        try:
            qualification = Qualification(_required_string(raw, "qualification", field))
        except ValueError as exc:
            raise InputError(
                f"{field}.qualification is unsupported: {raw.get('qualification')!r}"
            ) from exc

        artifacts_raw = raw.get("artifacts")
        if not isinstance(artifacts_raw, list) or not artifacts_raw:
            raise InputError(f"{field}.artifacts must be a non-empty list")
        artifacts = tuple(
            ArtifactRef.from_dict(item, field=f"{field}.artifacts[{index}]")
            for index, item in enumerate(artifacts_raw)
        )
        artifact_ids = [item.artifact_id for item in artifacts]
        if len(artifact_ids) != len(set(artifact_ids)):
            raise InputError(f"{field}.artifact identifiers must be unique")

        source_bundle_digest = _digest(
            _required_string(raw, "source_bundle_digest", field),
            f"{field}.source_bundle_digest",
        )
        engineering_bundles = [
            item
            for item in artifacts
            if item.role is ArtifactRole.ENGINEERING_BUNDLE
            and item.digest == source_bundle_digest
        ]
        if len(engineering_bundles) != 1:
            raise InputError(
                f"{field}.source_bundle_digest must identify exactly one engineering_bundle artifact"
            )

        geometry_bounds = (
            ExactGeometryBounds.from_dict(
                raw["geometry_bounds"],
                field=f"{field}.geometry_bounds",
                canonical=schema_version in {COMPONENT_SCHEMA_V3, COMPONENT_SCHEMA_V4},
            )
            if "geometry_bounds" in raw
            else None
        )

        interfaces_raw = raw.get("interfaces", [])
        if not isinstance(interfaces_raw, list):
            raise InputError(f"{field}.interfaces must be a list")
        if (
            schema_version == COMPONENT_SCHEMA_V4
            and len(interfaces_raw) > _MAX_COMPONENT_INTERFACES
        ):
            raise InputError(f"{field}.interfaces exceeds its count limit")
        interfaces = tuple(
            ComponentInterface.from_dict(
                item,
                field=f"{field}.interfaces[{index}]",
                frame_required=schema_version
                in {COMPONENT_SCHEMA_V3, COMPONENT_SCHEMA_V4},
                attachment_required=schema_version == COMPONENT_SCHEMA_V4,
                attachment_evidence_required=schema_version == COMPONENT_SCHEMA_V4,
            )
            for index, item in enumerate(interfaces_raw)
        )
        interface_ids = [item.interface_id for item in interfaces]
        if len(interface_ids) != len(set(interface_ids)):
            raise InputError(f"{field}.interface identifiers must be unique")
        if schema_version in {COMPONENT_SCHEMA_V3, COMPONENT_SCHEMA_V4}:
            if geometry_bounds is None:  # pragma: no cover - schema guard above
                raise InputError(f"{field}.geometry_bounds is required")
            for index, interface in enumerate(interfaces):
                if interface.frame is None:  # pragma: no cover - parser guard above
                    raise InputError(f"{field}.interfaces[{index}].frame is required")
                interface.frame.require_origin_within(
                    geometry_bounds, field=f"{field}.interfaces[{index}].frame"
                )

        capabilities_raw = raw.get("capabilities", [])
        if not isinstance(capabilities_raw, list) or not all(
            isinstance(item, str) and item for item in capabilities_raw
        ):
            raise InputError(
                f"{field}.capabilities must be a list of non-empty strings"
            )
        if len(capabilities_raw) != len(set(capabilities_raw)):
            raise InputError(f"{field}.capabilities must be unique")

        return cls(
            schema_version=schema_version,
            component_id=_required_string(raw, "component_id", field),
            revision=_required_string(raw, "revision", field),
            title=_required_string(raw, "title", field),
            lifecycle_state=lifecycle_state,
            qualification=qualification,
            source_bundle_digest=source_bundle_digest,
            artifacts=artifacts,
            interfaces=interfaces,
            capabilities=tuple(capabilities_raw),
            geometry_bounds=geometry_bounds,
            metadata=_string_map(raw.get("metadata", {}), f"{field}.metadata"),
        )

    @property
    def manifest_digest(self) -> str:
        return digest(self.as_dict())

    def as_dict(self) -> dict[str, Any]:
        document = {
            "schema_version": self.schema_version,
            "component_id": self.component_id,
            "revision": self.revision,
            "title": self.title,
            "lifecycle_state": self.lifecycle_state.value,
            "qualification": self.qualification.value,
            "source_bundle_digest": self.source_bundle_digest,
            "artifacts": [item.as_dict() for item in self.artifacts],
            "interfaces": [item.as_dict() for item in self.interfaces],
            "capabilities": list(self.capabilities),
            "metadata": dict(self.metadata),
        }
        if self.geometry_bounds is not None:
            document["geometry_bounds"] = self.geometry_bounds.as_dict()
        return document
