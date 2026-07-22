"""Digest-bound sync receipts with corpus_revision (AG3-174 Bounded-Window)."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from agentkit.backend.concept_catalog.corpus.hashing import sha256_text

if TYPE_CHECKING:
    from pathlib import Path


@dataclass(frozen=True)
class SyncReceipt:
    """Published after successful delete of the old generation."""

    project_id: str
    producer_tool: str
    corpus_revision: str
    generation_id: str
    written: int
    deleted: int
    published_at: str
    digest: str

    def as_dict(self) -> dict[str, object]:
        return {
            "project_id": self.project_id,
            "producer_tool": self.producer_tool,
            "corpus_revision": self.corpus_revision,
            "generation_id": self.generation_id,
            "written": self.written,
            "deleted": self.deleted,
            "published_at": self.published_at,
            "digest": self.digest,
        }


def build_receipt(
    *,
    project_id: str,
    producer_tool: str,
    corpus_revision: str,
    generation_id: str,
    written: int,
    deleted: int,
) -> SyncReceipt:
    """Build a digest-bound receipt (digest over canonical payload without digest)."""
    published_at = datetime.now(UTC).isoformat().replace("+00:00", "Z")
    payload = {
        "project_id": project_id,
        "producer_tool": producer_tool,
        "corpus_revision": corpus_revision,
        "generation_id": generation_id,
        "written": written,
        "deleted": deleted,
        "published_at": published_at,
    }
    digest = sha256_text(json.dumps(payload, sort_keys=True, separators=(",", ":")))
    return SyncReceipt(
        project_id=project_id,
        producer_tool=producer_tool,
        corpus_revision=corpus_revision,
        generation_id=generation_id,
        written=written,
        deleted=deleted,
        published_at=published_at,
        digest=digest,
    )


def publish_receipt(path: Path, receipt: SyncReceipt) -> None:
    """Atomically publish the receipt JSON (completion marker)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(
        json.dumps(receipt.as_dict(), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    tmp.replace(path)


def load_receipt(path: Path) -> SyncReceipt | None:
    """Load a receipt if present; return None when missing."""
    if not path.is_file():
        return None
    data = json.loads(path.read_text(encoding="utf-8"))
    return SyncReceipt(
        project_id=str(data["project_id"]),
        producer_tool=str(data["producer_tool"]),
        corpus_revision=str(data["corpus_revision"]),
        generation_id=str(data["generation_id"]),
        written=int(data["written"]),
        deleted=int(data["deleted"]),
        published_at=str(data["published_at"]),
        digest=str(data["digest"]),
    )


__all__ = [
    "SyncReceipt",
    "build_receipt",
    "load_receipt",
    "publish_receipt",
]
