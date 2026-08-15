from __future__ import annotations

import hashlib
import os
import stat
import tempfile
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
from .canonical import decimal_text, digest, dumps_pretty, loads_strict
from .component import (
    COMPONENT_SCHEMA,
    COMPONENT_SCHEMA_V3,
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
    SKETCH_BUNDLE_SCHEMA_V2,
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
_LEGACY_RESERVED_METADATA = {
    "derivation",
    "engineering_bundle_schema",
    "engineering_bundle_content_digest",
}
_FRAMED_RESERVED_METADATA = {
    *_LEGACY_RESERVED_METADATA,
    "component_release_request_content_digest",
}
_ARTIFACT_ROLES = {
    "exact_geometry": ArtifactRole.EXACT_GEOMETRY,
    "exact_assembly": ArtifactRole.EXACT_GEOMETRY,
    "mesh": ArtifactRole.MESH,
    "visualization_mesh": ArtifactRole.MESH,
    "assembly_mesh": ArtifactRole.MESH,
    "drawing": ArtifactRole.DRAWING,
}
_MAX_SOURCE_BYTES = 4 * 1024 * 1024
_MAX_RELEASE_ARTIFACT_BYTES = 64 * 1024 * 1024
_MAX_RELEASE_CHAIN_BYTES = 128 * 1024 * 1024
_MAX_RELEASE_ARTIFACTS = 128


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
        }:
            raise InputError(
                f"unsupported component release request schema: {self.schema_version!r}"
            )
        framed = tuple(interface.frame is not None for interface in self.interfaces)
        if self.schema_version == RELEASE_REQUEST_SCHEMA and any(framed):
            raise InputError(
                "component release request schema 0.1 does not support interface frames"
            )
        if self.schema_version == RELEASE_REQUEST_SCHEMA_V2 and not all(framed):
            raise InputError(
                "component release request schema 0.2 requires every interface frame"
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
        if schema not in {RELEASE_REQUEST_SCHEMA, RELEASE_REQUEST_SCHEMA_V2}:
            raise InputError(
                f"unsupported component release request schema: {schema!r}"
            )
        interfaces_raw = raw.get("interfaces", [])
        if not isinstance(interfaces_raw, list):
            raise InputError(f"{field}.interfaces must be a list")
        interfaces = tuple(
            ComponentInterface.from_dict(
                item,
                field=f"{field}.interfaces[{index}]",
                frame_required=schema == RELEASE_REQUEST_SCHEMA_V2,
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
            _FRAMED_RESERVED_METADATA
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
            "interfaces": [item.as_dict() for item in self.interfaces],
            "capabilities": list(self.capabilities),
            "metadata": dict(self.metadata),
        }


def load_release_request(path: str | Path) -> ComponentReleaseRequest:
    source = Path(path)
    try:
        return ComponentReleaseRequest.from_dict(loads_strict(source.read_bytes()))
    except OSError as exc:
        raise InputError(
            f"cannot read component release request {source}: {exc}"
        ) from exc


def derive_component_manifest(
    bundle_path: str | Path, request: ComponentReleaseRequest
) -> ComponentManifest:
    source = Path(bundle_path).resolve()
    document, schema, artifacts = _verified_bundle_artifacts(source)
    geometry_bounds = _exact_geometry_bounds(document, schema)
    metadata = dict(request.metadata)
    framed_release = request.schema_version == RELEASE_REQUEST_SCHEMA_V2
    metadata.update(
        {
            "derivation": (
                "verified_exact_bundle/0.2"
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
            "schema_version": COMPONENT_SCHEMA_V3
            if framed_release
            else COMPONENT_SCHEMA,
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
        "derivation": (
            "verified_exact_bundle/0.2"
            if manifest.schema_version == COMPONENT_SCHEMA_V3
            else "verified_exact_bundle/0.1"
        ),
        "engineering_bundle_schema": schema,
        "engineering_bundle_content_digest": document["digest"],
    }
    if manifest.schema_version == COMPONENT_SCHEMA_V3:
        request_document = {
            "schema_version": RELEASE_REQUEST_SCHEMA_V2,
            "component_id": manifest.component_id,
            "revision": manifest.revision,
            "title": manifest.title,
            "interfaces": [item.as_dict() for item in manifest.interfaces],
            "capabilities": list(manifest.capabilities),
            "metadata": {
                key: value
                for key, value in manifest.metadata.items()
                if key not in _FRAMED_RESERVED_METADATA
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
        _FRAMED_RESERVED_METADATA
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
    elif schema in {SKETCH_BUNDLE_SCHEMA, SKETCH_BUNDLE_SCHEMA_V2}:
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
    return _bounds_from_shape(_shape_from_verified_bundle(document, schema))


def _shape_from_verified_bundle(document: Mapping[str, Any], schema: str) -> Any:
    content = document["content"]
    if schema == CAD_BUNDLE_SCHEMA:
        shape = build_part_shape(PrismaticPart.from_dict(content["part"]))
    elif schema in {SKETCH_BUNDLE_SCHEMA, SKETCH_BUNDLE_SCHEMA_V2}:
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
