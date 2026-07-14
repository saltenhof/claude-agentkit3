"""Deterministic chunk and authorization metadata consumption."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

from concept_ingester.discovery import ConceptChunk, discover

if TYPE_CHECKING:
    from pathlib import Path

DEFAULT_MAX_CHARS = 12_000


class ChunkMetadataError(ValueError):
    """Raised when projected authorization metadata is malformed."""


def load_chunks(
    concept_root: Path,
    included_docs: frozenset[str] | None = None,
    *,
    max_chars: int = DEFAULT_MAX_CHARS,
) -> tuple[ConceptChunk, ...]:
    """Load working-tree chunks without an external index dependency."""
    chunks = discover(concept_root, max_chars=max_chars).chunks
    if included_docs is not None:
        chunks = [chunk for chunk in chunks if chunk.rel_path in included_docs]
    return tuple(chunks)


def authorization_scopes(chunk: ConceptChunk) -> frozenset[str]:
    """Return authority plus scope-qualified deferral scopes for a chunk."""
    authority = {
        scope
        for entry in _entries(chunk, "authority_over_full")
        if (scope := _non_empty(entry.get("scope"))) is not None
    }
    delegated = {
        scope
        for entry in _entries(chunk, "defers_to_full")
        if _non_empty(entry.get("target")) is not None
        and (scope := _non_empty(entry.get("scope"))) is not None
    }
    return frozenset(authority | delegated)


def _entries(chunk: ConceptChunk, key: str) -> tuple[dict[str, Any], ...]:
    raw = chunk.metadata.get(key)
    if not isinstance(raw, str):
        raise ChunkMetadataError(f"{chunk.rel_path}#{chunk.section_anchor}: missing {key}")
    if not raw:
        return ()
    try:
        parsed: Any = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ChunkMetadataError(f"{chunk.rel_path}#{chunk.section_anchor}: invalid {key}") from exc
    if not isinstance(parsed, list) or not all(isinstance(item, dict) for item in parsed):
        raise ChunkMetadataError(f"{chunk.rel_path}#{chunk.section_anchor}: {key} must be a list of mappings")
    return tuple(parsed)


def _non_empty(value: object) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None
