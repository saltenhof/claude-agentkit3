"""Generation-stamped lifecycle and CorpusStorePort composition."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from agentkit.backend.vectordb.completion_ledger import CompletionLedger
from agentkit.backend.vectordb.record_fields import utc_clock
from agentkit.backend.vectordb.schema import (
    OWNING_GENERATION_PROPERTY,
    STORY_CONTEXT_COLLECTION,
    StoryContextObject,
)
from agentkit.backend.vectordb.source_generation import SourceGenerationLadder
from agentkit.integration_clients.vectordb.errors import VectorDbUnavailableError

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping, Sequence
    from datetime import datetime

    from agentkit.backend.vectordb.client_port import CorpusClientPort
    from agentkit.backend.vectordb.commit_recovery import FileCommitRecoveryJournal
    from agentkit.backend.vectordb.sync import (
        ProducerCompletion,
        SourceClaim,
        SyncReceipt,
    )


@dataclass
class WeaviateCorpusStore:
    """Production :class:`CorpusStorePort` over the thin Weaviate adapter (R02).

    ``clock`` is the UTC time source for the claim/completion timestamps; it is a
    field so a test can drive them deterministically.
    """

    client: CorpusClientPort
    recovery_journal: FileCommitRecoveryJournal
    collection: str = STORY_CONTEXT_COLLECTION
    clock: Callable[[], datetime] = utc_clock
    _source_generations: SourceGenerationLadder = field(init=False, repr=False)
    _completion_ledger: CompletionLedger = field(init=False, repr=False)

    def __post_init__(self) -> None:
        self._source_generations = SourceGenerationLadder(
            client=self.client,
            clock=self.clock,
        )
        self._completion_ledger = CompletionLedger(
            client=self.client,
            recovery_journal=self.recovery_journal,
            clock=self.clock,
        )

    def try_claim_source(self, *, project_id: str, source_file: str, owner_id: str) -> SourceClaim | None:
        """Delegate source acquisition to the generation ladder."""
        return self._source_generations.try_claim_source(
            project_id=project_id,
            source_file=source_file,
            owner_id=owner_id,
        )

    def reclaim_source(
        self,
        *,
        project_id: str,
        source_file: str,
        owner_id: str,
        reason: str,
    ) -> SourceClaim:
        """Delegate administrative takeover to the generation ladder."""
        return self._source_generations.reclaim_source(
            project_id=project_id,
            source_file=source_file,
            owner_id=owner_id,
            reason=reason,
        )

    def assert_claim_held(self, *, claim: SourceClaim) -> None:
        """Delegate claim fencing to the generation ladder."""
        self._source_generations.assert_claim_held(claim=claim)

    def release_source(self, *, claim: SourceClaim) -> None:
        """Delegate release persistence to the generation ladder."""
        self._source_generations.release_source(claim=claim)

    def get_receipt(self, *, project_id: str, source_file: str) -> SyncReceipt | None:
        """Delegate authoritative completion lookup to the completion ledger."""
        return self._completion_ledger.get_receipt(
            project_id=project_id,
            source_file=source_file,
        )

    def set_receipt(self, *, receipt: SyncReceipt) -> SyncReceipt:
        """Delegate single-source completion publication to the ledger."""
        return self._completion_ledger.set_receipt(receipt=receipt)

    def set_receipts(
        self,
        *,
        run_id: str,
        receipts: Sequence[SyncReceipt],
        producer_completions: Sequence[ProducerCompletion],
    ) -> Sequence[SyncReceipt]:
        """Delegate atomic run completion publication to the ledger."""
        return self._completion_ledger.set_receipts(
            run_id=run_id,
            receipts=receipts,
            producer_completions=producer_completions,
        )

    def resolve_pending_commits(self, *, project_id: str) -> None:
        """Delegate unknown commit resolution to the completion ledger."""
        self._completion_ledger.resolve_pending_commits(project_id=project_id)

    def list_receipts(self, *, project_id: str) -> Sequence[SyncReceipt]:
        """Delegate verified completion enumeration to the ledger."""
        return self._completion_ledger.list_receipts(project_id=project_id)

    def list_producer_completions(self, *, project_id: str) -> Sequence[ProducerCompletion]:
        """Delegate producer-wide completion enumeration to the ledger."""
        return self._completion_ledger.list_producer_completions(project_id=project_id)

    def list_objects_for_source(self, *, project_id: str, source_file: str) -> Sequence[Mapping[str, object]]:
        rows = self.client.fetch_by_property(
            collection=self.collection,
            project_id=project_id,
            prop="source_file",
            value=source_file,
            return_props=(
                "content_hash",
                "source_type",
                "project_id",
                OWNING_GENERATION_PROPERTY,
            ),
        )
        return [
            {
                "uuid": uid,
                "source_file": source_file,
                "source_type": p.get("source_type", ""),
                "project_id": p.get("project_id", ""),
                "content_hash": p.get("content_hash", ""),
                OWNING_GENERATION_PROPERTY: p.get(OWNING_GENERATION_PROPERTY),
            }
            for uid, p in rows
            # Redundant after N51 (the project filter is server-side); kept as defence
            # in depth, never as the isolation mechanism.
            if str(p.get("project_id", "")) == project_id
        ]

    def list_objects_for_source_types(self, *, project_id: str, source_types: Sequence[str]) -> Sequence[Mapping[str, object]]:
        rows = self.client.fetch_by_property_any(
            collection=self.collection,
            project_id=project_id,
            prop="source_type",
            values=tuple(source_types),
            return_props=(
                "source_file",
                "project_id",
                "source_type",
                OWNING_GENERATION_PROPERTY,
            ),
        )
        return [
            {
                "uuid": uid,
                "source_file": p.get("source_file", ""),
                "source_type": p.get("source_type", ""),
                "project_id": p.get("project_id", ""),
                OWNING_GENERATION_PROPERTY: p.get(OWNING_GENERATION_PROPERTY),
            }
            for uid, p in rows
            if str(p.get("project_id", "")) == project_id
        ]

    def upsert_objects(self, *, objects: Sequence[StoryContextObject], owning_generation: int) -> int:
        """Write objects STAMPED with the writing SOURCE GENERATION (D9/N37).

        The stamp is applied here and nowhere else, so it is structurally impossible
        to persist an object version without the ordering marker the destructive
        delete conditions on. It does not touch the object identity: the uuid stays
        ``uuid5(project|source|chunk)`` and ``content_hash`` stays content-derived, so
        a re-sync still replaces the same object.
        """
        if owning_generation < 1:
            raise VectorDbUnavailableError(
                f"refusing to write objects with a non-positive owning generation "
                f"({owning_generation}); the destructive delete orders against it "
                "(fail-closed, N37)."
            )
        # Exact confirmed count: the adapter inspects batch failures and raises
        # on a partial batch (R12); a clean return == len(objects).
        docs = [
            {
                **obj.properties,
                "uuid": obj.uuid,
                OWNING_GENERATION_PROPERTY: owning_generation,
            }
            for obj in objects
        ]
        return self.client.upsert(collection=self.collection, objects=docs)

    def delete_objects_older_than(
        self,
        *,
        project_id: str,
        source_file: str,
        uuids: Sequence[str],
        owning_generation: int,
    ) -> int:
        """Delete objects ONLY where the writing generation is STRICTLY OLDER (N37).

        The condition is evaluated by the store together with the delete, and it
        orders against a number the CALLER owns -- its own generation -- not against
        a value it happened to read. That is what authorises the delete: an equality
        against an observed value closes only the interval between the read and the
        delete; it never establishes whose generation the value belonged to, so a
        resumed writer could delete a NEWER generation's data by simply observing it.

        Because the source generation ladder is persistent and strictly monotonic, a
        superseding owner always holds a HIGHER generation, so:

        - a superseded holder can never match the new owner's objects, in either race
          order (it reads them before or after -- the condition is the same);
        - every legitimately deletable object of a PREVIOUS generation still matches,
          including objects from several different earlier generations at once.

        Args:
            project_id: Authoritative bound project -- part of the condition (AC4).
            source_file: The claimed source -- part of the condition (AC4).
            uuids: Candidate object ids.
            owning_generation: The deleting claim's own generation (exclusive bound).

        Returns:
            The exact number of objects the store confirms deleted.

        Raises:
            VectorDbUnavailableError: For a non-positive generation (fail-closed).
        """
        if owning_generation < 1:
            raise VectorDbUnavailableError(
                f"refusing to delete with a non-positive owning generation ({owning_generation}); fail-closed (N37)."
            )
        return self.client.delete_by_ids_if_property_below(
            collection=self.collection,
            uuids=tuple(uuids),
            prop=OWNING_GENERATION_PROPERTY,
            limit=owning_generation,
            project_id=project_id,
            source_file=source_file,
        )

    def delete_objects_without_generation(self, *, project_id: str, source_file: str, uuids: Sequence[str]) -> int:
        """Delete objects that carry NO writing generation at all (N43).

        The condition is an IS-NULL evaluated by the store, so it can only ever match
        rows written before the ownership-ordering property existed. A row written by
        ANY generation is stamped, so this can never touch the caller's own data and
        never a newer owner's -- which is what makes the legacy backfill safe without
        adopting foreign content into a generation.

        Args:
            project_id: Authoritative bound project -- part of the condition (AC4).
            source_file: The claimed source -- part of the condition (AC4).
            uuids: Candidate object ids of that source.

        Returns:
            The exact number of objects the store confirms deleted.
        """
        if not uuids:
            return 0
        return self.client.delete_by_ids_if_property_absent(
            collection=self.collection,
            uuids=tuple(uuids),
            prop=OWNING_GENERATION_PROPERTY,
            project_id=project_id,
            source_file=source_file,
        )


__all__ = ["WeaviateCorpusStore"]
