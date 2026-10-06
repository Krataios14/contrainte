from __future__ import annotations

import hashlib
import os
import stat
import tempfile
from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal
from fractions import Fraction
from pathlib import Path
from typing import Any

from .artifacts import file_digest
from .assembly import (
    ASSEMBLY_BUNDLE_SCHEMA,
    Assembly,
    analyze_assembly,
    verify_assembly_bundle,
)
from .cad import CAD_BUNDLE_SCHEMA, PrismaticPart, build_part_shape, verify_cad_bundle
from .canonical import decimal_text, digest, dumps_pretty, loads_strict
from .component import (
    COMPONENT_SCHEMA,
    COMPONENT_SCHEMA_V3,
    COMPONENT_SCHEMA_V4,
    ArtifactRef,
    ArtifactRole,
    ComponentInterface,
    ComponentManifest,
    ExactGeometryBounds,
    InterfaceAttachmentKind,
    InterfaceAttachmentRole,
    LifecycleState,
    Qualification,
)
from .errors import InputError, IntegrityError
from .geometry import kernel_measurement
from .sketch import (
    SKETCH_BUNDLE_SCHEMA,
    SKETCH_BUNDLE_SCHEMA_V2,
    SKETCH_BUNDLE_SCHEMA_V3,
    SketchExtrusion,
    build_sketch_shape,
    verify_sketch_bundle,
)
from .solid import (
    SOLID_BUNDLE_SCHEMA,
    SolidProgram,
    analyze_solid_program,
    verify_solid_bundle,
)

RELEASE_REQUEST_SCHEMA = "contrainte.component-release-request/0.1"
RELEASE_REQUEST_SCHEMA_V2 = "contrainte.component-release-request/0.2"
RELEASE_REQUEST_SCHEMA_V3 = "contrainte.component-release-request/0.3"
_LEGACY_RESERVED_METADATA = {
    "derivation",
    "engineering_bundle_schema",
    "engineering_bundle_content_digest",
}
_FRAMED_RESERVED_METADATA = {
    *_LEGACY_RESERVED_METADATA,
    "component_release_request_content_digest",
}
_TOPOLOGY_RESERVED_METADATA = _FRAMED_RESERVED_METADATA
_ARTIFACT_ROLES = {
    "exact_geometry": ArtifactRole.EXACT_GEOMETRY,
    "exact_assembly": ArtifactRole.EXACT_GEOMETRY,
    "mesh": ArtifactRole.MESH,
    "visualization_mesh": ArtifactRole.MESH,
    "assembly_mesh": ArtifactRole.MESH,
    "drawing": ArtifactRole.DRAWING,
}
_MAX_SOURCE_BYTES = 4 * 1024 * 1024
_MAX_RELEASE_REQUEST_BYTES = 1024 * 1024
_MAX_COMPONENT_INTERFACES = 64
_MAX_RELEASE_ARTIFACT_BYTES = 64 * 1024 * 1024
_MAX_RELEASE_CHAIN_BYTES = 128 * 1024 * 1024
_MAX_RELEASE_ARTIFACTS = 128
# Every accepted sketch-bundle version is fully self-verifying: the sketch
# verifier re-solves the embedded constraints (including 0.3 midpoints),
# rebuilds the B-rep and rejects cross-version relabelling.
_RELEASABLE_SKETCH_BUNDLE_SCHEMAS = frozenset(
    {SKETCH_BUNDLE_SCHEMA, SKETCH_BUNDLE_SCHEMA_V2, SKETCH_BUNDLE_SCHEMA_V3}
)


def _is_link_or_reparse(path: Path) -> bool:
    try:
        if path.is_symlink():
            return True
        attributes = getattr(path.lstat(), "st_file_attributes", 0)
    except OSError:
        return False
    return bool(attributes & stat.FILE_ATTRIBUTE_REPARSE_POINT)


def _release_stat_identity(value: os.stat_result) -> tuple[int, ...]:
    return (
        value.st_dev,
        value.st_ino,
        value.st_mode,
        value.st_size,
        value.st_mtime_ns,
        value.st_nlink,
    )


def _read_stable_release_file(
    path: Path,
    *,
    maximum_bytes: int,
    field: str,
    expected_digest: str | None = None,
) -> bytes:
    try:
        before = path.lstat()
    except OSError as exc:
        raise InputError(f"{field} is unavailable: {exc}") from exc
    if stat.S_ISLNK(before.st_mode) or _is_link_or_reparse(path):
        raise InputError(f"{field} cannot be a link or reparse point")
    if not stat.S_ISREG(before.st_mode):
        raise InputError(f"{field} must be a regular file")
    if before.st_nlink != 1:
        raise InputError(f"{field} cannot be a hard-linked file")
    if before.st_size > maximum_bytes:
        raise InputError(f"{field} exceeds its byte limit")
    captured = bytearray()
    try:
        with path.open("rb") as handle:
            opened = os.fstat(handle.fileno())
            if _release_stat_identity(opened) != _release_stat_identity(before):
                raise InputError(f"{field} changed before it could be read")
            while True:
                block = handle.read(min(1024 * 1024, maximum_bytes + 1 - len(captured)))
                if not block:
                    break
                captured.extend(block)
                if len(captured) > maximum_bytes:
                    raise InputError(f"{field} exceeds its byte limit")
            after_handle = os.fstat(handle.fileno())
        after_path = path.lstat()
    except OSError as exc:
        raise InputError(f"cannot read {field}: {exc}") from exc
    identity = _release_stat_identity(before)
    if (
        _release_stat_identity(after_handle) != identity
        or _release_stat_identity(after_path) != identity
        or len(captured) != before.st_size
    ):
        raise InputError(f"{field} changed while it was being read")
    value = bytes(captured)
    if expected_digest is not None:
        actual = f"sha256:{hashlib.sha256(value).hexdigest()}"
        if actual != expected_digest:
            raise IntegrityError(f"{field} digest mismatch")
    return value


def _string(raw: Mapping[str, Any], name: str, field: str) -> str:
    value = raw.get(name)
    if not isinstance(value, str) or not value:
        raise InputError(f"{field}.{name} must be a non-empty string")
    return value


@dataclass(frozen=True)
class ComponentReleaseRequest:
    schema_version: str
    component_id: str
    revision: str
    title: str
    interfaces: tuple[ComponentInterface, ...]
    capabilities: tuple[str, ...]
    metadata: Mapping[str, str]

    def __post_init__(self) -> None:
        if self.schema_version not in {
            RELEASE_REQUEST_SCHEMA,
            RELEASE_REQUEST_SCHEMA_V2,
            RELEASE_REQUEST_SCHEMA_V3,
        }:
            raise InputError(
                f"unsupported component release request schema: {self.schema_version!r}"
            )
        framed = tuple(interface.frame is not None for interface in self.interfaces)
        attached = tuple(
            interface.attachment is not None for interface in self.interfaces
        )
        evidenced = tuple(
            interface.attachment is not None
            and interface.attachment.evidence is not None
            for interface in self.interfaces
        )
        if self.schema_version == RELEASE_REQUEST_SCHEMA and any(framed):
            raise InputError(
                "component release request schema 0.1 does not support interface frames"
            )
        if self.schema_version == RELEASE_REQUEST_SCHEMA_V2 and not all(framed):
            raise InputError(
                "component release request schema 0.2 requires every interface frame"
            )
        if self.schema_version in {
            RELEASE_REQUEST_SCHEMA,
            RELEASE_REQUEST_SCHEMA_V2,
        } and any(attached):
            raise InputError(
                "component release request schemas before 0.3 do not support "
                "interface attachments"
            )
        if self.schema_version == RELEASE_REQUEST_SCHEMA_V3:
            if len(self.interfaces) > _MAX_COMPONENT_INTERFACES:
                raise InputError(
                    "component release request interfaces exceeds its count limit"
                )
            if not all(framed):
                raise InputError(
                    "component release request schema 0.3 requires every interface frame"
                )
            if not all(attached):
                raise InputError(
                    "component release request schema 0.3 requires every interface attachment"
                )
            if any(evidenced):
                raise InputError(
                    "component release request schema 0.3 cannot supply derived "
                    "attachment evidence"
                )

    @classmethod
    def from_dict(
        cls, raw: Any, *, field: str = "component_release_request"
    ) -> ComponentReleaseRequest:
        if not isinstance(raw, dict):
            raise InputError(f"{field} must be an object")
        allowed = {
            "schema_version",
            "component_id",
            "revision",
            "title",
            "interfaces",
            "capabilities",
            "metadata",
        }
        unknown = sorted(set(raw) - allowed)
        if unknown:
            raise InputError(
                f"{field} contains unsupported fields: {', '.join(unknown)}"
            )
        schema = _string(raw, "schema_version", field)
        if schema not in {
            RELEASE_REQUEST_SCHEMA,
            RELEASE_REQUEST_SCHEMA_V2,
            RELEASE_REQUEST_SCHEMA_V3,
        }:
            raise InputError(
                f"unsupported component release request schema: {schema!r}"
            )
        interfaces_raw = raw.get("interfaces", [])
        if not isinstance(interfaces_raw, list):
            raise InputError(f"{field}.interfaces must be a list")
        if (
            schema == RELEASE_REQUEST_SCHEMA_V3
            and len(interfaces_raw) > _MAX_COMPONENT_INTERFACES
        ):
            raise InputError(f"{field}.interfaces exceeds its count limit")
        interfaces = tuple(
            ComponentInterface.from_dict(
                item,
                field=f"{field}.interfaces[{index}]",
                frame_required=schema
                in {RELEASE_REQUEST_SCHEMA_V2, RELEASE_REQUEST_SCHEMA_V3},
                attachment_required=schema == RELEASE_REQUEST_SCHEMA_V3,
                attachment_evidence_required=False,
            )
            for index, item in enumerate(interfaces_raw)
        )
        interface_ids = [item.interface_id for item in interfaces]
        if len(interface_ids) != len(set(interface_ids)):
            raise InputError(f"{field}.interface identifiers must be unique")
        capabilities_raw = raw.get("capabilities", [])
        if not isinstance(capabilities_raw, list) or not all(
            isinstance(item, str) and item for item in capabilities_raw
        ):
            raise InputError(f"{field}.capabilities must contain non-empty strings")
        capabilities = tuple(capabilities_raw)
        if len(capabilities) != len(set(capabilities)):
            raise InputError(f"{field}.capabilities must be unique")
        if capabilities != tuple(sorted(capabilities)):
            raise InputError(f"{field}.capabilities must be in ascending lexical order")
        metadata_raw = raw.get("metadata", {})
        if not isinstance(metadata_raw, dict) or not all(
            isinstance(key, str) and key and isinstance(value, str) and value
            for key, value in metadata_raw.items()
        ):
            raise InputError(f"{field}.metadata must map non-empty strings")
        reserved_names = (
            _TOPOLOGY_RESERVED_METADATA
            if schema == RELEASE_REQUEST_SCHEMA_V3
            else _FRAMED_RESERVED_METADATA
            if schema == RELEASE_REQUEST_SCHEMA_V2
            else _LEGACY_RESERVED_METADATA
        )
        reserved = sorted(set(metadata_raw) & reserved_names)
        if reserved:
            raise InputError(
                f"{field}.metadata uses reserved keys: {', '.join(reserved)}"
            )
        return cls(
            schema,
            _string(raw, "component_id", field),
            _string(raw, "revision", field),
            _string(raw, "title", field),
            interfaces,
            capabilities,
            dict(metadata_raw),
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "component_id": self.component_id,
            "revision": self.revision,
            "title": self.title,
            "interfaces": [
                item.as_dict(include_attachment_evidence=False)
                for item in self.interfaces
            ],
            "capabilities": list(self.capabilities),
            "metadata": dict(self.metadata),
        }


def load_release_request(path: str | Path) -> ComponentReleaseRequest:
    source = Path(path)
    try:
        request_bytes = _read_stable_release_file(
            source,
            maximum_bytes=_MAX_RELEASE_REQUEST_BYTES,
            field="component release request",
        )
        return ComponentReleaseRequest.from_dict(loads_strict(request_bytes))
    except OSError as exc:
        raise InputError(
            f"cannot read component release request {source}: {exc}"
        ) from exc


_STOCK_FACE_DIRECTIONS = {
    InterfaceAttachmentRole.NEGATIVE_X: (Fraction(-1), Fraction(0), Fraction(0)),
    InterfaceAttachmentRole.POSITIVE_X: (Fraction(1), Fraction(0), Fraction(0)),
    InterfaceAttachmentRole.NEGATIVE_Y: (Fraction(0), Fraction(-1), Fraction(0)),
    InterfaceAttachmentRole.POSITIVE_Y: (Fraction(0), Fraction(1), Fraction(0)),
    InterfaceAttachmentRole.NEGATIVE_Z: (Fraction(0), Fraction(0), Fraction(-1)),
    InterfaceAttachmentRole.POSITIVE_Z: (Fraction(0), Fraction(0), Fraction(1)),
}
_HOLE_AXIS_DIRECTION = (Fraction(0), Fraction(0), Fraction(1))
_AXIS_NAMES = ("x", "y", "z")


def _fraction_text(value: Fraction) -> str:
    if value.denominator == 1:
        return str(value.numerator)
    return f"{value.numerator}/{value.denominator}"


def _point_document(values: tuple[Decimal, Decimal, Decimal]) -> dict[str, str]:
    return {
        axis: decimal_text(value)
        for axis, value in zip(_AXIS_NAMES, values, strict=True)
    }


def _direction_document(
    values: tuple[Fraction, Fraction, Fraction],
) -> dict[str, str]:
    return {
        axis: _fraction_text(value)
        for axis, value in zip(_AXIS_NAMES, values, strict=True)
    }


def _kernel_vector(value: Any) -> tuple[Decimal, Decimal, Decimal]:
    return tuple(
        kernel_measurement(getattr(value, axis.upper())) for axis in _AXIS_NAMES
    )  # type: ignore[return-value]


def _kernel_point_distance_is_zero(face: Any, origin: tuple[Decimal, ...]) -> bool:
    try:
        from build123d import Vector
    except ImportError as exc:  # pragma: no cover - CAD verifier imports first
        raise InputError(
            "the CAD backend is required for topology attachment evidence"
        ) from exc
    point = Vector(*(float(value) for value in origin))
    return kernel_measurement(face.distance_to(point)) == 0


def _stock_feature_document(part: PrismaticPart) -> dict[str, Any]:
    return {
        "feature_id": "stock",
        "stock": part.as_dict()["stock"],
    }


def _stock_face_contract(
    part: PrismaticPart,
    role: InterfaceAttachmentRole,
) -> tuple[int, Decimal, tuple[Fraction, Fraction, Fraction]]:
    half_length = part.length.to("mm").value / 2
    half_width = part.width.to("mm").value / 2
    thickness = part.thickness.to("mm").value
    contracts = {
        InterfaceAttachmentRole.NEGATIVE_X: (0, -half_length),
        InterfaceAttachmentRole.POSITIVE_X: (0, half_length),
        InterfaceAttachmentRole.NEGATIVE_Y: (1, -half_width),
        InterfaceAttachmentRole.POSITIVE_Y: (1, half_width),
        InterfaceAttachmentRole.NEGATIVE_Z: (2, Decimal(0)),
        InterfaceAttachmentRole.POSITIVE_Z: (2, thickness),
    }
    try:
        axis_index, coordinate = contracts[role]
        direction = _STOCK_FACE_DIRECTIONS[role]
    except KeyError as exc:  # pragma: no cover - selector parser guards this
        raise InputError("unsupported prismatic stock-face attachment role") from exc
    return axis_index, coordinate, direction


def _require_stock_face_origin(
    part: PrismaticPart,
    role: InterfaceAttachmentRole,
    origin: tuple[Decimal, Decimal, Decimal],
    *,
    field: str,
) -> None:
    half_length = part.length.to("mm").value / 2
    half_width = part.width.to("mm").value / 2
    thickness = part.thickness.to("mm").value
    axis_index, coordinate, _ = _stock_face_contract(part, role)
    if origin[axis_index] != coordinate:
        raise InputError(f"{field} origin is not on the selected stock-face plane")
    if axis_index == 0:
        inside = -half_width < origin[1] < half_width and 0 < origin[2] < thickness
    elif axis_index == 1:
        inside = -half_length < origin[0] < half_length and 0 < origin[2] < thickness
    else:
        inside = (
            -half_length < origin[0] < half_length
            and -half_width < origin[1] < half_width
        )
        if inside:
            for hole in part.holes:
                dx = origin[0] - hole.x.to("mm").value
                dy = origin[1] - hole.y.to("mm").value
                radius = hole.diameter.to("mm").value / 2
                if dx * dx + dy * dy <= radius * radius:
                    inside = False
                    break
    if not inside:
        raise InputError(
            f"{field} origin must lie strictly inside the selected stock face"
        )


def _compiler_stock_face_matches(
    shape: Any,
    *,
    axis_index: int,
    coordinate: Decimal,
    direction: tuple[Fraction, Fraction, Fraction],
) -> list[Any]:
    try:
        from build123d import GeomType
    except ImportError as exc:  # pragma: no cover - CAD verifier imports first
        raise InputError(
            "the CAD backend is required for topology attachment evidence"
        ) from exc
    expected_direction = tuple(Decimal(value.numerator) for value in direction)
    expected_coordinate = kernel_measurement(coordinate)
    matches = []
    for face in shape.faces():
        if face.geom_type is not GeomType.PLANE:
            continue
        if _kernel_vector(face.normal_at()) != expected_direction:
            continue
        center = face.center()
        if (
            kernel_measurement(getattr(center, _AXIS_NAMES[axis_index].upper()))
            == expected_coordinate
        ):
            matches.append(face)
    return matches


def _compiler_hole_face_matches(shape: Any, hole: Any) -> list[Any]:
    try:
        from build123d import GeomType
    except ImportError as exc:  # pragma: no cover - CAD verifier imports first
        raise InputError(
            "the CAD backend is required for topology attachment evidence"
        ) from exc
    expected_xy = (
        kernel_measurement(hole.x.to("mm").value),
        kernel_measurement(hole.y.to("mm").value),
    )
    expected_radius = kernel_measurement(hole.diameter.to("mm").value / 2)
    expected_directions = {
        (
            Decimal("0.000000000"),
            Decimal("0.000000000"),
            Decimal("1.000000000"),
        ),
        (
            Decimal("0.000000000"),
            Decimal("0.000000000"),
            Decimal("-1.000000000"),
        ),
    }
    matches = []
    for face in shape.faces():
        if face.geom_type is not GeomType.CYLINDER:
            continue
        axis = face.axis_of_rotation
        if (
            _kernel_vector(axis.position)[:2] == expected_xy
            and _kernel_vector(axis.direction) in expected_directions
            and kernel_measurement(face.radius) == expected_radius
        ):
            matches.append(face)
    return matches


def _derive_attachment_evidence(
    part: PrismaticPart,
    shape: Any,
    interface: ComponentInterface,
    *,
    field: str,
) -> dict[str, Any]:
    if interface.frame is None or interface.attachment is None:
        raise InputError(f"{field} requires a frame and attachment selector")
    if interface.attachment.evidence is not None:
        raise InputError(f"{field} cannot supply derived attachment evidence")
    selector = interface.attachment.selector
    origin = tuple(interface.frame.origin[axis] for axis in _AXIS_NAMES)
    if selector.kind is InterfaceAttachmentKind.PRISMATIC_STOCK_FACE:
        _require_stock_face_origin(part, selector.role, origin, field=field)
        axis_index, coordinate, direction = _stock_face_contract(part, selector.role)
        if interface.frame.z_axis != direction:
            raise InputError(
                f"{field} frame z_axis must match the selected stock-face normal"
            )
        matches = _compiler_stock_face_matches(
            shape,
            axis_index=axis_index,
            coordinate=coordinate,
            direction=direction,
        )
        if len(matches) != 1:
            raise InputError(
                f"{field} selector resolved to {len(matches)} kernel faces, expected 1"
            )
        if not _kernel_point_distance_is_zero(matches[0], origin):
            raise InputError(f"{field} origin is not on the reproduced kernel face")
        return {
            "source_feature_digest": digest(_stock_feature_document(part)),
            "matched_face_count": 1,
            "surface_type": "plane",
            "origin_on_surface": True,
            "orientation_matches": True,
            "characteristic_point_mm": _point_document(origin),
            "direction": _direction_document(direction),
        }

    hole = next(
        (item for item in part.holes if item.hole_id == selector.feature_id), None
    )
    if hole is None:
        raise InputError(
            f"{field} references unknown prismatic through-hole {selector.feature_id!r}"
        )
    radius = hole.diameter.to("mm").value / 2
    center_x = hole.x.to("mm").value
    center_y = hole.y.to("mm").value
    thickness = part.thickness.to("mm").value
    dx = origin[0] - center_x
    dy = origin[1] - center_y
    if dx * dx + dy * dy != radius * radius or not 0 < origin[2] < thickness:
        raise InputError(
            f"{field} origin must lie strictly on the selected cylindrical hole wall"
        )
    if interface.frame.z_axis != _HOLE_AXIS_DIRECTION:
        raise InputError(f"{field} frame z_axis must match the through-hole axis")
    matches = _compiler_hole_face_matches(shape, hole)
    if len(matches) != 1:
        raise InputError(
            f"{field} selector resolved to {len(matches)} kernel faces, expected 1"
        )
    if not _kernel_point_distance_is_zero(matches[0], origin):
        raise InputError(f"{field} origin is not on the reproduced kernel face")
    return {
        "source_feature_digest": digest(hole.as_dict()),
        "matched_face_count": 1,
        "surface_type": "cylinder",
        "origin_on_surface": True,
        "orientation_matches": True,
        "characteristic_point_mm": _point_document(origin),
        "direction": _direction_document(_HOLE_AXIS_DIRECTION),
        "radius_mm": decimal_text(radius),
    }


def _derive_topology_interfaces(
    document: Mapping[str, Any],
    schema: str,
    interfaces: tuple[ComponentInterface, ...],
) -> list[dict[str, Any]]:
    if schema != CAD_BUNDLE_SCHEMA:
        raise InputError(
            "topology-backed component release 0.3 currently requires a verified "
            "prismatic CAD bundle"
        )
    part = PrismaticPart.from_dict(document["content"]["part"])
    shape = build_part_shape(part)
    derived = []
    for index, interface in enumerate(interfaces):
        interface_document = interface.as_dict(include_attachment_evidence=False)
        evidence = _derive_attachment_evidence(
            part,
            shape,
            interface,
            field=f"component_release_request.interfaces[{index}].attachment",
        )
        interface_document["attachment"]["evidence"] = evidence
        derived.append(interface_document)
    return derived


def _oracle_attachment_evidence(
    part: PrismaticPart,
    shape: Any,
    interface: ComponentInterface,
    *,
    field: str,
) -> dict[str, Any]:
    """Reproduce attachment evidence without using the derivation matchers."""

    try:
        from build123d import GeomType, Vector
    except ImportError as exc:  # pragma: no cover - CAD verifier imports first
        raise IntegrityError(
            "the CAD backend is required to replay topology attachment evidence"
        ) from exc
    if interface.frame is None or interface.attachment is None:
        raise IntegrityError(f"{field} lost its required frame or attachment")
    selector = interface.attachment.selector
    origin = tuple(interface.frame.origin[axis] for axis in _AXIS_NAMES)
    point = Vector(*(float(value) for value in origin))
    half_length = part.length.to("mm").value / 2
    half_width = part.width.to("mm").value / 2
    thickness = part.thickness.to("mm").value

    if selector.kind is InterfaceAttachmentKind.PRISMATIC_STOCK_FACE:
        expected = {
            InterfaceAttachmentRole.NEGATIVE_X: (
                0,
                -half_length,
                (Fraction(-1), Fraction(0), Fraction(0)),
            ),
            InterfaceAttachmentRole.POSITIVE_X: (
                0,
                half_length,
                (Fraction(1), Fraction(0), Fraction(0)),
            ),
            InterfaceAttachmentRole.NEGATIVE_Y: (
                1,
                -half_width,
                (Fraction(0), Fraction(-1), Fraction(0)),
            ),
            InterfaceAttachmentRole.POSITIVE_Y: (
                1,
                half_width,
                (Fraction(0), Fraction(1), Fraction(0)),
            ),
            InterfaceAttachmentRole.NEGATIVE_Z: (
                2,
                Decimal(0),
                (Fraction(0), Fraction(0), Fraction(-1)),
            ),
            InterfaceAttachmentRole.POSITIVE_Z: (
                2,
                thickness,
                (Fraction(0), Fraction(0), Fraction(1)),
            ),
        }
        try:
            axis_index, coordinate, direction = expected[selector.role]
        except KeyError as exc:  # pragma: no cover - selector parser guards this
            raise IntegrityError(f"{field} has an unsupported stock-face role") from exc
        if origin[axis_index] != coordinate or interface.frame.z_axis != direction:
            raise IntegrityError(
                f"{field} frame no longer satisfies the selected stock-face plane"
            )
        if axis_index == 0:
            interior = (
                -half_width < origin[1] < half_width
                and Decimal(0) < origin[2] < thickness
            )
        elif axis_index == 1:
            interior = (
                -half_length < origin[0] < half_length
                and Decimal(0) < origin[2] < thickness
            )
        else:
            interior = (
                -half_length < origin[0] < half_length
                and -half_width < origin[1] < half_width
            )
            if interior:
                for hole in part.holes:
                    x_delta = origin[0] - hole.x.to("mm").value
                    y_delta = origin[1] - hole.y.to("mm").value
                    hole_radius = hole.diameter.to("mm").value / 2
                    if (
                        x_delta * x_delta + y_delta * y_delta
                        <= hole_radius * hole_radius
                    ):
                        interior = False
                        break
        if not interior:
            raise IntegrityError(
                f"{field} frame is not strictly inside the selected stock face"
            )
        wanted_direction = tuple(Decimal(value.numerator) for value in direction)
        wanted_coordinate = kernel_measurement(coordinate)
        matches = []
        for face in shape.faces():
            if face.geom_type is not GeomType.PLANE:
                continue
            normal = tuple(
                kernel_measurement(getattr(face.normal_at(), axis.upper()))
                for axis in _AXIS_NAMES
            )
            center_coordinate = kernel_measurement(
                getattr(face.center(), _AXIS_NAMES[axis_index].upper())
            )
            if normal == wanted_direction and center_coordinate == wanted_coordinate:
                matches.append(face)
        if len(matches) != 1 or kernel_measurement(matches[0].distance_to(point)) != 0:
            raise IntegrityError(
                f"{field} does not reproduce one containing planar kernel face"
            )
        return {
            "source_feature_digest": digest(
                {
                    "feature_id": "stock",
                    "stock": part.as_dict()["stock"],
                }
            ),
            "matched_face_count": 1,
            "surface_type": "plane",
            "origin_on_surface": True,
            "orientation_matches": True,
            "characteristic_point_mm": {
                axis: decimal_text(origin[index])
                for index, axis in enumerate(_AXIS_NAMES)
            },
            "direction": {
                axis: _fraction_text(direction[index])
                for index, axis in enumerate(_AXIS_NAMES)
            },
        }

    matching_holes = [
        hole for hole in part.holes if hole.hole_id == selector.feature_id
    ]
    if len(matching_holes) != 1:
        raise IntegrityError(
            f"{field} does not identify exactly one authored through-hole"
        )
    hole = matching_holes[0]
    radius = hole.diameter.to("mm").value / 2
    x_delta = origin[0] - hole.x.to("mm").value
    y_delta = origin[1] - hole.y.to("mm").value
    if (
        x_delta * x_delta + y_delta * y_delta != radius * radius
        or not Decimal(0) < origin[2] < thickness
        or interface.frame.z_axis != _HOLE_AXIS_DIRECTION
    ):
        raise IntegrityError(
            f"{field} frame no longer lies on the authored cylindrical hole wall"
        )
    wanted_xy = (
        kernel_measurement(hole.x.to("mm").value),
        kernel_measurement(hole.y.to("mm").value),
    )
    wanted_axes = {
        (
            Decimal("0.000000000"),
            Decimal("0.000000000"),
            Decimal("1.000000000"),
        ),
        (
            Decimal("0.000000000"),
            Decimal("0.000000000"),
            Decimal("-1.000000000"),
        ),
    }
    wanted_radius = kernel_measurement(radius)
    matches = []
    for face in shape.faces():
        if face.geom_type is not GeomType.CYLINDER:
            continue
        axis = face.axis_of_rotation
        axis_position = tuple(
            kernel_measurement(getattr(axis.position, name.upper()))
            for name in _AXIS_NAMES
        )
        axis_direction = tuple(
            kernel_measurement(getattr(axis.direction, name.upper()))
            for name in _AXIS_NAMES
        )
        if (
            axis_position[:2] == wanted_xy
            and axis_direction in wanted_axes
            and kernel_measurement(face.radius) == wanted_radius
        ):
            matches.append(face)
    if len(matches) != 1 or kernel_measurement(matches[0].distance_to(point)) != 0:
        raise IntegrityError(
            f"{field} does not reproduce one containing cylindrical kernel face"
        )
    return {
        "source_feature_digest": digest(hole.as_dict()),
        "matched_face_count": 1,
        "surface_type": "cylinder",
        "origin_on_surface": True,
        "orientation_matches": True,
        "characteristic_point_mm": {
            axis: decimal_text(origin[index]) for index, axis in enumerate(_AXIS_NAMES)
        },
        "direction": {
            axis: _fraction_text(_HOLE_AXIS_DIRECTION[index])
            for index, axis in enumerate(_AXIS_NAMES)
        },
        "radius_mm": decimal_text(radius),
    }


def _verify_topology_interfaces(
    document: Mapping[str, Any],
    schema: str,
    interfaces: tuple[ComponentInterface, ...],
) -> None:
    if schema != CAD_BUNDLE_SCHEMA:
        raise IntegrityError(
            "topology-backed component no longer resolves to a prismatic CAD bundle"
        )
    part = PrismaticPart.from_dict(document["content"]["part"])
    shape = build_part_shape(part)
    for index, interface in enumerate(interfaces):
        if interface.attachment is None or interface.attachment.evidence is None:
            raise IntegrityError(
                f"component interface {index} lost its derived attachment evidence"
            )
        request_document = interface.as_dict(include_attachment_evidence=False)
        try:
            request_interface = ComponentInterface.from_dict(
                request_document,
                field=f"component.interfaces[{index}]",
                frame_required=True,
                attachment_required=True,
                attachment_evidence_required=False,
            )
        except InputError as exc:
            raise IntegrityError(
                f"component interface {index} no longer satisfies attachment request rules"
            ) from exc
        expected = _oracle_attachment_evidence(
            part,
            shape,
            request_interface,
            field=f"component.interfaces[{index}].attachment",
        )
        if interface.attachment.evidence.as_dict() != expected:
            raise IntegrityError(
                f"component interface {index} attachment evidence does not reproduce"
            )


def derive_component_manifest(
    bundle_path: str | Path, request: ComponentReleaseRequest
) -> ComponentManifest:
    source = Path(bundle_path).resolve()
    document, schema, artifacts, source_bundle_digest = _verified_bundle_artifacts(
        source
    )
    geometry_bounds = _exact_geometry_bounds(document, schema)
    metadata = dict(request.metadata)
    topology_release = request.schema_version == RELEASE_REQUEST_SCHEMA_V3
    framed_release = request.schema_version in {
        RELEASE_REQUEST_SCHEMA_V2,
        RELEASE_REQUEST_SCHEMA_V3,
    }
    interfaces = (
        _derive_topology_interfaces(document, schema, request.interfaces)
        if topology_release
        else [item.as_dict() for item in request.interfaces]
    )
    metadata.update(
        {
            "derivation": (
                "verified_exact_bundle/0.3"
                if topology_release
                else "verified_exact_bundle/0.2"
                if framed_release
                else "verified_exact_bundle/0.1"
            ),
            "engineering_bundle_schema": schema,
            "engineering_bundle_content_digest": document["digest"],
        }
    )
    if framed_release:
        metadata["component_release_request_content_digest"] = digest(request.as_dict())
    return ComponentManifest.from_dict(
        {
            "schema_version": COMPONENT_SCHEMA_V4
            if topology_release
            else COMPONENT_SCHEMA_V3
            if framed_release
            else COMPONENT_SCHEMA,
            "component_id": request.component_id,
            "revision": request.revision,
            "title": request.title,
            "lifecycle_state": LifecycleState.CONCEPT.value,
            "qualification": Qualification.UNQUALIFIED_DEMONSTRATION.value,
            "source_bundle_digest": source_bundle_digest,
            "artifacts": [item.as_dict() for item in artifacts],
            "interfaces": interfaces,
            "capabilities": list(request.capabilities),
            "geometry_bounds": geometry_bounds.as_dict(),
            "metadata": metadata,
        }
    )


def write_component_manifest(
    output_path: str | Path,
    manifest: ComponentManifest,
    *,
    bundle_path: str | Path,
) -> None:
    destination = Path(output_path).resolve()
    source = Path(bundle_path).resolve()
    if destination.parent != source.parent:
        raise InputError(
            "a derived local component manifest must be written beside its evidence bundle"
        )
    try:
        destination.write_text(
            dumps_pretty(manifest.as_dict()), encoding="utf-8", newline="\n"
        )
    except OSError as exc:
        raise InputError(
            f"cannot write component manifest {destination}: {exc}"
        ) from exc


def verify_local_component_manifest(manifest_path: str | Path) -> dict[str, str]:
    supplied = Path(manifest_path)
    manifest_bytes = _read_stable_release_file(
        supplied,
        maximum_bytes=_MAX_SOURCE_BYTES,
        field="component manifest",
    )
    path = supplied.resolve()
    manifest = ComponentManifest.from_dict(loads_strict(manifest_bytes))
    report, _, _ = _verify_local_component_value(path, manifest)
    return report


def _verify_local_component_value(
    path: Path, manifest: ComponentManifest
) -> tuple[dict[str, str], Mapping[str, Any], str]:
    if manifest.lifecycle_state is not LifecycleState.CONCEPT:
        raise IntegrityError("derived component lifecycle state was promoted")
    if manifest.qualification is not Qualification.UNQUALIFIED_DEMONSTRATION:
        raise IntegrityError("derived component qualification was promoted")
    engineering = [
        item
        for item in manifest.artifacts
        if item.role is ArtifactRole.ENGINEERING_BUNDLE
    ]
    if len(engineering) != 1:
        raise IntegrityError("derived component must have one engineering bundle")
    bundle_locator = _safe_locator(engineering[0].locator)
    bundle_path = path.parent / bundle_locator
    (
        document,
        schema,
        expected_artifacts,
        source_bundle_digest,
    ) = _verified_bundle_artifacts(bundle_path)
    if manifest.source_bundle_digest != source_bundle_digest:
        raise IntegrityError("component source-bundle byte digest does not reproduce")
    if manifest.artifacts != expected_artifacts:
        raise IntegrityError(
            "component artifacts do not exactly match the verified engineering bundle"
        )
    expected_bounds = _exact_geometry_bounds(document, schema)
    if manifest.geometry_bounds != expected_bounds:
        raise IntegrityError(
            "component geometry bounds do not reproduce from the engineering bundle"
        )
    for artifact in manifest.artifacts:
        locator = _safe_locator(artifact.locator)
        local_path = path.parent / locator
        if not local_path.is_file() or file_digest(local_path) != artifact.digest:
            raise IntegrityError(f"component artifact does not reproduce: {locator}")
    if manifest.schema_version == COMPONENT_SCHEMA_V4:
        _verify_topology_interfaces(document, schema, manifest.interfaces)
    expected_metadata = {
        "derivation": (
            "verified_exact_bundle/0.3"
            if manifest.schema_version == COMPONENT_SCHEMA_V4
            else "verified_exact_bundle/0.2"
            if manifest.schema_version == COMPONENT_SCHEMA_V3
            else "verified_exact_bundle/0.1"
        ),
        "engineering_bundle_schema": schema,
        "engineering_bundle_content_digest": document["digest"],
    }
    if manifest.schema_version in {COMPONENT_SCHEMA_V3, COMPONENT_SCHEMA_V4}:
        topology_release = manifest.schema_version == COMPONENT_SCHEMA_V4
        request_document = {
            "schema_version": (
                RELEASE_REQUEST_SCHEMA_V3
                if topology_release
                else RELEASE_REQUEST_SCHEMA_V2
            ),
            "component_id": manifest.component_id,
            "revision": manifest.revision,
            "title": manifest.title,
            "interfaces": [
                item.as_dict(include_attachment_evidence=not topology_release)
                for item in manifest.interfaces
            ],
            "capabilities": list(manifest.capabilities),
            "metadata": {
                key: value
                for key, value in manifest.metadata.items()
                if key
                not in (
                    _TOPOLOGY_RESERVED_METADATA
                    if topology_release
                    else _FRAMED_RESERVED_METADATA
                )
            },
        }
        try:
            reproduced_request = ComponentReleaseRequest.from_dict(request_document)
        except InputError as exc:
            raise IntegrityError(
                "component fields no longer satisfy the framed release request schema"
            ) from exc
        expected_metadata["component_release_request_content_digest"] = digest(
            reproduced_request.as_dict()
        )
    reserved_names = (
        _TOPOLOGY_RESERVED_METADATA
        if manifest.schema_version == COMPONENT_SCHEMA_V4
        else _FRAMED_RESERVED_METADATA
        if manifest.schema_version == COMPONENT_SCHEMA_V3
        else _LEGACY_RESERVED_METADATA
    )
    actual_system_metadata = set(manifest.metadata) & reserved_names
    if actual_system_metadata != set(expected_metadata):
        raise IntegrityError(
            "component derivation system metadata does not match its schema"
        )
    for key, value in expected_metadata.items():
        if manifest.metadata.get(key) != value:
            raise IntegrityError(f"component derivation metadata mismatch: {key}")
    return (
        {
            "status": "verified",
            "component_id": manifest.component_id,
            "manifest_digest": manifest.manifest_digest,
            "source_bundle_digest": manifest.source_bundle_digest,
            "engineering_bundle_content_digest": document["digest"],
        },
        document,
        schema,
    )


def _release_artifact_size(path: Path, locator: str, maximum_bytes: int) -> int:
    if _is_link_or_reparse(path):
        raise InputError(
            "component release artifacts cannot be links or reparse points"
        )
    try:
        metadata = path.lstat()
    except OSError as exc:
        raise InputError(
            f"component release artifact is unavailable: {locator}"
        ) from exc
    if not stat.S_ISREG(metadata.st_mode):
        raise InputError("component release artifact must be a regular file")
    if metadata.st_nlink != 1:
        raise InputError("component release artifacts cannot be hard-linked files")
    if metadata.st_size > maximum_bytes:
        raise InputError(
            f"component release artifact exceeds its byte limit: {locator}"
        )
    return metadata.st_size


def _capture_local_release(
    manifest_path: str | Path,
) -> tuple[ComponentManifest, bytes, dict[str, bytes]]:
    supplied = Path(manifest_path)
    manifest_bytes = _read_stable_release_file(
        supplied,
        maximum_bytes=_MAX_SOURCE_BYTES,
        field="component manifest",
    )
    path = supplied.resolve()
    manifest = ComponentManifest.from_dict(loads_strict(manifest_bytes))
    if len(manifest.artifacts) > _MAX_RELEASE_ARTIFACTS:
        raise InputError("component release artifact count exceeds its limit")
    artifact_paths: dict[str, tuple[Path, int, str]] = {}
    chain_size = len(manifest_bytes)
    for artifact in manifest.artifacts:
        locator = _safe_locator(artifact.locator)
        if locator in artifact_paths:
            raise IntegrityError("component artifact locators must be unique")
        maximum = (
            _MAX_SOURCE_BYTES
            if artifact.role is ArtifactRole.ENGINEERING_BUNDLE
            else _MAX_RELEASE_ARTIFACT_BYTES
        )
        candidate = path.parent / locator
        chain_size += _release_artifact_size(candidate, locator, maximum)
        if chain_size > _MAX_RELEASE_CHAIN_BYTES:
            raise InputError("component release chain exceeds its byte limit")
        artifact_paths[locator] = (candidate, maximum, artifact.digest)
    captured: dict[str, bytes] = {}
    remaining = _MAX_RELEASE_CHAIN_BYTES - len(manifest_bytes)
    for locator, (candidate, maximum, expected_digest) in artifact_paths.items():
        value = _read_stable_release_file(
            candidate,
            maximum_bytes=min(maximum, remaining),
            field=f"component release artifact {locator}",
            expected_digest=expected_digest,
        )
        captured[locator] = value
        remaining -= len(value)
    return manifest, manifest_bytes, captured


def reproduce_local_component_shape(
    manifest_path: str | Path,
) -> tuple[ComponentManifest, Any]:
    """Verify one captured local release and reproduce its authoritative B-rep.

    This is the geometry handoff for deterministic integration engines. It never
    loads the manifest's STEP file as authority: one bounded snapshot of the
    manifest and release chain is verified and its normalized definition is
    compiled again in a private directory.
    """

    manifest, manifest_bytes, artifacts = _capture_local_release(manifest_path)
    with tempfile.TemporaryDirectory(prefix="contrainte-release-replay-") as directory:
        snapshot_root = Path(directory)
        snapshot_path = snapshot_root / "component-manifest.json"
        snapshot_path.write_bytes(manifest_bytes)
        for locator, value in artifacts.items():
            (snapshot_root / locator).write_bytes(value)
        _, document, schema = _verify_local_component_value(snapshot_path, manifest)
        shape = _shape_from_verified_bundle(document, schema)
        if _bounds_from_shape(shape) != manifest.geometry_bounds:
            raise IntegrityError(
                "component geometry bounds do not reproduce from the engineering bundle"
            )
    return manifest, shape


def _verified_bundle_artifacts(
    path: Path,
) -> tuple[Mapping[str, Any], str, tuple[ArtifactRef, ...], str]:
    bundle_bytes = _read_stable_release_file(
        path,
        maximum_bytes=_MAX_SOURCE_BYTES,
        field="engineering bundle",
    )
    document = loads_strict(bundle_bytes)
    if not isinstance(document, dict) or set(document) != {"digest", "content"}:
        raise IntegrityError("engineering bundle envelope is invalid")
    content = document.get("content")
    if not isinstance(content, dict):
        raise IntegrityError("engineering bundle content is invalid")
    schema = content.get("schema_version")
    bundle_artifacts = content.get("artifacts")
    if not isinstance(bundle_artifacts, list):
        raise IntegrityError("engineering bundle artifacts are invalid")
    if len(bundle_artifacts) + 1 > _MAX_RELEASE_ARTIFACTS:
        raise InputError("engineering bundle artifact count exceeds its limit")
    captured_artifacts: dict[str, bytes] = {}
    chain_size = len(bundle_bytes)
    for raw in bundle_artifacts:
        if not isinstance(raw, dict):
            raise IntegrityError("engineering bundle artifact is invalid")
        locator = _safe_locator(raw.get("path"))
        if locator == path.name or locator in captured_artifacts:
            raise IntegrityError("engineering bundle artifact locators must be unique")
        expected_digest = raw.get("digest")
        if not isinstance(expected_digest, str):
            raise IntegrityError("engineering bundle artifact digest is invalid")
        captured = _read_stable_release_file(
            path.parent / locator,
            maximum_bytes=min(
                _MAX_RELEASE_ARTIFACT_BYTES,
                _MAX_RELEASE_CHAIN_BYTES - chain_size,
            ),
            field=f"engineering bundle artifact {locator}",
            expected_digest=expected_digest,
        )
        captured_artifacts[locator] = captured
        chain_size += len(captured)
        if chain_size > _MAX_RELEASE_CHAIN_BYTES:
            raise InputError("engineering bundle release chain exceeds its byte limit")

    with tempfile.TemporaryDirectory(prefix="contrainte-bundle-snapshot-") as directory:
        snapshot_root = Path(directory)
        snapshot_path = snapshot_root / path.name
        snapshot_path.write_bytes(bundle_bytes)
        for locator, captured in captured_artifacts.items():
            (snapshot_root / locator).write_bytes(captured)
        if schema == CAD_BUNDLE_SCHEMA:
            verify_cad_bundle(snapshot_path)
        elif schema in _RELEASABLE_SKETCH_BUNDLE_SCHEMAS:
            verify_sketch_bundle(snapshot_path)
        elif schema == SOLID_BUNDLE_SCHEMA:
            verify_solid_bundle(snapshot_path)
        elif schema == ASSEMBLY_BUNDLE_SCHEMA:
            verify_assembly_bundle(snapshot_path)
        else:
            raise InputError(
                f"unsupported component engineering bundle schema: {schema!r}"
            )

    source_bundle_digest = f"sha256:{hashlib.sha256(bundle_bytes).hexdigest()}"
    artifacts: list[ArtifactRef] = [
        ArtifactRef(
            artifact_id="engineering-bundle",
            role=ArtifactRole.ENGINEERING_BUNDLE,
            media_type="application/json",
            digest=source_bundle_digest,
            locator=path.name,
        )
    ]
    for index, raw in enumerate(bundle_artifacts, start=1):
        if not isinstance(raw, dict):
            raise IntegrityError("engineering bundle artifact is invalid")
        role = _ARTIFACT_ROLES.get(raw.get("role"))
        if role is None:
            raise IntegrityError(
                f"engineering bundle artifact role is not releasable: {raw.get('role')!r}"
            )
        locator = _safe_locator(raw.get("path"))
        artifacts.append(
            ArtifactRef(
                artifact_id=f"{role.value}-{index:02d}",
                role=role,
                media_type=str(raw.get("media_type")),
                digest=str(raw.get("digest")),
                locator=locator,
            )
        )
    return document, str(schema), tuple(artifacts), source_bundle_digest


def _exact_geometry_bounds(
    document: Mapping[str, Any], schema: str
) -> ExactGeometryBounds:
    return _bounds_from_shape(_shape_from_verified_bundle(document, schema))


def _shape_from_verified_bundle(document: Mapping[str, Any], schema: str) -> Any:
    content = document["content"]
    if schema == CAD_BUNDLE_SCHEMA:
        shape = build_part_shape(PrismaticPart.from_dict(content["part"]))
    elif schema in _RELEASABLE_SKETCH_BUNDLE_SCHEMAS:
        shape = build_sketch_shape(SketchExtrusion.from_dict(content["sketch"]))
    elif schema == SOLID_BUNDLE_SCHEMA:
        _, shape = analyze_solid_program(SolidProgram.from_dict(content["program"]))
    elif schema == ASSEMBLY_BUNDLE_SCHEMA:
        _, shape = analyze_assembly(Assembly.from_dict(content["assembly"]))
    else:  # pragma: no cover - guarded by _verified_bundle_artifacts
        raise InputError(f"unsupported component engineering bundle schema: {schema!r}")
    return shape


def _bounds_from_shape(shape: Any) -> ExactGeometryBounds:
    bounds = shape.bounding_box()
    return ExactGeometryBounds.from_dict(
        {
            "frame": "engineering_bundle",
            "unit": "mm",
            "minimum": {
                axis: decimal_text(
                    kernel_measurement(getattr(bounds.min, axis.upper()))
                )
                for axis in ("x", "y", "z")
            },
            "maximum": {
                axis: decimal_text(
                    kernel_measurement(getattr(bounds.max, axis.upper()))
                )
                for axis in ("x", "y", "z")
            },
        },
        field="derived_geometry_bounds",
    )


def _safe_locator(value: Any) -> str:
    if (
        not isinstance(value, str)
        or not value
        or Path(value).is_absolute()
        or Path(value).name != value
        or value in {".", ".."}
    ):
        raise IntegrityError(
            "derived component locator must be one safe local file name"
        )
    return value
