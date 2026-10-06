"""Strict closed-object parsing helpers shared by the physics schemas."""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from enum import Enum
from typing import Any

from ..errors import InputError

DIGEST_PATTERN = re.compile(r"^sha256:[0-9a-f]{64}$")
MAX_TEXT = 4000


class StalePinError(InputError):
    """Raised when a pinned rule set or group registry does not match the supplied one."""


def identifier_pattern(*prefixes: str) -> re.Pattern[str]:
    alternatives = "|".join(re.escape(prefix) for prefix in prefixes)
    return re.compile(rf"^(?:{alternatives})-[A-Z0-9]+(?:-[A-Z0-9]+)*$")


def obj(
    raw: Any, field: str, required: Iterable[str], optional: Iterable[str] = ()
) -> Mapping[str, Any]:
    if not isinstance(raw, dict):
        raise InputError(f"{field} must be an object")
    required = tuple(required)
    allowed = set(required) | set(optional)
    unknown = sorted(set(raw) - allowed)
    if unknown:
        raise InputError(f"{field} contains unsupported fields: {', '.join(unknown)}")
    missing = [name for name in required if name not in raw]
    if missing:
        raise InputError(f"{field} is missing required fields: {', '.join(missing)}")
    return raw


def text(raw: Mapping[str, Any], name: str, field: str) -> str:
    value = raw.get(name)
    if not isinstance(value, str) or not value:
        raise InputError(f"{field}.{name} must be a non-empty string")
    if value != value.strip():
        raise InputError(f"{field}.{name} must not have leading or trailing whitespace")
    if len(value) > MAX_TEXT:
        raise InputError(f"{field}.{name} exceeds {MAX_TEXT} characters")
    return value


def ident(
    raw: Mapping[str, Any], name: str, field: str, pattern: re.Pattern[str]
) -> str:
    value = raw.get(name)
    if not isinstance(value, str) or not pattern.fullmatch(value):
        raise InputError(f"{field}.{name} is not a valid identifier: {value!r}")
    return value


def enum[E: Enum](raw: Mapping[str, Any], name: str, field: str, kind: type[E]) -> E:
    value = raw.get(name)
    if isinstance(value, str):
        try:
            return kind(value)
        except ValueError:
            pass
    raise InputError(f"{field}.{name} is unsupported: {value!r}")


def boolean(raw: Mapping[str, Any], name: str, field: str) -> bool:
    value = raw.get(name)
    if not isinstance(value, bool):
        raise InputError(f"{field}.{name} must be a boolean")
    return value


def positive_int(raw: Mapping[str, Any], name: str, field: str) -> int:
    value = raw.get(name)
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise InputError(f"{field}.{name} must be a positive integer")
    return value


def digest_text(
    raw: Mapping[str, Any], name: str, field: str, *, nullable: bool = False
) -> str | None:
    value = raw.get(name)
    if value is None and nullable:
        return None
    if not isinstance(value, str) or not DIGEST_PATTERN.fullmatch(value):
        raise InputError(f"{field}.{name} must be a lowercase sha256 digest")
    return value


def array(
    raw: Mapping[str, Any], name: str, field: str, *, minimum: int = 0
) -> list[Any]:
    value = raw.get(name)
    if not isinstance(value, list):
        raise InputError(f"{field}.{name} must be a list")
    if len(value) < minimum:
        raise InputError(f"{field}.{name} must contain at least {minimum} item(s)")
    return value


def id_list(
    raw: Mapping[str, Any],
    name: str,
    field: str,
    pattern: re.Pattern[str],
    *,
    minimum: int = 0,
) -> tuple[str, ...]:
    values = array(raw, name, field, minimum=minimum)
    for index, item in enumerate(values):
        if not isinstance(item, str) or not pattern.fullmatch(item):
            raise InputError(
                f"{field}.{name}[{index}] is not a valid identifier: {item!r}"
            )
    unique(values, f"{field}.{name}")
    return tuple(values)


def enum_list[E: Enum](
    raw: Mapping[str, Any], name: str, field: str, kind: type[E], *, minimum: int = 0
) -> tuple[E, ...]:
    values = array(raw, name, field, minimum=minimum)
    parsed = []
    for index, item in enumerate(values):
        try:
            parsed.append(kind(item if isinstance(item, str) else None))
        except ValueError as exc:
            raise InputError(
                f"{field}.{name}[{index}] is unsupported: {item!r}"
            ) from exc
    unique(values, f"{field}.{name}")
    return tuple(parsed)


def unique(values: Iterable[Any], field: str) -> None:
    seen: set[Any] = set()
    for value in values:
        if value in seen:
            raise InputError(f"{field} contains duplicate identifier {value!r}")
        seen.add(value)


def resolve(values: Iterable[str], known: Iterable[str], field: str) -> None:
    known = set(known)
    missing = [value for value in values if value not in known]
    if missing:
        raise InputError(
            f"{field} references unknown identifiers: {', '.join(missing)}"
        )
