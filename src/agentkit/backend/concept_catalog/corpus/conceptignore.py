"""``.conceptignore`` loader and matcher (FK-13 §13.9.13).

Gitignore-like glob semantics — not ``Path.match``:

* ``*`` matches within one path segment (not ``/``)
* ``**`` matches zero or more path segments
* ``research/**`` matches everything under ``research/`` (any depth)
* ``research/**/*`` matches only under subdirectories of ``research/``,
  not direct children
* ``*.md`` matches ``foo.md``, not ``sub/foo.md``
* ``drafts/*.md`` matches only direct children of ``drafts/``
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path, PurePosixPath


@dataclass(frozen=True)
class ConceptIgnoreRules:
    """Compiled ignore rules relative to a concept root."""

    patterns: tuple[str, ...]
    _compiled: tuple[re.Pattern[str], ...]

    def matches(self, rel_posix: str) -> bool:
        """Return True when ``rel_posix`` (relative to concept root) is excluded."""
        path = rel_posix.replace("\\", "/").lstrip("./")
        return any(rx.fullmatch(path) is not None for rx in self._compiled)


def load_conceptignore(concept_root: Path) -> ConceptIgnoreRules:
    """Load ``{concept_root}/.conceptignore`` (optional; empty when absent)."""
    path = concept_root / ".conceptignore"
    if not path.is_file():
        return ConceptIgnoreRules(patterns=(), _compiled=())
    try:
        data = path.read_bytes()
    except OSError as exc:
        from agentkit.backend.concept_catalog.corpus.domain_errors import ConceptParseError

        raise ConceptParseError(
            "E-IGNORE-001",
            f".conceptignore unreadable: {exc}",
            path=str(path),
        ) from exc
    return load_conceptignore_from_bytes(data, path=str(path))


def load_conceptignore_from_bytes(
    data: bytes, *, path: str = ".conceptignore"
) -> ConceptIgnoreRules:
    """Compile ignore rules from raw bytes (R13: Index/HEAD, never working tree)."""
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as exc:
        from agentkit.backend.concept_catalog.corpus.domain_errors import ConceptParseError

        raise ConceptParseError(
            "E-IGNORE-001",
            f".conceptignore is not valid UTF-8: {exc}",
            path=path,
        ) from exc
    patterns: list[str] = []
    compiled: list[re.Pattern[str]] = []
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        patterns.append(line)
        compiled.append(_compile_gitignore_glob(line))
    return ConceptIgnoreRules(patterns=tuple(patterns), _compiled=tuple(compiled))


def _compile_gitignore_glob(pattern: str) -> re.Pattern[str]:
    """Compile a single gitignore-style glob to a fullmatch regex.

    FK-13 §13.9.13 special cases:
    * ``research/**`` — everything under research/ (any depth, incl. direct children)
    * ``research/**/*`` — only under subdirectories of research/, NOT direct children
    * ``*.md`` — only at root of the concept dir (not ``sub/foo.md``)
    """
    # Normalise separators.
    pat = pattern.replace("\\", "/").lstrip("/")
    # FK-13: ``dir/**/*`` matches only nested paths, not direct children.
    if pat.endswith("/**/*"):
        base = pat[: -len("/**/*")]
        if not base:
            return re.compile(r".+/.+")
        base_re = _glob_to_re(base, allow_double_star=False)
        # At least one intermediate directory segment before the final file.
        return re.compile(rf"{base_re}/.+/[^/]+")
    # Special-case trailing /** (match directory and all descendants).
    if pat.endswith("/**"):
        base = pat[:-3]
        if not base:
            return re.compile(r".+")
        base_re = _glob_to_re(base, allow_double_star=False)
        return re.compile(rf"(?:{base_re})(?:/.*)?")
    return re.compile(_glob_to_re(pat, allow_double_star=True))


def _glob_to_re(pattern: str, *, allow_double_star: bool) -> str:
    """Translate a gitignore-ish glob into a regex string (no anchors)."""
    i = 0
    out: list[str] = []
    n = len(pattern)
    while i < n:
        ch = pattern[i]
        if allow_double_star and pattern.startswith("**/", i):
            # Match zero or more full segments including a trailing slash when present.
            out.append("(?:.*/)?")
            i += 3
            continue
        if allow_double_star and pattern.startswith("**", i):
            out.append(".*")
            i += 2
            continue
        if ch == "*":
            out.append("[^/]*")
            i += 1
            continue
        if ch == "?":
            out.append("[^/]")
            i += 1
            continue
        if ch == "[":
            j = i + 1
            if j < n and pattern[j] in ("!", "]"):
                j += 1
            while j < n and pattern[j] != "]":
                j += 1
            if j >= n:
                out.append(re.escape(ch))
                i += 1
                continue
            out.append(pattern[i : j + 1])
            i = j + 1
            continue
        out.append(re.escape(ch))
        i += 1
    return "".join(out)


def is_under_archiv(rel_posix: str) -> bool:
    """Return True when the relative path lies under an ``archiv/`` segment."""
    parts = PurePosixPath(rel_posix.replace("\\", "/")).parts
    return "archiv" in parts or "archive" in parts


__all__ = [
    "ConceptIgnoreRules",
    "is_under_archiv",
    "load_conceptignore",
]
