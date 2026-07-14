"""Deterministic inversion and stable partitioning for W3 scope sets."""

from __future__ import annotations

from typing import TYPE_CHECKING

from concept_governance.chunks import authorization_scopes
from concept_governance.scope_models import ScopeAssertionChunk, ScopePartition, ScopeSet

if TYPE_CHECKING:
    from concept_ingester.discovery import ConceptChunk

DEFAULT_PARTITION_MAX_CHARS = 48_000
DEFAULT_PARTITION_MAX_CHUNKS = 20


class ScopeSetError(ValueError):
    """Raised when requested closed sets cannot be built safely."""


def build_scope_sets(
    chunks: tuple[ConceptChunk, ...],
    vocabulary: tuple[str, ...],
    requested_scopes: frozenset[str] | None = None,
) -> tuple[ScopeSet, ...]:
    """Invert chunk authorization scopes into one closed set per scope."""
    live = frozenset(vocabulary)
    selected = live if requested_scopes is None else requested_scopes
    unknown = selected - live
    if unknown:
        raise ScopeSetError(f"unknown scope filters: {sorted(unknown)}")
    buckets: dict[str, list[ScopeAssertionChunk]] = {scope: [] for scope in sorted(selected)}
    ordered = sorted(chunks, key=lambda item: (item.rel_path, item.ordering, item.chunk_id))
    for chunk in ordered:
        assertion = ScopeAssertionChunk(
            chunk_id=chunk.chunk_id,
            doc=chunk.rel_path,
            anchor=chunk.section_anchor,
            text=chunk.content,
        )
        for scope in sorted(authorization_scopes(chunk) & selected):
            buckets[scope].append(assertion)
    return tuple(ScopeSet(scope=scope, assertions=tuple(items)) for scope, items in buckets.items())


def partition_scope_sets(
    scope_sets: tuple[ScopeSet, ...],
    *,
    max_chars: int = DEFAULT_PARTITION_MAX_CHARS,
    max_chunks: int = DEFAULT_PARTITION_MAX_CHUNKS,
) -> tuple[ScopePartition, ...]:
    """Partition every non-empty set without truncating any assertion chunk."""
    if max_chars < 1 or max_chunks < 1:
        raise ScopeSetError("partition limits must be positive")
    partitions: list[ScopePartition] = []
    for scope_set in scope_sets:
        groups = _partition_assertions(scope_set.assertions, max_chars, max_chunks)
        partitions.extend(
            ScopePartition(scope=scope_set.scope, index=index, count=len(groups), assertions=group)
            for index, group in enumerate(groups, start=1)
        )
    return tuple(partitions)


def _partition_assertions(
    assertions: tuple[ScopeAssertionChunk, ...], max_chars: int, max_chunks: int
) -> tuple[tuple[ScopeAssertionChunk, ...], ...]:
    groups: list[tuple[ScopeAssertionChunk, ...]] = []
    current: list[ScopeAssertionChunk] = []
    current_chars = 0
    for assertion in assertions:
        size = len(assertion.doc) + len(assertion.anchor) + len(assertion.text)
        if current and (len(current) >= max_chunks or current_chars + size > max_chars):
            groups.append(tuple(current))
            current, current_chars = [], 0
        current.append(assertion)
        current_chars += size
    if current:
        groups.append(tuple(current))
    return tuple(groups)
