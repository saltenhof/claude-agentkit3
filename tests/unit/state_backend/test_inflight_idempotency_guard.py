"""Unit contract for the unified in-flight idempotency guard (AG3-140).

Drives the first-class in-memory guard (NOT a mock) through the full FK-91
§91.1a Regel 5 contract: fresh claim, in-flight rejection of a parallel same
op_id, replay of a terminal record, body-hash mismatch, and the ownership-scoped
release/finalize CAS. The Postgres-backed guard is proven against the real store
in ``tests/contract/state_backend/test_inflight_idempotency_guard_postgres.py``.
"""

from __future__ import annotations

from agentkit.backend.state_backend.store.inflight_idempotency_guard import (
    FreshClaim,
    IdempotencyRequest,
    InFlightOutcome,
    InMemoryInflightIdempotencyGuard,
    MismatchOutcome,
    ReplayOutcome,
    compute_body_hash,
)


def _req(op_id: str, body: dict[str, object], *, story_id: str | None = None) -> IdempotencyRequest:
    return IdempotencyRequest(
        op_id=op_id,
        operation_kind="task_create",
        body_hash=compute_body_hash(body),
        project_key="tenant-a",
        story_id=story_id,
    )


def test_compute_body_hash_excludes_op_id() -> None:
    """The op_id key is excluded so a replay of the same mutation hashes equal."""
    assert compute_body_hash({"op_id": "a", "x": 1}) == compute_body_hash(
        {"op_id": "b", "x": 1}
    )
    assert compute_body_hash({"op_id": "a", "x": 1}) != compute_body_hash(
        {"op_id": "a", "x": 2}
    )


def test_fresh_claim_then_finalize_then_replay_returns_stored_result() -> None:
    """A first claim wins; after finalize a replay returns the STORED result."""
    guard = InMemoryInflightIdempotencyGuard()
    req = _req("op-1", {"title": "T"})

    first = guard.claim(req)
    assert isinstance(first, FreshClaim)

    guard.finalize(req, first, {"status_code": 201, "body": {"task_id": "TM-1"}})

    replay = guard.claim(req)
    assert isinstance(replay, ReplayOutcome)
    assert replay.result_payload == {"status_code": 201, "body": {"task_id": "TM-1"}}


def test_parallel_same_op_id_before_finalize_is_in_flight_rejected() -> None:
    """A second claim while the first is still ``claimed`` is rejected in-flight."""
    guard = InMemoryInflightIdempotencyGuard()
    req = _req("op-2", {"title": "T"})

    first = guard.claim(req)
    assert isinstance(first, FreshClaim)

    second = guard.claim(req)
    assert isinstance(second, InFlightOutcome)
    assert second.op_id == "op-2"


def test_same_op_id_different_body_is_mismatch_after_finalize() -> None:
    """A terminal op_id reused with a DIFFERENT body is a 409-mismatch outcome."""
    guard = InMemoryInflightIdempotencyGuard()
    req = _req("op-3", {"title": "T"})
    first = guard.claim(req)
    assert isinstance(first, FreshClaim)
    guard.finalize(req, first, {"status_code": 201, "body": {}})

    conflicting = _req("op-3", {"title": "DIFFERENT"})
    outcome = guard.claim(conflicting)
    assert isinstance(outcome, MismatchOutcome)
    assert outcome.op_id == "op-3"


def test_release_after_claim_allows_a_clean_retry() -> None:
    """A released claim (mutation raised before any side effect) is re-claimable."""
    guard = InMemoryInflightIdempotencyGuard()
    req = _req("op-4", {"title": "T"})
    first = guard.claim(req)
    assert isinstance(first, FreshClaim)

    guard.release(req, first)

    retry = guard.claim(req)
    assert isinstance(retry, FreshClaim), "a released claim must be re-claimable"


def test_crash_window_no_finalize_leaves_claim_and_retry_is_in_flight() -> None:
    """Crash between mutate and finalize: the claim stays, a retry is rejected.

    Reproduces AC3 at the guard level: after a winning claim the mutation
    "committed" but ``finalize`` never ran (a crash). The row stays ``claimed``
    (never a silently-missing record), so a retry with the same op_id gets an
    in-flight rejection and NEVER re-executes -- no doubly-executable state.
    """
    guard = InMemoryInflightIdempotencyGuard()
    req = _req("op-5", {"title": "T"})
    first = guard.claim(req)
    assert isinstance(first, FreshClaim)
    # (no finalize -- simulate a crash between mutate and finalize)

    retry = guard.claim(req)
    assert isinstance(retry, InFlightOutcome)


def test_finalize_with_wrong_owner_token_does_not_apply() -> None:
    """The ownership CAS rejects a finalize that does not hold the live claim."""
    guard = InMemoryInflightIdempotencyGuard()
    req = _req("op-6", {"title": "T"})
    first = guard.claim(req)
    assert isinstance(first, FreshClaim)

    forged = FreshClaim(owner_token="not-the-owner", claimed_at_iso=first.claimed_at_iso)
    applied = guard.finalize(req, forged, {"status_code": 201, "body": {}})
    assert applied is False


def test_project_scoped_claim_carries_no_story_id() -> None:
    """A project-scoped (story-less) claim is a first-class claim (AG3-140)."""
    guard = InMemoryInflightIdempotencyGuard()
    req = _req("op-7", {"title": "T"}, story_id=None)
    assert req.story_id is None
    assert isinstance(guard.claim(req), FreshClaim)
