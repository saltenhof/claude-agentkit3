"""Unit tests for the idempotency subsystem.

Tests:
- compute_body_hash: canonical JSON, op_id excluded
- IdempotencyKeyStore.check: cache hit, miss, mismatch
- IdempotencyKeyStore.record: store and replay
- InMemoryIdempotencyKeyRepository: correct storage semantics
"""

from __future__ import annotations

import pytest

from agentkit.story_context_manager.errors import IdempotencyMismatchError
from agentkit.story_context_manager.idempotency import (
    IdempotencyKeyStore,
    InMemoryIdempotencyKeyRepository,
    compute_body_hash,
)

# ---------------------------------------------------------------------------
# compute_body_hash
# ---------------------------------------------------------------------------


def test_compute_body_hash_excludes_op_id() -> None:
    """Same body with different op_id must hash identically."""
    body1: dict[str, object] = {"project_key": "AK3", "title": "T1", "op_id": "op-aaa"}
    body2: dict[str, object] = {"project_key": "AK3", "title": "T1", "op_id": "op-bbb"}

    assert compute_body_hash(body1) == compute_body_hash(body2)


def test_compute_body_hash_different_values_differ() -> None:
    body1: dict[str, object] = {"project_key": "AK3", "title": "T1"}
    body2: dict[str, object] = {"project_key": "AK3", "title": "T2"}

    assert compute_body_hash(body1) != compute_body_hash(body2)


def test_compute_body_hash_is_deterministic() -> None:
    body: dict[str, object] = {"b": 2, "a": 1, "op_id": "x"}
    h1 = compute_body_hash(body)
    h2 = compute_body_hash(body)
    assert h1 == h2


def test_compute_body_hash_key_order_does_not_matter() -> None:
    """Keys are sorted canonically before hashing."""
    body_a: dict[str, object] = {"b": 2, "a": 1}
    body_b: dict[str, object] = {"a": 1, "b": 2}
    assert compute_body_hash(body_a) == compute_body_hash(body_b)


# ---------------------------------------------------------------------------
# IdempotencyKeyStore
# ---------------------------------------------------------------------------


def _make_store() -> IdempotencyKeyStore:
    return IdempotencyKeyStore(InMemoryIdempotencyKeyRepository())


def test_check_returns_false_for_new_op_id() -> None:
    store = _make_store()
    body: dict[str, object] = {"project_key": "AK3", "title": "New story"}

    cached, payload = store.check("op-new", body)

    assert cached is False
    assert payload is None


def test_check_returns_true_after_record() -> None:
    store = _make_store()
    body: dict[str, object] = {"project_key": "AK3", "title": "Story"}
    result_payload: dict[str, object] = {"story_id": "AK3-1", "status": "Backlog"}

    store.record("op-001", body, result_payload)
    cached, payload = store.check("op-001", body)

    assert cached is True
    assert payload == result_payload


def test_check_raises_on_body_hash_mismatch() -> None:
    """Same op_id but different body must raise IdempotencyMismatchError."""
    store = _make_store()
    original_body: dict[str, object] = {"project_key": "AK3", "title": "Original"}
    different_body: dict[str, object] = {"project_key": "AK3", "title": "Different"}

    store.record("op-clash", original_body, {"story_id": "AK3-1"})

    with pytest.raises(IdempotencyMismatchError):
        store.check("op-clash", different_body)


def test_check_same_body_different_op_ids_are_independent() -> None:
    """Two distinct op_ids with the same body are independent records."""
    store = _make_store()
    body: dict[str, object] = {"project_key": "AK3", "title": "Story"}

    store.record("op-a", body, {"story_id": "AK3-1"})
    store.record("op-b", body, {"story_id": "AK3-2"})

    cached_a, payload_a = store.check("op-a", body)
    cached_b, payload_b = store.check("op-b", body)

    assert cached_a is True and payload_a == {"story_id": "AK3-1"}
    assert cached_b is True and payload_b == {"story_id": "AK3-2"}


def test_record_is_idempotent_same_key_same_payload() -> None:
    """Calling record twice with same op_id + payload is safe."""
    store = _make_store()
    body: dict[str, object] = {"title": "S"}
    payload: dict[str, object] = {"story_id": "AK3-1"}

    store.record("op-dup", body, payload)
    store.record("op-dup", body, payload)  # should not raise

    cached, cached_payload = store.check("op-dup", body)
    assert cached is True
    assert cached_payload == payload


# ---------------------------------------------------------------------------
# InMemoryIdempotencyKeyRepository
# ---------------------------------------------------------------------------


def test_in_memory_repo_get_returns_none_for_missing() -> None:
    repo = InMemoryIdempotencyKeyRepository()
    assert repo.get("nonexistent") is None


def test_in_memory_repo_save_and_retrieve() -> None:
    from datetime import UTC, datetime

    from agentkit.story_context_manager.idempotency import IdempotencyRecord

    repo = InMemoryIdempotencyKeyRepository()
    now = datetime(2026, 1, 1, tzinfo=UTC)
    record = IdempotencyRecord(
        op_id="op-001",
        body_hash="hash123",
        result_payload={"story_id": "AK3-1"},
        created_at=now,
        correlation_id="corr-001",
    )

    repo.save(record)
    retrieved = repo.get("op-001")

    assert retrieved is not None
    assert retrieved.op_id == "op-001"
    assert retrieved.body_hash == "hash123"
    assert retrieved.result_payload == {"story_id": "AK3-1"}


def test_in_memory_repo_saves_most_recent_record() -> None:
    """InMemoryIdempotencyKeyRepository stores the latest save per op_id."""
    from datetime import UTC, datetime

    from agentkit.story_context_manager.idempotency import IdempotencyRecord

    repo = InMemoryIdempotencyKeyRepository()
    now = datetime(2026, 1, 1, tzinfo=UTC)
    r1 = IdempotencyRecord(op_id="op-x", body_hash="h1", result_payload={"v": 1}, created_at=now, correlation_id="c")
    r2 = IdempotencyRecord(op_id="op-x", body_hash="h2", result_payload={"v": 2}, created_at=now, correlation_id="c")

    repo.save(r1)
    repo.save(r2)

    retrieved = repo.get("op-x")
    # In-memory uses dict assignment — last write wins
    assert retrieved is not None
    assert retrieved.body_hash == "h2"
