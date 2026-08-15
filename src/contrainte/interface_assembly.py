from __future__ import annotations

import itertools
from collections import deque
from dataclasses import dataclass
from decimal import Decimal
from enum import Enum
from fractions import Fraction
from types import MappingProxyType
from typing import Any

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

INTERFACE_ASSEMBLY_SCHEMA = "contrainte.interface-assembly/0.1"
INTERFACE_ASSEMBLY_RESULT_SCHEMA = "contrainte.interface-assembly-result/0.1"

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
MAX_PREFERENCE_RANK = 1_000_000_000
_MAPPING_PROXY_TYPE = type(MappingProxyType({}))


class SolveStatus(str, Enum):
    SOLVED = "solved"
    UNSATISFIABLE = "unsatisfiable"
    INCONCLUSIVE = "inconclusive"


class InconclusiveReason(str, Enum):
    CANDIDATE_BUDGET_EXHAUSTED = "candidate_budget_exhausted"
    EXACT_SCALAR_LIMIT = "exact_scalar_limit"
    WORK_BUDGET_EXHAUSTED = "work_budget_exhausted"


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
    occurrences: tuple[InterfaceOccurrence, ...]
    mates: tuple[InterfaceMate, ...]
    candidate_budget: int
    schema_version: str = INTERFACE_ASSEMBLY_SCHEMA

    @classmethod
    def from_dict(cls, raw: Any) -> InterfaceAssembly:
        _preflight_json(raw)
        values = _require_exact_keys(
            raw,
            required={"schema_version", "occurrences", "mates", "candidate_budget"},
            field="interface_assembly",
        )
        if (
            type(values["schema_version"]) is not str
            or values["schema_version"] != INTERFACE_ASSEMBLY_SCHEMA
        ):
            raise InputError(
                "interface_assembly.schema_version must be "
                f"{INTERFACE_ASSEMBLY_SCHEMA!r}"
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
        occurrences = tuple(
            InterfaceOccurrence.from_dict(
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
        total_interfaces = sum(len(item.component.interfaces) for item in occurrences)
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
class InterfaceAssemblyResult:
    status: SolveStatus
    examined_candidates: int
    candidate_budget: int
    occurrence_transforms: tuple[SolvedOccurrence, ...] = ()
    selected_alternatives: tuple[SelectedMateAlternative, ...] = ()
    inconclusive_reason: InconclusiveReason | None = None
    schema_version: str = INTERFACE_ASSEMBLY_RESULT_SCHEMA

    @classmethod
    def from_dict(cls, raw: Any) -> InterfaceAssemblyResult:
        _preflight_json(raw)
        values = _require_exact_keys(
            raw,
            required={
                "schema_version",
                "status",
                "examined_candidates",
                "candidate_budget",
                "occurrence_transforms",
                "selected_alternatives",
            },
            optional={"inconclusive_reason"},
            field="interface_assembly_result",
        )
        if (
            type(values["schema_version"]) is not str
            or values["schema_version"] != INTERFACE_ASSEMBLY_RESULT_SCHEMA
        ):
            raise InputError(
                "interface_assembly_result.schema_version must be "
                f"{INTERFACE_ASSEMBLY_RESULT_SCHEMA!r}"
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
        return document


class _ExactScalarLimit(Exception):
    pass


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
    occurrences = {item.occurrence_id: item for item in assembly.occurrences}
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

    occurrences = {item.occurrence_id: item for item in assembly.occurrences}
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
    occurrences = {item.occurrence_id: item for item in assembly.occurrences}
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
    occurrences: dict[str, InterfaceOccurrence], endpoint: InterfaceEndpoint
) -> ExactRigidTransform:
    occurrence = occurrences[endpoint.occurrence_id]
    interface = next(
        item
        for item in occurrence.component.interfaces
        if item.interface_id == endpoint.interface_id
    )
    if interface.frame is None:  # pragma: no cover - component v0.3 guard
        raise InputError("interface frame is required")
    return _frame_transform(interface.frame, field="interface frame")


def _validate_mates(assembly: InterfaceAssembly) -> None:
    occurrences = {item.occurrence_id: item for item in assembly.occurrences}
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
        for property_key in mate.property_keys:
            if (
                property_key not in first.properties
                or property_key not in second.properties
                or first.properties[property_key] != second.properties[property_key]
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
    occurrences: dict[str, InterfaceOccurrence],
    endpoint: InterfaceEndpoint,
    *,
    field: str,
) -> ComponentInterface:
    occurrence = occurrences.get(endpoint.occurrence_id)
    if occurrence is None:
        raise InputError(
            f"{field} references unknown occurrence {endpoint.occurrence_id!r}"
        )
    matches = tuple(
        item
        for item in occurrence.component.interfaces
        if item.interface_id == endpoint.interface_id
    )
    if len(matches) != 1:
        raise InputError(
            f"{field} must identify exactly one framed interface, got "
            f"{endpoint.interface_id!r}"
        )
    if matches[0].frame is None:  # pragma: no cover - component v0.3 guard
        raise InputError(f"{field} interface must have an exact frame")
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
        if (
            type(occurrence) is not InterfaceOccurrence
            or type(occurrence.component) is not ComponentManifest
        ):
            raise InputError("assembly object contains a non-canonical occurrence")
        component = occurrence.component
        if (
            type(component.artifacts) is not tuple
            or type(component.interfaces) is not tuple
            or type(component.capabilities) is not tuple
            or type(component.metadata) is not _MAPPING_PROXY_TYPE
            or len(component.artifacts) > MAX_ARTIFACTS_PER_COMPONENT
            or len(component.interfaces) > MAX_INTERFACES_PER_COMPONENT
            or len(component.capabilities) > MAX_CAPABILITIES_PER_COMPONENT
            or len(component.metadata) > MAX_COMPONENT_METADATA_FIELDS
        ):
            raise InputError("assembly component exceeds direct collection limits")
        total_interfaces += len(component.interfaces)
        if total_interfaces > MAX_TOTAL_INTERFACES:
            raise InputError("assembly exceeds the aggregate interface limit")
        projected_json_nodes += (
            25
            + 6 * len(component.artifacts)
            + len(component.capabilities)
            + len(component.metadata)
            + (20 if occurrence.anchor_transform is not None else 0)
        )
        for interface in component.interfaces:
            if (
                type(interface) is not ComponentInterface
                or type(interface.properties) is not _MAPPING_PROXY_TYPE
                or len(interface.properties) > MAX_INTERFACE_PROPERTIES
            ):
                raise InputError("assembly interface exceeds direct collection limits")
            projected_json_nodes += 26 + len(interface.properties)
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


def _validate_direct_assembly_types(assembly: InterfaceAssembly) -> None:
    if (
        type(assembly.occurrences) is not tuple
        or type(assembly.mates) is not tuple
        or type(assembly.candidate_budget) is not int
        or type(assembly.schema_version) is not str
    ):
        raise InputError("assembly object contains non-canonical field types")
    for occurrence in assembly.occurrences:
        if (
            type(occurrence) is not InterfaceOccurrence
            or type(occurrence.occurrence_id) is not str
            or type(occurrence.component) is not ComponentManifest
            or (
                occurrence.anchor_transform is not None
                and type(occurrence.anchor_transform) is not ExactRigidTransform
            )
        ):
            raise InputError("assembly occurrence contains non-canonical field types")
        component = occurrence.component
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
    ):
        raise InputError("result object contains non-canonical field types")
    if (
        len(result.occurrence_transforms) > MAX_OCCURRENCES
        or len(result.selected_alternatives) > MAX_MATES
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
            for key, child in value.items():
                if type(key) is not str:
                    raise InputError(f"{field} field names must be strings")
                if len(key) > MAX_JSON_STRING_CHARACTERS:
                    raise InputError(f"{field} contains an overlong field name")
                pending.append((child, depth + 1, f"{field}.{key}"))
        elif type(value) is list:
            pending.extend(
                (child, depth + 1, f"{field}[{index}]")
                for index, child in enumerate(value)
            )
        elif type(value) is str:
            if len(value) > MAX_JSON_STRING_CHARACTERS:
                raise InputError(
                    f"{field} exceeds the {MAX_JSON_STRING_CHARACTERS}-character limit"
                )
        elif type(value) not in {int, bool, type(None)}:
            raise InputError(f"{field} is not a supported JSON value")
