"""Ingest engine with source/producer/delete closure (AG3-174 R04/R05/R12).

Bounded-window order (AC 6):
1. Write new desired generation completely
2. Re-read and validate the desired set (UUID/hash/project/source)
3. Only then delete old/foreign chunks of owned source types
4. Delete counters must prove matches==successful and failed==0
5. Only then publish a digest-bound receipt (caller)

Incremental path (R12): hash-based change detection; unchanged chunks are
``skipped`` and not re-upserted.
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol

from agentkit.backend.vectordb.ingest.builders import (
    build_concept_chunks,
    build_story_and_research_chunks,
)
from agentkit.backend.vectordb.ingest.models import ChunkRecord, SourceType, SyncCounters
from agentkit.backend.vectordb.ingest.source_routing import owned_source_types
from agentkit.backend.vectordb.schema import STORY_COLLECTION
from agentkit.backend.vectordb.single_writer import SingleWriterError, single_writer_lock

if TYPE_CHECKING:
    from pathlib import Path

    from agentkit.backend.vectordb.project_binding import ProjectBinding


class IngestError(Exception):
    """Raised when ingest write/validate/delete invariants fail (fail-closed)."""


class IngestStorePort(Protocol):
    """Minimal store surface used by the ingest engine."""

    def upsert(
        self,
        *,
        collection: str,
        objects: Sequence[Mapping[str, object]],
        uuids: Sequence[str] | None = None,
    ) -> int: ...

    def delete_by_filter(
        self,
        *,
        collection: str,
        project_id: str,
        source_types: Sequence[str] | None = None,
        source_file: str | None = None,
        generation_id_not: str | None = None,
    ) -> int: ...

    def fetch(
        self,
        *,
        collection: str,
        project_id: str,
        source_types: Sequence[str] | None = None,
        filters: Mapping[str, object] | None = None,
    ) -> Sequence[Mapping[str, object]]: ...


@dataclass(frozen=True)
class DeleteResult:
    """Strict delete counters (AC 10 / R04 / R07)."""

    matches: int
    successful: int
    failed: int


@dataclass(frozen=True)
class IngestReport:
    """Result of a story_sync or concept_sync run."""

    producer_tool: str
    project_id: str
    full_reindex: bool
    generation_id: str
    corpus_revision: str
    counters: SyncCounters
    source_types: tuple[str, ...]

    def as_dict(self) -> dict[str, object]:
        return {
            "producer_tool": self.producer_tool,
            "project_id": self.project_id,
            "full_reindex": self.full_reindex,
            "generation_id": self.generation_id,
            "corpus_revision": self.corpus_revision,
            "counters": self.counters.as_dict(),
            "source_types": list(self.source_types),
        }


class IngestEngine:
    """Project-scoped ingest with exclusive producer ownership."""

    def __init__(
        self,
        store: IngestStorePort,
        *,
        lock_dir: Path | None = None,
        lock_timeout_seconds: float = 30.0,
    ) -> None:
        self._store = store
        self._lock_dir = lock_dir
        self._lock_timeout = lock_timeout_seconds

    def story_sync(
        self,
        binding: ProjectBinding,
        *,
        full_reindex: bool = False,
        corpus_revision: str = "",
        publish_completion: bool = True,
    ) -> IngestReport:
        # R16: story corpus_revision is a digest over owned story/research files
        # when the caller does not supply one — never leave it permanently empty.
        rev = corpus_revision or _story_corpus_revision(binding)
        # Capture desired records for completion digest (R16).
        desired_holder: list[list[ChunkRecord]] = []

        def factory(gen: str, r: str) -> list[ChunkRecord]:
            recs = build_story_and_research_chunks(
                binding, generation_id=gen, corpus_revision=r
            )
            desired_holder.append(recs)
            return recs

        report = self._sync(
            binding=binding,
            producer_tool="story_sync",
            full_reindex=full_reindex,
            corpus_revision=rev,
            records_factory=factory,
        )
        if publish_completion:
            from agentkit.backend.vectordb.completion_store import (
                desired_set_digest_from_records,
            )
            from agentkit.backend.vectordb.completion_store import (
                publish_completion as _publish,
            )

            desired = desired_holder[0] if desired_holder else []
            _publish(
                binding.project_root,
                project_id=binding.project_id,
                producer_tool="story_sync",
                corpus_revision=report.corpus_revision,
                generation_id=report.generation_id,
                written=report.counters.written,
                deleted=report.counters.deleted,
                desired_set_digest=desired_set_digest_from_records(desired),
            )
        return report

    def concept_sync(
        self,
        binding: ProjectBinding,
        *,
        full_reindex: bool = False,
        corpus_revision: str = "",
        records: list[ChunkRecord] | None = None,
        source_file_filter: str | None = None,
        publish_completion: bool = True,
    ) -> IngestReport:
        def factory(gen: str, rev: str) -> list[ChunkRecord]:
            if records is not None:
                built = [_with_generation(r, gen, rev) for r in records]
            else:
                built = build_concept_chunks(
                    binding, generation_id=gen, corpus_revision=rev
                )
            if source_file_filter is not None:
                built = [r for r in built if r.source_file == source_file_filter]
            return built

        report = self._sync(
            binding=binding,
            producer_tool="concept_sync",
            full_reindex=full_reindex,
            corpus_revision=corpus_revision,
            records_factory=factory,
            source_file_filter=source_file_filter,
        )
        if publish_completion:
            # concept_sync_bounded_window may also publish; engine-level alone
            # still publishes when used without a staging outer call.
            from agentkit.backend.vectordb.completion_store import (
                desired_set_digest_from_records,
            )
            from agentkit.backend.vectordb.completion_store import (
                publish_completion as _publish,
            )

            desired = factory(report.generation_id, report.corpus_revision)
            _publish(
                binding.project_root,
                project_id=binding.project_id,
                producer_tool="concept_sync",
                corpus_revision=report.corpus_revision,
                generation_id=report.generation_id,
                written=report.counters.written,
                deleted=report.counters.deleted,
                desired_set_digest=desired_set_digest_from_records(desired),
            )
        return report

    def _sync(
        self,
        *,
        binding: ProjectBinding,
        producer_tool: str,
        full_reindex: bool,
        corpus_revision: str,
        records_factory: object,
        source_file_filter: str | None = None,
    ) -> IngestReport:
        owned = owned_source_types(producer_tool)
        owned_values = tuple(sorted(s.value for s in owned))
        lock_dir = self._lock_dir or (
            binding.project_root / ".agentkit" / "vectordb" / "locks"
        )
        try:
            with single_writer_lock(
                lock_dir=lock_dir,
                project_id=binding.project_id,
                producer_tool=producer_tool,
                timeout_seconds=self._lock_timeout,
            ):
                return self._sync_locked(
                    binding=binding,
                    producer_tool=producer_tool,
                    full_reindex=full_reindex,
                    corpus_revision=corpus_revision,
                    records_factory=records_factory,
                    owned_values=owned_values,
                    source_file_filter=source_file_filter,
                )
        except SingleWriterError as exc:
            raise IngestError(str(exc)) from exc

    def _sync_locked(  # noqa: C901
        self,
        *,
        binding: ProjectBinding,
        producer_tool: str,
        full_reindex: bool,
        corpus_revision: str,
        records_factory: object,
        owned_values: tuple[str, ...],
        source_file_filter: str | None,
    ) -> IngestReport:
        generation_id = uuid.uuid4().hex
        assert callable(records_factory)
        records: list[ChunkRecord] = records_factory(generation_id, corpus_revision)

        # --- R12: hash-based change detection against current remote state ---
        existing = list(
            self._store.fetch(
                collection=STORY_COLLECTION,
                project_id=binding.project_id,
                source_types=list(owned_values),
            )
        )
        if source_file_filter is not None:
            existing = [
                row for row in existing if str(row.get("source_file") or "") == source_file_filter
            ]
        remote_by_uuid = {
            str(row.get("chunk_uuid") or row.get("_uuid") or ""): row for row in existing
        }
        to_write: list[ChunkRecord] = []
        skipped = 0
        if full_reindex:
            to_write = list(records)
        else:
            for rec in records:
                remote = remote_by_uuid.get(rec.chunk_uuid)
                if (
                    remote is not None
                    and str(remote.get("content_hash") or "") == rec.content_hash
                    and str(remote.get("project_id") or "") == rec.project_id
                    and str(remote.get("source_type") or "") == rec.source_type.value
                ):
                    skipped += 1
                else:
                    to_write.append(rec)

        # (1) Write new/changed generation fully
        objects = [r.to_properties() for r in to_write]
        uuids = [r.chunk_uuid for r in to_write]
        written = 0
        if objects:
            raw_written = self._store.upsert(
                collection=STORY_COLLECTION,
                objects=objects,
                uuids=uuids,
            )
            # Strict non-bool int only — no int() coercion of bool/float/str (R07).
            if type(raw_written) is not int:
                raise IngestError(
                    f"upsert counter must be a non-bool int, got "
                    f"{type(raw_written).__name__}={raw_written!r}; "
                    "fail-closed (R07)."
                )
            written = raw_written
            if written != len(objects):
                raise IngestError(
                    f"partial write: upsert returned {written}, expected "
                    f"{len(objects)}; aborting without delete/receipt (R04)."
                )

        # (2) Validate desired generation: full tuple equality per UUID (R04).
        # Skipped (unchanged) records keep their prior generation_id; written
        # records must carry the new generation_id.
        desired_by_id = {r.chunk_uuid: r for r in records}
        written_ids = {r.chunk_uuid for r in to_write}
        after = list(
            self._store.fetch(
                collection=STORY_COLLECTION,
                project_id=binding.project_id,
                source_types=list(owned_values),
            )
        )
        if source_file_filter is not None:
            after = [
                row
                for row in after
                if str(row.get("source_file") or "") == source_file_filter
            ]
        present: dict[str, Mapping[str, object]] = {}
        for row in after:
            uid = str(row.get("chunk_uuid") or row.get("_uuid") or "")
            if uid in desired_by_id:
                present[uid] = row
        missing = set(desired_by_id) - set(present)
        if missing:
            raise IngestError(
                f"desired generation incomplete after write: missing "
                f"{len(missing)} chunk(s); aborting without delete/receipt (R04)."
            )
        for uid, expected in desired_by_id.items():
            row = present[uid]
            exp_gen = generation_id if uid in written_ids else str(
                remote_by_uuid.get(uid, {}).get("generation_id") or generation_id
            )
            # For skipped: accept existing remote generation_id (unchanged).
            if uid in written_ids:
                exp_gen = generation_id
            else:
                rem = remote_by_uuid.get(uid)
                exp_gen = str(rem.get("generation_id") or "") if rem else generation_id
            checks = {
                "project_id": (str(row.get("project_id") or ""), expected.project_id),
                "source_type": (str(row.get("source_type") or ""), expected.source_type.value),
                "source_file": (str(row.get("source_file") or ""), expected.source_file),
                "content_hash": (str(row.get("content_hash") or ""), expected.content_hash),
                "generation_id": (str(row.get("generation_id") or ""), exp_gen),
            }
            for field, (actual, want) in checks.items():
                if actual != want:
                    raise IngestError(
                        f"desired chunk {uid} field {field} mismatch after write: "
                        f"got {actual!r}, expected {want!r}; "
                        "aborting without delete/receipt (R04)."
                    )
        # Exact set equality of desired UUIDs among owned scope after write.
        if set(present) != set(desired_by_id):
            raise IngestError(
                "desired set != present set after write; abort without delete (R04)."
            )

        # (3) Delete remote owned chunks not in the desired set (only after
        # full desired-set validation). Incremental path does not re-stamp
        # skipped chunks' generation_id; UUID set membership is the delete key.
        desired_ids = set(desired_by_id)
        deleted = self._delete_not_desired(
            binding=binding,
            owned_values=owned_values,
            desired_ids=desired_ids,
            source_file_filter=source_file_filter,
            generation_id=generation_id if full_reindex else None,
            full_reindex=full_reindex,
        )

        return IngestReport(
            producer_tool=producer_tool,
            project_id=binding.project_id,
            full_reindex=full_reindex,
            generation_id=generation_id,
            corpus_revision=corpus_revision,
            counters=SyncCounters(
                discovered=len(records),
                written=written,
                deleted=deleted,
                skipped=skipped,
            ),
            source_types=owned_values,
        )

    def _delete_not_desired(
        self,
        *,
        binding: ProjectBinding,
        owned_values: tuple[str, ...],
        desired_ids: set[str],
        source_file_filter: str | None,
        generation_id: str | None,
        full_reindex: bool,
    ) -> int:
        existing = list(
            self._store.fetch(
                collection=STORY_COLLECTION,
                project_id=binding.project_id,
                source_types=list(owned_values),
            )
        )
        stale_uuids: list[str] = []
        for row in existing:
            uid = str(row.get("chunk_uuid") or row.get("_uuid") or "")
            if not uid:
                continue
            sf = str(row.get("source_file") or "")
            if source_file_filter is not None and sf != source_file_filter:
                continue
            if full_reindex and generation_id is not None:
                if str(row.get("generation_id") or "") != generation_id:
                    stale_uuids.append(uid)
            elif uid not in desired_ids:
                stale_uuids.append(uid)
        if not stale_uuids:
            return 0
        expected = len(stale_uuids)
        delete_ids = getattr(self._store, "delete_by_ids", None)
        if callable(delete_ids):
            result = delete_ids(
                collection=STORY_COLLECTION,
                uuids=stale_uuids,
                project_id=binding.project_id,
                source_types=list(owned_values),
            )
            deleted = self._assert_delete_counters(result, expected=expected)
            self._assert_stale_gone(
                binding=binding,
                owned_values=owned_values,
                stale_uuids=stale_uuids,
                desired_ids=desired_ids,
                source_file_filter=source_file_filter,
            )
            return deleted
        # Fallback: generation filter for full_reindex only.
        if full_reindex and generation_id is not None:
            deleted = self._delete_checked(
                collection=STORY_COLLECTION,
                project_id=binding.project_id,
                source_types=list(owned_values),
                source_file=source_file_filter,
                generation_id_not=generation_id,
            )
            if type(deleted) is not int:
                raise IngestError(
                    f"delete counter invalid type: {type(deleted).__name__}; "
                    "fail-closed (R07)."
                )
            if deleted != expected:
                raise IngestError(
                    f"delete counter invalid: {deleted} != expected {expected}; "
                    "fail-closed (R07)."
                )
            self._assert_stale_gone(
                binding=binding,
                owned_values=owned_values,
                stale_uuids=stale_uuids,
                desired_ids=desired_ids,
                source_file_filter=source_file_filter,
            )
            return deleted
        raise IngestError(
            "store cannot delete individual stale UUIDs (need delete_by_ids); "
            "fail-closed (R12)."
        )

    def _assert_stale_gone(
        self,
        *,
        binding: ProjectBinding,
        owned_values: tuple[str, ...],
        stale_uuids: list[str],
        desired_ids: set[str],
        source_file_filter: str | None,
    ) -> None:
        """Re-read and prove stale UUIDs vanished and desired set remains (R07)."""
        remaining = list(
            self._store.fetch(
                collection=STORY_COLLECTION,
                project_id=binding.project_id,
                source_types=list(owned_values),
            )
        )
        if source_file_filter is not None:
            remaining = [
                r
                for r in remaining
                if str(r.get("source_file") or "") == source_file_filter
            ]
        present_ids = {
            str(r.get("chunk_uuid") or r.get("_uuid") or "")
            for r in remaining
            if str(r.get("chunk_uuid") or r.get("_uuid") or "")
        }
        stale_set = set(stale_uuids)
        still = present_ids & stale_set
        if still:
            raise IngestError(
                f"partial delete: {len(still)} stale UUID(s) remain after delete; "
                "abort without receipt (R04/R07)."
            )
        if present_ids != desired_ids:
            raise IngestError(
                f"post-delete set mismatch: present={len(present_ids)} "
                f"desired={len(desired_ids)}; abort without receipt (R04/R07)."
            )

    def _assert_delete_counters(self, result: object, *, expected: int) -> int:
        """Require full non-bool int shape: matches==successful==expected, failed==0.

        No bare-int legacy path, no Mapping defaults, no bool-as-int (R07).
        """
        if type(result) is int or isinstance(result, bool):
            raise IngestError(
                "delete counters must be a full {matches, successful, failed} "
                "shape; bare int/bool rejected (fail-closed, R07)."
            )
        if isinstance(result, Mapping):
            missing = [k for k in ("matches", "successful", "failed") if k not in result]
            if missing:
                raise IngestError(
                    f"delete counters missing required field(s) {missing}; "
                    "fail-closed (R07)."
                )
            matches = result["matches"]
            successful = result["successful"]
            failed = result["failed"]
        else:
            for key in ("matches", "successful", "failed"):
                if not hasattr(result, key):
                    raise IngestError(
                        f"delete counters missing required field {key!r}; "
                        "fail-closed (R07)."
                    )
            matches = result.matches  # type: ignore[attr-defined]
            successful = result.successful  # type: ignore[attr-defined]
            failed = result.failed  # type: ignore[attr-defined]
        if type(matches) is not int or type(successful) is not int or type(failed) is not int:
            raise IngestError(
                f"delete counters must be non-bool ints "
                f"(matches={matches!r}, successful={successful!r}, failed={failed!r}); "
                "fail-closed (R07)."
            )
        if failed != 0 or matches != successful or successful != expected:
            raise IngestError(
                f"partial delete: matches={matches}, successful={successful}, "
                f"failed={failed}, expected={expected}; abort (R04/R07)."
            )
        return successful

    def _delete_checked(
        self,
        *,
        collection: str,
        project_id: str,
        source_types: Sequence[str] | None = None,
        source_file: str | None = None,
        generation_id_not: str | None = None,
    ) -> int:
        """Filter-delete via the canonical integer port only (R07).

        No structured-shape repair, no bare-int reinterpretation of bools,
        no Missing-``failed``→0. The store must return a non-bool int.
        """
        result = self._store.delete_by_filter(
            collection=collection,
            project_id=project_id,
            source_types=source_types,
            source_file=source_file,
            generation_id_not=generation_id_not,
        )
        if type(result) is not int:
            raise IngestError(
                f"delete_by_filter counter must be a non-bool int, got "
                f"{type(result).__name__}={result!r}; fail-closed (R07)."
            )
        return result

    def list_sources(self, binding: ProjectBinding) -> list[dict[str, object]]:
        """Return source overview against the completion stand (AC 8 / R16).

        Freshness is bound to corpus_revision + desired-set identity, not
        generation_id uniformity (FK-13 §13.9.9).
        """
        from agentkit.backend.vectordb.completion_store import (
            desired_set_digest_from_rows,
            evaluate_freshness,
            load_completion,
        )
        from agentkit.backend.vectordb.ingest.source_routing import producer_for

        rows = self._store.fetch(
            collection=STORY_COLLECTION,
            project_id=binding.project_id,
        )
        by_type: dict[str, dict[str, object]] = {}
        rows_by_type: dict[str, list[Mapping[str, object]]] = {}
        revs_by_type: dict[str, set[str]] = {}
        for row in rows:
            st = str(row.get("source_type") or "")
            if st not in {s.value for s in SourceType}:
                continue
            producer = str(row.get("producer_tool") or "")
            bucket = by_type.setdefault(
                st,
                {
                    "project_id": binding.project_id,
                    "source_type": st,
                    "producer": producer,
                    "source_count": 0,
                    "chunk_count": 0,
                    "sources": set(),
                    "last_corpus_revision": None,
                    "last_generation_id": None,
                },
            )
            sources: set[str] = bucket["sources"]  # type: ignore[assignment]
            sf = str(row.get("source_file") or "")
            if sf:
                sources.add(sf)
            prev = bucket["chunk_count"]
            prev_n = prev if type(prev) is int else 0
            bucket["chunk_count"] = prev_n + 1
            rev = str(row.get("corpus_revision") or "")
            if rev:
                revs_by_type.setdefault(st, set()).add(rev)
            rows_by_type.setdefault(st, []).append(row)
            if producer:
                bucket["producer"] = producer
        result: list[dict[str, object]] = []
        for st in sorted(by_type):
            bucket = by_type[st]
            sources_set: set[str] = bucket.pop("sources")  # type: ignore[assignment]
            bucket["source_count"] = len(sources_set)
            count_raw = bucket["chunk_count"]
            count_n = count_raw if type(count_raw) is int else 0
            try:
                producer_name = producer_for(SourceType(st))
            except Exception:  # noqa: BLE001
                producer_name = str(bucket.get("producer") or "")
            stand = load_completion(
                binding.project_root, binding.project_id, producer_name
            )
            observed_revs = revs_by_type.get(st, set())
            observed_digest = desired_set_digest_from_rows(rows_by_type.get(st, []))
            if stand is not None:
                bucket["last_corpus_revision"] = stand.corpus_revision
                bucket["last_generation_id"] = stand.generation_id
                bucket["completion_digest"] = stand.digest
                bucket["desired_set_digest"] = stand.desired_set_digest
            else:
                bucket["last_corpus_revision"] = ""
                bucket["last_generation_id"] = ""
            bucket["freshness_status"] = evaluate_freshness(
                stand=stand,
                observed_desired_digest=observed_digest,
                observed_revisions=observed_revs,
                chunk_count=count_n,
            )
            result.append(bucket)
        return result


def _story_corpus_revision(binding: ProjectBinding) -> str:
    """Digest of story/research markdown under the bound stories_dir (R16)."""
    from agentkit.backend.concept_catalog.corpus.hashing import (
        corpus_revision,
        sha256_bytes,
    )
    from agentkit.backend.concept_catalog.corpus.parser import PARSER_VERSION
    from agentkit.backend.vectordb.ingest.source_routing import classify_markdown_path

    hashes: list[str] = []
    root = binding.stories_dir
    if not root.is_dir():
        return corpus_revision([], parser_version=PARSER_VERSION)
    for path in sorted(root.rglob("*.md")):
        if not path.is_file():
            continue
        try:
            rel = binding.relative_posix(path)
        except Exception:  # noqa: BLE001
            continue
        if classify_markdown_path(rel) is None:
            continue
        try:
            hashes.append(sha256_bytes(path.read_bytes()))
        except OSError:
            continue
    return corpus_revision(hashes, parser_version=PARSER_VERSION)


def _with_generation(
    record: ChunkRecord, generation_id: str, corpus_revision: str
) -> ChunkRecord:
    return ChunkRecord(
        chunk_uuid=record.chunk_uuid,
        content=record.content,
        content_hash=record.content_hash,
        project_id=record.project_id,
        source_type=record.source_type,
        source_file=record.source_file,
        producer_tool=record.producer_tool,
        section_heading=record.section_heading,
        title=record.title,
        story_id=record.story_id,
        status=record.status,
        story_type=record.story_type,
        module=record.module,
        epic=record.epic,
        concept_id=record.concept_id,
        is_appendix=record.is_appendix,
        parent_concept_id=record.parent_concept_id,
        defers_to=record.defers_to,
        authority_over=record.authority_over,
        section_number=record.section_number,
        normative_rules=record.normative_rules,
        concept_status=record.concept_status,
        generation_id=generation_id,
        corpus_revision=corpus_revision or record.corpus_revision,
        extra=dict(record.extra),
    )


__all__ = [
    "DeleteResult",
    "IngestEngine",
    "IngestError",
    "IngestReport",
    "IngestStorePort",
]
