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


# ---------------------------------------------------------------------------
# Shared window-logic (run_route_idempotent) — the centralized claim/mutate/
# finalize invariant (Codex r2 Part-B #1 finalize-CAS-loss, #2 pre-outcome
# release). A tiny response value object stands in for a BC route response.
# ---------------------------------------------------------------------------
import json  # noqa: E402
from dataclasses import dataclass  # noqa: E402

from agentkit.backend.state_backend.store.inflight_idempotency_guard import (  # noqa: E402
    run_route_idempotent,
)


@dataclass(frozen=True)
class _Resp:
    status_code: int
    body: bytes


def _ok(status_code: int, body: dict[str, object]) -> _Resp:
    return _Resp(status_code, json.dumps(body, sort_keys=True).encode("utf-8"))


def _replay(payload: dict[str, object]) -> _Resp:
    sc = payload.get("status_code")
    body = payload.get("body")
    assert isinstance(sc, int) and isinstance(body, dict)
    return _Resp(sc, json.dumps(body, sort_keys=True).encode("utf-8"))


def _conflict(error_code: str, message: str, detail: dict[str, object]) -> _Resp:
    return _Resp(
        409, json.dumps({"error_code": error_code, "detail": detail}, sort_keys=True).encode()
    )


def _run(guard, req, mutate) -> _Resp:
    return run_route_idempotent(guard, req, mutate=mutate, replay=_replay, conflict=_conflict)


class _FinalizeAlwaysFalseGuard(InMemoryInflightIdempotencyGuard):
    """A guard whose finalize CAS always loses (models an admin-abort takeover)."""

    def finalize(self, request, claim, result_payload) -> bool:  # type: ignore[override]
        return False


def test_run_route_idempotent_success_then_replay_returns_stored_result() -> None:
    guard = InMemoryInflightIdempotencyGuard()
    req = _req("op-w1", {"a": 1})
    first = _run(guard, req, lambda: _ok(201, {"created": True}))
    second = _run(guard, req, lambda: _ok(201, {"created": "SHOULD-NOT-RUN"}))
    assert first.status_code == 201
    assert second.status_code == 201
    assert first.body == second.body  # replay returns the STORED result verbatim


def test_run_route_idempotent_finalize_false_does_not_return_success() -> None:
    """Codex r2 #1: a finalize CAS loss must NOT surface the success response."""
    guard = _FinalizeAlwaysFalseGuard()
    req = _req("op-ff", {"a": 1})
    ran: list[int] = []

    def mutate() -> _Resp:
        ran.append(1)
        return _ok(201, {"created": True})

    resp = _run(guard, req, mutate)
    assert ran == [1]  # the mutation ran once
    # finalize lost -> the row stayed 'claimed' -> classify returns in-flight ->
    # a fail-closed 409, NEVER a 201/committed success.
    assert resp.status_code == 409
    assert resp.status_code != 201


def test_run_route_idempotent_pre_outcome_exception_releases_claim_and_retry_succeeds() -> None:
    """Codex r2 #2: a pre-outcome exception releases the claim; a retry re-runs."""
    guard = InMemoryInflightIdempotencyGuard()
    req = _req("op-boom", {"a": 1})

    def boom() -> _Resp:
        raise RuntimeError("transient infrastructure error before any side effect")

    try:
        _run(guard, req, boom)
    except RuntimeError:
        pass
    else:  # pragma: no cover
        raise AssertionError("expected the transient exception to propagate")

    # The claim was released (not stuck operation_in_flight): a retry re-executes
    # cleanly and succeeds.
    retry = _run(guard, req, lambda: _ok(201, {"created": True}))
    assert retry.status_code == 201


def test_run_route_idempotent_server_error_response_releases_claim() -> None:
    """A >=500 route response is pre-commit; the claim is released for a retry."""
    guard = InMemoryInflightIdempotencyGuard()
    req = _req("op-500", {"a": 1})
    first = _run(guard, req, lambda: _ok(500, {"error_code": "internal_error"}))
    assert first.status_code == 500
    retry = _run(guard, req, lambda: _ok(201, {"created": True}))
    assert retry.status_code == 201  # released -> retry re-runs


def test_run_route_idempotent_post_commit_crash_stays_in_flight() -> None:
    """AC3: a claim + committed mutation with NO finalize (crash) stays in-flight.

    Modelled directly against the guard: after a winning claim and a 'committed'
    side effect, if finalize never runs (a process crash between mutate and
    finalize), the row stays 'claimed' and a retry is rejected in-flight (never
    re-executes). run_route_idempotent always calls finalize, so the crash is
    simulated at the guard boundary.
    """
    guard = InMemoryInflightIdempotencyGuard()
    req = _req("op-crash", {"a": 1})
    claim = guard.claim(req)
    assert isinstance(claim, FreshClaim)
    # <-- mutation "commits" here; process crashes before finalize (no finalize call)
    retry = guard.claim(req)
    assert isinstance(retry, InFlightOutcome)


def test_run_route_idempotent_admin_aborted_row_is_stable_conflict_not_replay() -> None:
    """Codex r3 #2: an admin-aborted terminal row is a STABLE 409 conflict.

    A real admin abort sets ``status='aborted'`` and stores a control-plane
    payload (NOT the route ``{status_code, body}`` shape). The generic guard must
    classify it as a fail-closed conflict -- never a replay of the foreign result,
    and never the corrupt-500 the route replay builder would raise on a non-route
    payload.
    """
    from agentkit.backend.state_backend.store.inflight_idempotency_guard import (
        AbortedOutcome,
    )

    guard = InMemoryInflightIdempotencyGuard()
    req = _req("op-admin-aborted", {"a": 1})

    # Faithful fixture: win the claim, then an admin abort resolves the SAME row
    # to a terminal 'aborted' state carrying a control-plane result payload.
    claim = guard.claim(req)
    assert isinstance(claim, FreshClaim)
    row = guard._rows[req.op_id]  # noqa: SLF001 - faithful abort fixture
    row.status = "aborted"
    row.result_payload = {
        "status": "aborted",
        "op_id": req.op_id,
        "operation_kind": "phase_start",
        "admin_note": "aborted by admin_abort_inflight_operation",
    }

    # classify() re-reads the row -> AbortedOutcome (not ReplayOutcome).
    assert isinstance(guard.classify(req), AbortedOutcome)

    # Through the route helper: a stable 409 operation_conflict, never a replay of
    # the aborted payload and never a corrupt-500.
    resp = _run(guard, req, lambda: _ok(201, {"should": "not-run"}))
    assert resp.status_code == 409
    assert json.loads(resp.body)["error_code"] == "operation_conflict"
