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
from typing import TYPE_CHECKING, Final, Protocol

from agentkit.backend.vectordb.runtime_binding import RuntimeBinding, RuntimeBindingError
from agentkit.backend.vectordb.schema import (
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
)

#: Dedicated collection for store-level atomic source claims (N03/D3/N15).
CLAIM_COLLECTION = "__agentkit_source_claims"

#: The claim record's full property set (owner/epoch, no expiry -- N15/N27).
CLAIM_PROPERTIES: tuple[str, ...] = (
    "project_id",
    "source_file",
    "state",
    "owner_id",
    "epoch",
    "claimed_at",
    "reclaimed_from",
    "reclaim_reason",
)

#: Bounded number of completion positions tried before failing closed (N28).
_COMPLETION_ATTEMPT_LIMIT: Final[int] = 256

#: Stable namespace for the position-bound completion records (N28).
_RECEIPT_NAMESPACE = uuid.UUID("8c5e2f3a-1b6d-4e7a-9c8f-2a1b3c4d5e6f")
#: Stable namespace for per-source, per-epoch claim identity (N03/N15).
_CLAIM_NAMESPACE = uuid.UUID("9d6f3a4b-2c7e-5f8b-ad9c-3b2c4d5e6f7a")

def _utc_clock() -> datetime:
    """Return the current UTC instant (the store's default clock)."""
    return datetime.now(UTC)


def _iso(value: datetime) -> str:
    """Render a UTC instant as an ISO-8601 string with a ``Z`` suffix."""
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


class CorpusClientPort(Protocol):
    """The thin-adapter corpus surface the engine needs (R02)."""

    def fetch_by_property(
        self, *, collection: str, prop: str, value: str, return_props: Sequence[str]
    ) -> Sequence[tuple[str, dict[str, object]]]: ...

    def fetch_by_property_any(
        self, *, collection: str, prop: str, values: Sequence[str], return_props: Sequence[str]
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

    def ensure_collection(
        self,
        *,
        collection: str,
        property_specs: Sequence[Mapping[str, object]],
        vectorizer: str = ...,
        vectorizer_model: Mapping[str, object] | None = ...,
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
            prop="source_file",
            value=source_file,
            return_props=("content_hash", "source_type", "project_id"),
        )
        return [
            {"uuid": uid, "source_file": source_file, "source_type": p.get("source_type", ""),
             "project_id": p.get("project_id", ""), "content_hash": p.get("content_hash", "")}
            for uid, p in rows
            if str(p.get("project_id", "")) == project_id
        ]

    def list_objects_for_source_types(
        self, *, project_id: str, source_types: Sequence[str]
    ) -> Sequence[Mapping[str, object]]:
        rows = self.client.fetch_by_property_any(
            collection=self.collection,
            prop="source_type",
            values=tuple(source_types),
            return_props=("source_file", "project_id", "source_type"),
        )
        return [
            {"uuid": uid, "source_file": p.get("source_file", ""),
             "source_type": p.get("source_type", ""), "project_id": p.get("project_id", "")}
            for uid, p in rows
            if str(p.get("project_id", "")) == project_id
        ]

    def upsert_objects(self, *, objects: Sequence[StoryContextObject]) -> int:
        # Exact confirmed count: the adapter inspects batch failures and raises
        # on a partial batch (R12); a clean return == len(objects).
        docs = [{**obj.properties, "uuid": obj.uuid} for obj in objects]
        return self.client.upsert(collection=self.collection, objects=docs)

    def delete_objects(self, *, uuids: Sequence[str]) -> int:
        return self.client.delete_by_ids(collection=self.collection, uuids=tuple(uuids))

    def get_receipt(self, *, project_id: str, source_file: str) -> SyncReceipt | None:
        """Return the LATEST verified completion of one source (N28)."""
        completions = [
            receipt
            for receipt in self.list_receipts(project_id=project_id)
            if receipt.source_file == source_file
        ]
        if not completions:
            return None
        return max(completions, key=lambda r: r.sequence)

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
            prop="project_id",
            value=project_id,
            return_props=RECEIPT_PROPERTIES,
        )
        highest = 0
        for _uid, props in rows:
            highest = max(highest, _positive_int(props.get("sequence"), field_name="sequence"))
        return highest

    def _prune_superseded_completions(self, current: SyncReceipt) -> None:
        """Delete older completions of the SAME source (best-effort housekeeping)."""
        import contextlib

        stale = [
            self._completion_uuid(current.project_id, receipt.sequence)
            for receipt in self.list_receipts(project_id=current.project_id)
            if receipt.source_file == current.source_file
            and receipt.sequence < current.sequence
        ]
        if not stale:
            return
        with contextlib.suppress(VectorDbUnavailableError, VectorDbWriteError):
            self.client.delete_by_ids(collection=RECEIPT_COLLECTION, uuids=stale)

    def list_receipts(self, *, project_id: str) -> Sequence[SyncReceipt]:
        """Return every persisted completion of a project (each verified, N08/N28)."""
        rows = self.client.fetch_by_property(
            collection=RECEIPT_COLLECTION,
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
        """Atomically claim a source via a conditional CREATE of the NEXT epoch.

        The claim is STORE-LEVEL and ATOMIC (N03/D3): each claim generation is a
        distinct record whose uuid folds in the epoch, so acquiring it is a
        compare-and-create the store arbitrates -- there is no read-then-write
        window in which two writers both observe "no claim" and both proceed.

        There is NO time-based takeover (N27/D3): a claim that exists rejects the
        writer, no matter how old it is. A claim left behind by a dead writer is
        released only by the EXPLICIT :meth:`reclaim_source` path.
        """
        active = self._active_claim(project_id, source_file)
        if active is not None:
            return None
        return self._create_claim(
            project_id=project_id, source_file=source_file, owner_id=owner_id, epoch=1
        )

    def reclaim_source(
        self, *, project_id: str, source_file: str, owner_id: str, reason: str
    ) -> SourceClaim:
        """ADMINISTRATIVELY take a claim over by creating the NEXT epoch (N27).

        Only reached from an explicit operator path, which asserts the previous
        holder is dead. The takeover is a conditional CREATE of epoch+1, so two
        concurrent reclaimers still produce exactly one winner, and the previous
        holder is fenced out of every further mutation.
        """
        active = self._active_claim(project_id, source_file)
        epoch = (active.epoch if active is not None else 0) + 1
        claim = self._create_claim(
            project_id=project_id,
            source_file=source_file,
            owner_id=owner_id,
            epoch=epoch,
            reclaimed_from=active.owner_id if active is not None else "",
            reason=reason,
        )
        if claim is None:
            raise ConcurrentSyncRejectedError(
                f"administrative reclaim of {(project_id, source_file)!r} lost the "
                f"race for epoch {epoch}; fail-closed (N27)."
            )
        if active is not None:
            # The superseded generation is no longer authoritative; removing its
            # record is housekeeping, never a correctness step (the epoch decides).
            self._discard_claim(project_id, source_file, active.epoch)
        return claim

    def _create_claim(
        self,
        *,
        project_id: str,
        source_file: str,
        owner_id: str,
        epoch: int,
        reclaimed_from: str = "",
        reason: str = "",
    ) -> SourceClaim | None:
        """Conditionally CREATE one claim generation; ``None`` when it is taken."""
        claimed_at = _iso(self._now())
        acquired = self.client.insert_object(
            collection=CLAIM_COLLECTION,
            uuid=self._claim_uuid(project_id, source_file, epoch),
            properties={
                "project_id": project_id,
                "source_file": source_file,
                "state": "claimed",
                "owner_id": owner_id,
                "epoch": str(epoch),
                "claimed_at": claimed_at,
                "reclaimed_from": reclaimed_from,
                "reclaim_reason": reason,
            },
        )
        if not acquired:
            return None
        return SourceClaim(
            project_id=project_id,
            source_file=source_file,
            owner_id=owner_id,
            epoch=epoch,
            claimed_at=claimed_at,
            reclaimed_from=reclaimed_from,
        )

    def assert_claim_held(self, *, claim: SourceClaim) -> None:
        """Fence: the claim must still be the ACTIVE generation (N15/N27)."""
        active = self._active_claim(claim.project_id, claim.source_file)
        if active is None or active.epoch != claim.epoch or active.owner_id != claim.owner_id:
            raise ClaimSupersededError(
                f"source claim on {(claim.project_id, claim.source_file)!r} was "
                f"superseded (held epoch {claim.epoch} owner {claim.owner_id!r}, "
                f"active {active!r}); fail-closed (N15/N27)."
            )

    def release_source(self, *, claim: SourceClaim) -> None:
        """Release the held claim generation (best-effort, never masks a fault)."""
        self._discard_claim(claim.project_id, claim.source_file, claim.epoch)

    def _discard_claim(self, project_id: str, source_file: str, epoch: int) -> None:
        import contextlib

        with contextlib.suppress(VectorDbUnavailableError):
            self.client.delete_by_ids(
                collection=CLAIM_COLLECTION,
                uuids=[self._claim_uuid(project_id, source_file, epoch)],
            )

    @staticmethod
    def _claim_uuid(project_id: str, source_file: str, epoch: int) -> str:
        return str(uuid.uuid5(_CLAIM_NAMESPACE, f"{project_id}|{source_file}|{epoch}"))

    def _active_claim(self, project_id: str, source_file: str) -> SourceClaim | None:
        """Return the highest-epoch claim record of a source (the active one)."""
        rows = self.client.fetch_by_property(
            collection=CLAIM_COLLECTION,
            prop="source_file",
            value=source_file,
            return_props=CLAIM_PROPERTIES,
        )
        active: SourceClaim | None = None
        for _uid, props in rows:
            if props.get("project_id") != project_id:
                continue
            candidate = _claim_from_props(project_id, source_file, props)
            if active is None or candidate.epoch > active.epoch:
                active = candidate
        return active

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
    """Rebuild a persisted claim strictly (owner/epoch/timestamp, N15/N27).

    There is NO expiry field: a claim never expires by time (N27). ``claimed_at``
    is diagnostics and must still be a valid UTC instant.
    """
    values = _required_strings(
        props, ("owner_id", "state", "claimed_at"), context="source claim"
    )
    if values["state"] != "claimed":
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
        epoch=_positive_int(props.get("epoch"), field_name="epoch"),
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
                }
            )
        return out


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
    from agentkit.backend.vectordb.schema import (
        FK13_VECTORIZER,
        FK13_VECTORIZER_MODEL,
        weaviate_property_specs,
    )

    client.ensure_collection(
        collection=STORY_CONTEXT_COLLECTION,
        property_specs=weaviate_property_specs(),
        vectorizer=FK13_VECTORIZER,
        vectorizer_model=FK13_VECTORIZER_MODEL,
    )
    # The receipt + claim collections are auxiliary (no vectors); their creation
    # is NOT suppressed -- a failure to ensure them must surface fail-closed
    # (N08), since receipt/claim persistence is required for the bounded-window
    # freshness + D3 concurrent-reject contracts.
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
