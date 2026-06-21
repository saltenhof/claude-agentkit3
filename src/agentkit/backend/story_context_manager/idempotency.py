"""Idempotency key store for story mutations.

Implements FK-91 §91.1a Rule 5: every mutating endpoint requires an
``op_id``. Repeated requests with the same ``op_id`` and same
body-hash return the cached result without re-executing the mutation.
A conflicting body-hash raises ``IdempotencyMismatchError`` (409).

The store delegates persistence to ``IdempotencyKeyRepository``
(Protocol). Two implementations exist:
  - ``InMemoryIdempotencyKeyRepository``: in-process, test-friendly.
  - ``StateBackendIdempotencyKeyRepository``: SQLite/Postgres-backed
    (in ``state_backend/store/idempotency_key_repository.py``).
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from typing import Protocol

from agentkit.backend.story_context_manager.errors import IdempotencyMismatchError

# ---------------------------------------------------------------------------
# Body-hash computation
# ---------------------------------------------------------------------------


def compute_body_hash(body: dict[str, object]) -> str:
    """Compute a deterministic SHA-256 hash of a canonical JSON body.

    Args:
        body: The request body as a dict. The ``op_id`` key is excluded
              so that the hash is a pure function of the mutation data.

    Returns:
        A lowercase hex SHA-256 digest string.
    """
    canonical_body = {k: v for k, v in body.items() if k != "op_id"}
    serialized = json.dumps(canonical_body, sort_keys=True, default=str)
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# Repository Protocol
# ---------------------------------------------------------------------------


class IdempotencyKeyRepository(Protocol):
    """Storage port for idempotency keys (FK-91 §91.1a Rule 5)."""

    def get(self, op_id: str) -> IdempotencyRecord | None:
        """Load an existing idempotency record by op_id."""
        ...

    def save(self, record: IdempotencyRecord) -> None:
        """Persist a new idempotency record."""
        ...


class IdempotencyRecord:
    """One idempotency record.

    Attributes:
        op_id: Caller-supplied idempotency key.
        body_hash: SHA-256 of the canonical request body (excl. op_id).
        result_payload: The JSON-serializable result that was returned.
        created_at: When this record was first stored.
        correlation_id: Propagated from the originating request header.
    """

    __slots__ = ("op_id", "body_hash", "result_payload", "created_at", "correlation_id")

    def __init__(
        self,
        op_id: str,
        body_hash: str,
        result_payload: dict[str, object],
        created_at: datetime,
        correlation_id: str,
    ) -> None:
        self.op_id = op_id
        self.body_hash = body_hash
        self.result_payload = result_payload
        self.created_at = created_at
        self.correlation_id = correlation_id


# ---------------------------------------------------------------------------
# In-memory implementation (for unit tests)
# ---------------------------------------------------------------------------


class InMemoryIdempotencyKeyRepository:
    """In-memory idempotency store — NOT mock; first-class test impl."""

    def __init__(self) -> None:
        self._records: dict[str, IdempotencyRecord] = {}

    def get(self, op_id: str) -> IdempotencyRecord | None:
        """Load by op_id."""
        return self._records.get(op_id)

    def save(self, record: IdempotencyRecord) -> None:
        """Persist record."""
        self._records[record.op_id] = record

    def clear(self) -> None:
        """Remove all records (test helper)."""
        self._records.clear()


# ---------------------------------------------------------------------------
# IdempotencyKeyStore (service wrapper)
# ---------------------------------------------------------------------------


class IdempotencyKeyStore:
    """Service wrapper around IdempotencyKeyRepository.

    Usage pattern in a mutating handler:

        cached, payload = store.check(op_id, body)
        if cached:
            return payload   # idempotent repeat — return cached result

        result = do_the_mutation(...)
        store.record(op_id, body, result, correlation_id)
        return result
    """

    def __init__(self, repository: IdempotencyKeyRepository) -> None:
        self._repo = repository

    def check(
        self,
        op_id: str,
        body: dict[str, object],
    ) -> tuple[bool, dict[str, object] | None]:
        """Check whether op_id is already recorded.

        Args:
            op_id: The idempotency key from the request.
            body: The full request body (op_id key excluded from hash).

        Returns:
            ``(True, cached_result)`` if the op is already recorded with
            the same body-hash. ``(False, None)`` if not yet recorded.

        Raises:
            ``IdempotencyMismatchError`` (409) if op_id was already used
            with a different body-hash.
        """
        existing = self._repo.get(op_id)
        if existing is None:
            return False, None

        incoming_hash = compute_body_hash(body)
        if existing.body_hash != incoming_hash:
            raise IdempotencyMismatchError(
                f"op_id {op_id!r} was previously used with a different "
                "request body; use a new op_id for a different mutation",
                detail={
                    "op_id": op_id,
                    "conflict": "body_hash_mismatch",
                },
            )
        return True, existing.result_payload

    def record(
        self,
        op_id: str,
        body: dict[str, object],
        result_payload: dict[str, object],
        *,
        correlation_id: str = "",
    ) -> None:
        """Persist a completed mutation so future repeats are idempotent.

        Args:
            op_id: The idempotency key.
            body: The original request body (used to compute hash).
            result_payload: The JSON-serializable result to cache.
            correlation_id: Correlation ID from the originating request.
        """
        self._repo.save(
            IdempotencyRecord(
                op_id=op_id,
                body_hash=compute_body_hash(body),
                result_payload=result_payload,
                created_at=datetime.now(UTC),
                correlation_id=correlation_id,
            )
        )
