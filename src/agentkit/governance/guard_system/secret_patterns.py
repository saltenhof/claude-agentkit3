"""Shared secret-detection pattern source for hook and structural checks."""

from __future__ import annotations

import fnmatch
from dataclasses import dataclass
from enum import StrEnum


class SecretPatternKind(StrEnum):
    """Kinds of canonical secret-detection patterns."""

    FILE_EXTENSION = "file_extension"
    FILE_NAME = "file_name"
    CONTENT_PREFIX = "content_prefix"


@dataclass(frozen=True)
class SecretPattern:
    """One typed secret-detection pattern."""

    kind: SecretPatternKind
    value: str


@dataclass(frozen=True)
class SecretFileHit:
    """A path matched by the canonical secret filename pattern source."""

    path: str
    pattern: SecretPattern


@dataclass(frozen=True)
class SecretContentHit:
    """A diff-content line matched by the canonical secret content patterns."""

    path: str
    pattern: SecretPattern
    line: str


SECRET_FILE_PATTERNS: tuple[SecretPattern, ...] = (
    SecretPattern(SecretPatternKind.FILE_EXTENSION, ".env"),
    SecretPattern(SecretPatternKind.FILE_EXTENSION, ".pem"),
    SecretPattern(SecretPatternKind.FILE_EXTENSION, ".key"),
    SecretPattern(SecretPatternKind.FILE_EXTENSION, ".pfx"),
    SecretPattern(SecretPatternKind.FILE_EXTENSION, ".p12"),
    SecretPattern(SecretPatternKind.FILE_EXTENSION, ".keystore"),
    SecretPattern(SecretPatternKind.FILE_EXTENSION, ".jks"),
    SecretPattern(SecretPatternKind.FILE_NAME, "credentials.json"),
    SecretPattern(SecretPatternKind.FILE_NAME, "serviceaccount.json"),
    SecretPattern(SecretPatternKind.FILE_NAME, "*_secret*"),
    SecretPattern(SecretPatternKind.FILE_NAME, "*_token*"),
    SecretPattern(SecretPatternKind.FILE_NAME, "*_password*"),
)

SECRET_CONTENT_PATTERNS: tuple[SecretPattern, ...] = (
    SecretPattern(SecretPatternKind.CONTENT_PREFIX, "AK" "IA"),
    SecretPattern(SecretPatternKind.CONTENT_PREFIX, "gh" "p_"),
    SecretPattern(SecretPatternKind.CONTENT_PREFIX, "sk" "-"),
)


def find_secret_file_hits(paths: tuple[str, ...]) -> tuple[SecretFileHit, ...]:
    """Return file/name secret hits for ``paths`` using the shared source."""
    hits: list[SecretFileHit] = []
    for path in paths:
        match = secret_file_pattern_for(path)
        if match is not None:
            hits.append(SecretFileHit(path=path, pattern=match))
    return tuple(hits)


def secret_file_pattern_for(path: str) -> SecretPattern | None:
    """Return the first matching canonical secret file pattern for ``path``."""
    normalized = path.replace("\\", "/")
    basename = normalized.rsplit("/", maxsplit=1)[-1].lower()
    lowered = normalized.lower()
    for pattern in SECRET_FILE_PATTERNS:
        if pattern.kind is SecretPatternKind.FILE_EXTENSION:
            if lowered.endswith(pattern.value):
                return pattern
            continue
        if fnmatch.fnmatchcase(basename, pattern.value):
            return pattern
    return None


def find_secret_content_hits(
    added_lines: tuple[tuple[str, str], ...],
) -> tuple[SecretContentHit, ...]:
    """Return content secret hits from ``(path, added_line)`` diff entries."""
    hits: list[SecretContentHit] = []
    for path, line in added_lines:
        match = secret_content_pattern_for(line)
        if match is not None:
            hits.append(SecretContentHit(path=path, pattern=match, line=line))
    return tuple(hits)


def secret_content_pattern_for(line: str) -> SecretPattern | None:
    """Return the first matching canonical secret content pattern for ``line``."""
    for pattern in SECRET_CONTENT_PATTERNS:
        if pattern.value in line:
            return pattern
    return None


__all__ = [
    "SECRET_CONTENT_PATTERNS",
    "SECRET_FILE_PATTERNS",
    "SecretContentHit",
    "SecretFileHit",
    "SecretPattern",
    "SecretPatternKind",
    "find_secret_content_hits",
    "find_secret_file_hits",
    "secret_content_pattern_for",
    "secret_file_pattern_for",
]
