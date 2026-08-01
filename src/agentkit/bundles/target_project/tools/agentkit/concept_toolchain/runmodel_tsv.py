"""Strict TSV parsing against declared FK-78 column contracts."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING

from .runmodel_constants import RunModelConstants as Vocab
from .runmodel_validation import Issue

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path


@dataclass(frozen=True)
class TsvColumn:
    """Column contract of one TSV register column."""

    name: str
    allow_empty: bool = False
    check: Callable[[str], str | None] | None = None


TsvRow = dict[str, str]


def check_pattern(pattern: re.Pattern[str], what: str) -> Callable[[str], str | None]:
    """Build a checker for a regular-expression-bound value."""

    def check(value: str) -> str | None:
        return None if pattern.fullmatch(value) else f"must be a {what}, got {value!r}"

    return check


def check_int_value(value: str) -> str | None:
    """Validate a non-negative integer encoded as text."""
    return None if re.fullmatch(r"\d+", value) else f"must be a non-negative integer, got {value!r}"


def check_rel_path(value: str) -> str | None:
    """Validate a project-relative slash-separated path."""
    if value.startswith(("/", "\\")) or "\\" in value or ".." in value.split("/") or ":" in value.split("/", 1)[0]:
        return f"must be a project-relative '/'-path, got {value!r}"
    return None


def check_semicolon_list(pattern: re.Pattern[str], what: str) -> Callable[[str], str | None]:
    """Build a checker for a semicolon-separated list of grammar-bound IDs."""

    def check(value: str) -> str | None:
        for item in value.split(";"):
            if item == "" or pattern.fullmatch(item) is None:
                return f"must be a semicolon list of {what}s, got {value!r}"
        return None

    return check


def split_refs(value: str) -> tuple[str, ...]:
    """Split a semicolon-list field into its items (empty field: no items)."""
    return tuple(item for item in value.split(";") if item) if value else ()


def check_empty_reason(value: str) -> str | None:
    """Validate the disposition reason of an empty source unit."""
    if value == "NO_MATERIAL_CONTENT":
        return None
    if value.startswith("DUPLICATE_OF:"):
        suffix = value.removeprefix("DUPLICATE_OF:")
        return None if Vocab.UNIT_ID_RE.fullmatch(suffix) else f"DUPLICATE_OF must reference a unit id, got {suffix!r}"
    if value.startswith("OUT_OF_SCOPE:"):
        return None if value.removeprefix("OUT_OF_SCOPE:") else "OUT_OF_SCOPE requires a reason"
    return f"must be NO_MATERIAL_CONTENT, DUPLICATE_OF:<unit_id> or OUT_OF_SCOPE:<reason>, got {value!r}"


def check_residual_edge(value: str) -> str | None:
    """Validate a residual-edge disposition."""
    if value in ("CHECKED_AGAINST_CURRENT", "ESCALATED_TO_PO"):
        return None
    if value.startswith("NONE_REQUIRED:"):
        return None if value.removeprefix("NONE_REQUIRED:") else "NONE_REQUIRED requires a class"
    return f"must be CHECKED_AGAINST_CURRENT, ESCALATED_TO_PO or NONE_REQUIRED:<class>, got {value!r}"


def check_target_refs(value: str) -> str | None:
    """Validate a semicolon list of target references.

    ``<path>#<anchor>`` addresses a markdown section; a bare ``<path>``
    addresses a whole file or directory target (FK-78 target modes).
    """
    for item in value.split(";"):
        if item == "" or item.startswith("#") or item.endswith("#"):
            return f"must be a semicolon list of <path> or <path>#<anchor> references, got {value!r}"
    return None


def check_deferral(value: str) -> str | None:
    """Validate an owner/trigger/anchor deferral record."""
    parts = value.split(";")
    prefixes = ("owner=", "trigger=", "anchor=")
    malformed = any(not part.startswith(prefix) or part == prefix for part, prefix in zip(parts, prefixes, strict=False))
    if len(parts) != 3 or malformed:
        return f"must be 'owner=<x>;trigger=<y>;anchor=<path#anchor>', got {value!r}"
    if "#" not in parts[2].removeprefix("anchor="):
        return f"deferral anchor must be <path>#<anchor>, got {value!r}"
    return None


def check_input_refs(value: str) -> str | None:
    """Validate typed source and artifact input references."""
    for item in value.split(";"):
        if item.startswith("source:"):
            if Vocab.SOURCE_ID_RE.fullmatch(item.removeprefix("source:")) is None:
                return f"source ref must carry a source id, got {item!r}"
        elif item.startswith("artifact:"):
            if item.removeprefix("artifact:") == "":
                return f"artifact ref must carry a path, got {item!r}"
        else:
            return f"input refs must be typed as source:<source_id> or artifact:<path>, got {item!r}"
    return None


def check_enum_value(allowed: tuple[str, ...]) -> Callable[[str], str | None]:
    """Build a checker for one of the declared enum values."""

    def check(value: str) -> str | None:
        return None if value in allowed else f"must be one of {', '.join(allowed)}, got {value!r}"

    return check


def load_tsv(
    path: Path,
    columns: tuple[TsvColumn, ...],
    row_rule: Callable[[TsvRow], list[tuple[str, str]]] | None = None,
) -> tuple[tuple[TsvRow, ...], list[Issue]]:
    """Load and validate a TSV file against its declared contract."""
    try:
        text = path.read_bytes().decode("utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        return (), [Issue(locator="file", message=f"not readable as UTF-8 text: {exc}")]
    lines = text.split("\n")
    if lines and lines[-1] == "":
        lines.pop()
    header = "\t".join(column.name for column in columns)
    if not lines or lines[0] != header:
        return (), [Issue(locator="line 1", message=f"header must be exactly {header!r}")]
    issues: list[Issue] = []
    rows: list[TsvRow] = []
    previous_id: str | None = None
    for number, line in enumerate(lines[1:], start=2):
        row = _parse_tsv_row(line, number, columns, issues)
        if row is None:
            continue
        previous_id = _check_row_order(row, columns[0].name, previous_id, number, issues)
        issues.extend(
            Issue(locator=f"line {number}:{column}", message=message) for column, message in (row_rule(row) if row_rule else [])
        )
        rows.append(row)
    return tuple(rows), issues


def _parse_tsv_row(
    line: str, number: int, columns: tuple[TsvColumn, ...], issues: list[Issue]
) -> TsvRow | None:
    if line == "":
        issues.append(Issue(locator=f"line {number}", message="empty line is not allowed"))
        return None
    if "\r" in line:
        issues.append(Issue(locator=f"line {number}", message="carriage return inside a row is not allowed (LF-only TSV)"))
        return None
    fields = line.split("\t")
    if len(fields) != len(columns):
        issues.append(Issue(locator=f"line {number}", message=f"expected {len(columns)} tab-separated fields, got {len(fields)}"))
        return None
    row: TsvRow = {}
    for column, value in zip(columns, fields, strict=True):
        if value == "":
            if not column.allow_empty:
                issues.append(Issue(locator=f"line {number}:{column.name}", message="must not be empty"))
        elif column.check is not None:
            message = column.check(value)
            if message is not None:
                issues.append(Issue(locator=f"line {number}:{column.name}", message=message))
        row[column.name] = value
    return row


def _check_row_order(row: TsvRow, id_column: str, previous_id: str | None, number: int, issues: list[Issue]) -> str:
    current = row[id_column]
    if previous_id is not None and current <= previous_id:
        issues.append(
            Issue(
                locator=f"line {number}:{id_column}",
                message=f"rows must be strictly sorted by {id_column} ascending, {current!r} after {previous_id!r}",
            )
        )
    return current


CHECK_SHA = check_pattern(Vocab.SHA256_RE, "sha256 lowercase-hex digest")
CHECK_SHA_OR_GENESIS = check_pattern(
    Vocab.SHA256_RE, "sha256 lowercase-hex digest (or the all-zero genesis digest)"
)
