from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from enum import Enum
from typing import Any

from .canonical import digest
from .errors import InputError

COMPONENT_SCHEMA = "contrainte.component-manifest/0.1"
_DIGEST_PATTERN = re.compile(r"^sha256:[0-9a-f]{64}$")


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
class ComponentInterface:
    interface_id: str
    kind: InterfaceKind
    direction: InterfaceDirection
    medium: str
    properties: Mapping[str, str]

    @classmethod
    def from_dict(cls, raw: Any, *, field: str) -> ComponentInterface:
        if not isinstance(raw, dict):
            raise InputError(f"{field} must be an object")
        _reject_unknown_keys(
            raw,
            {"interface_id", "kind", "direction", "medium", "properties"},
            field,
        )
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
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "interface_id": self.interface_id,
            "kind": self.kind.value,
            "direction": self.direction.value,
            "medium": self.medium,
            "properties": dict(self.properties),
        }


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
    metadata: Mapping[str, str]

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
                "metadata",
            },
            field,
        )
        schema_version = _required_string(raw, "schema_version", field)
        if schema_version != COMPONENT_SCHEMA:
            raise InputError(f"unsupported component schema: {schema_version!r}")
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
            metadata=_string_map(raw.get("metadata", {}), f"{field}.metadata"),
        )

    @property
    def manifest_digest(self) -> str:
        return digest(self.as_dict())

    def as_dict(self) -> dict[str, Any]:
        return {
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
