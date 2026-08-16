from __future__ import annotations

import copy
import itertools
import json
import os
import re
import secrets
import stat
import unicodedata
from collections.abc import Callable
from dataclasses import dataclass
from decimal import ROUND_HALF_EVEN, Context, localcontext
from fractions import Fraction
from pathlib import Path, PurePosixPath
from types import MappingProxyType
from typing import Any

from .artifacts import package_version
from .canonical import digest, dumps_pretty
from .component import COMPONENT_SCHEMA_V3
from .component_assembly import (
    ComponentBinding,
    ComponentPairClearance,
    SourceFileRef,
    _bound_release_snapshot,
    _BoundDirectory,
    _BoundSourceTree,
    _kernel_fraction,
    _normal_windows_handle_path,
    _open_retained_bound_file,
    _read_stable_file,
    _report_fraction,
    _require_direct_directory,
    _require_posix_named_handle,
    _RetainedBoundFile,
    _sha256_bytes,
    _source_root,
    _stat_identity,
    _windows_close,
    _windows_final_path,
    _windows_info,
    _windows_mark_delete,
    _windows_open,
    _windows_read,
    _windows_rename,
    _windows_write,
)
from .errors import ContrainteError, ExecutionError, InputError, IntegrityError
from .exact_transform import ExactRigidTransform, ExactRotation3
from .interface_assembly import (
    INTERFACE_ASSEMBLY_RESULT_SCHEMA_V2,
    INTERFACE_ASSEMBLY_SCHEMA_V2,
    InterfaceAssembly,
    InterfaceAssemblyResult,
    ParticipantKind,
    ProtectedReferenceParticipant,
    ReleasedComponentParticipant,
    SolveStatus,
    verify_interface_assembly_result,
)
from .reference_component import (
    DesignAroundProjection,
    DesignAroundRequest,
    EvidenceAuthority,
    ExactBox,
    ReferenceComponentManifest,
    verify_design_around_projection,
)

REFERENCE_SPATIAL_ASSEMBLY_SCHEMA = "contrainte.reference-spatial-assembly/0.1"
REFERENCE_SPATIAL_ASSEMBLY_BUNDLE_SCHEMA = (
    "contrainte.reference-spatial-assembly-bundle/0.1"
)

_MAX_SOURCE_BYTES = 4 * 1024 * 1024
_MAX_RELEASED_COMPONENTS = 63
_MAX_PROTECTED_REGIONS = 32
_MAX_PAIR_RULES = (_MAX_RELEASED_COMPONENTS * (_MAX_RELEASED_COMPONENTS - 1)) // 2
_MAX_JSON_NODES = 100_000
_MAX_JSON_DEPTH = 40
_MAX_JSON_STRING_CHARACTERS = 1_000_000
_MAX_JSON_INTEGER_BITS = 64
_MAX_BUNDLE_BYTES = 4 * 1024 * 1024
_INTERFERENCE_TOLERANCE = Fraction(1, 1_000_000)
_DISTANCE_TOLERANCE = Fraction(1, 1_000_000)
_MATRIX_TOLERANCE = Fraction(1, 1_000_000_000_000)
_MAX_SPATIAL_SCALAR_MM = Fraction(1_000_000_000, 1)
_MIN_PROTECTED_EDGE_MM = Fraction(1, 1_000_000)
_SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_SHA256 = re.compile(r"^sha256:[0-9a-f]{64}$")
_RATIONAL = re.compile(r"^(?:0|[1-9][0-9]*)(?:/[1-9][0-9]*)?$")


def _execution_context() -> Context:
    context = Context(
        prec=28,
        rounding=ROUND_HALF_EVEN,
        Emin=-999999,
        Emax=999999,
        capitals=1,
        clamp=0,
    )
    return context


_EXECUTION_CONTEXT = _execution_context()


def _exact_keys(raw: Any, expected: set[str], field: str) -> dict[str, Any]:
    if type(raw) is not dict or any(type(key) is not str for key in raw):
        raise InputError(f"{field} must be a plain JSON object with string keys")
    if set(raw) != expected:
        raise InputError(f"{field} must contain exactly {', '.join(sorted(expected))}")
    return raw


def _identifier(value: Any, field: str) -> str:
    if type(value) is not str or _SAFE_ID.fullmatch(value) is None:
        raise InputError(f"{field} must be a safe ASCII identifier")
    return value


def _text(value: Any, field: str) -> str:
    if (
        type(value) is not str
        or not value
        or len(value) > 2_048
        or any(
            unicodedata.category(character) in {"Cc", "Cf", "Cs", "Zl", "Zp"}
            for character in value
        )
    ):
        raise InputError(f"{field} must be bounded terminal-safe text")
    try:
        value.encode("utf-8")
    except UnicodeEncodeError as exc:
        raise InputError(f"{field} must contain valid Unicode") from exc
    return value


def _sha256(value: Any, field: str) -> str:
    if type(value) is not str or _SHA256.fullmatch(value) is None:
        raise InputError(f"{field} must be a lowercase sha256 digest")
    return value


def _fraction_text(value: Fraction) -> str:
    return (
        str(value.numerator)
        if value.denominator == 1
        else f"{value.numerator}/{value.denominator}"
    )


def _fraction(value: Any, field: str) -> Fraction:
    if type(value) is not str or len(value) > 128 or _RATIONAL.fullmatch(value) is None:
        raise InputError(f"{field} must be a canonical non-negative rational string")
    numerator, separator, denominator = value.partition("/")
    result = Fraction(int(numerator), int(denominator) if separator else 1)
    if _fraction_text(result) != value:
        raise InputError(f"{field} must be reduced and canonical")
    return result


def _bounded_fraction(value: Any, field: str) -> str:
    if (
        type(value) is not Fraction
        or value < 0
        or value.numerator.bit_length() > 512
        or value.denominator.bit_length() > 512
    ):
        raise InputError(f"{field} must be a bounded non-negative Fraction")
    rendered = _fraction_text(value)
    if len(rendered) > 128:
        raise InputError(f"{field} exceeds its exact scalar limit")
    return rendered


def _preflight_json(raw: Any) -> None:
    pending: list[tuple[Any, int]] = [(raw, 1)]
    nodes = 0
    while pending:
        value, depth = pending.pop()
        nodes += 1
        if nodes > _MAX_JSON_NODES:
            raise InputError("reference spatial assembly exceeds its JSON node limit")
        if depth > _MAX_JSON_DEPTH:
            raise InputError("reference spatial assembly exceeds its JSON depth limit")
        if value is None or type(value) is bool:
            continue
        if type(value) is int:
            if value.bit_length() > _MAX_JSON_INTEGER_BITS:
                raise InputError(
                    "reference spatial assembly integer exceeds its bit limit"
                )
            continue
        if type(value) is str:
            if len(value) > _MAX_JSON_STRING_CHARACTERS:
                raise InputError("reference spatial assembly string exceeds its limit")
            try:
                value.encode("utf-8")
            except UnicodeEncodeError as exc:
                raise InputError(
                    "reference spatial assembly contains invalid Unicode"
                ) from exc
            continue
        if type(value) is list:
            if len(value) > _MAX_JSON_NODES:
                raise InputError("reference spatial assembly list exceeds its limit")
            pending.extend((item, depth + 1) for item in value)
            continue
        if type(value) is dict:
            if len(value) > _MAX_JSON_NODES:
                raise InputError("reference spatial assembly object exceeds its limit")
            for key, item in value.items():
                if type(key) is not str:
                    raise InputError("reference spatial assembly keys must be strings")
                pending.append((key, depth + 1))
                pending.append((item, depth + 1))
            continue
        raise InputError(
            "reference spatial assembly must contain only built-in JSON values"
        )


def _json_integer(text: str) -> int:
    digits = text.removeprefix("-")
    if len(digits) > 20:
        raise InputError("reference spatial assembly integer exceeds its bit limit")
    value = int(text)
    if value.bit_length() > _MAX_JSON_INTEGER_BITS:
        raise InputError("reference spatial assembly integer exceeds its bit limit")
    return value


def _json_float(text: str) -> None:
    raise InputError(
        f"JSON floating-point literal {text!r} is forbidden; use exact rational strings"
    )


def _json_constant(text: str) -> None:
    raise InputError(f"non-finite JSON constant {text!r} is forbidden")


def _json_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise InputError(f"duplicate JSON object field is forbidden: {key!r}")
        result[key] = value
    return result


def _load_json_bytes(
    captured: bytes,
    *,
    field: str,
    error_type: type[InputError | IntegrityError] = InputError,
) -> Any:
    try:
        text = captured.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise error_type(f"{field} must be valid UTF-8") from exc
    try:
        raw = json.loads(
            text,
            parse_float=_json_float,
            parse_int=_json_integer,
            parse_constant=_json_constant,
            object_pairs_hook=_json_object,
        )
        _preflight_json(raw)
    except json.JSONDecodeError as exc:
        raise error_type(
            f"{field} is invalid JSON at line {exc.lineno}, column {exc.colno}"
        ) from exc
    except (InputError, RecursionError) as exc:
        raise error_type(f"{field} is invalid: {exc}") from exc
    return raw


@dataclass(frozen=True, slots=True)
class ProtectedReferenceBinding:
    occurrence_id: str
    reference_component: SourceFileRef
    reference_component_digest: str
    design_around_request: SourceFileRef
    design_around_request_digest: str
    design_around_projection: SourceFileRef
    design_around_projection_digest: str

    def __init_subclass__(cls, **kwargs: Any) -> None:
        raise TypeError("ProtectedReferenceBinding may not be subclassed")

    @classmethod
    def from_dict(cls, raw: Any, *, field: str) -> ProtectedReferenceBinding:
        values = _exact_keys(
            raw,
            {
                "occurrence_id",
                "reference_component",
                "reference_component_digest",
                "design_around_request",
                "design_around_request_digest",
                "design_around_projection",
                "design_around_projection_digest",
            },
            field,
        )
        return cls(
            _identifier(values["occurrence_id"], f"{field}.occurrence_id"),
            SourceFileRef.from_dict(
                values["reference_component"], field=f"{field}.reference_component"
            ),
            _sha256(
                values["reference_component_digest"],
                f"{field}.reference_component_digest",
            ),
            SourceFileRef.from_dict(
                values["design_around_request"],
                field=f"{field}.design_around_request",
            ),
            _sha256(
                values["design_around_request_digest"],
                f"{field}.design_around_request_digest",
            ),
            SourceFileRef.from_dict(
                values["design_around_projection"],
                field=f"{field}.design_around_projection",
            ),
            _sha256(
                values["design_around_projection_digest"],
                f"{field}.design_around_projection_digest",
            ),
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "occurrence_id": self.occurrence_id,
            "reference_component": self.reference_component.as_dict(),
            "reference_component_digest": self.reference_component_digest,
            "design_around_request": self.design_around_request.as_dict(),
            "design_around_request_digest": self.design_around_request_digest,
            "design_around_projection": self.design_around_projection.as_dict(),
            "design_around_projection_digest": self.design_around_projection_digest,
        }


@dataclass(frozen=True, slots=True)
class ReferenceSpatialAssembly:
    assembly_id: str
    revision: str
    title: str
    interface_assembly: SourceFileRef
    interface_result: SourceFileRef
    protected_reference: ProtectedReferenceBinding
    released_components: tuple[ComponentBinding, ...]
    minimum_occupied_clearance_mm: Fraction
    default_released_clearance_mm: Fraction
    released_pair_clearances: tuple[ComponentPairClearance, ...]
    schema_version: str = REFERENCE_SPATIAL_ASSEMBLY_SCHEMA

    def __init_subclass__(cls, **kwargs: Any) -> None:
        raise TypeError("ReferenceSpatialAssembly may not be subclassed")

    @classmethod
    def from_dict(cls, raw: Any) -> ReferenceSpatialAssembly:
        _preflight_json(raw)
        values = _exact_keys(
            raw,
            {
                "schema_version",
                "assembly_id",
                "revision",
                "title",
                "interface_assembly",
                "interface_result",
                "protected_reference",
                "released_components",
                "minimum_occupied_clearance_mm",
                "default_released_clearance_mm",
                "released_pair_clearances",
            },
            "reference_spatial_assembly",
        )
        if values["schema_version"] != REFERENCE_SPATIAL_ASSEMBLY_SCHEMA:
            raise InputError(
                "reference_spatial_assembly.schema_version must be "
                f"{REFERENCE_SPATIAL_ASSEMBLY_SCHEMA!r}"
            )
        released_raw = values["released_components"]
        rules_raw = values["released_pair_clearances"]
        if (
            type(released_raw) is not list
            or not 1 <= len(released_raw) <= _MAX_RELEASED_COMPONENTS
        ):
            raise InputError(
                "reference_spatial_assembly.released_components must contain 1 to 63 items"
            )
        if type(rules_raw) is not list or len(rules_raw) > _MAX_PAIR_RULES:
            raise InputError(
                "reference_spatial_assembly.released_pair_clearances exceeds its limit"
            )
        released = tuple(
            ComponentBinding.from_dict(
                item,
                field=f"reference_spatial_assembly.released_components[{index}]",
            )
            for index, item in enumerate(released_raw)
        )
        released_ids = tuple(item.occurrence_id for item in released)
        if released_ids != tuple(sorted(set(released_ids))):
            raise InputError("released component bindings must be sorted and unique")
        protected = ProtectedReferenceBinding.from_dict(
            values["protected_reference"],
            field="reference_spatial_assembly.protected_reference",
        )
        if protected.occurrence_id in set(released_ids):
            raise InputError(
                "protected and released occurrence identifiers must differ"
            )
        rules = tuple(
            ComponentPairClearance.from_dict(
                item,
                field=(f"reference_spatial_assembly.released_pair_clearances[{index}]"),
            )
            for index, item in enumerate(rules_raw)
        )
        pairs = tuple(item.pair for item in rules)
        if pairs != tuple(sorted(set(pairs))):
            raise InputError("released pair clearances must be sorted and unique")
        if any(
            left not in released_ids or right not in released_ids
            for left, right in pairs
        ):
            raise InputError("released pair clearances reference unknown occurrences")
        return cls(
            _identifier(
                values["assembly_id"], "reference_spatial_assembly.assembly_id"
            ),
            _text(values["revision"], "reference_spatial_assembly.revision"),
            _text(values["title"], "reference_spatial_assembly.title"),
            SourceFileRef.from_dict(
                values["interface_assembly"],
                field="reference_spatial_assembly.interface_assembly",
            ),
            SourceFileRef.from_dict(
                values["interface_result"],
                field="reference_spatial_assembly.interface_result",
            ),
            protected,
            released,
            _fraction(
                values["minimum_occupied_clearance_mm"],
                "reference_spatial_assembly.minimum_occupied_clearance_mm",
            ),
            _fraction(
                values["default_released_clearance_mm"],
                "reference_spatial_assembly.default_released_clearance_mm",
            ),
            rules,
        )

    @property
    def assembly_digest(self) -> str:
        return digest(self.as_dict())

    def released_clearance_for(self, first: str, second: str) -> Fraction:
        pair = tuple(sorted((first, second)))
        match = next(
            (item for item in self.released_pair_clearances if item.pair == pair),
            None,
        )
        return (
            self.default_released_clearance_mm
            if match is None
            else match.minimum_clearance_mm
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "assembly_id": self.assembly_id,
            "revision": self.revision,
            "title": self.title,
            "interface_assembly": self.interface_assembly.as_dict(),
            "interface_result": self.interface_result.as_dict(),
            "protected_reference": self.protected_reference.as_dict(),
            "released_components": [
                item.as_dict() for item in self.released_components
            ],
            "minimum_occupied_clearance_mm": _fraction_text(
                self.minimum_occupied_clearance_mm
            ),
            "default_released_clearance_mm": _fraction_text(
                self.default_released_clearance_mm
            ),
            "released_pair_clearances": [
                item.as_dict() for item in self.released_pair_clearances
            ],
        }


def _trusted_snapshot(value: Any) -> ReferenceSpatialAssembly:
    if type(value) is not ReferenceSpatialAssembly:
        raise InputError(
            "reference spatial assembly must be an exact ReferenceSpatialAssembly value"
        )
    if (
        type(value.interface_assembly) is not SourceFileRef
        or type(value.interface_result) is not SourceFileRef
        or type(value.protected_reference) is not ProtectedReferenceBinding
    ):
        raise InputError(
            "reference spatial assembly source bindings have invalid types"
        )
    protected = value.protected_reference
    if (
        type(protected.reference_component) is not SourceFileRef
        or type(protected.design_around_request) is not SourceFileRef
        or type(protected.design_around_projection) is not SourceFileRef
    ):
        raise InputError(
            "protected reference source bindings have invalid direct types"
        )
    if (
        type(value.released_components) is not tuple
        or not 1 <= len(value.released_components) <= _MAX_RELEASED_COMPONENTS
        or not all(type(item) is ComponentBinding for item in value.released_components)
    ):
        raise InputError("released component bindings have invalid direct state")
    if (
        type(value.released_pair_clearances) is not tuple
        or len(value.released_pair_clearances) > _MAX_PAIR_RULES
        or not all(
            type(item) is ComponentPairClearance
            for item in value.released_pair_clearances
        )
    ):
        raise InputError("released pair clearances have invalid direct state")
    source_ref_fields = (
        (value.interface_assembly, "interface_assembly"),
        (value.interface_result, "interface_result"),
        (protected.reference_component, "reference_component"),
        (protected.design_around_request, "design_around_request"),
        (protected.design_around_projection, "design_around_projection"),
    )
    source_refs: dict[str, dict[str, str]] = {}
    for source_ref, field in source_ref_fields:
        source_refs[field] = SourceFileRef.from_dict(
            {"locator": source_ref.locator, "file_digest": source_ref.file_digest},
            field=field,
        ).as_dict()
    protected_document = {
        "occurrence_id": protected.occurrence_id,
        "reference_component": source_refs["reference_component"],
        "reference_component_digest": protected.reference_component_digest,
        "design_around_request": source_refs["design_around_request"],
        "design_around_request_digest": protected.design_around_request_digest,
        "design_around_projection": source_refs["design_around_projection"],
        "design_around_projection_digest": protected.design_around_projection_digest,
    }
    released_documents = [
        ComponentBinding.from_dict(
            {
                "occurrence_id": item.occurrence_id,
                "manifest_locator": item.manifest_locator,
                "manifest_file_digest": item.manifest_file_digest,
                "manifest_digest": item.manifest_digest,
            },
            field=f"released_components[{index}]",
        ).as_dict()
        for index, item in enumerate(value.released_components)
    ]
    pair_documents = [
        ComponentPairClearance.from_dict(
            {
                "first_occurrence_id": item.first_occurrence_id,
                "second_occurrence_id": item.second_occurrence_id,
                "minimum_clearance_mm": _bounded_fraction(
                    item.minimum_clearance_mm,
                    f"released_pair_clearances[{index}].minimum_clearance_mm",
                ),
            },
            field=f"released_pair_clearances[{index}]",
        ).as_dict()
        for index, item in enumerate(value.released_pair_clearances)
    ]
    document = {
        "schema_version": _text(value.schema_version, "schema_version"),
        "assembly_id": _identifier(value.assembly_id, "assembly_id"),
        "revision": _text(value.revision, "revision"),
        "title": _text(value.title, "title"),
        "interface_assembly": source_refs["interface_assembly"],
        "interface_result": source_refs["interface_result"],
        "protected_reference": protected_document,
        "released_components": released_documents,
        "minimum_occupied_clearance_mm": _bounded_fraction(
            value.minimum_occupied_clearance_mm, "minimum_occupied_clearance_mm"
        ),
        "default_released_clearance_mm": _bounded_fraction(
            value.default_released_clearance_mm, "default_released_clearance_mm"
        ),
        "released_pair_clearances": pair_documents,
    }
    return ReferenceSpatialAssembly.from_dict(document)


@dataclass(slots=True)
class _BoundDirectoryChain:
    directories: tuple[_BoundDirectory, ...]
    created: tuple[_BoundDirectory, ...]

    @property
    def leaf(self) -> _BoundDirectory:
        return self.directories[-1]

    @classmethod
    def open(cls, path: Path, *, create: bool) -> _BoundDirectoryChain:
        absolute = Path(os.path.abspath(path))
        if not absolute.anchor or absolute.name in {"", ".", ".."}:
            raise InputError("bound directory path must name a non-root directory")
        anchor = Path(absolute.anchor)
        opened: list[_BoundDirectory] = []
        created: list[_BoundDirectory] = []
        try:
            current = _BoundDirectory.open(anchor)
            opened.append(current)
            for name in absolute.parts[1:]:
                current.verify_visible()
                names = current.names()
                if name in names:
                    child = current.child_directory(name)
                elif create:
                    child = current.create_child_directory(name)
                    created.append(child)
                else:
                    raise InputError(
                        f"bound directory component is unavailable: {name}"
                    )
                opened.append(child)
                current = child
            current.verify_visible()
            return cls(tuple(opened), tuple(created))
        except BaseException:
            for directory in reversed(opened):
                directory.close()
            raise

    def verify_visible(self) -> None:
        for directory in self.directories:
            directory.verify_visible()

    def close(self) -> None:
        for directory in reversed(self.directories):
            try:
                directory.close()
            except OSError:
                pass


@dataclass(slots=True)
class _AssemblyInputSnapshot:
    path: Path
    chain: _BoundDirectoryChain
    retained: _RetainedBoundFile
    assembly: ReferenceSpatialAssembly

    def verify_visible(self) -> None:
        self.chain.verify_visible()
        self.retained.verify_visible()
        if self.retained.captured != dumps_pretty(self.assembly.as_dict()).encode(
            "utf-8"
        ):
            # The exact captured bytes are authoritative. Canonical spelling is not
            # required, so only parse reproduction is checked here.
            reproduced = ReferenceSpatialAssembly.from_dict(
                _load_json_bytes(
                    self.retained.captured,
                    field="retained reference spatial assembly input",
                )
            )
            if reproduced.as_dict() != self.assembly.as_dict():
                raise IntegrityError("retained assembly input no longer reproduces")

    def close(self) -> None:
        try:
            self.retained.close()
        except OSError:
            pass
        self.chain.close()


def _open_assembly_input(path: str | Path) -> _AssemblyInputSnapshot:
    source = Path(os.path.abspath(Path(path)))
    if source.name in {"", ".", ".."}:
        raise InputError("reference spatial assembly input path is invalid")
    chain = _BoundDirectoryChain.open(source.parent, create=False)
    retained: _RetainedBoundFile | None = None
    try:
        retained = _open_retained_bound_file(
            chain.leaf,
            source.name,
            maximum_bytes=_MAX_SOURCE_BYTES,
            field=f"reference spatial assembly {source.name}",
            expected_digest=None,
            error_type=InputError,
        )
        assembly = ReferenceSpatialAssembly.from_dict(
            _load_json_bytes(
                retained.captured,
                field=f"reference spatial assembly {source.name}",
            )
        )
        snapshot = _AssemblyInputSnapshot(source, chain, retained, assembly)
        snapshot.verify_visible()
        return snapshot
    except BaseException:
        if retained is not None:
            retained.close()
        chain.close()
        raise


@dataclass(frozen=True, slots=True)
class _SpatialContext:
    interface_assembly: InterfaceAssembly
    interface_result: InterfaceAssemblyResult
    reference_component: ReferenceComponentManifest
    request: DesignAroundRequest
    projection: DesignAroundProjection
    released_shapes: MappingProxyType
    source_records: tuple[dict[str, Any], ...]
    source_locators: frozenset[str]


def _read_document(
    tree: _BoundSourceTree,
    source: SourceFileRef,
    *,
    field: str,
) -> tuple[Any, bytes]:
    captured = tree.read_locator(
        source.locator,
        maximum_bytes=_MAX_SOURCE_BYTES,
        field=field,
        expected_digest=source.file_digest,
    )
    return _load_json_bytes(captured, field=field), captured


def _load_context(
    assembly: ReferenceSpatialAssembly, tree: _BoundSourceTree
) -> _SpatialContext:
    interface_raw, _ = _read_document(
        tree, assembly.interface_assembly, field="interface assembly source"
    )
    result_raw, _ = _read_document(
        tree, assembly.interface_result, field="interface result source"
    )
    interface = InterfaceAssembly.from_dict(interface_raw)
    result = InterfaceAssemblyResult.from_dict(result_raw)
    if interface.schema_version != INTERFACE_ASSEMBLY_SCHEMA_V2:
        raise InputError("reference spatial assembly requires interface-assembly/0.2")
    if result.schema_version != INTERFACE_ASSEMBLY_RESULT_SCHEMA_V2:
        raise InputError(
            "reference spatial assembly requires interface-assembly-result/0.2"
        )
    if result.status is not SolveStatus.SOLVED:
        raise InputError(
            "reference spatial assembly requires a solved interface result"
        )
    if not verify_interface_assembly_result(interface, result):
        raise IntegrityError(
            "interface assembly result does not independently reproduce"
        )

    protected_occurrences = tuple(
        occurrence
        for occurrence in interface.occurrences
        if occurrence.participant.kind is ParticipantKind.PROTECTED_REFERENCE
    )
    released_occurrences = tuple(
        occurrence
        for occurrence in interface.occurrences
        if occurrence.participant.kind is ParticipantKind.RELEASED_COMPONENT
    )
    if len(protected_occurrences) != 1:
        raise InputError(
            "interface assembly must contain exactly one protected reference"
        )
    protected_occurrence = protected_occurrences[0]
    if protected_occurrence.occurrence_id != assembly.protected_reference.occurrence_id:
        raise IntegrityError(
            "protected occurrence binding does not match the interface"
        )
    released_ids = tuple(item.occurrence_id for item in assembly.released_components)
    if released_ids != tuple(
        sorted(item.occurrence_id for item in released_occurrences)
    ):
        raise InputError(
            "released component bindings must exactly cover interface occurrences"
        )

    binding = assembly.protected_reference
    manifest_raw, manifest_bytes = _read_document(
        tree, binding.reference_component, field="protected reference component"
    )
    request_raw, request_bytes = _read_document(
        tree, binding.design_around_request, field="protected design-around request"
    )
    projection_raw, projection_bytes = _read_document(
        tree,
        binding.design_around_projection,
        field="protected design-around projection",
    )
    manifest = ReferenceComponentManifest.from_dict(manifest_raw)
    request = DesignAroundRequest.from_dict(request_raw)
    projection = DesignAroundProjection.from_dict(projection_raw)
    if manifest.content_digest != binding.reference_component_digest:
        raise IntegrityError("protected reference semantic digest mismatch")
    if request.content_digest != binding.design_around_request_digest:
        raise IntegrityError("design-around request semantic digest mismatch")
    if projection.content_digest != binding.design_around_projection_digest:
        raise IntegrityError("design-around projection semantic digest mismatch")
    if not verify_design_around_projection(manifest, request, projection):
        raise IntegrityError(
            "design-around projection does not independently reproduce"
        )
    if len(manifest.envelopes) + 1 > _MAX_PROTECTED_REGIONS:
        raise InputError(
            "protected reference occupied/envelope region count exceeds 32"
        )
    if any(
        envelope.envelope_id == "occupied-bounds" for envelope in manifest.envelopes
    ):
        raise InputError(
            "protected envelope identifier 'occupied-bounds' is reserved by spatial assembly"
        )
    boxes = (manifest.occupied_bounds, *(item.bounds for item in manifest.envelopes))
    for box in boxes:
        coordinates = (
            box.minimum.x,
            box.minimum.y,
            box.minimum.z,
            box.maximum.x,
            box.maximum.y,
            box.maximum.z,
        )
        if any(abs(value) > _MAX_SPATIAL_SCALAR_MM for value in coordinates):
            raise InputError("protected spatial coordinate exceeds 1000000000 mm")
        if any(
            getattr(box.maximum, axis) - getattr(box.minimum, axis)
            < _MIN_PROTECTED_EDGE_MM
            for axis in ("x", "y", "z")
        ):
            raise InputError("protected spatial box edge is below 0.000001 mm")
    clearances = (
        assembly.minimum_occupied_clearance_mm,
        assembly.default_released_clearance_mm,
        *(item.minimum_clearance_mm for item in assembly.released_pair_clearances),
        *(item.clearance_mm for item in request.clearances),
    )
    if any(value > _MAX_SPATIAL_SCALAR_MM for value in clearances):
        raise InputError("reference spatial clearance exceeds 1000000000 mm")
    participant = protected_occurrence.participant
    if type(participant) is not ProtectedReferenceParticipant:
        raise IntegrityError("protected interface participant type changed")
    if (
        participant.reference_component.as_dict() != manifest.as_dict()
        or participant.design_around_request.as_dict() != request.as_dict()
        or participant.design_around_projection.as_dict() != projection.as_dict()
    ):
        raise IntegrityError("protected source documents do not match the interface")

    occurrence_index = {item.occurrence_id: item for item in released_occurrences}
    released_shapes: dict[str, Any] = {}
    source_locators = {
        assembly.interface_assembly.locator,
        assembly.interface_result.locator,
        binding.reference_component.locator,
        binding.design_around_request.locator,
        binding.design_around_projection.locator,
    }
    source_records: list[dict[str, Any]] = [
        {
            "occurrence_id": binding.occurrence_id,
            "participant_kind": "protected_reference",
            "reference_component": {
                **binding.reference_component.as_dict(),
                "content_digest": manifest.content_digest,
                "captured_size_bytes": len(manifest_bytes),
            },
            "design_around_request": {
                **binding.design_around_request.as_dict(),
                "content_digest": request.content_digest,
                "captured_size_bytes": len(request_bytes),
            },
            "design_around_projection": {
                **binding.design_around_projection.as_dict(),
                "content_digest": projection.content_digest,
                "captured_size_bytes": len(projection_bytes),
            },
        }
    ]
    for released_binding in assembly.released_components:
        try:
            current_manifest, shape, manifest_bytes = _bound_release_snapshot(
                tree, released_binding.manifest_locator
            )
        except (UnicodeDecodeError, RecursionError, OverflowError) as exc:
            raise InputError(
                "released component snapshot contains invalid bounded data"
            ) from exc
        if _sha256_bytes(manifest_bytes) != released_binding.manifest_file_digest:
            raise IntegrityError("released component manifest file digest mismatch")
        if current_manifest.schema_version != COMPONENT_SCHEMA_V3:
            raise InputError(
                "reference spatial assembly requires component-manifest/0.3 releases"
            )
        if current_manifest.manifest_digest != released_binding.manifest_digest:
            raise IntegrityError("released component semantic digest mismatch")
        embedded = occurrence_index[released_binding.occurrence_id].participant
        if type(embedded) is not ReleasedComponentParticipant:
            raise IntegrityError("released interface participant type changed")
        if embedded.component.as_dict() != current_manifest.as_dict():
            raise IntegrityError(
                "released source manifest does not match the interface"
            )
        released_shapes[released_binding.occurrence_id] = shape
        source_locators.add(released_binding.manifest_locator)
        manifest_parent = PurePosixPath(released_binding.manifest_locator).parent
        for artifact in current_manifest.artifacts:
            artifact_path = manifest_parent / artifact.locator
            source_locators.add(
                artifact.locator
                if str(manifest_parent) == "."
                else artifact_path.as_posix()
            )
        source_records.append(
            {
                "occurrence_id": released_binding.occurrence_id,
                "participant_kind": "released_component",
                "manifest_locator": released_binding.manifest_locator,
                "manifest_file_digest": released_binding.manifest_file_digest,
                "manifest_digest": released_binding.manifest_digest,
                "source_bundle_digest": current_manifest.source_bundle_digest,
                "captured_size_bytes": len(manifest_bytes),
            }
        )
    tree.verify_visible()
    return _SpatialContext(
        interface,
        result,
        manifest,
        request,
        projection,
        MappingProxyType(released_shapes),
        tuple(sorted(source_records, key=lambda item: item["occurrence_id"])),
        frozenset(source_locators),
    )


def _compiler_transforms(context: _SpatialContext) -> dict[str, ExactRigidTransform]:
    return {
        item.occurrence_id: item.transform
        for item in context.interface_result.occurrence_transforms
    }


def _verifier_transforms(context: _SpatialContext) -> dict[str, ExactRigidTransform]:
    expected_ids = {
        occurrence.occurrence_id
        for occurrence in context.interface_assembly.occurrences
    }
    reproduced: dict[str, ExactRigidTransform] = {}
    for solved in tuple(context.interface_result.occurrence_transforms):
        if solved.occurrence_id in reproduced:
            raise IntegrityError("replayed occurrence transform is duplicated")
        reproduced[solved.occurrence_id] = solved.transform
    if set(reproduced) != expected_ids:
        raise IntegrityError("replayed occurrence transform set is incomplete")
    return reproduced


def _verifier_released_clearance(
    assembly: ReferenceSpatialAssembly, first: str, second: str
) -> Fraction:
    left, right = (first, second) if first < second else (second, first)
    required = assembly.default_released_clearance_mm
    found = False
    for rule in tuple(assembly.released_pair_clearances):
        if rule.first_occurrence_id == left and rule.second_occurrence_id == right:
            if found:
                raise IntegrityError("replayed released clearance is duplicated")
            required = rule.minimum_clearance_mm
            found = True
    return required


def _matrix(transform: ExactRigidTransform) -> tuple[tuple[Fraction, ...], ...]:
    rotation = transform.rotation
    return (
        (
            rotation.x_axis.x,
            rotation.y_axis.x,
            rotation.z_axis.x,
            transform.translation.x,
        ),
        (
            rotation.x_axis.y,
            rotation.y_axis.y,
            rotation.z_axis.y,
            transform.translation.y,
        ),
        (
            rotation.x_axis.z,
            rotation.y_axis.z,
            rotation.z_axis.z,
            transform.translation.z,
        ),
    )


def _compiler_transform(transform: ExactRigidTransform) -> tuple[Any, Fraction]:
    try:
        from OCP.gp import gp_Trsf
    except ImportError as exc:
        raise ExecutionError(
            "the CAD backend is not installed; install Contrainte with the 'cad' extra"
        ) from exc
    matrix = _matrix(transform)
    projected = gp_Trsf()
    projected.SetValues(*(float(value) for row in matrix for value in row))
    error = max(
        abs(
            _kernel_fraction(
                projected.Value(row, column),
                error_type=ExecutionError,
                message="Open CASCADE returned an invalid transform coefficient",
            )
            - matrix[row - 1][column - 1]
        )
        for row in range(1, 4)
        for column in range(1, 5)
    )
    if error > _MATRIX_TOLERANCE:
        raise ExecutionError("Open CASCADE changed an exact transform beyond tolerance")
    return projected, error


def _verifier_transform(transform: ExactRigidTransform) -> tuple[Any, Fraction]:
    try:
        from OCP.gp import gp_Trsf
    except ImportError as exc:
        raise IntegrityError(
            "the CAD backend required for replay is unavailable"
        ) from exc
    rotation = transform.rotation
    expected = (
        (
            rotation.x_axis.x,
            rotation.y_axis.x,
            rotation.z_axis.x,
            transform.translation.x,
        ),
        (
            rotation.x_axis.y,
            rotation.y_axis.y,
            rotation.z_axis.y,
            transform.translation.y,
        ),
        (
            rotation.x_axis.z,
            rotation.y_axis.z,
            rotation.z_axis.z,
            transform.translation.z,
        ),
    )
    projected = gp_Trsf()
    projected.SetValues(
        float(rotation.x_axis.x),
        float(rotation.y_axis.x),
        float(rotation.z_axis.x),
        float(transform.translation.x),
        float(rotation.x_axis.y),
        float(rotation.y_axis.y),
        float(rotation.z_axis.y),
        float(transform.translation.y),
        float(rotation.x_axis.z),
        float(rotation.y_axis.z),
        float(rotation.z_axis.z),
        float(transform.translation.z),
    )
    errors = []
    for row_index, row in enumerate(expected, start=1):
        for column_index, exact in enumerate(row, start=1):
            errors.append(
                abs(
                    _kernel_fraction(
                        projected.Value(row_index, column_index),
                        error_type=IntegrityError,
                        message="kernel transform projection no longer reproduces",
                    )
                    - exact
                )
            )
    error = max(errors)
    if error > Fraction(1, 1_000_000_000_000):
        raise IntegrityError("kernel transform projection no longer reproduces")
    return projected, error


def _compiler_place_released(
    context: _SpatialContext,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    try:
        from build123d import Location
    except ImportError as exc:
        raise ExecutionError("the CAD backend is not installed") from exc
    transforms = _compiler_transforms(context)
    placed: dict[str, Any] = {}
    evidence: list[dict[str, Any]] = []
    for occurrence_id in sorted(context.released_shapes):
        transform = transforms[occurrence_id]
        projected, error = _compiler_transform(transform)
        shape = copy.copy(context.released_shapes[occurrence_id])
        shape.label = occurrence_id
        shape.locate(Location(projected))
        valid = shape.is_valid() if callable(shape.is_valid) else shape.is_valid
        if not valid:
            raise ExecutionError(
                f"released occurrence is not a valid B-rep: {occurrence_id}"
            )
        placed[occurrence_id] = shape
        evidence.append(
            {
                "occurrence_id": occurrence_id,
                "geometry_authority": "verified_local_release_brep",
                "exact_transform": transform.as_dict(),
                "maximum_matrix_projection_error": _report_fraction(error, places=18),
                "projection_tolerance": "0.000000000001",
                "status": "passed",
            }
        )
    return placed, evidence


def _verifier_place_released(
    context: _SpatialContext,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    try:
        from build123d import Location
    except ImportError as exc:
        raise IntegrityError(
            "the CAD backend required for replay is unavailable"
        ) from exc
    transforms = _verifier_transforms(context)
    placed: dict[str, Any] = {}
    evidence: list[dict[str, Any]] = []
    for occurrence_id in sorted(context.released_shapes):
        exact = transforms[occurrence_id]
        projected, error = _verifier_transform(exact)
        shape = copy.copy(context.released_shapes[occurrence_id])
        shape.label = occurrence_id
        shape.locate(Location(gp_trsf=projected))
        validity = shape.is_valid() if callable(shape.is_valid) else shape.is_valid
        if not validity:
            raise IntegrityError(
                f"released occurrence B-rep no longer reproduces: {occurrence_id}"
            )
        placed[occurrence_id] = shape
        evidence.append(
            {
                "occurrence_id": occurrence_id,
                "geometry_authority": "verified_local_release_brep",
                "exact_transform": {
                    "schema_version": "contrainte.exact-rigid-transform/0.1",
                    "unit": "mm",
                    "translation": exact.translation.as_dict(),
                    "basis": exact.rotation.as_dict(),
                },
                "maximum_matrix_projection_error": _report_fraction(error, places=18),
                "projection_tolerance": "0.000000000001",
                "status": "passed",
            }
        )
    return placed, evidence


def _evidence_record(
    manifest: ReferenceComponentManifest, evidence_id: str
) -> tuple[str, str, str]:
    match = next(item for item in manifest.evidence if item.evidence_id == evidence_id)
    return match.authority.value, match.kind.value, match.artifact_digest


def _compiler_region_specs(
    assembly: ReferenceSpatialAssembly, context: _SpatialContext
) -> list[dict[str, Any]]:
    request_clearances = {
        item.envelope_id: item.clearance_mm for item in context.request.clearances
    }
    manifest = context.reference_component
    regions: list[dict[str, Any]] = []
    authority, kind, artifact = _evidence_record(
        manifest, manifest.occupied_bounds_evidence_id
    )
    regions.append(
        {
            "region_id": "occupied-bounds",
            "purpose": "occupied",
            "source_path": "/occupied_bounds",
            "bounds": manifest.occupied_bounds,
            "evidence_id": manifest.occupied_bounds_evidence_id,
            "evidence_authority": authority,
            "evidence_kind": kind,
            "evidence_artifact_digest": artifact,
            "minimum_clearance_mm": assembly.minimum_occupied_clearance_mm,
        }
    )
    for envelope in manifest.envelopes:
        authority, kind, artifact = _evidence_record(manifest, envelope.evidence_id)
        regions.append(
            {
                "region_id": envelope.envelope_id,
                "purpose": envelope.purpose.value,
                "source_path": f"/envelopes/{envelope.envelope_id}",
                "bounds": envelope.bounds,
                "evidence_id": envelope.evidence_id,
                "evidence_authority": authority,
                "evidence_kind": kind,
                "evidence_artifact_digest": artifact,
                "minimum_clearance_mm": request_clearances.get(
                    envelope.envelope_id, Fraction(0)
                ),
            }
        )
    return sorted(regions, key=lambda item: item["region_id"])


def _verifier_region_specs(
    assembly: ReferenceSpatialAssembly, context: _SpatialContext
) -> list[dict[str, Any]]:
    declared_clearances = {
        clearance.envelope_id: clearance.clearance_mm
        for clearance in context.request.clearances
    }
    evidence_index = {
        record.evidence_id: record for record in context.reference_component.evidence
    }
    reproduced: list[dict[str, Any]] = []
    occupied_evidence = evidence_index[
        context.reference_component.occupied_bounds_evidence_id
    ]
    reproduced.append(
        {
            "region_id": "occupied-bounds",
            "purpose": "occupied",
            "source_path": "/occupied_bounds",
            "bounds": context.reference_component.occupied_bounds,
            "evidence_id": occupied_evidence.evidence_id,
            "evidence_authority": occupied_evidence.authority.value,
            "evidence_kind": occupied_evidence.kind.value,
            "evidence_artifact_digest": occupied_evidence.artifact_digest,
            "minimum_clearance_mm": assembly.minimum_occupied_clearance_mm,
        }
    )
    for envelope in tuple(context.reference_component.envelopes):
        record = evidence_index[envelope.evidence_id]
        reproduced.append(
            {
                "region_id": envelope.envelope_id,
                "purpose": envelope.purpose.value,
                "source_path": "/envelopes/" + envelope.envelope_id,
                "bounds": envelope.bounds,
                "evidence_id": record.evidence_id,
                "evidence_authority": record.authority.value,
                "evidence_kind": record.kind.value,
                "evidence_artifact_digest": record.artifact_digest,
                "minimum_clearance_mm": declared_clearances.get(
                    envelope.envelope_id, Fraction(0, 1)
                ),
            }
        )
    reproduced.sort(key=lambda item: item["region_id"])
    return reproduced


def _compiler_place_regions(
    assembly: ReferenceSpatialAssembly, context: _SpatialContext
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    try:
        from build123d import Align, Box, Location
    except ImportError as exc:
        raise ExecutionError("the CAD backend is not installed") from exc
    reference_transform = _compiler_transforms(context)[
        assembly.protected_reference.occurrence_id
    ]
    shapes: dict[str, Any] = {}
    evidence: list[dict[str, Any]] = []
    for spec in _compiler_region_specs(assembly, context):
        bounds: ExactBox = spec["bounds"]
        size = bounds.maximum - bounds.minimum
        local = ExactRigidTransform(bounds.minimum, ExactRotation3.identity())
        world = reference_transform.compose(local)
        projected, error = _compiler_transform(world)
        proxy = Box(
            float(size.x),
            float(size.y),
            float(size.z),
            align=(Align.MIN, Align.MIN, Align.MIN),
        )
        proxy.label = f"protected-proxy:{spec['region_id']}"
        proxy.locate(Location(projected))
        shapes[spec["region_id"]] = proxy
        evidence.append(
            {
                "region_id": spec["region_id"],
                "purpose": spec["purpose"],
                "source_path": spec["source_path"],
                "local_bounds": bounds.as_dict(),
                "exact_world_transform": world.as_dict(),
                "minimum_clearance_mm": _fraction_text(spec["minimum_clearance_mm"]),
                "evidence_id": spec["evidence_id"],
                "evidence_authority": spec["evidence_authority"],
                "evidence_kind": spec["evidence_kind"],
                "evidence_artifact_digest": spec["evidence_artifact_digest"],
                "geometry_authority": "conservative_box_proxy_only",
                "protected_brep_claimed": False,
                "maximum_matrix_projection_error": _report_fraction(error, places=18),
                "projection_tolerance": "0.000000000001",
            }
        )
    return shapes, evidence


def _verifier_place_regions(
    assembly: ReferenceSpatialAssembly, context: _SpatialContext
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    try:
        from build123d import Align, Box, Location
    except ImportError as exc:
        raise IntegrityError(
            "the CAD backend required for replay is unavailable"
        ) from exc
    reference_world = _verifier_transforms(context)[
        assembly.protected_reference.occurrence_id
    ]
    shapes: dict[str, Any] = {}
    records: list[dict[str, Any]] = []
    for spec in _verifier_region_specs(assembly, context):
        bounds: ExactBox = spec["bounds"]
        lengths = (
            bounds.maximum.x - bounds.minimum.x,
            bounds.maximum.y - bounds.minimum.y,
            bounds.maximum.z - bounds.minimum.z,
        )
        offset = ExactRigidTransform(
            translation=bounds.minimum,
            rotation=ExactRotation3.identity(),
        )
        world = reference_world.compose(offset)
        projected, error = _verifier_transform(world)
        proxy = Box(
            float(lengths[0]),
            float(lengths[1]),
            float(lengths[2]),
            align=(Align.MIN, Align.MIN, Align.MIN),
        )
        proxy.label = "protected-proxy:" + spec["region_id"]
        proxy.locate(Location(gp_trsf=projected))
        shapes[spec["region_id"]] = proxy
        records.append(
            {
                "region_id": spec["region_id"],
                "purpose": spec["purpose"],
                "source_path": spec["source_path"],
                "local_bounds": {
                    "unit": "mm",
                    "minimum": bounds.minimum.as_dict(),
                    "maximum": bounds.maximum.as_dict(),
                },
                "exact_world_transform": {
                    "schema_version": "contrainte.exact-rigid-transform/0.1",
                    "unit": "mm",
                    "translation": world.translation.as_dict(),
                    "basis": world.rotation.as_dict(),
                },
                "minimum_clearance_mm": _fraction_text(spec["minimum_clearance_mm"]),
                "evidence_id": spec["evidence_id"],
                "evidence_authority": spec["evidence_authority"],
                "evidence_kind": spec["evidence_kind"],
                "evidence_artifact_digest": spec["evidence_artifact_digest"],
                "geometry_authority": "conservative_box_proxy_only",
                "protected_brep_claimed": False,
                "maximum_matrix_projection_error": _report_fraction(error, places=18),
                "projection_tolerance": "0.000000000001",
            }
        )
    return shapes, records


def _compiler_measure_pair(first: Any, second: Any) -> tuple[Fraction, Fraction]:
    distance = _kernel_fraction(
        first.distance_to(second),
        error_type=ExecutionError,
        message="Open CASCADE spatial distance measurement is invalid",
    )
    common = first & second
    volumes = tuple(
        _kernel_fraction(
            solid.volume,
            error_type=ExecutionError,
            message="Open CASCADE spatial intersection measurement is invalid",
        )
        for solid in common.solids()
    )
    if distance < 0 or any(volume < 0 for volume in volumes):
        raise ExecutionError("Open CASCADE spatial measurement is negative")
    return distance, sum(volumes, Fraction(0))


def _verifier_measure_pair(first: Any, second: Any) -> tuple[Fraction, Fraction]:
    measured_distance = _kernel_fraction(
        first.distance_to(second),
        error_type=IntegrityError,
        message="Open CASCADE replay distance is invalid",
    )
    intersection = first & second
    measured_volumes: list[Fraction] = []
    for solid in intersection.solids():
        measured_volumes.append(
            _kernel_fraction(
                solid.volume,
                error_type=IntegrityError,
                message="Open CASCADE replay intersection is invalid",
            )
        )
    if measured_distance < Fraction(0, 1) or any(
        item < Fraction(0, 1) for item in measured_volumes
    ):
        raise IntegrityError("Open CASCADE replay produced a negative measurement")
    return measured_distance, sum(measured_volumes, Fraction(0, 1))


def _compiler_pair_result(
    first_id: str,
    second_id: str,
    distance: Fraction,
    volume: Fraction,
    minimum: Fraction,
) -> tuple[dict[str, str], str | None]:
    failure = None
    if volume > _INTERFERENCE_TOLERANCE:
        status = "interference"
        failure = f"released:{first_id}/{second_id}:interference"
    elif distance + _DISTANCE_TOLERANCE < minimum:
        status = "clearance_violation"
        failure = f"released:{first_id}/{second_id}:clearance"
    else:
        status = "passed"
    return (
        {
            "first_occurrence_id": first_id,
            "second_occurrence_id": second_id,
            "distance_mm": _report_fraction(distance, places=9),
            "minimum_clearance_mm": _fraction_text(minimum),
            "interference_volume_mm3": _report_fraction(volume, places=9),
            "status": status,
        },
        failure,
    )


def _verifier_pair_result(
    first_id: str,
    second_id: str,
    distance: Fraction,
    volume: Fraction,
    minimum: Fraction,
) -> tuple[dict[str, str], str | None]:
    if volume > Fraction(1, 1_000_000):
        status = "interference"
        failure: str | None = f"released:{first_id}/{second_id}:interference"
    elif distance + Fraction(1, 1_000_000) < minimum:
        status = "clearance_violation"
        failure = f"released:{first_id}/{second_id}:clearance"
    else:
        status = "passed"
        failure = None
    return (
        {
            "first_occurrence_id": first_id,
            "second_occurrence_id": second_id,
            "distance_mm": _report_fraction(distance, places=9),
            "minimum_clearance_mm": _fraction_text(minimum),
            "interference_volume_mm3": _report_fraction(volume, places=9),
            "status": status,
        },
        failure,
    )


def _compiler_region_result(
    occurrence_id: str,
    region: dict[str, Any],
    distance: Fraction,
    volume: Fraction,
) -> tuple[dict[str, Any], str | None]:
    minimum = Fraction(region["minimum_clearance_mm"])
    failure = None
    if volume > _INTERFERENCE_TOLERANCE:
        status = "interference"
        failure = f"protected:{region['region_id']}/{occurrence_id}:interference"
    elif distance + _DISTANCE_TOLERANCE < minimum:
        status = "clearance_violation"
        failure = f"protected:{region['region_id']}/{occurrence_id}:clearance"
    else:
        status = "passed"
    return (
        {
            "occurrence_id": occurrence_id,
            "region_id": region["region_id"],
            "purpose": region["purpose"],
            "source_path": region["source_path"],
            "distance_mm": _report_fraction(distance, places=9),
            "minimum_clearance_mm": region["minimum_clearance_mm"],
            "interference_volume_mm3": _report_fraction(volume, places=9),
            "evidence_id": region["evidence_id"],
            "evidence_authority": region["evidence_authority"],
            "evidence_artifact_digest": region["evidence_artifact_digest"],
            "status": status,
        },
        failure,
    )


def _verifier_region_result(
    occurrence_id: str,
    region: dict[str, Any],
    distance: Fraction,
    volume: Fraction,
) -> tuple[dict[str, Any], str | None]:
    minimum = Fraction(region["minimum_clearance_mm"])
    if volume > Fraction(1, 1_000_000):
        status = "interference"
        failure: str | None = (
            f"protected:{region['region_id']}/{occurrence_id}:interference"
        )
    elif distance + Fraction(1, 1_000_000) < minimum:
        status = "clearance_violation"
        failure = f"protected:{region['region_id']}/{occurrence_id}:clearance"
    else:
        status = "passed"
        failure = None
    return (
        {
            "occurrence_id": occurrence_id,
            "region_id": region["region_id"],
            "purpose": region["purpose"],
            "source_path": region["source_path"],
            "distance_mm": _report_fraction(distance, places=9),
            "minimum_clearance_mm": region["minimum_clearance_mm"],
            "interference_volume_mm3": _report_fraction(volume, places=9),
            "evidence_id": region["evidence_id"],
            "evidence_authority": region["evidence_authority"],
            "evidence_artifact_digest": region["evidence_artifact_digest"],
            "status": status,
        },
        failure,
    )


def _compiler_spatial_analysis(
    assembly: ReferenceSpatialAssembly, context: _SpatialContext
) -> dict[str, Any]:
    released, placements = _compiler_place_released(context)
    regions, region_evidence = _compiler_place_regions(assembly, context)
    pair_results: list[dict[str, str]] = []
    region_results: list[dict[str, Any]] = []
    failures: list[str] = []
    for first_id, second_id in itertools.combinations(sorted(released), 2):
        distance, volume = _compiler_measure_pair(
            released[first_id], released[second_id]
        )
        row, failure = _compiler_pair_result(
            first_id,
            second_id,
            distance,
            volume,
            assembly.released_clearance_for(first_id, second_id),
        )
        pair_results.append(row)
        if failure is not None:
            failures.append(failure)
    region_by_id = {item["region_id"]: item for item in region_evidence}
    for occurrence_id in sorted(released):
        for region_id in sorted(regions):
            distance, volume = _compiler_measure_pair(
                released[occurrence_id], regions[region_id]
            )
            row, failure = _compiler_region_result(
                occurrence_id, region_by_id[region_id], distance, volume
            )
            region_results.append(row)
            if failure is not None:
                failures.append(failure)
    return {
        "status": "passed" if not failures else "failed",
        "protected_occurrence_id": assembly.protected_reference.occurrence_id,
        "released_occurrence_count": len(released),
        "protected_region_count": len(regions),
        "released_pair_count": len(pair_results),
        "released_placements": placements,
        "protected_regions": region_evidence,
        "released_pair_results": pair_results,
        "protected_region_results": region_results,
        "failures": sorted(failures),
    }


def _verifier_spatial_analysis(
    assembly: ReferenceSpatialAssembly, context: _SpatialContext
) -> dict[str, Any]:
    released, placement_records = _verifier_place_released(context)
    protected, protected_records = _verifier_place_regions(assembly, context)
    replayed_pairs: list[dict[str, str]] = []
    replayed_regions: list[dict[str, Any]] = []
    failures: list[str] = []
    identifiers = sorted(released)
    for left_index in range(len(identifiers)):
        for right_index in range(left_index + 1, len(identifiers)):
            left = identifiers[left_index]
            right = identifiers[right_index]
            distance, volume = _verifier_measure_pair(released[left], released[right])
            required = _verifier_released_clearance(assembly, left, right)
            row, failure = _verifier_pair_result(
                left, right, distance, volume, required
            )
            replayed_pairs.append(row)
            if failure is not None:
                failures.append(failure)
    protected_by_id = {item["region_id"]: item for item in protected_records}
    for released_id in identifiers:
        for protected_id in sorted(protected):
            distance, volume = _verifier_measure_pair(
                released[released_id], protected[protected_id]
            )
            row, failure = _verifier_region_result(
                released_id, protected_by_id[protected_id], distance, volume
            )
            replayed_regions.append(row)
            if failure is not None:
                failures.append(failure)
    return {
        "status": "passed" if len(failures) == 0 else "failed",
        "protected_occurrence_id": assembly.protected_reference.occurrence_id,
        "released_occurrence_count": len(identifiers),
        "protected_region_count": len(protected),
        "released_pair_count": len(replayed_pairs),
        "released_placements": placement_records,
        "protected_regions": protected_records,
        "released_pair_results": replayed_pairs,
        "protected_region_results": replayed_regions,
        "failures": sorted(failures),
    }


def _authority_summary(context: _SpatialContext) -> dict[str, Any]:
    counts = {authority.value: 0 for authority in EvidenceAuthority}
    evidence = {item.evidence_id: item for item in context.reference_component.evidence}
    spatial_ids = [context.reference_component.occupied_bounds_evidence_id]
    spatial_ids.extend(
        item.evidence_id for item in context.reference_component.envelopes
    )
    for evidence_id in spatial_ids:
        counts[evidence[evidence_id].authority.value] += 1
    return {
        "protected_reference_geometry": "conservative_explicit_boxes_only",
        "protected_reference_brep_claimed": False,
        "released_component_geometry": "verified_local_release_brep",
        "spatial_result_authority": "conditional_constraint_evidence",
        "release_authority": "none",
        "protected_spatial_evidence_authority_counts": {
            key: value for key, value in sorted(counts.items()) if value
        },
    }


def _blockers(context: _SpatialContext) -> list[str]:
    values = {
        "protected-reference:no-brep-authority",
        "release:human-engineering-review-required",
        "spatial-model:conservative-primitives-only",
        *context.projection.evidence_blockers,
    }
    return sorted(values)


def _kernel_identity() -> dict[str, str]:
    return {
        "backend": "build123d-opencascade",
        "build123d_version": package_version("build123d"),
        "opencascade_distribution_version": package_version("cadquery-ocp"),
        "transform_projection": "direct-exact-basis-to-gp-trsf/0.1",
        "protected_region_model": "transformed-conservative-box-proxy/0.1",
    }


def _checks() -> list[dict[str, str]]:
    return [
        {"id": "REFERENCE-SPATIAL-ASSEMBLY-SCHEMA", "status": "passed"},
        {"id": "REFERENCE-SPATIAL-SOURCE-SNAPSHOTS", "status": "passed"},
        {"id": "REFERENCE-SPATIAL-INTERFACE-REPLAY", "status": "passed"},
        {"id": "REFERENCE-SPATIAL-PROJECTION-REPLAY", "status": "passed"},
        {"id": "REFERENCE-SPATIAL-RELEASED-BREP-REPLAY", "status": "passed"},
        {"id": "REFERENCE-SPATIAL-EXACT-PLACEMENT", "status": "passed"},
        {"id": "REFERENCE-SPATIAL-CONSERVATIVE-REGIONS", "status": "passed"},
        {"id": "REFERENCE-SPATIAL-COLLISION-CLEARANCE", "status": "passed"},
        {"id": "REFERENCE-SPATIAL-NON-RELEASE", "status": "passed"},
    ]


def _spatial_publish_fault_hook(event: str) -> None:
    """Test seam for deterministic publication-failure injection."""


@dataclass(slots=True)
class _BoundPublishFile:
    parent: _BoundDirectory
    name: str
    handle: int
    identity: tuple[int, ...]
    captured: bytes
    closed: bool = False

    @property
    def path(self) -> Path:
        return self.parent.path / self.name

    def _verify_identity(self) -> None:
        self.parent.verify_visible()
        if self.closed:
            raise IntegrityError("bound publication file is already closed")
        if self.parent.windows:
            info = _windows_info(self.handle)
            if info[1:4] != self.identity[1:4] or _windows_final_path(
                self.handle
            ) != _normal_windows_handle_path(str(self.path)):
                raise IntegrityError("bound publication file identity changed")
            return
        opened = os.fstat(self.handle)
        visible = os.stat(self.name, dir_fd=self.parent.handle, follow_symlinks=False)
        if (opened.st_dev, opened.st_ino, opened.st_mode) != (
            self.identity[0],
            self.identity[1],
            self.identity[2],
        ) or (visible.st_dev, visible.st_ino, visible.st_mode) != (
            self.identity[0],
            self.identity[1],
            self.identity[2],
        ):
            raise IntegrityError("bound publication file identity changed")

    def verify_visible(self) -> None:
        self._verify_identity()
        if self.parent.windows:
            info = _windows_info(self.handle)
            size = (info[5] << 32) | info[6]
            if (
                info[1:4] != self.identity[1:4]
                or info[4] != 1
                or size != len(self.captured)
            ):
                raise IntegrityError("bound publication file metadata changed")
            reproduced = _windows_read(self.handle, max(len(self.captured), 1))
        else:
            opened = os.fstat(self.handle)
            visible = os.stat(
                self.name, dir_fd=self.parent.handle, follow_symlinks=False
            )
            if (
                (opened.st_dev, opened.st_ino, opened.st_mode)
                != (self.identity[0], self.identity[1], self.identity[2])
                or (visible.st_dev, visible.st_ino, visible.st_mode)
                != (self.identity[0], self.identity[1], self.identity[2])
                or opened.st_nlink != 1
                or opened.st_size != len(self.captured)
            ):
                raise IntegrityError("bound publication file metadata changed")
            os.lseek(self.handle, 0, os.SEEK_SET)
            blocks = bytearray()
            while len(blocks) < len(self.captured):
                block = os.read(
                    self.handle,
                    min(1024 * 1024, len(self.captured) - len(blocks)),
                )
                if not block:
                    break
                blocks.extend(block)
            reproduced = bytes(blocks)
        if reproduced != self.captured:
            raise IntegrityError("bound publication file bytes changed")
        self.parent.verify_visible()

    def rename(self, new_name: str, *, require_bytes: bool = True) -> None:
        if require_bytes:
            self.verify_visible()
        else:
            self._verify_identity()
        old_name = self.name
        if self.parent.windows:
            _windows_rename(self.handle, self.parent, new_name)
        else:
            os.rename(
                old_name,
                new_name,
                src_dir_fd=self.parent.handle,
                dst_dir_fd=self.parent.handle,
            )
        self.name = new_name
        self._verify_identity()

    def discard_owned(self) -> None:
        self._verify_identity()
        if self.parent.windows:
            _windows_mark_delete(self.handle)
            self.closed = True
            try:
                _windows_close(self.handle)
            except OSError:
                pass
            return
        os.unlink(self.name, dir_fd=self.parent.handle)
        self.closed = True
        try:
            os.close(self.handle)
        except OSError:
            pass

    def close(self) -> None:
        if self.closed:
            return
        try:
            _windows_close(self.handle) if self.parent.windows else os.close(
                self.handle
            )
        finally:
            self.closed = True


def _unique_publish_name(parent: _BoundDirectory, target: str, label: str) -> str:
    for _ in range(128):
        candidate = f".{target}.{label}-{secrets.token_hex(12)}"
        if candidate not in parent.names():
            return candidate
    raise ExecutionError("cannot allocate a unique reference spatial staging file")


def _create_staged_publish_file(
    parent: _BoundDirectory, name: str, captured: bytes
) -> _BoundPublishFile:
    parent.verify_visible()
    handle: int | None = None
    staged: _BoundPublishFile | None = None
    try:
        if parent.windows:
            handle = _windows_open(
                parent.path / name,
                directory=False,
                create=True,
                deletable=True,
            )
            before = _windows_info(handle)
            if (
                before[0] & 0x410
                or before[4] != 1
                or (before[5] << 32) | before[6] != 0
                or _windows_final_path(handle)
                != _normal_windows_handle_path(str(parent.path / name))
            ):
                raise IntegrityError("staged bundle handle is indirect or misplaced")
            _spatial_publish_fault_hook("stage_created_before_write")
            if _windows_info(handle)[4] != 1:
                raise IntegrityError("staged bundle was hard-linked before write")
            _windows_write(handle, captured)
            after = _windows_info(handle)
            size = (after[5] << 32) | after[6]
            if after[1:4] != before[1:4] or after[4] != 1 or size != len(captured):
                raise IntegrityError("staged bundle metadata does not reproduce")
            reproduced = _windows_read(handle, max(len(captured), 1))
            identity = after
        else:
            flags = os.O_RDWR | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC
            handle = os.open(name, flags, 0o600, dir_fd=parent.handle)
            before_stat = os.fstat(handle)
            _require_posix_named_handle(
                parent.handle,
                name,
                before_stat,
                directory=False,
                error_type=IntegrityError,
                message="staged bundle handle is indirect or misplaced",
            )
            if before_stat.st_nlink != 1 or before_stat.st_size != 0:
                raise IntegrityError("staged bundle handle is indirect or misplaced")
            _spatial_publish_fault_hook("stage_created_before_write")
            if os.fstat(handle).st_nlink != 1:
                raise IntegrityError("staged bundle was hard-linked before write")
            offset = 0
            while offset < len(captured):
                offset += os.write(handle, captured[offset:])
            os.fsync(handle)
            after_stat = os.fstat(handle)
            _require_posix_named_handle(
                parent.handle,
                name,
                after_stat,
                directory=False,
                error_type=IntegrityError,
                message="staged bundle metadata does not reproduce",
            )
            if (
                (after_stat.st_dev, after_stat.st_ino, after_stat.st_mode)
                != (before_stat.st_dev, before_stat.st_ino, before_stat.st_mode)
                or after_stat.st_nlink != 1
                or after_stat.st_size != len(captured)
            ):
                raise IntegrityError("staged bundle metadata does not reproduce")
            os.lseek(handle, 0, os.SEEK_SET)
            reproduced_blocks = bytearray()
            while len(reproduced_blocks) < len(captured):
                block = os.read(
                    handle,
                    min(1024 * 1024, len(captured) - len(reproduced_blocks)),
                )
                if not block:
                    break
                reproduced_blocks.extend(block)
            reproduced = bytes(reproduced_blocks)
            identity = _stat_identity(after_stat)
        if reproduced != captured:
            raise IntegrityError("staged bundle bytes do not reproduce")
        staged = _BoundPublishFile(parent, name, handle, identity, captured)
        staged.verify_visible()
        return staged
    except BaseException:
        if handle is not None:
            temporary = staged or _BoundPublishFile(
                parent,
                name,
                handle,
                _windows_info(handle)
                if parent.windows
                else _stat_identity(os.fstat(handle)),
                b"",
            )
            try:
                temporary.discard_owned()
            except (ContrainteError, OSError):
                temporary.close()
        raise


def _open_existing_publish_file(
    parent: _BoundDirectory, name: str
) -> _BoundPublishFile:
    parent.verify_visible()
    handle: int | None = None
    success = False
    try:
        if parent.windows:
            handle = _windows_open(parent.path / name, directory=False, deletable=True)
            before = _windows_info(handle)
            size = (before[5] << 32) | before[6]
            if (
                before[0] & 0x410
                or before[4] != 1
                or size > _MAX_BUNDLE_BYTES
                or _windows_final_path(handle)
                != _normal_windows_handle_path(str(parent.path / name))
            ):
                raise InputError("prior spatial bundle is indirect or hard-linked")
            captured = _windows_read(handle, _MAX_BUNDLE_BYTES)
            after = _windows_info(handle)
            identity = after
        else:
            handle = os.open(
                name,
                os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC,
                dir_fd=parent.handle,
            )
            before_stat = os.fstat(handle)
            _require_posix_named_handle(
                parent.handle,
                name,
                before_stat,
                directory=False,
                error_type=InputError,
                message="prior spatial bundle is indirect or hard-linked",
            )
            if (
                not stat.S_ISREG(before_stat.st_mode)
                or before_stat.st_nlink != 1
                or before_stat.st_size > _MAX_BUNDLE_BYTES
            ):
                raise InputError("prior spatial bundle is indirect or hard-linked")
            captured_blocks = bytearray()
            while True:
                block = os.read(
                    handle,
                    min(
                        1024 * 1024,
                        _MAX_BUNDLE_BYTES + 1 - len(captured_blocks),
                    ),
                )
                if not block:
                    break
                captured_blocks.extend(block)
                if len(captured_blocks) > _MAX_BUNDLE_BYTES:
                    raise InputError("prior spatial bundle exceeds its byte limit")
            captured = bytes(captured_blocks)
            after_stat = os.fstat(handle)
            identity = _stat_identity(after_stat)
            after = identity
            before = _stat_identity(before_stat)
        if before != after or len(captured) > _MAX_BUNDLE_BYTES:
            raise InputError("prior spatial bundle changed during capture")
        result = _BoundPublishFile(parent, name, handle, identity, captured)
        result.verify_visible()
        success = True
        return result
    except OSError as exc:
        raise InputError("prior spatial bundle is unavailable") from exc
    finally:
        if handle is not None and not success:
            _windows_close(handle) if parent.windows else os.close(handle)


def _reject_bound_input_collision(
    target: Path, assembly_input: _AssemblyInputSnapshot | None
) -> None:
    if assembly_input is None:
        return
    assembly_input.verify_visible()
    if os.path.normcase(os.path.abspath(target)) == os.path.normcase(
        os.path.abspath(assembly_input.path)
    ):
        raise InputError(
            "reference spatial bundle output cannot overwrite its assembly input"
        )


def _reject_bound_input_identity(
    output: _BoundPublishFile, assembly_input: _AssemblyInputSnapshot | None
) -> None:
    if assembly_input is None:
        return
    assembly_input.verify_visible()
    if output.parent.windows:
        same_identity = output.identity[1:4] == assembly_input.retained.identity[1:4]
    else:
        same_identity = output.identity[:2] == assembly_input.retained.identity[:2]
    if same_identity:
        raise InputError(
            "reference spatial bundle output aliases its retained assembly input"
        )


def _rollback_spatial_publish(
    stage: _BoundPublishFile | None,
    stage_name: str | None,
    prior: _BoundPublishFile | None,
    target_name: str,
) -> None:
    if stage is not None and stage.name == target_name:
        if stage_name is None:
            raise AssertionError("promoted staging file requires its original name")
        stage.rename(stage_name, require_bytes=False)
    if prior is not None and not prior.closed and prior.name != target_name:
        prior.rename(target_name)
        prior.verify_visible()
    if stage is not None and not stage.closed:
        stage.discard_owned()


def _publish_spatial_bundle_bound(
    destination: Path,
    target_name: str,
    captured: bytes,
    *,
    root: Path,
    source_locators: frozenset[str],
    assembly_input: _AssemblyInputSnapshot | None,
    dependency_verifier: Callable[[], None],
) -> None:
    destination_chain = _BoundDirectoryChain.open(destination, create=True)
    output = destination_chain.leaf
    stage: _BoundPublishFile | None = None
    prior: _BoundPublishFile | None = None
    stage_name: str | None = None
    committed = False
    try:
        destination_chain.verify_visible()
        dependency_verifier()
        target = output.path / target_name
        _reject_source_output_collision(target, root, source_locators)
        _reject_bound_input_collision(target, assembly_input)
        existing_names = output.names()
        if target_name in existing_names:
            prior = _open_existing_publish_file(output, target_name)
            _reject_bound_input_identity(prior, assembly_input)
        stage_name = _unique_publish_name(output, target_name, "tmp")
        _spatial_publish_fault_hook("before_stage_create")
        stage = _create_staged_publish_file(output, stage_name, captured)
        _spatial_publish_fault_hook("after_stage_write")
        stage.verify_visible()
        if assembly_input is not None:
            assembly_input.verify_visible()
        dependency_verifier()
        _spatial_publish_fault_hook("before_promotion")
        if prior is not None:
            backup_name = _unique_publish_name(output, target_name, "previous")
            prior.rename(backup_name)
            _spatial_publish_fault_hook("after_prior_backup")
        stage.verify_visible()
        stage.rename(target_name)
        _spatial_publish_fault_hook("after_stage_promotion")
        stage.verify_visible()
        if assembly_input is not None:
            assembly_input.verify_visible()
        dependency_verifier()
        _spatial_publish_fault_hook("before_backup_cleanup")
        if prior is not None:
            prior.verify_visible()
            prior.discard_owned()
        committed = True
    except BaseException:
        try:
            _rollback_spatial_publish(
                stage,
                stage_name,
                prior,
                target_name,
            )
        except BaseException as rollback_exc:
            raise IntegrityError(
                "reference spatial publication failed and rollback was incomplete"
            ) from rollback_exc
        raise
    finally:
        for item in (stage, prior):
            if item is not None and not item.closed:
                try:
                    item.close()
                except OSError:
                    if not committed:
                        raise
        try:
            destination_chain.close()
        except OSError:
            if not committed:
                raise


def _reject_source_output_collision(
    target: Path, root: Path, source_locators: frozenset[str]
) -> None:
    try:
        resolved_target = target.resolve(strict=False)
    except (OSError, RuntimeError) as exc:
        raise InputError("reference spatial bundle output path is invalid") from exc
    for locator in source_locators:
        source = root.joinpath(*PurePosixPath(locator).parts).resolve(strict=False)
        if source == resolved_target:
            raise InputError(
                "reference spatial bundle output cannot overwrite a consumed source"
            )


def load_reference_spatial_assembly(path: str | Path) -> ReferenceSpatialAssembly:
    snapshot = _open_assembly_input(path)
    try:
        return snapshot.assembly
    finally:
        snapshot.close()


def compile_reference_spatial_assembly(
    assembly: ReferenceSpatialAssembly,
    source_root: str | Path,
    output_directory: str | Path,
) -> dict[str, Any]:
    return _compile_reference_spatial_assembly(
        assembly, source_root, output_directory, assembly_input=None
    )


def compile_reference_spatial_assembly_file(
    assembly_path: str | Path,
    source_root: str | Path,
    output_directory: str | Path,
) -> dict[str, Any]:
    snapshot = _open_assembly_input(assembly_path)
    try:
        return _compile_reference_spatial_assembly(
            snapshot.assembly,
            source_root,
            output_directory,
            assembly_input=snapshot,
        )
    finally:
        snapshot.close()


def _compile_reference_spatial_assembly(
    assembly: ReferenceSpatialAssembly,
    source_root: str | Path,
    output_directory: str | Path,
    *,
    assembly_input: _AssemblyInputSnapshot | None,
) -> dict[str, Any]:
    with localcontext(_EXECUTION_CONTEXT):
        checked = _trusted_snapshot(assembly)
        target_name = f"{checked.assembly_id}.reference-spatial-assembly-bundle.json"
        if assembly_input is not None:
            assembly_input.verify_visible()
            _reject_bound_input_collision(
                Path(output_directory) / target_name, assembly_input
            )
        root = _source_root(source_root)
        tree = _BoundSourceTree.open(root)
        completed = False
        try:
            context = _load_context(checked, tree)
            analysis = _compiler_spatial_analysis(checked, context)
            if analysis["status"] != "passed":
                raise ExecutionError(
                    "reference spatial assembly constraints failed: "
                    + "; ".join(analysis["failures"])
                )
            tree.verify_visible()
            destination = Path(output_directory)
            content = {
                "schema_version": REFERENCE_SPATIAL_ASSEMBLY_BUNDLE_SCHEMA,
                "qualification": "unqualified_demonstration",
                "release_eligible": False,
                "assembly_digest": checked.assembly_digest,
                "interface_assembly_digest": digest(
                    context.interface_assembly.as_dict()
                ),
                "interface_result_digest": digest(context.interface_result.as_dict()),
                "reference_component_digest": context.reference_component.content_digest,
                "design_around_request_digest": context.request.content_digest,
                "design_around_projection_digest": context.projection.content_digest,
                "assembly": checked.as_dict(),
                "source_records": list(context.source_records),
                "authority_summary": _authority_summary(context),
                "evidence_blockers": _blockers(context),
                "kernel": _kernel_identity(),
                "analysis": analysis,
                "checks": _checks(),
                "artifacts": [],
            }
            bundle = {"digest": digest(content), "content": content}
            captured = dumps_pretty(bundle).encode("utf-8")
            if len(captured) > _MAX_BUNDLE_BYTES:
                raise ExecutionError(
                    "reference spatial assembly bundle exceeds its limit"
                )
            _publish_spatial_bundle_bound(
                destination,
                target_name,
                captured,
                root=root,
                source_locators=context.source_locators,
                assembly_input=assembly_input,
                dependency_verifier=tree.verify_visible,
            )
            completed = True
            return bundle
        finally:
            try:
                tree.close()
            except OSError:
                if not completed:
                    raise


def verify_reference_spatial_assembly_bundle(
    bundle_path: str | Path, source_root: str | Path
) -> dict[str, str | bool]:
    with localcontext(_EXECUTION_CONTEXT):
        path = Path(bundle_path)
        _require_direct_directory(
            path.parent,
            field="reference spatial bundle directory",
            error_type=IntegrityError,
        )
        captured = _read_stable_file(
            path,
            maximum_bytes=_MAX_BUNDLE_BYTES,
            field=f"reference spatial assembly bundle {path.name}",
            error_type=IntegrityError,
        )
        raw = _load_json_bytes(
            captured,
            field=f"reference spatial assembly bundle {path.name}",
            error_type=IntegrityError,
        )
        if type(raw) is not dict or set(raw) != {"digest", "content"}:
            raise IntegrityError("reference spatial bundle envelope is invalid")
        content = raw["content"]
        if type(content) is not dict or digest(content) != raw["digest"]:
            raise IntegrityError("reference spatial bundle digest mismatch")
        expected = {
            "schema_version",
            "qualification",
            "release_eligible",
            "assembly_digest",
            "interface_assembly_digest",
            "interface_result_digest",
            "reference_component_digest",
            "design_around_request_digest",
            "design_around_projection_digest",
            "assembly",
            "source_records",
            "authority_summary",
            "evidence_blockers",
            "kernel",
            "analysis",
            "checks",
            "artifacts",
        }
        if set(content) != expected:
            raise IntegrityError("reference spatial bundle content is incomplete")
        if content["schema_version"] != REFERENCE_SPATIAL_ASSEMBLY_BUNDLE_SCHEMA:
            raise IntegrityError("unsupported reference spatial bundle schema")
        if content["qualification"] != "unqualified_demonstration":
            raise IntegrityError("reference spatial qualification was promoted")
        if content["release_eligible"] is not False:
            raise IntegrityError("reference spatial bundle was promoted for release")
        if content["artifacts"] != []:
            raise IntegrityError(
                "reference spatial bundle must not publish geometry artifacts"
            )
        assembly = _trusted_snapshot(
            ReferenceSpatialAssembly.from_dict(content["assembly"])
        )
        if content["assembly_digest"] != assembly.assembly_digest:
            raise IntegrityError("embedded reference spatial assembly digest mismatch")
        root = _source_root(source_root)
        tree = _BoundSourceTree.open(root)
        try:
            context = _load_context(assembly, tree)
            semantic = {
                "interface_assembly_digest": digest(
                    context.interface_assembly.as_dict()
                ),
                "interface_result_digest": digest(context.interface_result.as_dict()),
                "reference_component_digest": context.reference_component.content_digest,
                "design_around_request_digest": context.request.content_digest,
                "design_around_projection_digest": context.projection.content_digest,
            }
            if any(content[key] != value for key, value in semantic.items()):
                raise IntegrityError(
                    "reference spatial semantic digests do not reproduce"
                )
            if content["source_records"] != list(context.source_records):
                raise IntegrityError(
                    "reference spatial source records do not reproduce"
                )
            analysis = _verifier_spatial_analysis(assembly, context)
            if analysis["status"] != "passed" or analysis != content["analysis"]:
                raise IntegrityError(
                    "reference spatial analysis does not independently reproduce"
                )
            if content["authority_summary"] != _authority_summary(context):
                raise IntegrityError("reference spatial authority summary changed")
            if content["evidence_blockers"] != _blockers(context):
                raise IntegrityError("reference spatial evidence blockers changed")
            if content["kernel"] != _kernel_identity():
                raise IntegrityError("reference spatial kernel identity changed")
            if content["checks"] != _checks():
                raise IntegrityError("reference spatial checks are incomplete or false")
            tree.verify_visible()
            return {
                "status": "verified",
                "bundle_digest": raw["digest"],
                "assembly_digest": assembly.assembly_digest,
                "release_eligible": False,
            }
        finally:
            tree.close()
