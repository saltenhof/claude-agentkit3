"""Real-backend contract for the unified in-flight idempotency guard (AG3-140).

Exercises the Postgres-backed ``StateBackendInflightIdempotencyGuard`` against
the genuine ``control_plane_operations`` store (the physical inflight-operation
record) -- NOT the in-memory fake -- so the atomic
``INSERT ... ON CONFLICT DO NOTHING`` claim, the body-hash replay/mismatch and
the ownership-scoped finalize/release CAS hold against the real driver. Also
proves the AG3-140 schema deltas on the real store: a project-scoped claim with
``story_id = NULL`` and the ``request_body_hash`` column.

Postgres-only by design (K5): the control-plane row methods exist only on the
Postgres backend. Binds the shared per-test isolated schema fixture.
"""

from __future__ import annotations

import pytest

from agentkit.backend.state_backend.store.inflight_idempotency_guard import (
    FreshClaim,
    IdempotencyRequest,
    InFlightOutcome,
    MismatchOutcome,
    ReplayOutcome,
    StateBackendInflightIdempotencyGuard,
    compute_body_hash,
)

pytest_plugins = ("tests.fixtures.postgres_backend",)


def _req(
    op_id: str,
    body: dict[str, object],
    *,
    story_id: str | None = "AG3-140",
) -> IdempotencyRequest:
    return IdempotencyRequest(
        op_id=op_id,
        operation_kind="task_create",
        body_hash=compute_body_hash(body),
        project_key="tenant-a",
        story_id=story_id,
    )


@pytest.mark.contract
def test_fresh_claim_wins_and_parallel_same_op_id_is_in_flight_real_store(
    postgres_backend_env: object,
) -> None:
    """The first claim wins; a second before finalize is in-flight rejected."""
    del postgres_backend_env
    guard = StateBackendInflightIdempotencyGuard()
    req = _req("op-guard-claim-1", {"title": "T"})

    first = guard.claim(req)
    assert isinstance(first, FreshClaim)

    second = guard.claim(req)
    assert isinstance(second, InFlightOutcome)


@pytest.mark.contract
def test_winner_finalizes_then_retry_replays_stored_result_real_store(
    postgres_backend_env: object,
) -> None:
    """After finalize a replay of the same op_id returns the STORED result."""
    del postgres_backend_env
    guard = StateBackendInflightIdempotencyGuard()
    req = _req("op-guard-replay-1", {"title": "T"})

    first = guard.claim(req)
    assert isinstance(first, FreshClaim)
    payload = {"status_code": 201, "body": {"task_id": "TM-2026-0001"}}
    assert guard.finalize(req, first, payload) is True

    replay = guard.claim(req)
    assert isinstance(replay, ReplayOutcome)
    assert replay.result_payload == payload


@pytest.mark.contract
def test_same_op_id_different_body_is_mismatch_real_store(
    postgres_backend_env: object,
) -> None:
    """A terminal op_id reused with a different body-hash is a mismatch."""
    del postgres_backend_env
    guard = StateBackendInflightIdempotencyGuard()
    req = _req("op-guard-mismatch-1", {"title": "T"})
    first = guard.claim(req)
    assert isinstance(first, FreshClaim)
    guard.finalize(req, first, {"status_code": 201, "body": {}})

    outcome = guard.claim(_req("op-guard-mismatch-1", {"title": "OTHER"}))
    assert isinstance(outcome, MismatchOutcome)


@pytest.mark.contract
def test_released_claim_is_reclaimable_real_store(
    postgres_backend_env: object,
) -> None:
    """A released claim (clean mutation failure) is re-claimable at the real store."""
    del postgres_backend_env
    guard = StateBackendInflightIdempotencyGuard()
    req = _req("op-guard-release-1", {"title": "T"})
    first = guard.claim(req)
    assert isinstance(first, FreshClaim)

    guard.release(req, first)

    retry = guard.claim(req)
    assert isinstance(retry, FreshClaim)


@pytest.mark.contract
def test_crash_window_claim_without_finalize_retry_is_in_flight_real_store(
    postgres_backend_env: object,
) -> None:
    """AC3 at the real store: a claim with no finalize leaves an in-flight fence.

    The winning caller claims, "mutates", then crashes before finalize. The row
    stays ``claimed`` at the real store, so a retry with the same op_id is
    rejected in-flight and never re-executes -- the crash window is closed.
    """
    del postgres_backend_env
    guard = StateBackendInflightIdempotencyGuard()
    req = _req("op-guard-crash-1", {"title": "T"})

    first = guard.claim(req)
    assert isinstance(first, FreshClaim)
    # simulate a crash between mutate and finalize -- no finalize/release call

    retry = guard.claim(req)
    assert isinstance(retry, InFlightOutcome)


@pytest.mark.contract
def test_project_scoped_claim_with_null_story_id_real_store(
    postgres_backend_env: object,
) -> None:
    """A story-less (project-scoped) claim persists with story_id NULL (AG3-140).

    Proves the ``control_plane_operations.story_id`` NOT-NULL relaxation on the
    real store: a task-management-style operation carries no story_id and still
    claims, finalizes and replays under the one unified contract.
    """
    del postgres_backend_env
    guard = StateBackendInflightIdempotencyGuard()
    req = _req("op-guard-projscope-1", {"title": "T"}, story_id=None)

    first = guard.claim(req)
    assert isinstance(first, FreshClaim)
    payload = {"status_code": 200, "body": {"ok": True}}
    assert guard.finalize(req, first, payload) is True

    replay = guard.claim(req)
    assert isinstance(replay, ReplayOutcome)
    assert replay.result_payload == payload


@pytest.mark.contract
def test_admin_aborted_row_is_stable_conflict_not_replay_real_store(
    postgres_backend_env: object,
) -> None:
    """Codex r3 #2 (real store): an admin-aborted claim classifies as a stable
    conflict, never a replay of the abort payload and never a corrupt-500.

    A generic guard claim is resolved by the REAL admin-abort path
    (``admin_abort_control_plane_operation_global``) to ``status='aborted'`` with a
    control-plane result payload (NOT the route ``{status_code, body}`` shape).
    ``classify`` must return :class:`AbortedOutcome` against the genuine store.
    """
    from datetime import UTC, datetime

    from agentkit.backend.state_backend.operation_ledger import admin_abort_control_plane_operation_global
    from agentkit.backend.state_backend.store.inflight_idempotency_guard import (
        AbortedOutcome,
    )

    del postgres_backend_env
    guard = StateBackendInflightIdempotencyGuard()
    req = _req("op-real-admin-aborted", {"a": 1})

    first = guard.claim(req)
    assert isinstance(first, FreshClaim)

    aborted = admin_abort_control_plane_operation_global(
        op_id=req.op_id,
        status="aborted",
        response_payload={
            "status": "aborted",
            "op_id": req.op_id,
            "operation_kind": "task_create",
            "admin_note": "aborted by admin_abort_inflight_operation",
        },
        now=datetime.now(UTC),
    )
    assert aborted is True

    # The row is now terminal 'aborted' with a non-route payload -> a stable
    # conflict, NEVER a replay of the abort payload.
    assert isinstance(guard.classify(req), AbortedOutcome)


@pytest.mark.contract
def test_route_op_id_colliding_with_control_plane_committed_row_is_mismatch_real_store(
    postgres_backend_env: object,
) -> None:
    """Codex r4 #1 (cross-namespace): a route op_id that collides with a committed
    control_plane operation (even at the SAME body-hash) classifies as a 409
    mismatch on the real store -- never a cross-shape replay of the control-plane
    payload.
    """
    from datetime import UTC, datetime

    from agentkit.backend.control_plane.records import ControlPlaneOperationRecord
    from agentkit.backend.state_backend.operation_ledger import save_control_plane_operation_global
    from agentkit.backend.state_backend.store.inflight_idempotency_guard import (
        MismatchOutcome,
    )

    del postgres_backend_env
    guard = StateBackendInflightIdempotencyGuard()
    req = _req("op-route-cp-collision", {"a": 1})

    # A control_plane operation committed a terminal row under the SAME op_id and
    # (worst case) the SAME body-hash, but a control-plane operation_kind + a
    # ControlPlaneMutationResult-shaped payload.
    now = datetime.now(UTC)
    save_control_plane_operation_global(
        ControlPlaneOperationRecord(
            op_id=req.op_id,
            project_key="tenant-a",
            story_id="AG3-140",
            run_id="run-1",
            session_id="sess-1",
            operation_kind="phase_start",
            phase="setup",
            status="committed",
            response_payload={"status": "committed", "operation_kind": "phase_start"},
            created_at=now,
            updated_at=now,
            request_body_hash=req.body_hash,
        )
    )

    # The generic route classifies the foreign committed row by operation_kind ->
    # a stable 409 mismatch, NOT a replay of the control-plane payload.
    assert isinstance(guard.classify(req), MismatchOutcome)
