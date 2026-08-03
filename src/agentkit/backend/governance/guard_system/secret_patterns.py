"""Shared secret-detection pattern source for hook and structural checks."""

from __future__ import annotations

import fnmatch
import re
from dataclasses import dataclass
from enum import StrEnum

TOKEN_BODY_CHARACTERS = "A-Za-z0-9_-"


class SecretFilePatternKind(StrEnum):
    """Kinds of canonical secret-detection patterns over changed file paths."""

    FILE_EXTENSION = "file_extension"
    FILE_NAME = "file_name"


@dataclass(frozen=True)
class SecretFilePattern:
    """One typed secret-detection pattern over changed file paths."""

    kind: SecretFilePatternKind
    value: str


@dataclass(frozen=True)
class SecretTokenPattern:
    """One secret-token pattern for diff content.

    A hit requires the credential shape, not the mere character sequence:
    ``value`` must start a token — no token character may precede it — and at
    least ``min_body_length`` token characters must follow it. Prose that
    happens to contain the prefix inside a word (``risk-adjusted``) or a short
    look-alike is therefore not a hit.

    ``min_body_length`` is a **false-positive floor**, not an issuer contract:
    it is deliberately set below the shortest documented issuance so that a
    longer or changed issuer format still produces a hit. The issuer-side
    truth has no live checkpoint in this repository -- see FK-15 §15.5.2.

    Attributes:
        value: The literal credential prefix, anchored at a token start.
        min_body_length: Minimum number of token characters that must follow
            ``value`` for a hit.
    """

    value: str
    min_body_length: int


@dataclass(frozen=True)
class SecretFileHit:
    """A path matched by the canonical secret filename pattern source."""

    path: str
    pattern: SecretFilePattern


@dataclass(frozen=True)
class SecretContentHit:
    """A diff-content line matched by the canonical secret content patterns."""

    path: str
    pattern: SecretTokenPattern
    line: str


SECRET_FILE_PATTERNS: tuple[SecretFilePattern, ...] = (
    SecretFilePattern(SecretFilePatternKind.FILE_EXTENSION, ".env"),
    SecretFilePattern(SecretFilePatternKind.FILE_EXTENSION, ".pem"),
    SecretFilePattern(SecretFilePatternKind.FILE_EXTENSION, ".key"),
    SecretFilePattern(SecretFilePatternKind.FILE_EXTENSION, ".pfx"),
    SecretFilePattern(SecretFilePatternKind.FILE_EXTENSION, ".p12"),
    SecretFilePattern(SecretFilePatternKind.FILE_EXTENSION, ".keystore"),
    SecretFilePattern(SecretFilePatternKind.FILE_EXTENSION, ".jks"),
    # FK-15 §15.5.2 norms `.env.*`, not only `.env`.
    SecretFilePattern(SecretFilePatternKind.FILE_NAME, ".env.*"),
    SecretFilePattern(SecretFilePatternKind.FILE_NAME, "*.env.*"),
    SecretFilePattern(SecretFilePatternKind.FILE_NAME, "credentials.json"),
    SecretFilePattern(SecretFilePatternKind.FILE_NAME, "serviceaccount.json"),
    SecretFilePattern(SecretFilePatternKind.FILE_NAME, "*_secret*"),
    SecretFilePattern(SecretFilePatternKind.FILE_NAME, "*_token*"),
    SecretFilePattern(SecretFilePatternKind.FILE_NAME, "*_password*"),
)

# The floors are set BELOW the shortest documented issuance on purpose: a
# credential that grows or changes its alphabet must keep hitting. They are the
# point below which natural prose becomes plausible, not an issuer contract.
SECRET_CONTENT_PATTERNS: tuple[SecretTokenPattern, ...] = (
    # AWS long-term access key ID (`AccessKeyId` is 16-128 chars in total).
    SecretTokenPattern("AKIA", min_body_length=12),
    # AWS temporary STS access key ID.
    SecretTokenPattern("ASIA", min_body_length=12),
    # GitHub token families: personal, OAuth, user-to-server, server-to-server,
    # refresh, and the fine-grained `github_pat_` format.
    SecretTokenPattern("ghp_", min_body_length=16),
    SecretTokenPattern("gho_", min_body_length=16),
    SecretTokenPattern("ghu_", min_body_length=16),
    SecretTokenPattern("ghs_", min_body_length=16),
    SecretTokenPattern("ghr_", min_body_length=16),
    SecretTokenPattern("github_pat_", min_body_length=16),
    # OpenAI API key, including the `sk-proj-` and service-account forms.
    SecretTokenPattern("sk-", min_body_length=16),
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


def secret_file_pattern_for(path: str) -> SecretFilePattern | None:
    """Return the first matching canonical secret file pattern for ``path``."""
    normalized = path.replace("\\", "/")
    basename = normalized.rsplit("/", maxsplit=1)[-1].lower()
    lowered = normalized.lower()
    for pattern in SECRET_FILE_PATTERNS:
        if pattern.kind is SecretFilePatternKind.FILE_EXTENSION:
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
    "SecretFilePattern",
    "SecretFilePatternKind",
    "SecretTokenPattern",
    "find_secret_content_hits",
    "find_secret_file_hits",
    "secret_content_pattern_for",
    "secret_file_pattern_for",
]
