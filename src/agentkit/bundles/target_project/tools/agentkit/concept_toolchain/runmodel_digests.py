"""Canonical digests and scope identities for FK-78 run artifacts."""

from __future__ import annotations

import datetime
import hashlib
import json
from typing import TYPE_CHECKING

from .runmodel_constants import RunModelConstants as Vocab

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence
    from pathlib import Path

_SCOPE_NORMALIZE_RE = Vocab.SCOPE_NORMALIZE_RE


def canonical_request_digest(payload: Mapping[str, object]) -> str:
    """Compute the semantic request-pack digest over the canonical pack."""
    reduced = {key: value for key, value in payload.items() if key != "request_digest"}
    canonical = json.dumps(reduced, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def canonical_projection_entry_digest(raw_entry: Mapping[str, object], self_target: str) -> str:
    """Compute the canonical entry digest for manifest self-projection.

    Per FK-78 section 78.12 the digest covers the canonically serialized
    entry without derived status fields (``assertion_status``, each
    projection's ``equivalence_status``) and without the self-referencing
    projection's own ``target_digest`` field.
    """
    reduced: dict[str, object] = {key: value for key, value in raw_entry.items() if key != "assertion_status"}
    raw_projections = reduced.get("required_projections")
    if isinstance(raw_projections, list):
        slim_projections: list[object] = []
        for item in raw_projections:
            if isinstance(item, dict):
                slim = {key: value for key, value in item.items() if key != "equivalence_status"}
                if slim.get("target") == self_target:
                    slim.pop("target_digest", None)
                slim_projections.append(slim)
            else:
                slim_projections.append(item)
        reduced["required_projections"] = slim_projections
    canonical = json.dumps(reduced, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def normalize_scope_id(scope_id: str) -> str:
    """Normalize a scope id for lock naming: lowercase, ``[._-]+`` to ``-``."""
    return _SCOPE_NORMALIZE_RE.sub("-", scope_id.lower())


def scope_hash(scope_id: str) -> str:
    """Return the full scope hash used for lock naming and remote refs."""
    return hashlib.sha256(scope_id.encode("utf-8")).hexdigest()


def scope_lock_filename(scope_id: str) -> str:
    """Return the filesystem lock filename for a scope (FK-78 section 78.11)."""
    return f"{normalize_scope_id(scope_id)}.{scope_hash(scope_id)[:8]}.lock.json"


def scope_lock_ref(scope_id: str) -> str:
    """Return the git-remote lock ref of a scope (FK-78 section 78.11)."""
    return f"refs/concept-locks/{scope_hash(scope_id)}"


def canonical_lock_blob_digest(
    scope_id: str, locked_by_run: str, fencing_token: int, backend: str, ttl_seconds: int, acquired_at: str
) -> str:
    """Digest the canonical, identity-bearing part of a scope-lock blob.

    Covers the fields that bind ownership and validity: scope, owning
    run, fencing token, backend, TTL and acquisition time. Binding both
    ``ttl_seconds`` and ``acquired_at`` makes the attested lock's
    lifetime — not just the age of the attestation — verifiable.
    """
    payload = {
        "scope_id": scope_id,
        "locked_by_run": locked_by_run,
        "fencing_token": fencing_token,
        "backend": backend,
        "ttl_seconds": ttl_seconds,
        "acquired_at": acquired_at,
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def decode_tsv_field(value: str) -> str:
    """Decode the TSV field convention of literal ``\\n`` as line breaks."""
    return value.replace("\\n", "\n")


def file_sha256(path: Path) -> str:
    """Return the SHA-256 lowercase-hex digest of a file's raw bytes."""
    return hashlib.sha256(path.read_bytes()).hexdigest()


def timestamp_expired(acquired_at: str, ttl_seconds: int) -> bool:
    """Return whether a UTC-``Z`` timestamp plus TTL lies in the past."""
    acquired = datetime.datetime.fromisoformat(acquired_at.replace("Z", "+00:00"))
    return datetime.datetime.now(datetime.UTC) > acquired + datetime.timedelta(seconds=ttl_seconds)


def canonical_tsv_subset_digest(header: str, rows: Sequence[str]) -> str:
    """Compute the canonical digest of a TSV row subset."""
    canonical = "\n".join([header, *sorted(rows)]) + "\n"
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
