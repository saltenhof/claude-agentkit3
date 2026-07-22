"""``concept_sync`` with generations-consistent Bounded-Window replace.

Order (FK-13 §13.9.9 / AG3-174 AC 6):

1. Write new desired generation completely and validate the desired set
2. Only then delete old/foreign chunks of the same source
3. Only after successful delete publish a digest-bound receipt with
   ``corpus_revision``
4. Crash before (3) leaves the last completion marker unchanged; retry
   cleans full/partial leftovers deterministically
5. Parallel syncs of the same ``(project_id, source)`` are serialised via
   the ingest engine single-writer lock

Explicitly NOT guaranteed: an immediate single-generation state after a
process crash. Readers may see both generations in the normed window.
No CAS, no generation pointer.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from agentkit.backend.vectordb.concept_corpus.build import build_corpus_artifacts
from agentkit.backend.vectordb.concept_corpus.receipts import (
    SyncReceipt,
    build_receipt,
)
from agentkit.backend.vectordb.concept_corpus.validate import ValidationResult, validate_corpus
from agentkit.backend.vectordb.ingest.builders import build_concept_chunks

if TYPE_CHECKING:
    from agentkit.backend.vectordb.ingest.engine import IngestEngine, IngestReport
    from agentkit.backend.vectordb.ingest.models import ChunkRecord
    from agentkit.backend.vectordb.project_binding import ProjectBinding


class ConceptSyncBlockedError(Exception):
    """Raised when validate fails and sync must not start (fail-closed)."""

    def __init__(self, validation: ValidationResult) -> None:
        self.validation = validation
        super().__init__(
            f"concept_sync blocked by validation "
            f"(exit_code={validation.exit_code}, errors={len(validation.errors)})"
        )


@dataclass(frozen=True)
class ConceptSyncResult:
    """Full concept sync outcome including receipt."""

    validation: ValidationResult
    ingest: IngestReport
    receipt: SyncReceipt
    receipt_path: Path


def concept_sync_bounded_window(
    binding: ProjectBinding,
    engine: IngestEngine,
    *,
    full_reindex: bool = False,
    receipt_dir: Path | str | None = None,
    build_artifacts: bool = True,
    records: list[ChunkRecord] | None = None,
    source_file_filter: str | None = None,
    publish_completion: bool = True,
    publish_receipt: bool = True,
) -> ConceptSyncResult:
    """Run validate → (optional build) → bounded-window concept ingest.

    Receipt is published only after engine completes write-validate-delete
    without raising (R04).
    """
    validation = validate_corpus(binding.concepts_dir)
    if not validation.ok_for_sync:
        raise ConceptSyncBlockedError(validation)

    if build_artifacts and source_file_filter is None:
        build_corpus_artifacts(
            binding.concepts_dir,
            validation=validation,
            persist=True,
        )

    if records is None:
        chunk_records = build_concept_chunks(
            binding,
            corpus_revision=validation.corpus_revision,
            documents=validation.documents,
        )
    else:
        chunk_records = list(records)

    # Engine enforces write==expected, re-read validation, then delete, else raises.
    report = engine.concept_sync(
        binding,
        full_reindex=full_reindex,
        corpus_revision=validation.corpus_revision,
        records=chunk_records,
        source_file_filter=source_file_filter,
        publish_completion=publish_completion,
    )

    receipt = build_receipt(
        project_id=binding.project_id,
        producer_tool="concept_sync",
        corpus_revision=validation.corpus_revision,
        generation_id=report.generation_id,
        written=report.counters.written,
        deleted=report.counters.deleted,
    )
    out_dir = Path(receipt_dir) if receipt_dir is not None else (
        binding.project_root / ".agentkit" / "vectordb"
    )
    receipt_path = out_dir / f"concept_sync_receipt_{binding.project_id}.json"
    if publish_receipt:
        from agentkit.backend.vectordb.concept_corpus.receipts import (
            publish_receipt as write_sync_receipt,
        )

        write_sync_receipt(receipt_path, receipt)
    # R16: completion stand is also published by engine.concept_sync; re-publish
    # here with the same desired-set digest for the bounded-window receipt path
    # when staging is not requested by the outer CP10a first-index call.
    if publish_completion:
        from agentkit.backend.vectordb.completion_store import (
            desired_set_digest_from_records,
        )
        from agentkit.backend.vectordb.completion_store import (
            publish_completion as _publish,
        )

        _publish(
            binding.project_root,
            project_id=binding.project_id,
            producer_tool="concept_sync",
            corpus_revision=validation.corpus_revision,
            generation_id=report.generation_id,
            written=report.counters.written,
            deleted=report.counters.deleted,
            desired_set_digest=desired_set_digest_from_records(chunk_records),
        )

    return ConceptSyncResult(
        validation=validation,
        ingest=report,
        receipt=receipt,
        receipt_path=receipt_path,
    )


__all__ = [
    "ConceptSyncBlockedError",
    "ConceptSyncResult",
    "concept_sync_bounded_window",
]
