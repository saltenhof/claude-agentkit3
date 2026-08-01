"""Strict JSON field validation for FK-78 run artifacts."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import TYPE_CHECKING

from .runmodel_constants import RunModelConstants as Vocab

if TYPE_CHECKING:
    from collections.abc import Mapping
    from pathlib import Path


@dataclass(frozen=True)
class Issue:
    """One fail-closed validation issue inside an artifact."""

    locator: str
    message: str


class Ctx:
    """Issue accumulator shared by all field validators."""

    __slots__ = ("issues",)

    def __init__(self) -> None:
        self.issues: list[Issue] = []

    def error(self, locator: str, message: str) -> None:
        self.issues.append(Issue(locator=locator, message=message))


def read_json_object(path: Path) -> tuple[dict[str, object] | None, list[Issue]]:
    """Read a JSON file whose top-level value must be an object."""
    try:
        raw: object = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError) as exc:
        return None, [Issue(locator="file", message=f"not readable as JSON: {exc}")]
    if not isinstance(raw, dict):
        return None, [Issue(locator="file", message="top level must be a JSON object")]
    return raw, []


def check_keys(
    ctx: Ctx,
    obj: Mapping[str, object],
    where: str,
    required: tuple[str, ...],
    optional: tuple[str, ...] = (),
) -> None:
    """Report unknown and missing object fields."""
    unknown = sorted(set(obj) - set(required) - set(optional))
    missing = sorted(set(required) - set(obj))
    for key in unknown:
        ctx.error(where, f"unknown field {key!r}")
    for key in missing:
        ctx.error(where, f"missing required field {key!r}")


def read_str(ctx: Ctx, obj: Mapping[str, object], where: str, key: str, *, allow_empty: bool = False) -> str:
    """Read a required string field."""
    if key not in obj:
        return ""
    value = obj[key]
    if not isinstance(value, str) or (value == "" and not allow_empty):
        ctx.error(f"{where}.{key}", "must be a non-empty string")
        return ""
    return value


def read_optional_str(ctx: Ctx, obj: Mapping[str, object], where: str, key: str) -> str | None:
    """Read an optional nullable string field."""
    if key not in obj:
        return None
    value = obj[key]
    if value is None:
        return None
    if not isinstance(value, str) or value == "":
        ctx.error(f"{where}.{key}", "must be a non-empty string or null")
        return None
    return value


def read_int(ctx: Ctx, obj: Mapping[str, object], where: str, key: str, *, minimum: int = 0) -> int:
    """Read an integer field with an inclusive lower bound."""
    if key not in obj:
        return minimum
    value = obj[key]
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        ctx.error(f"{where}.{key}", f"must be an integer >= {minimum}")
        return minimum
    return value


def read_bool(ctx: Ctx, obj: Mapping[str, object], where: str, key: str) -> bool:
    """Read a boolean field."""
    if key not in obj:
        return False
    value = obj[key]
    if not isinstance(value, bool):
        ctx.error(f"{where}.{key}", "must be a boolean")
        return False
    return value


def read_enum(ctx: Ctx, obj: Mapping[str, object], where: str, key: str, allowed: tuple[str, ...]) -> str:
    """Read a string field constrained to an enum."""
    value = read_str(ctx, obj, where, key)
    if value and value not in allowed:
        ctx.error(f"{where}.{key}", f"must be one of {', '.join(allowed)}, got {value!r}")
        return ""
    return value


def read_matched(
    ctx: Ctx,
    obj: Mapping[str, object],
    where: str,
    key: str,
    pattern: re.Pattern[str],
    what: str,
) -> str:
    """Read a string field constrained by a regular expression."""
    value = read_str(ctx, obj, where, key)
    if value and pattern.fullmatch(value) is None:
        ctx.error(f"{where}.{key}", f"must be a {what}, got {value!r}")
    return value


def read_sha(ctx: Ctx, obj: Mapping[str, object], where: str, key: str) -> str:
    """Read a lowercase hexadecimal SHA-256 digest."""
    return read_matched(ctx, obj, where, key, Vocab.SHA256_RE, "sha256 lowercase-hex digest")


def read_sha_or_null(ctx: Ctx, obj: Mapping[str, object], where: str, key: str) -> str | None:
    """Read a nullable lowercase hexadecimal SHA-256 digest."""
    value = read_optional_str(ctx, obj, where, key)
    if value is not None and Vocab.SHA256_RE.fullmatch(value) is None:
        ctx.error(f"{where}.{key}", f"must be a sha256 lowercase-hex digest or null, got {value!r}")
        return None
    return value


def read_time(ctx: Ctx, obj: Mapping[str, object], where: str, key: str) -> str:
    """Read a UTC ISO-8601 timestamp with a Z suffix."""
    return read_matched(ctx, obj, where, key, Vocab.TIMESTAMP_RE, "UTC ISO-8601 timestamp with Z suffix")


def read_semver(ctx: Ctx, obj: Mapping[str, object], where: str) -> str:
    """Read the major-version-one schema version."""
    value = read_str(ctx, obj, where, "schema_version")
    if value and re.fullmatch(r"1\.\d+\.\d+", value) is None:
        ctx.error(f"{where}.schema_version", f"must be SemVer with major 1, got {value!r}")
    return value


def read_str_list(
    ctx: Ctx,
    obj: Mapping[str, object],
    where: str,
    key: str,
    pattern: re.Pattern[str] | None = None,
    what: str = "value",
) -> tuple[str, ...]:
    """Read an array of non-empty strings with an optional grammar."""
    if key not in obj:
        return ()
    value = obj[key]
    if not isinstance(value, list):
        ctx.error(f"{where}.{key}", Vocab.ARRAY_REQUIRED)
        return ()
    items: list[str] = []
    for index, item in enumerate(value):
        if not isinstance(item, str) or item == "":
            ctx.error(f"{where}.{key}[{index}]", "must be a non-empty string")
            continue
        if pattern is not None and pattern.fullmatch(item) is None:
            ctx.error(f"{where}.{key}[{index}]", f"must be a {what}, got {item!r}")
            continue
        items.append(item)
    return tuple(items)


def read_object_items(
    ctx: Ctx, obj: Mapping[str, object], where: str, key: str
) -> list[tuple[str, dict[str, object]]]:
    """Read an array whose entries must all be objects."""
    if key not in obj:
        return []
    value = obj[key]
    if not isinstance(value, list):
        ctx.error(f"{where}.{key}", Vocab.ARRAY_REQUIRED)
        return []
    items: list[tuple[str, dict[str, object]]] = []
    for index, item in enumerate(value):
        if not isinstance(item, dict):
            ctx.error(f"{where}.{key}[{index}]", "must be an object")
            continue
        items.append((f"{where}.{key}[{index}]", item))
    return items


def read_sub_object(ctx: Ctx, obj: Mapping[str, object], where: str, key: str) -> dict[str, object] | None:
    """Read a required object field."""
    if key not in obj:
        return None
    value = obj[key]
    if not isinstance(value, dict):
        ctx.error(f"{where}.{key}", "must be an object")
        return None
    return value


def read_nullable_object(ctx: Ctx, obj: Mapping[str, object], where: str, key: str) -> dict[str, object] | None:
    """Read an optional nullable object field."""
    if key not in obj or obj[key] is None:
        return None
    return read_sub_object(ctx, obj, where, key)
