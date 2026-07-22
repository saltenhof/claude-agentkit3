"""Digest-bound completion stand per project/producer (AG3-174 R16).

FK-13 §13.9.9 derivation: the completion/freshness marker is bound to
``corpus_revision`` and the DESIRED set identity
``(uuid, content_hash, source_file, source_type)`` — not to generation_id
uniformity. ``generation_id`` is only a write-batch tag for full-reindex
delete, never a completion criterion or generation pointer.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Final

from agentkit.backend.concept_catalog.corpus.hashing import sha256_text
from agentkit.backend.vectordb.concept_corpus.receipts import (
    SyncReceipt,
    build_receipt,
)

if TYPE_CHECKING:
    from pathlib import Path

PRODUCER_STORY: Final[str] = "story_sync"
PRODUCER_CONCEPT: Final[str] = "concept_sync"


@dataclass(frozen=True)
class CompletionStand:
    """Last successful completion for one (project, producer)."""

    project_id: str
    producer_tool: str
    corpus_revision: str
    generation_id: str
    written: int
    deleted: int
    digest: str
    published_at: str
    desired_set_digest: str = ""

    def as_dict(self) -> dict[str, object]:
        return {
            "project_id": self.project_id,
            "producer_tool": self.producer_tool,
            "corpus_revision": self.corpus_revision,
            "generation_id": self.generation_id,
            "written": self.written,
            "deleted": self.deleted,
            "digest": self.digest,
            "published_at": self.published_at,
            "desired_set_digest": self.desired_set_digest,
        }


def desired_set_digest_from_rows(
    rows: Iterable[Mapping[str, object]],
) -> str:
    """Canonical digest over the desired identity set (R16).

    Each row contributes ``(chunk_uuid, content_hash, source_file, source_type)``.
    generation_id is intentionally excluded.
    """
    tuples: list[tuple[str, str, str, str]] = []
    for row in rows:
        uid = str(row.get("chunk_uuid") or row.get("_uuid") or "")
        ch = str(row.get("content_hash") or "")
        sf = str(row.get("source_file") or "")
        st = str(row.get("source_type") or "")
        if not uid:
            continue
        tuples.append((uid, ch, sf, st))
    tuples.sort()
    payload = json.dumps(tuples, separators=(",", ":"), ensure_ascii=True)
    return sha256_text(payload)


def desired_set_digest_from_records(records: Sequence[object]) -> str:
    """Digest from ChunkRecord-like objects."""
    rows: list[dict[str, object]] = []
    for rec in records:
        to_props = getattr(rec, "to_properties", None)
        if callable(to_props):
            props = to_props()
            if isinstance(props, Mapping):
                rows.append(dict(props))
        elif isinstance(rec, Mapping):
            rows.append(dict(rec))
    return desired_set_digest_from_rows(rows)


def completion_dir(project_root: Path) -> Path:
    from pathlib import Path as _Path

    return _Path(project_root) / ".agentkit" / "vectordb" / "completions"


def completion_path(project_root: Path, project_id: str, producer_tool: str) -> Path:
    safe_producer = producer_tool.replace("/", "_")
    return completion_dir(project_root) / f"{project_id}__{safe_producer}.json"


def publish_completion(
    project_root: Path,
    *,
    project_id: str,
    producer_tool: str,
    corpus_revision: str,
    generation_id: str,
    written: int,
    deleted: int,
    desired_set_digest: str,
) -> CompletionStand:
    """Publish a digest-bound completion stand (only after successful delete)."""
    receipt = build_receipt(
        project_id=project_id,
        producer_tool=producer_tool,
        corpus_revision=corpus_revision,
        generation_id=generation_id,
        written=written,
        deleted=deleted,
    )
    # Extend on-disk payload with desired_set_digest (R16).
    path = completion_path(project_root, project_id, producer_tool)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = receipt.as_dict()
    payload["desired_set_digest"] = desired_set_digest
    # Re-digest including the desired set so tampering is visible.
    digest_body = {
        k: payload[k]
        for k in (
            "project_id",
            "producer_tool",
            "corpus_revision",
            "generation_id",
            "written",
            "deleted",
            "published_at",
            "desired_set_digest",
        )
    }
    stand_digest = sha256_text(
        json.dumps(digest_body, sort_keys=True, separators=(",", ":"))
    )
    payload["digest"] = stand_digest
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    tmp.replace(path)
    written_raw = payload["written"]
    deleted_raw = payload["deleted"]
    if type(written_raw) is not int or type(deleted_raw) is not int:
        raise TypeError(
            f"completion written/deleted must be non-bool int, "
            f"got {written_raw!r}/{deleted_raw!r}"
        )
    return CompletionStand(
        project_id=str(payload["project_id"]),
        producer_tool=str(payload["producer_tool"]),
        corpus_revision=str(payload["corpus_revision"]),
        generation_id=str(payload["generation_id"]),
        written=written_raw,
        deleted=deleted_raw,
        digest=stand_digest,
        published_at=str(payload["published_at"]),
        desired_set_digest=desired_set_digest,
    )


def load_completion(
    project_root: Path, project_id: str, producer_tool: str
) -> CompletionStand | None:
    path = completion_path(project_root, project_id, producer_tool)
    if not path.is_file():
        return None
    data = json.loads(path.read_text(encoding="utf-8"))
    return CompletionStand(
        project_id=str(data["project_id"]),
        producer_tool=str(data["producer_tool"]),
        corpus_revision=str(data["corpus_revision"]),
        generation_id=str(data["generation_id"]),
        written=int(data["written"]),
        deleted=int(data["deleted"]),
        published_at=str(data["published_at"]),
        digest=str(data["digest"]),
        desired_set_digest=str(data.get("desired_set_digest") or ""),
    )


def evaluate_freshness(
    *,
    stand: CompletionStand | None,
    observed_desired_digest: str,
    observed_revisions: set[str],
    chunk_count: int,
) -> str:
    """Return freshness_status for story_list_sources (R16 / FK-13 §13.9.9).

    Bound to the DESIRED set identity (uuid, content_hash, source_file,
    source_type) and the completion stand's corpus_revision as the last
    successful close marker — not to generation_id or per-chunk
    corpus_revision uniformity. Hash-skipped chunks may retain older
    generation_id / corpus_revision tags after an incremental sync; that
    must not force ``partial`` when the desired set matches.
    """
    del observed_revisions  # diagnostics only; not a completion criterion
    if chunk_count == 0:
        return "missing" if stand is None else "ok"
    if stand is None:
        return "missing_revision"
    if not stand.desired_set_digest:
        # Legacy stand without desired-set proof cannot claim ok.
        return "stale"
    if not stand.corpus_revision:
        return "missing_revision"
    if observed_desired_digest != stand.desired_set_digest:
        return "partial"
    return "ok"


def verify_receipt_digest(receipt: SyncReceipt) -> bool:
    """Recompute digest and compare (tamper detection)."""
    payload = {
        "project_id": receipt.project_id,
        "producer_tool": receipt.producer_tool,
        "corpus_revision": receipt.corpus_revision,
        "generation_id": receipt.generation_id,
        "written": receipt.written,
        "deleted": receipt.deleted,
        "published_at": receipt.published_at,
    }
    expected = sha256_text(json.dumps(payload, sort_keys=True, separators=(",", ":")))
    return expected == receipt.digest


__all__ = [
    "PRODUCER_CONCEPT",
    "PRODUCER_STORY",
    "CompletionStand",
    "completion_dir",
    "completion_path",
    "desired_set_digest_from_records",
    "desired_set_digest_from_rows",
    "evaluate_freshness",
    "load_completion",
    "publish_completion",
    "verify_receipt_digest",
]
