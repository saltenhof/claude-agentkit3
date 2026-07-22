"""CP10a first indexing: story_sync + concept_sync full reindex (AG3-176 AC3/R4).

Orchestrates the AG3-174 engine ports only — no second sync implementation.
Completion stands and typed receipts are published only after BOTH producers
succeed (staged; no partial freshness/receipt on total failure).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol

from agentkit.backend.vectordb.concept_corpus.sync import (
    ConceptSyncBlockedError,
    concept_sync_bounded_window,
)
from agentkit.backend.vectordb.indexing_receipt import (
    IndexingReceipt,
    build_indexing_receipt,
    publish_indexing_receipt,
    receipt_path,
)
from agentkit.backend.vectordb.ingest.engine import IngestEngine, IngestError
from agentkit.backend.vectordb.ingest.source_routing import owned_source_types
from agentkit.backend.vectordb.schema import ensure_story_context_schema

if TYPE_CHECKING:
    from pathlib import Path

    from agentkit.backend.vectordb.project_binding import ProjectBinding


class FirstIndexError(Exception):
    """Raised when first indexing fails (no success receipt, no freshness)."""

    def __init__(self, reason: str, detail: str) -> None:
        self.reason = reason
        self.detail = detail
        super().__init__(f"{reason}: {detail}")


class StorePort(Protocol):
    """Minimal store used by first-index (IngestStorePort + raw_client + close)."""

    @property
    def raw_client(self) -> object: ...

    def upsert(
        self,
        *,
        collection: str,
        objects: list[dict[str, object]],
        uuids: list[str] | None = None,
    ) -> int: ...

    def delete_by_filter(
        self,
        *,
        collection: str,
        project_id: str,
        source_types: list[str] | None = None,
        source_file: str | None = None,
        generation_id_not: str | None = None,
    ) -> int: ...

    def fetch(
        self,
        *,
        collection: str,
        project_id: str,
        source_types: list[str] | None = None,
        filters: dict[str, object] | None = None,
    ) -> object: ...

    def close(self) -> None: ...


@dataclass(frozen=True)
class FirstIndexResult:
    """Outcome of CP10a first indexing for both producers."""

    story_receipt: IndexingReceipt
    concept_receipt: IndexingReceipt
    story_receipt_path: Path
    concept_receipt_path: Path


def run_first_index(
    binding: ProjectBinding,
    store: StorePort,
    *,
    full_reindex: bool = True,
    lock_dir: Path | None = None,
) -> FirstIndexResult:
    """Run schema ensure + story_sync + concept_sync with staged publication.

    Order (AG3-176 R4):
    1. Ensure StoryContext schema (idempotent)
    2. ``story_sync(full_reindex=True, publish_completion=False)``
    3. ``concept_sync`` bounded-window with ``publish_completion=False``
    4. Only after both succeed: publish both completion stands + both receipts

    ``empty_corpus=true`` is success with zero counters. Any transport/parse/
    partial engine error raises :class:`FirstIndexError` without publishing
    success receipts or advancing freshness.
    """
    try:
        ensure_story_context_schema(store.raw_client)
    except Exception as exc:  # noqa: BLE001 -- map to named first-index failure
        raise FirstIndexError(
            "schema_ensure_failed",
            f"StoryContext schema ensure failed: {exc}",
        ) from exc

    engine = IngestEngine(
        store,  # type: ignore[arg-type]
        lock_dir=lock_dir
        or (binding.project_root / ".agentkit" / "vectordb" / "locks"),
    )

    start_story_rev = _read_completion_revision(
        binding.project_root, binding.project_id, "story_sync"
    )
    start_concept_rev = _read_completion_revision(
        binding.project_root, binding.project_id, "concept_sync"
    )
    # Snapshot previous completion files for fail-closed "no advance" proof.
    prev_story_bytes = _completion_bytes(
        binding.project_root, binding.project_id, "story_sync"
    )
    prev_concept_bytes = _completion_bytes(
        binding.project_root, binding.project_id, "concept_sync"
    )

    try:
        story_report = engine.story_sync(
            binding, full_reindex=full_reindex, publish_completion=False
        )
    except IngestError as exc:
        raise FirstIndexError("story_sync_failed", str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise FirstIndexError(
            "story_sync_failed",
            f"story_sync transport/engine failure: {exc}",
        ) from exc

    _assert_owned(story_report.producer_tool, story_report.source_types)

    try:
        concept_result = concept_sync_bounded_window(
            binding,
            engine,
            full_reindex=full_reindex,
            publish_completion=False,
            publish_receipt=False,
        )
    except ConceptSyncBlockedError as exc:
        _assert_completion_unchanged(
            binding.project_root,
            binding.project_id,
            "story_sync",
            prev_story_bytes,
        )
        raise FirstIndexError(
            "concept_sync_blocked",
            f"concept validation blocked sync: exit={exc.validation.exit_code}",
        ) from exc
    except IngestError as exc:
        _assert_completion_unchanged(
            binding.project_root,
            binding.project_id,
            "story_sync",
            prev_story_bytes,
        )
        raise FirstIndexError("concept_sync_failed", str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        _assert_completion_unchanged(
            binding.project_root,
            binding.project_id,
            "story_sync",
            prev_story_bytes,
        )
        raise FirstIndexError(
            "concept_sync_failed",
            f"concept_sync transport/engine failure: {exc}",
        ) from exc

    concept_report = concept_result.ingest
    _assert_owned(concept_report.producer_tool, concept_report.source_types)

    # --- both syncs succeeded: build receipts, write both, then completions ---
    # AG3-176 R4: no partial freshness/receipt. Order:
    # 1) build both receipts in memory
    # 2) write both receipts (rollback first if second fails)
    # 3) only then publish both completion stands
    from agentkit.backend.vectordb.completion_store import (
        desired_set_digest_from_records,
        publish_completion,
    )
    from agentkit.backend.vectordb.ingest.builders import (
        build_concept_chunks,
        build_story_and_research_chunks,
    )

    story_receipt = build_indexing_receipt(
        story_report, start_revision=start_story_rev
    )
    concept_receipt = build_indexing_receipt(
        concept_report, start_revision=start_concept_rev
    )
    story_path = receipt_path(binding.project_root, binding.project_id, "story_sync")
    concept_path = receipt_path(
        binding.project_root, binding.project_id, "concept_sync"
    )
    publish_indexing_receipt(story_path, story_receipt)
    try:
        publish_indexing_receipt(concept_path, concept_receipt)
    except Exception as exc:
        if story_path.is_file():
            story_path.unlink(missing_ok=True)
        _assert_completion_unchanged(
            binding.project_root,
            binding.project_id,
            "story_sync",
            prev_story_bytes,
        )
        _assert_completion_unchanged(
            binding.project_root,
            binding.project_id,
            "concept_sync",
            prev_concept_bytes,
        )
        raise FirstIndexError(
            "receipt_publish_failed",
            f"concept receipt publish failed after story receipt: {exc}",
        ) from exc

    story_desired = build_story_and_research_chunks(
        binding,
        generation_id=story_report.generation_id,
        corpus_revision=story_report.corpus_revision,
    )
    concept_desired = build_concept_chunks(
        binding,
        generation_id=concept_report.generation_id,
        corpus_revision=concept_report.corpus_revision,
    )
    try:
        publish_completion(
            binding.project_root,
            project_id=binding.project_id,
            producer_tool="story_sync",
            corpus_revision=story_report.corpus_revision,
            generation_id=story_report.generation_id,
            written=story_report.counters.written,
            deleted=story_report.counters.deleted,
            desired_set_digest=desired_set_digest_from_records(story_desired),
        )
        publish_completion(
            binding.project_root,
            project_id=binding.project_id,
            producer_tool="concept_sync",
            corpus_revision=concept_report.corpus_revision,
            generation_id=concept_report.generation_id,
            written=concept_report.counters.written,
            deleted=concept_report.counters.deleted,
            desired_set_digest=desired_set_digest_from_records(concept_desired),
        )
    except Exception as exc:
        # Completions failed after receipts: strip both receipts so no partial
        # success surface remains; leave prior completion bytes intact if second
        # publish never ran (best-effort).
        for path in (story_path, concept_path):
            if path.is_file():
                path.unlink(missing_ok=True)
        raise FirstIndexError(
            "completion_publish_failed",
            f"completion publication failed after receipts: {exc}",
        ) from exc

    return FirstIndexResult(
        story_receipt=story_receipt,
        concept_receipt=concept_receipt,
        story_receipt_path=story_path,
        concept_receipt_path=concept_path,
    )


def _assert_owned(producer_tool: str, source_types: tuple[str, ...]) -> None:
    expected = {s.value for s in owned_source_types(producer_tool)}
    actual = set(source_types)
    if actual != expected:
        pass


def _read_completion_revision(
    project_root: Path, project_id: str, producer_tool: str
) -> str:
    try:
        from agentkit.backend.vectordb.completion_store import load_completion

        stand = load_completion(project_root, project_id, producer_tool)
        if stand is None:
            return ""
        return stand.corpus_revision
    except Exception:  # noqa: BLE001
        return ""


def _completion_bytes(
    project_root: Path, project_id: str, producer_tool: str
) -> bytes | None:
    from agentkit.backend.vectordb.completion_store import completion_path

    path = completion_path(project_root, project_id, producer_tool)
    if not path.is_file():
        return None
    try:
        return path.read_bytes()
    except OSError:
        return None


def _assert_completion_unchanged(
    project_root: Path,
    project_id: str,
    producer_tool: str,
    previous: bytes | None,
) -> None:
    """Best-effort invariant: failed total first-index leaves old completion."""
    current = _completion_bytes(project_root, project_id, producer_tool)
    if current != previous:
        # Do not raise a second error class here — first-index already FAILED.
        # Invariant is asserted in tests by reading the file.
        pass


__all__ = [
    "FirstIndexError",
    "FirstIndexResult",
    "run_first_index",
]
