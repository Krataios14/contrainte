from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import fields, is_dataclass
from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from pathlib import Path
from typing import Any

from .errors import CanonicalizationError, InputError


def decimal_text(value: Decimal) -> str:
    """Return one non-exponent decimal representation with no insignificant zeros."""

    if not value.is_finite():
        raise CanonicalizationError("non-finite decimals are forbidden")
    if value == 0:
        return "0"
    rendered = format(value, "f")
    if "." in rendered:
        rendered = rendered.rstrip("0").rstrip(".")
    return rendered


def _primitive(value: Any) -> Any:
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        raise CanonicalizationError("binary floating-point values are forbidden")
    if isinstance(value, Decimal):
        return decimal_text(value)
    if isinstance(value, Enum):
        return _primitive(value.value)
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Path):
        return str(value)
    if is_dataclass(value):
        return {
            field.name: _primitive(getattr(value, field.name))
            for field in fields(value)
        }
    if isinstance(value, Mapping):
        result: dict[str, Any] = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise CanonicalizationError("canonical object keys must be strings")
            result[key] = _primitive(item)
        return result
    if isinstance(value, (list, tuple)):
        return [_primitive(item) for item in value]
    raise CanonicalizationError(f"unsupported canonical value: {type(value).__name__}")


def canonical_bytes(value: Any) -> bytes:
    primitive = _primitive(value)
    rendered = json.dumps(
        primitive,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return rendered.encode("utf-8")


def digest_bytes(content: bytes) -> str:
    return f"sha256:{hashlib.sha256(content).hexdigest()}"


def digest(value: Any) -> str:
    return digest_bytes(canonical_bytes(value))


def _reject_float(value: str) -> None:
    raise InputError(
        f"JSON floating-point literal {value!r} is forbidden; encode engineering decimals as strings"
    )


def loads_strict(content: str | bytes) -> Any:
    try:
        return json.loads(content, parse_float=_reject_float)
    except json.JSONDecodeError as exc:
        raise InputError(
            f"invalid JSON: {exc.msg} at line {exc.lineno}, column {exc.colno}"
        ) from exc


def dumps_pretty(value: Any) -> str:
    return (
        json.dumps(
            _primitive(value),
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            indent=2,
        )
        + "\n"
    )
