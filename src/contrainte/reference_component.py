from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum
from fractions import Fraction
from typing import Any

from .canonical import digest
from .component import InterfaceDirection, InterfaceKind
from .errors import InputError, IntegrityError
from .exact_transform import (
    MAX_EXACT_SCALAR_CHARACTERS,
    ExactRigidTransform,
    ExactVector3,
)

REFERENCE_COMPONENT_SCHEMA = "contrainte.reference-component/0.1"
DESIGN_AROUND_REQUEST_SCHEMA = "contrainte.design-around-request/0.1"
DESIGN_AROUND_PROJECTION_SCHEMA = "contrainte.design-around-projection/0.1"

LEGAL_GATE_DISCLAIMER = (
    "Project workflow dispositions only; not legal determinations or advice."
)

MAX_EVIDENCE_RECORDS = 128
MAX_REFERENCE_FRAMES = 256
MAX_SPATIAL_ENVELOPES = 256
MAX_KNOWN_FIELDS = 512
MAX_UNKNOWN_FIELDS = 512
MAX_FLEXIBLE_DOMAINS = 32
MAX_CLEARANCE_REQUIREMENTS = 256
MAX_IDENTIFIER_CHARACTERS = 128
MAX_TEXT_CHARACTERS = 2_048
MAX_JSON_STRING_CHARACTERS = 4_096
MAX_JSON_NODES = 20_000
MAX_JSON_DEPTH = 32
MAX_JSON_INTEGER_BITS = 64

_DIGEST_PATTERN = re.compile(r"^sha256:[0-9a-f]{64}$")
_IDENTIFIER_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]*$")
_RATIONAL_PATTERN = re.compile(r"^-?(?:0|[1-9][0-9]*)(?:/[1-9][0-9]*)?$")
_AXES = ("x", "y", "z")


class EvidenceKind(str, Enum):
    MANUFACTURER_DRAWING = "manufacturer_drawing"
    MANUFACTURER_DATASHEET = "manufacturer_datasheet"
    SUPPLIER_MODEL = "supplier_model"
    CALIBRATED_METROLOGY = "calibrated_metrology"
    TEST_REPORT = "test_report"
    DECLARATION = "declaration"
    SCAN = "scan"
    GAUSSIAN_SPLAT = "gaussian_splat"
    OTHER = "other"


class EvidenceAuthority(str, Enum):
    DOCUMENTED_SOURCE = "documented_source"
    VERIFIED_MEASUREMENT = "verified_measurement"
    NOMINAL_SOURCE = "nominal_source"
    OBSERVATION = "observation"
    INFORMATIVE = "informative"


class FrameRole(str, Enum):
    DATUM = "datum"
    INTERFACE = "interface"


class EnvelopePurpose(str, Enum):
    KEEP_OUT = "keepout"
    SERVICE = "service"
    ACCESS = "access"


class AllowedOperation(str, Enum):
    RIGID_PLACEMENT = "rigid_placement"
    ATTACH_AT_DECLARED_INTERFACE = "attach_at_declared_interface"
    ROUTE_WITHIN_DECLARED_ACCESS = "route_within_declared_access"
    REMOVE_FOR_SERVICE = "remove_for_service"
    REPLACE_LIKE_FOR_LIKE = "replace_like_for_like"


class GateName(str, Enum):
    AUTHENTICITY = "authenticity"
    RIGHTS_TO_USE = "rights_to_use"
    RIGHTS_TO_MODIFY = "rights_to_modify"
    FREEDOM_TO_OPERATE = "freedom_to_operate"
    EXPORT_CONTROL = "export_control"


class GateDisposition(str, Enum):
    UNREVIEWED = "unreviewed"
    ACCEPTED_FOR_PROJECT = "accepted_for_project"
    BLOCKED = "blocked"
    NOT_APPLICABLE = "not_applicable"


class DesignDomain(str, Enum):
    MOUNTING = "mounting"
    STRUCTURE = "structure"
    TRANSMISSION = "transmission"
    POWER = "power"
    ELECTRONICS = "electronics"
    COOLING = "cooling"
    LUBRICATION = "lubrication"
    HARNESS = "harness"
    CONTROLS = "controls"
    SHIELDING = "shielding"
    GUARDING = "guarding"
    SERVICE_TOOLING = "service_tooling"


class ConstraintKind(str, Enum):
    IDENTITY = "identity"
    SOURCE_MODEL = "source_model"
    OCCUPIED_BOUNDS = "occupied_bounds"
    FRAME = "frame"
    ENVELOPE = "envelope"
    MASS_PROPERTIES = "mass_properties"
    ALLOWED_OPERATIONS = "allowed_operations"
    EVIDENCE_GATE = "evidence_gate"
    KNOWN_FIELD = "known_field"
    UNKNOWN_FIELD = "unknown_field"
    CLEARANCE = "clearance"


def _no_subclass(cls: type[Any], **_: Any) -> None:
    raise TypeError(f"{cls.__name__} may not be subclassed")


def _exact_dict(raw: Any, expected: set[str], field: str) -> dict[str, Any]:
    if type(raw) is not dict:
        raise InputError(f"{field} must be an object")
    if any(type(key) is not str for key in raw):
        raise InputError(f"{field} field names must be built-in strings")
    missing = sorted(expected - set(raw))
    unknown = sorted(set(raw) - expected)
    if missing:
        raise InputError(f"{field} is missing required fields: {', '.join(missing)}")
    if unknown:
        raise InputError(f"{field} contains unsupported fields: {', '.join(unknown)}")
    return raw


def _string(value: Any, field: str, *, identifier: bool = False) -> str:
    maximum = MAX_IDENTIFIER_CHARACTERS if identifier else MAX_TEXT_CHARACTERS
    if type(value) is not str or not value or len(value) > maximum:
        raise InputError(
            f"{field} must be a non-empty built-in string of at most {maximum} characters"
        )
    if identifier and not _IDENTIFIER_PATTERN.fullmatch(value):
        raise InputError(f"{field} must use the portable identifier character set")
    return value


def _field_path(value: Any, field: str) -> str:
    text = _string(value, field)
    if not text.startswith("/") or text.endswith("/"):
        raise InputError(f"{field} must be a canonical absolute field path")
    for raw_segment in text[1:].split("/"):
        if not raw_segment:
            raise InputError(f"{field} must not contain empty path segments")
        index = 0
        while index < len(raw_segment):
            if raw_segment[index] == "~":
                if index + 1 >= len(raw_segment) or raw_segment[index + 1] not in {
                    "0",
                    "1",
                }:
                    raise InputError(
                        f"{field} contains an invalid RFC 6901 escape sequence"
                    )
                index += 2
            else:
                index += 1
        decoded = raw_segment.replace("~1", "/").replace("~0", "~")
        if decoded in {".", ".."}:
            raise InputError(f"{field} must not contain dot-navigation segments")
    return text


def _path_segments(path: str) -> tuple[str, ...]:
    return tuple(
        segment.replace("~1", "/").replace("~0", "~") for segment in path[1:].split("/")
    )


def _path_is_parent_or_same(parent: str, child: str) -> bool:
    parent_segments = _path_segments(parent)
    child_segments = _path_segments(child)
    return (
        len(parent_segments) <= len(child_segments)
        and child_segments[: len(parent_segments)] == parent_segments
    )


def _sha256(value: Any, field: str) -> str:
    if type(value) is not str or not _DIGEST_PATTERN.fullmatch(value):
        raise InputError(f"{field} must be a lowercase SHA-256 digest")
    return value


def _fraction_text(value: Fraction) -> str:
    if value.denominator == 1:
        return str(value.numerator)
    return f"{value.numerator}/{value.denominator}"


def _fraction(value: Any, field: str, *, nonnegative: bool = False) -> Fraction:
    if (
        type(value) is not str
        or len(value) > MAX_EXACT_SCALAR_CHARACTERS
        or not _RATIONAL_PATTERN.fullmatch(value)
    ):
        raise InputError(f"{field} must be a bounded canonical rational string")
    numerator, separator, denominator = value.partition("/")
    result = Fraction(int(numerator), int(denominator) if separator else 1)
    if _fraction_text(result) != value:
        raise InputError(f"{field} must be reduced and canonical")
    if nonnegative and result < 0:
        raise InputError(f"{field} must be non-negative")
    return result


def _enum(enum_type: type[Enum], value: Any, field: str) -> Any:
    if type(value) is not str:
        raise InputError(f"{field} must be a built-in string")
    try:
        return enum_type(value)
    except ValueError as exc:
        raise InputError(f"{field} has unsupported value {value!r}") from exc


def _bounded_tree(root: Any, field: str) -> None:
    stack = [(root, 1)]
    nodes = 0
    while stack:
        value, depth = stack.pop()
        nodes += 1
        if nodes > MAX_JSON_NODES:
            raise InputError(f"{field} exceeds the {MAX_JSON_NODES}-node input limit")
        if depth > MAX_JSON_DEPTH:
            raise InputError(f"{field} exceeds the {MAX_JSON_DEPTH}-level depth limit")
        if type(value) is dict:
            if nodes + len(stack) + len(value) > MAX_JSON_NODES:
                raise InputError(
                    f"{field} exceeds the {MAX_JSON_NODES}-node input limit"
                )
            if any(type(key) is not str for key in value):
                raise InputError(f"{field} field names must be built-in strings")
            for key, item in value.items():
                if len(key) > MAX_JSON_STRING_CHARACTERS:
                    raise InputError(f"{field} contains an overlong field name")
            for item in value.values():
                stack.append((item, depth + 1))
        elif type(value) is list:
            if nodes + len(stack) + len(value) > MAX_JSON_NODES:
                raise InputError(
                    f"{field} exceeds the {MAX_JSON_NODES}-node input limit"
                )
            for item in value:
                stack.append((item, depth + 1))
        elif type(value) is int:
            if value.bit_length() > MAX_JSON_INTEGER_BITS:
                raise InputError(
                    f"{field} contains an integer exceeding the {MAX_JSON_INTEGER_BITS}-bit limit"
                )
        elif value is None or type(value) in {str, bool}:
            if type(value) is str and len(value) > MAX_JSON_STRING_CHARACTERS:
                raise InputError(f"{field} contains an overlong string")
        else:
            raise InputError(
                f"{field} contains unsupported value type {type(value).__name__}"
            )


def _ordered(items: tuple[Any, ...], key: Any, field: str) -> None:
    if tuple(sorted(items, key=key)) != items:
        raise InputError(f"{field} must be in canonical order")


def _unique(values: tuple[str, ...], field: str) -> None:
    if len(set(values)) != len(values):
        raise InputError(f"{field} must be unique")


def _supports_path(record: EvidenceRecord, path: str, *, exact: bool = False) -> bool:
    return any(
        support == path or (not exact and _path_is_parent_or_same(support, path))
        for support in record.supports
    )


def _needs_independent_resolution(authority: EvidenceAuthority) -> bool:
    return authority not in {
        EvidenceAuthority.DOCUMENTED_SOURCE,
        EvidenceAuthority.VERIFIED_MEASUREMENT,
    }


def _resolve_pointer(document: Any, path: str, *, field: str) -> Any:
    current = document
    for segment in _path_segments(path):
        if type(current) is dict:
            if segment not in current:
                raise InputError(f"{field} does not resolve to a manifest value")
            current = current[segment]
        elif type(current) is list:
            if (
                not segment.isascii()
                or not segment.isdigit()
                or (len(segment) > 1 and segment.startswith("0"))
            ):
                raise InputError(f"{field} contains a non-canonical list index")
            index = int(segment)
            if index >= len(current):
                raise InputError(f"{field} list index is out of range")
            current = current[index]
        else:
            raise InputError(f"{field} descends through a scalar manifest value")
    return current


def _mass_properties_within_bounds(mass: MassProperties, bounds: ExactBox) -> bool:
    distances: dict[str, Fraction] = {}
    for axis in _AXES:
        center = getattr(mass.center_of_mass, axis)
        distances[axis] = max(
            abs(getattr(bounds.minimum, axis) - center),
            abs(getattr(bounds.maximum, axis) - center),
        )
    dx, dy, dz = (distances[axis] for axis in _AXES)
    ixx, iyy, izz, ixy, ixz, iyz = mass.inertia_kg_mm2
    return (
        ixx <= mass.mass_kg * (dy * dy + dz * dz)
        and iyy <= mass.mass_kg * (dx * dx + dz * dz)
        and izz <= mass.mass_kg * (dx * dx + dy * dy)
        and abs(ixy) <= mass.mass_kg * dx * dy
        and abs(ixz) <= mass.mass_kg * dx * dz
        and abs(iyz) <= mass.mass_kg * dy * dz
    )


@dataclass(frozen=True, slots=True)
class ExactBox:
    minimum: ExactVector3
    maximum: ExactVector3
    unit: str = "mm"

    __init_subclass__ = classmethod(_no_subclass)

    def __post_init__(self) -> None:
        if (
            type(self.minimum) is not ExactVector3
            or type(self.maximum) is not ExactVector3
        ):
            raise InputError("exact_box bounds must be ExactVector3 values")
        if type(self.unit) is not str or self.unit != "mm":
            raise InputError("exact_box.unit must be 'mm'")
        if any(
            getattr(self.maximum, axis) <= getattr(self.minimum, axis) for axis in _AXES
        ):
            raise InputError(
                "exact_box maximum must be greater than minimum on every axis"
            )

    @classmethod
    def from_dict(cls, raw: Any, *, field: str) -> ExactBox:
        values = _exact_dict(raw, {"unit", "minimum", "maximum"}, field)
        if type(values["unit"]) is not str or values["unit"] != "mm":
            raise InputError(f"{field}.unit must be 'mm'")
        return cls(
            ExactVector3.from_dict(values["minimum"], field=f"{field}.minimum"),
            ExactVector3.from_dict(values["maximum"], field=f"{field}.maximum"),
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "unit": self.unit,
            "minimum": self.minimum.as_dict(),
            "maximum": self.maximum.as_dict(),
        }

    def contains(self, point: ExactVector3) -> bool:
        if type(point) is not ExactVector3:
            raise InputError("point must be an ExactVector3")
        return all(
            getattr(self.minimum, axis)
            <= getattr(point, axis)
            <= getattr(self.maximum, axis)
            for axis in _AXES
        )


@dataclass(frozen=True, slots=True)
class EvidenceRecord:
    evidence_id: str
    kind: EvidenceKind
    artifact_digest: str
    authority: EvidenceAuthority
    locator: str
    supports: tuple[str, ...]

    __init_subclass__ = classmethod(_no_subclass)

    def __post_init__(self) -> None:
        _string(self.evidence_id, "evidence.evidence_id", identifier=True)
        if (
            type(self.kind) is not EvidenceKind
            or type(self.authority) is not EvidenceAuthority
        ):
            raise InputError(
                "evidence kind and authority must use their exact enum types"
            )
        _sha256(self.artifact_digest, "evidence.artifact_digest")
        _string(self.locator, "evidence.locator")
        if type(self.supports) is not tuple or not self.supports:
            raise InputError("evidence.supports must be a non-empty tuple")
        if len(self.supports) > MAX_KNOWN_FIELDS:
            raise InputError("evidence.supports exceeds the resource limit")
        for index, path in enumerate(self.supports):
            _field_path(path, f"evidence.supports[{index}]")
        _unique(self.supports, "evidence.supports")
        if tuple(sorted(self.supports)) != self.supports:
            raise InputError("evidence.supports must be in canonical order")
        if (
            self.kind in {EvidenceKind.SCAN, EvidenceKind.GAUSSIAN_SPLAT}
            and self.authority is not EvidenceAuthority.OBSERVATION
        ):
            raise InputError(
                "scan and Gaussian-splat evidence is observational, not dimensional authority"
            )
        if self.authority is EvidenceAuthority.DOCUMENTED_SOURCE and self.kind not in {
            EvidenceKind.MANUFACTURER_DRAWING,
            EvidenceKind.MANUFACTURER_DATASHEET,
        }:
            raise InputError(
                "documented_source authority requires manufacturer documentation"
            )
        if (
            self.authority is EvidenceAuthority.VERIFIED_MEASUREMENT
            and self.kind is not EvidenceKind.CALIBRATED_METROLOGY
        ):
            raise InputError(
                "verified_measurement authority requires calibrated metrology"
            )

    @classmethod
    def from_dict(cls, raw: Any, *, field: str) -> EvidenceRecord:
        values = _exact_dict(
            raw,
            {
                "evidence_id",
                "kind",
                "artifact_digest",
                "authority",
                "locator",
                "supports",
            },
            field,
        )
        supports = values["supports"]
        if type(supports) is not list or not 1 <= len(supports) <= MAX_KNOWN_FIELDS:
            raise InputError(
                f"{field}.supports must contain 1 to {MAX_KNOWN_FIELDS} paths"
            )
        return cls(
            _string(values["evidence_id"], f"{field}.evidence_id", identifier=True),
            _enum(EvidenceKind, values["kind"], f"{field}.kind"),
            _sha256(values["artifact_digest"], f"{field}.artifact_digest"),
            _enum(EvidenceAuthority, values["authority"], f"{field}.authority"),
            _string(values["locator"], f"{field}.locator"),
            tuple(
                _field_path(item, f"{field}.supports[{index}]")
                for index, item in enumerate(supports)
            ),
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "evidence_id": self.evidence_id,
            "kind": self.kind.value,
            "artifact_digest": self.artifact_digest,
            "authority": self.authority.value,
            "locator": self.locator,
            "supports": list(self.supports),
        }


@dataclass(frozen=True, slots=True)
class ReferenceFrame:
    """A physical interface or a datum in the component-local frame.

    Interface origins are physical attachment/connection locations and must fall
    within occupied bounds. Datum frames may be virtual construction references
    outside those bounds and never imply occupied material at their origin.
    """

    frame_id: str
    role: FrameRole
    transform: ExactRigidTransform
    evidence_id: str
    interface_kind: InterfaceKind | None = None
    direction: InterfaceDirection | None = None
    medium: str | None = None
    properties: tuple[tuple[str, str], ...] = ()

    __init_subclass__ = classmethod(_no_subclass)

    def __post_init__(self) -> None:
        _string(self.frame_id, "reference_frame.frame_id", identifier=True)
        if (
            type(self.role) is not FrameRole
            or type(self.transform) is not ExactRigidTransform
        ):
            raise InputError(
                "reference_frame role and transform must use exact public types"
            )
        _string(self.evidence_id, "reference_frame.evidence_id", identifier=True)
        if type(self.properties) is not tuple or len(self.properties) > 128:
            raise InputError("reference_frame.properties must be a bounded tuple")
        for index, pair in enumerate(self.properties):
            if type(pair) is not tuple or len(pair) != 2:
                raise InputError(f"reference_frame.properties[{index}] must be a pair")
            _string(
                pair[0], f"reference_frame.properties[{index}].key", identifier=True
            )
            _string(pair[1], f"reference_frame.properties[{index}].value")
        if tuple(sorted(self.properties)) != self.properties or len(
            {key for key, _ in self.properties}
        ) != len(self.properties):
            raise InputError(
                "reference_frame.properties must have unique keys in canonical order"
            )
        interface_values = (self.interface_kind, self.direction, self.medium)
        if self.role is FrameRole.DATUM:
            if any(value is not None for value in interface_values) or self.properties:
                raise InputError("datum frames cannot declare interface semantics")
        else:
            if (
                type(self.interface_kind) is not InterfaceKind
                or type(self.direction) is not InterfaceDirection
            ):
                raise InputError(
                    "interface frames require exact kind and direction enums"
                )
            _string(self.medium, "reference_frame.medium", identifier=True)

    @classmethod
    def from_dict(cls, raw: Any, *, field: str) -> ReferenceFrame:
        values = _exact_dict(
            raw, {"frame_id", "role", "transform", "evidence_id", "interface"}, field
        )
        role = _enum(FrameRole, values["role"], f"{field}.role")
        interface = values["interface"]
        if role is FrameRole.DATUM:
            if interface is not None:
                raise InputError(f"{field}.interface must be null for datum frames")
            semantics: tuple[Any, ...] = (None, None, None, ())
        else:
            iv = _exact_dict(
                interface,
                {"kind", "direction", "medium", "properties"},
                f"{field}.interface",
            )
            raw_properties = iv["properties"]
            if (
                type(raw_properties) is not dict
                or len(raw_properties) > 128
                or any(
                    type(key) is not str or type(value) is not str
                    for key, value in raw_properties.items()
                )
            ):
                raise InputError(
                    f"{field}.interface.properties must be a bounded string map"
                )
            semantics = (
                _enum(InterfaceKind, iv["kind"], f"{field}.interface.kind"),
                _enum(
                    InterfaceDirection, iv["direction"], f"{field}.interface.direction"
                ),
                _string(iv["medium"], f"{field}.interface.medium", identifier=True),
                tuple(sorted(raw_properties.items())),
            )
        return cls(
            _string(values["frame_id"], f"{field}.frame_id", identifier=True),
            role,
            ExactRigidTransform.from_dict(
                values["transform"], field=f"{field}.transform"
            ),
            _string(values["evidence_id"], f"{field}.evidence_id", identifier=True),
            *semantics,
        )

    def as_dict(self) -> dict[str, Any]:
        interface = None
        if self.role is FrameRole.INTERFACE:
            interface = {
                "kind": self.interface_kind.value,  # type: ignore[union-attr]
                "direction": self.direction.value,  # type: ignore[union-attr]
                "medium": self.medium,
                "properties": dict(self.properties),
            }
        return {
            "frame_id": self.frame_id,
            "role": self.role.value,
            "transform": self.transform.as_dict(),
            "evidence_id": self.evidence_id,
            "interface": interface,
        }


@dataclass(frozen=True, slots=True)
class SpatialEnvelope:
    envelope_id: str
    purpose: EnvelopePurpose
    bounds: ExactBox
    evidence_id: str

    __init_subclass__ = classmethod(_no_subclass)

    def __post_init__(self) -> None:
        _string(self.envelope_id, "spatial_envelope.envelope_id", identifier=True)
        if (
            type(self.purpose) is not EnvelopePurpose
            or type(self.bounds) is not ExactBox
        ):
            raise InputError("spatial_envelope purpose and bounds must use exact types")
        _string(self.evidence_id, "spatial_envelope.evidence_id", identifier=True)

    @classmethod
    def from_dict(cls, raw: Any, *, field: str) -> SpatialEnvelope:
        values = _exact_dict(
            raw, {"envelope_id", "purpose", "bounds", "evidence_id"}, field
        )
        return cls(
            _string(values["envelope_id"], f"{field}.envelope_id", identifier=True),
            _enum(EnvelopePurpose, values["purpose"], f"{field}.purpose"),
            ExactBox.from_dict(values["bounds"], field=f"{field}.bounds"),
            _string(values["evidence_id"], f"{field}.evidence_id", identifier=True),
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "envelope_id": self.envelope_id,
            "purpose": self.purpose.value,
            "bounds": self.bounds.as_dict(),
            "evidence_id": self.evidence_id,
        }


def _symmetric_matrix_is_psd(
    xx: Fraction,
    yy: Fraction,
    zz: Fraction,
    xy: Fraction,
    xz: Fraction,
    yz: Fraction,
) -> bool:
    return (
        min(xx, yy, zz) >= 0
        and xx * yy - xy * xy >= 0
        and xx * zz - xz * xz >= 0
        and yy * zz - yz * yz >= 0
        and (
            xx * yy * zz + 2 * xy * xz * yz - xx * yz * yz - yy * xz * xz - zz * xy * xy
        )
        >= 0
    )


@dataclass(frozen=True, slots=True)
class MassProperties:
    """Exact mass properties with inertia about ``center_of_mass``."""

    mass_kg: Fraction
    center_of_mass: ExactVector3
    inertia_kg_mm2: tuple[Fraction, Fraction, Fraction, Fraction, Fraction, Fraction]
    evidence_id: str

    __init_subclass__ = classmethod(_no_subclass)

    def __post_init__(self) -> None:
        if type(self.mass_kg) is not Fraction or self.mass_kg <= 0:
            raise InputError(
                "mass_properties.mass_kg must be a positive exact Fraction"
            )
        if len(_fraction_text(self.mass_kg)) > MAX_EXACT_SCALAR_CHARACTERS:
            raise InputError("mass_properties.mass_kg exceeds the exact scalar limit")
        if type(self.center_of_mass) is not ExactVector3:
            raise InputError("mass_properties.center_of_mass must be an ExactVector3")
        if (
            type(self.inertia_kg_mm2) is not tuple
            or len(self.inertia_kg_mm2) != 6
            or not all(type(value) is Fraction for value in self.inertia_kg_mm2)
        ):
            raise InputError("mass_properties inertia must contain six exact Fractions")
        if any(
            len(_fraction_text(value)) > MAX_EXACT_SCALAR_CHARACTERS
            for value in self.inertia_kg_mm2
        ):
            raise InputError("mass_properties inertia exceeds the exact scalar limit")
        ixx, iyy, izz, ixy, ixz, iyz = self.inertia_kg_mm2
        if not _symmetric_matrix_is_psd(ixx, iyy, izz, ixy, ixz, iyz):
            raise InputError("mass_properties inertia must be positive semidefinite")
        half_trace = (ixx + iyy + izz) / 2
        if not _symmetric_matrix_is_psd(
            half_trace - ixx,
            half_trace - iyy,
            half_trace - izz,
            -ixy,
            -ixz,
            -iyz,
        ):
            raise InputError(
                "mass_properties inertia violates exact principal triangle inequalities"
            )
        _string(self.evidence_id, "mass_properties.evidence_id", identifier=True)

    @classmethod
    def from_dict(cls, raw: Any, *, field: str) -> MassProperties:
        values = _exact_dict(
            raw,
            {
                "mass_kg",
                "center_of_mass",
                "inertia_kg_mm2",
                "inertia_reference",
                "evidence_id",
            },
            field,
        )
        if (
            type(values["inertia_reference"]) is not str
            or values["inertia_reference"] != "center_of_mass"
        ):
            raise InputError(f"{field}.inertia_reference must be 'center_of_mass'")
        inertia = _exact_dict(
            values["inertia_kg_mm2"],
            {"ixx", "iyy", "izz", "ixy", "ixz", "iyz"},
            f"{field}.inertia_kg_mm2",
        )
        return cls(
            _fraction(values["mass_kg"], f"{field}.mass_kg"),
            ExactVector3.from_dict(
                values["center_of_mass"], field=f"{field}.center_of_mass"
            ),
            tuple(
                _fraction(inertia[name], f"{field}.inertia_kg_mm2.{name}")
                for name in ("ixx", "iyy", "izz", "ixy", "ixz", "iyz")
            ),  # type: ignore[arg-type]
            _string(values["evidence_id"], f"{field}.evidence_id", identifier=True),
        )

    def as_dict(self) -> dict[str, Any]:
        names = ("ixx", "iyy", "izz", "ixy", "ixz", "iyz")
        return {
            "mass_kg": _fraction_text(self.mass_kg),
            "center_of_mass": self.center_of_mass.as_dict(),
            "inertia_kg_mm2": {
                name: _fraction_text(value)
                for name, value in zip(names, self.inertia_kg_mm2, strict=True)
            },
            "inertia_reference": "center_of_mass",
            "evidence_id": self.evidence_id,
        }


@dataclass(frozen=True, slots=True)
class KnownField:
    field_path: str
    evidence_id: str

    __init_subclass__ = classmethod(_no_subclass)

    def __post_init__(self) -> None:
        _field_path(self.field_path, "known_field.field_path")
        _string(self.evidence_id, "known_field.evidence_id", identifier=True)

    @classmethod
    def from_dict(cls, raw: Any, *, field: str) -> KnownField:
        values = _exact_dict(raw, {"field_path", "evidence_id"}, field)
        return cls(
            _field_path(values["field_path"], f"{field}.field_path"),
            _string(values["evidence_id"], f"{field}.evidence_id", identifier=True),
        )

    def as_dict(self) -> dict[str, str]:
        return {"field_path": self.field_path, "evidence_id": self.evidence_id}


@dataclass(frozen=True, slots=True)
class UnknownField:
    field_path: str
    consequence: str
    required_evidence: str

    __init_subclass__ = classmethod(_no_subclass)

    def __post_init__(self) -> None:
        _field_path(self.field_path, "unknown_field.field_path")
        _string(self.consequence, "unknown_field.consequence")
        _string(self.required_evidence, "unknown_field.required_evidence")

    @classmethod
    def from_dict(cls, raw: Any, *, field: str) -> UnknownField:
        values = _exact_dict(
            raw, {"field_path", "consequence", "required_evidence"}, field
        )
        return cls(
            _field_path(values["field_path"], f"{field}.field_path"),
            _string(values["consequence"], f"{field}.consequence"),
            _string(values["required_evidence"], f"{field}.required_evidence"),
        )

    def as_dict(self) -> dict[str, str]:
        return {
            "field_path": self.field_path,
            "consequence": self.consequence,
            "required_evidence": self.required_evidence,
        }


@dataclass(frozen=True, slots=True)
class EvidenceGate:
    name: GateName
    disposition: GateDisposition
    evidence_ids: tuple[str, ...]
    rationale: str

    __init_subclass__ = classmethod(_no_subclass)

    def __post_init__(self) -> None:
        if (
            type(self.name) is not GateName
            or type(self.disposition) is not GateDisposition
        ):
            raise InputError("evidence_gate name and disposition must use exact enums")
        if type(self.evidence_ids) is not tuple:
            raise InputError("evidence_gate.evidence_ids must be a tuple")
        if len(self.evidence_ids) > MAX_EVIDENCE_RECORDS:
            raise InputError("evidence_gate.evidence_ids exceeds the resource limit")
        for index, item in enumerate(self.evidence_ids):
            _string(item, f"evidence_gate.evidence_ids[{index}]", identifier=True)
        _unique(self.evidence_ids, "evidence_gate.evidence_ids")
        if tuple(sorted(self.evidence_ids)) != self.evidence_ids:
            raise InputError("evidence_gate.evidence_ids must be in canonical order")
        _string(self.rationale, "evidence_gate.rationale")
        if (
            self.disposition
            in {GateDisposition.ACCEPTED_FOR_PROJECT, GateDisposition.BLOCKED}
            and not self.evidence_ids
        ):
            raise InputError(
                "accepted or blocked project gates require supporting evidence"
            )

    @classmethod
    def from_dict(cls, raw: Any, *, field: str) -> EvidenceGate:
        values = _exact_dict(
            raw, {"name", "disposition", "evidence_ids", "rationale"}, field
        )
        ids = values["evidence_ids"]
        if type(ids) is not list or len(ids) > MAX_EVIDENCE_RECORDS:
            raise InputError(f"{field}.evidence_ids must be a bounded list")
        return cls(
            _enum(GateName, values["name"], f"{field}.name"),
            _enum(GateDisposition, values["disposition"], f"{field}.disposition"),
            tuple(
                _string(item, f"{field}.evidence_ids[{index}]", identifier=True)
                for index, item in enumerate(ids)
            ),
            _string(values["rationale"], f"{field}.rationale"),
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "name": self.name.value,
            "disposition": self.disposition.value,
            "evidence_ids": list(self.evidence_ids),
            "rationale": self.rationale,
        }


def _manifest_payload(
    schema_version: str,
    component_id: str,
    manufacturer: str,
    part_number: str,
    revision: str,
    title: str,
    source_model_digest: str,
    unit: str,
    evidence: tuple[EvidenceRecord, ...],
    reference_frames: tuple[ReferenceFrame, ...],
    occupied_bounds: ExactBox,
    occupied_bounds_evidence_id: str,
    envelopes: tuple[SpatialEnvelope, ...],
    mass_properties: MassProperties | None,
    allowed_operations: tuple[AllowedOperation, ...],
    known_fields: tuple[KnownField, ...],
    unknown_fields: tuple[UnknownField, ...],
    evidence_gates: tuple[EvidenceGate, ...],
) -> dict[str, Any]:
    return {
        "schema_version": schema_version,
        "component_id": component_id,
        "manufacturer": manufacturer,
        "part_number": part_number,
        "revision": revision,
        "title": title,
        "source_model_digest": source_model_digest,
        "unit": unit,
        "evidence": [item.as_dict() for item in evidence],
        "reference_frames": [item.as_dict() for item in reference_frames],
        "occupied_bounds": occupied_bounds.as_dict(),
        "occupied_bounds_evidence_id": occupied_bounds_evidence_id,
        "envelopes": [item.as_dict() for item in envelopes],
        "mass_properties": None
        if mass_properties is None
        else mass_properties.as_dict(),
        "allowed_operations": [item.value for item in allowed_operations],
        "known_fields": [item.as_dict() for item in known_fields],
        "unknown_fields": [item.as_dict() for item in unknown_fields],
        "evidence_gates": [item.as_dict() for item in evidence_gates],
        "legal_gate_disclaimer": LEGAL_GATE_DISCLAIMER,
    }


@dataclass(frozen=True, slots=True)
class ReferenceComponentManifest:
    schema_version: str
    component_id: str
    manufacturer: str
    part_number: str
    revision: str
    title: str
    source_model_digest: str
    unit: str
    evidence: tuple[EvidenceRecord, ...]
    reference_frames: tuple[ReferenceFrame, ...]
    occupied_bounds: ExactBox
    occupied_bounds_evidence_id: str
    envelopes: tuple[SpatialEnvelope, ...]
    mass_properties: MassProperties | None
    allowed_operations: tuple[AllowedOperation, ...]
    known_fields: tuple[KnownField, ...]
    unknown_fields: tuple[UnknownField, ...]
    evidence_gates: tuple[EvidenceGate, ...]
    content_digest: str

    __init_subclass__ = classmethod(_no_subclass)

    def __post_init__(self) -> None:
        if (
            type(self.schema_version) is not str
            or self.schema_version != REFERENCE_COMPONENT_SCHEMA
        ):
            raise InputError(
                f"reference_component.schema_version must be {REFERENCE_COMPONENT_SCHEMA!r}"
            )
        for name in ("component_id", "part_number", "revision"):
            _string(getattr(self, name), f"reference_component.{name}", identifier=True)
        for name in ("manufacturer", "title"):
            _string(getattr(self, name), f"reference_component.{name}")
        _sha256(self.source_model_digest, "reference_component.source_model_digest")
        if type(self.unit) is not str or self.unit != "mm":
            raise InputError("reference_component.unit must be 'mm'")
        typed_collections = (
            (self.evidence, EvidenceRecord, MAX_EVIDENCE_RECORDS, "evidence"),
            (
                self.reference_frames,
                ReferenceFrame,
                MAX_REFERENCE_FRAMES,
                "reference_frames",
            ),
            (self.envelopes, SpatialEnvelope, MAX_SPATIAL_ENVELOPES, "envelopes"),
            (
                self.allowed_operations,
                AllowedOperation,
                len(AllowedOperation),
                "allowed_operations",
            ),
            (self.known_fields, KnownField, MAX_KNOWN_FIELDS, "known_fields"),
            (self.unknown_fields, UnknownField, MAX_UNKNOWN_FIELDS, "unknown_fields"),
            (self.evidence_gates, EvidenceGate, len(GateName), "evidence_gates"),
        )
        for collection, item_type, maximum, name in typed_collections:
            if (
                type(collection) is not tuple
                or len(collection) > maximum
                or not all(type(item) is item_type for item in collection)
            ):
                raise InputError(
                    f"reference_component.{name} must be a bounded tuple of exact values"
                )
        if (
            not self.evidence
            or not self.reference_frames
            or not self.allowed_operations
        ):
            raise InputError(
                "reference component requires evidence, at least one frame, and allowed operations"
            )
        operation_set = set(self.allowed_operations)
        if AllowedOperation.ATTACH_AT_DECLARED_INTERFACE in operation_set and not any(
            frame.role is FrameRole.INTERFACE for frame in self.reference_frames
        ):
            raise InputError(
                "attach_at_declared_interface requires at least one physical interface frame"
            )
        if AllowedOperation.ROUTE_WITHIN_DECLARED_ACCESS in operation_set and not any(
            envelope.purpose is EnvelopePurpose.ACCESS for envelope in self.envelopes
        ):
            raise InputError(
                "route_within_declared_access requires at least one access envelope"
            )
        if AllowedOperation.REMOVE_FOR_SERVICE in operation_set and not any(
            envelope.purpose is EnvelopePurpose.SERVICE for envelope in self.envelopes
        ):
            raise InputError(
                "remove_for_service requires at least one service envelope"
            )
        if type(self.occupied_bounds) is not ExactBox:
            raise InputError("reference_component.occupied_bounds must be an ExactBox")
        _string(
            self.occupied_bounds_evidence_id,
            "reference_component.occupied_bounds_evidence_id",
            identifier=True,
        )
        if (
            self.mass_properties is not None
            and type(self.mass_properties) is not MassProperties
        ):
            raise InputError(
                "reference_component.mass_properties must be MassProperties or null"
            )
        _ordered(
            self.evidence, lambda item: item.evidence_id, "reference_component.evidence"
        )
        _ordered(
            self.reference_frames,
            lambda item: item.frame_id,
            "reference_component.reference_frames",
        )
        _ordered(
            self.envelopes,
            lambda item: (item.purpose.value, item.envelope_id),
            "reference_component.envelopes",
        )
        _ordered(
            self.allowed_operations,
            lambda item: item.value,
            "reference_component.allowed_operations",
        )
        _unique(
            tuple(item.value for item in self.allowed_operations),
            "reference_component.allowed_operations",
        )
        _ordered(
            self.known_fields,
            lambda item: item.field_path,
            "reference_component.known_fields",
        )
        _ordered(
            self.unknown_fields,
            lambda item: item.field_path,
            "reference_component.unknown_fields",
        )
        expected_gates = tuple(GateName)
        if tuple(item.name for item in self.evidence_gates) != expected_gates:
            raise InputError(
                "reference_component.evidence_gates must contain every gate once in schema order"
            )
        for values, name in (
            (tuple(item.evidence_id for item in self.evidence), "evidence identifiers"),
            (
                tuple(item.frame_id for item in self.reference_frames),
                "frame identifiers",
            ),
            (
                tuple(item.envelope_id for item in self.envelopes),
                "envelope identifiers",
            ),
            (tuple(item.field_path for item in self.known_fields), "known field paths"),
            (
                tuple(item.field_path for item in self.unknown_fields),
                "unknown field paths",
            ),
        ):
            _unique(values, f"reference_component.{name}")
        if {item.field_path for item in self.known_fields} & {
            item.field_path for item in self.unknown_fields
        }:
            raise InputError("a field cannot be both known and unknown")
        for known in self.known_fields:
            for unknown in self.unknown_fields:
                if _path_is_parent_or_same(
                    known.field_path, unknown.field_path
                ) or _path_is_parent_or_same(unknown.field_path, known.field_path):
                    raise InputError(
                        "known and unknown fields cannot have ancestor/descendant overlap"
                    )
        evidence_by_id = {item.evidence_id: item for item in self.evidence}
        referenced_evidence = [self.occupied_bounds_evidence_id]
        referenced_evidence.extend(item.evidence_id for item in self.reference_frames)
        referenced_evidence.extend(item.evidence_id for item in self.envelopes)
        referenced_evidence.extend(item.evidence_id for item in self.known_fields)
        referenced_evidence.extend(
            item for gate in self.evidence_gates for item in gate.evidence_ids
        )
        if self.mass_properties is not None:
            referenced_evidence.append(self.mass_properties.evidence_id)
            if not self.occupied_bounds.contains(self.mass_properties.center_of_mass):
                raise InputError(
                    "mass_properties.center_of_mass must lie within occupied_bounds"
                )
            if not _mass_properties_within_bounds(
                self.mass_properties, self.occupied_bounds
            ):
                raise InputError(
                    "mass_properties inertia exceeds conservative occupied-bounds limits"
                )
        for frame in self.reference_frames:
            if frame.role is FrameRole.INTERFACE and not self.occupied_bounds.contains(
                frame.transform.translation
            ):
                raise InputError(
                    f"physical interface frame {frame.frame_id!r} must originate within occupied_bounds"
                )
        missing = sorted(set(referenced_evidence) - set(evidence_by_id))
        if missing:
            raise InputError(
                f"reference_component references unknown evidence: {', '.join(missing)}"
            )
        if self.source_model_digest not in {
            item.artifact_digest for item in self.evidence
        }:
            raise InputError(
                "source_model_digest must identify one declared evidence artifact"
            )
        if not any(
            _supports_path(item, "/identity", exact=True) for item in self.evidence
        ):
            raise InputError(
                "reference_component identity must be supported by declared evidence"
            )
        evidence_bindings = (
            ("/occupied_bounds", self.occupied_bounds_evidence_id, True),
            *[
                (f"/reference_frames/{item.frame_id}", item.evidence_id, True)
                for item in self.reference_frames
            ],
            *[
                (f"/envelopes/{item.envelope_id}", item.evidence_id, True)
                for item in self.envelopes
            ],
            *[(item.field_path, item.evidence_id, False) for item in self.known_fields],
        )
        if self.mass_properties is not None:
            evidence_bindings = (
                *evidence_bindings,
                ("/mass_properties", self.mass_properties.evidence_id, True),
            )
        evidence_bindings = (
            *evidence_bindings,
            *[
                (f"/evidence_gates/{gate.name.value}", evidence_id, False)
                for gate in self.evidence_gates
                for evidence_id in gate.evidence_ids
            ],
        )
        for path, evidence_id, exact_support in evidence_bindings:
            record = evidence_by_id[evidence_id]
            if not _supports_path(record, path, exact=exact_support):
                raise InputError(
                    f"evidence {evidence_id!r} must explicitly declare support for {path}"
                )
        payload = self.payload_dict()
        forbidden_known_roots = {
            "known_fields",
            "unknown_fields",
            "evidence_gates",
            "legal_gate_disclaimer",
        }
        for item in self.known_fields:
            if _path_segments(item.field_path)[0] in forbidden_known_roots:
                raise InputError(
                    f"known field {item.field_path!r} targets schema bookkeeping"
                )
            _resolve_pointer(
                payload,
                item.field_path,
                field=f"known field {item.field_path!r}",
            )
        _sha256(self.content_digest, "reference_component.content_digest")
        if digest(payload) != self.content_digest:
            raise IntegrityError("reference_component content digest mismatch")

    def payload_dict(self) -> dict[str, Any]:
        return _manifest_payload(
            self.schema_version,
            self.component_id,
            self.manufacturer,
            self.part_number,
            self.revision,
            self.title,
            self.source_model_digest,
            self.unit,
            self.evidence,
            self.reference_frames,
            self.occupied_bounds,
            self.occupied_bounds_evidence_id,
            self.envelopes,
            self.mass_properties,
            self.allowed_operations,
            self.known_fields,
            self.unknown_fields,
            self.evidence_gates,
        )

    def as_dict(self) -> dict[str, Any]:
        return {**self.payload_dict(), "content_digest": self.content_digest}

    @classmethod
    def from_dict(
        cls, raw: Any, *, field: str = "reference_component"
    ) -> ReferenceComponentManifest:
        _bounded_tree(raw, field)
        keys = {
            "schema_version",
            "component_id",
            "manufacturer",
            "part_number",
            "revision",
            "title",
            "source_model_digest",
            "unit",
            "evidence",
            "reference_frames",
            "occupied_bounds",
            "occupied_bounds_evidence_id",
            "envelopes",
            "mass_properties",
            "allowed_operations",
            "known_fields",
            "unknown_fields",
            "evidence_gates",
            "legal_gate_disclaimer",
            "content_digest",
        }
        values = _exact_dict(raw, keys, field)
        if (
            values["legal_gate_disclaimer"] != LEGAL_GATE_DISCLAIMER
            or type(values["legal_gate_disclaimer"]) is not str
        ):
            raise InputError(
                f"{field}.legal_gate_disclaimer must use the schema-defined nonclaim"
            )
        list_specs = (
            ("evidence", MAX_EVIDENCE_RECORDS),
            ("reference_frames", MAX_REFERENCE_FRAMES),
            ("envelopes", MAX_SPATIAL_ENVELOPES),
            ("allowed_operations", len(AllowedOperation)),
            ("known_fields", MAX_KNOWN_FIELDS),
            ("unknown_fields", MAX_UNKNOWN_FIELDS),
            ("evidence_gates", len(GateName)),
        )
        for name, maximum in list_specs:
            if type(values[name]) is not list or len(values[name]) > maximum:
                raise InputError(
                    f"{field}.{name} must be a list within the {maximum}-item limit"
                )
        evidence = tuple(
            EvidenceRecord.from_dict(item, field=f"{field}.evidence[{index}]")
            for index, item in enumerate(values["evidence"])
        )
        frames = tuple(
            ReferenceFrame.from_dict(item, field=f"{field}.reference_frames[{index}]")
            for index, item in enumerate(values["reference_frames"])
        )
        envelopes = tuple(
            SpatialEnvelope.from_dict(item, field=f"{field}.envelopes[{index}]")
            for index, item in enumerate(values["envelopes"])
        )
        mass = (
            None
            if values["mass_properties"] is None
            else MassProperties.from_dict(
                values["mass_properties"], field=f"{field}.mass_properties"
            )
        )
        return cls(
            values["schema_version"],
            _string(values["component_id"], f"{field}.component_id", identifier=True),
            _string(values["manufacturer"], f"{field}.manufacturer"),
            _string(values["part_number"], f"{field}.part_number", identifier=True),
            _string(values["revision"], f"{field}.revision", identifier=True),
            _string(values["title"], f"{field}.title"),
            _sha256(values["source_model_digest"], f"{field}.source_model_digest"),
            values["unit"],
            evidence,
            frames,
            ExactBox.from_dict(
                values["occupied_bounds"], field=f"{field}.occupied_bounds"
            ),
            _string(
                values["occupied_bounds_evidence_id"],
                f"{field}.occupied_bounds_evidence_id",
                identifier=True,
            ),
            envelopes,
            mass,
            tuple(
                _enum(AllowedOperation, item, f"{field}.allowed_operations[{index}]")
                for index, item in enumerate(values["allowed_operations"])
            ),
            tuple(
                KnownField.from_dict(item, field=f"{field}.known_fields[{index}]")
                for index, item in enumerate(values["known_fields"])
            ),
            tuple(
                UnknownField.from_dict(item, field=f"{field}.unknown_fields[{index}]")
                for index, item in enumerate(values["unknown_fields"])
            ),
            tuple(
                EvidenceGate.from_dict(item, field=f"{field}.evidence_gates[{index}]")
                for index, item in enumerate(values["evidence_gates"])
            ),
            _sha256(values["content_digest"], f"{field}.content_digest"),
        )


def seal_reference_component(payload: Any) -> dict[str, Any]:
    """Return a digest-sealed document after full schema validation."""

    _bounded_tree(payload, "reference_component_payload")
    if type(payload) is not dict or "content_digest" in payload:
        raise InputError("reference_component_payload must be an unsealed object")
    document = {**payload, "content_digest": digest(payload)}
    return ReferenceComponentManifest.from_dict(document).as_dict()


@dataclass(frozen=True, slots=True)
class ClearanceRequirement:
    envelope_id: str
    clearance_mm: Fraction

    __init_subclass__ = classmethod(_no_subclass)

    def __post_init__(self) -> None:
        _string(self.envelope_id, "clearance.envelope_id", identifier=True)
        if (
            type(self.clearance_mm) is not Fraction
            or self.clearance_mm < 0
            or len(_fraction_text(self.clearance_mm)) > MAX_EXACT_SCALAR_CHARACTERS
        ):
            raise InputError(
                "clearance.clearance_mm must be a bounded non-negative exact Fraction"
            )

    @classmethod
    def from_dict(cls, raw: Any, *, field: str) -> ClearanceRequirement:
        values = _exact_dict(raw, {"envelope_id", "clearance_mm"}, field)
        return cls(
            _string(values["envelope_id"], f"{field}.envelope_id", identifier=True),
            _fraction(
                values["clearance_mm"], f"{field}.clearance_mm", nonnegative=True
            ),
        )

    def as_dict(self) -> dict[str, str]:
        return {
            "envelope_id": self.envelope_id,
            "clearance_mm": _fraction_text(self.clearance_mm),
        }


def _request_payload(
    schema_version: str,
    request_id: str,
    reference_component_digest: str,
    occurrence_id: str,
    flexible_domains: tuple[DesignDomain, ...],
    required_interface_ids: tuple[str, ...],
    clearances: tuple[ClearanceRequirement, ...],
) -> dict[str, Any]:
    return {
        "schema_version": schema_version,
        "request_id": request_id,
        "reference_component_digest": reference_component_digest,
        "occurrence_id": occurrence_id,
        "flexible_domains": [item.value for item in flexible_domains],
        "required_interface_ids": list(required_interface_ids),
        "clearances": [item.as_dict() for item in clearances],
    }


@dataclass(frozen=True, slots=True)
class DesignAroundRequest:
    schema_version: str
    request_id: str
    reference_component_digest: str
    occurrence_id: str
    flexible_domains: tuple[DesignDomain, ...]
    required_interface_ids: tuple[str, ...]
    clearances: tuple[ClearanceRequirement, ...]
    content_digest: str

    __init_subclass__ = classmethod(_no_subclass)

    def __post_init__(self) -> None:
        if (
            type(self.schema_version) is not str
            or self.schema_version != DESIGN_AROUND_REQUEST_SCHEMA
        ):
            raise InputError(
                f"design_around_request.schema_version must be {DESIGN_AROUND_REQUEST_SCHEMA!r}"
            )
        _string(self.request_id, "design_around_request.request_id", identifier=True)
        _sha256(
            self.reference_component_digest,
            "design_around_request.reference_component_digest",
        )
        _string(
            self.occurrence_id, "design_around_request.occurrence_id", identifier=True
        )
        if (
            type(self.flexible_domains) is not tuple
            or not 1 <= len(self.flexible_domains) <= MAX_FLEXIBLE_DOMAINS
            or not all(type(item) is DesignDomain for item in self.flexible_domains)
        ):
            raise InputError(
                "design_around_request.flexible_domains must be a non-empty bounded tuple"
            )
        if (
            type(self.required_interface_ids) is not tuple
            or len(self.required_interface_ids) > MAX_REFERENCE_FRAMES
        ):
            raise InputError(
                "design_around_request.required_interface_ids must be a bounded tuple"
            )
        if (
            type(self.clearances) is not tuple
            or len(self.clearances) > MAX_CLEARANCE_REQUIREMENTS
            or not all(type(item) is ClearanceRequirement for item in self.clearances)
        ):
            raise InputError("design_around_request.clearances must be a bounded tuple")
        for index, item in enumerate(self.required_interface_ids):
            _string(
                item,
                f"design_around_request.required_interface_ids[{index}]",
                identifier=True,
            )
        _ordered(
            self.flexible_domains,
            lambda item: item.value,
            "design_around_request.flexible_domains",
        )
        _unique(
            tuple(item.value for item in self.flexible_domains),
            "design_around_request.flexible_domains",
        )
        if tuple(sorted(self.required_interface_ids)) != self.required_interface_ids:
            raise InputError(
                "design_around_request.required_interface_ids must be in canonical order"
            )
        _ordered(
            self.clearances,
            lambda item: item.envelope_id,
            "design_around_request.clearances",
        )
        _unique(
            self.required_interface_ids, "design_around_request.required_interface_ids"
        )
        _unique(
            tuple(item.envelope_id for item in self.clearances),
            "design_around_request clearance envelope identifiers",
        )
        _sha256(self.content_digest, "design_around_request.content_digest")
        if digest(self.payload_dict()) != self.content_digest:
            raise IntegrityError("design_around_request content digest mismatch")

    def payload_dict(self) -> dict[str, Any]:
        return _request_payload(
            self.schema_version,
            self.request_id,
            self.reference_component_digest,
            self.occurrence_id,
            self.flexible_domains,
            self.required_interface_ids,
            self.clearances,
        )

    def as_dict(self) -> dict[str, Any]:
        return {**self.payload_dict(), "content_digest": self.content_digest}

    @classmethod
    def from_dict(
        cls, raw: Any, *, field: str = "design_around_request"
    ) -> DesignAroundRequest:
        _bounded_tree(raw, field)
        values = _exact_dict(
            raw,
            {
                "schema_version",
                "request_id",
                "reference_component_digest",
                "occurrence_id",
                "flexible_domains",
                "required_interface_ids",
                "clearances",
                "content_digest",
            },
            field,
        )
        for name, maximum in (
            ("flexible_domains", MAX_FLEXIBLE_DOMAINS),
            ("required_interface_ids", MAX_REFERENCE_FRAMES),
            ("clearances", MAX_CLEARANCE_REQUIREMENTS),
        ):
            if type(values[name]) is not list or len(values[name]) > maximum:
                raise InputError(
                    f"{field}.{name} must be a list within the {maximum}-item limit"
                )
        return cls(
            values["schema_version"],
            _string(values["request_id"], f"{field}.request_id", identifier=True),
            _sha256(
                values["reference_component_digest"],
                f"{field}.reference_component_digest",
            ),
            _string(values["occurrence_id"], f"{field}.occurrence_id", identifier=True),
            tuple(
                _enum(DesignDomain, item, f"{field}.flexible_domains[{index}]")
                for index, item in enumerate(values["flexible_domains"])
            ),
            tuple(
                _string(
                    item, f"{field}.required_interface_ids[{index}]", identifier=True
                )
                for index, item in enumerate(values["required_interface_ids"])
            ),
            tuple(
                ClearanceRequirement.from_dict(
                    item, field=f"{field}.clearances[{index}]"
                )
                for index, item in enumerate(values["clearances"])
            ),
            _sha256(values["content_digest"], f"{field}.content_digest"),
        )


def seal_design_around_request(payload: Any) -> dict[str, Any]:
    _bounded_tree(payload, "design_around_request_payload")
    if type(payload) is not dict or "content_digest" in payload:
        raise InputError("design_around_request_payload must be an unsealed object")
    document = {**payload, "content_digest": digest(payload)}
    return DesignAroundRequest.from_dict(document).as_dict()


@dataclass(frozen=True, slots=True)
class ProjectedConstraint:
    constraint_id: str
    kind: ConstraintKind
    source_path: str
    value_digest: str
    evidence_ids: tuple[str, ...]
    authority: EvidenceAuthority | None
    resolution_required: bool

    __init_subclass__ = classmethod(_no_subclass)

    def __post_init__(self) -> None:
        _string(
            self.constraint_id, "projected_constraint.constraint_id", identifier=True
        )
        if type(self.kind) is not ConstraintKind:
            raise InputError("projected_constraint.kind must use the exact enum")
        _field_path(self.source_path, "projected_constraint.source_path")
        _sha256(self.value_digest, "projected_constraint.value_digest")
        if type(self.evidence_ids) is not tuple:
            raise InputError("projected_constraint.evidence_ids must be a tuple")
        if len(self.evidence_ids) > MAX_EVIDENCE_RECORDS:
            raise InputError(
                "projected_constraint.evidence_ids exceeds the resource limit"
            )
        for item in self.evidence_ids:
            _string(item, "projected_constraint.evidence_id", identifier=True)
        if tuple(sorted(self.evidence_ids)) != self.evidence_ids or len(
            set(self.evidence_ids)
        ) != len(self.evidence_ids):
            raise InputError(
                "projected_constraint.evidence_ids must be unique and canonical"
            )
        if self.authority is not None and type(self.authority) is not EvidenceAuthority:
            raise InputError(
                "projected_constraint.authority must be an exact enum or null"
            )
        if type(self.resolution_required) is not bool:
            raise InputError("projected_constraint.resolution_required must be a bool")

    def as_dict(self) -> dict[str, Any]:
        return {
            "constraint_id": self.constraint_id,
            "kind": self.kind.value,
            "source_path": self.source_path,
            "value_digest": self.value_digest,
            "evidence_ids": list(self.evidence_ids),
            "authority": None if self.authority is None else self.authority.value,
            "resolution_required": self.resolution_required,
        }

    @classmethod
    def from_dict(cls, raw: Any, *, field: str) -> ProjectedConstraint:
        values = _exact_dict(
            raw,
            {
                "constraint_id",
                "kind",
                "source_path",
                "value_digest",
                "evidence_ids",
                "authority",
                "resolution_required",
            },
            field,
        )
        evidence_ids = values["evidence_ids"]
        if type(evidence_ids) is not list or len(evidence_ids) > MAX_EVIDENCE_RECORDS:
            raise InputError(f"{field}.evidence_ids must be a bounded list")
        authority_raw = values["authority"]
        if authority_raw is not None and type(authority_raw) is not str:
            raise InputError(f"{field}.authority must be a string or null")
        if type(values["resolution_required"]) is not bool:
            raise InputError(f"{field}.resolution_required must be a bool")
        return cls(
            _string(values["constraint_id"], f"{field}.constraint_id", identifier=True),
            _enum(ConstraintKind, values["kind"], f"{field}.kind"),
            _field_path(values["source_path"], f"{field}.source_path"),
            _sha256(values["value_digest"], f"{field}.value_digest"),
            tuple(
                _string(item, f"{field}.evidence_ids[{index}]", identifier=True)
                for index, item in enumerate(evidence_ids)
            ),
            (
                None
                if authority_raw is None
                else _enum(EvidenceAuthority, authority_raw, f"{field}.authority")
            ),
            values["resolution_required"],
        )


@dataclass(frozen=True, slots=True)
class FlexibleDesignBinding:
    domain: DesignDomain
    interface_ids: tuple[str, ...]

    __init_subclass__ = classmethod(_no_subclass)

    def __post_init__(self) -> None:
        if (
            type(self.domain) is not DesignDomain
            or type(self.interface_ids) is not tuple
        ):
            raise InputError("flexible_design_binding must use exact typed values")
        if len(self.interface_ids) > MAX_REFERENCE_FRAMES:
            raise InputError(
                "flexible_design_binding.interface_ids exceeds the resource limit"
            )
        for item in self.interface_ids:
            _string(item, "flexible_design_binding.interface_id", identifier=True)
        if tuple(sorted(self.interface_ids)) != self.interface_ids or len(
            set(self.interface_ids)
        ) != len(self.interface_ids):
            raise InputError(
                "flexible_design_binding.interface_ids must be unique and canonical"
            )

    def as_dict(self) -> dict[str, Any]:
        return {"domain": self.domain.value, "interface_ids": list(self.interface_ids)}

    @classmethod
    def from_dict(cls, raw: Any, *, field: str) -> FlexibleDesignBinding:
        values = _exact_dict(raw, {"domain", "interface_ids"}, field)
        interface_ids = values["interface_ids"]
        if type(interface_ids) is not list or len(interface_ids) > MAX_REFERENCE_FRAMES:
            raise InputError(f"{field}.interface_ids must be a bounded list")
        return cls(
            _enum(DesignDomain, values["domain"], f"{field}.domain"),
            tuple(
                _string(item, f"{field}.interface_ids[{index}]", identifier=True)
                for index, item in enumerate(interface_ids)
            ),
        )


def _projection_payload(
    schema_version: str,
    request_digest: str,
    reference_component_digest: str,
    occurrence_id: str,
    protected_constraints: tuple[ProjectedConstraint, ...],
    flexible_bindings: tuple[FlexibleDesignBinding, ...],
    evidence_blockers: tuple[str, ...],
) -> dict[str, Any]:
    return {
        "schema_version": schema_version,
        "request_digest": request_digest,
        "reference_component_digest": reference_component_digest,
        "occurrence_id": occurrence_id,
        "protected_constraints": [item.as_dict() for item in protected_constraints],
        "flexible_bindings": [item.as_dict() for item in flexible_bindings],
        "evidence_blockers": list(evidence_blockers),
        "legal_gate_disclaimer": LEGAL_GATE_DISCLAIMER,
    }


@dataclass(frozen=True, slots=True)
class DesignAroundProjection:
    schema_version: str
    request_digest: str
    reference_component_digest: str
    occurrence_id: str
    protected_constraints: tuple[ProjectedConstraint, ...]
    flexible_bindings: tuple[FlexibleDesignBinding, ...]
    evidence_blockers: tuple[str, ...]
    content_digest: str

    __init_subclass__ = classmethod(_no_subclass)

    def __post_init__(self) -> None:
        if (
            type(self.schema_version) is not str
            or self.schema_version != DESIGN_AROUND_PROJECTION_SCHEMA
        ):
            raise InputError(
                f"design_around_projection.schema_version must be {DESIGN_AROUND_PROJECTION_SCHEMA!r}"
            )
        _sha256(self.request_digest, "design_around_projection.request_digest")
        _sha256(
            self.reference_component_digest,
            "design_around_projection.reference_component_digest",
        )
        _string(
            self.occurrence_id,
            "design_around_projection.occurrence_id",
            identifier=True,
        )
        if (
            type(self.protected_constraints) is not tuple
            or len(self.protected_constraints) > MAX_JSON_NODES
            or not all(
                type(item) is ProjectedConstraint for item in self.protected_constraints
            )
        ):
            raise InputError(
                "design_around_projection.protected_constraints must be a bounded exact tuple"
            )
        if (
            type(self.flexible_bindings) is not tuple
            or len(self.flexible_bindings) > MAX_FLEXIBLE_DOMAINS
            or not all(
                type(item) is FlexibleDesignBinding for item in self.flexible_bindings
            )
        ):
            raise InputError(
                "design_around_projection.flexible_bindings must be a bounded exact tuple"
            )
        if (
            type(self.evidence_blockers) is not tuple
            or len(self.evidence_blockers) > MAX_JSON_NODES
        ):
            raise InputError(
                "design_around_projection.evidence_blockers must be a bounded tuple"
            )
        for item in self.evidence_blockers:
            _string(item, "design_around_projection.evidence_blocker")
        _ordered(
            self.protected_constraints,
            lambda item: item.constraint_id,
            "design_around_projection.protected_constraints",
        )
        _ordered(
            self.flexible_bindings,
            lambda item: item.domain.value,
            "design_around_projection.flexible_bindings",
        )
        _unique(
            tuple(item.domain.value for item in self.flexible_bindings),
            "design_around_projection.flexible binding domains",
        )
        if tuple(sorted(self.evidence_blockers)) != self.evidence_blockers:
            raise InputError(
                "design_around_projection.evidence_blockers must be canonical"
            )
        _unique(
            self.evidence_blockers,
            "design_around_projection.evidence_blockers",
        )
        _unique(
            tuple(item.constraint_id for item in self.protected_constraints),
            "design_around_projection constraint identifiers",
        )
        _sha256(self.content_digest, "design_around_projection.content_digest")
        if digest(self.payload_dict()) != self.content_digest:
            raise IntegrityError("design_around_projection content digest mismatch")

    def payload_dict(self) -> dict[str, Any]:
        return _projection_payload(
            self.schema_version,
            self.request_digest,
            self.reference_component_digest,
            self.occurrence_id,
            self.protected_constraints,
            self.flexible_bindings,
            self.evidence_blockers,
        )

    def as_dict(self) -> dict[str, Any]:
        return {**self.payload_dict(), "content_digest": self.content_digest}

    @classmethod
    def from_dict(
        cls, raw: Any, *, field: str = "design_around_projection"
    ) -> DesignAroundProjection:
        _bounded_tree(raw, field)
        values = _exact_dict(
            raw,
            {
                "schema_version",
                "request_digest",
                "reference_component_digest",
                "occurrence_id",
                "protected_constraints",
                "flexible_bindings",
                "evidence_blockers",
                "legal_gate_disclaimer",
                "content_digest",
            },
            field,
        )
        if (
            type(values["legal_gate_disclaimer"]) is not str
            or values["legal_gate_disclaimer"] != LEGAL_GATE_DISCLAIMER
        ):
            raise InputError(
                f"{field}.legal_gate_disclaimer must use the schema-defined nonclaim"
            )
        protected = values["protected_constraints"]
        flexible = values["flexible_bindings"]
        blockers = values["evidence_blockers"]
        if type(protected) is not list or len(protected) > MAX_JSON_NODES:
            raise InputError(f"{field}.protected_constraints must be a bounded list")
        if type(flexible) is not list or len(flexible) > MAX_FLEXIBLE_DOMAINS:
            raise InputError(f"{field}.flexible_bindings must be a bounded list")
        if type(blockers) is not list or len(blockers) > MAX_JSON_NODES:
            raise InputError(f"{field}.evidence_blockers must be a bounded list")
        return cls(
            values["schema_version"],
            _sha256(values["request_digest"], f"{field}.request_digest"),
            _sha256(
                values["reference_component_digest"],
                f"{field}.reference_component_digest",
            ),
            _string(values["occurrence_id"], f"{field}.occurrence_id", identifier=True),
            tuple(
                ProjectedConstraint.from_dict(
                    item, field=f"{field}.protected_constraints[{index}]"
                )
                for index, item in enumerate(protected)
            ),
            tuple(
                FlexibleDesignBinding.from_dict(
                    item, field=f"{field}.flexible_bindings[{index}]"
                )
                for index, item in enumerate(flexible)
            ),
            tuple(
                _string(item, f"{field}.evidence_blockers[{index}]")
                for index, item in enumerate(blockers)
            ),
            _sha256(values["content_digest"], f"{field}.content_digest"),
        )


def _constraint(
    identifier: str,
    kind: ConstraintKind,
    path: str,
    value: Any,
    evidence: tuple[EvidenceRecord, ...] = (),
    *,
    resolution_required: bool = False,
) -> ProjectedConstraint:
    authorities = {item.authority for item in evidence}
    authority = next(iter(authorities)) if len(authorities) == 1 else None
    return ProjectedConstraint(
        identifier,
        kind,
        path,
        digest(value),
        tuple(sorted(item.evidence_id for item in evidence)),
        authority,
        resolution_required,
    )


def project_design_around(
    manifest: ReferenceComponentManifest, request: DesignAroundRequest
) -> DesignAroundProjection:
    """Project a fixed component into protected and intentionally flexible constraints.

    The projection preserves evidence grades.  In particular, observational scan or
    Gaussian-splat geometry remains observational and creates a blocker rather than
    silently becoming an authoritative dimension.
    """

    if (
        type(manifest) is not ReferenceComponentManifest
        or type(request) is not DesignAroundRequest
    ):
        raise InputError(
            "project_design_around requires exact parsed manifest and request values"
        )
    manifest = ReferenceComponentManifest.from_dict(manifest.as_dict())
    request = DesignAroundRequest.from_dict(request.as_dict())
    if request.reference_component_digest != manifest.content_digest:
        raise IntegrityError(
            "design-around request binds a different reference component"
        )
    interfaces = {
        item.frame_id
        for item in manifest.reference_frames
        if item.role is FrameRole.INTERFACE
    }
    missing_interfaces = sorted(set(request.required_interface_ids) - interfaces)
    if missing_interfaces:
        raise InputError(
            f"design-around request names unknown interface frames: {', '.join(missing_interfaces)}"
        )
    envelope_by_id = {item.envelope_id: item for item in manifest.envelopes}
    missing_envelopes = sorted(
        {item.envelope_id for item in request.clearances} - set(envelope_by_id)
    )
    if missing_envelopes:
        raise InputError(
            f"design-around request names unknown envelopes: {', '.join(missing_envelopes)}"
        )
    evidence = {item.evidence_id: item for item in manifest.evidence}
    constraints: list[ProjectedConstraint] = []
    identity_records = tuple(
        item
        for item in manifest.evidence
        if _supports_path(item, "/identity", exact=True)
    )
    constraints.append(
        _constraint(
            "identity",
            ConstraintKind.IDENTITY,
            "/identity",
            {
                "component_id": manifest.component_id,
                "manufacturer": manifest.manufacturer,
                "part_number": manifest.part_number,
                "revision": manifest.revision,
            },
            identity_records,
            resolution_required=any(
                _needs_independent_resolution(item.authority)
                for item in identity_records
            ),
        )
    )
    source_records = tuple(
        item
        for item in manifest.evidence
        if item.artifact_digest == manifest.source_model_digest
    )
    constraints.append(
        _constraint(
            "source-model",
            ConstraintKind.SOURCE_MODEL,
            "/source_model_digest",
            manifest.source_model_digest,
            source_records,
            resolution_required=any(
                _needs_independent_resolution(item.authority) for item in source_records
            ),
        )
    )
    occupied_evidence = (evidence[manifest.occupied_bounds_evidence_id],)
    constraints.append(
        _constraint(
            "occupied-bounds",
            ConstraintKind.OCCUPIED_BOUNDS,
            "/occupied_bounds",
            manifest.occupied_bounds.as_dict(),
            occupied_evidence,
            resolution_required=_needs_independent_resolution(
                occupied_evidence[0].authority
            ),
        )
    )
    for frame in manifest.reference_frames:
        frame_evidence = (evidence[frame.evidence_id],)
        constraints.append(
            _constraint(
                f"frame:{frame.frame_id}",
                ConstraintKind.FRAME,
                f"/reference_frames/{frame.frame_id}",
                frame.as_dict(),
                frame_evidence,
                resolution_required=_needs_independent_resolution(
                    frame_evidence[0].authority
                ),
            )
        )
    for envelope in manifest.envelopes:
        envelope_evidence = (evidence[envelope.evidence_id],)
        constraints.append(
            _constraint(
                f"envelope:{envelope.envelope_id}",
                ConstraintKind.ENVELOPE,
                f"/envelopes/{envelope.envelope_id}",
                envelope.as_dict(),
                envelope_evidence,
                resolution_required=_needs_independent_resolution(
                    envelope_evidence[0].authority
                ),
            )
        )
    if manifest.mass_properties is not None:
        mass_evidence = (evidence[manifest.mass_properties.evidence_id],)
        constraints.append(
            _constraint(
                "mass-properties",
                ConstraintKind.MASS_PROPERTIES,
                "/mass_properties",
                manifest.mass_properties.as_dict(),
                mass_evidence,
                resolution_required=_needs_independent_resolution(
                    mass_evidence[0].authority
                ),
            )
        )
    constraints.append(
        _constraint(
            "allowed-operations",
            ConstraintKind.ALLOWED_OPERATIONS,
            "/allowed_operations",
            [item.value for item in manifest.allowed_operations],
        )
    )
    for gate in manifest.evidence_gates:
        gate_evidence = tuple(evidence[item] for item in gate.evidence_ids)
        constraints.append(
            _constraint(
                f"gate:{gate.name.value}",
                ConstraintKind.EVIDENCE_GATE,
                f"/evidence_gates/{gate.name.value}",
                gate.as_dict(),
                gate_evidence,
                resolution_required=gate.disposition is GateDisposition.UNREVIEWED,
            )
        )
    manifest_payload = manifest.payload_dict()
    for known in manifest.known_fields:
        known_evidence = (evidence[known.evidence_id],)
        constraints.append(
            _constraint(
                f"known:{digest(known.field_path)[7:23]}",
                ConstraintKind.KNOWN_FIELD,
                known.field_path,
                _resolve_pointer(
                    manifest_payload,
                    known.field_path,
                    field=f"known field {known.field_path!r}",
                ),
                known_evidence,
                resolution_required=_needs_independent_resolution(
                    known_evidence[0].authority
                ),
            )
        )
    for unknown in manifest.unknown_fields:
        constraints.append(
            _constraint(
                f"unknown:{digest(unknown.field_path)[7:23]}",
                ConstraintKind.UNKNOWN_FIELD,
                unknown.field_path,
                unknown.as_dict(),
                (),
                resolution_required=True,
            )
        )
    for clearance in request.clearances:
        constraints.append(
            _constraint(
                f"clearance:{clearance.envelope_id}",
                ConstraintKind.CLEARANCE,
                f"/request/clearances/{clearance.envelope_id}",
                clearance.as_dict(),
                (evidence[envelope_by_id[clearance.envelope_id].evidence_id],),
                resolution_required=_needs_independent_resolution(
                    evidence[
                        envelope_by_id[clearance.envelope_id].evidence_id
                    ].authority
                ),
            )
        )
    protected = tuple(sorted(constraints, key=lambda item: item.constraint_id))
    bindings = tuple(
        FlexibleDesignBinding(domain, request.required_interface_ids)
        for domain in request.flexible_domains
    )
    blockers = [f"unknown:{item.field_path}" for item in manifest.unknown_fields]
    blockers.extend(
        f"evidence-resolution:{item.source_path}"
        for item in protected
        if item.resolution_required
        and item.kind
        in {
            ConstraintKind.IDENTITY,
            ConstraintKind.SOURCE_MODEL,
            ConstraintKind.OCCUPIED_BOUNDS,
            ConstraintKind.FRAME,
            ConstraintKind.ENVELOPE,
            ConstraintKind.MASS_PROPERTIES,
            ConstraintKind.KNOWN_FIELD,
            ConstraintKind.CLEARANCE,
        }
    )
    blockers.extend(
        f"gate:{item.name.value}:{item.disposition.value}"
        for item in manifest.evidence_gates
        if item.disposition
        not in {GateDisposition.ACCEPTED_FOR_PROJECT, GateDisposition.NOT_APPLICABLE}
    )
    blockers_tuple = tuple(sorted(set(blockers)))
    payload = _projection_payload(
        DESIGN_AROUND_PROJECTION_SCHEMA,
        request.content_digest,
        manifest.content_digest,
        request.occurrence_id,
        protected,
        bindings,
        blockers_tuple,
    )
    return DesignAroundProjection(
        DESIGN_AROUND_PROJECTION_SCHEMA,
        request.content_digest,
        manifest.content_digest,
        request.occurrence_id,
        protected,
        bindings,
        blockers_tuple,
        digest(payload),
    )


def _oracle_constraint_document(
    constraint_id: str,
    kind: ConstraintKind,
    source_path: str,
    value: Any,
    records: tuple[EvidenceRecord, ...] = (),
    *,
    resolution_required: bool = False,
) -> dict[str, Any]:
    authority_values = {item.authority for item in records}
    authority = next(iter(authority_values)) if len(authority_values) == 1 else None
    return {
        "constraint_id": constraint_id,
        "kind": kind.value,
        "source_path": source_path,
        "value_digest": digest(value),
        "evidence_ids": sorted(item.evidence_id for item in records),
        "authority": None if authority is None else authority.value,
        "resolution_required": resolution_required,
    }


def _oracle_requires_resolution(authority: EvidenceAuthority) -> bool:
    return authority.value not in {"documented_source", "verified_measurement"}


def _oracle_has_exact_identity_support(record: EvidenceRecord) -> bool:
    return "/identity" in record.supports


def _oracle_resolve_pointer(document: Any, path: str) -> Any:
    current = document
    raw_segments = path[1:].split("/")
    for raw_segment in raw_segments:
        segment = raw_segment.replace("~1", "/").replace("~0", "~")
        if type(current) is dict:
            if segment not in current:
                raise InputError("oracle field path does not resolve")
            current = current[segment]
        elif type(current) is list:
            if (
                not segment.isascii()
                or not segment.isdigit()
                or (len(segment) > 1 and segment[0] == "0")
            ):
                raise InputError("oracle field path has a non-canonical list index")
            index = int(segment)
            if index >= len(current):
                raise InputError("oracle field path list index is out of range")
            current = current[index]
        else:
            raise InputError("oracle field path descends through a scalar")
    return current


def _independent_projection_payload(
    manifest: ReferenceComponentManifest,
    request: DesignAroundRequest,
) -> dict[str, Any]:
    """Reconstruct projection semantics without using the production projector."""

    evidence_by_id = {item.evidence_id: item for item in manifest.evidence}
    interface_ids = {
        item.frame_id
        for item in manifest.reference_frames
        if item.role is FrameRole.INTERFACE
    }
    if not set(request.required_interface_ids) <= interface_ids:
        raise InputError("oracle request contains an unknown interface")
    envelopes = {item.envelope_id: item for item in manifest.envelopes}
    if not {item.envelope_id for item in request.clearances} <= set(envelopes):
        raise InputError("oracle request contains an unknown envelope")

    expected: list[dict[str, Any]] = []
    identity_evidence = tuple(
        item for item in manifest.evidence if _oracle_has_exact_identity_support(item)
    )
    expected.append(
        _oracle_constraint_document(
            "identity",
            ConstraintKind.IDENTITY,
            "/identity",
            {
                "component_id": manifest.component_id,
                "manufacturer": manifest.manufacturer,
                "part_number": manifest.part_number,
                "revision": manifest.revision,
            },
            identity_evidence,
            resolution_required=any(
                _oracle_requires_resolution(item.authority)
                for item in identity_evidence
            ),
        )
    )
    source_evidence = tuple(
        item
        for item in manifest.evidence
        if item.artifact_digest == manifest.source_model_digest
    )
    expected.append(
        _oracle_constraint_document(
            "source-model",
            ConstraintKind.SOURCE_MODEL,
            "/source_model_digest",
            manifest.source_model_digest,
            source_evidence,
            resolution_required=any(
                _oracle_requires_resolution(item.authority) for item in source_evidence
            ),
        )
    )
    occupied_record = evidence_by_id[manifest.occupied_bounds_evidence_id]
    expected.append(
        _oracle_constraint_document(
            "occupied-bounds",
            ConstraintKind.OCCUPIED_BOUNDS,
            "/occupied_bounds",
            manifest.occupied_bounds.as_dict(),
            (occupied_record,),
            resolution_required=_oracle_requires_resolution(occupied_record.authority),
        )
    )
    for frame in manifest.reference_frames:
        record = evidence_by_id[frame.evidence_id]
        expected.append(
            _oracle_constraint_document(
                f"frame:{frame.frame_id}",
                ConstraintKind.FRAME,
                f"/reference_frames/{frame.frame_id}",
                frame.as_dict(),
                (record,),
                resolution_required=_oracle_requires_resolution(record.authority),
            )
        )
    for envelope in manifest.envelopes:
        record = evidence_by_id[envelope.evidence_id]
        expected.append(
            _oracle_constraint_document(
                f"envelope:{envelope.envelope_id}",
                ConstraintKind.ENVELOPE,
                f"/envelopes/{envelope.envelope_id}",
                envelope.as_dict(),
                (record,),
                resolution_required=_oracle_requires_resolution(record.authority),
            )
        )
    if manifest.mass_properties is not None:
        record = evidence_by_id[manifest.mass_properties.evidence_id]
        expected.append(
            _oracle_constraint_document(
                "mass-properties",
                ConstraintKind.MASS_PROPERTIES,
                "/mass_properties",
                manifest.mass_properties.as_dict(),
                (record,),
                resolution_required=_oracle_requires_resolution(record.authority),
            )
        )
    expected.append(
        _oracle_constraint_document(
            "allowed-operations",
            ConstraintKind.ALLOWED_OPERATIONS,
            "/allowed_operations",
            [item.value for item in manifest.allowed_operations],
        )
    )
    for gate in manifest.evidence_gates:
        records = tuple(evidence_by_id[item] for item in gate.evidence_ids)
        expected.append(
            _oracle_constraint_document(
                f"gate:{gate.name.value}",
                ConstraintKind.EVIDENCE_GATE,
                f"/evidence_gates/{gate.name.value}",
                gate.as_dict(),
                records,
                resolution_required=gate.disposition is GateDisposition.UNREVIEWED,
            )
        )
    semantic_manifest = manifest.payload_dict()
    for known in manifest.known_fields:
        record = evidence_by_id[known.evidence_id]
        expected.append(
            _oracle_constraint_document(
                f"known:{digest(known.field_path)[7:23]}",
                ConstraintKind.KNOWN_FIELD,
                known.field_path,
                _oracle_resolve_pointer(semantic_manifest, known.field_path),
                (record,),
                resolution_required=_oracle_requires_resolution(record.authority),
            )
        )
    for unknown in manifest.unknown_fields:
        expected.append(
            _oracle_constraint_document(
                f"unknown:{digest(unknown.field_path)[7:23]}",
                ConstraintKind.UNKNOWN_FIELD,
                unknown.field_path,
                unknown.as_dict(),
                resolution_required=True,
            )
        )
    for clearance in request.clearances:
        envelope = envelopes[clearance.envelope_id]
        record = evidence_by_id[envelope.evidence_id]
        expected.append(
            _oracle_constraint_document(
                f"clearance:{clearance.envelope_id}",
                ConstraintKind.CLEARANCE,
                f"/request/clearances/{clearance.envelope_id}",
                clearance.as_dict(),
                (record,),
                resolution_required=_oracle_requires_resolution(record.authority),
            )
        )
    expected.sort(key=lambda item: item["constraint_id"])

    blockers = {f"unknown:{item.field_path}" for item in manifest.unknown_fields}
    evidence_ceiling_kinds = {
        ConstraintKind.IDENTITY.value,
        ConstraintKind.SOURCE_MODEL.value,
        ConstraintKind.OCCUPIED_BOUNDS.value,
        ConstraintKind.FRAME.value,
        ConstraintKind.ENVELOPE.value,
        ConstraintKind.MASS_PROPERTIES.value,
        ConstraintKind.KNOWN_FIELD.value,
        ConstraintKind.CLEARANCE.value,
    }
    blockers.update(
        f"evidence-resolution:{item['source_path']}"
        for item in expected
        if item["resolution_required"] and item["kind"] in evidence_ceiling_kinds
    )
    blockers.update(
        f"gate:{gate.name.value}:{gate.disposition.value}"
        for gate in manifest.evidence_gates
        if gate.disposition
        not in {GateDisposition.ACCEPTED_FOR_PROJECT, GateDisposition.NOT_APPLICABLE}
    )
    return {
        "schema_version": DESIGN_AROUND_PROJECTION_SCHEMA,
        "request_digest": request.content_digest,
        "reference_component_digest": manifest.content_digest,
        "occurrence_id": request.occurrence_id,
        "protected_constraints": expected,
        "flexible_bindings": [
            {
                "domain": domain.value,
                "interface_ids": list(request.required_interface_ids),
            }
            for domain in request.flexible_domains
        ],
        "evidence_blockers": sorted(blockers),
        "legal_gate_disclaimer": LEGAL_GATE_DISCLAIMER,
    }


def verify_design_around_projection(
    manifest: ReferenceComponentManifest,
    request: DesignAroundRequest,
    projection: DesignAroundProjection,
) -> bool:
    if (
        type(manifest) is not ReferenceComponentManifest
        or type(request) is not DesignAroundRequest
        or type(projection) is not DesignAroundProjection
    ):
        return False
    try:
        checked_manifest = ReferenceComponentManifest.from_dict(manifest.as_dict())
        checked_request = DesignAroundRequest.from_dict(request.as_dict())
        checked_projection = DesignAroundProjection.from_dict(projection.as_dict())
        if (
            checked_request.reference_component_digest
            != checked_manifest.content_digest
        ):
            return False
        expected = _independent_projection_payload(
            checked_manifest,
            checked_request,
        )
    except (AttributeError, InputError, IntegrityError, TypeError, ValueError):
        return False
    return checked_projection.payload_dict() == expected
