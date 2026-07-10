"""Real-backend contract tests for the control-plane operation/claim store (AG3-054).

E4/E8 (#8): these tests exercise the REAL state-backend control-plane operation
store -- NOT the injected fake repository the unit tests use -- so the atomic
claim, the stale-claim reclaim (#1) and the run-admission idempotency hold against
the genuine ``INSERT ... ON CONFLICT DO NOTHING`` semantics.

The control-plane operation/claim, session-binding and lock records are
Postgres-only by design (FK-22 §22.9; the global control-plane row methods exist
ONLY on the postgres backend; #3). These tests therefore bind the real Postgres
backend via the shared ``postgres_backend_env`` fixture (a per-test isolated
schema). They run in CI (and locally when a Postgres / docker backend is
available); the fixture provisions a throwaway container or honours an explicit
``AGENTKIT_STATE_BACKEND=postgres`` env.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING
from uuid import uuid4

import pytest

from agentkit.backend.control_plane.models import (
    ClosureCompleteRequest,
    PhaseDispatchResult,
    PhaseMutationRequest,
)
from agentkit.backend.control_plane.push_sync import (
    PushBarrierVerdict,
    PushBarrierVerdictStatus,
    RepoPushVerificationInput,
    SyncPointBarrierType,
)
from agentkit.backend.control_plane.records import (
    ControlPlaneOperationRecord,
    SessionRunBindingRecord,
)
from agentkit.backend.control_plane.runtime import ControlPlaneRuntimeService
from agentkit.backend.core_types import StoryMode
from agentkit.backend.governance.guard_system.records import StoryExecutionLockRecord
from agentkit.backend.state_backend.governance_runtime_store import load_story_execution_lock_global
from agentkit.backend.state_backend.operation_ledger import (
    admin_abort_control_plane_operation_global,
    claim_control_plane_operation_global,
    delete_control_plane_operation_global,
    finalize_control_plane_operation_global,
    finalize_control_plane_start_phase_global,
    has_committed_control_plane_operation_for_run_global,
    load_control_plane_operation_global,
    release_control_plane_operation_global,
    save_control_plane_operation_global,
)
from agentkit.backend.state_backend.story_closure_store import upsert_push_barrier_verdict_global
from agentkit.backend.state_backend.story_lifecycle_store import (
    load_session_run_binding_global,
    save_session_run_binding_global,
    save_story_context_global,
)
from agentkit.backend.state_backend.telemetry_event_store import load_execution_events_global
from agentkit.backend.story_context_manager.models import StoryContext
from agentkit.backend.story_context_manager.types import StoryType
from agentkit.backend.telemetry.contract.records import ExecutionEventRecord

if TYPE_CHECKING:
    from pathlib import Path

pytest_plugins = ("tests.fixtures.postgres_backend",)


def _op(
    op_id: str,
    *,
    status: str = "claimed",
    claimed_by: str | None = None,
    claimed_at: datetime | None = None,
) -> ControlPlaneOperationRecord:
    now = datetime(2026, 6, 7, 10, 0, tzinfo=UTC)
    return ControlPlaneOperationRecord(
        op_id=op_id,
        project_key="tenant-a",
        story_id="AG3-100",
        run_id="run-100",
        session_id="sess-001",
        operation_kind="phase_start",
        phase="setup",
        status=status,
        response_payload={},
        created_at=now,
        updated_at=now,
        claimed_by=claimed_by,
        claimed_at=claimed_at,
    )


@pytest.mark.contract
def test_atomic_claim_winner_then_loser_against_real_store(
    postgres_backend_env: object,
) -> None:
    """E4/#8: the first atomic claim WINS; a second claim for the same op_id LOSES.

    Exercises the genuine ``INSERT ... ON CONFLICT (op_id) DO NOTHING`` rowcount
    semantics at the real backend -- exactly ONE concurrent caller can win the
    claim for a given op_id, so two same-op_id starts can never both dispatch.
    """
    del postgres_backend_env
    op_id = "op-real-claim-001"

    won_first = claim_control_plane_operation_global(_op(op_id))
    won_second = claim_control_plane_operation_global(_op(op_id))

    assert won_first is True, "the first claim must win at the real store"
    assert won_second is False, "a second claim for the same op_id must lose"
    stored = load_control_plane_operation_global(op_id)
    assert stored is not None
    assert stored.status == "claimed"


@pytest.mark.contract
def test_claim_releases_and_reclaims_against_real_store(
    postgres_backend_env: object,
) -> None:
    """E1/#8: a released (deleted) claim is re-claimable at the real store.

    Proves the #1 cleanup path against the genuine store: after the claim is
    RELEASED (the exception/rejection path deletes it), the op_id is no longer
    poisoned -- a retry re-claims it and can proceed. A stale ``claimed`` row is
    therefore never permanently stranded.
    """
    del postgres_backend_env
    op_id = "op-real-claim-002"

    assert claim_control_plane_operation_global(_op(op_id)) is True
    # The loser cannot claim while the (stale/in-flight) row exists.
    assert claim_control_plane_operation_global(_op(op_id)) is False
    # Release the claim (the #1 exception/rejection cleanup path).
    delete_control_plane_operation_global(op_id)
    assert load_control_plane_operation_global(op_id) is None
    # The op_id is reclaimable -- a retry wins again (no poison).
    assert claim_control_plane_operation_global(_op(op_id)) is True


@pytest.mark.contract
def test_committed_op_blocks_reclaim_against_real_store(
    postgres_backend_env: object,
) -> None:
    """E4/#8: a terminal committed op blocks any re-claim at the real store.

    Once a winner durably stores its TERMINAL result, a same-op_id claim must
    lose (the loser replays, never re-dispatches). The committed row is retained,
    not overwritten by a placeholder.
    """
    del postgres_backend_env
    op_id = "op-real-claim-003"

    save_control_plane_operation_global(_op(op_id, status="committed"))
    # A claim for an already-terminal op_id loses (idempotent replay path).
    assert claim_control_plane_operation_global(_op(op_id)) is False
    stored = load_control_plane_operation_global(op_id)
    assert stored is not None
    assert stored.status == "committed", "the terminal row must not be clobbered"


# ---------------------------------------------------------------------------
# Runtime against the REAL Postgres store (#8): dispatch-once + exception cleanup
# ---------------------------------------------------------------------------


class _CountingDispatcher:
    """Records dispatch calls; returns a fixed admitted result (real-store test)."""

    def __init__(self) -> None:
        self.calls: list[str] = []

    def dispatch(
        self,
        *,
        ctx: StoryContext,
        phase: str,
        run_id: str,
        run_admitted: bool,
        detail: dict[str, object] | None = None,
    ) -> PhaseDispatchResult:
        del ctx, run_id, run_admitted, detail
        self.calls.append(phase)
        return PhaseDispatchResult(
            phase="setup",
            status="phase_completed",
            reaction="advance",
            dispatched=True,
            next_phase="implementation",
        )


@dataclass(frozen=True)
class _FakeBarrierPort:
    """Minimal ``PushBarrierEvidencePort`` returning prepared two-stage inputs.

    Mirrors the barrier's own boundary tests
    (``tests/integration/control_plane/test_push_barrier_boundaries_pg.py``): the
    op-id idempotency test injects a VERIFIED-pushed evidence set so the wired
    closure-entry barrier (FK-10 §10.2.4b) is satisfied and the test stays focused
    on the request-body-hash idempotency contract, not the unrelated push barrier.
    """

    inputs: tuple[RepoPushVerificationInput, ...]

    def collect_repo_inputs(
        self,
        *,
        project_key: str,
        story_id: str,
        run_id: str,
        required_sync_point_id: str | None = None,
    ) -> tuple[RepoPushVerificationInput, ...]:
        del project_key, story_id, run_id
        return tuple(
            replace(
                inp,
                edge_report_sync_point_id=(
                    inp.edge_report_sync_point_id or required_sync_point_id
                ),
                required_sync_point_id=required_sync_point_id,
            )
            for inp in self.inputs
        )


def _verified_input(repo_id: str) -> RepoPushVerificationInput:
    """A two-stage input the A-core counts as server-verified-pushed."""
    sha = "a" * 40
    return RepoPushVerificationInput(
        repo_id=repo_id,
        edge_report_present=True,
        edge_reported_pushed=True,
        edge_reported_head_sha=sha,
        server_ref_resolved=True,
        server_head_sha=sha,
    )


def _seed_passed_closure_entry_verdict(boundary_id: str) -> None:
    """Seed the closure-entry verdict for idempotency-only tests."""
    now = datetime(2026, 6, 7, 10, 0, tzinfo=UTC)
    sha = "a" * 40
    upsert_push_barrier_verdict_global(
        PushBarrierVerdict(
            project_key="tenant-a",
            story_id="AG3-100",
            run_id="run-100",
            boundary_type=SyncPointBarrierType.CLOSURE_ENTRY,
            boundary_id=boundary_id,
            repo_id="api",
            producer="test",
            boundary_epoch=1,
            expected_head_sha=sha,
            server_head_sha=sha,
            ownership_epoch=1,
            status=PushBarrierVerdictStatus.PASSED,
            created_at=now,
            updated_at=now,
            resolved_at=now,
            status_detail="seeded for op-id idempotency contract",
        )
    )


def _seed_pg_story_context(tmp_path: Path) -> StoryContext:
    project_root = tmp_path / "tenant-a"
    (project_root / "stories" / "AG3-100").mkdir(parents=True, exist_ok=True)
    ctx = StoryContext(
        project_key="tenant-a",
        story_id="AG3-100",
        story_type=StoryType.IMPLEMENTATION,
        execution_route=StoryMode.EXECUTION,
        project_root=project_root,
        participating_repos=["api"],
    )
    save_story_context_global(None, ctx)
    return ctx


def _pg_setup_request(op_id: str) -> PhaseMutationRequest:
    return PhaseMutationRequest(
        project_key="tenant-a",
        story_id="AG3-100",
        session_id="sess-001",
        principal_type="orchestrator",
        worktree_roots=["T:/worktrees/ag3-100"],
        op_id=op_id,
    )


@pytest.mark.contract
def test_two_concurrent_same_op_id_starts_dispatch_once_real_store(
    postgres_backend_env: object,
    tmp_path: Path,
) -> None:
    """E4/#8: two same-op_id starts dispatch EXACTLY once against the real store.

    Drives the productive ``ControlPlaneRuntimeService`` over the REAL Postgres
    control-plane store (default repository) with a counting stub dispatcher at
    the engine boundary. The real atomic claim lets only the FIRST caller
    dispatch; the second loses the claim, sees the committed terminal row and
    REPLAYS without re-dispatching.
    """
    del postgres_backend_env
    _seed_pg_story_context(tmp_path)
    dispatcher = _CountingDispatcher()
    service = ControlPlaneRuntimeService(phase_dispatcher=dispatcher)  # type: ignore[arg-type]
    request = _pg_setup_request("op-pg-race-001")

    first = service.start_phase(run_id="run-100", phase="setup", request=request)
    second = service.start_phase(run_id="run-100", phase="setup", request=request)

    assert first.status == "committed"
    assert second.status == "replayed"
    assert dispatcher.calls == ["setup"], "the real store must allow ONE dispatch"


@pytest.mark.contract
def test_exception_after_claim_releases_real_store_claim(
    postgres_backend_env: object,
    tmp_path: Path,
) -> None:
    """E1/#8: an exception after the real-store claim releases it (no poison).

    A dispatch that raises AFTER the atomic claim and BEFORE a terminal op is
    committed must RELEASE the claim at the real store, so the op_id is left
    reclaimable. The exception propagates, and a retry then dispatches and
    commits against the real Postgres store.
    """
    del postgres_backend_env
    _seed_pg_story_context(tmp_path)

    class _ExplodingThenAdmitted:
        def __init__(self) -> None:
            self.calls = 0

        def dispatch(
            self,
            *,
            ctx: StoryContext,
            phase: str,
            run_id: str,
            run_admitted: bool,
            detail: dict[str, object] | None = None,
        ) -> PhaseDispatchResult:
            del ctx, run_id, run_admitted, detail
            self.calls += 1
            if self.calls == 1:
                raise RuntimeError("dispatch boom (real store)")
            return PhaseDispatchResult(
                phase="setup",
                status="phase_completed",
                reaction="advance",
                dispatched=True,
                next_phase="implementation",
            )

    dispatcher = _ExplodingThenAdmitted()
    service = ControlPlaneRuntimeService(phase_dispatcher=dispatcher)  # type: ignore[arg-type]
    request = _pg_setup_request("op-pg-boom-001")

    with pytest.raises(RuntimeError, match="dispatch boom"):
        service.start_phase(run_id="run-100", phase="setup", request=request)
    # The claim was released at the real store -- no stranded op_id row.
    assert load_control_plane_operation_global("op-pg-boom-001") is None

    # Retry: reclaim + commit against the real store.
    result = service.start_phase(run_id="run-100", phase="setup", request=request)
    assert result.status == "committed"
    assert dispatcher.calls == 2
    committed = load_control_plane_operation_global("op-pg-boom-001")
    assert committed is not None
    assert committed.status == "committed"


# ---------------------------------------------------------------------------
# AG3-054 PART A: owner-scoped claim against the REAL Postgres store
# ---------------------------------------------------------------------------


def _claimed_op(
    op_id: str,
    *,
    owner: str,
    claimed_at: datetime,
) -> ControlPlaneOperationRecord:
    return _op(op_id, status="claimed", claimed_by=owner, claimed_at=claimed_at)


@pytest.mark.contract
def test_concurrent_claims_one_wins_loser_in_flight_real_store(
    postgres_backend_env: object,
    tmp_path: Path,
) -> None:
    """PART A: two same-op_id starts -> ONE wins; the loser is rejected in-flight.

    Drives the productive runtime over the REAL store with injected owner-token /
    clock seams. Winner A holds a LIVE claim (mid-dispatch, not yet finalized,
    simulated by seeding A's live claim). Loser B's start_phase must get an
    in-flight rejection and must NOT dispatch; A's claim is untouched.
    """
    del postgres_backend_env
    _seed_pg_story_context(tmp_path)
    now = datetime(2026, 6, 7, 10, 0, tzinfo=UTC)
    op_id = "op-pg-claim-race"
    # Winner A's LIVE claim.
    assert claim_control_plane_operation_global(
        _claimed_op(op_id, owner="owner-A", claimed_at=now)
    ) is True

    loser_dispatcher = _CountingDispatcher()
    loser = ControlPlaneRuntimeService(
        phase_dispatcher=loser_dispatcher,  # type: ignore[arg-type]
        now_fn=lambda: now + timedelta(minutes=1),  # AG3-139: age never matters
        # WARNING-5 (#5): the minted owner token must be UUID-shaped; the loser's
        # token only needs to be valid + distinct (it never wins here).
        token_factory=lambda: f"owner-{uuid4().hex}",
    )

    result = loser.start_phase(
        run_id="run-100", phase="setup", request=_pg_setup_request(op_id)
    )

    assert result.status == "rejected"
    assert loser_dispatcher.calls == [], "the loser must NOT dispatch at the real store"
    stored = load_control_plane_operation_global(op_id)
    assert stored is not None
    assert stored.status == "claimed"
    assert stored.claimed_by == "owner-A", "A's live claim must be untouched"


@pytest.mark.contract
def test_winner_finalizes_then_loser_replays_real_store(
    postgres_backend_env: object,
) -> None:
    """PART A: a winner's ownership-scoped finalize is replayed by a later caller."""
    del postgres_backend_env
    now = datetime(2026, 6, 7, 10, 0, tzinfo=UTC)
    op_id = "op-pg-finalize"
    assert claim_control_plane_operation_global(
        _claimed_op(op_id, owner="owner-A", claimed_at=now)
    ) is True

    terminal = _op(op_id, status="committed")
    assert (
        finalize_control_plane_operation_global(terminal, owner_token="owner-A") is True
    )
    stored = load_control_plane_operation_global(op_id)
    assert stored is not None
    assert stored.status == "committed"
    assert stored.claimed_by is None, "finalize clears the owner token"

    # A later same-op_id claim loses (terminal row), and a non-owner finalize/
    # release is a no-op against the terminal row.
    assert claim_control_plane_operation_global(_op(op_id)) is False
    release_control_plane_operation_global(op_id, owner_token="owner-B")
    assert load_control_plane_operation_global(op_id) is not None


@pytest.mark.contract
def test_owner_release_is_ownership_scoped_real_store(
    postgres_backend_env: object,
) -> None:
    """PART A: A's release/finalize is a no-op once the claim is admin-aborted.

    AG3-139: a foreign claim is never taken over via CAS. Instead: an operator
    admin-aborts A's claim (the AG3-138 end-way for a stuck claim). A's
    ownership-scoped release must NOT delete the aborted terminal row and A's
    ownership-scoped finalize must NOT overwrite it.
    """
    del postgres_backend_env
    start = datetime(2026, 6, 7, 10, 0, tzinfo=UTC)
    op_id = "op-pg-ownership"
    assert claim_control_plane_operation_global(
        _claimed_op(op_id, owner="owner-A", claimed_at=start)
    ) is True

    abort_payload: dict[str, object] = {
        "status": "aborted",
        "op_id": op_id,
        "operation_kind": "phase_start",
        "run_id": "run-100",
        "phase": "setup",
        "edge_bundle": None,
        "phase_dispatch": None,
        "admin_note": "admin_abort_inflight_operation by test: reason='stuck'.",
    }
    assert (
        admin_abort_control_plane_operation_global(
            op_id=op_id,
            status="aborted",
            response_payload=abort_payload,
            now=start + timedelta(minutes=10),
        )
        is True
    )

    # A's release is now a no-op (the row is terminal 'aborted', not 'claimed').
    release_control_plane_operation_global(op_id, owner_token="owner-A")
    stored = load_control_plane_operation_global(op_id)
    assert stored is not None, "A must not delete the aborted terminal row"
    assert stored.status == "aborted"

    # A's finalize is also a no-op (CAS rowcount 0).
    a_terminal = _op(op_id, status="committed")
    assert (
        finalize_control_plane_operation_global(a_terminal, owner_token="owner-A")
        is False
    )
    assert load_control_plane_operation_global(op_id).status == "aborted"  # type: ignore[union-attr]


@pytest.mark.contract
def test_foreign_claim_of_any_age_cannot_be_reclaimed_real_store(
    postgres_backend_env: object,
) -> None:
    """AG3-139: a foreign claim is never reclaimable, however old, at the real store.

    There is no CAS-takeover function left to exercise: ``claim_control_plane_
    operation_global`` (``INSERT ... ON CONFLICT (op_id) DO NOTHING``) is the ONLY
    claim-acquisition entrypoint, and it never consults the row's age. This pins
    that a claim seeded with a ``claimed_at`` well past the FORMER 5-minute TTL
    still blocks a second claim attempt (ownership never ends by wall clock, FK-91
    §91.1a Rule 16).
    """
    del postgres_backend_env
    start = datetime(2026, 6, 7, 10, 0, tzinfo=UTC)
    op_id = "op-pg-ancient-claim"
    assert claim_control_plane_operation_global(
        _claimed_op(
            op_id, owner="owner-crashed", claimed_at=start - timedelta(days=30)
        )
    ) is True

    # A second claim attempt on the SAME op_id still loses -- no reclaim path
    # exists at the store, regardless of the row's age.
    assert (
        claim_control_plane_operation_global(
            _claimed_op(op_id, owner="owner-new", claimed_at=start)
        )
        is False
    )
    stored = load_control_plane_operation_global(op_id)
    assert stored is not None
    assert stored.claimed_by == "owner-crashed", "the original claimant is untouched"
    assert stored.status == "claimed"


@pytest.mark.contract
def test_committed_op_for_run_admission_probe_real_store(
    postgres_backend_env: object,
) -> None:
    """PART C (#3): the run-scoped committed-op admission probe is run-matched."""
    del postgres_backend_env
    save_control_plane_operation_global(_op("op-pg-run-admit", status="committed"))

    assert (
        has_committed_control_plane_operation_for_run_global(
            "tenant-a", "AG3-100", "run-100"
        )
        is True
    )
    # A different run is NOT admitted by this run's committed op (#3).
    assert (
        has_committed_control_plane_operation_for_run_global(
            "tenant-a", "AG3-100", "run-999"
        )
        is False
    )


@pytest.mark.contract
def test_committed_phase_complete_does_not_admit_real_store(
    postgres_backend_env: object,
) -> None:
    """ERROR-3 (#3): a committed phase_complete (no committed setup start) is no proof.

    The admission probe must prove an admitted START (a committed setup
    ``phase_start``). A committed ``phase_complete`` for the run with NO committed
    setup start must NOT admit -- against the REAL narrowed SQL.
    """
    del postgres_backend_env
    # Only a committed phase_complete exists for the run -- NO committed setup start.
    save_control_plane_operation_global(
        ControlPlaneOperationRecord(
            op_id="op-pg-stray-complete",
            project_key="tenant-a",
            story_id="AG3-100",
            run_id="run-stray",
            session_id="sess-001",
            operation_kind="phase_complete",
            phase="implementation",
            status="committed",
            response_payload={},
            created_at=datetime(2026, 6, 7, 10, 0, tzinfo=UTC),
            updated_at=datetime(2026, 6, 7, 10, 0, tzinfo=UTC),
        )
    )

    assert (
        has_committed_control_plane_operation_for_run_global(
            "tenant-a", "AG3-100", "run-stray"
        )
        is False
    ), "a committed phase_complete must not admit (no committed setup start)"

    # A committed setup phase_start for the run DOES admit.
    save_control_plane_operation_global(_op("op-pg-setup-start", status="committed"))
    assert (
        has_committed_control_plane_operation_for_run_global(
            "tenant-a", "AG3-100", "run-100"
        )
        is True
    )


@pytest.mark.contract
def test_late_finalize_after_admin_abort_writes_no_side_effects_real_store(
    postgres_backend_env: object,
) -> None:
    """ERROR-1 (#1): a late finalize after an admin-abort writes NO side effects.

    AG3-139: a foreign claim is never taken over via CAS -- an orphaned/stuck
    claim ends ONLY via an explicit ``admin_abort_inflight_operation`` (or the
    AG3-138 startup reconciliation). Owner A holds a claim that an operator then
    admin-aborts. When A later calls the atomic CAS-gated start-phase finalize,
    the ownership CAS affects ZERO rows (status is no longer ``claimed``), so the
    whole transaction rolls back: NO session binding, NO lock and NO event are
    materialized by A, and the aborted terminal row is untouched.
    """
    del postgres_backend_env
    now = datetime(2026, 6, 7, 10, 0, tzinfo=UTC)
    op_id = "op-pg-loser-finalize"

    # A wins a claim; an operator then admin-aborts it (the AG3-138 end-way).
    assert claim_control_plane_operation_global(
        _claimed_op(op_id, owner="owner-A", claimed_at=now)
    ) is True
    abort_payload: dict[str, object] = {
        "status": "aborted",
        "op_id": op_id,
        "operation_kind": "phase_start",
        "run_id": "run-100",
        "phase": "setup",
        "edge_bundle": None,
        "phase_dispatch": None,
        "admin_note": "admin_abort_inflight_operation by test: reason='stuck'.",
    }
    assert (
        admin_abort_control_plane_operation_global(
            op_id=op_id,
            status="aborted",
            response_payload=abort_payload,
            now=now + timedelta(minutes=10),
        )
        is True
    )

    # A (the loser) now attempts the atomic CAS-gated start-phase finalize with its
    # OWN side effects. The CAS affects zero rows -> nothing is written.
    binding = SessionRunBindingRecord(
        session_id="sess-loser",
        project_key="tenant-a",
        story_id="AG3-100",
        run_id="run-100",
        principal_type="orchestrator",
        worktree_roots=("T:/worktrees/loser",),
        binding_version="1",
        updated_at=now,
    )
    lock = StoryExecutionLockRecord(
        project_key="tenant-a",
        story_id="AG3-100",
        run_id="run-loser",
        lock_type="story_execution",
        status="ACTIVE",
        worktree_roots=("T:/worktrees/loser",),
        binding_version="1",
        activated_at=now,
        updated_at=now,
    )
    event = ExecutionEventRecord(
        project_key="tenant-a",
        story_id="AG3-100",
        run_id="run-loser",
        event_id="evt-loser",
        event_type="session_run_binding_created",
        occurred_at=now,
        source_component="project_edge_client",
        severity="info",
        phase="setup",
        payload={},
    )

    applied = finalize_control_plane_start_phase_global(
        _op(op_id, status="committed"),
        owner_token="owner-A",
        binding=binding,
        locks=(lock,),
        events=(event,),
    )

    assert applied is False, "the loser's CAS finalize must not apply"
    # NO side effects were materialized by A.
    assert load_session_run_binding_global("sess-loser") is None
    assert (
        load_story_execution_lock_global(
            "tenant-a", "AG3-100", "run-loser", "story_execution"
        )
        is None
    )
    # The aborted terminal row is intact.
    stored = load_control_plane_operation_global(op_id)
    assert stored is not None
    assert stored.status == "aborted"
    assert stored.claimed_by is None


# ---------------------------------------------------------------------------
# AG3-054 adversarial edges: ERROR-2 (naive/legacy claimed_at never crashes and
# is never a takeover trigger, AG3-139), ERROR-3 (legacy save refuses to clobber
# a live claim), WARNING-4 (claim-generation scoped finalize/release) against the
# REAL Postgres store.
# ---------------------------------------------------------------------------


def _insert_raw_claimed_at_row(op_id: str, *, claimed_by: str, claimed_at_raw: str) -> None:
    """Insert a ``claimed`` op row with a RAW (verbatim) ``claimed_at`` TEXT value.

    Bypasses the canonicalizing mapper so the row carries exactly the legacy /
    naive / malformed text we want to exercise (ERROR-2). Uses the real backend's
    global connection -- the same store the productive runtime writes through.
    """
    from agentkit.backend.state_backend.postgres_store import _connect_global

    now_raw = datetime(2026, 6, 7, 10, 0, tzinfo=UTC).isoformat()
    with _connect_global() as conn:
        conn.execute(
            """
            INSERT INTO control_plane_operations (
                op_id, project_key, story_id, run_id, session_id,
                operation_kind, phase, status, response_json,
                created_at, updated_at, claimed_by, claimed_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                op_id,
                "tenant-a",
                "AG3-100",
                "run-100",
                "sess-001",
                "phase_start",
                "setup",
                "claimed",
                "{}",
                now_raw,
                now_raw,
                claimed_by,
                claimed_at_raw,
            ),
        )


@pytest.mark.contract
def test_naive_legacy_claimed_at_row_is_loadable_and_still_a_foreign_claim(
    postgres_backend_env: object,
) -> None:
    """AG3-139: a naive/legacy ``claimed_at`` row loads fine and stays foreign.

    A row stored with a naive ``claimed_at`` (no UTC offset) must NOT crash on
    load. Previously such a row was judged EXPIRED and reclaimed via a
    raw-column CAS takeover (ERROR-2); AG3-139 removed both the expiry judgement
    and the takeover CAS entirely -- a naive/legacy row is just an ordinary
    foreign claim now: it loads without crashing and a second claim attempt on
    it still loses, exactly like any other foreign claim.
    """
    del postgres_backend_env
    op_id = "op-pg-naive-legacy"
    naive_raw = "2026-06-07T09:00:00"
    _insert_raw_claimed_at_row(op_id, claimed_by="owner-legacy", claimed_at_raw=naive_raw)

    stored = load_control_plane_operation_global(op_id)
    assert stored is not None
    assert stored.status == "claimed"
    assert stored.claimed_by == "owner-legacy"
    # The mapper still normalizes claimed_at (audit instant only), no crash.
    assert stored.claimed_at is not None
    assert stored.claimed_at.tzinfo is not None

    # A second claim attempt on the SAME op_id still loses -- no reclaim path.
    assert (
        claim_control_plane_operation_global(
            _claimed_op(
                op_id,
                owner="owner-new",
                claimed_at=datetime(2026, 6, 7, 11, 0, tzinfo=UTC),
            )
        )
        is False
    )
    after = load_control_plane_operation_global(op_id)
    assert after is not None
    assert after.claimed_by == "owner-legacy", "the original (legacy) claimant is untouched"


@pytest.mark.contract
def test_legacy_save_refuses_to_clobber_live_claim_real_store(
    postgres_backend_env: object,
) -> None:
    """ERROR-3 (#3): the legacy upsert refuses to overwrite a LIVE claimed row.

    A ``complete_phase`` / ``fail_phase`` (or any non-owner save) reusing a live
    ``start_phase`` op_id must NOT clobber the claimed row and steal/destroy its
    ownership. The conditional upsert fails closed via
    ``ControlPlaneClaimCollisionError``; the claimed row is left intact.
    """
    from agentkit.backend.exceptions import ControlPlaneClaimCollisionError

    del postgres_backend_env
    now = datetime(2026, 6, 7, 10, 0, tzinfo=UTC)
    op_id = "op-pg-clobber-guard"
    # A live claimed start row owned by owner-A.
    assert claim_control_plane_operation_global(
        _claimed_op(op_id, owner="owner-A", claimed_at=now)
    ) is True

    # A complete/fail reusing the SAME op_id tries to save a terminal row.
    clobber = ControlPlaneOperationRecord(
        op_id=op_id,
        project_key="tenant-a",
        story_id="AG3-100",
        run_id="run-100",
        session_id="sess-001",
        operation_kind="phase_complete",
        phase="implementation",
        status="committed",
        response_payload={},
        created_at=now,
        updated_at=now,
    )
    with pytest.raises(ControlPlaneClaimCollisionError):
        save_control_plane_operation_global(clobber)

    # A's live claim is intact -- NOT clobbered, ownership NOT stolen.
    stored = load_control_plane_operation_global(op_id)
    assert stored is not None
    assert stored.status == "claimed"
    assert stored.claimed_by == "owner-A"

    # Sanity: a TERMINAL (non-claimed) row is still freely updatable by the save.
    save_control_plane_operation_global(_op("op-pg-terminal-ok", status="committed"))
    save_control_plane_operation_global(_op("op-pg-terminal-ok", status="rejected"))
    again = load_control_plane_operation_global("op-pg-terminal-ok")
    assert again is not None
    assert again.status == "rejected"


@pytest.mark.contract
def test_finalize_release_are_claim_generation_scoped_real_store(
    postgres_backend_env: object,
) -> None:
    """WARNING-4 (#4): finalize/release CAS key on owner AND claim generation.

    AG3-139: there is no more CAS-takeover to produce a "new generation, same
    token" scenario. Instead: owner-X's claim is released (the AG3-054 #1
    exception-cleanup path) and owner-X reclaims the SAME op_id fresh (a NEW
    ``claimed_at`` generation -- token reuse, the exact WARNING-4 hazard). The
    PREVIOUS generation's release/finalize -- even reusing the same owner token
    -- must be a no-op: its claim-generation-scoped CAS cannot match the NEWER claim
    generation, so it neither deletes nor finalizes it.
    """
    del postgres_backend_env
    start = datetime(2026, 6, 7, 10, 0, tzinfo=UTC)
    new_epoch = start + timedelta(minutes=10)
    op_id = "op-pg-epoch-scope"

    # owner-X holds a claim at the OLD generation.
    assert claim_control_plane_operation_global(
        _claimed_op(op_id, owner="owner-X", claimed_at=start)
    ) is True
    # The claim is released and owner-X reclaims the SAME op_id fresh at a NEW
    # generation (token reuse -- the exact WARNING-4 hazard).
    release_control_plane_operation_global(op_id, owner_token="owner-X")
    assert load_control_plane_operation_global(op_id) is None
    assert claim_control_plane_operation_global(
        _claimed_op(op_id, owner="owner-X", claimed_at=new_epoch)
    ) is True

    # The PREVIOUS generation's release (same token, OLD epoch) is a no-op.
    release_control_plane_operation_global(
        op_id, owner_token="owner-X", owner_claimed_at=start.isoformat()
    )
    stored = load_control_plane_operation_global(op_id)
    assert stored is not None, "the stale-epoch release must not delete the new claim"
    assert stored.status == "claimed"
    assert stored.claimed_at is not None
    assert stored.claimed_at.isoformat() == new_epoch.isoformat()

    # The PREVIOUS generation's finalize (same token, OLD epoch) is also a no-op.
    assert (
        finalize_control_plane_operation_global(
            _op(op_id, status="committed"),
            owner_token="owner-X",
            owner_claimed_at=start.isoformat(),
        )
        is False
    ), "the stale-epoch finalize must not finalize the new claim"
    still = load_control_plane_operation_global(op_id)
    assert still is not None
    assert still.status == "claimed"

    # The CURRENT generation (new epoch) finalizes successfully.
    assert (
        finalize_control_plane_operation_global(
            _op(op_id, status="committed"),
            owner_token="owner-X",
            owner_claimed_at=new_epoch.isoformat(),
        )
        is True
    )
    final = load_control_plane_operation_global(op_id)
    assert final is not None
    assert final.status == "committed"
    assert final.claimed_by is None


# ---------------------------------------------------------------------------
# AG3-054 ERROR-2: complete/fail/closure rejection is ATOMIC -- a collision with a
# LIVE claimed start leaves NO orphan side effect (against the REAL Postgres store,
# through the productive runtime path).
# ---------------------------------------------------------------------------


def _seed_live_claimed_start(op_id: str, *, now: datetime) -> None:
    """Seed a LIVE ``claimed`` setup start claim (owner-A, mid-dispatch)."""
    assert claim_control_plane_operation_global(
        _claimed_op(op_id, owner="owner-A", claimed_at=now)
    ) is True


def _seed_admission_binding(*, now: datetime) -> None:
    """Seed a run-matched session binding so complete/fail/closure is admitted."""
    save_session_run_binding_global(
        SessionRunBindingRecord(
            session_id="sess-001",
            project_key="tenant-a",
            story_id="AG3-100",
            run_id="run-100",
            principal_type="orchestrator",
            worktree_roots=("T:/worktrees/ag3-100",),
            binding_version="1",
            updated_at=now,
        )
    )


@pytest.mark.contract
def test_complete_phase_collision_writes_no_side_effects_real_store(
    postgres_backend_env: object,
    tmp_path: Path,
) -> None:
    """ERROR-2 (#2): a complete_phase colliding with a live claim is atomic (real store).

    The runtime drives the REAL atomic ``commit_control_plane_operation_with_side_
    effects`` store path. A ``complete_phase`` reusing a LIVE ``claimed`` start op_id
    must be fail-closed REJECTED with NO orphan side effect: the admission binding is
    NOT overwritten by a second materialization, NO new lock is written, NO event is
    appended, and the live claimed start row stays intact. The prior code committed
    the side effects in separate transactions BEFORE the collision was detected.
    """
    del postgres_backend_env
    _seed_pg_story_context(tmp_path)
    now = datetime(2026, 6, 7, 10, 0, tzinfo=UTC)
    _seed_admission_binding(now=now)
    op_id = "op-pg-complete-collision"
    _seed_live_claimed_start(op_id, now=now)

    service = ControlPlaneRuntimeService(now_fn=lambda: now)
    result = service.complete_phase(
        run_id="run-100",
        phase="implementation",
        request=PhaseMutationRequest(
            project_key="tenant-a",
            story_id="AG3-100",
            session_id="sess-001",
            principal_type="orchestrator",
            worktree_roots=["T:/worktrees/ag3-100"],
            op_id=op_id,
        ),
    )

    assert result.status == "rejected"
    # The live claimed start row is intact -- ownership NOT stolen/destroyed.
    stored = load_control_plane_operation_global(op_id)
    assert stored is not None
    assert stored.status == "claimed"
    assert stored.claimed_by == "owner-A"
    assert stored.operation_kind == "phase_start"
    # ERROR-2: NO orphan side effect was committed.
    binding = load_session_run_binding_global("sess-001")
    assert binding is not None, "the admission binding must survive the rejection"
    assert binding.binding_version == "1", "binding must NOT be re-materialized"
    assert (
        load_story_execution_lock_global(
            "tenant-a", "AG3-100", "run-100", "story_execution"
        )
        is None
    ), "no orphan lock may be written on a rejected complete"
    events = load_execution_events_global("tenant-a", "AG3-100", run_id="run-100")
    assert events == [], "no orphan event may be appended on a rejected complete"


@pytest.mark.contract
def test_complete_closure_collision_writes_no_side_effects_real_store(
    postgres_backend_env: object,
    tmp_path: Path,
) -> None:
    """ERROR-2 (#2): a closure colliding with a live claim is atomic (real store).

    A ``complete_closure`` reusing a LIVE ``claimed`` start op_id must be fail-closed
    REJECTED with NO orphan TEARDOWN: the binding is NOT deleted, NO INACTIVE lock is
    written, NO deactivation event fires, and the live claimed start row stays intact.
    Proves the standard-closure side effects roll back on collision through the real
    atomic commit path (the prior code deactivated the regime BEFORE the collision).
    """
    del postgres_backend_env
    _seed_pg_story_context(tmp_path)
    now = datetime(2026, 6, 7, 10, 0, tzinfo=UTC)
    _seed_admission_binding(now=now)
    op_id = "op-pg-closure-collision"
    _seed_live_claimed_start(op_id, now=now)

    service = ControlPlaneRuntimeService(now_fn=lambda: now)
    result = service.complete_closure(
        run_id="run-100",
        request=ClosureCompleteRequest(
            project_key="tenant-a",
            story_id="AG3-100",
            session_id="sess-001",
            op_id=op_id,
        ),
    )

    assert result.status == "rejected"
    # ERROR-2: the teardown rolled back -- NO orphan side effect.
    binding = load_session_run_binding_global("sess-001")
    assert binding is not None, "the binding must NOT be deleted on collision"
    assert binding.run_id == "run-100"
    assert (
        load_story_execution_lock_global(
            "tenant-a", "AG3-100", "run-100", "story_execution"
        )
        is None
    ), "no INACTIVE lock may be written on a rejected closure"
    events = load_execution_events_global("tenant-a", "AG3-100", run_id="run-100")
    assert events == [], "no deactivation event may fire on a rejected closure"
    # The live claimed start row is intact.
    stored = load_control_plane_operation_global(op_id)
    assert stored is not None
    assert stored.status == "claimed"
    assert stored.claimed_by == "owner-A"


# ---------------------------------------------------------------------------
# AG3-054 run-scoping sweep: the session-run-binding is keyed by session_id, but a
# stale/late operation for an OLD run must never overwrite/delete a DIFFERENT (NEW)
# run's live binding that has rebound the same session_id. Exercised against the
# REAL run-scoped conditional binding SAVE/DELETE SQL.
# ---------------------------------------------------------------------------


def _binding(run_id: str, *, version: str) -> SessionRunBindingRecord:
    """A session-run-binding for ``sess-001`` bound to ``run_id``."""
    return SessionRunBindingRecord(
        session_id="sess-001",
        project_key="tenant-a",
        story_id="AG3-100",
        run_id=run_id,
        principal_type="orchestrator",
        worktree_roots=("T:/worktrees/ag3-100",),
        binding_version=version,
        updated_at=datetime(2026, 6, 7, 10, 0, tzinfo=UTC),
    )


@pytest.mark.contract
def test_binding_save_run_scoped_collision_real_store(
    postgres_backend_env: object,
) -> None:
    """AG3-054 sweep: a binding SAVE for an OLD run never overwrites a NEW binding.

    ``sess-001`` is bound to run-NEW. An attempt to upsert a binding for the SAME
    session under run-OLD (a stale/late operation) must fail closed via
    ``ControlPlaneBindingCollisionError`` at the REAL run-scoped conditional upsert
    SQL -- the live run-NEW binding is left untouched. A re-save for the OWNING run
    still succeeds (run-matched update).
    """
    from agentkit.backend.exceptions import ControlPlaneBindingCollisionError
    del postgres_backend_env
    save_session_run_binding_global(_binding("run-NEW", version="500"))

    # The PUBLIC save surface refuses a foreign active overwrite.
    with pytest.raises(ControlPlaneBindingCollisionError):
        save_session_run_binding_global(_binding("run-OLD", version="400"))

    # The live NEW binding is intact (run + version unchanged).
    survived = load_session_run_binding_global("sess-001")
    assert survived is not None
    assert survived.run_id == "run-NEW"
    assert survived.binding_version == "500"

    # A run-matched re-save (the OWNING run) still updates successfully.
    save_session_run_binding_global(_binding("run-NEW", version="501"))
    updated = load_session_run_binding_global("sess-001")
    assert updated is not None
    assert updated.run_id == "run-NEW"
    assert updated.binding_version == "501"


@pytest.mark.contract
def test_public_binding_save_cannot_erase_revoked_notification(
    postgres_backend_env: object,
) -> None:
    """R2-1: revoked-row supersede requires an audited ledger transaction."""
    from agentkit.backend.exceptions import ControlPlaneBindingCollisionError

    del postgres_backend_env
    revoked = replace(
        _binding("run-OLD", version="500"),
        status="revoked",
        revocation_reason="story_reset",
    )
    save_session_run_binding_global(revoked)

    with pytest.raises(ControlPlaneBindingCollisionError):
        save_session_run_binding_global(_binding("run-NEW", version="501"))

    survived = load_session_run_binding_global("sess-001")
    assert survived == revoked


@pytest.mark.contract
def test_standard_closure_foreign_binding_protected_real_store(
    postgres_backend_env: object,
    tmp_path: Path,
) -> None:
    """AG3-054 sweep: an OLD run's closure never deletes a NEW run's binding (real store).

    Run-OLD is admitted by its OWN committed setup ``phase_start`` op, so admission
    passes. But ``sess-001`` is bound to run-NEW (the session was rebound). The
    standard closure for run-OLD must be fail-closed REJECTED at the REAL run-scoped
    binding DELETE: run-NEW's binding is NOT deleted, NO INACTIVE lock is written for
    run-OLD and NO deactivation event is appended for run-OLD. The repo probes use
    the global load surfaces (the foreign-binding-protection evidence).
    """
    del postgres_backend_env
    _seed_pg_story_context(tmp_path)
    now = datetime(2026, 6, 7, 10, 0, tzinfo=UTC)
    # run-NEW owns the live binding under sess-001.
    save_session_run_binding_global(_binding("run-NEW", version="500"))
    # run-OLD is admitted by its own committed setup phase_start op.
    save_control_plane_operation_global(
        ControlPlaneOperationRecord(
            op_id="op-pg-old-setup",
            project_key="tenant-a",
            story_id="AG3-100",
            run_id="run-OLD",
            session_id="sess-001",
            operation_kind="phase_start",
            phase="setup",
            status="committed",
            response_payload={},
            created_at=now,
            updated_at=now,
        )
    )

    service = ControlPlaneRuntimeService(now_fn=lambda: now)
    result = service.complete_closure(
        run_id="run-OLD",
        request=ClosureCompleteRequest(
            project_key="tenant-a",
            story_id="AG3-100",
            session_id="sess-001",
            op_id="op-pg-old-closure",
        ),
    )

    assert result.status == "rejected"
    # Foreign-binding-protection probes (global load surfaces).
    survived = load_session_run_binding_global("sess-001")
    assert survived is not None, "run-NEW's live binding must survive the old closure"
    assert survived.run_id == "run-NEW"
    assert survived.binding_version == "500"
    assert (
        load_story_execution_lock_global(
            "tenant-a", "AG3-100", "run-OLD", "story_execution"
        )
        is None
    ), "no INACTIVE lock may be written for the old run"
    old_events = load_execution_events_global("tenant-a", "AG3-100", run_id="run-OLD")
    assert old_events == [], "no deactivation event may fire for the old run"
    # The stale closure stored no committed op.
    assert load_control_plane_operation_global("op-pg-old-closure") is None


# ---------------------------------------------------------------------------
# AG3-140 / Codex finding 3 against the REAL Postgres store: op_id reuse with a
# DIFFERENT body must fail closed with ``409 idempotency_mismatch`` (the stamped
# ``request_body_hash`` is compared on replay), never replay the wrong result.
# ---------------------------------------------------------------------------


def _pg_setup_request_wt(op_id: str, worktree_root: str) -> PhaseMutationRequest:
    return PhaseMutationRequest(
        project_key="tenant-a",
        story_id="AG3-100",
        session_id="sess-001",
        principal_type="orchestrator",
        worktree_roots=[worktree_root],
        op_id=op_id,
    )


@pytest.mark.contract
def test_phase_start_reused_op_id_different_body_mismatch_real_store(
    postgres_backend_env: object,
    tmp_path: Path,
) -> None:
    """A reused start op_id with a DIFFERENT body is 409 idempotency_mismatch (real store).

    Codex finding 3: against the GENUINE Postgres control-plane store the stamped
    ``request_body_hash`` on the committed terminal row is compared on replay -- a
    reuse with a different body (here different ``worktree_roots``) fails closed
    instead of surfacing the wrong stored result; an identical-body reuse replays.
    """
    from agentkit.backend.story_context_manager.errors import IdempotencyMismatchError

    del postgres_backend_env
    _seed_pg_story_context(tmp_path)
    service = ControlPlaneRuntimeService(phase_dispatcher=_CountingDispatcher())  # type: ignore[arg-type]

    first = service.start_phase(
        run_id="run-100",
        phase="setup",
        request=_pg_setup_request_wt("op-pg-mismatch-001", "T:/worktrees/a"),
    )
    assert first.status == "committed"

    with pytest.raises(IdempotencyMismatchError) as excinfo:
        service.start_phase(
            run_id="run-100",
            phase="setup",
            request=_pg_setup_request_wt("op-pg-mismatch-001", "T:/worktrees/DIFFERENT"),
        )
    assert excinfo.value.detail["conflict"] == "body_hash_mismatch"
    assert excinfo.value.detail["op_id"] == "op-pg-mismatch-001"

    # An identical-body reuse still replays the stored result (no false mismatch).
    replay = service.start_phase(
        run_id="run-100",
        phase="setup",
        request=_pg_setup_request_wt("op-pg-mismatch-001", "T:/worktrees/a"),
    )
    assert replay.status == "replayed"


@pytest.mark.contract
def test_closure_reused_op_id_different_body_mismatch_real_store(
    postgres_backend_env: object,
    tmp_path: Path,
) -> None:
    """A reused closure op_id with a DIFFERENT body is 409 idempotency_mismatch (real store).

    A committed closure over the real store MUST stamp its ``request_body_hash``; a
    reuse of the same op_id with a different ``detail`` MUST fail closed, while an
    identical-body reuse replays. AG3-140 finding-3 fix: the atomic side-effects
    commit (``commit_control_plane_operation_with_side_effects_global_row``) now
    persists ``request_body_hash``, so complete/fail/closure enforce the mismatch
    on the real store (this test no longer xfails).
    """
    from agentkit.backend.story_context_manager.errors import IdempotencyMismatchError

    del postgres_backend_env
    _seed_pg_story_context(tmp_path)
    # The closure-entry push barrier (AG3-147, FK-10 §10.2.4b) is wired on the
    # default store; seed its persisted verdict so this test stays focused on
    # the op-id idempotency contract (the barrier's own negative paths are
    # covered elsewhere).
    service = ControlPlaneRuntimeService(
        phase_dispatcher=_CountingDispatcher(),  # type: ignore[arg-type]
        push_barrier_evidence=_FakeBarrierPort((_verified_input("api"),)),  # type: ignore[arg-type]
    )
    # Admit the run: a committed setup start materializes the run-matched evidence
    # closure requires (a session binding + a committed setup phase_start).
    admitted = service.start_phase(
        run_id="run-100",
        phase="setup",
        request=_pg_setup_request("op-pg-closure-admit-001"),
    )
    assert admitted.status == "committed"
    _seed_passed_closure_entry_verdict("run-100")

    def _closure(op_id: str, detail: dict[str, object]) -> ClosureCompleteRequest:
        return ClosureCompleteRequest(
            project_key="tenant-a",
            story_id="AG3-100",
            session_id="sess-001",
            op_id=op_id,
            detail=detail,
        )

    first = service.complete_closure(
        run_id="run-100", request=_closure("op-pg-closure-mismatch-001", {"k": "v1"})
    )
    assert first.status == "committed"

    with pytest.raises(IdempotencyMismatchError) as excinfo:
        service.complete_closure(
            run_id="run-100",
            request=_closure("op-pg-closure-mismatch-001", {"k": "DIFFERENT"}),
        )
    assert excinfo.value.detail["conflict"] == "body_hash_mismatch"

    replay = service.complete_closure(
        run_id="run-100", request=_closure("op-pg-closure-mismatch-001", {"k": "v1"})
    )
    assert replay.status == "replayed"
