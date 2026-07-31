"""App-layer adapter binding ``StoryIndexPort`` to the ONE corpus write path (N38).

Story export, split and repair used to index through the thin adapter's own
``story_sync``, which upserted ``StoryContext`` objects directly. That was a SECOND
write path: it took no source claim, published no completion and -- once the
destructive delete became storage-conditional on the writing generation (N37) --
produced objects that carried no generation at all, so a later MCP sync or a
vanished-source delete had to refuse them.

There is therefore exactly one way into ``StoryContext``: the claim-aware
:class:`~agentkit.backend.vectordb.sync.SyncService`. It claims the source, stamps the
writing generation, verifies the written generation and publishes a digest-bound
completion, so an exported story participates in the delete closure and in freshness
exactly like an MCP-synced one.

The fail-closed indexing policy (a failure blocks the export) lives in
:mod:`agentkit.backend.story_creation.story_md_export`; this shim only routes.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from agentkit.backend.vectordb.engine import (
    CorpusClientPort,
    WeaviateCorpusStore,
    ensure_corpus_collections,
)
from agentkit.backend.vectordb.sync import SyncService
from agentkit.concepts.hashing import corpus_revision
from agentkit.integration_clients.vectordb.errors import VectorDbUnavailableError

if TYPE_CHECKING:
    from collections.abc import Sequence

    from agentkit.backend.vectordb.commit_recovery import FileCommitRecoveryJournal
    from agentkit.backend.vectordb.schema import StoryContextObject
    from agentkit.integration_clients.vectordb import WeaviateStoryAdapter


class WeaviateStoryIndex:
    """Bind the ``StoryIndexPort`` to the claim-aware corpus sync owner (N38)."""

    def __init__(
        self,
        adapter: WeaviateStoryAdapter,
        *,
        recovery_journal: FileCommitRecoveryJournal | None = None,
        sync: SyncService | None = None,
    ) -> None:
        """Initialise with a connected Weaviate adapter.

        Args:
            adapter: The thin Weaviate transport adapter (owns the connection).
            sync: The corpus sync owner. Built over the adapter's client when
                omitted; injectable so the export path can be exercised against a
                double at the transport seam.
            recovery_journal: Durable project-bound completion owner. Mandatory
                whenever this adapter constructs its productive write service.

        Raises:
            VectorDbUnavailableError: When the adapter's client does not implement
                the corpus surface the sync owner requires (fail-closed).
        """
        self._adapter = adapter
        if sync is not None:
            self._sync = sync
            return
        client = self._corpus_client(adapter)
        if recovery_journal is None:
            raise VectorDbUnavailableError(
                "the productive Weaviate story index requires a durable completion "
                "recovery owner; refusing an unjournaled write path"
            )
        self._sync = self._build_sync(client, recovery_journal)

    @staticmethod
    def _corpus_client(adapter: WeaviateStoryAdapter) -> CorpusClientPort:
        client = adapter.corpus_client
        if not isinstance(client, CorpusClientPort):
            raise VectorDbUnavailableError(
                "the Weaviate client does not implement the corpus surface required "
                "for a claimed, generation-stamped write; refusing to index through "
                "a second write path (fail-closed, N38)."
            )
        return client

    @staticmethod
    def _build_sync(
        client: CorpusClientPort,
        recovery_journal: FileCommitRecoveryJournal,
    ) -> SyncService:
        """Build the corpus sync owner over the adapter's own connection."""
        ensure_corpus_collections(client)
        return SyncService(
            store=WeaviateCorpusStore(
                client=client,
                recovery_journal=recovery_journal,
            )
        )

    def index_story(
        self,
        *,
        story_id: str,
        project_id: str,
        objects: Sequence[StoryContextObject],
    ) -> int:
        """Index/update the story chunks through the sync owner (FK-21 §21.11.4).

        Every source is synced under its OWN claim, so a concurrent writer to the same
        story is rejected fail-closed (D3) instead of interleaving, the objects carry
        the writing generation (N37) and a completion is published for freshness.

        Args:
            story_id: Story display-ID (the objects already carry their ``story_id``).
            project_id: Bound multi-tenant discriminator. Each object's
                ``project_id`` MUST match (N06) -- a divergent/missing object
                project_id is REJECTED (never silently overwritten).
            objects: The TYPED StoryContext projection. Its ``chunk_id`` is the
                identity input the deterministic uuid was derived from and is passed
                through UNCHANGED (N42) -- reconstructing it here produced uuids the
                production identity validation rejects.

        Returns:
            The number of objects written.

        Raises:
            ValueError: When an object's project_id diverges from the binding, or an
                object carries no usable identity fields.
            SyncError: When the objects do not form a publishable generation.
            VectorDbWriteError: When the indexing write fails (hard blocker,
                propagated; fail-closed).
        """
        del story_id
        if not project_id:
            raise ValueError("project_id is empty; cannot index (N06).")
        by_source: dict[str, list[StoryContextObject]] = {}
        for obj in objects:
            obj_pid = str(obj.properties.get("project_id", ""))
            if obj_pid != project_id:
                raise ValueError(
                    f"object project_id {obj_pid!r} diverges from the bound "
                    f"{project_id!r}; cross-project indexing rejected (N06)."
                )
            by_source.setdefault(_require(obj, "source_file"), []).append(obj)
        written = 0
        for source_file, chunks in sorted(by_source.items()):
            revision = corpus_revision(
                [str(chunk.properties["content_hash"]) for chunk in chunks]
            )
            result = self._sync.sync_source(
                project_id=project_id,
                source_file=source_file,
                source_type=str(chunks[0].properties["source_type"]),
                objects=chunks,
                corpus_revision=revision,
            )
            written += result.written
        return written


def _require(obj: StoryContextObject, key: str) -> str:
    """Return a mandatory non-empty string property (no repair default)."""
    value = obj.properties.get(key)
    if not isinstance(value, str) or not value:
        raise ValueError(
            f"story object is missing a usable {key!r} ({value!r}); it cannot be "
            "claimed or completed (fail-closed, N38)."
        )
    return value


__all__ = ["WeaviateStoryIndex"]
