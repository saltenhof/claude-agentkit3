"""Production retrieval engine for the FK-13 MCP server (R02).

Real, productive implementations of :class:`RetrievalPort` and
:class:`CorpusStorePort` over the THIN Weaviate transport adapter, plus an
env-bound runtime composition (:func:`compose_runtime`) and an executable stdio
entry point (:func:`main`). The engine never synthesises endpoints: both the
HTTP and gRPC endpoints come exclusively from the registered env (D2), are
passed verbatim into the real connection, and a localhost default fails closed.

This is the ONLY production wiring of the engine; tests instantiate the ports
with fakes at the :class:`CorpusStorePort` / :class:`RetrievalPort` boundary
(the narrow mock exception).
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Final, Protocol, runtime_checkable

from agentkit.backend.vectordb.runtime_binding import RuntimeBinding, RuntimeBindingError
from agentkit.backend.vectordb.schema import (
    OWNING_GENERATION_PROPERTY,
    STORY_CONTEXT_COLLECTION,
    StoryContextObject,
    search_property_spec,
)
from agentkit.backend.vectordb.sync import (
    ClaimSupersededError,
    ConcurrentSyncRejectedError,
    SourceClaim,
    SyncReceipt,
    SyncService,
    parse_utc_timestamp,
)
from agentkit.integration_clients.vectordb.errors import VectorDbUnavailableError, VectorDbWriteError

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping, Sequence
    from pathlib import Path

#: Dedicated collection for digest-bound sync receipts (R02/R12).
RECEIPT_COLLECTION = "__agentkit_sync_receipts"

#: The receipt record's full property set (verified on read, N08).
RECEIPT_PROPERTIES: tuple[str, ...] = (
    "project_id",
    "source_file",
    "source_type",
    "corpus_revision",
    "digest",
    "state",
    "completed_at",
    "sequence",
    "generation",
)

#: Dedicated collection for store-level atomic source claims (N03/D3/N15).
CLAIM_COLLECTION = "__agentkit_source_claims"

#: The claim/generation record's property set (no expiry -- N15/N27; persistent
#: monotonic ``generation`` -- N37). ``state`` is ``claimed`` for an acquisition and
#: ``released`` for the insert-only release marker of that same generation.
CLAIM_PROPERTIES: tuple[str, ...] = (
    "project_id",
    "source_file",
    "state",
    "owner_id",
    "generation",
    "claimed_at",
    "reclaimed_from",
    "reclaim_reason",
)

#: Record states in the claim collection (insert-only; nothing is ever updated).
CLAIM_STATE_HELD: Final[str] = "claimed"
CLAIM_STATE_RELEASED: Final[str] = "released"

#: Bounded number of completion positions tried before failing closed (N28).
_COMPLETION_ATTEMPT_LIMIT: Final[int] = 256

#: Stable namespace for the position-bound completion records (N28).
_RECEIPT_NAMESPACE = uuid.UUID("8c5e2f3a-1b6d-4e7a-9c8f-2a1b3c4d5e6f")
#: Stable namespace for per-source, per-generation claim identity (N03/N15/N37).
_CLAIM_NAMESPACE = uuid.UUID("9d6f3a4b-2c7e-5f8b-ad9c-3b2c4d5e6f7a")

def _utc_clock() -> datetime:
    """Return the current UTC instant (the store's default clock)."""
    return datetime.now(UTC)


def _iso(value: datetime) -> str:
    """Render a UTC instant as an ISO-8601 string with a ``Z`` suffix."""
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


@runtime_checkable
class CorpusClientPort(Protocol):
    """The thin-adapter corpus surface the engine needs (R02)."""

    def fetch_by_property(
        self,
        *,
        collection: str,
        project_id: str,
        prop: str,
        value: str,
        return_props: Sequence[str],
    ) -> Sequence[tuple[str, dict[str, object]]]: ...

    def fetch_by_property_any(
        self,
        *,
        collection: str,
        project_id: str,
        prop: str,
        values: Sequence[str],
        return_props: Sequence[str],
    ) -> Sequence[tuple[str, dict[str, object]]]: ...

    def search_objects(
        self,
        *,
        collection: str,
        query: str,
        search_mode: str,
        project_id: str,
        source_type: str,
        filters: Mapping[str, object],
        limit: int,
        property_spec: Sequence[tuple[str, str, bool]],
    ) -> Sequence[tuple[str, dict[str, object], float]]: ...

    def upsert(self, *, collection: str, objects: Sequence[Mapping[str, object]]) -> int: ...

    def insert_object(
        self, *, collection: str, uuid: str, properties: Mapping[str, object]
    ) -> bool: ...

    def delete_by_ids(self, *, collection: str, uuids: Sequence[str]) -> int: ...

    def delete_by_ids_if_property_below(
        self,
        *,
        collection: str,
        uuids: Sequence[str],
        prop: str,
        limit: int,
        project_id: str,
        source_file: str,
    ) -> int: ...

    def delete_by_ids_if_property_absent(
        self,
        *,
        collection: str,
        uuids: Sequence[str],
        prop: str,
        project_id: str,
        source_file: str,
    ) -> int: ...

    def ensure_collection(
        self,
        *,
        collection: str,
        property_specs: Sequence[Mapping[str, object]],
        vectorizer: str = ...,
        vectorizer_model: Mapping[str, object] | None = ...,
        vector_source_properties: Sequence[str] | None = ...,
    ) -> None: ...


@dataclass
class WeaviateCorpusStore:
    """Production :class:`CorpusStorePort` over the thin Weaviate adapter (R02).

    ``clock`` is the UTC time source for the claim/completion timestamps; it is a
    field so a test can drive them deterministically.
    """

    client: CorpusClientPort
    collection: str = STORY_CONTEXT_COLLECTION
    clock: Callable[[], datetime] = _utc_clock

    def list_objects_for_source(
        self, *, project_id: str, source_file: str
    ) -> Sequence[Mapping[str, object]]:
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
            {"uuid": uid, "source_file": source_file, "source_type": p.get("source_type", ""),
             "project_id": p.get("project_id", ""), "content_hash": p.get("content_hash", ""),
             OWNING_GENERATION_PROPERTY: p.get(OWNING_GENERATION_PROPERTY)}
            for uid, p in rows
            # Redundant after N51 (the project filter is server-side); kept as defence
            # in depth, never as the isolation mechanism.
            if str(p.get("project_id", "")) == project_id
        ]

    def list_objects_for_source_types(
        self, *, project_id: str, source_types: Sequence[str]
    ) -> Sequence[Mapping[str, object]]:
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
            {"uuid": uid, "source_file": p.get("source_file", ""),
             "source_type": p.get("source_type", ""), "project_id": p.get("project_id", ""),
             OWNING_GENERATION_PROPERTY: p.get(OWNING_GENERATION_PROPERTY)}
            for uid, p in rows
            if str(p.get("project_id", "")) == project_id
        ]

    def upsert_objects(
        self, *, objects: Sequence[StoryContextObject], owning_generation: int
    ) -> int:
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
                f"refusing to delete with a non-positive owning generation "
                f"({owning_generation}); fail-closed (N37)."
            )
        return self.client.delete_by_ids_if_property_below(
            collection=self.collection,
            uuids=tuple(uuids),
            prop=OWNING_GENERATION_PROPERTY,
            limit=owning_generation,
            project_id=project_id,
            source_file=source_file,
        )

    def delete_objects_without_generation(
        self, *, project_id: str, source_file: str, uuids: Sequence[str]
    ) -> int:
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

    def get_receipt(self, *, project_id: str, source_file: str) -> SyncReceipt | None:
        """Return the AUTHORITATIVE completion of one source (N28/N39).

        The winner is the highest SOURCE GENERATION, not the highest completion
        position. Insert-only records prevent an overwrite, but they do not make a
        stale APPEND harmless: a superseded writer that publishes after the newer
        owner would take the next position and, ordered by position, would become
        freshness-authoritative and prune the newer owner's valid completion. The
        generation is monotonic per source, so a superseded generation can never win.
        """
        completions = [
            receipt
            for receipt in self.list_receipts(project_id=project_id)
            if receipt.source_file == source_file
        ]
        if not completions:
            return None
        return max(completions, key=lambda r: (r.generation, r.sequence))

    def set_receipt(self, *, receipt: SyncReceipt) -> SyncReceipt:
        """Establish ONE immutable, fully digest-bound completion record (N28).

        Reserving a number is NOT establishing completion order: with a separate
        token the reservation and the publication were two writes, so a stalled
        writer could publish AFTER a later one (freshness went backwards), and an
        old valid receipt could be replayed over the stable per-source record.

        Here the successful CONDITIONAL CREATE *is* the completion record:

        - its uuid is ``uuid5(project_id | sequence)``, so the store itself grants
          each position to exactly one writer;
        - its properties carry the COMPLETE receipt, whose digest binds
          project/source/source_type/revision/state/completed_at/sequence -- the
          number and the content are established by the SAME write;
        - the record is INSERT-ONLY and never updated, so a replayed older receipt
          finds its position taken and cannot overwrite anything;
        - the sealed receipt is verified BEFORE it is persisted (N29).

        Superseded completions of the same source are pruned best-effort AFTER the
        new one is established (housekeeping only -- correctness comes from the
        immutable winning record).
        """
        candidate = self._highest_completion_sequence(receipt.project_id) + 1
        for _attempt in range(_COMPLETION_ATTEMPT_LIMIT):
            sealed = receipt.stamped(sequence=candidate)
            sealed.verify()  # N29: never persist an unverified receipt
            record_uuid = self._completion_uuid(sealed.project_id, sealed.sequence)
            if self.client.insert_object(
                collection=RECEIPT_COLLECTION,
                uuid=record_uuid,
                properties={
                    "project_id": sealed.project_id,
                    "source_file": sealed.source_file,
                    "source_type": sealed.source_type,
                    "corpus_revision": sealed.corpus_revision,
                    "digest": sealed.digest,
                    "state": sealed.state.value,
                    "completed_at": sealed.completed_at,
                    "sequence": str(sealed.sequence),
                    "generation": str(sealed.generation),
                },
            ):
                self._prune_superseded_completions(sealed)
                return sealed
            candidate += 1
        raise VectorDbWriteError(
            f"could not establish a completion for {receipt.source_file!r} after "
            f"{_COMPLETION_ATTEMPT_LIMIT} attempts; fail-closed (N28)."
        )

    @staticmethod
    def _completion_uuid(project_id: str, sequence: int) -> str:
        return str(uuid.uuid5(_RECEIPT_NAMESPACE, f"{project_id}|{sequence}"))

    def _highest_completion_sequence(self, project_id: str) -> int:
        """Return the highest completion position already established (N28)."""
        rows = self.client.fetch_by_property(
            collection=RECEIPT_COLLECTION,
            project_id=project_id,
            prop="project_id",
            value=project_id,
            return_props=RECEIPT_PROPERTIES,
        )
        highest = 0
        for _uid, props in rows:
            highest = max(highest, _positive_int(props.get("sequence"), field_name="sequence"))
        return highest

    def _prune_superseded_completions(self, current: SyncReceipt) -> None:
        """Delete completions of the SAME source from OLDER generations (N39).

        Pruning follows the same order as the authority rule: only a strictly lower
        SOURCE GENERATION is superseded. Pruning by completion position would let a
        stale append delete the newer owner's valid completion (best-effort
        housekeeping either way -- correctness comes from the winning record).
        """
        import contextlib

        stale = [
            self._completion_uuid(current.project_id, receipt.sequence)
            for receipt in self.list_receipts(project_id=current.project_id)
            if receipt.source_file == current.source_file
            and receipt.generation < current.generation
        ]
        if not stale:
            return
        with contextlib.suppress(VectorDbUnavailableError, VectorDbWriteError):
            self.client.delete_by_ids(collection=RECEIPT_COLLECTION, uuids=stale)

    def list_receipts(self, *, project_id: str) -> Sequence[SyncReceipt]:
        """Return every persisted completion of a project (each verified, N08/N28)."""
        rows = self.client.fetch_by_property(
            collection=RECEIPT_COLLECTION,
            project_id=project_id,
            prop="project_id",
            value=project_id,
            return_props=RECEIPT_PROPERTIES,
        )
        out: list[SyncReceipt] = []
        for uid, props in rows:
            source_file = props.get("source_file")
            if not isinstance(source_file, str) or not source_file:
                raise VectorDbUnavailableError(
                    "persisted sync completion carries no usable 'source_file'; "
                    "fail-closed (N08)."
                )
            completion = receipt_from_props(project_id, source_file, props)
            # The record's POSITION is part of its identity: a completion stored
            # under a different position than it binds to has been moved/replayed.
            expected_uuid = self._completion_uuid(project_id, completion.sequence)
            if uid != expected_uuid:
                raise VectorDbUnavailableError(
                    f"persisted completion for {source_file!r} is stored at {uid!r} "
                    f"but binds position {completion.sequence} ({expected_uuid!r}); "
                    "fail-closed (N28: completions are immutable and position-bound)."
                )
            out.append(completion)
        return out

    def try_claim_source(
        self, *, project_id: str, source_file: str, owner_id: str
    ) -> SourceClaim | None:
        """Atomically claim a source by CREATING the next source generation (N37).

        The claim is STORE-LEVEL and ATOMIC (N03/D3): each generation is a distinct
        record whose uuid folds in the generation number, so acquiring it is a
        compare-and-create the store arbitrates -- there is no read-then-write window
        in which two writers both observe "no claim" and both proceed.

        The generation ladder is PERSISTENT and STRICTLY MONOTONIC per
        ``(project_id, source_file)`` (N37): a normal release does not remove the
        ladder position, it adds an insert-only ``released`` marker, so the next
        acquisition allocates a strictly HIGHER number. Without that, a released
        claim used to reset the ladder to 1 and no ordering statement about "who
        wrote this object" was decidable at all.

        There is NO time-based takeover (N27/D3): a HELD generation rejects the
        writer, no matter how old it is. It is released only by its holder finishing
        or by the EXPLICIT :meth:`reclaim_source` path.
        """
        rows = self._generation_rows(project_id, source_file)
        highest = self._highest_generation(rows)
        if self._held_claim(project_id, source_file, rows) is not None:
            return None
        return self._create_generation(
            project_id=project_id,
            source_file=source_file,
            owner_id=owner_id,
            generation=highest + 1,
        )

    def reclaim_source(
        self, *, project_id: str, source_file: str, owner_id: str, reason: str
    ) -> SourceClaim:
        """ADMINISTRATIVELY take a claim over by creating the NEXT generation (N27).

        Only reached from an explicit operator path, which asserts the previous
        holder is dead. The takeover is a conditional CREATE of the next generation,
        so two concurrent reclaimers still produce exactly one winner, and the
        previous holder can never again delete data this generation writes (N37: its
        generation is strictly lower).
        """
        rows = self._generation_rows(project_id, source_file)
        held = self._held_claim(project_id, source_file, rows)
        generation = self._highest_generation(rows) + 1
        claim = self._create_generation(
            project_id=project_id,
            source_file=source_file,
            owner_id=owner_id,
            generation=generation,
            reclaimed_from=held.owner_id if held is not None else "",
            reason=reason,
        )
        if claim is None:
            raise ConcurrentSyncRejectedError(
                f"administrative reclaim of {(project_id, source_file)!r} lost the "
                f"race for generation {generation}; fail-closed (N27)."
            )
        return claim

    def _create_generation(
        self,
        *,
        project_id: str,
        source_file: str,
        owner_id: str,
        generation: int,
        reclaimed_from: str = "",
        reason: str = "",
    ) -> SourceClaim | None:
        """Conditionally CREATE one generation; ``None`` when it is already taken."""
        claimed_at = _iso(self._now())
        acquired = self.client.insert_object(
            collection=CLAIM_COLLECTION,
            uuid=self._claim_uuid(project_id, source_file, generation),
            properties={
                "project_id": project_id,
                "source_file": source_file,
                "state": CLAIM_STATE_HELD,
                "owner_id": owner_id,
                "generation": str(generation),
                "claimed_at": claimed_at,
                "reclaimed_from": reclaimed_from,
                "reclaim_reason": reason,
            },
        )
        if not acquired:
            return None
        self._prune_generations_below(project_id, source_file, generation)
        return SourceClaim(
            project_id=project_id,
            source_file=source_file,
            owner_id=owner_id,
            generation=generation,
            claimed_at=claimed_at,
            reclaimed_from=reclaimed_from,
        )

    def assert_claim_held(self, *, claim: SourceClaim) -> None:
        """Fence: the claim must still be the HELD generation (N15/N27).

        This check can be overtaken between here and the following mutation, which
        is why it is NOT what protects the destructive step -- that is bound
        storage-side to the generation ordering (N37).
        """
        held = self._held_claim(claim.project_id, claim.source_file)
        if held is None or held.generation != claim.generation or held.owner_id != claim.owner_id:
            raise ClaimSupersededError(
                f"source claim on {(claim.project_id, claim.source_file)!r} was "
                f"superseded (held generation {claim.generation} owner "
                f"{claim.owner_id!r}, active {held!r}); fail-closed (N15/N27)."
            )

    def release_source(self, *, claim: SourceClaim) -> None:
        """Release the held generation by ADDING its release marker (N37/N45).

        Insert-only: the ladder position survives, so the next acquisition of this
        source is strictly higher.

        The release is CONFIRMED, not best-effort (N45). A suppressed failure left the
        source held forever: the sync could publish its completion, fail to persist the
        marker, report success, and every later sync of that source would then be
        rejected until someone issued an administrative reclaim with no idea why. A
        release that did not land is therefore a typed, named fault.

        Raises:
            ClaimReleaseFailedError: When the marker could not be persisted, or the
                store denied it. An ALREADY EXISTING marker is success -- releasing
                twice is idempotent, not a fault.
        """
        from agentkit.backend.vectordb.sync import ClaimReleaseFailedError

        try:
            created = self.client.insert_object(
                collection=CLAIM_COLLECTION,
                uuid=self._release_uuid(
                    claim.project_id, claim.source_file, claim.generation
                ),
                properties={
                    "project_id": claim.project_id,
                    "source_file": claim.source_file,
                    "state": CLAIM_STATE_RELEASED,
                    "owner_id": claim.owner_id,
                    "generation": str(claim.generation),
                    "claimed_at": _iso(self._now()),
                    "reclaimed_from": "",
                    "reclaim_reason": "",
                },
            )
        except (VectorDbUnavailableError, VectorDbWriteError) as exc:
            raise ClaimReleaseFailedError(
                f"source {(claim.project_id, claim.source_file)!r} generation "
                f"{claim.generation} could NOT be released ({exc}); it stays HELD and "
                "every later sync of it will be rejected until an administrative "
                "reclaim. Reported instead of suppressed (fail-closed, N45)."
            ) from exc
        if not created and not self._release_marker_exists(claim):
            raise ClaimReleaseFailedError(
                f"source {(claim.project_id, claim.source_file)!r} generation "
                f"{claim.generation} could NOT be released: the store neither created "
                "nor holds the release marker; it stays HELD (fail-closed, N45)."
            )

    def _release_marker_exists(self, claim: SourceClaim) -> bool:
        """Whether THIS generation's valid release marker is persisted (N45/N50).

        The deterministic uuid alone is not proof. Accepting any row stored at that id
        meant a malformed duplicate -- e.g. one carrying ``state=claimed`` -- made the
        sync report a successful release while the source stayed HELD, which is exactly
        the silent-success path N45 closed. The persisted record is therefore validated
        in FULL: it must be a ``released`` marker for this project, source, owner and
        generation. Anything else is not this claim's release.

        Args:
            claim: The claim whose release is being confirmed.

        Returns:
            ``True`` only for a complete, matching release marker.
        """
        wanted = self._release_uuid(
            claim.project_id, claim.source_file, claim.generation
        )
        expected = {
            "project_id": claim.project_id,
            "source_file": claim.source_file,
            "state": CLAIM_STATE_RELEASED,
            "owner_id": claim.owner_id,
            "generation": str(claim.generation),
        }
        for uid, props in self._generation_rows(claim.project_id, claim.source_file):
            if uid != wanted:
                continue
            return all(props.get(name) == value for name, value in expected.items())
        return False

    def _prune_generations_below(
        self, project_id: str, source_file: str, generation: int
    ) -> None:
        """Drop ladder records BELOW the given generation (housekeeping only).

        The record of the highest generation is never removed, so the ladder cannot
        reset -- that is the property the destructive delete depends on. Everything
        below it carries no decision any more.
        """
        import contextlib

        stale: list[str] = []
        for _uid, props in self._generation_rows(project_id, source_file):
            row_generation = _positive_int(props.get("generation"), field_name="generation")
            if row_generation >= generation:
                continue
            stale.append(self._claim_uuid(project_id, source_file, row_generation))
            stale.append(self._release_uuid(project_id, source_file, row_generation))
        if not stale:
            return
        with contextlib.suppress(VectorDbUnavailableError, VectorDbWriteError):
            self.client.delete_by_ids(collection=CLAIM_COLLECTION, uuids=stale)

    @staticmethod
    def _claim_uuid(project_id: str, source_file: str, generation: int) -> str:
        return str(
            uuid.uuid5(_CLAIM_NAMESPACE, f"{project_id}|{source_file}|{generation}")
        )

    @staticmethod
    def _release_uuid(project_id: str, source_file: str, generation: int) -> str:
        return str(
            uuid.uuid5(
                _CLAIM_NAMESPACE, f"{project_id}|{source_file}|{generation}|released"
            )
        )

    def _generation_rows(
        self, project_id: str, source_file: str
    ) -> list[tuple[str, Mapping[str, object]]]:
        """Return this source's ladder records (claims AND release markers).

        Read with the SAME server-side project scope as the corpus (AC4/N51): the
        app-side filter that used to follow was not enough, because another project
        holding the same ``source_file`` still had to be transported and could push this
        read into the pagination ceiling.
        """
        return list(
            self.client.fetch_by_property(
                collection=CLAIM_COLLECTION,
                project_id=project_id,
                prop="source_file",
                value=source_file,
                return_props=CLAIM_PROPERTIES,
            )
        )

    @staticmethod
    def _highest_generation(rows: Sequence[tuple[str, Mapping[str, object]]]) -> int:
        """Return the highest generation EVER allocated for the source (N37).

        Release markers count: the ladder must not reset when a claim is released,
        or "written by an older generation" stops being decidable.
        """
        highest = 0
        for _uid, props in rows:
            highest = max(
                highest, _positive_int(props.get("generation"), field_name="generation")
            )
        return highest

    def _held_claim(
        self,
        project_id: str,
        source_file: str,
        rows: Sequence[tuple[str, Mapping[str, object]]] | None = None,
    ) -> SourceClaim | None:
        """Return the currently HELD claim of a source, or ``None``.

        The highest generation decides: it is held when it has a ``claimed`` record
        and no ``released`` marker. Older generations carry no ownership any more.
        """
        ladder = list(rows) if rows is not None else self._generation_rows(project_id, source_file)
        highest = self._highest_generation(ladder)
        if highest == 0:
            return None
        claimed: SourceClaim | None = None
        for _uid, props in ladder:
            generation = _positive_int(props.get("generation"), field_name="generation")
            if generation != highest:
                continue
            if props.get("state") == CLAIM_STATE_RELEASED:
                return None
            claimed = _claim_from_props(project_id, source_file, props)
        return claimed

    def _now(self) -> datetime:
        return self.clock()


def _positive_int(raw: object, *, field_name: str) -> int:
    """Read a positive integer strictly (no coercion, no bool-as-int, N08/N16)."""
    if isinstance(raw, bool) or not isinstance(raw, (int, str)):
        raise VectorDbUnavailableError(
            f"persisted record has a non-numeric {field_name!r} ({raw!r}); "
            "fail-closed (N08/N16)."
        )
    try:
        value = int(raw)
    except ValueError as exc:
        raise VectorDbUnavailableError(
            f"persisted record has a non-numeric {field_name!r} ({raw!r}); "
            "fail-closed (N08/N16)."
        ) from exc
    if value < 1:
        raise VectorDbUnavailableError(
            f"persisted record has a non-positive {field_name!r} ({value}); "
            "fail-closed (N08/N16)."
        )
    return value


def _required_strings(
    props: Mapping[str, object], names: Sequence[str], *, context: str
) -> dict[str, str]:
    """Read mandatory string fields strictly (no ``str()`` coercion, N08)."""
    values: dict[str, str] = {}
    for field_name in names:
        raw = props.get(field_name)
        if not isinstance(raw, str) or not raw:
            raise VectorDbUnavailableError(
                f"persisted {context} has a missing/non-string {field_name!r} "
                f"({raw!r}); fail-closed (N08)."
            )
        values[field_name] = raw
    return values


def _claim_from_props(
    project_id: str, source_file: str, props: Mapping[str, object]
) -> SourceClaim:
    """Rebuild a persisted claim strictly (owner/generation/timestamp, N15/N27/N37).

    There is NO expiry field: a claim never expires by time (N27). ``claimed_at``
    is diagnostics and must still be a valid UTC instant.
    """
    values = _required_strings(
        props, ("owner_id", "state", "claimed_at"), context="source claim"
    )
    if values["state"] not in (CLAIM_STATE_HELD, CLAIM_STATE_RELEASED):
        raise VectorDbUnavailableError(
            f"persisted source claim for {source_file!r} has unknown state "
            f"{values['state']!r}; fail-closed (N15)."
        )
    parse_utc_timestamp(values["claimed_at"])
    reclaimed_from = props.get("reclaimed_from")
    return SourceClaim(
        project_id=project_id,
        source_file=source_file,
        owner_id=values["owner_id"],
        generation=_positive_int(props.get("generation"), field_name="generation"),
        claimed_at=values["claimed_at"],
        reclaimed_from=reclaimed_from if isinstance(reclaimed_from, str) else "",
    )


def receipt_from_props(
    project_id: str, source_file: str, props: Mapping[str, object]
) -> SyncReceipt:
    """Rebuild a persisted receipt with FULL verification (N08/N16).

    Every mandatory field must be present and string-typed (no ``str()``
    coercion), the state must be a KNOWN receipt state, the timestamp a UTC
    instant, the sequence positive, and the digest must bind every identity AND
    ordering field. Anything else raises -- a malformed, replayed or unknown-state
    receipt can never advance the reported freshness, and an unknown state is
    REJECTED rather than skipped (which would hide it).
    """
    from agentkit.backend.vectordb.sync import ReceiptState, SyncError

    values = _required_strings(
        props,
        ("project_id", "source_file", "source_type", "corpus_revision", "digest", "state", "completed_at"),
        context=f"sync receipt for {source_file!r}",
    )
    sequence = _positive_int(props.get("sequence"), field_name="sequence")
    generation = _positive_int(props.get("generation"), field_name="generation")
    if values["project_id"] != project_id or values["source_file"] != source_file:
        raise VectorDbUnavailableError(
            f"persisted sync receipt identity mismatch: record "
            f"({values['project_id']!r}, {values['source_file']!r}) != requested "
            f"({project_id!r}, {source_file!r}); fail-closed (N08)."
        )
    try:
        state = ReceiptState(values["state"])
    except ValueError as exc:
        raise VectorDbUnavailableError(
            f"persisted sync receipt for {source_file!r} has unknown state "
            f"{values['state']!r}; fail-closed (N16: an unknown state is rejected, "
            "never skipped)."
        ) from exc
    receipt = SyncReceipt(
        project_id=project_id,
        source_file=source_file,
        source_type=values["source_type"],
        corpus_revision=values["corpus_revision"],
        digest=values["digest"],
        state=state,
        completed_at=values["completed_at"],
        sequence=sequence,
        generation=generation,
    )
    try:
        receipt.verify()
    except SyncError as exc:
        raise VectorDbUnavailableError(
            f"persisted sync receipt for {source_file!r} is not trustworthy: {exc}"
        ) from exc
    return receipt


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
        return [
            {**props, "score": score, "snippet": str(props.get("content", ""))[:200]}
            for _uid, props, score in rows
        ]

    def list_sources(self, *, project_id: str) -> Sequence[Mapping[str, object]]:
        from agentkit.backend.vectordb.ingest.classify import PRODUCER_BY_SOURCE_TYPE

        receipts = self.store.list_receipts(project_id=project_id)
        # AG3-177 (c): the authoritative generation per source comes from the SAME
        # completion set this listing already reads, so making the residual
        # detectable costs no additional transport.
        authority = authoritative_generations(receipts)
        out: list[Mapping[str, object]] = []
        for source_type, producer in PRODUCER_BY_SOURCE_TYPE.items():
            rows = self.store.list_objects_for_source_types(
                project_id=project_id, source_types=(source_type,)
            )
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
                    "last_revision": _last_completed_revision(receipts, source_type),
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


def stale_chunk_count(
    rows: Sequence[Mapping[str, object]], authority: Mapping[str, int]
) -> int:
    """Count rows that are NOT part of their source's authoritative generation.

    This is the observable form of the residual AG3-177 ratified as a contract: after a
    hung sync, a deliberate administrative takeover and a resurrected writer, rows of an
    OLDER generation can sit beside the current ones until the next sync of that source
    removes them -- a moment that is not time-bounded. A residual nobody can notice would
    be a concealed residual, so it is counted and reported.

    Counted:

    - a row whose generation is strictly BELOW its source's authoritative generation
      (the takeover residual, and exactly what the next sync's ordered delete removes);
    - a row with NO generation at all (a legacy row predating the ordering property);
      the same remedy applies -- the next sync converges it;
    - a row whose generation is present but unusable. It is certainly not authoritative,
      and it needs attention rather than a sync: the sync path rejects it by name.

    NOT counted:

    - rows of a source that has no completion at all -- there is no authority to judge
      them against, and inventing one would be a guess;
    - rows of a generation ABOVE the authoritative one: that is an in-flight newer
      generation whose completion is not published yet, not a remnant.

    Args:
        rows: The source rows as read (uuid, source_file, writing generation).
        authority: The authoritative generation per source file.

    Returns:
        The number of non-authoritative rows.
    """
    count = 0
    for row in rows:
        authoritative = authority.get(str(row.get("source_file", "")))
        if authoritative is None:
            continue
        raw = row.get(OWNING_GENERATION_PROPERTY)
        if isinstance(raw, bool) or not isinstance(raw, int):
            count += 1  # absent or unusable -> not part of the authoritative generation
            continue
        if raw < authoritative:
            count += 1
    return count


def _last_completed_revision(
    receipts: Sequence[SyncReceipt], source_type: str
) -> str:
    """Return the revision of the LAST successful completion of a source type (N04).

    Ordering is the persisted completion ``sequence`` (store-monotonic); the
    ``completed_at`` timestamp and the source file break ties deterministically.
    An unfinished (``in_progress``) receipt is not a completion.
    """
    completed = [
        r
        for r in receipts
        if r.source_type == source_type and r.state.value == "completed"
    ]
    if not completed:
        return ""
    latest = max(completed, key=lambda r: (r.sequence, r.completed_at, r.source_file))
    return latest.corpus_revision


def ensure_corpus_collections(client: CorpusClientPort) -> None:
    """Create OR verify the three corpus collections against the schema SSOT.

    Shared by EVERY write path into ``StoryContext`` (N38): the MCP runtime and the
    story-export/split/repair sync owner bootstrap the same schema, so a collection
    can never be created without the ownership-ordering property the destructive
    delete conditions on.

    The auxiliary receipt/claim collections are ensured too and NOT suppressed -- a
    failure must surface fail-closed (N08), since completion/claim persistence is
    required for the freshness and D3 contracts.
    """
    from agentkit.backend.vectordb.schema import (
        FK13_VECTOR_SOURCE_PROPERTIES,
        FK13_VECTORIZER,
        FK13_VECTORIZER_MODEL,
        weaviate_property_specs,
    )

    client.ensure_collection(
        collection=STORY_CONTEXT_COLLECTION,
        property_specs=weaviate_property_specs(),
        vectorizer=FK13_VECTORIZER,
        vectorizer_model=FK13_VECTORIZER_MODEL,
        vector_source_properties=FK13_VECTOR_SOURCE_PROPERTIES,
    )
    client.ensure_collection(
        collection=RECEIPT_COLLECTION,
        property_specs=_receipt_property_specs(),
        vectorizer="self_provided",
    )
    client.ensure_collection(
        collection=CLAIM_COLLECTION,
        property_specs=_aux_property_specs(CLAIM_PROPERTIES),
        vectorizer="self_provided",
    )


def connect_real_client(binding: RuntimeBinding) -> CorpusClientPort:
    """Build a real Weaviate client from the binding's EXACT endpoints (R02/R03).

    Both endpoints come verbatim from the registered env (D2) and are passed into
    ``weaviate.connect_to_custom`` -- the only connect API of the pinned client
    that accepts a DISTINCT gRPC host (``connect_to_local`` does not, R03).
    Raises :class:`VectorDbUnavailableError` fail-closed.
    """
    from agentkit.integration_clients.vectordb.weaviate_adapter import _build_real_client

    http_host, http_port, http_secure = _split_endpoint(binding.weaviate_http_endpoint)
    grpc_host, grpc_port, grpc_secure = _split_grpc(binding.weaviate_grpc_endpoint)
    return _build_real_client(  # type: ignore[return-value]
        http_host=http_host,
        http_port=http_port,
        http_secure=http_secure,
        grpc_host=grpc_host,
        grpc_port=grpc_port,
        grpc_secure=grpc_secure,
    )


def _split_endpoint(endpoint: str) -> tuple[str, int, bool]:
    """Split an ``http(s)://host:port`` endpoint into ``(host, port, secure)``."""
    import urllib.parse

    parsed = urllib.parse.urlparse(endpoint)
    if parsed.scheme not in ("http", "https"):
        raise VectorDbUnavailableError(
            f"WEAVIATE_HTTP_ENDPOINT {endpoint!r} must be http(s)://host:port "
            "(fail-closed, D2)."
        )
    if not parsed.hostname or parsed.port is None:
        raise VectorDbUnavailableError(
            f"WEAVIATE_HTTP_ENDPOINT {endpoint!r} is not host:port (fail-closed, D2)."
        )
    return parsed.hostname, parsed.port, parsed.scheme == "https"


def _split_grpc(endpoint: str) -> tuple[str, int, bool]:
    """Split a gRPC endpoint into ``(host, port, secure)`` fail-closed.

    Accepts ``host:port`` as well as an explicit ``grpc://``/``grpcs://`` scheme;
    ``grpcs`` selects a TLS gRPC channel.
    """
    candidate = endpoint
    secure = False
    if candidate.startswith("grpcs://"):
        secure = True
        candidate = candidate.removeprefix("grpcs://")
    elif candidate.startswith("grpc://"):
        candidate = candidate.removeprefix("grpc://")
    if ":" not in candidate:
        raise VectorDbUnavailableError(
            f"WEAVIATE_GRPC_ENDPOINT {endpoint!r} is not host:port (fail-closed, D2)."
        )
    host, _, port = candidate.rpartition(":")
    if not host:
        raise VectorDbUnavailableError(
            f"WEAVIATE_GRPC_ENDPOINT {endpoint!r} is not host:port (fail-closed, D2)."
        )
    try:
        return host, int(port), secure
    except ValueError as exc:
        raise VectorDbUnavailableError(
            f"WEAVIATE_GRPC_ENDPOINT {endpoint!r} has non-integer port (fail-closed, D2)."
        ) from exc


def compose_runtime(
    env: Mapping[str, str],
    *,
    concepts_dir: Path,
    stories_dir: Path,
    command: str = "python",
    args: tuple[str, ...] = (),
    cwd: str = ".",
) -> object:
    """Build the productive :class:`McpToolService` from the env (R02).

    Ensures the StoryContext collection exists idempotently. Fails closed on any
    binding or connection fault.
    """
    from agentkit.backend.vectordb.mcp_server import McpToolService

    binding = RuntimeBinding.from_env(env, command=command, args=args, cwd=cwd)
    client = connect_real_client(binding)
    # Idempotent collection creation. The schema-OWNER (schema.py) declares the
    # property set via ``weaviate_property_specs()`` + the FK-13 §13.2
    # server-side text2vec-transformers vectorizer (N02); the thin adapter's
    # ``ensure_collection`` materialises it. Created via the port (not raw
    # ``.collections``) so it works through the CorpusClientPort boundary.
    ensure_corpus_collections(client)
    store = WeaviateCorpusStore(client=client)
    sync = SyncService(store=store)
    retrieval = WeaviateRetrievalPort(client=client, store=store, binding=binding)
    return McpToolService(
        binding=binding,
        retrieval=retrieval,
        sync=sync,
        concepts_dir=concepts_dir,
        stories_dir=stories_dir,
    )


def _aux_property_specs(names: Sequence[str]) -> list[dict[str, object]]:
    """Property specs of an auxiliary bookkeeping collection.

    Auxiliary records are pure state (receipts, claims, sequence tokens): every
    field is an exact-match identifier, so nothing is vectorised, nothing is
    BM25-searchable and everything stays whole-value tokenised.
    """
    return [
        {
            "name": name,
            "data_type": "TEXT",
            "skip_vectorization": True,
            "vectorize_property_name": False,
            "filterable": True,
            "tokenization": "FIELD",
            "searchable": False,
        }
        for name in names
    ]


def _receipt_property_specs() -> list[dict[str, object]]:
    """Property specs of the auxiliary receipt collection."""
    return _aux_property_specs(RECEIPT_PROPERTIES)


def run_stdio_server(service: object) -> None:
    """Run the FastMCP server over stdio for the composed service (R02)."""
    from agentkit.backend.vectordb.mcp_server import build_mcp_server

    server = build_mcp_server(service)  # type: ignore[arg-type]
    server.run()


def main() -> int:
    """Executable stdio entry point.

    Reads the env, composes the production engine, and serves. Fails closed
    (exit 1) on any binding/connection fault -- never starts on a localhost
    default or missing endpoint (D2).
    """
    import os

    env = dict(os.environ)
    cwd = os.getcwd()
    # N20/D2: the concept corpus root is project configuration and must come from
    # the registered env. Defaulting to the literal ``concept`` pointed the server
    # at AK3's OWN development corpus; a missing binding stops the server.
    concepts_dir_value = env.get("AGENTKIT_CONCEPTS_DIR", "").strip()
    if not concepts_dir_value:
        print(
            json.dumps(
                {
                    "error": "composition_failed",
                    "detail": (
                        "AGENTKIT_CONCEPTS_DIR is missing/empty; the concept corpus "
                        "root has no default (fail-closed, D2/N20)."
                    ),
                }
            )
        )
        return 1
    concepts_dir = _resolve_dir(concepts_dir_value)
    # The story corpus root is the CANONICAL relative layout the classifier
    # recognises (FK-13 §13.3.2 ``stories/<story>/story.md``), resolved inside the
    # bound cwd -- not a foreign path.
    stories_dir = _resolve_dir(env.get("AGENTKIT_STORIES_DIR", "stories"))
    try:
        service = compose_runtime(
            env,
            concepts_dir=concepts_dir,
            stories_dir=stories_dir,
            cwd=cwd,
        )
    except (RuntimeBindingError, VectorDbUnavailableError) as exc:
        print(json.dumps({"error": "composition_failed", "detail": str(exc)}))
        return 1
    run_stdio_server(service)
    return 0


def _resolve_dir(path: str) -> Path:
    from pathlib import Path

    return Path(path).resolve()


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())


__all__ = [
    "CLAIM_COLLECTION",
    "RECEIPT_COLLECTION",
    "RECEIPT_PROPERTIES",
    "WeaviateCorpusStore",
    "WeaviateRetrievalPort",
    "compose_runtime",
    "connect_real_client",
    "main",
    "receipt_from_props",
    "run_stdio_server",
]
