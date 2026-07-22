"""Typed first-index / sync receipts for CP10a (AG3-176 AC3).

Extends the engine completion markers with the counters and status fields
required by the installer contract. Receipts are published only after a
successful engine run; transport/parse/partial failures produce **no**
success receipt and **no** freshness advance.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import TYPE_CHECKING, Final

from agentkit.backend.concept_catalog.corpus.hashing import sha256_text

if TYPE_CHECKING:
    from pathlib import Path

    from agentkit.backend.vectordb.ingest.engine import IngestReport


class IndexingStatus(StrEnum):
    """Receipt status (success only is published)."""

    SUCCESS = "success"
    EMPTY_CORPUS = "empty_corpus"


@dataclass(frozen=True)
class IndexingReceipt:
    """Typed receipt for story_sync / concept_sync first index (AC3).

    Attributes:
        project_id: Bound project discriminator.
        producer_tool: ``story_sync`` or ``concept_sync``.
        owned_source_types: Source types owned by the producer.
        discovered: Documents/chunks discovered in the desired set.
        unchanged: Unchanged (skipped) count on incremental; 0 on full reindex.
        upserted: Written/upserted count.
        deleted: Deleted count.
        failed: Failed count (must be 0 for a published success receipt).
        empty_corpus: True when discovered==0 (success with zero counts).
        start_revision: Corpus revision before the run (may be empty).
        end_revision: Corpus revision after successful completion.
        status: ``success`` or ``empty_corpus``.
        generation_id: Write-batch generation id from the engine.
        published_at: ISO-8601 UTC timestamp.
        digest: SHA-256 over the canonical payload without digest.
    """

    project_id: str
    producer_tool: str
    owned_source_types: tuple[str, ...]
    discovered: int
    unchanged: int
    upserted: int
    deleted: int
    failed: int
    empty_corpus: bool
    start_revision: str
    end_revision: str
    status: IndexingStatus
    generation_id: str
    published_at: str
    digest: str

    def as_dict(self) -> dict[str, object]:
        return {
            "project_id": self.project_id,
            "producer_tool": self.producer_tool,
            "owned_source_types": list(self.owned_source_types),
            "discovered": self.discovered,
            "unchanged": self.unchanged,
            "upserted": self.upserted,
            "deleted": self.deleted,
            "failed": self.failed,
            "empty_corpus": self.empty_corpus,
            "start_revision": self.start_revision,
            "end_revision": self.end_revision,
            "status": self.status.value,
            "generation_id": self.generation_id,
            "published_at": self.published_at,
            "digest": self.digest,
        }


RECEIPT_DIR_REL: Final = (".agentkit", "vectordb", "receipts")


def build_indexing_receipt(
    report: IngestReport,
    *,
    start_revision: str = "",
) -> IndexingReceipt:
    """Build a typed receipt from an engine :class:`IngestReport` (success only)."""
    counters = report.counters
    empty = counters.discovered == 0
    status = IndexingStatus.EMPTY_CORPUS if empty else IndexingStatus.SUCCESS
    published_at = datetime.now(UTC).isoformat().replace("+00:00", "Z")
    payload = {
        "project_id": report.project_id,
        "producer_tool": report.producer_tool,
        "owned_source_types": list(report.source_types),
        "discovered": counters.discovered,
        "unchanged": counters.skipped,
        "upserted": counters.written,
        "deleted": counters.deleted,
        "failed": 0,
        "empty_corpus": empty,
        "start_revision": start_revision,
        "end_revision": report.corpus_revision,
        "status": status.value,
        "generation_id": report.generation_id,
        "published_at": published_at,
    }
    digest = sha256_text(json.dumps(payload, sort_keys=True, separators=(",", ":")))
    return IndexingReceipt(
        project_id=report.project_id,
        producer_tool=report.producer_tool,
        owned_source_types=tuple(report.source_types),
        discovered=counters.discovered,
        unchanged=counters.skipped,
        upserted=counters.written,
        deleted=counters.deleted,
        failed=0,
        empty_corpus=empty,
        start_revision=start_revision,
        end_revision=report.corpus_revision,
        status=status,
        generation_id=report.generation_id,
        published_at=published_at,
        digest=digest,
    )


def publish_indexing_receipt(path: Path, receipt: IndexingReceipt) -> None:
    """Atomically write a success receipt JSON."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(
        json.dumps(receipt.as_dict(), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    tmp.replace(path)


def receipt_path(project_root: Path, project_id: str, producer_tool: str) -> Path:
    """Canonical receipt path under the project."""
    return (
        project_root.joinpath(*RECEIPT_DIR_REL)
        / f"{producer_tool}_receipt_{project_id}.json"
    )


def load_indexing_receipt(path: Path) -> IndexingReceipt | None:
    """Load a receipt when present; ``None`` when missing."""
    if not path.is_file():
        return None
    data = json.loads(path.read_text(encoding="utf-8"))
    return IndexingReceipt(
        project_id=str(data["project_id"]),
        producer_tool=str(data["producer_tool"]),
        owned_source_types=tuple(str(x) for x in data["owned_source_types"]),
        discovered=int(data["discovered"]),
        unchanged=int(data["unchanged"]),
        upserted=int(data["upserted"]),
        deleted=int(data["deleted"]),
        failed=int(data["failed"]),
        empty_corpus=bool(data["empty_corpus"]),
        start_revision=str(data["start_revision"]),
        end_revision=str(data["end_revision"]),
        status=IndexingStatus(str(data["status"])),
        generation_id=str(data["generation_id"]),
        published_at=str(data["published_at"]),
        digest=str(data["digest"]),
    )


__all__ = [
    "IndexingReceipt",
    "IndexingStatus",
    "RECEIPT_DIR_REL",
    "build_indexing_receipt",
    "load_indexing_receipt",
    "publish_indexing_receipt",
    "receipt_path",
]
