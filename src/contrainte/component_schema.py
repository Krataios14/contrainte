from __future__ import annotations

import copy
from pathlib import Path
from typing import Any

from .canonical import dumps_pretty
from .component import (
    COMPONENT_SCHEMA,
    COMPONENT_SCHEMA_V1,
    COMPONENT_SCHEMA_V3,
    COMPONENT_SCHEMA_V4,
)
from .errors import InputError

JSON_SCHEMA_DIALECT = "https://json-schema.org/draft/2020-12/schema"
SUPPORTED_COMPONENT_MANIFEST_SCHEMA_VERSIONS = (
    COMPONENT_SCHEMA_V1,
    COMPONENT_SCHEMA,
    COMPONENT_SCHEMA_V3,
    COMPONENT_SCHEMA_V4,
)

_DIGEST_PATTERN = r"^sha256:[0-9a-f]{64}$"
_CANONICAL_DECIMAL_PATTERN = r"^-?(?:0|[1-9][0-9]*)(?:\.[0-9]*[1-9])?$"
_CANONICAL_RATIONAL_PATTERN = r"^-?(?:0|[1-9][0-9]*)(?:/[1-9][0-9]*)?$"
_POSITIVE_CANONICAL_DECIMAL_PATTERN = (
    r"^(?:[1-9][0-9]*(?:\.[0-9]*[1-9])?|0\.[0-9]*[1-9])$"
)
_SAFE_FEATURE_ID_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9._-]*$"
_MAX_EXACT_SCALAR_CHARACTERS = 128
_MAX_ATTACHMENT_FEATURE_ID_CHARACTERS = 128
_MAX_COMPONENT_INTERFACES = 64

_ARTIFACT_ROLES = (
    "engineering_bundle",
    "exact_geometry",
    "drawing",
    "mesh",
    "scene",
    "material_record",
    "solver_capsule",
    "test_record",
)
_INTERFACE_KINDS = (
    "mechanical",
    "material",
    "electrical",
    "utility",
    "control",
    "safety",
    "spatial",
)
_INTERFACE_DIRECTIONS = ("input", "output", "bidirectional")
_STOCK_FACE_ROLES = (
    "negative_x",
    "positive_x",
    "negative_y",
    "positive_y",
    "negative_z",
    "positive_z",
)

_COMMON_RUNTIME_INVARIANTS = (
    (
        "component.artifact-identifiers-unique",
        "artifact_id values are unique across artifacts.",
    ),
    (
        "component.source-bundle-linkage",
        (
            "source_bundle_digest identifies exactly one artifact whose role is "
            "engineering_bundle and whose digest is identical."
        ),
    ),
    (
        "component.interface-identifiers-unique",
        "interface_id values are unique across interfaces.",
    ),
)
_GEOMETRY_RUNTIME_INVARIANTS = (
    (
        "component.geometry-finite-positive-extent",
        (
            "Every geometry bound parses as a finite decimal and maximum is strictly "
            "greater than minimum on each axis."
        ),
    ),
)
_FRAME_RUNTIME_INVARIANTS = (
    (
        "component.exact-rationals-reduced",
        "Every rational scalar is reduced and uses its unique canonical spelling.",
    ),
    (
        "component.frame-basis-orthonormal-right-handed",
        (
            "Each interface basis is exactly unit length, mutually orthogonal, and "
            "right-handed."
        ),
    ),
    (
        "component.frame-origin-within-bounds",
        "Each interface frame origin lies within or on geometry_bounds.",
    ),
)
_ATTACHMENT_RUNTIME_INVARIANTS = (
    (
        "component.attachment-direction-unit",
        "Attachment evidence direction is an exact unit vector.",
    ),
    (
        "component.attachment-selector-evidence-correspondence",
        (
            "Attachment evidence surface_type and direction match the selector kind "
            "and canonical role."
        ),
    ),
    (
        "component.attachment-evidence-frame-binding",
        (
            "Attachment evidence characteristic_point_mm equals the interface frame "
            "origin and evidence direction equals the frame z_axis."
        ),
    ),
)


def _closed_object(
    properties: dict[str, Any], *, required: tuple[str, ...] = ()
) -> dict[str, Any]:
    schema: dict[str, Any] = {
        "type": "object",
        "properties": properties,
        "additionalProperties": False,
    }
    if required:
        schema["required"] = list(required)
    return schema


def _non_empty_string() -> dict[str, Any]:
    return {"type": "string", "minLength": 1}


def _string_map() -> dict[str, Any]:
    return {"type": "object", "additionalProperties": {"type": "string"}}


def _digest() -> dict[str, Any]:
    return {"type": "string", "pattern": _DIGEST_PATTERN}


def _canonical_decimal() -> dict[str, Any]:
    return {
        "type": "string",
        "pattern": _CANONICAL_DECIMAL_PATTERN,
        "maxLength": _MAX_EXACT_SCALAR_CHARACTERS,
        "not": {"const": "-0"},
    }


def _canonical_rational() -> dict[str, Any]:
    return {
        "type": "string",
        "pattern": _CANONICAL_RATIONAL_PATTERN,
        "maxLength": _MAX_EXACT_SCALAR_CHARACTERS,
        "not": {"const": "-0"},
    }


def _axis_object(value_schema: dict[str, Any]) -> dict[str, Any]:
    return _closed_object(
        {axis: copy.deepcopy(value_schema) for axis in ("x", "y", "z")},
        required=("x", "y", "z"),
    )


def _geometry_bounds(*, canonical: bool) -> dict[str, Any]:
    scalar = _canonical_decimal() if canonical else {"type": "string"}
    return _closed_object(
        {
            "frame": {"const": "engineering_bundle"},
            "unit": {"const": "mm"},
            "minimum": _axis_object(scalar),
            "maximum": _axis_object(scalar),
        },
        required=("frame", "unit", "minimum", "maximum"),
    )


def _exact_interface_frame() -> dict[str, Any]:
    return _closed_object(
        {
            "reference": {"const": "engineering_bundle"},
            "unit": {"const": "mm"},
            "origin": _axis_object(_canonical_decimal()),
            "basis": _closed_object(
                {
                    axis: _axis_object(_canonical_rational())
                    for axis in ("x_axis", "y_axis", "z_axis")
                },
                required=("x_axis", "y_axis", "z_axis"),
            ),
        },
        required=("reference", "unit", "origin", "basis"),
    )


def _artifact() -> dict[str, Any]:
    return _closed_object(
        {
            "artifact_id": _non_empty_string(),
            "role": {"type": "string", "enum": list(_ARTIFACT_ROLES)},
            "media_type": _non_empty_string(),
            "digest": _digest(),
            "locator": _non_empty_string(),
        },
        required=("artifact_id", "role", "media_type", "digest", "locator"),
    )


def _attachment_selector() -> dict[str, Any]:
    stock_face = _closed_object(
        {
            "kind": {"const": "prismatic_stock_face"},
            "feature_id": {"const": "stock"},
            "role": {"type": "string", "enum": list(_STOCK_FACE_ROLES)},
        },
        required=("kind", "feature_id", "role"),
    )
    through_hole = _closed_object(
        {
            "kind": {"const": "prismatic_through_hole"},
            "feature_id": {
                "type": "string",
                "pattern": _SAFE_FEATURE_ID_PATTERN,
                "maxLength": _MAX_ATTACHMENT_FEATURE_ID_CHARACTERS,
            },
            "role": {"const": "cylindrical_wall"},
        },
        required=("kind", "feature_id", "role"),
    )
    return {"oneOf": [stock_face, through_hole]}


def _attachment_evidence() -> dict[str, Any]:
    schema = _closed_object(
        {
            "source_feature_digest": _digest(),
            "matched_face_count": {"const": 1},
            "surface_type": {"enum": ["plane", "cylinder"]},
            "origin_on_surface": {"const": True},
            "orientation_matches": {"const": True},
            "characteristic_point_mm": _axis_object(_canonical_decimal()),
            "direction": _axis_object(_canonical_rational()),
            "radius_mm": {
                "type": "string",
                "pattern": _POSITIVE_CANONICAL_DECIMAL_PATTERN,
                "maxLength": _MAX_EXACT_SCALAR_CHARACTERS,
            },
        },
        required=(
            "source_feature_digest",
            "matched_face_count",
            "surface_type",
            "origin_on_surface",
            "orientation_matches",
            "characteristic_point_mm",
            "direction",
        ),
    )
    schema["allOf"] = [
        {
            "if": {
                "properties": {"surface_type": {"const": "plane"}},
                "required": ["surface_type"],
            },
            "then": {"not": {"required": ["radius_mm"]}},
            "else": {"required": ["radius_mm"]},
        }
    ]
    return schema


def _attachment() -> dict[str, Any]:
    return _closed_object(
        {
            "selector": {"$ref": "#/$defs/attachment_selector"},
            "evidence": {"$ref": "#/$defs/attachment_evidence"},
        },
        required=("selector", "evidence"),
    )


def _interface(schema_version: str) -> dict[str, Any]:
    properties: dict[str, Any] = {
        "interface_id": _non_empty_string(),
        "kind": {"type": "string", "enum": list(_INTERFACE_KINDS)},
        "direction": {"type": "string", "enum": list(_INTERFACE_DIRECTIONS)},
        "medium": _non_empty_string(),
        "properties": _string_map(),
    }
    required = ["interface_id", "kind", "direction", "medium"]
    if schema_version in {COMPONENT_SCHEMA_V3, COMPONENT_SCHEMA_V4}:
        properties["frame"] = {"$ref": "#/$defs/exact_interface_frame"}
        required.append("frame")
    if schema_version == COMPONENT_SCHEMA_V4:
        properties["attachment"] = {"$ref": "#/$defs/attachment"}
        required.append("attachment")
    return _closed_object(properties, required=tuple(required))


def _runtime_invariants(schema_version: str) -> list[dict[str, str]]:
    invariants = _COMMON_RUNTIME_INVARIANTS
    if schema_version != COMPONENT_SCHEMA_V1:
        invariants += _GEOMETRY_RUNTIME_INVARIANTS
    if schema_version in {COMPONENT_SCHEMA_V3, COMPONENT_SCHEMA_V4}:
        invariants += _FRAME_RUNTIME_INVARIANTS
    if schema_version == COMPONENT_SCHEMA_V4:
        invariants += _ATTACHMENT_RUNTIME_INVARIANTS
    return [
        {"id": invariant_id, "description": description}
        for invariant_id, description in invariants
    ]


def _require_supported_version(schema_version: str) -> None:
    if (
        type(schema_version) is not str
        or schema_version not in SUPPORTED_COMPONENT_MANIFEST_SCHEMA_VERSIONS
    ):
        raise InputError(f"unsupported component manifest schema: {schema_version!r}")


def component_manifest_json_schema(schema_version: str) -> dict[str, Any]:
    """Return a fresh Draft 2020-12 schema for one public manifest version."""

    _require_supported_version(schema_version)
    version = schema_version.rsplit("/", 1)[1]
    definitions: dict[str, Any] = {
        "artifact": _artifact(),
        "interface": _interface(schema_version),
    }
    if schema_version != COMPONENT_SCHEMA_V1:
        definitions["geometry_bounds"] = _geometry_bounds(
            canonical=schema_version in {COMPONENT_SCHEMA_V3, COMPONENT_SCHEMA_V4}
        )
    if schema_version in {COMPONENT_SCHEMA_V3, COMPONENT_SCHEMA_V4}:
        definitions["exact_interface_frame"] = _exact_interface_frame()
    if schema_version == COMPONENT_SCHEMA_V4:
        definitions.update(
            {
                "attachment_selector": _attachment_selector(),
                "attachment_evidence": _attachment_evidence(),
                "attachment": _attachment(),
            }
        )

    properties: dict[str, Any] = {
        "schema_version": {"const": schema_version},
        "component_id": _non_empty_string(),
        "revision": _non_empty_string(),
        "title": _non_empty_string(),
        "lifecycle_state": {
            "type": "string",
            "enum": ["concept", "released", "retired"],
        },
        "qualification": {
            "type": "string",
            "enum": [
                "unqualified_demonstration",
                "engineering_reviewed",
                "qualified_for_intended_use",
            ],
        },
        "source_bundle_digest": _digest(),
        "artifacts": {
            "type": "array",
            "minItems": 1,
            "items": {"$ref": "#/$defs/artifact"},
        },
        "interfaces": {
            "type": "array",
            "items": {"$ref": "#/$defs/interface"},
        },
        "capabilities": {
            "type": "array",
            "items": _non_empty_string(),
            "uniqueItems": True,
        },
        "metadata": _string_map(),
    }
    required = [
        "schema_version",
        "component_id",
        "revision",
        "title",
        "lifecycle_state",
        "qualification",
        "source_bundle_digest",
        "artifacts",
    ]
    if schema_version != COMPONENT_SCHEMA_V1:
        properties["geometry_bounds"] = {"$ref": "#/$defs/geometry_bounds"}
        required.append("geometry_bounds")
    if schema_version == COMPONENT_SCHEMA_V4:
        properties["interfaces"]["maxItems"] = _MAX_COMPONENT_INTERFACES

    schema = _closed_object(properties, required=tuple(required))
    schema.update(
        {
            "$schema": JSON_SCHEMA_DIALECT,
            "$id": f"urn:contrainte:schema:component-manifest:{version}",
            "title": f"Contrainte component manifest {version}",
            "description": (
                "Closed public interchange shape. The runtime-only semantic "
                "invariants annotation identifies checks that require exact "
                "cross-field engineering logic in ComponentManifest.from_dict."
            ),
            "$defs": definitions,
            "x-contrainte-runtime-only-semantic-invariants": _runtime_invariants(
                schema_version
            ),
        }
    )
    return schema


def component_manifest_json_schema_text(schema_version: str) -> str:
    """Return the deterministic UTF-8 JSON representation used by the CLI."""

    return dumps_pretty(component_manifest_json_schema(schema_version))


def export_component_manifest_json_schema(
    schema_version: str, destination: str | Path
) -> Path:
    """Write one deterministic schema document and return its destination path."""

    output = Path(destination)
    content = component_manifest_json_schema_text(schema_version)
    try:
        output.write_text(content, encoding="utf-8", newline="\n")
    except OSError as exc:
        raise InputError(
            f"cannot write component manifest schema {output}: {exc}"
        ) from exc
    return output
