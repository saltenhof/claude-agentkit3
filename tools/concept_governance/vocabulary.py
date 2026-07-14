"""Live scope vocabulary derived from concept frontmatter."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from concept_compiler.loader import try_load_frontmatter

if TYPE_CHECKING:
    from pathlib import Path


def load_scope_vocabulary(concept_root: Path) -> tuple[str, ...]:
    """Return the sorted union of all live authority-over scopes."""
    scopes: set[str] = set()
    for path in sorted(concept_root.rglob("*.md")):
        frontmatter = try_load_frontmatter(path)
        if frontmatter is None:
            continue
        scopes.update(_authority_scopes(frontmatter.get("authority_over")))
    return tuple(sorted(scopes))


def _authority_scopes(raw: Any) -> set[str]:
    if not isinstance(raw, list):
        return set()
    scopes: set[str] = set()
    for entry in raw:
        value = entry if isinstance(entry, str) else entry.get("scope") if isinstance(entry, dict) else None
        if isinstance(value, str) and value.strip():
            scopes.add(value.strip())
    return scopes
