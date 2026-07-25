""".conceptignore glob matching (FK-13 §13.9.13).

Implements ``.gitignore``-style pattern semantics for concept discovery, with
correct ``**`` handling. This is NOT a bare :meth:`pathlib.Path.match` -- that
does not implement ``**`` across path segments.

Pattern semantics (FK-13 §13.9.13):
- Patterns are glob expressions relative to the concept root.
- ``*`` matches any characters WITHIN a path segment (not ``/``).
- ``**`` matches zero or more path segments (including ``/``).
- ``?`` matches exactly one character (not ``/``).
- ``research/**`` matches everything under ``research/`` (direct children + any
  depth).
- ``research/**/*`` matches only in subdirectories of ``research/``, NOT direct
  children.
- ``*.md`` matches ``foo.md``, NOT ``sub/foo.md``.
- Leading/trailing whitespace trimmed; blank lines and ``#``-comment lines
  ignored.
- No fallback when the file is absent: all ``.md`` files are processed.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterable, Sequence
    from pathlib import Path


@dataclass(frozen=True)
class IgnorePattern:
    """One compiled ``.conceptignore`` pattern."""

    raw: str
    regex: re.Pattern[str]

    def matches(self, rel_posix: str) -> bool:
        """Return ``True`` if ``rel_posix`` (POSIX relative path) is ignored."""
        return self.regex.search(rel_posix) is not None


def _glob_to_regex(pattern: str) -> str:
    """Translate an ignore glob pattern to an anchored regex.

    Implements ``*``, ``?`` and ``**`` per FK-13 §13.9.13 semantics. Crucially
    ``research/**/*`` matches only in SUBDIRECTORIES of ``research/`` (the
    explicit ``/<glob>`` after ``**`` forces at least one path segment), while
    ``research/**`` matches direct children too.
    """
    i = 0
    n = len(pattern)
    out: list[str] = ["^"]
    while i < n:
        ch = pattern[i]
        if ch == "*":
            if i + 1 < n and pattern[i + 1] == "*":
                # '**'
                j = i + 2
                if j >= n:
                    # '**' at end -> match everything remaining (direct + deep).
                    out.append(r".*")
                    i = j
                elif pattern[j] == "/" and j + 1 < n:
                    # '**/<rest>' -> at least one path segment required.
                    out.append(r"(?:[^/]+/)+")
                    i = j + 1
                else:
                    # '**' followed by a non-slash, or '**/' at end.
                    out.append(r".*")
                    i = j + 1 if (j < n and pattern[j] == "/") else j
            else:
                # '*' -- within a segment, no '/'.
                out.append(r"[^/]*")
                i += 1
        elif ch == "?":
            out.append(r"[^/]")
            i += 1
        elif ch in r".+()|^$\\{}[]":
            out.append(re.escape(ch))
            i += 1
        else:
            out.append(re.escape(ch))
            i += 1
    out.append("$")
    return "".join(out)


def load_patterns(lines: Iterable[str]) -> list[IgnorePattern]:
    """Parse ``.conceptignore`` text lines into compiled patterns.

    Blank lines and ``#`` comments are dropped; whitespace is trimmed.
    """
    patterns: list[IgnorePattern] = []
    for raw in lines:
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        patterns.append(IgnorePattern(raw=line, regex=re.compile(_glob_to_regex(line))))
    return patterns


def load_ignore_file(path: Path) -> list[IgnorePattern]:
    """Load patterns from a ``.conceptignore`` file; ``[]`` when absent."""
    if not path.is_file():
        return []
    return load_patterns(path.read_text(encoding="utf-8").splitlines())


def is_ignored(rel_posix: str, patterns: Sequence[IgnorePattern]) -> bool:
    """Return ``True`` when ``rel_posix`` matches any ignore pattern."""
    return any(p.matches(rel_posix) for p in patterns)


__all__ = [
    "IgnorePattern",
    "is_ignored",
    "load_ignore_file",
    "load_patterns",
]
