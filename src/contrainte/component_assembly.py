from __future__ import annotations

import copy
import hashlib
import itertools
import math
import os
import re
import stat
import tempfile
import unicodedata
from dataclasses import dataclass
from decimal import ROUND_HALF_EVEN, Context, Decimal, localcontext
from fractions import Fraction
from pathlib import Path, PurePosixPath
from typing import Any

from .artifacts import package_version
from .canonical import decimal_text, digest, dumps_pretty, loads_strict
from .component import COMPONENT_SCHEMA_V3, ArtifactRole, ComponentManifest
from .errors import ExecutionError, InputError, IntegrityError
from .exact_transform import ExactRigidTransform
from .geometry import normalize_step_occurrence_identifiers
from .interface_assembly import (
    InterfaceAssembly,
    InterfaceAssemblyResult,
    SolveStatus,
    verify_interface_assembly_result,
)
from .release import reproduce_local_component_shape

COMPONENT_ASSEMBLY_SCHEMA = "contrainte.component-assembly/0.1"
COMPONENT_ASSEMBLY_BUNDLE_SCHEMA = "contrainte.component-assembly-bundle/0.1"
_SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_SHA256 = re.compile(r"^sha256:[0-9a-f]{64}$")
_RATIONAL = re.compile(r"^(?:0|[1-9][0-9]*)(?:/[1-9][0-9]*)?$")
_LOCATOR = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/-]*$")
_WINDOWS_RESERVED = {
    "CON",
    "PRN",
    "AUX",
    "NUL",
    *(f"COM{index}" for index in range(1, 10)),
    *(f"LPT{index}" for index in range(1, 10)),
}
_MAX_SOURCE_BYTES = 4 * 1024 * 1024
_MAX_RELEASE_ARTIFACT_BYTES = 64 * 1024 * 1024
_MAX_RELEASE_CHAIN_BYTES = 128 * 1024 * 1024
_MAX_RELEASE_ARTIFACTS = 128
_MAX_OUTPUT_ARTIFACT_BYTES = 64 * 1024 * 1024
_MAX_COMPONENTS = 64
_MAX_PAIR_RULES = 2016
_INTERFERENCE_TOLERANCE = Fraction(1, 1_000_000)
_DISTANCE_TOLERANCE = Fraction(1, 1_000_000)
_MATRIX_TOLERANCE = Fraction(1, 1_000_000_000_000)
_PROJECTION_REPORT_PLACES = 18
_MEASUREMENT_REPORT_PLACES = 9


def _closed_decimal_context() -> Context:
    context = Context(
        prec=2048,
        rounding=ROUND_HALF_EVEN,
        Emin=-999999,
        Emax=999999,
        capitals=1,
        clamp=0,
    )
    for signal in context.traps:
        context.traps[signal] = False
    return context


_REPORT_CONTEXT = _closed_decimal_context()
_EXECUTION_CONTEXT = Context(
    prec=28,
    rounding=ROUND_HALF_EVEN,
    Emin=-999999,
    Emax=999999,
    capitals=1,
    clamp=0,
)
_REPORT_QUANTA = {
    _PROJECTION_REPORT_PLACES: Decimal("0.000000000000000001"),
    _MEASUREMENT_REPORT_PLACES: Decimal("0.000000001"),
}


def _exact_keys(raw: Any, expected: set[str], field: str) -> dict[str, Any]:
    if type(raw) is not dict or any(type(key) is not str for key in raw):
        raise InputError(f"{field} must be a plain JSON object with string keys")
    if set(raw) != expected:
        raise InputError(f"{field} must contain exactly {', '.join(sorted(expected))}")
    return raw


def _string(value: Any, field: str, *, identifier: bool = False) -> str:
    if type(value) is not str or not value:
        raise InputError(f"{field} must be a non-empty string")
    if len(value) > 512 or any(
        unicodedata.category(character) in {"Cc", "Cf", "Cs"} for character in value
    ):
        raise InputError(f"{field} contains unsupported text")
    if identifier and not _SAFE_ID.fullmatch(value):
        raise InputError(f"{field} must be a safe ASCII identifier")
    return value


def _sha256(value: Any, field: str) -> str:
    if type(value) is not str or not _SHA256.fullmatch(value):
        raise InputError(f"{field} must be a lowercase sha256 digest")
    return value


def _fraction(value: Any, field: str) -> Fraction:
    if type(value) is not str or len(value) > 128 or not _RATIONAL.fullmatch(value):
        raise InputError(f"{field} must be a canonical non-negative rational string")
    numerator, separator, denominator = value.partition("/")
    parsed = Fraction(int(numerator), int(denominator) if separator else 1)
    if _fraction_text(parsed) != value:
        raise InputError(f"{field} must be reduced and canonical")
    return parsed


def _fraction_text(value: Fraction) -> str:
    return (
        str(value.numerator)
        if value.denominator == 1
        else f"{value.numerator}/{value.denominator}"
    )


def _kernel_fraction(
    value: Any,
    *,
    error_type: type[ExecutionError | IntegrityError],
    message: str,
) -> Fraction:
    try:
        binary_value = float(value)
    except (OverflowError, TypeError, ValueError) as exc:
        raise error_type(message) from exc
    if not math.isfinite(binary_value):
        raise error_type(message)
    return Fraction.from_float(binary_value)


def _report_fraction(value: Fraction, *, places: int) -> str:
    quantum = _REPORT_QUANTA[places]
    with localcontext(_REPORT_CONTEXT):
        rendered = (Decimal(value.numerator) / Decimal(value.denominator)).quantize(
            quantum
        )
    return decimal_text(rendered)


def _locator(value: Any, field: str) -> str:
    if (
        type(value) is not str
        or not value
        or len(value) > 240
        or not _LOCATOR.fullmatch(value)
        or "\\" in value
    ):
        raise InputError(f"{field} must be a bounded relative POSIX file locator")
    path = PurePosixPath(value)
    if path.is_absolute() or len(path.parts) > 16:
        raise InputError(f"{field} must remain within the source root")
    for part in path.parts:
        stem = part.split(".", 1)[0].upper()
        if (
            part in {"", ".", ".."}
            or part.endswith((".", " "))
            or ":" in part
            or stem in _WINDOWS_RESERVED
        ):
            raise InputError(f"{field} contains an unsafe path segment")
    return path.as_posix()


def _sha256_bytes(value: bytes) -> str:
    return f"sha256:{hashlib.sha256(value).hexdigest()}"


def _stat_identity(value: os.stat_result) -> tuple[int, ...]:
    return (
        value.st_dev,
        value.st_ino,
        value.st_mode,
        value.st_size,
        value.st_mtime_ns,
        value.st_nlink,
    )


def _read_bounded_chunks(handle: Any, maximum_bytes: int) -> bytes:
    captured = bytearray()
    while True:
        block = handle.read(min(1024 * 1024, maximum_bytes + 1 - len(captured)))
        if not block:
            return bytes(captured)
        captured.extend(block)
        if len(captured) > maximum_bytes:
            raise InputError(
                "file changed beyond its declared size limit while reading"
            )


def _read_stable_file(
    path: Path,
    *,
    maximum_bytes: int,
    field: str,
    expected_digest: str | None = None,
    error_type: type[InputError | IntegrityError] = InputError,
) -> bytes:
    """Capture one bounded, direct-file snapshot with continuity evidence."""

    try:
        before = path.lstat()
    except OSError as exc:
        raise error_type(f"{field} is unavailable: {exc}") from exc
    if stat.S_ISLNK(before.st_mode) or _is_link_or_reparse(path):
        raise error_type(f"{field} cannot be a link or reparse point")
    if not stat.S_ISREG(before.st_mode):
        raise error_type(f"{field} must be a regular file")
    if before.st_nlink != 1:
        raise error_type(f"{field} cannot be a hard-linked file")
    if before.st_size > maximum_bytes:
        raise error_type(f"{field} exceeds its byte limit")
    try:
        with path.open("rb") as handle:
            opened = os.fstat(handle.fileno())
            if _stat_identity(opened) != _stat_identity(before):
                raise error_type(f"{field} changed before it could be read")
            try:
                captured = _read_bounded_chunks(handle, maximum_bytes)
            except InputError as exc:
                raise error_type(f"{field} exceeds its byte limit") from exc
            after_handle = os.fstat(handle.fileno())
        after_path = path.lstat()
    except error_type:
        raise
    except OSError as exc:
        raise error_type(f"cannot read {field}: {exc}") from exc
    identity = _stat_identity(before)
    if (
        _stat_identity(after_handle) != identity
        or _stat_identity(after_path) != identity
    ):
        raise error_type(f"{field} changed while it was being read")
    if len(captured) != before.st_size:
        raise error_type(f"{field} size changed while it was being read")
    actual_digest = _sha256_bytes(captured)
    if expected_digest is not None and actual_digest != expected_digest:
        raise IntegrityError(f"{field} digest mismatch")
    return captured


@dataclass(frozen=True, slots=True)
class SourceFileRef:
    locator: str
    file_digest: str

    @classmethod
    def from_dict(cls, raw: Any, *, field: str) -> SourceFileRef:
        values = _exact_keys(raw, {"locator", "file_digest"}, field)
        return cls(
            locator=_locator(values["locator"], f"{field}.locator"),
            file_digest=_sha256(values["file_digest"], f"{field}.file_digest"),
        )

    def as_dict(self) -> dict[str, str]:
        return {"locator": self.locator, "file_digest": self.file_digest}


@dataclass(frozen=True, slots=True)
class ComponentBinding:
    occurrence_id: str
    manifest_locator: str
    manifest_file_digest: str
    manifest_digest: str

    @classmethod
    def from_dict(cls, raw: Any, *, field: str) -> ComponentBinding:
        values = _exact_keys(
            raw,
            {
                "occurrence_id",
                "manifest_locator",
                "manifest_file_digest",
                "manifest_digest",
            },
            field,
        )
        return cls(
            occurrence_id=_string(
                values["occurrence_id"], f"{field}.occurrence_id", identifier=True
            ),
            manifest_locator=_locator(
                values["manifest_locator"], f"{field}.manifest_locator"
            ),
            manifest_file_digest=_sha256(
                values["manifest_file_digest"], f"{field}.manifest_file_digest"
            ),
            manifest_digest=_sha256(
                values["manifest_digest"], f"{field}.manifest_digest"
            ),
        )

    def as_dict(self) -> dict[str, str]:
        return {
            "occurrence_id": self.occurrence_id,
            "manifest_locator": self.manifest_locator,
            "manifest_file_digest": self.manifest_file_digest,
            "manifest_digest": self.manifest_digest,
        }


@dataclass(frozen=True, slots=True)
class ComponentPairClearance:
    first_occurrence_id: str
    second_occurrence_id: str
    minimum_clearance_mm: Fraction

    @classmethod
    def from_dict(cls, raw: Any, *, field: str) -> ComponentPairClearance:
        values = _exact_keys(
            raw,
            {
                "first_occurrence_id",
                "second_occurrence_id",
                "minimum_clearance_mm",
            },
            field,
        )
        first = _string(
            values["first_occurrence_id"],
            f"{field}.first_occurrence_id",
            identifier=True,
        )
        second = _string(
            values["second_occurrence_id"],
            f"{field}.second_occurrence_id",
            identifier=True,
        )
        if first >= second:
            raise InputError(f"{field} occurrence identifiers must be sorted")
        return cls(
            first_occurrence_id=first,
            second_occurrence_id=second,
            minimum_clearance_mm=_fraction(
                values["minimum_clearance_mm"], f"{field}.minimum_clearance_mm"
            ),
        )

    @property
    def pair(self) -> tuple[str, str]:
        return self.first_occurrence_id, self.second_occurrence_id

    def as_dict(self) -> dict[str, str]:
        return {
            "first_occurrence_id": self.first_occurrence_id,
            "second_occurrence_id": self.second_occurrence_id,
            "minimum_clearance_mm": _fraction_text(self.minimum_clearance_mm),
        }


@dataclass(frozen=True, slots=True)
class ComponentAssembly:
    assembly_id: str
    revision: str
    title: str
    interface_assembly: SourceFileRef
    interface_result: SourceFileRef
    component_bindings: tuple[ComponentBinding, ...]
    default_minimum_clearance_mm: Fraction
    pair_clearances: tuple[ComponentPairClearance, ...]
    schema_version: str = COMPONENT_ASSEMBLY_SCHEMA

    def __init_subclass__(cls, **kwargs: Any) -> None:
        raise TypeError("ComponentAssembly may not be subclassed")

    @classmethod
    def from_dict(cls, raw: Any) -> ComponentAssembly:
        values = _exact_keys(
            raw,
            {
                "schema_version",
                "assembly_id",
                "revision",
                "title",
                "interface_assembly",
                "interface_result",
                "component_bindings",
                "default_minimum_clearance_mm",
                "pair_clearances",
            },
            "component_assembly",
        )
        if (
            type(values["schema_version"]) is not str
            or values["schema_version"] != COMPONENT_ASSEMBLY_SCHEMA
        ):
            raise InputError(
                f"component_assembly.schema_version must be {COMPONENT_ASSEMBLY_SCHEMA!r}"
            )
        bindings_raw = values["component_bindings"]
        rules_raw = values["pair_clearances"]
        if (
            type(bindings_raw) is not list
            or not 2 <= len(bindings_raw) <= _MAX_COMPONENTS
        ):
            raise InputError(
                "component_assembly.component_bindings must contain 2 to 64 items"
            )
        if type(rules_raw) is not list or len(rules_raw) > _MAX_PAIR_RULES:
            raise InputError("component_assembly.pair_clearances exceeds its limit")
        bindings = tuple(
            ComponentBinding.from_dict(
                item, field=f"component_assembly.component_bindings[{index}]"
            )
            for index, item in enumerate(bindings_raw)
        )
        binding_ids = tuple(item.occurrence_id for item in bindings)
        if binding_ids != tuple(sorted(set(binding_ids))):
            raise InputError(
                "component bindings must be sorted and unique by occurrence_id"
            )
        rules = tuple(
            ComponentPairClearance.from_dict(
                item, field=f"component_assembly.pair_clearances[{index}]"
            )
            for index, item in enumerate(rules_raw)
        )
        pairs = tuple(item.pair for item in rules)
        if pairs != tuple(sorted(set(pairs))):
            raise InputError("pair clearances must be sorted and unique")
        known = set(binding_ids)
        if any(first not in known or second not in known for first, second in pairs):
            raise InputError("pair clearances reference unknown component bindings")
        return cls(
            assembly_id=_string(
                values["assembly_id"], "component_assembly.assembly_id", identifier=True
            ),
            revision=_string(values["revision"], "component_assembly.revision"),
            title=_string(values["title"], "component_assembly.title"),
            interface_assembly=SourceFileRef.from_dict(
                values["interface_assembly"],
                field="component_assembly.interface_assembly",
            ),
            interface_result=SourceFileRef.from_dict(
                values["interface_result"], field="component_assembly.interface_result"
            ),
            component_bindings=bindings,
            default_minimum_clearance_mm=_fraction(
                values["default_minimum_clearance_mm"],
                "component_assembly.default_minimum_clearance_mm",
            ),
            pair_clearances=rules,
        )

    @property
    def assembly_digest(self) -> str:
        return digest(self.as_dict())

    def clearance_for(self, first: str, second: str) -> Fraction:
        pair = tuple(sorted((first, second)))
        rule = next((item for item in self.pair_clearances if item.pair == pair), None)
        return (
            rule.minimum_clearance_mm
            if rule is not None
            else self.default_minimum_clearance_mm
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "assembly_id": self.assembly_id,
            "revision": self.revision,
            "title": self.title,
            "interface_assembly": self.interface_assembly.as_dict(),
            "interface_result": self.interface_result.as_dict(),
            "component_bindings": [item.as_dict() for item in self.component_bindings],
            "default_minimum_clearance_mm": _fraction_text(
                self.default_minimum_clearance_mm
            ),
            "pair_clearances": [item.as_dict() for item in self.pair_clearances],
        }


def _trusted_fraction(value: Any, field: str) -> str:
    if (
        type(value) is not Fraction
        or value < 0
        or value.numerator.bit_length() > 512
        or value.denominator.bit_length() > 512
    ):
        raise InputError(f"{field} must be a bounded non-negative Fraction")
    text = _fraction_text(value)
    if len(text) > 128:
        raise InputError(f"{field} exceeds its exact scalar limit")
    return text


def _trusted_component_assembly_snapshot(
    assembly: Any,
) -> ComponentAssembly:
    """Validate bounded dataclass state before invoking any user-overridable method."""

    if type(assembly) is not ComponentAssembly:
        raise InputError("component assembly must be an exact ComponentAssembly value")
    if type(assembly.interface_assembly) is not SourceFileRef:
        raise InputError("component_assembly.interface_assembly has an invalid type")
    if type(assembly.interface_result) is not SourceFileRef:
        raise InputError("component_assembly.interface_result has an invalid type")
    if (
        type(assembly.component_bindings) is not tuple
        or not 2 <= len(assembly.component_bindings) <= _MAX_COMPONENTS
    ):
        raise InputError(
            "component_assembly.component_bindings must be a tuple of 2 to 64 items"
        )
    if (
        type(assembly.pair_clearances) is not tuple
        or len(assembly.pair_clearances) > _MAX_PAIR_RULES
    ):
        raise InputError("component_assembly.pair_clearances exceeds its limit")
    schema = _string(assembly.schema_version, "component_assembly.schema_version")
    if schema != COMPONENT_ASSEMBLY_SCHEMA:
        raise InputError(
            f"component_assembly.schema_version must be {COMPONENT_ASSEMBLY_SCHEMA!r}"
        )
    document: dict[str, Any] = {
        "schema_version": schema,
        "assembly_id": _string(
            assembly.assembly_id, "component_assembly.assembly_id", identifier=True
        ),
        "revision": _string(assembly.revision, "component_assembly.revision"),
        "title": _string(assembly.title, "component_assembly.title"),
        "interface_assembly": {
            "locator": _locator(
                assembly.interface_assembly.locator,
                "component_assembly.interface_assembly.locator",
            ),
            "file_digest": _sha256(
                assembly.interface_assembly.file_digest,
                "component_assembly.interface_assembly.file_digest",
            ),
        },
        "interface_result": {
            "locator": _locator(
                assembly.interface_result.locator,
                "component_assembly.interface_result.locator",
            ),
            "file_digest": _sha256(
                assembly.interface_result.file_digest,
                "component_assembly.interface_result.file_digest",
            ),
        },
        "component_bindings": [],
        "default_minimum_clearance_mm": _trusted_fraction(
            assembly.default_minimum_clearance_mm,
            "component_assembly.default_minimum_clearance_mm",
        ),
        "pair_clearances": [],
    }
    for index, binding in enumerate(assembly.component_bindings):
        field = f"component_assembly.component_bindings[{index}]"
        if type(binding) is not ComponentBinding:
            raise InputError(f"{field} has an invalid type")
        document["component_bindings"].append(
            {
                "occurrence_id": _string(
                    binding.occurrence_id,
                    f"{field}.occurrence_id",
                    identifier=True,
                ),
                "manifest_locator": _locator(
                    binding.manifest_locator, f"{field}.manifest_locator"
                ),
                "manifest_file_digest": _sha256(
                    binding.manifest_file_digest,
                    f"{field}.manifest_file_digest",
                ),
                "manifest_digest": _sha256(
                    binding.manifest_digest, f"{field}.manifest_digest"
                ),
            }
        )
    for index, rule in enumerate(assembly.pair_clearances):
        field = f"component_assembly.pair_clearances[{index}]"
        if type(rule) is not ComponentPairClearance:
            raise InputError(f"{field} has an invalid type")
        document["pair_clearances"].append(
            {
                "first_occurrence_id": _string(
                    rule.first_occurrence_id,
                    f"{field}.first_occurrence_id",
                    identifier=True,
                ),
                "second_occurrence_id": _string(
                    rule.second_occurrence_id,
                    f"{field}.second_occurrence_id",
                    identifier=True,
                ),
                "minimum_clearance_mm": _trusted_fraction(
                    rule.minimum_clearance_mm, f"{field}.minimum_clearance_mm"
                ),
            }
        )
    return ComponentAssembly.from_dict(document)


@dataclass(frozen=True, slots=True)
class _LoadedContext:
    interface_assembly: InterfaceAssembly
    interface_result: InterfaceAssemblyResult
    shapes: dict[str, Any]
    source_records: tuple[dict[str, str], ...]


def _artifact_specs(assembly_id: str) -> tuple[tuple[str, str, str], ...]:
    return (
        (f"{assembly_id}.step", "model/step", "exact_component_assembly"),
        (f"{assembly_id}.stl", "model/stl", "component_assembly_mesh"),
    )


def _descriptor(
    name: str, media_type: str, role: str, captured: bytes
) -> dict[str, Any]:
    return {
        "path": name,
        "media_type": media_type,
        "role": role,
        "digest": _sha256_bytes(captured),
        "size_bytes": len(captured),
    }


def _require_direct_directory(
    path: Path, *, field: str, error_type: type[InputError | IntegrityError]
) -> None:
    if _is_link_or_reparse(path):
        raise error_type(f"{field} cannot be a link or reparse point")
    try:
        metadata = path.lstat()
    except OSError as exc:
        raise error_type(f"{field} is unavailable: {exc}") from exc
    if not stat.S_ISDIR(metadata.st_mode):
        raise error_type(f"{field} must be a direct directory")


def _prepare_output_file(path: Path, field: str) -> None:
    try:
        metadata = path.lstat()
    except FileNotFoundError:
        return
    except OSError as exc:
        raise InputError(f"cannot inspect {field}: {exc}") from exc
    if stat.S_ISLNK(metadata.st_mode) or _is_link_or_reparse(path):
        raise InputError(f"{field} cannot be a link or reparse point")
    if not stat.S_ISREG(metadata.st_mode):
        raise InputError(f"{field} must be a regular file")
    if metadata.st_nlink != 1:
        raise InputError(f"{field} cannot be a hard-linked file")


def _render_geometry_artifacts(
    compound: Any, assembly_id: str
) -> tuple[list[dict[str, Any]], dict[str, bytes]]:
    try:
        from build123d import export_step, export_stl
    except ImportError as exc:
        raise ExecutionError(
            "the CAD backend is not installed; install Contrainte with the 'cad' extra"
        ) from exc
    descriptors: list[dict[str, Any]] = []
    captured: dict[str, bytes] = {}
    with tempfile.TemporaryDirectory(prefix="contrainte-assembly-render-") as directory:
        render_root = Path(directory)
        step_name, step_media, step_role = _artifact_specs(assembly_id)[0]
        step_path = render_root / step_name
        if not export_step(compound, step_path, timestamp="2000-01-01T00:00:00"):
            raise ExecutionError(
                "Open CASCADE failed to export the component assembly STEP"
            )
        step_metadata = step_path.lstat()
        if step_metadata.st_size > _MAX_OUTPUT_ARTIFACT_BYTES:
            raise ExecutionError("component assembly STEP exceeds its byte limit")
        normalize_step_occurrence_identifiers(step_path)
        step_bytes = _read_stable_file(
            step_path,
            maximum_bytes=_MAX_OUTPUT_ARTIFACT_BYTES,
            field="rendered component assembly STEP",
        )
        descriptors.append(_descriptor(step_name, step_media, step_role, step_bytes))
        captured[step_name] = step_bytes

        stl_name, stl_media, stl_role = _artifact_specs(assembly_id)[1]
        stl_path = render_root / stl_name
        if not export_stl(compound, stl_path, tolerance=0.01, angular_tolerance=0.1):
            raise ExecutionError(
                "Open CASCADE failed to export the component assembly STL"
            )
        stl_bytes = _read_stable_file(
            stl_path,
            maximum_bytes=_MAX_OUTPUT_ARTIFACT_BYTES,
            field="rendered component assembly STL",
        )
        descriptors.append(_descriptor(stl_name, stl_media, stl_role, stl_bytes))
        captured[stl_name] = stl_bytes
    return descriptors, captured


def _publish_captured_file(path: Path, captured: bytes, field: str) -> None:
    _prepare_output_file(path, field)
    try:
        path.write_bytes(captured)
    except OSError as exc:
        raise InputError(f"cannot write {field}: {exc}") from exc
    reproduced = _read_stable_file(
        path,
        maximum_bytes=max(len(captured), 1),
        field=field,
    )
    if reproduced != captured:
        raise IntegrityError(f"{field} changed while it was published")


def _load_declared_artifacts(
    directory: Path, raw: Any, assembly_id: str
) -> tuple[list[dict[str, Any]], dict[str, bytes]]:
    specs = _artifact_specs(assembly_id)
    if type(raw) is not list or len(raw) != len(specs):
        raise IntegrityError("bundle artifact set is incomplete or contains extras")
    descriptors: dict[str, dict[str, Any]] = {}
    required = {"path", "media_type", "role", "digest", "size_bytes"}
    for index, item in enumerate(raw):
        if type(item) is not dict or set(item) != required:
            raise IntegrityError(f"bundle artifact[{index}] has invalid fields")
        name = item["path"]
        if type(name) is not str or Path(name).name != name or name in {"", ".", ".."}:
            raise IntegrityError(f"bundle artifact[{index}].path is invalid")
        if name in descriptors:
            raise IntegrityError(f"bundle artifact path is duplicated: {name}")
        if type(item["media_type"]) is not str or type(item["role"]) is not str:
            raise IntegrityError(f"bundle artifact metadata is invalid: {name}")
        if type(item["digest"]) is not str or not _SHA256.fullmatch(item["digest"]):
            raise IntegrityError(f"bundle artifact digest is invalid: {name}")
        if (
            type(item["size_bytes"]) is not int
            or item["size_bytes"] < 0
            or item["size_bytes"] > _MAX_OUTPUT_ARTIFACT_BYTES
        ):
            raise IntegrityError(f"bundle artifact size is invalid: {name}")
        descriptors[name] = item
    expected = {name: (media, role) for name, media, role in specs}
    if set(descriptors) != set(expected):
        raise IntegrityError("bundle artifact paths do not match the schema contract")
    ordered: list[dict[str, Any]] = []
    captured: dict[str, bytes] = {}
    for name, media_type, role in specs:
        item = descriptors[name]
        if item["media_type"] != media_type or item["role"] != role:
            raise IntegrityError(f"bundle artifact contract mismatch: {name}")
        try:
            if (directory / name).lstat().st_size != item["size_bytes"]:
                raise IntegrityError(f"bundle artifact size mismatch: {name}")
        except FileNotFoundError as exc:
            raise IntegrityError(f"bundle artifact is missing: {name}") from exc
        value = _read_stable_file(
            directory / name,
            maximum_bytes=_MAX_OUTPUT_ARTIFACT_BYTES,
            field=f"bundle artifact {name}",
            expected_digest=item["digest"],
            error_type=IntegrityError,
        )
        if len(value) != item["size_bytes"]:
            raise IntegrityError(f"bundle artifact size mismatch: {name}")
        ordered.append(item)
        captured[name] = value
    return ordered, captured


def load_component_assembly(path: str | Path) -> ComponentAssembly:
    source = Path(path)
    raw = _read_stable_file(
        source,
        maximum_bytes=_MAX_SOURCE_BYTES,
        field=f"component assembly {source}",
    )
    return ComponentAssembly.from_dict(loads_strict(raw))


def compile_component_assembly(
    assembly: ComponentAssembly,
    source_root: str | Path,
    output_directory: str | Path,
) -> dict[str, Any]:
    with localcontext(_EXECUTION_CONTEXT):
        return _compile_component_assembly_closed(
            assembly, source_root, output_directory
        )


def _compile_component_assembly_closed(
    assembly: ComponentAssembly,
    source_root: str | Path,
    output_directory: str | Path,
) -> dict[str, Any]:
    assembly = _trusted_component_assembly_snapshot(assembly)
    context = _load_context(assembly, source_root)
    analysis, compound = _compile_analysis(assembly, context)
    if analysis["status"] != "passed":
        raise ExecutionError(
            "component assembly verification failed: " + "; ".join(analysis["failures"])
        )
    destination = Path(output_directory)
    if destination.exists() and _is_link_or_reparse(destination):
        raise InputError(
            "component assembly output directory cannot be a link or reparse point"
        )
    destination.mkdir(parents=True, exist_ok=True)
    _require_direct_directory(
        destination, field="component assembly output directory", error_type=InputError
    )
    artifacts, rendered = _render_geometry_artifacts(compound, assembly.assembly_id)
    for name, _, _ in _artifact_specs(assembly.assembly_id):
        _publish_captured_file(
            destination / name,
            rendered[name],
            f"component assembly output artifact {name}",
        )
    content = {
        "schema_version": COMPONENT_ASSEMBLY_BUNDLE_SCHEMA,
        "qualification": "unqualified_demonstration",
        "component_assembly_digest": assembly.assembly_digest,
        "interface_assembly_digest": digest(context.interface_assembly.as_dict()),
        "interface_result_digest": digest(context.interface_result.as_dict()),
        "component_assembly": assembly.as_dict(),
        "source_records": list(context.source_records),
        "kernel": _kernel_identity(),
        "analysis": analysis,
        "checks": _checks(),
        "artifacts": artifacts,
    }
    bundle = {"digest": digest(content), "content": content}
    bundle_path = destination / f"{assembly.assembly_id}.component-assembly-bundle.json"
    bundle_bytes = dumps_pretty(bundle).encode("utf-8")
    if len(bundle_bytes) > _MAX_SOURCE_BYTES:
        raise ExecutionError("component assembly bundle exceeds its byte limit")
    _publish_captured_file(
        bundle_path, bundle_bytes, "component assembly bundle output"
    )
    return bundle


def verify_component_assembly_bundle(
    bundle_path: str | Path, source_root: str | Path
) -> dict[str, str]:
    with localcontext(_EXECUTION_CONTEXT):
        return _verify_component_assembly_bundle_closed(bundle_path, source_root)


def _verify_component_assembly_bundle_closed(
    bundle_path: str | Path, source_root: str | Path
) -> dict[str, str]:
    path = Path(bundle_path)
    _require_direct_directory(
        path.parent,
        field="component assembly bundle directory",
        error_type=IntegrityError,
    )
    raw = _read_stable_file(
        path,
        maximum_bytes=_MAX_SOURCE_BYTES,
        field=f"component assembly bundle {path.name}",
        error_type=IntegrityError,
    )
    bundle = loads_strict(raw)
    if type(bundle) is not dict or set(bundle) != {"digest", "content"}:
        raise IntegrityError("component assembly bundle envelope is invalid")
    content = bundle["content"]
    if type(content) is not dict or digest(content) != bundle["digest"]:
        raise IntegrityError("component assembly bundle digest mismatch")
    expected_fields = {
        "schema_version",
        "qualification",
        "component_assembly_digest",
        "interface_assembly_digest",
        "interface_result_digest",
        "component_assembly",
        "source_records",
        "kernel",
        "analysis",
        "checks",
        "artifacts",
    }
    if set(content) != expected_fields:
        raise IntegrityError(
            "component assembly bundle content is incomplete or unsupported"
        )
    if content["schema_version"] != COMPONENT_ASSEMBLY_BUNDLE_SCHEMA:
        raise IntegrityError("unsupported component assembly bundle schema")
    if content["qualification"] != "unqualified_demonstration":
        raise IntegrityError("component assembly qualification was promoted")
    assembly = ComponentAssembly.from_dict(content["component_assembly"])
    assembly = _trusted_component_assembly_snapshot(assembly)
    if content["component_assembly_digest"] != assembly.assembly_digest:
        raise IntegrityError("embedded component assembly digest does not reproduce")
    context = _load_context(assembly, source_root)
    if content["interface_assembly_digest"] != digest(
        context.interface_assembly.as_dict()
    ):
        raise IntegrityError("interface assembly semantic digest does not reproduce")
    if content["interface_result_digest"] != digest(context.interface_result.as_dict()):
        raise IntegrityError("interface result semantic digest does not reproduce")
    if content["source_records"] != list(context.source_records):
        raise IntegrityError("component source records do not reproduce")
    analysis, compound = _verification_analysis(assembly, context)
    if analysis != content["analysis"] or analysis["status"] != "passed":
        raise IntegrityError(
            "component assembly analysis does not independently reproduce"
        )
    if content["kernel"] != _kernel_identity():
        raise IntegrityError("component assembly kernel identity changed")
    if content["checks"] != _checks():
        raise IntegrityError("component assembly checks are incomplete or false")
    declared, published = _load_declared_artifacts(
        path.parent, content["artifacts"], assembly.assembly_id
    )
    reproduced, regenerated = _render_geometry_artifacts(compound, assembly.assembly_id)
    if reproduced != declared:
        raise IntegrityError("bundle artifacts do not reproduce from rebuilt geometry")
    for name, _, _ in _artifact_specs(assembly.assembly_id):
        if regenerated[name] != published[name]:
            raise IntegrityError(
                f"bundle artifact bytes do not reproduce from rebuilt geometry: {name}"
            )
    return {
        "status": "verified",
        "bundle_digest": bundle["digest"],
        "component_assembly_digest": assembly.assembly_digest,
        "interface_result_digest": content["interface_result_digest"],
    }


def _load_context(
    assembly: ComponentAssembly, source_root: str | Path
) -> _LoadedContext:
    root = _source_root(source_root)
    interface_path = _resolve_source_file(
        root, assembly.interface_assembly.locator, "interface_assembly"
    )
    result_path = _resolve_source_file(
        root, assembly.interface_result.locator, "interface_result"
    )
    interface_bytes = _read_stable_file(
        interface_path,
        maximum_bytes=_MAX_SOURCE_BYTES,
        field="interface assembly source file",
        expected_digest=assembly.interface_assembly.file_digest,
    )
    result_bytes = _read_stable_file(
        result_path,
        maximum_bytes=_MAX_SOURCE_BYTES,
        field="interface result source file",
        expected_digest=assembly.interface_result.file_digest,
    )
    interface = InterfaceAssembly.from_dict(loads_strict(interface_bytes))
    result = InterfaceAssemblyResult.from_dict(loads_strict(result_bytes))
    if result.status is not SolveStatus.SOLVED:
        raise InputError("component assembly requires a solved interface result")
    if not verify_interface_assembly_result(interface, result):
        raise IntegrityError(
            "interface assembly result does not independently reproduce"
        )
    occurrence_index = {item.occurrence_id: item for item in interface.occurrences}
    binding_ids = tuple(item.occurrence_id for item in assembly.component_bindings)
    if binding_ids != tuple(sorted(occurrence_index)):
        raise InputError("component bindings must exactly cover interface occurrences")
    shapes: dict[str, Any] = {}
    source_records: list[dict[str, str]] = []
    for binding in assembly.component_bindings:
        path = _resolve_source_file(
            root,
            binding.manifest_locator,
            f"component_bindings.{binding.occurrence_id}",
        )
        manifest_bytes = _read_stable_file(
            path,
            maximum_bytes=_MAX_SOURCE_BYTES,
            field="source file",
            expected_digest=binding.manifest_file_digest,
        )
        manifest, shape = _reproduce_component_from_snapshots(path, manifest_bytes)
        if manifest.schema_version != COMPONENT_SCHEMA_V3:
            raise InputError(
                "component assembly requires component-manifest/0.3 releases"
            )
        if manifest.manifest_digest != binding.manifest_digest:
            raise IntegrityError("component binding manifest digest mismatch")
        embedded = occurrence_index[binding.occurrence_id].component
        if manifest.as_dict() != embedded.as_dict():
            raise IntegrityError(
                f"local manifest does not match embedded interface component: "
                f"{binding.occurrence_id}"
            )
        shapes[binding.occurrence_id] = shape
        source_records.append(
            {
                "occurrence_id": binding.occurrence_id,
                "manifest_locator": binding.manifest_locator,
                "manifest_file_digest": binding.manifest_file_digest,
                "manifest_digest": binding.manifest_digest,
                "source_bundle_digest": manifest.source_bundle_digest,
            }
        )
    return _LoadedContext(
        interface_assembly=interface,
        interface_result=result,
        shapes=shapes,
        source_records=tuple(source_records),
    )


def _source_root(value: str | Path) -> Path:
    supplied = Path(value)
    if _is_link_or_reparse(supplied):
        raise InputError(
            "component assembly source root cannot be a link or reparse point"
        )
    try:
        root = supplied.resolve(strict=True)
    except OSError as exc:
        raise InputError(
            f"component assembly source root is unavailable: {exc}"
        ) from exc
    if not root.is_dir() or _is_link_or_reparse(root):
        raise InputError("component assembly source root must be a direct directory")
    return root


def _resolve_source_file(root: Path, locator: str, field: str) -> Path:
    relative = PurePosixPath(locator)
    current = root
    for part in relative.parts:
        current = current / part
        if _is_link_or_reparse(current):
            raise InputError(f"{field} cannot traverse a link or reparse point")
    try:
        resolved = current.resolve(strict=True)
        resolved.relative_to(root)
    except (OSError, ValueError) as exc:
        raise InputError(
            f"{field} must resolve to a file within the source root"
        ) from exc
    if not resolved.is_file():
        raise InputError(f"{field} is not a regular file")
    stat_result = resolved.stat()
    if getattr(stat_result, "st_nlink", 1) != 1:
        raise InputError(f"{field} cannot use a hard-linked file")
    if stat_result.st_size > _MAX_SOURCE_BYTES:
        raise InputError(f"{field} exceeds the source file size limit")
    return resolved


def _is_link_or_reparse(path: Path) -> bool:
    try:
        if path.is_symlink():
            return True
        attributes = getattr(path.lstat(), "st_file_attributes", 0)
    except OSError:
        return False
    return bool(attributes & stat.FILE_ATTRIBUTE_REPARSE_POINT)


def _release_artifact_preflight(path: Path, locator: str, maximum_bytes: int) -> int:
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


def _reproduce_component_from_snapshots(
    manifest_path: Path, manifest_bytes: bytes
) -> tuple[ComponentManifest, Any]:
    manifest = ComponentManifest.from_dict(loads_strict(manifest_bytes))
    if len(manifest.artifacts) > _MAX_RELEASE_ARTIFACTS:
        raise InputError("component release artifact count exceeds its limit")
    artifact_paths: dict[str, tuple[Path, int, str]] = {}
    chain_size = len(manifest_bytes)
    for artifact in manifest.artifacts:
        locator = artifact.locator
        if Path(locator).name != locator or locator in {"", ".", ".."}:
            raise IntegrityError(
                "component artifact locator must be one local file name"
            )
        if locator in artifact_paths:
            raise IntegrityError("component artifact locators must be unique")
        candidate = manifest_path.parent / locator
        maximum = (
            _MAX_SOURCE_BYTES
            if artifact.role is ArtifactRole.ENGINEERING_BUNDLE
            else _MAX_RELEASE_ARTIFACT_BYTES
        )
        size = _release_artifact_preflight(candidate, locator, maximum)
        chain_size += size
        if chain_size > _MAX_RELEASE_CHAIN_BYTES:
            raise InputError("component release chain exceeds its byte limit")
        artifact_paths[locator] = (candidate, maximum, artifact.digest)

    captured: dict[str, bytes] = {}
    remaining = _MAX_RELEASE_CHAIN_BYTES - len(manifest_bytes)
    for locator, (candidate, maximum, expected_digest) in artifact_paths.items():
        value = _read_stable_file(
            candidate,
            maximum_bytes=min(maximum, remaining),
            field=f"component release artifact {locator}",
            expected_digest=expected_digest,
        )
        captured[locator] = value
        remaining -= len(value)
    with tempfile.TemporaryDirectory(
        prefix="contrainte-component-release-"
    ) as directory:
        snapshot_root = Path(directory)
        snapshot_manifest = snapshot_root / manifest_path.name
        snapshot_manifest.write_bytes(manifest_bytes)
        for locator, value in captured.items():
            (snapshot_root / locator).write_bytes(value)
        reproduced_manifest, shape = reproduce_local_component_shape(snapshot_manifest)
    if reproduced_manifest.as_dict() != manifest.as_dict():
        raise IntegrityError("component manifest snapshot did not reproduce")
    return manifest, shape


def _result_transforms(context: _LoadedContext) -> dict[str, ExactRigidTransform]:
    return {
        item.occurrence_id: item.transform
        for item in context.interface_result.occurrence_transforms
    }


def _compile_analysis(
    assembly: ComponentAssembly, context: _LoadedContext
) -> tuple[dict[str, Any], Any]:
    placed, projections = _compiler_place_shapes(context)
    return _compiler_pair_analysis(assembly, placed, projections)


def _verification_analysis(
    assembly: ComponentAssembly, context: _LoadedContext
) -> tuple[dict[str, Any], Any]:
    placed, projections = _verifier_place_shapes(context)
    return _verifier_pair_analysis(assembly, placed, projections)


def _compiler_place_shapes(
    context: _LoadedContext,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    try:
        from build123d import Location
        from OCP.gp import gp_Trsf
    except ImportError as exc:
        raise ExecutionError(
            "the CAD backend is not installed; install Contrainte with the 'cad' extra"
        ) from exc
    placed: dict[str, Any] = {}
    reports: list[dict[str, Any]] = []
    for occurrence_id, transform in sorted(_result_transforms(context).items()):
        matrix = _matrix_values(transform)
        trsf = gp_Trsf()
        trsf.SetValues(*(float(value) for row in matrix for value in row))
        maximum_error = max(
            abs(
                _kernel_fraction(
                    trsf.Value(row, column),
                    error_type=ExecutionError,
                    message="Open CASCADE returned an invalid transform coefficient",
                )
                - matrix[row - 1][column - 1]
            )
            for row in range(1, 4)
            for column in range(1, 5)
        )
        if maximum_error > _MATRIX_TOLERANCE:
            raise ExecutionError(
                "Open CASCADE changed an exact transform beyond tolerance"
            )
        shape = copy.copy(context.shapes[occurrence_id])
        shape.label = occurrence_id
        shape.locate(Location(trsf))
        placed[occurrence_id] = shape
        reports.append(
            {
                "occurrence_id": occurrence_id,
                "method": "direct-exact-basis-to-gp-trsf/0.1",
                "exact_transform": transform.as_dict(),
                "maximum_matrix_projection_error": _report_fraction(
                    maximum_error, places=_PROJECTION_REPORT_PLACES
                ),
                "projection_tolerance": "0.000000000001",
                "status": "passed",
            }
        )
    return placed, reports


def _verifier_place_shapes(
    context: _LoadedContext,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    try:
        from build123d import Location
        from OCP.gp import gp_Trsf
    except ImportError as exc:
        raise ExecutionError(
            "the CAD backend is not installed; install Contrainte with the 'cad' extra"
        ) from exc
    placed: dict[str, Any] = {}
    reports: list[dict[str, Any]] = []
    transforms = _result_transforms(context)
    for occurrence_id in sorted(transforms):
        transform = transforms[occurrence_id]
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
        trsf = gp_Trsf()
        trsf.SetValues(
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
        errors: list[Fraction] = []
        for row_index, row in enumerate(expected, start=1):
            for column_index, exact_value in enumerate(row, start=1):
                errors.append(
                    abs(
                        _kernel_fraction(
                            trsf.Value(row_index, column_index),
                            error_type=IntegrityError,
                            message=(
                                "kernel transform projection returned an invalid "
                                "coefficient"
                            ),
                        )
                        - exact_value
                    )
                )
        maximum_error = max(errors)
        if maximum_error > _MATRIX_TOLERANCE:
            raise IntegrityError("kernel transform projection no longer reproduces")
        shape = copy.copy(context.shapes[occurrence_id])
        shape.label = occurrence_id
        shape.locate(Location(gp_trsf=trsf))
        placed[occurrence_id] = shape
        reports.append(
            {
                "occurrence_id": occurrence_id,
                "method": "direct-exact-basis-to-gp-trsf/0.1",
                "exact_transform": {
                    "schema_version": "contrainte.exact-rigid-transform/0.1",
                    "unit": "mm",
                    "translation": transform.translation.as_dict(),
                    "basis": transform.rotation.as_dict(),
                },
                "maximum_matrix_projection_error": _report_fraction(
                    maximum_error, places=_PROJECTION_REPORT_PLACES
                ),
                "projection_tolerance": "0.000000000001",
                "status": "passed",
            }
        )
    return placed, reports


def _matrix_values(transform: ExactRigidTransform) -> tuple[tuple[Fraction, ...], ...]:
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


def _compiler_pair_analysis(
    assembly: ComponentAssembly,
    placed: dict[str, Any],
    projections: list[dict[str, Any]],
) -> tuple[dict[str, Any], Any]:
    try:
        from build123d import Compound
    except ImportError as exc:  # pragma: no cover - placement already imports it
        raise ExecutionError("the CAD backend is not installed") from exc
    pair_results: list[dict[str, str]] = []
    failures: list[str] = []
    for first, second in itertools.combinations(sorted(placed), 2):
        first_shape, second_shape = placed[first], placed[second]
        raw_distance = _kernel_fraction(
            first_shape.distance_to(second_shape),
            error_type=ExecutionError,
            message="Open CASCADE returned an invalid pair measurement",
        )
        intersection = first_shape & second_shape
        volume_parts = tuple(
            _kernel_fraction(
                solid.volume,
                error_type=ExecutionError,
                message="Open CASCADE returned an invalid pair measurement",
            )
            for solid in intersection.solids()
        )
        if raw_distance < 0 or any(value < 0 for value in volume_parts):
            raise ExecutionError("Open CASCADE returned an invalid pair measurement")
        raw_volume = sum(volume_parts, Fraction(0))
        required = assembly.clearance_for(first, second)
        if raw_volume > _INTERFERENCE_TOLERANCE:
            status = "interference"
            failures.append(f"{first}/{second} interfere")
        elif Fraction(raw_distance) + _DISTANCE_TOLERANCE < required:
            status = "clearance_violation"
            failures.append(f"{first}/{second} clearance is below its requirement")
        else:
            status = "passed"
        pair_results.append(
            {
                "first_occurrence_id": first,
                "second_occurrence_id": second,
                "distance_mm": _report_fraction(
                    raw_distance, places=_MEASUREMENT_REPORT_PLACES
                ),
                "minimum_clearance_mm": _fraction_text(required),
                "interference_volume_mm3": _report_fraction(
                    raw_volume, places=_MEASUREMENT_REPORT_PLACES
                ),
                "status": status,
            }
        )
    compound = Compound(
        label=assembly.assembly_id, children=[placed[key] for key in sorted(placed)]
    )
    analysis = _compiler_analysis_document(
        compound, projections, pair_results, failures
    )
    return analysis, compound


def _verifier_pair_analysis(
    assembly: ComponentAssembly,
    placed: dict[str, Any],
    projections: list[dict[str, Any]],
) -> tuple[dict[str, Any], Any]:
    try:
        from build123d import Compound
    except ImportError as exc:  # pragma: no cover - placement already imports it
        raise ExecutionError("the CAD backend is not installed") from exc
    reproduced: list[dict[str, str]] = []
    failures: list[str] = []
    ids = sorted(placed)
    for first_index in range(len(ids)):
        for second_index in range(first_index + 1, len(ids)):
            first, second = ids[first_index], ids[second_index]
            distance_raw = _kernel_fraction(
                placed[first].distance_to(placed[second]),
                error_type=IntegrityError,
                message="kernel pair measurement no longer reproduces",
            )
            common = placed[first] & placed[second]
            volume_parts = tuple(
                _kernel_fraction(
                    solid.volume,
                    error_type=IntegrityError,
                    message="kernel pair measurement no longer reproduces",
                )
                for solid in common.solids()
            )
            if distance_raw < 0 or any(value < 0 for value in volume_parts):
                raise IntegrityError("kernel pair measurement no longer reproduces")
            volume_raw = sum(volume_parts, Fraction(0))
            minimum = assembly.clearance_for(first, second)
            if volume_raw > Fraction(1, 1_000_000):
                outcome = "interference"
                failures.append(f"{first}/{second} interfere")
            elif Fraction(distance_raw) + Fraction(1, 1_000_000) < minimum:
                outcome = "clearance_violation"
                failures.append(f"{first}/{second} clearance is below its requirement")
            else:
                outcome = "passed"
            reproduced.append(
                {
                    "first_occurrence_id": first,
                    "second_occurrence_id": second,
                    "distance_mm": _report_fraction(
                        distance_raw, places=_MEASUREMENT_REPORT_PLACES
                    ),
                    "minimum_clearance_mm": _fraction_text(minimum),
                    "interference_volume_mm3": _report_fraction(
                        volume_raw, places=_MEASUREMENT_REPORT_PLACES
                    ),
                    "status": outcome,
                }
            )
    compound = Compound(
        children=[placed[key] for key in ids], label=assembly.assembly_id
    )
    return (
        _verifier_analysis_document(compound, projections, reproduced, failures),
        compound,
    )


def _compiler_analysis_document(
    compound: Any,
    projections: list[dict[str, Any]],
    pair_results: list[dict[str, str]],
    failures: list[str],
) -> dict[str, Any]:
    valid = compound.is_valid
    if callable(valid):
        valid = valid()
    if not valid:
        failures.append("component assembly compound is not a valid B-rep")
    bounds = compound.bounding_box().size
    return {
        "status": "passed" if not failures else "failed",
        "occurrence_count": len(projections),
        "pair_count": len(pair_results),
        "transform_projections": projections,
        "bounding_box_mm": {
            axis: _report_fraction(
                _kernel_fraction(
                    getattr(bounds, axis.upper()),
                    error_type=ExecutionError,
                    message="Open CASCADE returned invalid assembly bounds",
                ),
                places=_MEASUREMENT_REPORT_PLACES,
            )
            for axis in ("x", "y", "z")
        },
        "pair_results": pair_results,
        "failures": failures,
    }


def _verifier_analysis_document(
    compound: Any,
    transform_projections: list[dict[str, Any]],
    pair_evidence: list[dict[str, str]],
    recorded_failures: list[str],
) -> dict[str, Any]:
    validity = compound.is_valid
    if callable(validity):
        validity = validity()
    failures = list(recorded_failures)
    if not validity:
        failures.append("component assembly compound is not a valid B-rep")
    box = compound.bounding_box()
    size = box.size
    return {
        "status": "passed" if len(failures) == 0 else "failed",
        "occurrence_count": len(transform_projections),
        "pair_count": len(pair_evidence),
        "transform_projections": transform_projections,
        "bounding_box_mm": {
            axis: _report_fraction(
                _kernel_fraction(
                    getattr(size, axis.upper()),
                    error_type=IntegrityError,
                    message="kernel assembly bounds no longer reproduce",
                ),
                places=_MEASUREMENT_REPORT_PLACES,
            )
            for axis in ("x", "y", "z")
        },
        "pair_results": pair_evidence,
        "failures": failures,
    }


def _kernel_identity() -> dict[str, str]:
    return {
        "backend": "build123d-opencascade",
        "build123d_version": package_version("build123d"),
        "opencascade_distribution_version": package_version("cadquery-ocp"),
        "transform_projection": "direct-exact-basis-to-gp-trsf/0.1",
    }


def _checks() -> list[dict[str, str]]:
    return [
        {"id": "COMPONENT-ASSEMBLY-SCHEMA", "status": "passed"},
        {"id": "COMPONENT-ASSEMBLY-SOURCE-FILES", "status": "passed"},
        {"id": "COMPONENT-ASSEMBLY-LOCAL-RELEASES", "status": "passed"},
        {"id": "COMPONENT-ASSEMBLY-INTERFACE-REPLAY", "status": "passed"},
        {"id": "COMPONENT-ASSEMBLY-EXACT-POSE-PROJECTION", "status": "passed"},
        {"id": "COMPONENT-ASSEMBLY-BREP-VALIDITY", "status": "passed"},
        {"id": "COMPONENT-ASSEMBLY-INTERFERENCE", "status": "passed"},
        {"id": "COMPONENT-ASSEMBLY-CLEARANCE", "status": "passed"},
    ]
