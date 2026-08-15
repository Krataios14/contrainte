from __future__ import annotations

import copy
import ctypes
import hashlib
import itertools
import math
import os
import re
import secrets
import stat
import tempfile
import unicodedata
from dataclasses import dataclass
from decimal import ROUND_HALF_EVEN, Context, Decimal, localcontext
from fractions import Fraction
from pathlib import Path, PurePosixPath
from typing import Any

if os.name == "nt":
    from ctypes import wintypes

from .artifacts import package_version
from .canonical import decimal_text, digest, dumps_pretty, loads_strict
from .component import COMPONENT_SCHEMA_V3, ArtifactRole, ComponentManifest
from .errors import ContrainteError, ExecutionError, InputError, IntegrityError
from .exact_transform import ExactRigidTransform
from .geometry import normalize_step_occurrence_identifiers
from .interface_assembly import (
    InterfaceAssembly,
    InterfaceAssemblyResult,
    SolveStatus,
    solve_interface_assembly,
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


def _guarded_stable_file(
    guard: _DirectoryIdentityGuard,
    path: Path,
    *,
    maximum_bytes: int,
    field: str,
    expected_digest: str | None = None,
    error_type: type[InputError | IntegrityError] = InputError,
) -> bytes:
    guard.verify()
    captured = _read_stable_file(
        path,
        maximum_bytes=maximum_bytes,
        field=field,
        expected_digest=expected_digest,
        error_type=error_type,
    )
    guard.verify()
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


@dataclass(slots=True)
class _DirectoryIdentityGuard:
    root: Path
    identities: dict[Path, tuple[int, int, int]]

    @classmethod
    def create(cls, root: Path) -> _DirectoryIdentityGuard:
        guard = cls(root, {})
        guard.bind(root)
        return guard

    def bind(self, path: Path) -> None:
        identity = _direct_directory_identity(path)
        previous = self.identities.setdefault(path, identity)
        if previous != identity:
            raise IntegrityError(
                f"bound directory identity changed during preparation: {path}"
            )

    def verify(self) -> None:
        for path, expected in self.identities.items():
            if _direct_directory_identity(path) != expected:
                raise IntegrityError(
                    f"bound directory identity changed during preparation: {path}"
                )

    def unbind(self, path: Path) -> None:
        self.identities.pop(path, None)


def _prepare_fault_hook(point: str) -> None:
    """Deterministic no-op seam for pre-I/O race regression tests."""


if os.name == "nt":
    _KERNEL32 = ctypes.WinDLL("kernel32", use_last_error=True)
    _INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value
    _GENERIC_READ = 0x80000000
    _GENERIC_WRITE = 0x40000000
    _DELETE = 0x00010000
    _FILE_LIST_DIRECTORY = 0x0001
    _FILE_READ_ATTRIBUTES = 0x0080
    _FILE_SHARE_READ = 0x00000001
    _FILE_SHARE_WRITE = 0x00000002
    _CREATE_NEW = 1
    _CREATE_ALWAYS = 2
    _OPEN_EXISTING = 3
    _FILE_ATTRIBUTE_DIRECTORY = 0x00000010
    _FILE_ATTRIBUTE_REPARSE_POINT = 0x00000400
    _FILE_FLAG_BACKUP_SEMANTICS = 0x02000000
    _FILE_FLAG_OPEN_REPARSE_POINT = 0x00200000
    _FILE_FLAG_SEQUENTIAL_SCAN = 0x08000000
    _FILE_BEGIN = 0
    _FILE_RENAME_INFO_CLASS = 3
    _FILE_DISPOSITION_INFO_CLASS = 4

    class _WinFileTime(ctypes.Structure):
        _fields_ = (("low", wintypes.DWORD), ("high", wintypes.DWORD))

    class _WinByHandleInfo(ctypes.Structure):
        _fields_ = (
            ("attributes", wintypes.DWORD),
            ("creation", _WinFileTime),
            ("access", _WinFileTime),
            ("write", _WinFileTime),
            ("volume_serial", wintypes.DWORD),
            ("size_high", wintypes.DWORD),
            ("size_low", wintypes.DWORD),
            ("links", wintypes.DWORD),
            ("index_high", wintypes.DWORD),
            ("index_low", wintypes.DWORD),
        )

    class _WinRenameHeader(ctypes.Structure):
        _fields_ = (
            ("replace", wintypes.BOOL),
            ("root", wintypes.HANDLE),
            ("name_length", wintypes.DWORD),
            ("name", wintypes.WCHAR * 1),
        )

    class _WinDisposition(ctypes.Structure):
        _fields_ = (("delete", wintypes.BOOL),)

    _KERNEL32.CreateFileW.argtypes = (
        wintypes.LPCWSTR,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.LPVOID,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.HANDLE,
    )
    _KERNEL32.CreateFileW.restype = wintypes.HANDLE
    _KERNEL32.CloseHandle.argtypes = (wintypes.HANDLE,)
    _KERNEL32.CloseHandle.restype = wintypes.BOOL
    _KERNEL32.GetFileInformationByHandle.argtypes = (
        wintypes.HANDLE,
        ctypes.POINTER(_WinByHandleInfo),
    )
    _KERNEL32.GetFileInformationByHandle.restype = wintypes.BOOL
    _KERNEL32.GetFinalPathNameByHandleW.argtypes = (
        wintypes.HANDLE,
        wintypes.LPWSTR,
        wintypes.DWORD,
        wintypes.DWORD,
    )
    _KERNEL32.GetFinalPathNameByHandleW.restype = wintypes.DWORD
    _KERNEL32.ReadFile.argtypes = (
        wintypes.HANDLE,
        wintypes.LPVOID,
        wintypes.DWORD,
        ctypes.POINTER(wintypes.DWORD),
        wintypes.LPVOID,
    )
    _KERNEL32.ReadFile.restype = wintypes.BOOL
    _KERNEL32.WriteFile.argtypes = (
        wintypes.HANDLE,
        wintypes.LPCVOID,
        wintypes.DWORD,
        ctypes.POINTER(wintypes.DWORD),
        wintypes.LPVOID,
    )
    _KERNEL32.WriteFile.restype = wintypes.BOOL
    _KERNEL32.SetFilePointerEx.argtypes = (
        wintypes.HANDLE,
        ctypes.c_longlong,
        ctypes.POINTER(ctypes.c_longlong),
        wintypes.DWORD,
    )
    _KERNEL32.SetFilePointerEx.restype = wintypes.BOOL
    _KERNEL32.FlushFileBuffers.argtypes = (wintypes.HANDLE,)
    _KERNEL32.FlushFileBuffers.restype = wintypes.BOOL
    _KERNEL32.SetFileInformationByHandle.argtypes = (
        wintypes.HANDLE,
        ctypes.c_int,
        wintypes.LPVOID,
        wintypes.DWORD,
    )
    _KERNEL32.SetFileInformationByHandle.restype = wintypes.BOOL
    _KERNEL32.CreateDirectoryW.argtypes = (wintypes.LPCWSTR, wintypes.LPVOID)
    _KERNEL32.CreateDirectoryW.restype = wintypes.BOOL


def _windows_error(message: str) -> OSError:
    return OSError(ctypes.get_last_error(), message)


def _normal_windows_handle_path(value: str) -> str:
    if value.startswith("\\\\?\\UNC\\"):
        value = "\\\\" + value[8:]
    elif value.startswith("\\\\?\\"):
        value = value[4:]
    return os.path.normcase(os.path.abspath(value))


def _windows_final_path(handle: int) -> str:
    size = 512
    while True:
        buffer = ctypes.create_unicode_buffer(size)
        length = _KERNEL32.GetFinalPathNameByHandleW(handle, buffer, size, 0)
        if length == 0:
            raise _windows_error("cannot resolve opened handle")
        if length < size:
            return _normal_windows_handle_path(buffer.value)
        size = length + 1


def _windows_info(handle: int) -> tuple[int, ...]:
    value = _WinByHandleInfo()
    if not _KERNEL32.GetFileInformationByHandle(handle, ctypes.byref(value)):
        raise _windows_error("cannot inspect opened handle")
    return (
        value.attributes,
        value.volume_serial,
        value.index_high,
        value.index_low,
        value.links,
        value.size_high,
        value.size_low,
        value.creation.high,
        value.creation.low,
        value.write.high,
        value.write.low,
    )


def _windows_open(
    path: Path,
    *,
    directory: bool,
    create: bool = False,
    truncate: bool = False,
    deletable: bool = False,
) -> int:
    desired = _FILE_READ_ATTRIBUTES | (_DELETE if deletable else 0)
    flags = _FILE_FLAG_OPEN_REPARSE_POINT
    disposition = _OPEN_EXISTING
    if directory:
        desired |= _FILE_LIST_DIRECTORY
        flags |= _FILE_FLAG_BACKUP_SEMANTICS
    else:
        desired |= _GENERIC_READ
        flags |= _FILE_FLAG_SEQUENTIAL_SCAN
        if create or truncate:
            desired |= _GENERIC_WRITE
            disposition = _CREATE_ALWAYS if truncate else _CREATE_NEW
    handle = _KERNEL32.CreateFileW(
        str(path),
        desired,
        _FILE_SHARE_READ | (_FILE_SHARE_WRITE if directory else 0),
        None,
        disposition,
        flags,
        None,
    )
    if handle == _INVALID_HANDLE_VALUE:
        raise _windows_error(f"cannot open direct handle: {path}")
    return int(handle)


def _windows_close(handle: int) -> None:
    if not _KERNEL32.CloseHandle(handle):
        raise _windows_error("cannot close native handle")


def _windows_read(handle: int, maximum_bytes: int) -> bytes:
    if not _KERNEL32.SetFilePointerEx(handle, 0, None, _FILE_BEGIN):
        raise _windows_error("cannot rewind opened file")
    captured = bytearray()
    while True:
        block_size = min(1024 * 1024, maximum_bytes + 1 - len(captured))
        buffer = ctypes.create_string_buffer(block_size)
        count = wintypes.DWORD()
        if not _KERNEL32.ReadFile(
            handle, buffer, block_size, ctypes.byref(count), None
        ):
            raise _windows_error("cannot read opened file")
        if count.value == 0:
            return bytes(captured)
        captured.extend(buffer.raw[: count.value])
        if len(captured) > maximum_bytes:
            raise InputError("file exceeds its byte limit while reading")


def _windows_write(handle: int, value: bytes) -> None:
    offset = 0
    while offset < len(value):
        block = value[offset : offset + 1024 * 1024]
        buffer = ctypes.create_string_buffer(block)
        count = wintypes.DWORD()
        if not _KERNEL32.WriteFile(
            handle, buffer, len(block), ctypes.byref(count), None
        ):
            raise _windows_error("cannot write opened file")
        if count.value != len(block):
            raise OSError("native file write was incomplete")
        offset += count.value
    if not _KERNEL32.FlushFileBuffers(handle):
        raise _windows_error("cannot flush opened file")


def _windows_rename(handle: int, parent: _BoundDirectory, name: str) -> None:
    encoded = str(parent.path / name).encode("utf-16-le")
    size = _WinRenameHeader.name.offset + len(encoded) + ctypes.sizeof(wintypes.WCHAR)
    buffer = ctypes.create_string_buffer(size)
    header = _WinRenameHeader.from_buffer(buffer)
    header.replace = False
    header.root = 0
    header.name_length = len(encoded)
    ctypes.memmove(
        ctypes.addressof(buffer) + _WinRenameHeader.name.offset, encoded, len(encoded)
    )
    if not _KERNEL32.SetFileInformationByHandle(
        handle, _FILE_RENAME_INFO_CLASS, buffer, size
    ):
        raise _windows_error("cannot rename opened transaction entry")


def _windows_mark_delete(handle: int) -> None:
    value = _WinDisposition(True)
    if not _KERNEL32.SetFileInformationByHandle(
        handle,
        _FILE_DISPOSITION_INFO_CLASS,
        ctypes.byref(value),
        ctypes.sizeof(value),
    ):
        raise _windows_error("cannot delete opened transaction entry")


def _posix_named_identity(value: os.stat_result) -> tuple[int, ...]:
    """Return the identity fields that bind an fd to one visible directory entry."""

    return (value.st_dev, value.st_ino, value.st_mode, value.st_nlink)


def _require_posix_named_handle(
    parent_handle: int,
    name: str,
    opened: os.stat_result,
    *,
    directory: bool,
    error_type: type[InputError | IntegrityError],
    message: str,
) -> os.stat_result:
    try:
        visible = os.stat(name, dir_fd=parent_handle, follow_symlinks=False)
    except OSError as exc:
        raise error_type(message) from exc
    expected_kind = stat.S_ISDIR if directory else stat.S_ISREG
    if (
        not expected_kind(opened.st_mode)
        or not expected_kind(visible.st_mode)
        or opened.st_nlink < 1
        or _posix_named_identity(opened) != _posix_named_identity(visible)
    ):
        raise error_type(message)
    return visible


@dataclass(slots=True)
class _BoundDirectory:
    path: Path
    handle: int
    identity: tuple[int, ...]
    windows: bool
    parent: _BoundDirectory | None = None
    closed: bool = False

    @classmethod
    def open(cls, path: Path, *, deletable: bool = False) -> _BoundDirectory:
        if os.name == "nt":
            try:
                handle = _windows_open(path, directory=True, deletable=deletable)
            except OSError as exc:
                raise InputError(
                    f"cannot open direct directory handle: {path}"
                ) from exc
            info = _windows_info(handle)
            attributes = info[0]
            expected = _normal_windows_handle_path(str(path))
            if (
                not attributes & _FILE_ATTRIBUTE_DIRECTORY
                or attributes & _FILE_ATTRIBUTE_REPARSE_POINT
                or _windows_final_path(handle) != expected
            ):
                _windows_close(handle)
                raise InputError(f"directory handle is indirect or misplaced: {path}")
            return cls(path, handle, info[:4], True)
        flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
        try:
            handle = os.open(path, flags)
        except OSError as exc:
            raise InputError(f"cannot open direct directory handle: {path}") from exc
        metadata = os.fstat(handle)
        try:
            visible = os.stat(path, follow_symlinks=False)
        except OSError as exc:
            os.close(handle)
            raise InputError(f"cannot inspect direct directory handle: {path}") from exc
        if not stat.S_ISDIR(metadata.st_mode) or _posix_named_identity(
            metadata
        ) != _posix_named_identity(visible):
            os.close(handle)
            raise InputError(f"directory handle is indirect or misplaced: {path}")
        return cls(
            path, handle, (metadata.st_dev, metadata.st_ino, metadata.st_mode), False
        )

    def child_directory(self, name: str, *, deletable: bool = False) -> _BoundDirectory:
        _prepare_fault_hook("before_directory_open")
        self.verify_visible()
        child_path = self.path / name
        if self.windows:
            return _BoundDirectory.open(child_path, deletable=deletable)
        flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
        try:
            handle = os.open(name, flags, dir_fd=self.handle)
        except OSError as exc:
            raise InputError(f"cannot open direct child directory: {name}") from exc
        metadata = os.fstat(handle)
        try:
            _require_posix_named_handle(
                self.handle,
                name,
                metadata,
                directory=True,
                error_type=InputError,
                message=f"child directory handle is misplaced: {name}",
            )
            self.verify_visible()
        except BaseException:
            os.close(handle)
            raise
        return _BoundDirectory(
            child_path,
            handle,
            (metadata.st_dev, metadata.st_ino, metadata.st_mode),
            False,
            self,
        )

    def verify_visible(self) -> None:
        if self.windows:
            if _windows_info(self.handle)[:4] != self.identity or _windows_final_path(
                self.handle
            ) != _normal_windows_handle_path(str(self.path)):
                raise IntegrityError("bound directory handle location changed")
            return
        opened = os.fstat(self.handle)
        try:
            if self.parent is None:
                visible = os.stat(self.path, follow_symlinks=False)
                if not stat.S_ISDIR(visible.st_mode) or _posix_named_identity(
                    visible
                ) != _posix_named_identity(opened):
                    raise IntegrityError("bound directory handle location changed")
            else:
                self.parent.verify_visible()
                _require_posix_named_handle(
                    self.parent.handle,
                    self.path.name,
                    opened,
                    directory=True,
                    error_type=IntegrityError,
                    message="bound directory handle location changed",
                )
        except OSError as exc:
            raise IntegrityError("bound directory is no longer visible") from exc
        if (opened.st_dev, opened.st_ino, opened.st_mode) != self.identity:
            raise IntegrityError("bound directory handle location changed")

    def create_child_directory(self, name: str) -> _BoundDirectory:
        _prepare_fault_hook("before_directory_create")
        self.verify_visible()
        if self.windows:
            path = self.path / name
            if not _KERNEL32.CreateDirectoryW(str(path), None):
                raise _windows_error(f"cannot create transaction directory: {name}")
            return self.child_directory(name, deletable=True)
        try:
            os.mkdir(name, mode=0o700, dir_fd=self.handle)
        except OSError as exc:
            raise InputError(f"cannot create direct child directory: {name}") from exc
        child = self.child_directory(name)
        if stat.S_IMODE(os.fstat(child.handle).st_mode) & 0o077:
            self.delete_child_directory(child)
            raise IntegrityError("private transaction directory permissions are broad")
        return child

    def read_file(
        self,
        name: str,
        *,
        maximum_bytes: int,
        field: str,
        expected_digest: str | None = None,
        error_type: type[InputError | IntegrityError] = InputError,
    ) -> bytes:
        retained = _open_retained_bound_file(
            self,
            name,
            maximum_bytes=maximum_bytes,
            field=field,
            expected_digest=expected_digest,
            error_type=error_type,
        )
        try:
            retained.verify_visible()
            return retained.captured
        finally:
            retained.close()

    def write_new_file(self, name: str, captured: bytes, *, field: str) -> None:
        self.verify_visible()
        _prepare_fault_hook(f"before_file_create:{field}")
        self.verify_visible()
        handle: int | None = None
        try:
            if self.windows:
                handle = _windows_open(self.path / name, directory=False, create=True)
                before_info = _windows_info(handle)
                before_path = _windows_final_path(handle)
                if (
                    before_info[0]
                    & (_FILE_ATTRIBUTE_DIRECTORY | _FILE_ATTRIBUTE_REPARSE_POINT)
                    or before_info[4] != 1
                    or (before_info[5] << 32) | before_info[6] != 0
                    or before_path != _normal_windows_handle_path(str(self.path / name))
                ):
                    raise IntegrityError(f"{field} handle is misplaced")
                _windows_write(handle, captured)
                info = _windows_info(handle)
                if (
                    info[:4] != before_info[:4]
                    or info[4] != 1
                    or (info[5] << 32) | info[6] != len(captured)
                ):
                    raise IntegrityError(f"{field} metadata does not reproduce")
                reproduced = _windows_read(handle, max(len(captured), 1))
            else:
                flags = (
                    os.O_RDWR | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC
                )
                handle = os.open(name, flags, 0o600, dir_fd=self.handle)
                before_metadata = os.fstat(handle)
                _require_posix_named_handle(
                    self.handle,
                    name,
                    before_metadata,
                    directory=False,
                    error_type=IntegrityError,
                    message=f"{field} handle is misplaced",
                )
                if (
                    not stat.S_ISREG(before_metadata.st_mode)
                    or before_metadata.st_nlink != 1
                    or before_metadata.st_size != 0
                ):
                    raise IntegrityError(f"{field} handle is misplaced")
                offset = 0
                while offset < len(captured):
                    offset += os.write(handle, captured[offset:])
                os.fsync(handle)
                metadata = os.fstat(handle)
                _require_posix_named_handle(
                    self.handle,
                    name,
                    metadata,
                    directory=False,
                    error_type=IntegrityError,
                    message=f"{field} metadata does not reproduce",
                )
                if (
                    (metadata.st_dev, metadata.st_ino, metadata.st_mode)
                    != (
                        before_metadata.st_dev,
                        before_metadata.st_ino,
                        before_metadata.st_mode,
                    )
                    or metadata.st_nlink != 1
                    or metadata.st_size != len(captured)
                ):
                    raise IntegrityError(f"{field} metadata does not reproduce")
                os.lseek(handle, 0, os.SEEK_SET)
                reproduced = b""
                while len(reproduced) < len(captured):
                    block = os.read(handle, len(captured) - len(reproduced))
                    if not block:
                        break
                    reproduced += block
            if reproduced != captured:
                raise IntegrityError(f"{field} bytes do not reproduce")
            self.verify_visible()
        except OSError as exc:
            raise InputError(f"cannot publish {field}") from exc
        finally:
            if handle is not None:
                _windows_close(handle) if self.windows else os.close(handle)

    def names(self) -> set[str]:
        _prepare_fault_hook("before_directory_enumeration")
        if self.windows:
            self.verify_visible()
            names = {item.name for item in os.scandir(self.path)}
            self.verify_visible()
        else:
            names = set(os.listdir(self.handle))
        return names

    def rename_child_handle(self, child: _BoundDirectory, new_name: str) -> None:
        old_name = child.path.name
        _prepare_fault_hook(f"before_handle_rename:{old_name}->{new_name}")
        if self.windows:
            self.verify_visible()
            child.verify_visible()
            _windows_rename(child.handle, self, new_name)
        else:
            _require_posix_named_handle(
                self.handle,
                old_name,
                os.fstat(child.handle),
                directory=True,
                error_type=IntegrityError,
                message="transaction directory handle location changed",
            )
            os.rename(
                child.path.name,
                new_name,
                src_dir_fd=self.handle,
                dst_dir_fd=self.handle,
            )
        child.path = self.path / new_name
        _prepare_fault_hook(f"after_handle_rename:{old_name}->{new_name}")
        if self.windows:
            child.verify_visible()
            self.verify_visible()
        else:
            _require_posix_named_handle(
                self.handle,
                new_name,
                os.fstat(child.handle),
                directory=True,
                error_type=IntegrityError,
                message="transaction directory handle location changed",
            )

    def delete_child_file(self, name: str) -> None:
        _prepare_fault_hook("before_handle_unlink")
        if self.windows:
            self.verify_visible()
            handle = _windows_open(self.path / name, directory=False, deletable=True)
            try:
                info = _windows_info(handle)
                if (
                    info[0]
                    & (_FILE_ATTRIBUTE_DIRECTORY | _FILE_ATTRIBUTE_REPARSE_POINT)
                    or info[4] != 1
                    or _windows_final_path(handle)
                    != _normal_windows_handle_path(str(self.path / name))
                ):
                    raise IntegrityError("transaction file is indirect or hard-linked")
                _windows_mark_delete(handle)
            finally:
                _windows_close(handle)
            self.verify_visible()
        else:
            handle = os.open(
                name, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=self.handle
            )
            try:
                metadata = os.fstat(handle)
                _require_posix_named_handle(
                    self.handle,
                    name,
                    metadata,
                    directory=False,
                    error_type=IntegrityError,
                    message="transaction file is indirect or hard-linked",
                )
                if metadata.st_nlink != 1:
                    raise IntegrityError("transaction file is indirect or hard-linked")
                os.unlink(name, dir_fd=self.handle)
                if os.fstat(handle).st_nlink != 0:
                    raise IntegrityError("transaction file unlink did not reproduce")
            finally:
                os.close(handle)

    def delete_child_directory(self, child: _BoundDirectory) -> None:
        _prepare_fault_hook("before_handle_rmdir")
        if self.windows:
            self.verify_visible()
            child.verify_visible()
            _windows_mark_delete(child.handle)
            child.close()
            self.verify_visible()
        else:
            _require_posix_named_handle(
                self.handle,
                child.path.name,
                os.fstat(child.handle),
                directory=True,
                error_type=IntegrityError,
                message="transaction directory handle location changed",
            )
            os.rmdir(child.path.name, dir_fd=self.handle)
            child.close()

    def close(self) -> None:
        if self.closed:
            return
        _windows_close(self.handle) if self.windows else os.close(self.handle)
        self.closed = True


@dataclass(slots=True)
class _RetainedBoundFile:
    parent: _BoundDirectory
    name: str
    handle: int
    identity: tuple[int, ...]
    captured: bytes
    error_type: type[InputError | IntegrityError]
    field: str
    closed: bool = False

    def verify_visible(self) -> None:
        self.parent.verify_visible()
        if self.parent.windows:
            if _windows_info(self.handle) != self.identity or _windows_final_path(
                self.handle
            ) != _normal_windows_handle_path(str(self.parent.path / self.name)):
                raise self.error_type(f"{self.field} changed after capture")
            return
        try:
            opened = os.fstat(self.handle)
            relative = os.stat(
                self.name, dir_fd=self.parent.handle, follow_symlinks=False
            )
        except OSError as exc:
            raise self.error_type(f"{self.field} changed after capture") from exc
        if (
            _stat_identity(opened) != self.identity
            or _stat_identity(relative) != self.identity
        ):
            raise self.error_type(f"{self.field} changed after capture")

    def close(self) -> None:
        if self.closed:
            return
        _windows_close(self.handle) if self.parent.windows else os.close(self.handle)
        self.closed = True


def _open_retained_bound_file(
    parent: _BoundDirectory,
    name: str,
    *,
    maximum_bytes: int,
    field: str,
    expected_digest: str | None,
    error_type: type[InputError | IntegrityError],
) -> _RetainedBoundFile:
    parent.verify_visible()
    _prepare_fault_hook(f"before_file_open:{field}")
    parent.verify_visible()
    handle: int | None = None
    success = False
    try:
        if parent.windows:
            handle = _windows_open(parent.path / name, directory=False)
            before = _windows_info(handle)
            attributes = before[0]
            size = (before[5] << 32) | before[6]
            if attributes & (
                _FILE_ATTRIBUTE_DIRECTORY | _FILE_ATTRIBUTE_REPARSE_POINT
            ) or _windows_final_path(handle) != _normal_windows_handle_path(
                str(parent.path / name)
            ):
                raise error_type(f"{field} cannot use links or reparse points")
            if before[4] != 1:
                raise error_type(f"{field} cannot be hard-linked")
            if size > maximum_bytes:
                raise error_type(f"{field} exceeds its byte limit")
            captured = _windows_read(handle, maximum_bytes)
            after = _windows_info(handle)
            identity = after
        else:
            flags = os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC
            handle = os.open(name, flags, dir_fd=parent.handle)
            before_stat = os.fstat(handle)
            relative_stat = _require_posix_named_handle(
                parent.handle,
                name,
                before_stat,
                directory=False,
                error_type=error_type,
                message=f"{field} cannot use links or reparse points",
            )
            if not stat.S_ISREG(before_stat.st_mode) or _stat_identity(
                before_stat
            ) != _stat_identity(relative_stat):
                raise error_type(f"{field} cannot use links or reparse points")
            if before_stat.st_nlink != 1:
                raise error_type(f"{field} cannot be hard-linked")
            if before_stat.st_size > maximum_bytes:
                raise error_type(f"{field} exceeds its byte limit")
            captured_array = bytearray()
            while True:
                block = os.read(
                    handle,
                    min(1024 * 1024, maximum_bytes + 1 - len(captured_array)),
                )
                if not block:
                    break
                captured_array.extend(block)
                if len(captured_array) > maximum_bytes:
                    raise error_type(f"{field} exceeds its byte limit")
            captured = bytes(captured_array)
            after_stat = os.fstat(handle)
            _require_posix_named_handle(
                parent.handle,
                name,
                after_stat,
                directory=False,
                error_type=error_type,
                message=f"{field} changed while it was being read",
            )
            after = _stat_identity(after_stat)
            before = _stat_identity(before_stat)
            identity = after
        expected_size = (
            (before[5] << 32) | before[6] if parent.windows else before_stat.st_size
        )
        if before != after or len(captured) != expected_size:
            raise error_type(f"{field} changed while it was being read")
        if expected_digest is not None and _sha256_bytes(captured) != expected_digest:
            raise IntegrityError(f"{field} digest mismatch")
        retained = _RetainedBoundFile(
            parent, name, handle, identity, captured, error_type, field
        )
        retained.verify_visible()
        success = True
        return retained
    except OSError as exc:
        if not parent.windows:
            try:
                failed_metadata = os.stat(
                    name, dir_fd=parent.handle, follow_symlinks=False
                )
            except OSError:
                pass
            else:
                if stat.S_ISLNK(failed_metadata.st_mode):
                    raise error_type(
                        f"{field} cannot use links or reparse points"
                    ) from exc
        raise error_type(f"{field} is unavailable") from exc
    finally:
        if handle is not None and not success:
            _windows_close(handle) if parent.windows else os.close(handle)


@dataclass(slots=True)
class _BoundSourceTree:
    root: _BoundDirectory
    directories: dict[tuple[str, ...], _BoundDirectory]

    @classmethod
    def open(cls, root: Path) -> _BoundSourceTree:
        bound = _BoundDirectory.open(root)
        return cls(bound, {(): bound})

    def directory(
        self, parts: tuple[str, ...], *, create: bool = False
    ) -> _BoundDirectory:
        current_parts: tuple[str, ...] = ()
        current = self.root
        for part in parts:
            current_parts += (part,)
            cached = self.directories.get(current_parts)
            if cached is None:
                try:
                    cached = current.child_directory(part)
                except InputError:
                    if not create:
                        raise
                    cached = current.create_child_directory(part)
                self.directories[current_parts] = cached
            current = cached
        return current

    def read_locator(
        self,
        locator: str,
        *,
        maximum_bytes: int,
        field: str,
        expected_digest: str | None = None,
    ) -> bytes:
        parts = PurePosixPath(locator).parts
        parent = self.directory(tuple(parts[:-1]))
        return parent.read_file(
            parts[-1],
            maximum_bytes=maximum_bytes,
            field=field,
            expected_digest=expected_digest,
        )

    def close(self) -> None:
        for parts in sorted(self.directories, key=len, reverse=True):
            self.directories[parts].close()

    def verify_visible(self) -> None:
        for directory in self.directories.values():
            directory.verify_visible()


def _bound_release_snapshot(
    tree: _BoundSourceTree, manifest_locator: str
) -> tuple[ComponentManifest, Any, bytes]:
    parts = PurePosixPath(manifest_locator).parts
    parent = tree.directory(tuple(parts[:-1]))
    manifest_bytes = parent.read_file(
        parts[-1],
        maximum_bytes=_MAX_SOURCE_BYTES,
        field="component manifest",
    )
    manifest = ComponentManifest.from_dict(loads_strict(manifest_bytes))
    if len(manifest.artifacts) > _MAX_RELEASE_ARTIFACTS:
        raise InputError("component release artifact count exceeds its limit")
    captured: dict[str, bytes] = {}
    chain_size = len(manifest_bytes)
    for artifact in manifest.artifacts:
        locator = artifact.locator
        if Path(locator).name != locator or locator in {"", ".", ".."}:
            raise IntegrityError(
                "component artifact locator must be one local file name"
            )
        if locator in captured:
            raise IntegrityError("component artifact locators must be unique")
        maximum = (
            _MAX_SOURCE_BYTES
            if artifact.role is ArtifactRole.ENGINEERING_BUNDLE
            else _MAX_RELEASE_ARTIFACT_BYTES
        )
        remaining = _MAX_RELEASE_CHAIN_BYTES - chain_size
        if remaining <= 0:
            raise InputError("component release chain exceeds its byte limit")
        value = parent.read_file(
            locator,
            maximum_bytes=min(maximum, remaining),
            field=f"component release artifact {locator}",
            expected_digest=artifact.digest,
        )
        chain_size += len(value)
        if chain_size > _MAX_RELEASE_CHAIN_BYTES:
            raise InputError("component release chain exceeds its byte limit")
        captured[locator] = value
    with tempfile.TemporaryDirectory(
        prefix="contrainte-component-release-"
    ) as directory:
        snapshot_root = Path(directory)
        snapshot_manifest = snapshot_root / parts[-1]
        snapshot_manifest.write_bytes(manifest_bytes)
        for locator, value in captured.items():
            (snapshot_root / locator).write_bytes(value)
        reproduced_manifest, shape = reproduce_local_component_shape(snapshot_manifest)
    if reproduced_manifest.as_dict() != manifest.as_dict():
        raise IntegrityError("component manifest snapshot did not reproduce")
    return manifest, shape, manifest_bytes


def _capture_bound_prepared_set(
    directory: _BoundDirectory,
    documents: dict[str, bytes],
    *,
    compare: bool,
    error_type: type[InputError | IntegrityError] = IntegrityError,
) -> dict[str, bytes]:
    captured, retained = _capture_bound_prepared_set_retained(
        directory, documents, compare=compare, error_type=error_type
    )
    try:
        return captured
    finally:
        for item in retained:
            item.close()


def _capture_bound_prepared_set_retained(
    directory: _BoundDirectory,
    documents: dict[str, bytes],
    *,
    compare: bool,
    error_type: type[InputError | IntegrityError] = IntegrityError,
) -> tuple[dict[str, bytes], tuple[_RetainedBoundFile, ...]]:
    if directory.names() != set(documents):
        raise IntegrityError(
            "prepared output directory must contain exactly the three prepared files"
        )
    captured: dict[str, bytes] = {}
    retained: list[_RetainedBoundFile] = []
    try:
        for name, expected in documents.items():
            item = _open_retained_bound_file(
                directory,
                name,
                maximum_bytes=_MAX_SOURCE_BYTES,
                field=f"prepared output {name}",
                expected_digest=_sha256_bytes(expected) if compare else None,
                error_type=error_type,
            )
            retained.append(item)
            if compare and item.captured != expected:
                raise IntegrityError(f"prepared output bytes changed: {name}")
            captured[name] = item.captured
        if directory.names() != set(documents):
            raise IntegrityError("prepared output set changed while it was captured")
        for item in retained:
            item.verify_visible()
        return captured, tuple(retained)
    except BaseException:
        for item in retained:
            item.close()
        raise


def _discard_bound_prepared_directory(
    parent: _BoundDirectory,
    directory: _BoundDirectory,
    expected_names: tuple[str, ...],
) -> None:
    names = directory.names()
    if not names.issubset(set(expected_names)):
        raise IntegrityError("transaction directory contains foreign entries")
    for name in sorted(names):
        directory.delete_child_file(name)
    parent.delete_child_directory(directory)


@dataclass(slots=True)
class _BoundPreparedTransaction:
    parent: _BoundDirectory
    destination: _BoundDirectory
    stage_name: str
    destination_name: str
    backup: _BoundDirectory | None
    expected_names: tuple[str, ...]
    previous_documents: dict[str, bytes]
    active: bool = True

    def rollback(self) -> None:
        if not self.active:
            return
        backup = self.backup
        try:
            self.parent.rename_child_handle(self.destination, self.stage_name)
            if backup is not None:
                self.parent.rename_child_handle(backup, self.destination_name)
            _discard_bound_prepared_directory(
                self.parent, self.destination, self.expected_names
            )
            self.active = False
        finally:
            if backup is not None:
                backup.close()

    def commit(
        self, retained_output_files: tuple[_RetainedBoundFile, ...] = ()
    ) -> None:
        if not self.active:
            return
        backup = self.backup
        try:
            if backup is not None:
                try:
                    _discard_bound_prepared_directory(
                        self.parent, backup, self.expected_names
                    )
                except (ContrainteError, OSError) as cleanup_exc:
                    for retained in retained_output_files:
                        retained.close()
                    self._restore_after_backup_cleanup_failure(cleanup_exc)
            self.active = False
        finally:
            if backup is not None:
                backup.close()

    def _restore_after_backup_cleanup_failure(self, cleanup_exc: Exception) -> None:
        backup = self.backup
        if backup is None:
            raise AssertionError("backup restoration requires a prior directory")
        restore: _BoundDirectory | None = None
        try:
            self.parent.rename_child_handle(self.destination, self.stage_name)
            restore = backup
            if backup.closed:
                restore_name = _unique_transaction_name(
                    self.parent, f"{self.destination_name}.restore"
                )
                restore = self.parent.create_child_directory(restore_name)
            remaining_names = restore.names()
            if not remaining_names.issubset(set(self.previous_documents)):
                raise IntegrityError(
                    "partially cleaned prepared backup contains foreign entries"
                )
            for name in sorted(remaining_names):
                retained = _open_retained_bound_file(
                    restore,
                    name,
                    maximum_bytes=_MAX_SOURCE_BYTES,
                    field=f"partially cleaned prepared backup {name}",
                    expected_digest=None,
                    error_type=IntegrityError,
                )
                try:
                    if retained.captured != self.previous_documents[name]:
                        raise IntegrityError(
                            f"partially cleaned prepared backup changed: {name}"
                        )
                finally:
                    retained.close()
            for name, captured in self.previous_documents.items():
                if name not in remaining_names:
                    restore.write_new_file(
                        name,
                        captured,
                        field=f"restored prepared backup {name}",
                    )
            _capture_bound_prepared_set(restore, self.previous_documents, compare=True)
            self.parent.rename_child_handle(restore, self.destination_name)
            _discard_bound_prepared_directory(
                self.parent, self.destination, self.expected_names
            )
            self.active = False
        except (ContrainteError, OSError) as restore_exc:
            retained_name = (
                restore.path.name if restore is not None else backup.path.name
            )
            if restore is not None and restore is not backup:
                restore.close()
            raise IntegrityError(
                "prepared backup cleanup failed and the prior exact set could not "
                f"be reconstructed; retained directory: {retained_name}"
            ) from restore_exc
        if restore is not None and restore is not backup:
            restore.close()
        raise IntegrityError(
            "prepared backup cleanup failed; the previous exact set was restored"
        ) from cleanup_exc


def _unique_transaction_name(parent: _BoundDirectory, prefix: str) -> str:
    for _ in range(128):
        name = f".{prefix}-{secrets.token_hex(12)}"
        if name not in parent.names():
            return name
    raise ExecutionError("cannot allocate a unique transaction directory")


def _publish_bound_prepared_set(
    parent: _BoundDirectory,
    destination_name: str,
    documents: dict[str, bytes],
) -> _BoundPreparedTransaction:
    expected_names = tuple(documents)
    parent_names = parent.names()
    prior: _BoundDirectory | None = None
    previous_documents: dict[str, bytes] = {}
    if destination_name in parent_names:
        prior = parent.child_directory(destination_name, deletable=True)
        try:
            existing_names = prior.names()
            if existing_names not in (set(), set(expected_names)):
                raise InputError(
                    "prepared output directory contains a partial set or foreign entries"
                )
            if existing_names:
                previous_documents = _capture_bound_prepared_set(
                    prior, documents, compare=False, error_type=InputError
                )
        except BaseException:
            prior.close()
            raise
    stage_name = _unique_transaction_name(parent, f"{destination_name}.tmp")
    stage = parent.create_child_directory(stage_name)
    try:
        for name, captured in documents.items():
            stage.write_new_file(name, captured, field=f"staged prepared output {name}")
        _capture_bound_prepared_set(stage, documents, compare=True)
    except BaseException:
        try:
            _discard_bound_prepared_directory(parent, stage, expected_names)
        finally:
            if prior is not None:
                prior.close()
        raise

    backup: _BoundDirectory | None = None
    try:
        if prior is not None:
            backup_name = _unique_transaction_name(
                parent, f"{destination_name}.previous"
            )
            try:
                parent.rename_child_handle(prior, backup_name)
            except BaseException:
                if prior.path.name == backup_name:
                    backup = prior
                raise
            backup = prior
        parent.rename_child_handle(stage, destination_name)
        _capture_bound_prepared_set(stage, documents, compare=True)
    except BaseException:
        try:
            if stage.path.name == destination_name:
                parent.rename_child_handle(stage, stage_name)
            if backup is not None:
                parent.rename_child_handle(backup, destination_name)
            _discard_bound_prepared_directory(parent, stage, expected_names)
        except BaseException as rollback_exc:
            raise IntegrityError(
                "prepared output promotion failed and rollback was incomplete"
            ) from rollback_exc
        finally:
            if prior is not None:
                prior.close()
        raise
    return _BoundPreparedTransaction(
        parent,
        stage,
        stage_name,
        destination_name,
        backup,
        expected_names,
        previous_documents,
    )


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


def _direct_directory_identity(path: Path) -> tuple[int, int, int]:
    try:
        metadata = path.lstat()
    except OSError as exc:
        raise IntegrityError(f"bound directory is unavailable: {path}") from exc
    if stat.S_ISLNK(metadata.st_mode) or _is_link_or_reparse(path):
        raise IntegrityError(f"bound directory became a link or reparse point: {path}")
    if not stat.S_ISDIR(metadata.st_mode):
        raise IntegrityError(f"bound directory is no longer a directory: {path}")
    return metadata.st_dev, metadata.st_ino, metadata.st_mode


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
        artifact_path = directory / name
        try:
            metadata = artifact_path.lstat()
        except FileNotFoundError as exc:
            raise IntegrityError(f"bundle artifact is missing: {name}") from exc
        except OSError as exc:
            raise IntegrityError(f"bundle artifact is unavailable: {name}") from exc
        if stat.S_ISLNK(metadata.st_mode) or _is_link_or_reparse(artifact_path):
            raise IntegrityError(
                f"bundle artifact {name} cannot be a link or reparse point"
            )
        if not stat.S_ISREG(metadata.st_mode):
            raise IntegrityError(f"bundle artifact {name} must be a regular file")
        if metadata.st_nlink != 1:
            raise IntegrityError(f"bundle artifact {name} cannot be hard-linked")
        if metadata.st_size != item["size_bytes"]:
            raise IntegrityError(f"bundle artifact size mismatch: {name}")
        value = _read_stable_file(
            artifact_path,
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


def prepare_component_assembly(
    interface_template_locator: str,
    assembly_template_locator: str,
    source_root: str | Path,
    output_directory: str | Path,
) -> dict[str, str]:
    """Bind local releases into canonical, digest-pinned assembly documents.

    Preparation is an authoring operation, not a relaxation of compilation. It
    consumes the manifest locators from an assembly template, independently
    reproduces those releases, replaces the interface template's embedded
    manifests, solves and replays the exact interface problem, and publishes a
    new strict component assembly that pins every consumed byte snapshot.
    """

    with localcontext(_EXECUTION_CONTEXT):
        return _prepare_component_assembly_handle_bound(
            interface_template_locator,
            assembly_template_locator,
            source_root,
            output_directory,
        )


def _prepare_component_assembly_handle_bound(
    interface_template_locator: str,
    assembly_template_locator: str,
    source_root: str | Path,
    output_directory: str | Path,
) -> dict[str, str]:
    root = _source_root(source_root)
    tree = _BoundSourceTree.open(root)
    try:
        interface_locator = _locator(
            interface_template_locator, "interface_template_locator"
        )
        assembly_locator = _locator(
            assembly_template_locator, "assembly_template_locator"
        )
        interface_template_bytes = tree.read_locator(
            interface_locator,
            maximum_bytes=_MAX_SOURCE_BYTES,
            field="interface assembly template",
        )
        assembly_template_bytes = tree.read_locator(
            assembly_locator,
            maximum_bytes=_MAX_SOURCE_BYTES,
            field="component assembly template",
        )
        interface_template = InterfaceAssembly.from_dict(
            loads_strict(interface_template_bytes)
        )
        assembly_template = ComponentAssembly.from_dict(
            loads_strict(assembly_template_bytes)
        )
        if assembly_template.interface_assembly.locator != interface_locator:
            raise InputError(
                "component assembly template must reference the supplied interface template"
            )
        occurrence_ids = tuple(
            occurrence.occurrence_id for occurrence in interface_template.occurrences
        )
        binding_ids = tuple(
            binding.occurrence_id for binding in assembly_template.component_bindings
        )
        if binding_ids != tuple(sorted(occurrence_ids)):
            raise InputError(
                "component assembly template bindings must exactly cover interface "
                "template occurrences"
            )

        current_manifests: dict[str, ComponentManifest] = {}
        prepared_bindings: list[dict[str, str]] = []
        protected_locators = {
            interface_locator,
            assembly_locator,
            assembly_template.interface_result.locator,
        }
        for binding in assembly_template.component_bindings:
            manifest, _, manifest_bytes = _bound_release_snapshot(
                tree, binding.manifest_locator
            )
            if manifest.schema_version != COMPONENT_SCHEMA_V3:
                raise InputError(
                    "component assembly preparation requires "
                    "component-manifest/0.3 releases"
                )
            current_manifests[binding.occurrence_id] = manifest
            protected_locators.add(binding.manifest_locator)
            manifest_parent = PurePosixPath(binding.manifest_locator).parent
            protected_locators.update(
                (manifest_parent / artifact.locator).as_posix()
                for artifact in manifest.artifacts
            )
            prepared_bindings.append(
                {
                    "occurrence_id": binding.occurrence_id,
                    "manifest_locator": binding.manifest_locator,
                    "manifest_file_digest": _sha256_bytes(manifest_bytes),
                    "manifest_digest": manifest.manifest_digest,
                }
            )
        tree.verify_visible()

        interface_document = interface_template.as_dict()
        for occurrence in interface_document["occurrences"]:
            occurrence["component"] = current_manifests[
                occurrence["occurrence_id"]
            ].as_dict()
        prepared_interface = InterfaceAssembly.from_dict(interface_document)
        prepared_result = solve_interface_assembly(prepared_interface)
        if prepared_result.status is not SolveStatus.SOLVED:
            raise ExecutionError(
                "prepared interface assembly is not solved: "
                f"{prepared_result.status.value}"
            )
        if not verify_interface_assembly_result(prepared_interface, prepared_result):
            raise IntegrityError(
                "prepared interface assembly result does not independently reproduce"
            )

        output_parts = _bound_output_parts(root, output_directory)
        output_parent = tree.directory(tuple(output_parts[:-1]), create=True)
        destination_name = output_parts[-1]
        relative_directory = PurePosixPath(*output_parts).as_posix()
        interface_name = f"{assembly_template.assembly_id}.interface.json"
        result_name = f"{assembly_template.assembly_id}.interface-result.json"
        assembly_name = f"{assembly_template.assembly_id}.component-assembly.json"

        def output_locator(name: str) -> str:
            return _locator(f"{relative_directory}/{name}", f"prepared output {name}")

        output_locators = {
            output_locator(interface_name),
            output_locator(result_name),
            output_locator(assembly_name),
        }
        if protected_locators & output_locators:
            raise InputError("prepared outputs cannot overwrite their source inputs")
        interface_bytes = dumps_pretty(prepared_interface.as_dict()).encode("utf-8")
        result_bytes = dumps_pretty(prepared_result.as_dict()).encode("utf-8")
        assembly_document = assembly_template.as_dict()
        assembly_document["interface_assembly"] = {
            "locator": output_locator(interface_name),
            "file_digest": _sha256_bytes(interface_bytes),
        }
        assembly_document["interface_result"] = {
            "locator": output_locator(result_name),
            "file_digest": _sha256_bytes(result_bytes),
        }
        assembly_document["component_bindings"] = prepared_bindings
        prepared_assembly = ComponentAssembly.from_dict(assembly_document)
        assembly_bytes = dumps_pretty(prepared_assembly.as_dict()).encode("utf-8")
        documents = {
            interface_name: interface_bytes,
            result_name: result_bytes,
            assembly_name: assembly_bytes,
        }
        if any(len(captured) > _MAX_SOURCE_BYTES for captured in documents.values()):
            raise ExecutionError("a prepared document exceeds its byte limit")

        transaction = _publish_bound_prepared_set(
            output_parent, destination_name, documents
        )
        tree.directories[tuple(output_parts)] = transaction.destination
        final_retained: tuple[_RetainedBoundFile, ...] = ()
        try:
            tree.verify_visible()
            first_final = _capture_bound_prepared_set(
                transaction.destination, documents, compare=True
            )
            reloaded = ComponentAssembly.from_dict(
                loads_strict(first_final[assembly_name])
            )
            if reloaded != prepared_assembly:
                raise IntegrityError(
                    "prepared component assembly does not strictly reload"
                )
            _load_bound_context(reloaded, tree)
            tree.verify_visible()
            final, final_retained = _capture_bound_prepared_set_retained(
                transaction.destination, documents, compare=True
            )
            tree.verify_visible()
            final_interface = InterfaceAssembly.from_dict(
                loads_strict(final[interface_name])
            )
            final_result = InterfaceAssemblyResult.from_dict(
                loads_strict(final[result_name])
            )
            final_assembly = ComponentAssembly.from_dict(
                loads_strict(final[assembly_name])
            )
            if (
                final_interface != prepared_interface
                or final_result != prepared_result
                or final_assembly != prepared_assembly
            ):
                raise IntegrityError("final prepared snapshots changed semantically")
            tree.verify_visible()
        except BaseException:
            for item in final_retained:
                item.close()
            final_retained = ()
            transaction.rollback()
            raise
        report = {
            "status": "prepared",
            "interface_locator": output_locator(interface_name),
            "interface_file_digest": _sha256_bytes(final[interface_name]),
            "interface_digest": digest(final_interface.as_dict()),
            "result_locator": output_locator(result_name),
            "result_file_digest": _sha256_bytes(final[result_name]),
            "result_digest": digest(final_result.as_dict()),
            "assembly_locator": output_locator(assembly_name),
            "assembly_file_digest": _sha256_bytes(final[assembly_name]),
            "assembly_digest": final_assembly.assembly_digest,
        }
        try:
            for item in final_retained:
                item.verify_visible()
            tree.verify_visible()
            transaction.commit(final_retained)
            for item in final_retained:
                item.verify_visible()
            tree.verify_visible()
            return report
        finally:
            for item in final_retained:
                item.close()
    finally:
        tree.close()


def _bound_output_parts(root: Path, value: str | Path) -> tuple[str, ...]:
    try:
        supplied = Path(value)
    except (TypeError, ValueError) as exc:
        raise InputError("prepared output directory must be a filesystem path") from exc
    candidate = supplied if supplied.is_absolute() else root / supplied
    try:
        lexical = Path(os.path.abspath(candidate))
        relative = lexical.relative_to(root)
    except (OSError, ValueError) as exc:
        raise InputError(
            "prepared output directory must remain within the source root"
        ) from exc
    if not relative.parts:
        raise InputError("prepared output directory cannot be the source root")
    _locator(f"{relative.as_posix()}/prepared.json", "prepared output directory")
    return relative.parts


def _load_bound_context(
    assembly: ComponentAssembly, tree: _BoundSourceTree
) -> _LoadedContext:
    interface_bytes = tree.read_locator(
        assembly.interface_assembly.locator,
        maximum_bytes=_MAX_SOURCE_BYTES,
        field="interface assembly source file",
        expected_digest=assembly.interface_assembly.file_digest,
    )
    result_bytes = tree.read_locator(
        assembly.interface_result.locator,
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
        manifest, shape, manifest_bytes = _bound_release_snapshot(
            tree, binding.manifest_locator
        )
        if _sha256_bytes(manifest_bytes) != binding.manifest_file_digest:
            raise IntegrityError("source file digest mismatch")
        if manifest.schema_version != COMPONENT_SCHEMA_V3:
            raise InputError(
                "component assembly requires component-manifest/0.3 releases"
            )
        if manifest.manifest_digest != binding.manifest_digest:
            raise IntegrityError("component binding manifest digest mismatch")
        embedded = occurrence_index[binding.occurrence_id].component
        if manifest.as_dict() != embedded.as_dict():
            raise IntegrityError(
                "local manifest does not match embedded interface component: "
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
    return _LoadedContext(interface, result, shapes, tuple(source_records))


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
    assembly: ComponentAssembly,
    source_root: str | Path,
    *,
    guard: _DirectoryIdentityGuard | None = None,
) -> _LoadedContext:
    root = _source_root(source_root)
    if guard is not None:
        if root != guard.root:
            raise IntegrityError("component assembly source root identity changed")
        guard.verify()
    interface_path = _resolve_source_file(
        root,
        assembly.interface_assembly.locator,
        "interface_assembly",
        guard=guard,
    )
    result_path = _resolve_source_file(
        root, assembly.interface_result.locator, "interface_result", guard=guard
    )
    read_source = _read_stable_file if guard is None else _guarded_stable_file
    interface_bytes = read_source(
        *((guard, interface_path) if guard is not None else (interface_path,)),
        maximum_bytes=_MAX_SOURCE_BYTES,
        field="interface assembly source file",
        expected_digest=assembly.interface_assembly.file_digest,
    )
    result_bytes = read_source(
        *((guard, result_path) if guard is not None else (result_path,)),
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
            guard=guard,
        )
        manifest_bytes = read_source(
            *((guard, path) if guard is not None else (path,)),
            maximum_bytes=_MAX_SOURCE_BYTES,
            field="source file",
            expected_digest=binding.manifest_file_digest,
        )
        manifest, shape = _reproduce_component_from_snapshots(
            path, manifest_bytes, guard=guard
        )
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
    if guard is not None:
        guard.verify()
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


def _resolve_source_file(
    root: Path,
    locator: str,
    field: str,
    *,
    guard: _DirectoryIdentityGuard | None = None,
) -> Path:
    relative = PurePosixPath(locator)
    current = root
    if guard is not None:
        guard.verify()
    for index, part in enumerate(relative.parts):
        current = current / part
        if _is_link_or_reparse(current):
            raise InputError(f"{field} cannot traverse a link or reparse point")
        if guard is not None and index < len(relative.parts) - 1:
            guard.bind(current)
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
    if guard is not None:
        guard.verify()
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
    manifest_path: Path,
    manifest_bytes: bytes,
    *,
    guard: _DirectoryIdentityGuard | None = None,
) -> tuple[ComponentManifest, Any]:
    if guard is not None:
        guard.bind(manifest_path.parent)
        guard.verify()
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
        if guard is not None:
            guard.verify()
        size = _release_artifact_preflight(candidate, locator, maximum)
        if guard is not None:
            guard.verify()
        chain_size += size
        if chain_size > _MAX_RELEASE_CHAIN_BYTES:
            raise InputError("component release chain exceeds its byte limit")
        artifact_paths[locator] = (candidate, maximum, artifact.digest)

    captured: dict[str, bytes] = {}
    remaining = _MAX_RELEASE_CHAIN_BYTES - len(manifest_bytes)
    for locator, (candidate, maximum, expected_digest) in artifact_paths.items():
        if guard is None:
            value = _read_stable_file(
                candidate,
                maximum_bytes=min(maximum, remaining),
                field=f"component release artifact {locator}",
                expected_digest=expected_digest,
            )
        else:
            value = _guarded_stable_file(
                guard,
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
    if guard is not None:
        guard.verify()
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
