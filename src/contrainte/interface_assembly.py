from __future__ import annotations

import itertools
import re
from collections import deque
from dataclasses import dataclass
from decimal import Decimal
from enum import Enum
from fractions import Fraction
from types import MappingProxyType
from typing import Any

from .canonical import digest
from .component import (
    COMPONENT_SCHEMA_V3,
    ArtifactRef,
    ArtifactRole,
    ComponentInterface,
    ComponentManifest,
    ExactGeometryBounds,
    ExactInterfaceFrame,
    InterfaceDirection,
    InterfaceKind,
    LifecycleState,
    Qualification,
)
from .errors import InputError
from .exact_transform import (
    MAX_EXACT_SCALAR_CHARACTERS,
    ExactRigidTransform,
    ExactRotation3,
    ExactVector3,
)
from .reference_component import (
    AllowedOperation,
    ClearanceRequirement,
    ConstraintKind,
    DesignAroundProjection,
    DesignAroundRequest,
    DesignDomain,
    EnvelopePurpose,
    EvidenceAuthority,
    EvidenceGate,
    EvidenceKind,
    EvidenceRecord,
    ExactBox,
    FlexibleDesignBinding,
    FrameRole,
    GateDisposition,
    GateName,
    KnownField,
    MassProperties,
    ProjectedConstraint,
    ReferenceComponentManifest,
    ReferenceFrame,
    SpatialEnvelope,
    UnknownField,
    verify_design_around_projection,
)

INTERFACE_ASSEMBLY_SCHEMA = "contrainte.interface-assembly/0.1"
INTERFACE_ASSEMBLY_RESULT_SCHEMA = "contrainte.interface-assembly-result/0.1"
INTERFACE_ASSEMBLY_SCHEMA_V2 = "contrainte.interface-assembly/0.2"
INTERFACE_ASSEMBLY_RESULT_SCHEMA_V2 = "contrainte.interface-assembly-result/0.2"

MAX_OCCURRENCES = 128
MAX_MATES = 256
MAX_INTERFACES_PER_COMPONENT = 256
MAX_TOTAL_INTERFACES = 4_096
MAX_ARTIFACTS_PER_COMPONENT = 128
MAX_CAPABILITIES_PER_COMPONENT = 256
MAX_COMPONENT_METADATA_FIELDS = 256
MAX_INTERFACE_PROPERTIES = 128
MAX_PROPERTIES_PER_MATE = 128
MAX_ALTERNATIVES_PER_MATE = 64
MAX_TOTAL_ALTERNATIVES = 4_096
MAX_CANDIDATE_BUDGET = 256
MAX_EXACT_MATE_EVALUATIONS = 2_048
MAX_IDENTIFIER_CHARACTERS = 128
MAX_JSON_STRING_CHARACTERS = 4_096
MAX_JSON_NODES = 50_000
MAX_JSON_DEPTH = 32
MAX_JSON_INTEGER_BITS = 64
MAX_PREFERENCE_RANK = 1_000_000_000
_MAPPING_PROXY_TYPE = type(MappingProxyType({}))
_SHA256 = re.compile(r"^sha256:[0-9a-f]{64}$")


class SolveStatus(str, Enum):
    SOLVED = "solved"
    UNSATISFIABLE = "unsatisfiable"
    INCONCLUSIVE = "inconclusive"


class InconclusiveReason(str, Enum):
    CANDIDATE_BUDGET_EXHAUSTED = "candidate_budget_exhausted"
    EXACT_SCALAR_LIMIT = "exact_scalar_limit"
    WORK_BUDGET_EXHAUSTED = "work_budget_exhausted"


class ParticipantKind(str, Enum):
    RELEASED_COMPONENT = "released_component"
    PROTECTED_REFERENCE = "protected_reference"


@dataclass(frozen=True, slots=True)
class InterfaceEndpoint:
    occurrence_id: str
    interface_id: str

    @classmethod
    def from_dict(cls, raw: Any, *, field: str) -> InterfaceEndpoint:
        values = _require_exact_keys(
            raw, required={"occurrence_id", "interface_id"}, field=field
        )
        return cls(
            _identifier(values["occurrence_id"], f"{field}.occurrence_id"),
            _identifier(values["interface_id"], f"{field}.interface_id"),
        )

    def as_dict(self) -> dict[str, str]:
        return {
            "occurrence_id": self.occurrence_id,
            "interface_id": self.interface_id,
        }


@dataclass(frozen=True, slots=True)
class InterfaceOccurrence:
    occurrence_id: str
    component: ComponentManifest
    anchor_transform: ExactRigidTransform | None

    @classmethod
    def from_dict(cls, raw: Any, *, field: str) -> InterfaceOccurrence:
        values = _require_exact_keys(
            raw,
            required={"occurrence_id", "component"},
            optional={"anchor_transform"},
            field=field,
        )
        component_raw = values["component"]
        if (
            type(component_raw) is not dict
            or type(component_raw.get("schema_version")) is not str
            or component_raw["schema_version"] != COMPONENT_SCHEMA_V3
        ):
            raise InputError(
                f"{field}.component must use component schema {COMPONENT_SCHEMA_V3!r}"
            )
        component = ComponentManifest.from_dict(
            component_raw, field=f"{field}.component"
        )
        _enforce_component_caps(component, field=f"{field}.component")
        frozen_component = _freeze_component(component)
        for index, interface in enumerate(frozen_component.interfaces):
            if interface.frame is None:  # pragma: no cover - component v0.3 guard
                raise InputError(
                    f"{field}.component.interfaces[{index}].frame is required"
                )
            _frame_transform(
                interface.frame, field=f"{field}.component.interfaces[{index}].frame"
            )
        anchor = (
            ExactRigidTransform.from_dict(
                values["anchor_transform"], field=f"{field}.anchor_transform"
            )
            if "anchor_transform" in values
            else None
        )
        return cls(
            _identifier(values["occurrence_id"], f"{field}.occurrence_id"),
            frozen_component,
            anchor,
        )

    def as_dict(self) -> dict[str, Any]:
        document: dict[str, Any] = {
            "occurrence_id": self.occurrence_id,
            "component": self.component.as_dict(),
        }
        if self.anchor_transform is not None:
            document["anchor_transform"] = self.anchor_transform.as_dict()
        return document


@dataclass(frozen=True, slots=True)
class ReleasedComponentParticipant:
    """A v0.2 participant backed by a complete released-component snapshot."""

    component: ComponentManifest

    def __init_subclass__(cls, **kwargs: Any) -> None:
        raise TypeError("ReleasedComponentParticipant may not be subclassed")

    def __post_init__(self) -> None:
        if type(self.component) is not ComponentManifest:
            raise InputError(
                "released_component participant requires an exact ComponentManifest"
            )

    @property
    def kind(self) -> ParticipantKind:
        return ParticipantKind.RELEASED_COMPONENT

    @classmethod
    def from_dict(cls, raw: Any, *, field: str) -> ReleasedComponentParticipant:
        values = _require_exact_keys(raw, required={"kind", "component"}, field=field)
        if (
            type(values["kind"]) is not str
            or values["kind"] != ParticipantKind.RELEASED_COMPONENT.value
        ):
            raise InputError(f"{field}.kind must be 'released_component'")
        component_raw = values["component"]
        if (
            type(component_raw) is not dict
            or component_raw.get("schema_version") != COMPONENT_SCHEMA_V3
        ):
            raise InputError(
                f"{field}.component must use component schema {COMPONENT_SCHEMA_V3!r}"
            )
        component = ComponentManifest.from_dict(
            component_raw, field=f"{field}.component"
        )
        _enforce_component_caps(component, field=f"{field}.component")
        frozen = _freeze_component(component)
        for index, interface in enumerate(frozen.interfaces):
            if interface.frame is None:  # pragma: no cover - schema v0.3 guard
                raise InputError(
                    f"{field}.component.interfaces[{index}].frame is required"
                )
            _frame_transform(
                interface.frame, field=f"{field}.component.interfaces[{index}].frame"
            )
        return cls(frozen)

    def as_dict(self) -> dict[str, Any]:
        return {"kind": self.kind.value, "component": self.component.as_dict()}


@dataclass(frozen=True, slots=True)
class ProtectedReferenceParticipant:
    """A protected existing part whose authority remains in its sealed evidence."""

    reference_component: ReferenceComponentManifest
    design_around_request: DesignAroundRequest
    design_around_projection: DesignAroundProjection

    def __init_subclass__(cls, **kwargs: Any) -> None:
        raise TypeError("ProtectedReferenceParticipant may not be subclassed")

    def __post_init__(self) -> None:
        if (
            type(self.reference_component) is not ReferenceComponentManifest
            or type(self.design_around_request) is not DesignAroundRequest
            or type(self.design_around_projection) is not DesignAroundProjection
        ):
            raise InputError(
                "protected_reference participant requires exact sealed public types"
            )
        if not verify_design_around_projection(
            self.reference_component,
            self.design_around_request,
            self.design_around_projection,
        ):
            raise InputError(
                "protected_reference design-around projection does not reproduce"
            )
        if (
            self.design_around_request.required_interface_ids
            and AllowedOperation.ATTACH_AT_DECLARED_INTERFACE
            not in self.reference_component.allowed_operations
        ):
            raise InputError(
                "protected_reference physical interfaces require "
                "attach_at_declared_interface authority"
            )

    @property
    def kind(self) -> ParticipantKind:
        return ParticipantKind.PROTECTED_REFERENCE

    @property
    def evidence_blockers(self) -> tuple[str, ...]:
        return self.design_around_projection.evidence_blockers

    @property
    def interface_authorities(self) -> tuple[tuple[str, EvidenceAuthority], ...]:
        evidence = {
            item.evidence_id: item.authority
            for item in self.reference_component.evidence
        }
        requested = set(self.design_around_request.required_interface_ids)
        return tuple(
            (frame.frame_id, evidence[frame.evidence_id])
            for frame in self.reference_component.reference_frames
            if frame.frame_id in requested
        )

    @classmethod
    def from_dict(cls, raw: Any, *, field: str) -> ProtectedReferenceParticipant:
        values = _require_exact_keys(
            raw,
            required={
                "kind",
                "reference_component",
                "design_around_request",
                "design_around_projection",
            },
            field=field,
        )
        if (
            type(values["kind"]) is not str
            or values["kind"] != ParticipantKind.PROTECTED_REFERENCE.value
        ):
            raise InputError(f"{field}.kind must be 'protected_reference'")
        return cls(
            ReferenceComponentManifest.from_dict(
                values["reference_component"], field=f"{field}.reference_component"
            ),
            DesignAroundRequest.from_dict(
                values["design_around_request"],
                field=f"{field}.design_around_request",
            ),
            DesignAroundProjection.from_dict(
                values["design_around_projection"],
                field=f"{field}.design_around_projection",
            ),
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind.value,
            "reference_component": self.reference_component.as_dict(),
            "design_around_request": self.design_around_request.as_dict(),
            "design_around_projection": self.design_around_projection.as_dict(),
        }


InterfaceParticipant = ReleasedComponentParticipant | ProtectedReferenceParticipant


@dataclass(frozen=True, slots=True)
class InterfaceOccurrenceV2:
    occurrence_id: str
    participant: InterfaceParticipant
    anchor_transform: ExactRigidTransform | None

    def __init_subclass__(cls, **kwargs: Any) -> None:
        raise TypeError("InterfaceOccurrenceV2 may not be subclassed")

    def __post_init__(self) -> None:
        _identifier(self.occurrence_id, "interface_occurrence_v2.occurrence_id")
        if type(self.participant) not in {
            ReleasedComponentParticipant,
            ProtectedReferenceParticipant,
        }:
            raise InputError("interface_occurrence_v2 participant has an invalid type")
        if (
            self.anchor_transform is not None
            and type(self.anchor_transform) is not ExactRigidTransform
        ):
            raise InputError(
                "interface_occurrence_v2.anchor_transform must be exact or null"
            )
        if (
            type(self.participant) is ProtectedReferenceParticipant
            and self.participant.design_around_request.occurrence_id
            != self.occurrence_id
        ):
            raise InputError(
                "protected_reference occurrence must match its design-around request"
            )
        if (
            type(self.participant) is ProtectedReferenceParticipant
            and self.participant.design_around_projection.occurrence_id
            != self.occurrence_id
        ):
            raise InputError(
                "protected_reference occurrence must match its design-around projection"
            )

    @property
    def component(self) -> ComponentManifest:
        """Reject legacy geometry handoff for every version 0.2 occurrence."""

        raise InputError(
            "interface-assembly v0.2 is not accepted by component-assembly v0.1"
        )

    @classmethod
    def from_dict(cls, raw: Any, *, field: str) -> InterfaceOccurrenceV2:
        values = _require_exact_keys(
            raw,
            required={"occurrence_id", "participant"},
            optional={"anchor_transform"},
            field=field,
        )
        participant_raw = values["participant"]
        if (
            type(participant_raw) is not dict
            or type(participant_raw.get("kind")) is not str
        ):
            raise InputError(f"{field}.participant must be a tagged object")
        if participant_raw["kind"] == ParticipantKind.RELEASED_COMPONENT.value:
            participant: InterfaceParticipant = ReleasedComponentParticipant.from_dict(
                participant_raw, field=f"{field}.participant"
            )
        elif participant_raw["kind"] == ParticipantKind.PROTECTED_REFERENCE.value:
            participant = ProtectedReferenceParticipant.from_dict(
                participant_raw, field=f"{field}.participant"
            )
        else:
            raise InputError(f"{field}.participant.kind is unsupported")
        anchor = (
            ExactRigidTransform.from_dict(
                values["anchor_transform"], field=f"{field}.anchor_transform"
            )
            if "anchor_transform" in values
            else None
        )
        return cls(
            _identifier(values["occurrence_id"], f"{field}.occurrence_id"),
            participant,
            anchor,
        )

    def as_dict(self) -> dict[str, Any]:
        document: dict[str, Any] = {
            "occurrence_id": self.occurrence_id,
            "participant": self.participant.as_dict(),
        }
        if self.anchor_transform is not None:
            document["anchor_transform"] = self.anchor_transform.as_dict()
        return document


@dataclass(frozen=True, slots=True)
class MateAlternative:
    alternative_id: str
    preference_rank: int
    second_interface_in_first_interface: ExactRigidTransform

    @classmethod
    def from_dict(cls, raw: Any, *, field: str) -> MateAlternative:
        values = _require_exact_keys(
            raw,
            required={
                "alternative_id",
                "preference_rank",
                "second_interface_in_first_interface",
            },
            field=field,
        )
        rank = values["preference_rank"]
        if type(rank) is not int or not 0 <= rank <= MAX_PREFERENCE_RANK:
            raise InputError(
                f"{field}.preference_rank must be an integer from 0 to "
                f"{MAX_PREFERENCE_RANK}"
            )
        return cls(
            _identifier(values["alternative_id"], f"{field}.alternative_id"),
            rank,
            ExactRigidTransform.from_dict(
                values["second_interface_in_first_interface"],
                field=f"{field}.second_interface_in_first_interface",
            ),
        )

    @property
    def preference_key(self) -> tuple[int, str]:
        return self.preference_rank, self.alternative_id

    def as_dict(self) -> dict[str, Any]:
        return {
            "alternative_id": self.alternative_id,
            "preference_rank": self.preference_rank,
            "second_interface_in_first_interface": (
                self.second_interface_in_first_interface.as_dict()
            ),
        }


@dataclass(frozen=True, slots=True)
class InterfaceMate:
    mate_id: str
    first: InterfaceEndpoint
    second: InterfaceEndpoint
    property_keys: tuple[str, ...]
    alternatives: tuple[MateAlternative, ...]

    @classmethod
    def from_dict(cls, raw: Any, *, field: str) -> InterfaceMate:
        values = _require_exact_keys(
            raw,
            required={
                "mate_id",
                "first",
                "second",
                "property_keys",
                "alternatives",
            },
            field=field,
        )
        property_keys_raw = values["property_keys"]
        if type(property_keys_raw) is not list:
            raise InputError(f"{field}.property_keys must be a list")
        if len(property_keys_raw) > MAX_PROPERTIES_PER_MATE:
            raise InputError(
                f"{field}.property_keys exceeds the {MAX_PROPERTIES_PER_MATE}-item limit"
            )
        property_keys = tuple(
            _identifier(item, f"{field}.property_keys[{index}]")
            for index, item in enumerate(property_keys_raw)
        )
        if property_keys != tuple(sorted(set(property_keys))):
            raise InputError(f"{field}.property_keys must be sorted and unique")

        alternatives_raw = values["alternatives"]
        if type(alternatives_raw) is not list or not alternatives_raw:
            raise InputError(f"{field}.alternatives must be a non-empty list")
        if len(alternatives_raw) > MAX_ALTERNATIVES_PER_MATE:
            raise InputError(
                f"{field}.alternatives exceeds the "
                f"{MAX_ALTERNATIVES_PER_MATE}-item limit"
            )
        alternatives = tuple(
            MateAlternative.from_dict(item, field=f"{field}.alternatives[{index}]")
            for index, item in enumerate(alternatives_raw)
        )
        preference_keys = tuple(item.preference_key for item in alternatives)
        if preference_keys != tuple(sorted(preference_keys)):
            raise InputError(
                f"{field}.alternatives must be sorted by preference_rank and alternative_id"
            )
        alternative_ids = tuple(item.alternative_id for item in alternatives)
        if len(alternative_ids) != len(set(alternative_ids)):
            raise InputError(f"{field}.alternative identifiers must be unique")
        alternative_transforms = tuple(
            item.second_interface_in_first_interface for item in alternatives
        )
        if len(alternative_transforms) != len(set(alternative_transforms)):
            raise InputError(f"{field}.alternative transforms must be unique")

        first = InterfaceEndpoint.from_dict(values["first"], field=f"{field}.first")
        second = InterfaceEndpoint.from_dict(values["second"], field=f"{field}.second")
        if first.occurrence_id == second.occurrence_id:
            raise InputError(f"{field} cannot mate an occurrence to itself")
        return cls(
            _identifier(values["mate_id"], f"{field}.mate_id"),
            first,
            second,
            property_keys,
            alternatives,
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "mate_id": self.mate_id,
            "first": self.first.as_dict(),
            "second": self.second.as_dict(),
            "property_keys": list(self.property_keys),
            "alternatives": [item.as_dict() for item in self.alternatives],
        }


@dataclass(frozen=True, slots=True)
class InterfaceAssembly:
    occurrences: tuple[InterfaceOccurrence | InterfaceOccurrenceV2, ...]
    mates: tuple[InterfaceMate, ...]
    candidate_budget: int
    schema_version: str = INTERFACE_ASSEMBLY_SCHEMA

    @classmethod
    def from_dict(cls, raw: Any) -> InterfaceAssembly:
        _preflight_json(raw)
        if type(raw) is not dict:
            raise InputError("interface_assembly must be an object")
        schema = raw.get("schema_version")
        if type(schema) is not str or schema not in {
            INTERFACE_ASSEMBLY_SCHEMA,
            INTERFACE_ASSEMBLY_SCHEMA_V2,
        }:
            raise InputError(
                "interface_assembly.schema_version must be "
                f"{INTERFACE_ASSEMBLY_SCHEMA!r} or {INTERFACE_ASSEMBLY_SCHEMA_V2!r}"
            )
        values = _require_exact_keys(
            raw,
            required={"schema_version", "occurrences", "mates", "candidate_budget"},
            field="interface_assembly",
        )
        budget = values["candidate_budget"]
        if type(budget) is not int or not 1 <= budget <= MAX_CANDIDATE_BUDGET:
            raise InputError(
                "interface_assembly.candidate_budget must be an integer from 1 to "
                f"{MAX_CANDIDATE_BUDGET}"
            )

        occurrences_raw = values["occurrences"]
        if type(occurrences_raw) is not list or not occurrences_raw:
            raise InputError("interface_assembly.occurrences must be a non-empty list")
        if len(occurrences_raw) > MAX_OCCURRENCES:
            raise InputError(
                "interface_assembly.occurrences exceeds the "
                f"{MAX_OCCURRENCES}-item limit"
            )
        occurrence_type = (
            InterfaceOccurrence
            if schema == INTERFACE_ASSEMBLY_SCHEMA
            else InterfaceOccurrenceV2
        )
        occurrences = tuple(
            occurrence_type.from_dict(
                item, field=f"interface_assembly.occurrences[{index}]"
            )
            for index, item in enumerate(occurrences_raw)
        )
        occurrence_ids = tuple(item.occurrence_id for item in occurrences)
        if len(occurrence_ids) != len(set(occurrence_ids)):
            raise InputError("interface_assembly occurrence identifiers must be unique")
        anchors = tuple(
            item for item in occurrences if item.anchor_transform is not None
        )
        if len(anchors) != 1:
            raise InputError("interface_assembly must contain exactly one anchor")
        total_interfaces = sum(
            _occurrence_interface_count(item) for item in occurrences
        )
        if total_interfaces > MAX_TOTAL_INTERFACES:
            raise InputError(
                "interface_assembly components exceed the "
                f"{MAX_TOTAL_INTERFACES}-interface aggregate limit"
            )

        mates_raw = values["mates"]
        if type(mates_raw) is not list:
            raise InputError("interface_assembly.mates must be a list")
        if len(mates_raw) > MAX_MATES:
            raise InputError(
                f"interface_assembly.mates exceeds the {MAX_MATES}-item limit"
            )
        mates = tuple(
            InterfaceMate.from_dict(item, field=f"interface_assembly.mates[{index}]")
            for index, item in enumerate(mates_raw)
        )
        mate_ids = tuple(item.mate_id for item in mates)
        if len(mate_ids) != len(set(mate_ids)):
            raise InputError("interface_assembly mate identifiers must be unique")
        if sum(len(item.alternatives) for item in mates) > MAX_TOTAL_ALTERNATIVES:
            raise InputError(
                "interface_assembly exceeds the "
                f"{MAX_TOTAL_ALTERNATIVES}-alternative aggregate limit"
            )

        assembly = cls(
            tuple(sorted(occurrences, key=lambda item: item.occurrence_id)),
            tuple(sorted(mates, key=lambda item: item.mate_id)),
            budget,
            schema,
        )
        _validate_mates(assembly)
        _validate_connected(assembly)
        return assembly

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "occurrences": [item.as_dict() for item in self.occurrences],
            "mates": [item.as_dict() for item in self.mates],
            "candidate_budget": self.candidate_budget,
        }


@dataclass(frozen=True, slots=True)
class SolvedOccurrence:
    occurrence_id: str
    transform: ExactRigidTransform

    @classmethod
    def from_dict(cls, raw: Any, *, field: str) -> SolvedOccurrence:
        values = _require_exact_keys(
            raw, required={"occurrence_id", "transform"}, field=field
        )
        return cls(
            _identifier(values["occurrence_id"], f"{field}.occurrence_id"),
            ExactRigidTransform.from_dict(
                values["transform"], field=f"{field}.transform"
            ),
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "occurrence_id": self.occurrence_id,
            "transform": self.transform.as_dict(),
        }


@dataclass(frozen=True, slots=True)
class SelectedMateAlternative:
    mate_id: str
    alternative_id: str
    preference_rank: int

    @classmethod
    def from_dict(cls, raw: Any, *, field: str) -> SelectedMateAlternative:
        values = _require_exact_keys(
            raw,
            required={"mate_id", "alternative_id", "preference_rank"},
            field=field,
        )
        rank = values["preference_rank"]
        if type(rank) is not int or not 0 <= rank <= MAX_PREFERENCE_RANK:
            raise InputError(
                f"{field}.preference_rank must be an integer from 0 to "
                f"{MAX_PREFERENCE_RANK}"
            )
        return cls(
            _identifier(values["mate_id"], f"{field}.mate_id"),
            _identifier(values["alternative_id"], f"{field}.alternative_id"),
            rank,
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "mate_id": self.mate_id,
            "alternative_id": self.alternative_id,
            "preference_rank": self.preference_rank,
        }


@dataclass(frozen=True, slots=True)
class InterfaceEvidenceSummary:
    """Evidence retained for one interface exposed to v0.2 placement."""

    interface_id: str
    authority: EvidenceAuthority | None
    evidence_ids: tuple[str, ...]
    resolution_required: bool

    @classmethod
    def from_dict(cls, raw: Any, *, field: str) -> InterfaceEvidenceSummary:
        values = _require_exact_keys(
            raw,
            required={
                "interface_id",
                "authority",
                "evidence_ids",
                "resolution_required",
            },
            field=field,
        )
        authority_raw = values["authority"]
        authority_by_value = {item.value: item for item in EvidenceAuthority}
        if authority_raw is not None and (
            type(authority_raw) is not str or authority_raw not in authority_by_value
        ):
            raise InputError(f"{field}.authority is unsupported")
        evidence_ids_raw = values["evidence_ids"]
        if (
            type(evidence_ids_raw) is not list
            or len(evidence_ids_raw) > 128
            or any(type(item) is not str for item in evidence_ids_raw)
        ):
            raise InputError(f"{field}.evidence_ids must be a bounded string list")
        if evidence_ids_raw != sorted(set(evidence_ids_raw)):
            raise InputError(f"{field}.evidence_ids must be sorted and unique")
        resolution_required = values["resolution_required"]
        if type(resolution_required) is not bool:
            raise InputError(f"{field}.resolution_required must be boolean")
        return cls(
            _identifier(values["interface_id"], f"{field}.interface_id"),
            authority_by_value[authority_raw] if authority_raw is not None else None,
            tuple(evidence_ids_raw),
            resolution_required,
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "interface_id": self.interface_id,
            "authority": self.authority.value if self.authority is not None else None,
            "evidence_ids": list(self.evidence_ids),
            "resolution_required": self.resolution_required,
        }


@dataclass(frozen=True, slots=True)
class ParticipantEvidenceSummary:
    """Non-release evidence summary bound to one v0.2 participant occurrence."""

    occurrence_id: str
    participant_kind: ParticipantKind
    subject_digest: str
    request_digest: str | None
    projection_digest: str | None
    protected_constraint_count: int
    resolution_required_count: int
    authority_counts: tuple[tuple[str, int], ...]
    exposed_interfaces: tuple[InterfaceEvidenceSummary, ...]
    evidence_blockers: tuple[str, ...]

    @classmethod
    def from_dict(cls, raw: Any, *, field: str) -> ParticipantEvidenceSummary:
        values = _require_exact_keys(
            raw,
            required={
                "occurrence_id",
                "participant_kind",
                "subject_digest",
                "request_digest",
                "projection_digest",
                "protected_constraint_count",
                "resolution_required_count",
                "authority_counts",
                "exposed_interfaces",
                "evidence_blockers",
            },
            field=field,
        )
        kind_raw = values["participant_kind"]
        kind_by_value = {item.value: item for item in ParticipantKind}
        if type(kind_raw) is not str or kind_raw not in kind_by_value:
            raise InputError(f"{field}.participant_kind is unsupported")
        kind = kind_by_value[kind_raw]
        request_digest = values["request_digest"]
        projection_digest = values["projection_digest"]
        if kind is ParticipantKind.RELEASED_COMPONENT:
            if request_digest is not None or projection_digest is not None:
                raise InputError(
                    f"{field} released participants cannot bind projections"
                )
        else:
            request_digest = _sha256(request_digest, f"{field}.request_digest")
            projection_digest = _sha256(projection_digest, f"{field}.projection_digest")
        constraint_count = values["protected_constraint_count"]
        resolution_count = values["resolution_required_count"]
        if (
            type(constraint_count) is not int
            or not 0 <= constraint_count <= 4_096
            or type(resolution_count) is not int
            or not 0 <= resolution_count <= constraint_count
        ):
            raise InputError(f"{field} has invalid constraint counts")
        counts_raw = values["authority_counts"]
        allowed_authorities = {item.value for item in EvidenceAuthority} | {
            "unattributed"
        }
        if (
            type(counts_raw) is not dict
            or len(counts_raw) > len(allowed_authorities)
            or any(
                type(key) is not str
                or key not in allowed_authorities
                or type(value) is not int
                or value < 1
                for key, value in counts_raw.items()
            )
        ):
            raise InputError(f"{field}.authority_counts is invalid")
        authority_counts = tuple(sorted(counts_raw.items()))
        if sum(value for _, value in authority_counts) != constraint_count:
            raise InputError(f"{field}.authority_counts must cover all constraints")
        interfaces_raw = values["exposed_interfaces"]
        blockers_raw = values["evidence_blockers"]
        if type(interfaces_raw) is not list or len(interfaces_raw) > 256:
            raise InputError(f"{field}.exposed_interfaces exceeds collection limits")
        if (
            type(blockers_raw) is not list
            or len(blockers_raw) > 4_096
            or any(type(item) is not str for item in blockers_raw)
        ):
            raise InputError(f"{field}.evidence_blockers must be a bounded string list")
        interfaces = tuple(
            InterfaceEvidenceSummary.from_dict(
                item, field=f"{field}.exposed_interfaces[{index}]"
            )
            for index, item in enumerate(interfaces_raw)
        )
        if tuple(item.interface_id for item in interfaces) != tuple(
            sorted({item.interface_id for item in interfaces})
        ):
            raise InputError(f"{field}.exposed_interfaces must be sorted and unique")
        if blockers_raw != sorted(set(blockers_raw)):
            raise InputError(f"{field}.evidence_blockers must be sorted and unique")
        return cls(
            _identifier(values["occurrence_id"], f"{field}.occurrence_id"),
            kind,
            _sha256(values["subject_digest"], f"{field}.subject_digest"),
            request_digest,
            projection_digest,
            constraint_count,
            resolution_count,
            authority_counts,
            interfaces,
            tuple(blockers_raw),
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "occurrence_id": self.occurrence_id,
            "participant_kind": self.participant_kind.value,
            "subject_digest": self.subject_digest,
            "request_digest": self.request_digest,
            "projection_digest": self.projection_digest,
            "protected_constraint_count": self.protected_constraint_count,
            "resolution_required_count": self.resolution_required_count,
            "authority_counts": dict(self.authority_counts),
            "exposed_interfaces": [item.as_dict() for item in self.exposed_interfaces],
            "evidence_blockers": list(self.evidence_blockers),
        }


@dataclass(frozen=True, slots=True)
class InterfaceAssemblyResult:
    status: SolveStatus
    examined_candidates: int
    candidate_budget: int
    occurrence_transforms: tuple[SolvedOccurrence, ...] = ()
    selected_alternatives: tuple[SelectedMateAlternative, ...] = ()
    inconclusive_reason: InconclusiveReason | None = None
    schema_version: str = INTERFACE_ASSEMBLY_RESULT_SCHEMA
    assembly_digest: str | None = None
    participant_evidence: tuple[ParticipantEvidenceSummary, ...] = ()
    release_eligible: bool | None = None

    @classmethod
    def from_dict(cls, raw: Any) -> InterfaceAssemblyResult:
        _preflight_json(raw)
        if type(raw) is not dict:
            raise InputError("interface_assembly_result must be an object")
        schema = raw.get("schema_version")
        if type(schema) is not str or schema not in {
            INTERFACE_ASSEMBLY_RESULT_SCHEMA,
            INTERFACE_ASSEMBLY_RESULT_SCHEMA_V2,
        }:
            raise InputError(
                "interface_assembly_result.schema_version must be "
                f"{INTERFACE_ASSEMBLY_RESULT_SCHEMA!r} or "
                f"{INTERFACE_ASSEMBLY_RESULT_SCHEMA_V2!r}"
            )
        required = {
            "schema_version",
            "status",
            "examined_candidates",
            "candidate_budget",
            "occurrence_transforms",
            "selected_alternatives",
        }
        if schema == INTERFACE_ASSEMBLY_RESULT_SCHEMA_V2:
            required.update(
                {"assembly_digest", "participant_evidence", "release_eligible"}
            )
        values = _require_exact_keys(
            raw,
            required=required,
            optional={"inconclusive_reason"},
            field="interface_assembly_result",
        )
        status_by_value = {item.value: item for item in SolveStatus}
        status_raw = values["status"]
        if type(status_raw) is not str or status_raw not in status_by_value:
            raise InputError("interface_assembly_result.status is unsupported")
        status = status_by_value[status_raw]
        budget = values["candidate_budget"]
        if type(budget) is not int or not 1 <= budget <= MAX_CANDIDATE_BUDGET:
            raise InputError(
                "interface_assembly_result.candidate_budget must be an integer from "
                f"1 to {MAX_CANDIDATE_BUDGET}"
            )
        examined = values["examined_candidates"]
        if type(examined) is not int or not 0 <= examined <= budget:
            raise InputError(
                "interface_assembly_result.examined_candidates must be an integer "
                "within candidate_budget"
            )
        transforms_raw = values["occurrence_transforms"]
        selections_raw = values["selected_alternatives"]
        if type(transforms_raw) is not list or type(selections_raw) is not list:
            raise InputError(
                "interface_assembly_result transforms and selections must be lists"
            )
        if len(transforms_raw) > MAX_OCCURRENCES or len(selections_raw) > MAX_MATES:
            raise InputError("interface_assembly_result exceeds collection limits")
        participant_evidence: tuple[ParticipantEvidenceSummary, ...] = ()
        release_eligible: bool | None = None
        if schema == INTERFACE_ASSEMBLY_RESULT_SCHEMA_V2:
            evidence_raw = values["participant_evidence"]
            if type(evidence_raw) is not list or len(evidence_raw) > MAX_OCCURRENCES:
                raise InputError(
                    "interface_assembly_result.participant_evidence exceeds limits"
                )
            participant_evidence = tuple(
                ParticipantEvidenceSummary.from_dict(
                    item,
                    field=f"interface_assembly_result.participant_evidence[{index}]",
                )
                for index, item in enumerate(evidence_raw)
            )
            if tuple(item.occurrence_id for item in participant_evidence) != tuple(
                sorted({item.occurrence_id for item in participant_evidence})
            ):
                raise InputError(
                    "interface_assembly_result participant evidence must be sorted and unique"
                )
            if values["release_eligible"] is not False:
                raise InputError(
                    "interface_assembly_result v0.2 is placement evidence, not a release"
                )
            release_eligible = False
        transforms = tuple(
            SolvedOccurrence.from_dict(
                item,
                field=f"interface_assembly_result.occurrence_transforms[{index}]",
            )
            for index, item in enumerate(transforms_raw)
        )
        selections = tuple(
            SelectedMateAlternative.from_dict(
                item,
                field=f"interface_assembly_result.selected_alternatives[{index}]",
            )
            for index, item in enumerate(selections_raw)
        )
        transform_ids = tuple(item.occurrence_id for item in transforms)
        selection_ids = tuple(item.mate_id for item in selections)
        if transform_ids != tuple(sorted(set(transform_ids))):
            raise InputError(
                "interface_assembly_result occurrence transforms must be sorted and unique"
            )
        if selection_ids != tuple(sorted(set(selection_ids))):
            raise InputError(
                "interface_assembly_result selections must be sorted and unique"
            )

        reason = None
        if "inconclusive_reason" in values:
            reason_by_value = {item.value: item for item in InconclusiveReason}
            reason_raw = values["inconclusive_reason"]
            if type(reason_raw) is not str or reason_raw not in reason_by_value:
                raise InputError(
                    "interface_assembly_result.inconclusive_reason is unsupported"
                )
            reason = reason_by_value[reason_raw]
        if status is SolveStatus.SOLVED:
            if examined < 1 or not transforms or reason is not None:
                raise InputError("solved interface assembly result has invalid state")
        elif transforms or selections:
            raise InputError(
                "non-solved interface assembly result cannot contain a solution"
            )
        elif status is SolveStatus.INCONCLUSIVE and reason is None:
            raise InputError("inconclusive interface assembly result requires a reason")
        elif status is SolveStatus.UNSATISFIABLE and reason is not None:
            raise InputError(
                "unsatisfiable interface assembly result cannot have a reason"
            )
        elif status is SolveStatus.UNSATISFIABLE and examined < 1:
            raise InputError(
                "unsatisfiable interface assembly result must examine a candidate"
            )
        if status is SolveStatus.INCONCLUSIVE:
            if reason is InconclusiveReason.CANDIDATE_BUDGET_EXHAUSTED:
                if examined != budget:
                    raise InputError(
                        "candidate budget exhaustion requires examining the full budget"
                    )
            elif examined < 1:
                raise InputError(
                    "arithmetic or work exhaustion must follow an examined candidate"
                )
            elif (
                reason is InconclusiveReason.WORK_BUDGET_EXHAUSTED
                and examined >= budget
            ):
                raise InputError(
                    "work exhaustion must occur before the candidate budget"
                )

        return cls(
            status=status,
            examined_candidates=examined,
            candidate_budget=budget,
            occurrence_transforms=transforms,
            selected_alternatives=selections,
            inconclusive_reason=reason,
            schema_version=schema,
            assembly_digest=(
                _sha256(
                    values["assembly_digest"],
                    "interface_assembly_result.assembly_digest",
                )
                if schema == INTERFACE_ASSEMBLY_RESULT_SCHEMA_V2
                else None
            ),
            participant_evidence=participant_evidence,
            release_eligible=release_eligible,
        )

    def as_dict(self) -> dict[str, Any]:
        document: dict[str, Any] = {
            "schema_version": self.schema_version,
            "status": self.status.value,
            "examined_candidates": self.examined_candidates,
            "candidate_budget": self.candidate_budget,
            "occurrence_transforms": [
                item.as_dict() for item in self.occurrence_transforms
            ],
            "selected_alternatives": [
                item.as_dict() for item in self.selected_alternatives
            ],
        }
        if self.inconclusive_reason is not None:
            document["inconclusive_reason"] = self.inconclusive_reason.value
        if self.schema_version == INTERFACE_ASSEMBLY_RESULT_SCHEMA_V2:
            document["assembly_digest"] = self.assembly_digest
            document["participant_evidence"] = [
                item.as_dict() for item in self.participant_evidence
            ]
            document["release_eligible"] = self.release_eligible
        return document


class _ExactScalarLimit(Exception):
    pass


@dataclass(frozen=True, slots=True)
class _PlacementInterface:
    interface_id: str
    kind: InterfaceKind
    direction: InterfaceDirection
    medium: str
    properties: tuple[tuple[str, str], ...]
    frame: ExactRigidTransform
    authority: EvidenceAuthority | None
    evidence_ids: tuple[str, ...]
    resolution_required: bool


@dataclass(frozen=True, slots=True)
class _PlacementOccurrence:
    occurrence_id: str
    interfaces: tuple[_PlacementInterface, ...]
    anchor_transform: ExactRigidTransform | None
    participant_kind: ParticipantKind
    subject_digest: str
    request_digest: str | None
    projection_digest: str | None
    evidence_blockers: tuple[str, ...]
    protected_constraint_authorities: tuple[EvidenceAuthority | None, ...]
    protected_resolution_required_count: int


def _occurrence_interface_count(
    occurrence: InterfaceOccurrence | InterfaceOccurrenceV2,
) -> int:
    if type(occurrence) is InterfaceOccurrence:
        return len(occurrence.component.interfaces)
    if type(occurrence) is InterfaceOccurrenceV2:
        participant = occurrence.participant
        if type(participant) is ReleasedComponentParticipant:
            return len(participant.component.interfaces)
        if type(participant) is ProtectedReferenceParticipant:
            return len(participant.design_around_request.required_interface_ids)
    raise InputError("interface assembly contains a non-canonical occurrence")


def _normalize_occurrence(
    occurrence: InterfaceOccurrence | InterfaceOccurrenceV2,
) -> _PlacementOccurrence:
    if type(occurrence) is InterfaceOccurrence:
        participant_kind = ParticipantKind.RELEASED_COMPONENT
        component = occurrence.component
        participant: InterfaceParticipant | None = None
    elif type(occurrence) is InterfaceOccurrenceV2:
        participant = occurrence.participant
        participant_kind = participant.kind
        component = (
            participant.component
            if type(participant) is ReleasedComponentParticipant
            else None
        )
    else:  # pragma: no cover - trusted boundary guard
        raise InputError("interface assembly contains a non-canonical occurrence")

    if component is not None:
        interfaces = tuple(
            _PlacementInterface(
                item.interface_id,
                item.kind,
                item.direction,
                item.medium,
                tuple(sorted(item.properties.items())),
                _frame_transform(item.frame, field="interface frame"),  # type: ignore[arg-type]
                None,
                (),
                False,
            )
            for item in component.interfaces
        )
        return _PlacementOccurrence(
            occurrence.occurrence_id,
            interfaces,
            occurrence.anchor_transform,
            participant_kind,
            component.manifest_digest,
            None,
            None,
            (),
            (),
            0,
        )

    if type(participant) is not ProtectedReferenceParticipant:  # pragma: no cover
        raise InputError("protected reference participant is unavailable")
    reference = participant.reference_component
    request = participant.design_around_request
    projection = participant.design_around_projection
    requested = set(request.required_interface_ids)
    evidence = {item.evidence_id: item for item in reference.evidence}
    constraints = {
        item.constraint_id: item for item in projection.protected_constraints
    }
    interfaces = tuple(
        _PlacementInterface(
            frame.frame_id,
            frame.interface_kind,  # type: ignore[arg-type]
            frame.direction,  # type: ignore[arg-type]
            frame.medium,  # type: ignore[arg-type]
            frame.properties,
            frame.transform,
            evidence[frame.evidence_id].authority,
            (frame.evidence_id,),
            constraints[f"frame:{frame.frame_id}"].resolution_required,
        )
        for frame in reference.reference_frames
        if frame.role is FrameRole.INTERFACE and frame.frame_id in requested
    )
    if (
        tuple(item.interface_id for item in interfaces)
        != request.required_interface_ids
    ):
        raise InputError(
            "protected_reference requested interfaces must retain canonical frame order"
        )
    return _PlacementOccurrence(
        occurrence.occurrence_id,
        interfaces,
        occurrence.anchor_transform,
        participant_kind,
        reference.content_digest,
        request.content_digest,
        projection.content_digest,
        projection.evidence_blockers,
        tuple(item.authority for item in projection.protected_constraints),
        sum(item.resolution_required for item in projection.protected_constraints),
    )


def _normalized_occurrences(
    assembly: InterfaceAssembly,
) -> dict[str, _PlacementOccurrence]:
    return {
        item.occurrence_id: _normalize_occurrence(item) for item in assembly.occurrences
    }


def _oracle_occurrences(
    assembly: InterfaceAssembly,
) -> dict[str, _PlacementOccurrence]:
    """Interpret participant placement evidence independently for verification."""

    normalized: dict[str, _PlacementOccurrence] = {}
    for occurrence in assembly.occurrences:
        component: ComponentManifest | None = None
        if type(occurrence) is InterfaceOccurrence:
            component = occurrence.component
        elif (
            type(occurrence) is InterfaceOccurrenceV2
            and type(occurrence.participant) is ReleasedComponentParticipant
        ):
            component = occurrence.participant.component
        if component is not None:
            interfaces = []
            for interface in component.interfaces:
                frame = interface.frame
                if type(frame) is not ExactInterfaceFrame:
                    raise InputError(
                        "oracle requires an exact released interface frame"
                    )
                try:
                    exact_frame = ExactRigidTransform(
                        ExactVector3(
                            *(Fraction(frame.origin[axis]) for axis in ("x", "y", "z"))
                        ),
                        ExactRotation3(
                            ExactVector3(*frame.x_axis),
                            ExactVector3(*frame.y_axis),
                            ExactVector3(*frame.z_axis),
                        ),
                    )
                except InputError as exc:
                    raise InputError(
                        f"oracle cannot represent released interface {interface.interface_id}: {exc}"
                    ) from exc
                interfaces.append(
                    _PlacementInterface(
                        interface.interface_id,
                        InterfaceKind(interface.kind.value),
                        InterfaceDirection(interface.direction.value),
                        str(interface.medium),
                        tuple(
                            sorted(
                                (str(k), str(v))
                                for k, v in interface.properties.items()
                            )
                        ),
                        exact_frame,
                        None,
                        (),
                        False,
                    )
                )
            normalized[occurrence.occurrence_id] = _PlacementOccurrence(
                occurrence.occurrence_id,
                tuple(interfaces),
                occurrence.anchor_transform,
                ParticipantKind.RELEASED_COMPONENT,
                component.manifest_digest,
                None,
                None,
                (),
                (),
                0,
            )
            continue

        if (
            type(occurrence) is not InterfaceOccurrenceV2
            or type(occurrence.participant) is not ProtectedReferenceParticipant
        ):
            raise InputError("oracle encountered a non-canonical participant")
        participant = occurrence.participant
        reference = participant.reference_component
        request = participant.design_around_request
        projection = participant.design_around_projection
        if request.required_interface_ids and (
            AllowedOperation.ATTACH_AT_DECLARED_INTERFACE
            not in reference.allowed_operations
        ):
            raise InputError(
                "oracle refuses physical interfaces without attach_at_declared_interface"
            )
        evidence_records: dict[str, EvidenceRecord] = {}
        for record in reference.evidence:
            if record.evidence_id in evidence_records:
                raise InputError(
                    "oracle found duplicate protected evidence identifiers"
                )
            evidence_records[record.evidence_id] = record
        interfaces = []
        for requested_id in request.required_interface_ids:
            frames = tuple(
                frame
                for frame in reference.reference_frames
                if frame.frame_id == requested_id and frame.role is FrameRole.INTERFACE
            )
            if len(frames) != 1:
                raise InputError(
                    "oracle could not resolve exactly one requested physical interface"
                )
            frame = frames[0]
            constraints = tuple(
                item
                for item in projection.protected_constraints
                if item.kind is ConstraintKind.FRAME
                and item.source_path == f"/reference_frames/{requested_id}"
            )
            if len(constraints) != 1:
                raise InputError(
                    "oracle could not resolve exactly one protected frame constraint"
                )
            constraint = constraints[0]
            record = evidence_records.get(frame.evidence_id)
            if (
                record is None
                or constraint.evidence_ids != (frame.evidence_id,)
                or constraint.authority is not record.authority
                or frame.interface_kind is None
                or frame.direction is None
                or frame.medium is None
            ):
                raise InputError("oracle rejected protected interface evidence binding")
            interfaces.append(
                _PlacementInterface(
                    requested_id,
                    InterfaceKind(frame.interface_kind.value),
                    InterfaceDirection(frame.direction.value),
                    str(frame.medium),
                    tuple((str(key), str(value)) for key, value in frame.properties),
                    ExactRigidTransform.from_dict(
                        frame.transform.as_dict(),
                        field=f"oracle.reference_frames.{requested_id}.transform",
                    ),
                    EvidenceAuthority(record.authority.value),
                    tuple(str(item) for item in constraint.evidence_ids),
                    bool(constraint.resolution_required),
                )
            )
        normalized[occurrence.occurrence_id] = _PlacementOccurrence(
            occurrence.occurrence_id,
            tuple(interfaces),
            occurrence.anchor_transform,
            ParticipantKind.PROTECTED_REFERENCE,
            str(reference.content_digest),
            str(request.content_digest),
            str(projection.content_digest),
            tuple(str(item) for item in projection.evidence_blockers),
            tuple(
                EvidenceAuthority(item.authority.value)
                if item.authority is not None
                else None
                for item in projection.protected_constraints
            ),
            sum(
                1
                for item in projection.protected_constraints
                if item.resolution_required
            ),
        )
    return normalized


def _participant_evidence_summaries(
    occurrences: dict[str, _PlacementOccurrence],
) -> tuple[ParticipantEvidenceSummary, ...]:
    summaries = []
    for occurrence_id in sorted(occurrences):
        occurrence = occurrences[occurrence_id]
        counts: dict[str, int] = {}
        for authority in occurrence.protected_constraint_authorities:
            key = authority.value if authority is not None else "unattributed"
            counts[key] = counts.get(key, 0) + 1
        summaries.append(
            ParticipantEvidenceSummary(
                occurrence_id=occurrence.occurrence_id,
                participant_kind=occurrence.participant_kind,
                subject_digest=occurrence.subject_digest,
                request_digest=occurrence.request_digest,
                projection_digest=occurrence.projection_digest,
                protected_constraint_count=len(
                    occurrence.protected_constraint_authorities
                ),
                resolution_required_count=(
                    occurrence.protected_resolution_required_count
                ),
                authority_counts=tuple(sorted(counts.items())),
                exposed_interfaces=tuple(
                    InterfaceEvidenceSummary(
                        interface_id=item.interface_id,
                        authority=item.authority,
                        evidence_ids=tuple(sorted(item.evidence_ids)),
                        resolution_required=item.resolution_required,
                    )
                    for item in occurrence.interfaces
                ),
                evidence_blockers=occurrence.evidence_blockers,
            )
        )
    return tuple(summaries)


def _result_identity(assembly: InterfaceAssembly) -> dict[str, Any]:
    if assembly.schema_version == INTERFACE_ASSEMBLY_SCHEMA_V2:
        occurrences = _normalized_occurrences(assembly)
        return {
            "schema_version": INTERFACE_ASSEMBLY_RESULT_SCHEMA_V2,
            "assembly_digest": digest(assembly.as_dict()),
            "participant_evidence": _participant_evidence_summaries(occurrences),
            "release_eligible": False,
        }
    return {
        "schema_version": INTERFACE_ASSEMBLY_RESULT_SCHEMA,
        "assembly_digest": None,
        "participant_evidence": (),
        "release_eligible": None,
    }


def _result_identity_matches(
    assembly: InterfaceAssembly, result: InterfaceAssemblyResult
) -> bool:
    if assembly.schema_version == INTERFACE_ASSEMBLY_SCHEMA:
        return (
            result.schema_version == INTERFACE_ASSEMBLY_RESULT_SCHEMA
            and result.assembly_digest is None
        )
    return (
        assembly.schema_version == INTERFACE_ASSEMBLY_SCHEMA_V2
        and result.schema_version == INTERFACE_ASSEMBLY_RESULT_SCHEMA_V2
        and result.assembly_digest == digest(assembly.as_dict())
    )


def _result_evidence_matches(
    assembly: InterfaceAssembly, result: InterfaceAssemblyResult
) -> bool:
    if assembly.schema_version == INTERFACE_ASSEMBLY_SCHEMA:
        return result.participant_evidence == () and result.release_eligible is None
    oracle = _oracle_occurrences(assembly)
    return (
        result.release_eligible is False
        and result.participant_evidence == _participant_evidence_summaries(oracle)
    )


def solve_interface_assembly(assembly: InterfaceAssembly) -> InterfaceAssemblyResult:
    """Search mate alternatives in stable lexicographic preference order."""

    assembly = _trusted_assembly_snapshot(assembly)
    candidate_product = itertools.product(
        *(mate.alternatives for mate in assembly.mates)
    )
    examined = 0
    work = 0
    inconclusive_reason = None
    work_per_candidate = max(1, len(assembly.mates))
    for choices in candidate_product:
        if examined == assembly.candidate_budget:
            inconclusive_reason = InconclusiveReason.CANDIDATE_BUDGET_EXHAUSTED
            break
        if work + work_per_candidate > MAX_EXACT_MATE_EVALUATIONS:
            inconclusive_reason = InconclusiveReason.WORK_BUDGET_EXHAUSTED
            break
        examined += 1
        work += work_per_candidate
        selection = {
            mate.mate_id: alternative
            for mate, alternative in zip(assembly.mates, choices, strict=True)
        }
        try:
            transforms = _propagate_candidate(assembly, selection)
        except _ExactScalarLimit:
            return InterfaceAssemblyResult(
                status=SolveStatus.INCONCLUSIVE,
                examined_candidates=examined,
                candidate_budget=assembly.candidate_budget,
                inconclusive_reason=InconclusiveReason.EXACT_SCALAR_LIMIT,
                **_result_identity(assembly),
            )
        if transforms is None:
            continue
        result = InterfaceAssemblyResult(
            status=SolveStatus.SOLVED,
            examined_candidates=examined,
            candidate_budget=assembly.candidate_budget,
            occurrence_transforms=tuple(
                SolvedOccurrence(occurrence_id, transforms[occurrence_id])
                for occurrence_id in sorted(transforms)
            ),
            selected_alternatives=tuple(
                SelectedMateAlternative(
                    mate.mate_id,
                    selection[mate.mate_id].alternative_id,
                    selection[mate.mate_id].preference_rank,
                )
                for mate in assembly.mates
            ),
            **_result_identity(assembly),
        )
        try:
            verified = verify_interface_assembly_solution(
                assembly, result, _raise_scalar_limit=True
            )
        except _ExactScalarLimit:
            return InterfaceAssemblyResult(
                status=SolveStatus.INCONCLUSIVE,
                examined_candidates=examined,
                candidate_budget=assembly.candidate_budget,
                inconclusive_reason=InconclusiveReason.EXACT_SCALAR_LIMIT,
                **_result_identity(assembly),
            )
        if not verified:
            raise RuntimeError("internal interface assembly reconstruction failed")
        return result

    if inconclusive_reason is not None:
        status = SolveStatus.INCONCLUSIVE
    else:
        status = SolveStatus.UNSATISFIABLE
    return InterfaceAssemblyResult(
        status=status,
        examined_candidates=examined,
        candidate_budget=assembly.candidate_budget,
        inconclusive_reason=inconclusive_reason,
        **_result_identity(assembly),
    )


def verify_interface_assembly_solution(
    assembly: InterfaceAssembly,
    result: InterfaceAssemblyResult,
    *,
    _raise_scalar_limit: bool = False,
) -> bool:
    """Prove the submitted solution is the first feasible exact candidate."""

    if (
        type(assembly) is not InterfaceAssembly
        or type(result) is not InterfaceAssemblyResult
    ):
        raise InputError("solution verification requires exact assembly result types")
    assembly = _trusted_assembly_snapshot(assembly)
    try:
        result = _trusted_result_snapshot(result)
    except InputError:
        return False
    if not _result_identity_matches(assembly, result):
        return False
    if not _result_evidence_matches(assembly, result):
        return False
    if (
        result.status is not SolveStatus.SOLVED
        or result.candidate_budget != assembly.candidate_budget
        or result.examined_candidates > assembly.candidate_budget
    ):
        return False
    occurrence_ids = tuple(item.occurrence_id for item in result.occurrence_transforms)
    expected_occurrence_ids = tuple(item.occurrence_id for item in assembly.occurrences)
    if occurrence_ids != expected_occurrence_ids:
        return False
    mate_ids = tuple(item.mate_id for item in result.selected_alternatives)
    expected_mate_ids = tuple(item.mate_id for item in assembly.mates)
    if mate_ids != expected_mate_ids:
        return False
    transforms = {
        item.occurrence_id: item.transform for item in result.occurrence_transforms
    }
    occurrences = _oracle_occurrences(assembly)
    anchor = next(
        item for item in assembly.occurrences if item.anchor_transform is not None
    )
    if transforms[anchor.occurrence_id] != anchor.anchor_transform:
        return False
    selected_records = {item.mate_id: item for item in result.selected_alternatives}
    selected_ids = tuple(
        selected_records[mate.mate_id].alternative_id for mate in assembly.mates
    )

    # Establish the exact ordinal separately from the submitted world transforms.
    work = 0
    work_per_candidate = max(1, len(assembly.mates))
    try:
        for ordinal, choices in enumerate(
            itertools.product(*(mate.alternatives for mate in assembly.mates)), start=1
        ):
            if ordinal > assembly.candidate_budget:
                return False
            if work + work_per_candidate > MAX_EXACT_MATE_EVALUATIONS:
                return False
            work += work_per_candidate
            selection = {
                mate.mate_id: alternative
                for mate, alternative in zip(assembly.mates, choices, strict=True)
            }
            candidate_transforms = _independent_candidate_transforms(
                assembly, selection
            )
            if candidate_transforms is None:
                if ordinal >= result.examined_candidates:
                    return False
                continue
            if ordinal != result.examined_candidates:
                return False
            if selected_ids != tuple(item.alternative_id for item in choices):
                return False
            for record, alternative in zip(
                result.selected_alternatives, choices, strict=True
            ):
                if record.preference_rank != alternative.preference_rank:
                    return False

            if any(
                _raw_from_exact(transforms[occurrence_id])
                != candidate_transforms[occurrence_id]
                for occurrence_id in transforms
            ):
                return False

            # Verify each mate as the direct homogeneous-frame equation
            # W_first * F_first * A == W_second * F_second. This deliberately
            # avoids the inverse-based propagation expressions used by search.
            for mate, alternative in zip(assembly.mates, choices, strict=True):
                first_frame = _endpoint_frame(occurrences, mate.first)
                second_frame = _endpoint_frame(occurrences, mate.second)
                try:
                    if not _mate_equation_holds(
                        transforms[mate.first.occurrence_id],
                        first_frame,
                        alternative.second_interface_in_first_interface,
                        transforms[mate.second.occurrence_id],
                        second_frame,
                    ):
                        return False
                except _ExactScalarLimit:
                    # The independently propagated raw-Fraction world frames
                    # above remain a complete equation certificate.
                    continue
            return True
    except _ExactScalarLimit:
        if _raise_scalar_limit:
            raise
        return False
    except InputError as exc:
        try:
            _raise_if_scalar_limit(exc)
        except _ExactScalarLimit:
            if _raise_scalar_limit:
                raise
            return False
        raise
    return False


def verify_interface_assembly_result(
    assembly: InterfaceAssembly, result: InterfaceAssemblyResult
) -> bool:
    """Reproduce terminal search evidence for solved and non-solved results."""

    if (
        type(assembly) is not InterfaceAssembly
        or type(result) is not InterfaceAssemblyResult
    ):
        raise InputError("result verification requires exact assembly result types")
    assembly = _trusted_assembly_snapshot(assembly)
    try:
        result = _trusted_result_snapshot(result)
    except InputError:
        return False
    if not _result_identity_matches(assembly, result):
        return False
    if not _result_evidence_matches(assembly, result):
        return False
    if result.candidate_budget != assembly.candidate_budget:
        return False
    if result.status is SolveStatus.SOLVED:
        return verify_interface_assembly_solution(assembly, result)

    examined = 0
    work = 0
    work_per_candidate = max(1, len(assembly.mates))
    for choices in itertools.product(*(mate.alternatives for mate in assembly.mates)):
        if examined == assembly.candidate_budget:
            return _terminal_result_matches(
                result,
                status=SolveStatus.INCONCLUSIVE,
                examined=examined,
                reason=InconclusiveReason.CANDIDATE_BUDGET_EXHAUSTED,
            )
        if work + work_per_candidate > MAX_EXACT_MATE_EVALUATIONS:
            return _terminal_result_matches(
                result,
                status=SolveStatus.INCONCLUSIVE,
                examined=examined,
                reason=InconclusiveReason.WORK_BUDGET_EXHAUSTED,
            )
        examined += 1
        work += work_per_candidate
        selection = {
            mate.mate_id: alternative
            for mate, alternative in zip(assembly.mates, choices, strict=True)
        }
        try:
            transforms = _independent_candidate_transforms(assembly, selection)
        except _ExactScalarLimit:
            return _terminal_result_matches(
                result,
                status=SolveStatus.INCONCLUSIVE,
                examined=examined,
                reason=InconclusiveReason.EXACT_SCALAR_LIMIT,
            )
        if transforms is None:
            continue
        # An independently feasible candidate requires a solved result.
        return False

    return _terminal_result_matches(
        result,
        status=SolveStatus.UNSATISFIABLE,
        examined=examined,
        reason=None,
    )


def _terminal_result_matches(
    result: InterfaceAssemblyResult,
    *,
    status: SolveStatus,
    examined: int,
    reason: InconclusiveReason | None,
) -> bool:
    return (
        result.status is status
        and result.examined_candidates == examined
        and result.inconclusive_reason is reason
        and result.occurrence_transforms == ()
        and result.selected_alternatives == ()
    )


def _mate_equation_holds(
    first_occurrence: ExactRigidTransform,
    first_frame: ExactRigidTransform,
    alternative: ExactRigidTransform,
    second_occurrence: ExactRigidTransform,
    second_frame: ExactRigidTransform,
) -> bool:
    """Check a mate equation in either exact, algebraically symmetric direction."""

    try:
        first_side = first_occurrence.compose(first_frame).compose(alternative)
        second_side = second_occurrence.compose(second_frame)
        return first_side == second_side
    except InputError as exc:
        try:
            _raise_if_scalar_limit(exc)
        except _ExactScalarLimit:
            pass
        else:
            raise

    # Right-multiplying the original equation by A^-1 avoids false arithmetic
    # exhaustion when W_first already contains A^-1. If this orientation also
    # exceeds the scalar bound, the caller preserves the inconclusive state.
    try:
        first_side = first_occurrence.compose(first_frame)
        second_side = second_occurrence.compose(second_frame).compose(
            alternative.inverse()
        )
        return first_side == second_side
    except InputError as exc:
        _raise_if_scalar_limit(exc)
        raise


_RawVector = tuple[Fraction, Fraction, Fraction]
_RawRotation = tuple[_RawVector, _RawVector, _RawVector]
_RawTransform = tuple[_RawRotation, _RawVector]


def _independent_candidate_transforms(
    assembly: InterfaceAssembly, selection: dict[str, MateAlternative]
) -> dict[str, _RawTransform] | None:
    """Solve graph equations with a separate bounded raw-Fraction oracle."""

    occurrences = _oracle_occurrences(assembly)
    anchor = next(
        item for item in assembly.occurrences if item.anchor_transform is not None
    )
    transforms = {
        anchor.occurrence_id: _raw_from_exact(anchor.anchor_transform)  # type: ignore[arg-type]
    }
    adjacency: dict[str, list[tuple[InterfaceMate, bool]]] = {
        occurrence_id: [] for occurrence_id in occurrences
    }
    for mate in assembly.mates:
        adjacency[mate.first.occurrence_id].append((mate, True))
        adjacency[mate.second.occurrence_id].append((mate, False))
    for edges in adjacency.values():
        edges.sort(key=lambda item: item[0].mate_id)

    pending = deque([anchor.occurrence_id])
    processed_mates: set[str] = set()
    while pending:
        current_id = pending.popleft()
        current = transforms[current_id]
        for mate, current_is_first in adjacency[current_id]:
            if mate.mate_id in processed_mates:
                continue
            processed_mates.add(mate.mate_id)
            alternative = _raw_from_exact(
                selection[mate.mate_id].second_interface_in_first_interface
            )
            first_frame = _raw_from_exact(_endpoint_frame(occurrences, mate.first))
            second_frame = _raw_from_exact(_endpoint_frame(occurrences, mate.second))
            if current_is_first:
                neighbour_id = mate.second.occurrence_id
                proposed = _raw_compose(
                    _raw_compose(_raw_compose(current, first_frame), alternative),
                    _raw_inverse(second_frame),
                )
            else:
                neighbour_id = mate.first.occurrence_id
                proposed = _raw_compose(
                    _raw_compose(
                        _raw_compose(current, second_frame),
                        _raw_inverse(alternative),
                    ),
                    _raw_inverse(first_frame),
                )
            existing = transforms.get(neighbour_id)
            if existing is not None:
                if existing != proposed:
                    return None
                continue
            transforms[neighbour_id] = proposed
            pending.append(neighbour_id)
    if len(transforms) != len(occurrences):  # pragma: no cover - connectivity guard
        return None
    return transforms


def _raw_from_exact(transform: ExactRigidTransform) -> _RawTransform:
    rotation = transform.rotation
    rows = (
        (rotation.x_axis.x, rotation.y_axis.x, rotation.z_axis.x),
        (rotation.x_axis.y, rotation.y_axis.y, rotation.z_axis.y),
        (rotation.x_axis.z, rotation.y_axis.z, rotation.z_axis.z),
    )
    translation = (
        transform.translation.x,
        transform.translation.y,
        transform.translation.z,
    )
    return rows, translation


def _raw_compose(left: _RawTransform, right: _RawTransform) -> _RawTransform:
    left_rotation, left_translation = left
    right_rotation, right_translation = right
    right_columns = tuple(zip(*right_rotation, strict=True))
    rotation = tuple(
        tuple(_raw_dot(row, column) for column in right_columns)
        for row in left_rotation
    )
    rotated_translation = tuple(
        _raw_dot(row, right_translation) for row in left_rotation
    )
    translation = tuple(
        _raw_add(value, offset)
        for value, offset in zip(rotated_translation, left_translation, strict=True)
    )
    return rotation, translation  # type: ignore[return-value]


def _raw_inverse(transform: _RawTransform) -> _RawTransform:
    rotation, translation = transform
    inverse_rotation = tuple(zip(*rotation, strict=True))
    inverse_translation = tuple(
        _raw_negate(_raw_dot(row, translation)) for row in inverse_rotation
    )
    return inverse_rotation, inverse_translation  # type: ignore[return-value]


def _raw_dot(left: tuple[Fraction, ...], right: tuple[Fraction, ...]) -> Fraction:
    value = Fraction(0)
    for left_value, right_value in zip(left, right, strict=True):
        value = _raw_add(value, _raw_multiply(left_value, right_value))
    return value


def _raw_multiply(left: Fraction, right: Fraction) -> Fraction:
    return _raw_bounded(left * right)


def _raw_add(left: Fraction, right: Fraction) -> Fraction:
    return _raw_bounded(left + right)


def _raw_negate(value: Fraction) -> Fraction:
    return _raw_bounded(-value)


def _raw_bounded(value: Fraction) -> Fraction:
    text = (
        str(value.numerator)
        if value.denominator == 1
        else f"{value.numerator}/{value.denominator}"
    )
    if len(text) > MAX_EXACT_SCALAR_CHARACTERS:
        raise _ExactScalarLimit
    return value


def _propagate_candidate(
    assembly: InterfaceAssembly, selection: dict[str, MateAlternative]
) -> dict[str, ExactRigidTransform] | None:
    occurrences = _normalized_occurrences(assembly)
    anchor = next(
        item for item in assembly.occurrences if item.anchor_transform is not None
    )
    transforms = {anchor.occurrence_id: anchor.anchor_transform}
    pending = deque([anchor.occurrence_id])
    adjacency: dict[str, list[tuple[InterfaceMate, bool]]] = {
        occurrence_id: [] for occurrence_id in occurrences
    }
    for mate in assembly.mates:
        adjacency[mate.first.occurrence_id].append((mate, True))
        adjacency[mate.second.occurrence_id].append((mate, False))
    for edges in adjacency.values():
        edges.sort(key=lambda item: item[0].mate_id)

    processed_mates: set[str] = set()
    while pending:
        current_id = pending.popleft()
        current = transforms[current_id]
        for mate, current_is_first in adjacency[current_id]:
            if mate.mate_id in processed_mates:
                continue
            processed_mates.add(mate.mate_id)
            alternative = selection[mate.mate_id].second_interface_in_first_interface
            first_frame = _endpoint_frame(occurrences, mate.first)
            second_frame = _endpoint_frame(occurrences, mate.second)
            if current_is_first:
                neighbour_id = mate.second.occurrence_id
                proposed = _compose_second_transform(
                    current, first_frame, alternative, second_frame
                )
            else:
                neighbour_id = mate.first.occurrence_id
                proposed = _compose_first_transform(
                    current, first_frame, alternative, second_frame
                )
            existing = transforms.get(neighbour_id)
            if existing is not None:
                if existing != proposed:
                    return None
                continue
            transforms[neighbour_id] = proposed
            pending.append(neighbour_id)
    if len(transforms) != len(occurrences):  # pragma: no cover - connectivity guard
        return None
    return transforms  # type: ignore[return-value]


def _compose_second_transform(
    first_occurrence: ExactRigidTransform,
    first_frame: ExactRigidTransform,
    alternative: ExactRigidTransform,
    second_frame: ExactRigidTransform,
) -> ExactRigidTransform:
    try:
        return (
            first_occurrence.compose(first_frame)
            .compose(alternative)
            .compose(second_frame.inverse())
        )
    except InputError as exc:
        _raise_if_scalar_limit(exc)
        raise


def _compose_first_transform(
    second_occurrence: ExactRigidTransform,
    first_frame: ExactRigidTransform,
    alternative: ExactRigidTransform,
    second_frame: ExactRigidTransform,
) -> ExactRigidTransform:
    try:
        return (
            second_occurrence.compose(second_frame)
            .compose(alternative.inverse())
            .compose(first_frame.inverse())
        )
    except InputError as exc:
        _raise_if_scalar_limit(exc)
        raise


def _raise_if_scalar_limit(exc: InputError) -> None:
    if "scalar limit" in str(exc):
        raise _ExactScalarLimit from exc


def _frame_transform(frame: ExactInterfaceFrame, *, field: str) -> ExactRigidTransform:
    try:
        translation = ExactVector3(
            *(Fraction(frame.origin[axis]) for axis in ("x", "y", "z"))
        )
        rotation = ExactRotation3(
            *(
                ExactVector3(*getattr(frame, basis_name))
                for basis_name in ("x_axis", "y_axis", "z_axis")
            )
        )
        return ExactRigidTransform(translation, rotation)
    except InputError as exc:
        raise InputError(
            f"{field} cannot be represented as a bounded transform: {exc}"
        ) from exc


def _endpoint_frame(
    occurrences: dict[str, _PlacementOccurrence], endpoint: InterfaceEndpoint
) -> ExactRigidTransform:
    occurrence = occurrences[endpoint.occurrence_id]
    interface = next(
        item
        for item in occurrence.interfaces
        if item.interface_id == endpoint.interface_id
    )
    return interface.frame


def _validate_mates(assembly: InterfaceAssembly) -> None:
    occurrences = _normalized_occurrences(assembly)
    used_endpoints: set[InterfaceEndpoint] = set()
    for mate in assembly.mates:
        first = _resolve_interface(
            occurrences, mate.first, field=f"mate {mate.mate_id}.first"
        )
        second = _resolve_interface(
            occurrences, mate.second, field=f"mate {mate.mate_id}.second"
        )
        for endpoint in (mate.first, mate.second):
            if endpoint in used_endpoints:
                raise InputError(
                    f"interface endpoint {endpoint.occurrence_id}.{endpoint.interface_id} "
                    "is used by more than one mate"
                )
            used_endpoints.add(endpoint)
        if first.kind is not second.kind:
            raise InputError(f"mate {mate.mate_id} interface kinds are incompatible")
        if first.medium != second.medium:
            raise InputError(f"mate {mate.mate_id} interface media are incompatible")
        if not _directions_compatible(first.direction, second.direction):
            raise InputError(
                f"mate {mate.mate_id} interface directions are incompatible"
            )
        first_properties = dict(first.properties)
        second_properties = dict(second.properties)
        for property_key in mate.property_keys:
            if (
                property_key not in first_properties
                or property_key not in second_properties
                or first_properties[property_key] != second_properties[property_key]
            ):
                raise InputError(
                    f"mate {mate.mate_id} selected property {property_key!r} is incompatible"
                )


def _validate_connected(assembly: InterfaceAssembly) -> None:
    occurrence_ids = {item.occurrence_id for item in assembly.occurrences}
    anchor = next(
        item for item in assembly.occurrences if item.anchor_transform is not None
    )
    adjacency = {occurrence_id: set() for occurrence_id in occurrence_ids}
    for mate in assembly.mates:
        adjacency[mate.first.occurrence_id].add(mate.second.occurrence_id)
        adjacency[mate.second.occurrence_id].add(mate.first.occurrence_id)
    visited: set[str] = set()
    pending = [anchor.occurrence_id]
    while pending:
        current = pending.pop()
        if current in visited:
            continue
        visited.add(current)
        pending.extend(sorted(adjacency[current] - visited, reverse=True))
    if visited != occurrence_ids:
        missing = ", ".join(sorted(occurrence_ids - visited))
        raise InputError(f"interface_assembly mate graph is disconnected: {missing}")


def _resolve_interface(
    occurrences: dict[str, _PlacementOccurrence],
    endpoint: InterfaceEndpoint,
    *,
    field: str,
) -> _PlacementInterface:
    occurrence = occurrences.get(endpoint.occurrence_id)
    if occurrence is None:
        raise InputError(
            f"{field} references unknown occurrence {endpoint.occurrence_id!r}"
        )
    matches = tuple(
        item
        for item in occurrence.interfaces
        if item.interface_id == endpoint.interface_id
    )
    if len(matches) != 1:
        raise InputError(
            f"{field} must identify exactly one framed interface, got "
            f"{endpoint.interface_id!r}"
        )
    return matches[0]


def _directions_compatible(
    first: InterfaceDirection, second: InterfaceDirection
) -> bool:
    return (
        first is InterfaceDirection.BIDIRECTIONAL
        or second is InterfaceDirection.BIDIRECTIONAL
        or {first, second} == {InterfaceDirection.INPUT, InterfaceDirection.OUTPUT}
    )


def _freeze_component(component: ComponentManifest) -> ComponentManifest:
    interfaces = tuple(
        ComponentInterface(
            interface.interface_id,
            interface.kind,
            interface.direction,
            interface.medium,
            MappingProxyType(dict(interface.properties)),
            _freeze_frame(interface.frame) if interface.frame is not None else None,
        )
        for interface in component.interfaces
    )
    bounds = component.geometry_bounds
    frozen_bounds = (
        ExactGeometryBounds(
            bounds.frame,
            bounds.unit,
            MappingProxyType(dict(bounds.minimum)),
            MappingProxyType(dict(bounds.maximum)),
        )
        if bounds is not None
        else None
    )
    return ComponentManifest(
        component.schema_version,
        component.component_id,
        component.revision,
        component.title,
        component.lifecycle_state,
        component.qualification,
        component.source_bundle_digest,
        component.artifacts,
        interfaces,
        component.capabilities,
        frozen_bounds,
        MappingProxyType(dict(component.metadata)),
    )


def _freeze_frame(frame: ExactInterfaceFrame) -> ExactInterfaceFrame:
    return ExactInterfaceFrame(
        frame.reference,
        frame.unit,
        MappingProxyType(dict(frame.origin)),
        frame.x_axis,
        frame.y_axis,
        frame.z_axis,
    )


def _enforce_component_caps(component: ComponentManifest, *, field: str) -> None:
    caps = (
        (len(component.artifacts), MAX_ARTIFACTS_PER_COMPONENT, "artifacts"),
        (len(component.interfaces), MAX_INTERFACES_PER_COMPONENT, "interfaces"),
        (len(component.capabilities), MAX_CAPABILITIES_PER_COMPONENT, "capabilities"),
        (len(component.metadata), MAX_COMPONENT_METADATA_FIELDS, "metadata fields"),
    )
    for count, limit, name in caps:
        if count > limit:
            raise InputError(f"{field}.{name} exceeds the {limit}-item limit")
    for index, interface in enumerate(component.interfaces):
        if len(interface.properties) > MAX_INTERFACE_PROPERTIES:
            raise InputError(
                f"{field}.interfaces[{index}].properties exceeds the "
                f"{MAX_INTERFACE_PROPERTIES}-item limit"
            )


def _require_exact_keys(
    raw: Any,
    *,
    required: set[str],
    field: str,
    optional: set[str] | None = None,
) -> dict[str, Any]:
    if type(raw) is not dict:
        raise InputError(f"{field} must be an object")
    if any(type(key) is not str for key in raw):
        raise InputError(f"{field} field names must be strings")
    allowed = required | (optional or set())
    missing = sorted(required - set(raw))
    unknown = sorted(set(raw) - allowed)
    if missing:
        raise InputError(f"{field} is missing required fields: {', '.join(missing)}")
    if unknown:
        raise InputError(f"{field} contains unsupported fields: {', '.join(unknown)}")
    return raw


def _identifier(value: Any, field: str) -> str:
    if type(value) is not str or not value or len(value) > MAX_IDENTIFIER_CHARACTERS:
        raise InputError(
            f"{field} must be a non-empty string of at most "
            f"{MAX_IDENTIFIER_CHARACTERS} characters"
        )
    _utf8_string(value, field)
    return value


def _sha256(value: Any, field: str) -> str:
    if type(value) is not str or not _SHA256.fullmatch(value):
        raise InputError(f"{field} must be a lowercase sha256 digest")
    return value


def _trusted_assembly_snapshot(assembly: InterfaceAssembly) -> InterfaceAssembly:
    """Reparse a public object so direct construction cannot bypass its schema."""

    if type(assembly) is not InterfaceAssembly:
        raise InputError("assembly must be an exact InterfaceAssembly")
    try:
        _precheck_direct_assembly_collections(assembly)
        _validate_direct_assembly_types(assembly)
        document = assembly.as_dict()
        _preflight_json(document)
        canonical = InterfaceAssembly.from_dict(document)
        if document != canonical.as_dict():
            raise InputError("assembly object is not in canonical schema order")
        return canonical
    except InputError:
        raise
    except Exception as exc:
        raise InputError(f"assembly object is malformed: {type(exc).__name__}") from exc


def _trusted_result_snapshot(
    result: InterfaceAssemblyResult,
) -> InterfaceAssemblyResult:
    """Reparse result state before verification or serialization claims."""

    if type(result) is not InterfaceAssemblyResult:
        raise InputError("result must be an exact InterfaceAssemblyResult")
    try:
        _validate_direct_result_types(result)
        document = result.as_dict()
        _preflight_json(document)
        canonical = InterfaceAssemblyResult.from_dict(document)
        if document != canonical.as_dict():
            raise InputError("result object is not in canonical schema order")
        return canonical
    except InputError:
        raise
    except Exception as exc:
        raise InputError(f"result object is malformed: {type(exc).__name__}") from exc


def _precheck_direct_assembly_collections(assembly: InterfaceAssembly) -> None:
    """Reject oversized direct objects before any deep walk or serialization."""

    if (
        type(assembly.occurrences) is not tuple
        or type(assembly.mates) is not tuple
        or not 1 <= len(assembly.occurrences) <= MAX_OCCURRENCES
        or len(assembly.mates) > MAX_MATES
    ):
        raise InputError("assembly object has invalid occurrence or mate collections")
    total_interfaces = 0
    projected_json_nodes = 5  # root plus its four field values
    for occurrence in assembly.occurrences:
        if assembly.schema_version == INTERFACE_ASSEMBLY_SCHEMA:
            if type(occurrence) is not InterfaceOccurrence:
                raise InputError("assembly object contains a non-canonical occurrence")
            component = occurrence.component
            _precheck_component_collections(component)
            interface_count = len(component.interfaces)
            projected_json_nodes += _component_projected_nodes(component)
        elif assembly.schema_version == INTERFACE_ASSEMBLY_SCHEMA_V2:
            if type(occurrence) is not InterfaceOccurrenceV2:
                raise InputError(
                    "assembly object contains a non-canonical v0.2 occurrence"
                )
            participant = occurrence.participant
            if type(participant) is ReleasedComponentParticipant:
                component = participant.component
                _precheck_component_collections(component)
                interface_count = len(component.interfaces)
                projected_json_nodes += 2 + _component_projected_nodes(component)
            elif type(participant) is ProtectedReferenceParticipant:
                interface_count, nodes = _precheck_protected_collections(participant)
                projected_json_nodes += nodes
            else:
                raise InputError("assembly participant has a non-canonical type")
        else:
            raise InputError("assembly object has an unsupported schema version")
        total_interfaces += interface_count
        if total_interfaces > MAX_TOTAL_INTERFACES:
            raise InputError("assembly exceeds the aggregate interface limit")
        projected_json_nodes += 20 if occurrence.anchor_transform is not None else 0
        if projected_json_nodes > MAX_JSON_NODES:
            raise InputError("assembly exceeds the aggregate JSON node limit")

    total_alternatives = 0
    for mate in assembly.mates:
        if (
            type(mate) is not InterfaceMate
            or type(mate.property_keys) is not tuple
            or type(mate.alternatives) is not tuple
            or len(mate.property_keys) > MAX_PROPERTIES_PER_MATE
            or not 1 <= len(mate.alternatives) <= MAX_ALTERNATIVES_PER_MATE
        ):
            raise InputError("assembly mate exceeds direct collection limits")
        total_alternatives += len(mate.alternatives)
        if total_alternatives > MAX_TOTAL_ALTERNATIVES:
            raise InputError("assembly exceeds the aggregate alternative limit")
        projected_json_nodes += (
            10 + len(mate.property_keys) + 23 * len(mate.alternatives)
        )
        if projected_json_nodes > MAX_JSON_NODES:
            raise InputError("assembly exceeds the aggregate JSON node limit")


def _precheck_component_collections(component: Any) -> None:
    if (
        type(component) is not ComponentManifest
        or type(component.artifacts) is not tuple
        or type(component.interfaces) is not tuple
        or type(component.capabilities) is not tuple
        or type(component.metadata) is not _MAPPING_PROXY_TYPE
        or len(component.artifacts) > MAX_ARTIFACTS_PER_COMPONENT
        or len(component.interfaces) > MAX_INTERFACES_PER_COMPONENT
        or len(component.capabilities) > MAX_CAPABILITIES_PER_COMPONENT
        or len(component.metadata) > MAX_COMPONENT_METADATA_FIELDS
    ):
        raise InputError("assembly component exceeds direct collection limits")
    for interface in component.interfaces:
        if (
            type(interface) is not ComponentInterface
            or type(interface.properties) is not _MAPPING_PROXY_TYPE
            or len(interface.properties) > MAX_INTERFACE_PROPERTIES
        ):
            raise InputError("assembly interface exceeds direct collection limits")


def _component_projected_nodes(component: ComponentManifest) -> int:
    return (
        25
        + 6 * len(component.artifacts)
        + len(component.capabilities)
        + len(component.metadata)
        + sum(26 + len(interface.properties) for interface in component.interfaces)
    )


def _precheck_protected_collections(
    participant: ProtectedReferenceParticipant,
) -> tuple[int, int]:
    reference = participant.reference_component
    request = participant.design_around_request
    projection = participant.design_around_projection
    if (
        type(reference) is not ReferenceComponentManifest
        or type(request) is not DesignAroundRequest
        or type(projection) is not DesignAroundProjection
    ):
        raise InputError("protected reference contains non-canonical public types")
    collections = (
        (reference.evidence, 128, "reference evidence"),
        (reference.reference_frames, 256, "reference frames"),
        (reference.envelopes, 256, "reference envelopes"),
        (reference.allowed_operations, len(AllowedOperation), "allowed operations"),
        (reference.known_fields, 512, "reference known fields"),
        (reference.unknown_fields, 512, "reference unknown fields"),
        (reference.evidence_gates, 5, "reference evidence gates"),
        (request.flexible_domains, 32, "reference flexible domains"),
        (request.required_interface_ids, 256, "reference required interfaces"),
        (request.clearances, 256, "reference clearances"),
        (projection.protected_constraints, 4_096, "projected constraints"),
        (projection.flexible_bindings, 32, "projected flexible bindings"),
        (projection.evidence_blockers, 4_096, "projected evidence blockers"),
    )
    for value, maximum, label in collections:
        if type(value) is not tuple or len(value) > maximum:
            raise InputError(f"{label} exceeds direct collection limits")
    exact_items = (
        (reference.evidence, EvidenceRecord, "reference evidence"),
        (reference.reference_frames, ReferenceFrame, "reference frames"),
        (reference.envelopes, SpatialEnvelope, "reference envelopes"),
        (reference.known_fields, KnownField, "reference known fields"),
        (reference.unknown_fields, UnknownField, "reference unknown fields"),
        (reference.evidence_gates, EvidenceGate, "reference evidence gates"),
        (request.clearances, ClearanceRequirement, "reference clearances"),
        (
            projection.protected_constraints,
            ProjectedConstraint,
            "projected constraints",
        ),
        (
            projection.flexible_bindings,
            FlexibleDesignBinding,
            "projected flexible bindings",
        ),
    )
    for value, expected, label in exact_items:
        if any(type(item) is not expected for item in value):
            raise InputError(f"{label} contains non-canonical values")
    nested_collections = (
        *((item.supports, 512, "evidence supports") for item in reference.evidence),
        *(
            (item.properties, MAX_INTERFACE_PROPERTIES, "reference frame properties")
            for item in reference.reference_frames
        ),
        *(
            (item.evidence_ids, 128, "evidence gate identifiers")
            for item in reference.evidence_gates
        ),
        *(
            (item.evidence_ids, 128, "constraint evidence identifiers")
            for item in projection.protected_constraints
        ),
        *(
            (item.interface_ids, 256, "flexible binding interfaces")
            for item in projection.flexible_bindings
        ),
    )
    for value, maximum, label in nested_collections:
        if type(value) is not tuple or len(value) > maximum:
            raise InputError(f"{label} exceeds direct nested collection limits")
    if (
        reference.mass_properties is not None
        and type(reference.mass_properties) is not MassProperties
    ):
        raise InputError("reference mass properties have a non-canonical type")
    if any(type(item) is not str for item in request.required_interface_ids):
        raise InputError("reference required interfaces must contain exact strings")
    if any(type(item) is not DesignDomain for item in request.flexible_domains):
        raise InputError("reference flexible domains contain non-canonical values")
    if any(type(item) is not AllowedOperation for item in reference.allowed_operations):
        raise InputError("reference allowed operations contain non-canonical values")
    if any(type(item) is not str for item in projection.evidence_blockers):
        raise InputError("projected evidence blockers must contain exact strings")
    interface_count = len(request.required_interface_ids)
    projected_nodes = (
        160
        + sum(len(value) for value, _, _ in collections) * 8
        + sum(len(value) for value, _, _ in nested_collections) * 2
    )
    if projected_nodes > MAX_JSON_NODES:
        raise InputError("protected reference exceeds the aggregate JSON node limit")
    return interface_count, projected_nodes


def _validate_direct_assembly_types(assembly: InterfaceAssembly) -> None:
    if (
        type(assembly.occurrences) is not tuple
        or type(assembly.mates) is not tuple
        or type(assembly.candidate_budget) is not int
        or type(assembly.schema_version) is not str
    ):
        raise InputError("assembly object contains non-canonical field types")
    for occurrence in assembly.occurrences:
        if type(occurrence.occurrence_id) is not str or (
            occurrence.anchor_transform is not None
            and type(occurrence.anchor_transform) is not ExactRigidTransform
        ):
            raise InputError("assembly occurrence contains non-canonical field types")
        if assembly.schema_version == INTERFACE_ASSEMBLY_SCHEMA:
            if type(occurrence) is not InterfaceOccurrence:
                raise InputError(
                    "assembly v0.1 occurrence contains non-canonical field types"
                )
            component = occurrence.component
        elif assembly.schema_version == INTERFACE_ASSEMBLY_SCHEMA_V2:
            if type(occurrence) is not InterfaceOccurrenceV2:
                raise InputError(
                    "assembly v0.2 occurrence contains non-canonical field types"
                )
            if type(occurrence.participant) is ReleasedComponentParticipant:
                component = occurrence.participant.component
            elif type(occurrence.participant) is ProtectedReferenceParticipant:
                _validate_protected_direct_types(occurrence.participant)
                continue
            else:
                raise InputError("assembly participant has a non-canonical type")
        else:
            raise InputError("assembly object has an unsupported schema version")
        if (
            type(component.schema_version) is not str
            or type(component.component_id) is not str
            or type(component.revision) is not str
            or type(component.title) is not str
            or type(component.lifecycle_state) is not LifecycleState
            or type(component.qualification) is not Qualification
            or type(component.source_bundle_digest) is not str
            or type(component.artifacts) is not tuple
            or type(component.interfaces) is not tuple
            or type(component.capabilities) is not tuple
            or type(component.metadata) is not _MAPPING_PROXY_TYPE
            or any(type(item) is not ArtifactRef for item in component.artifacts)
            or any(type(item) is not str for item in component.capabilities)
            or (
                component.geometry_bounds is not None
                and type(component.geometry_bounds) is not ExactGeometryBounds
            )
        ):
            raise InputError("assembly component contains non-canonical field types")
        for artifact in component.artifacts:
            if (
                type(artifact.artifact_id) is not str
                or type(artifact.role) is not ArtifactRole
                or type(artifact.media_type) is not str
                or type(artifact.digest) is not str
                or type(artifact.locator) is not str
            ):
                raise InputError("assembly artifact contains non-canonical field types")
        if any(
            type(key) is not str or type(value) is not str
            for key, value in component.metadata.items()
        ):
            raise InputError("assembly component metadata must contain exact strings")
        if component.geometry_bounds is not None and (
            type(component.geometry_bounds.frame) is not str
            or type(component.geometry_bounds.unit) is not str
            or not _is_exact_xyz_mapping(
                component.geometry_bounds.minimum, value_type=Decimal
            )
            or not _is_exact_xyz_mapping(
                component.geometry_bounds.maximum, value_type=Decimal
            )
        ):
            raise InputError("assembly component bounds must be immutable")
        for interface in component.interfaces:
            if (
                type(interface) is not ComponentInterface
                or type(interface.interface_id) is not str
                or type(interface.kind) is not InterfaceKind
                or type(interface.direction) is not InterfaceDirection
                or type(interface.medium) is not str
                or type(interface.properties) is not _MAPPING_PROXY_TYPE
                or type(interface.frame) is not ExactInterfaceFrame
                or not _is_exact_xyz_mapping(interface.frame.origin, value_type=Decimal)
                or type(interface.frame.x_axis) is not tuple
                or type(interface.frame.y_axis) is not tuple
                or type(interface.frame.z_axis) is not tuple
                or type(interface.frame.reference) is not str
                or type(interface.frame.unit) is not str
                or any(
                    type(value) is not Fraction
                    for axis in (
                        interface.frame.x_axis,
                        interface.frame.y_axis,
                        interface.frame.z_axis,
                    )
                    for value in axis
                )
                or any(
                    type(key) is not str or type(value) is not str
                    for key, value in interface.properties.items()
                )
            ):
                raise InputError(
                    "assembly interface contains non-canonical field types"
                )
    for mate in assembly.mates:
        if (
            type(mate) is not InterfaceMate
            or type(mate.first) is not InterfaceEndpoint
            or type(mate.second) is not InterfaceEndpoint
            or type(mate.property_keys) is not tuple
            or type(mate.alternatives) is not tuple
            or any(type(key) is not str for key in mate.property_keys)
        ):
            raise InputError("assembly mate contains non-canonical field types")
        for endpoint in (mate.first, mate.second):
            if (
                type(endpoint.occurrence_id) is not str
                or type(endpoint.interface_id) is not str
            ):
                raise InputError("assembly endpoint contains non-canonical field types")
        for alternative in mate.alternatives:
            if (
                type(alternative) is not MateAlternative
                or type(alternative.alternative_id) is not str
                or type(alternative.preference_rank) is not int
                or type(alternative.second_interface_in_first_interface)
                is not ExactRigidTransform
            ):
                raise InputError(
                    "assembly alternative contains non-canonical field types"
                )


def _validate_protected_direct_types(
    participant: ProtectedReferenceParticipant,
) -> None:
    _precheck_protected_collections(participant)
    reference = participant.reference_component
    request = participant.design_around_request
    projection = participant.design_around_projection
    scalar_values = (
        reference.schema_version,
        reference.component_id,
        reference.manufacturer,
        reference.part_number,
        reference.revision,
        reference.title,
        reference.source_model_digest,
        reference.unit,
        reference.occupied_bounds_evidence_id,
        reference.content_digest,
        request.schema_version,
        request.request_id,
        request.reference_component_digest,
        request.occurrence_id,
        request.content_digest,
        projection.schema_version,
        projection.request_digest,
        projection.reference_component_digest,
        projection.occurrence_id,
        projection.content_digest,
    )
    if any(type(value) is not str for value in scalar_values):
        raise InputError("protected reference contains non-canonical scalar types")
    if not _is_direct_exact_box(reference.occupied_bounds):
        raise InputError("protected occupied bounds contain non-canonical exact values")
    strings = list(scalar_values)
    strings.append(reference.occupied_bounds.unit)
    for record in reference.evidence:
        if (
            type(record.evidence_id) is not str
            or type(record.kind) is not EvidenceKind
            or type(record.artifact_digest) is not str
            or type(record.authority) is not EvidenceAuthority
            or type(record.locator) is not str
            or not _is_exact_string_tuple(record.supports)
        ):
            raise InputError("protected evidence contains non-canonical nested values")
        strings.extend(
            (
                record.evidence_id,
                record.artifact_digest,
                record.locator,
                *record.supports,
            )
        )
    for frame in reference.reference_frames:
        if (
            type(frame.frame_id) is not str
            or type(frame.role) is not FrameRole
            or not _is_direct_exact_transform(frame.transform)
            or type(frame.evidence_id) is not str
            or (
                frame.interface_kind is not None
                and type(frame.interface_kind) is not InterfaceKind
            )
            or (
                frame.direction is not None
                and type(frame.direction) is not InterfaceDirection
            )
            or (frame.medium is not None and type(frame.medium) is not str)
            or type(frame.properties) is not tuple
            or any(
                type(item) is not tuple
                or len(item) != 2
                or type(item[0]) is not str
                or type(item[1]) is not str
                for item in frame.properties
            )
        ):
            raise InputError(
                "protected reference frame contains non-canonical nested values"
            )
        strings.extend((frame.frame_id, frame.evidence_id, frame.transform.unit))
        if frame.medium is not None:
            strings.append(frame.medium)
        strings.extend(value for pair in frame.properties for value in pair)
    for envelope in reference.envelopes:
        if (
            type(envelope.envelope_id) is not str
            or type(envelope.purpose) is not EnvelopePurpose
            or not _is_direct_exact_box(envelope.bounds)
            or type(envelope.evidence_id) is not str
        ):
            raise InputError("protected envelope contains non-canonical nested values")
        strings.extend(
            (envelope.envelope_id, envelope.bounds.unit, envelope.evidence_id)
        )
    if reference.mass_properties is not None:
        mass = reference.mass_properties
        if (
            not _is_bounded_fraction(mass.mass_kg)
            or not _is_direct_exact_vector(mass.center_of_mass)
            or type(mass.inertia_kg_mm2) is not tuple
            or len(mass.inertia_kg_mm2) != 6
            or any(not _is_bounded_fraction(item) for item in mass.inertia_kg_mm2)
            or type(mass.evidence_id) is not str
        ):
            raise InputError(
                "protected mass properties contain non-canonical nested values"
            )
        strings.append(mass.evidence_id)
    for item in reference.known_fields:
        if type(item.field_path) is not str or type(item.evidence_id) is not str:
            raise InputError("protected known field contains non-canonical values")
        strings.extend((item.field_path, item.evidence_id))
    for item in reference.unknown_fields:
        if any(
            type(value) is not str
            for value in (item.field_path, item.consequence, item.required_evidence)
        ):
            raise InputError("protected unknown field contains non-canonical values")
        strings.extend((item.field_path, item.consequence, item.required_evidence))
    for gate in reference.evidence_gates:
        if (
            type(gate.name) is not GateName
            or type(gate.disposition) is not GateDisposition
            or not _is_exact_string_tuple(gate.evidence_ids)
            or type(gate.rationale) is not str
        ):
            raise InputError("protected evidence gate contains non-canonical values")
        strings.extend((*gate.evidence_ids, gate.rationale))
    for clearance in request.clearances:
        if type(clearance.envelope_id) is not str or not _is_bounded_fraction(
            clearance.clearance_mm
        ):
            raise InputError("protected clearance contains non-canonical values")
        strings.append(clearance.envelope_id)
    strings.extend(request.required_interface_ids)
    for constraint in projection.protected_constraints:
        if (
            type(constraint.constraint_id) is not str
            or type(constraint.kind) is not ConstraintKind
            or type(constraint.source_path) is not str
            or type(constraint.value_digest) is not str
            or not _is_exact_string_tuple(constraint.evidence_ids)
            or (
                constraint.authority is not None
                and type(constraint.authority) is not EvidenceAuthority
            )
            or type(constraint.resolution_required) is not bool
        ):
            raise InputError(
                "protected constraint contains non-canonical nested values"
            )
        strings.extend(
            (
                constraint.constraint_id,
                constraint.source_path,
                constraint.value_digest,
                *constraint.evidence_ids,
            )
        )
    for binding in projection.flexible_bindings:
        if type(binding.domain) is not DesignDomain or not _is_exact_string_tuple(
            binding.interface_ids
        ):
            raise InputError(
                "protected flexible binding contains non-canonical nested values"
            )
        strings.extend(binding.interface_ids)
    strings.extend(projection.evidence_blockers)
    for index, value in enumerate(strings):
        _utf8_string(value, f"protected_reference string[{index}]")
    if (
        request.required_interface_ids
        and AllowedOperation.ATTACH_AT_DECLARED_INTERFACE
        not in reference.allowed_operations
    ):
        raise InputError(
            "protected_reference physical interfaces require "
            "attach_at_declared_interface authority"
        )


def _is_exact_string_tuple(value: Any) -> bool:
    return type(value) is tuple and all(type(item) is str for item in value)


def _is_bounded_fraction(value: Any) -> bool:
    return (
        type(value) is Fraction
        and abs(value.numerator).bit_length() <= MAX_EXACT_SCALAR_CHARACTERS * 4
        and value.denominator.bit_length() <= MAX_EXACT_SCALAR_CHARACTERS * 4
    )


def _is_direct_exact_vector(value: Any) -> bool:
    return type(value) is ExactVector3 and all(
        _is_bounded_fraction(item) for item in (value.x, value.y, value.z)
    )


def _is_direct_exact_transform(value: Any) -> bool:
    return (
        type(value) is ExactRigidTransform
        and _is_direct_exact_vector(value.translation)
        and type(value.rotation) is ExactRotation3
        and _is_direct_exact_vector(value.rotation.x_axis)
        and _is_direct_exact_vector(value.rotation.y_axis)
        and _is_direct_exact_vector(value.rotation.z_axis)
        and type(value.unit) is str
    )


def _is_direct_exact_box(value: Any) -> bool:
    return (
        type(value) is ExactBox
        and _is_direct_exact_vector(value.minimum)
        and _is_direct_exact_vector(value.maximum)
        and type(value.unit) is str
    )


def _is_exact_xyz_mapping(value: Any, *, value_type: type[Any]) -> bool:
    if type(value) is not _MAPPING_PROXY_TYPE:
        return False
    keys = tuple(value.keys())
    if len(keys) != 3 or any(type(key) is not str for key in keys):
        return False
    if set(keys) != {"x", "y", "z"}:
        return False
    return all(type(item) is value_type for item in value.values())


def _validate_direct_result_types(result: InterfaceAssemblyResult) -> None:
    if (
        type(result.status) is not SolveStatus
        or type(result.examined_candidates) is not int
        or type(result.candidate_budget) is not int
        or type(result.occurrence_transforms) is not tuple
        or type(result.selected_alternatives) is not tuple
        or (
            result.inconclusive_reason is not None
            and type(result.inconclusive_reason) is not InconclusiveReason
        )
        or type(result.schema_version) is not str
        or (
            result.assembly_digest is not None
            and type(result.assembly_digest) is not str
        )
        or type(result.participant_evidence) is not tuple
        or (
            result.release_eligible is not None
            and type(result.release_eligible) is not bool
        )
    ):
        raise InputError("result object contains non-canonical field types")
    if result.schema_version == INTERFACE_ASSEMBLY_RESULT_SCHEMA:
        if (
            result.assembly_digest is not None
            or result.participant_evidence
            or result.release_eligible is not None
        ):
            raise InputError("v0.1 result cannot contain v0.2 evidence fields")
    elif result.schema_version == INTERFACE_ASSEMBLY_RESULT_SCHEMA_V2:
        _sha256(result.assembly_digest, "interface_assembly_result.assembly_digest")
        if result.release_eligible is not False:
            raise InputError("v0.2 result is placement evidence, not a release")
    else:
        raise InputError("result object has an unsupported schema version")
    if (
        len(result.occurrence_transforms) > MAX_OCCURRENCES
        or len(result.selected_alternatives) > MAX_MATES
        or len(result.participant_evidence) > MAX_OCCURRENCES
    ):
        raise InputError("result object exceeds direct collection limits")
    if any(
        type(item) is not SolvedOccurrence
        or type(item.occurrence_id) is not str
        or type(item.transform) is not ExactRigidTransform
        for item in result.occurrence_transforms
    ):
        raise InputError("result transform contains non-canonical field types")
    if any(
        type(item) is not SelectedMateAlternative
        or type(item.mate_id) is not str
        or type(item.alternative_id) is not str
        or type(item.preference_rank) is not int
        for item in result.selected_alternatives
    ):
        raise InputError("result selection contains non-canonical field types")
    for summary in result.participant_evidence:
        if (
            type(summary) is not ParticipantEvidenceSummary
            or type(summary.occurrence_id) is not str
            or type(summary.participant_kind) is not ParticipantKind
            or type(summary.subject_digest) is not str
            or (
                summary.request_digest is not None
                and type(summary.request_digest) is not str
            )
            or (
                summary.projection_digest is not None
                and type(summary.projection_digest) is not str
            )
            or type(summary.protected_constraint_count) is not int
            or type(summary.resolution_required_count) is not int
            or type(summary.authority_counts) is not tuple
            or len(summary.authority_counts) > len(EvidenceAuthority) + 1
            or any(
                type(item) is not tuple
                or len(item) != 2
                or type(item[0]) is not str
                or type(item[1]) is not int
                for item in summary.authority_counts
            )
            or type(summary.exposed_interfaces) is not tuple
            or len(summary.exposed_interfaces) > 256
            or type(summary.evidence_blockers) is not tuple
            or len(summary.evidence_blockers) > 4_096
            or any(type(item) is not str for item in summary.evidence_blockers)
        ):
            raise InputError("result evidence summary has non-canonical field types")
        for interface in summary.exposed_interfaces:
            if (
                type(interface) is not InterfaceEvidenceSummary
                or type(interface.interface_id) is not str
                or (
                    interface.authority is not None
                    and type(interface.authority) is not EvidenceAuthority
                )
                or not _is_exact_string_tuple(interface.evidence_ids)
                or len(interface.evidence_ids) > 128
                or type(interface.resolution_required) is not bool
            ):
                raise InputError(
                    "result interface evidence has non-canonical field types"
                )


def _preflight_json(raw: Any) -> None:
    pending: list[tuple[Any, int, str]] = [(raw, 0, "interface_assembly")]
    nodes = 0
    while pending:
        value, depth, field = pending.pop()
        nodes += 1
        if nodes > MAX_JSON_NODES:
            raise InputError(
                f"interface_assembly exceeds the {MAX_JSON_NODES}-node input limit"
            )
        if depth > MAX_JSON_DEPTH:
            raise InputError(
                f"interface_assembly exceeds the {MAX_JSON_DEPTH}-level depth limit"
            )
        if type(value) is dict:
            if nodes + len(pending) + len(value) > MAX_JSON_NODES:
                raise InputError(
                    f"interface_assembly exceeds the {MAX_JSON_NODES}-node input limit"
                )
            for key, child in value.items():
                if type(key) is not str:
                    raise InputError(f"{field} field names must be strings")
                _utf8_string(key, f"{field} field name")
                if len(key) > MAX_JSON_STRING_CHARACTERS:
                    raise InputError(f"{field} contains an overlong field name")
                pending.append((child, depth + 1, f"{field}.{key}"))
        elif type(value) is list:
            if nodes + len(pending) + len(value) > MAX_JSON_NODES:
                raise InputError(
                    f"interface_assembly exceeds the {MAX_JSON_NODES}-node input limit"
                )
            pending.extend(
                (child, depth + 1, f"{field}[{index}]")
                for index, child in enumerate(value)
            )
        elif type(value) is str:
            _utf8_string(value, field)
            if len(value) > MAX_JSON_STRING_CHARACTERS:
                raise InputError(
                    f"{field} exceeds the {MAX_JSON_STRING_CHARACTERS}-character limit"
                )
        elif type(value) is int:
            if value.bit_length() > MAX_JSON_INTEGER_BITS:
                raise InputError(
                    f"{field} exceeds the {MAX_JSON_INTEGER_BITS}-bit integer limit"
                )
        elif type(value) not in {bool, type(None)}:
            raise InputError(f"{field} is not a supported JSON value")


def _utf8_string(value: str, field: str) -> None:
    try:
        value.encode("utf-8", errors="strict")
    except UnicodeEncodeError as exc:
        raise InputError(f"{field} must contain valid UTF-8 scalar values") from exc
