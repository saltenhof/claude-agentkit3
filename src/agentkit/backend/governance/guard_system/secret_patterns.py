"""Shared secret-detection pattern source for hook and structural checks."""

from __future__ import annotations

import fnmatch
import re
from dataclasses import dataclass
from enum import StrEnum

TOKEN_BODY_CHARACTERS = "A-Za-z0-9_-"


class SecretPatternKind(StrEnum):
    """Kinds of canonical secret-detection patterns."""

    FILE_EXTENSION = "file_extension"
    FILE_NAME = "file_name"
    TOKEN_PREFIX = "token_prefix"


@dataclass(frozen=True)
class SecretPattern:
    """One typed secret-detection pattern over changed file paths."""

    kind: SecretPatternKind
    value: str


@dataclass(frozen=True)
class SecretTokenPattern:
    """One secret-token pattern for diff content.

    A hit requires the credential shape, not the mere character sequence:
    ``value`` must start a token — no token character may precede it — and at
    least ``min_body_length`` token characters must follow it. Prose that
    happens to contain the prefix inside a word (``risk-adjusted``) or a short
    look-alike is therefore not a hit.

    Attributes:
        value: The literal credential prefix, anchored at a token start.
        min_body_length: Minimum number of token characters that must follow
            ``value``, taken from the shape the issuing system actually emits.
    """

    value: str
    min_body_length: int

    @property
    def kind(self) -> SecretPatternKind:
        """Return the pattern kind, fixed for every secret-token pattern."""
        return SecretPatternKind.TOKEN_PREFIX


@dataclass(frozen=True)
class SecretFileHit:
    """A path matched by the canonical secret filename pattern source."""

    path: str
    pattern: SecretPattern


@dataclass(frozen=True)
class SecretContentHit:
    """A diff-content line matched by the canonical secret content patterns."""

    path: str
    pattern: SecretTokenPattern
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

SECRET_CONTENT_PATTERNS: tuple[SecretTokenPattern, ...] = (
    # AWS access key ID: prefix plus 16 characters.
    SecretTokenPattern("AKIA", min_body_length=16),
    # GitHub personal access token: prefix plus 36 characters.
    SecretTokenPattern("ghp_", min_body_length=36),
    # OpenAI API key: prefix plus at least 20 characters.
    SecretTokenPattern("sk-", min_body_length=20),
)

_TOKEN_MATCHERS: tuple[tuple[SecretTokenPattern, re.Pattern[str]], ...] = tuple(
    (
        pattern,
        re.compile(
            f"(?<![{TOKEN_BODY_CHARACTERS}])"
            f"{re.escape(pattern.value)}"
            f"[{TOKEN_BODY_CHARACTERS}]{{{pattern.min_body_length},}}"
        ),
    )
    for pattern in SECRET_CONTENT_PATTERNS
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


def secret_content_pattern_for(line: str) -> SecretTokenPattern | None:
    """Return the first canonical secret-token pattern whose shape ``line`` carries."""
    for pattern, matcher in _TOKEN_MATCHERS:
        if matcher.search(line) is not None:
            return pattern
    return None


__all__ = [
    "SECRET_CONTENT_PATTERNS",
    "SECRET_FILE_PATTERNS",
    "TOKEN_BODY_CHARACTERS",
    "SecretContentHit",
    "SecretFileHit",
    "SecretPattern",
    "SecretPatternKind",
    "SecretTokenPattern",
    "find_secret_content_hits",
    "find_secret_file_hits",
    "secret_content_pattern_for",
    "secret_file_pattern_for",
]
