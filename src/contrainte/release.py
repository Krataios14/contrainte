from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
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
from .canonical import decimal_text, dumps_pretty, loads_strict
from .component import (
    COMPONENT_SCHEMA,
    ArtifactRef,
    ArtifactRole,
    ComponentInterface,
    ComponentManifest,
    ExactGeometryBounds,
    LifecycleState,
    Qualification,
)
from .errors import InputError, IntegrityError
from .geometry import kernel_measurement
from .sketch import (
    SKETCH_BUNDLE_SCHEMA,
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
_RESERVED_METADATA = {
    "derivation",
    "engineering_bundle_schema",
    "engineering_bundle_content_digest",
}
_ARTIFACT_ROLES = {
    "exact_geometry": ArtifactRole.EXACT_GEOMETRY,
    "exact_assembly": ArtifactRole.EXACT_GEOMETRY,
    "mesh": ArtifactRole.MESH,
    "visualization_mesh": ArtifactRole.MESH,
    "assembly_mesh": ArtifactRole.MESH,
    "drawing": ArtifactRole.DRAWING,
}


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
            raise InputError(f"{field} contains unsupported fields: {', '.join(unknown)}")
        schema = _string(raw, "schema_version", field)
        if schema != RELEASE_REQUEST_SCHEMA:
            raise InputError(f"unsupported component release request schema: {schema!r}")
        interfaces_raw = raw.get("interfaces", [])
        if not isinstance(interfaces_raw, list):
            raise InputError(f"{field}.interfaces must be a list")
        interfaces = tuple(
            ComponentInterface.from_dict(item, field=f"{field}.interfaces[{index}]")
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
            isinstance(key, str)
            and key
            and isinstance(value, str)
            and value
            for key, value in metadata_raw.items()
        ):
            raise InputError(f"{field}.metadata must map non-empty strings")
        reserved = sorted(set(metadata_raw) & _RESERVED_METADATA)
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
            "interfaces": [item.as_dict() for item in self.interfaces],
            "capabilities": list(self.capabilities),
            "metadata": dict(self.metadata),
        }


def load_release_request(path: str | Path) -> ComponentReleaseRequest:
    source = Path(path)
    try:
        return ComponentReleaseRequest.from_dict(loads_strict(source.read_bytes()))
    except OSError as exc:
        raise InputError(f"cannot read component release request {source}: {exc}") from exc


def derive_component_manifest(
    bundle_path: str | Path, request: ComponentReleaseRequest
) -> ComponentManifest:
    source = Path(bundle_path).resolve()
    document, schema, artifacts = _verified_bundle_artifacts(source)
    geometry_bounds = _exact_geometry_bounds(document, schema)
    metadata = dict(request.metadata)
    metadata.update(
        {
            "derivation": "verified_exact_bundle/0.1",
            "engineering_bundle_schema": schema,
            "engineering_bundle_content_digest": document["digest"],
        }
    )
    return ComponentManifest.from_dict(
        {
            "schema_version": COMPONENT_SCHEMA,
            "component_id": request.component_id,
            "revision": request.revision,
            "title": request.title,
            "lifecycle_state": LifecycleState.CONCEPT.value,
            "qualification": Qualification.UNQUALIFIED_DEMONSTRATION.value,
            "source_bundle_digest": file_digest(source),
            "artifacts": [item.as_dict() for item in artifacts],
            "interfaces": [item.as_dict() for item in request.interfaces],
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
        raise InputError(f"cannot write component manifest {destination}: {exc}") from exc


def verify_local_component_manifest(manifest_path: str | Path) -> dict[str, str]:
    path = Path(manifest_path).resolve()
    try:
        manifest = ComponentManifest.from_dict(loads_strict(path.read_bytes()))
    except OSError as exc:
        raise InputError(f"cannot read component manifest {path}: {exc}") from exc
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
    document, schema, expected_artifacts = _verified_bundle_artifacts(bundle_path)
    if manifest.source_bundle_digest != file_digest(bundle_path):
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
    expected_metadata = {
        "derivation": "verified_exact_bundle/0.1",
        "engineering_bundle_schema": schema,
        "engineering_bundle_content_digest": document["digest"],
    }
    for key, value in expected_metadata.items():
        if manifest.metadata.get(key) != value:
            raise IntegrityError(f"component derivation metadata mismatch: {key}")
    return {
        "status": "verified",
        "component_id": manifest.component_id,
        "manifest_digest": manifest.manifest_digest,
        "source_bundle_digest": manifest.source_bundle_digest,
        "engineering_bundle_content_digest": document["digest"],
    }


def _verified_bundle_artifacts(
    path: Path,
) -> tuple[Mapping[str, Any], str, tuple[ArtifactRef, ...]]:
    if not path.is_file():
        raise InputError(f"engineering bundle is not a file: {path}")
    try:
        document = loads_strict(path.read_bytes())
    except OSError as exc:
        raise InputError(f"cannot read engineering bundle {path}: {exc}") from exc
    if not isinstance(document, dict) or set(document) != {"digest", "content"}:
        raise IntegrityError("engineering bundle envelope is invalid")
    content = document.get("content")
    if not isinstance(content, dict):
        raise IntegrityError("engineering bundle content is invalid")
    schema = content.get("schema_version")
    if schema == CAD_BUNDLE_SCHEMA:
        verify_cad_bundle(path)
    elif schema == SKETCH_BUNDLE_SCHEMA:
        verify_sketch_bundle(path)
    elif schema == SOLID_BUNDLE_SCHEMA:
        verify_solid_bundle(path)
    elif schema == ASSEMBLY_BUNDLE_SCHEMA:
        verify_assembly_bundle(path)
    else:
        raise InputError(f"unsupported component engineering bundle schema: {schema!r}")
    artifacts: list[ArtifactRef] = [
        ArtifactRef(
            artifact_id="engineering-bundle",
            role=ArtifactRole.ENGINEERING_BUNDLE,
            media_type="application/json",
            digest=file_digest(path),
            locator=path.name,
        )
    ]
    bundle_artifacts = content.get("artifacts")
    if not isinstance(bundle_artifacts, list):
        raise IntegrityError("engineering bundle artifacts are invalid")
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
    return document, str(schema), tuple(artifacts)


def _exact_geometry_bounds(
    document: Mapping[str, Any], schema: str
) -> ExactGeometryBounds:
    content = document["content"]
    if schema == CAD_BUNDLE_SCHEMA:
        shape = build_part_shape(PrismaticPart.from_dict(content["part"]))
    elif schema == SKETCH_BUNDLE_SCHEMA:
        shape = build_sketch_shape(SketchExtrusion.from_dict(content["sketch"]))
    elif schema == SOLID_BUNDLE_SCHEMA:
        _, shape = analyze_solid_program(SolidProgram.from_dict(content["program"]))
    elif schema == ASSEMBLY_BUNDLE_SCHEMA:
        _, shape = analyze_assembly(Assembly.from_dict(content["assembly"]))
    else:  # pragma: no cover - guarded by _verified_bundle_artifacts
        raise InputError(f"unsupported component engineering bundle schema: {schema!r}")
    bounds = shape.bounding_box()
    return ExactGeometryBounds.from_dict(
        {
            "frame": "engineering_bundle",
            "unit": "mm",
            "minimum": {
                axis: decimal_text(kernel_measurement(getattr(bounds.min, axis.upper())))
                for axis in ("x", "y", "z")
            },
            "maximum": {
                axis: decimal_text(kernel_measurement(getattr(bounds.max, axis.upper())))
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
        raise IntegrityError("derived component locator must be one safe local file name")
    return value
