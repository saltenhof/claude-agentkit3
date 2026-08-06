"""Deterministic inversion and stable partitioning for W3 scope sets."""

from __future__ import annotations

from typing import TYPE_CHECKING

from concept_governance.chunks import authorization_scopes
from concept_governance.scope_models import ScopeAssertionChunk, ScopePartition, ScopeSet
from concept_governance.scope_prompt import render_scope_prompt

if TYPE_CHECKING:
    from concept_ingester.discovery import ConceptChunk

DEFAULT_PARTITION_MAX_CHARS = 30_000
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
    """Partition sets under exact rendered-prompt and source-count limits."""
    if max_chars < 1 or max_chunks < 1:
        raise ScopeSetError("partition limits must be positive")
    if max_chars > DEFAULT_PARTITION_MAX_CHARS:
        raise ScopeSetError(
            f"partition maximum cannot exceed {DEFAULT_PARTITION_MAX_CHARS} characters"
        )
    partitions: list[ScopePartition] = []
    for scope_set in scope_sets:
        groups = _partition_assertions(scope_set.assertions, max_chunks)
        groups = _fit_rendered_prompt_limit(scope_set.scope, groups, max_chars)
        partitions.extend(
            ScopePartition(scope=scope_set.scope, index=index, count=len(groups), assertions=group)
            for index, group in enumerate(groups, start=1)
        )
    return tuple(partitions)


def _partition_assertions(
    assertions: tuple[ScopeAssertionChunk, ...], max_chunks: int
) -> tuple[tuple[ScopeAssertionChunk, ...], ...]:
    return tuple(
        assertions[start : start + max_chunks]
        for start in range(0, len(assertions), max_chunks)
    )


def _fit_rendered_prompt_limit(
    scope: str,
    initial: tuple[tuple[ScopeAssertionChunk, ...], ...],
    max_chars: int,
) -> tuple[tuple[ScopeAssertionChunk, ...], ...]:
    """Split deterministically until every final rendered prompt fits."""
    groups = initial
    while groups:
        count = len(groups)
        revised: list[tuple[ScopeAssertionChunk, ...]] = []
        changed = False
        for index, group in enumerate(groups, start=1):
            partition = ScopePartition(
                scope=scope,
                index=index,
                count=count,
                assertions=group,
            )
            rendered, _ = render_scope_prompt(partition)
            if len(rendered) <= max_chars:
                revised.append(group)
                continue
            if len(group) == 1:
                raise ScopeSetError(
                    f"source {group[0].chunk_id!r} renders to {len(rendered)} characters, "
                    f"above partition maximum {max_chars}"
                )
            midpoint = (len(group) + 1) // 2
            revised.extend((group[:midpoint], group[midpoint:]))
            changed = True
        groups = tuple(revised)
        if not changed:
            return groups
    return ()
