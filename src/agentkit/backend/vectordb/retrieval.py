"""Corpus retrieval with completion-derived freshness and residual reporting."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from agentkit.backend.vectordb.schema import (
    OWNING_GENERATION_PROPERTY,
    STORY_CONTEXT_COLLECTION,
    is_ordered_generation,
    search_property_spec,
)

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from agentkit.backend.vectordb.client_port import CorpusClientPort
    from agentkit.backend.vectordb.corpus_store import WeaviateCorpusStore
    from agentkit.backend.vectordb.runtime_binding import RuntimeBinding
    from agentkit.backend.vectordb.sync import ProducerCompletion, SyncReceipt


@dataclass
class WeaviateRetrievalPort:
    """Production :class:`RetrievalPort` over the thin Weaviate adapter (R02/N01).

    Search issues a REAL StoryContext query scoped by project_id AND source_type
    AND the typed filters, returning full properties (concept_id/status/module
    preserved). Source listings read the persisted receipts for real freshness
    (N04/D1).
    """

    client: CorpusClientPort
    store: WeaviateCorpusStore
    binding: RuntimeBinding
    collection: str = STORY_CONTEXT_COLLECTION

    def search(
        self,
        *,
        project_id: str,
        source_type: str,
        query: str,
        search_mode: str,
        limit: int,
        filters: Mapping[str, object],
    ) -> Sequence[Mapping[str, object]]:
        # The source-type retrieval profile (schema SSOT) is BOTH the requested
        # property set and the strict validation spec the transport enforces on
        # every hit (N11).
        rows = self.client.search_objects(
            collection=self.collection,
            query=query,
            search_mode=search_mode,
            project_id=project_id,
            source_type=source_type,
            filters=filters,
            limit=limit,
            property_spec=search_property_spec(source_type),
        )
        return [{**props, "score": score, "snippet": str(props.get("content", ""))[:200]} for _uid, props, score in rows]

    def list_sources(self, *, project_id: str) -> Sequence[Mapping[str, object]]:
        from agentkit.backend.vectordb.ingest.classify import PRODUCER_BY_SOURCE_TYPE

        receipts = self.store.list_receipts(project_id=project_id)
        producer_completions = self.store.list_producer_completions(project_id=project_id)
        # AG3-177 (c): the authoritative generation per source comes from the SAME
        # completion set this listing already reads, so making the residual
        # detectable costs no additional transport.
        authority = authoritative_generations(receipts)
        out: list[Mapping[str, object]] = []
        for source_type, producer in PRODUCER_BY_SOURCE_TYPE.items():
            rows = self.store.list_objects_for_source_types(project_id=project_id, source_types=(source_type,))
            files = {str(r.get("source_file")) for r in rows}
            out.append(
                {
                    "project_id": project_id,
                    "source_type": source_type,
                    "producer": producer,
                    "source_count": len(files),
                    "chunk_count": len(rows),
                    # N04/D1: the revision of the LAST SUCCESSFUL COMPLETION for
                    # this source type (persisted completion order, not a
                    # lexicographic maximum over content digests).
                    "last_revision": _last_completed_revision(
                        receipts,
                        producer_completions,
                        source_type,
                    ),
                    # AG3-177: the EXACT predicate of :func:`stale_chunk_count` --
                    # rows below their source's authoritative generation, rows with
                    # no generation, rows with an unusable one. > 0 is an actionable
                    # finding, NOT proof of a takeover residual: a sync resolves the
                    # first two classes and REFUSES the third by name (FK-04 §4.5.14).
                    # ``chunk_count`` stays the PHYSICAL count -- (c) changes
                    # detectability, not visibility.
                    "stale_chunk_count": stale_chunk_count(rows, authority),
                }
            )
        return out


def authoritative_generations(
    receipts: Sequence[SyncReceipt],
) -> Mapping[str, int]:
    """Return ``{source_file: authoritative generation}`` from the completions (AG3-177).

    The authoritative generation of a source is the HIGHEST generation among its
    verified, completed records -- the same ordering :meth:`WeaviateCorpusStore.
    get_receipt` uses to answer "which completion counts" (N39). A source with no
    completion has no authority and does not appear here.

    Args:
        receipts: The project's verified completions, as read.

    Returns:
        The authoritative generation per source file.
    """
    out: dict[str, int] = {}
    for receipt in receipts:
        if receipt.state.value != "completed":
            continue
        if receipt.generation > out.get(receipt.source_file, 0):
            out[receipt.source_file] = receipt.generation
    return out


def stale_chunk_count(rows: Sequence[Mapping[str, object]], authority: Mapping[str, int]) -> int:
    """Count the rows matching the EXACT predicate below (AG3-177).

    This is NOT "every row that is not part of the authoritative generation": a row of a
    HIGHER generation is not part of it either and is deliberately not counted. Reading
    the figure as a complete non-authoritative count would make a zero look like proof
    that nothing is in flight, which it is not.

    Counted, each row against the authoritative generation of ITS source, using the one
    classification ladder :func:`classify_owning_generation` (so the sync and this
    listing can never disagree about what a row is):

    - :attr:`GenerationClass.ORDERED` strictly BELOW the authority -- the takeover
      residual, and exactly what the next sync's ordered delete removes;
    - :attr:`GenerationClass.MISSING` (absent or ``null``) -- a legacy row predating the
      ordering property; the next sync converges it under its IS-NULL condition;
    - :attr:`GenerationClass.UNUSABLE` -- present but not orderable. It is certainly not
      authoritative, and it needs ATTENTION rather than a sync: the sync refuses it by
      name instead of cleaning it up.

    NOT counted:

    - rows of a source that has no completion at all -- there is no authority to judge
      them against, and inventing one would be a guess;
    - rows of a generation ABOVE the authoritative one: that is an in-flight newer
      generation whose completion is not published yet, not a remnant.

    Because the three counted classes carry DIFFERENT remedies, a value ``> 0`` is an
    actionable finding, not proof of a takeover residual (FK-04 §4.5.14).

    Args:
        rows: The source rows as read (uuid, source_file, writing generation).
        authority: The authoritative generation per source file.

    Returns:
        The number of rows matching the predicate.
    """
    count = 0
    for row in rows:
        authoritative = authority.get(str(row.get("source_file", "")))
        if authoritative is None:
            continue
        raw = row.get(OWNING_GENERATION_PROPERTY)
        if not is_ordered_generation(raw):
            count += 1  # MISSING (legacy) or UNUSABLE (a named error, not a sync case)
            continue
        if raw < authoritative:
            count += 1
    return count


def _last_completed_revision(
    receipts: Sequence[SyncReceipt],
    producer_completions: Sequence[ProducerCompletion],
    source_type: str,
) -> str:
    """Return the revision of the LAST successful completion of a source type (N04).

    Ordering is the persisted completion ``sequence`` (store-monotonic); the
    ``completed_at`` timestamp and the source file break ties deterministically.
    An unfinished (``in_progress``) receipt is not a completion.
    """
    source_candidates = [
        (receipt.sequence, receipt.completed_at, receipt.source_file, receipt.corpus_revision)
        for receipt in receipts
        if receipt.source_type == source_type and receipt.state.value == "completed"
    ]
    producer_candidates = [
        (completion.sequence, "", completion.producer, completion.corpus_revision)
        for completion in producer_completions
        if source_type in completion.source_types
    ]
    completed = source_candidates + producer_candidates
    if not completed:
        return ""
    return max(completed)[3]


__all__ = [
    "WeaviateRetrievalPort",
    "authoritative_generations",
    "stale_chunk_count",
]
