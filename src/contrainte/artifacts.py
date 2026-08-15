from __future__ import annotations

import hashlib
import re
from collections.abc import Mapping
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Any

from .errors import IntegrityError

_SHA256 = re.compile(r"^sha256:[0-9a-f]{64}$")


def file_digest(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            hasher.update(block)
    return f"sha256:{hasher.hexdigest()}"


def artifact_descriptor(path: Path, media_type: str, role: str) -> dict[str, Any]:
    return {
        "path": path.name,
        "media_type": media_type,
        "role": role,
        "digest": file_digest(path),
        "size_bytes": path.stat().st_size,
    }


def verify_artifacts(
    bundle_directory: Path,
    raw: Any,
    expected: Mapping[str, tuple[str, str]],
) -> None:
    if not isinstance(raw, list):
        raise IntegrityError("bundle artifacts must be a list")
    if len(raw) != len(expected):
        raise IntegrityError("bundle artifact set is incomplete or contains extras")
    descriptors: dict[str, Mapping[str, Any]] = {}
    required_fields = {"path", "media_type", "role", "digest", "size_bytes"}
    for index, item in enumerate(raw):
        if not isinstance(item, dict) or set(item) != required_fields:
            raise IntegrityError(
                f"bundle artifact[{index}] has unsupported or missing fields"
            )
        relative = item.get("path")
        if (
            not isinstance(relative, str)
            or not relative
            or Path(relative).is_absolute()
            or Path(relative).name != relative
            or relative in {".", ".."}
        ):
            raise IntegrityError(
                f"bundle artifact[{index}].path must be one safe file name"
            )
        if relative in descriptors:
            raise IntegrityError(f"bundle artifact path is duplicated: {relative}")
        descriptors[relative] = item
    if set(descriptors) != set(expected):
        raise IntegrityError("bundle artifact paths do not match the schema contract")
    for relative, (media_type, role) in expected.items():
        descriptor = descriptors[relative]
        if descriptor.get("media_type") != media_type:
            raise IntegrityError(f"bundle artifact media type mismatch: {relative}")
        if descriptor.get("role") != role:
            raise IntegrityError(f"bundle artifact role mismatch: {relative}")
        declared_digest = descriptor.get("digest")
        if not isinstance(declared_digest, str) or not _SHA256.fullmatch(
            declared_digest
        ):
            raise IntegrityError(f"bundle artifact digest is invalid: {relative}")
        declared_size = descriptor.get("size_bytes")
        if (
            not isinstance(declared_size, int)
            or isinstance(declared_size, bool)
            or declared_size < 0
        ):
            raise IntegrityError(f"bundle artifact size is invalid: {relative}")
        path = bundle_directory / relative
        if not path.is_file():
            raise IntegrityError(f"bundle artifact is missing: {relative}")
        if path.stat().st_size != declared_size:
            raise IntegrityError(f"bundle artifact size mismatch: {relative}")
        if file_digest(path) != declared_digest:
            raise IntegrityError(f"bundle artifact digest mismatch: {relative}")


def package_version(distribution: str) -> str:
    try:
        return version(distribution)
    except PackageNotFoundError:
        return "unknown"
