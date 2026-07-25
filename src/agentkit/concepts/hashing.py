"""Deterministic hashing for the concept/story corpus (FK-13 §13.3.3 / §13.9.8).

- ``chunk_hash``: SHA-256 over the chunk payload (content + structural metadata).
- ``document_hash``: SHA-256 over a file's bytes (file-level change detection).
- ``corpus_revision``: shared revision marker, ``SHA-256(sorted(file_hashes) +
  parser_version)`` (FK-13 §13.9.8). Used as the freshness indicator (NOT mtime)
  and as the bounded-window sync receipt anchor (DR 2026-07-21 Rand 5).
"""

from __future__ import annotations

import hashlib
import json
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

#: Version of the discovery/chunking projection; bumping forces a rebuild.
PARSER_VERSION = "fk13-v1-2026-07-23"


def sha256_hex(data: bytes) -> str:
    """Return the SHA-256 hex digest of ``data``."""
    return hashlib.sha256(data).hexdigest()


def chunk_hash(payload: Mapping[str, Any]) -> str:
    """SHA-256 over a deterministic JSON projection of a chunk's payload.

    Including structural metadata (not just content) means the delta ingest
    detects changes in section/identity fields, not only body edits.
    """
    blob = json.dumps(payload, sort_keys=True, ensure_ascii=False, default=_default).encode("utf-8")
    return sha256_hex(blob)


def document_hash(text: str) -> str:
    """SHA-256 over a document's full text (file-level change detection)."""
    return sha256_hex(text.encode("utf-8"))


def file_hash(data: bytes) -> str:
    """SHA-256 over a file's raw bytes."""
    return sha256_hex(data)


def corpus_revision(file_hashes: Sequence[str], *, parser_version: str = PARSER_VERSION) -> str:
    """Deterministic corpus revision marker (FK-13 §13.9.8).

    ``SHA-256(sorted(file_hashes) + parser_version)``. Empty corpus yields a
    stable, well-defined value (still dependent on the parser version).
    """
    h = hashlib.sha256()
    h.update(parser_version.encode("utf-8"))
    h.update(b"\x00")
    for fh in sorted(file_hashes):
        h.update(fh.encode("utf-8"))
        h.update(b"\x00")
    return h.hexdigest()


def sync_receipt_digest(
    *,
    project_id: str,
    source_file: str,
    source_type: str,
    corpus_revision: str,
    state: str,
    completed_at: str,
    sequence: int,
    generation: int,
) -> str:
    """Digest-bound sync receipt anchor (DR 2026-07-21 Rand 5 / D1 / D3 / N39).

    Binds a completion marker to EVERY identity and ORDERING field: project,
    source, source type, corpus revision, state, completion timestamp, the
    store-assigned completion position AND the publishing SOURCE GENERATION.
    Binding the ordering fields is what makes a persisted receipt replay-proof --
    with only ``(project, source, revision)`` bound, position/timestamp/state could
    be edited freely and a stale receipt could be replayed to the front of the
    freshness order (N16). The generation is bound because it is what DECIDES the
    freshness order: an unbound generation could be raised on a stale record and
    make a superseded completion authoritative (N39).
    """
    payload = "|".join(
        (
            "sync-receipt-v3",
            project_id,
            source_file,
            source_type,
            corpus_revision,
            state,
            completed_at,
            str(sequence),
            str(generation),
        )
    )
    return sha256_hex(payload.encode())


def _default(obj: object) -> str:
    return str(obj)


__all__ = [
    "PARSER_VERSION",
    "chunk_hash",
    "corpus_revision",
    "document_hash",
    "file_hash",
    "sha256_hex",
    "sync_receipt_digest",
]
