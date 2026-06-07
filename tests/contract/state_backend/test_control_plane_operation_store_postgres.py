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

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING
from uuid import uuid4

import pytest

from agentkit.control_plane.models import (
    ClosureCompleteRequest,
    PhaseDispatchResult,
    PhaseMutationRequest,
)
from agentkit.control_plane.records import (
    ControlPlaneOperationRecord,
    SessionRunBindingRecord,
)
from agentkit.control_plane.runtime import ControlPlaneRuntimeService
from agentkit.core_types import StoryMode
from agentkit.governance.guard_system.records import StoryExecutionLockRecord
from agentkit.state_backend.store import (
    claim_control_plane_operation_global,
    delete_control_plane_operation_global,
    finalize_control_plane_operation_global,
    finalize_control_plane_start_phase_global,
    has_committed_control_plane_operation_for_run_global,
    load_control_plane_operation_global,
    load_execution_events_global,
    load_session_run_binding_global,
    load_story_execution_lock_global,
    release_control_plane_operation_global,
    save_control_plane_operation_global,
    save_session_run_binding_global,
    save_story_context_global,
    takeover_control_plane_operation_global,
)
from agentkit.story_context_manager.models import StoryContext
from agentkit.story_context_manager.types import StoryType
from agentkit.telemetry.contract.records import ExecutionEventRecord

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
        story_dir: Path,
        run_id: str,
        run_admitted: bool,
        detail: dict[str, object] | None = None,
    ) -> PhaseDispatchResult:
        del ctx, story_dir, run_id, run_admitted, detail
        self.calls.append(phase)
        return PhaseDispatchResult(
            phase="setup",
            status="phase_completed",
            reaction="advance",
            dispatched=True,
            next_phase="implementation",
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
            story_dir: Path,
            run_id: str,
            run_admitted: bool,
            detail: dict[str, object] | None = None,
        ) -> PhaseDispatchResult:
            del ctx, story_dir, run_id, run_admitted, detail
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
# AG3-054 PART A: leased, owner-scoped claim against the REAL Postgres store
# ---------------------------------------------------------------------------


def _leased_op(
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
    simulated by seeding A's live leased claim). Loser B's start_phase must get an
    in-flight rejection and must NOT dispatch; A's claim is untouched.
    """
    del postgres_backend_env
    _seed_pg_story_context(tmp_path)
    now = datetime(2026, 6, 7, 10, 0, tzinfo=UTC)
    op_id = "op-pg-leased-race"
    # Winner A's LIVE claim (fresh, not expired).
    assert claim_control_plane_operation_global(
        _leased_op(op_id, owner="owner-A", claimed_at=now)
    ) is True

    loser_dispatcher = _CountingDispatcher()
    loser = ControlPlaneRuntimeService(
        phase_dispatcher=loser_dispatcher,  # type: ignore[arg-type]
        now_fn=lambda: now + timedelta(minutes=1),  # still within the lease TTL
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
        _leased_op(op_id, owner="owner-A", claimed_at=now)
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
    """PART A: A's release/finalize is a no-op once B took over (CAS rowcount 0).

    After B takes over the (expired) claim, A's ownership-scoped release must NOT
    delete B's row and A's ownership-scoped finalize must NOT overwrite B's claim.
    """
    del postgres_backend_env
    start = datetime(2026, 6, 7, 10, 0, tzinfo=UTC)
    op_id = "op-pg-ownership"
    # A holds an EXPIRED claim.
    assert claim_control_plane_operation_global(
        _leased_op(op_id, owner="owner-A", claimed_at=start)
    ) is True
    # B takes over via CAS (observing A's exact lease).
    b_claim = _leased_op(
        op_id, owner="owner-B", claimed_at=start + timedelta(minutes=10)
    )
    assert (
        takeover_control_plane_operation_global(
            b_claim,
            observed_claimed_by="owner-A",
            # ERROR-2 (AG3-054): the observed value is the RAW stored ``claimed_at``
            # TEXT (what the store round-trips), not the datetime.
            observed_claimed_at=start.isoformat(),
        )
        is True
    )

    # A's release is now a no-op (it no longer owns the row).
    release_control_plane_operation_global(op_id, owner_token="owner-A")
    stored = load_control_plane_operation_global(op_id)
    assert stored is not None, "A must not delete B's row"
    assert stored.claimed_by == "owner-B"

    # A's finalize is also a no-op (CAS rowcount 0).
    a_terminal = _op(op_id, status="committed")
    assert (
        finalize_control_plane_operation_global(a_terminal, owner_token="owner-A")
        is False
    )
    assert load_control_plane_operation_global(op_id).status == "claimed"  # type: ignore[union-attr]


@pytest.mark.contract
def test_expired_takeover_succeeds_non_expired_refused_real_store(
    postgres_backend_env: object,
) -> None:
    """PART A: CAS takeover succeeds for an expired lease; refused for a live one."""
    del postgres_backend_env
    start = datetime(2026, 6, 7, 10, 0, tzinfo=UTC)

    # Expired claim -> CAS takeover succeeds.
    assert claim_control_plane_operation_global(
        _leased_op("op-pg-expired", owner="owner-crash", claimed_at=start)
    ) is True
    taken = _leased_op(
        "op-pg-expired", owner="owner-new", claimed_at=start + timedelta(minutes=10)
    )
    assert (
        takeover_control_plane_operation_global(
            taken,
            observed_claimed_by="owner-crash",
            observed_claimed_at=start.isoformat(),
        )
        is True
    )

    # A stale-observation takeover (wrong observed lease) is refused (CAS 0 rows).
    assert (
        takeover_control_plane_operation_global(
            _leased_op("op-pg-expired", owner="owner-other", claimed_at=start),
            observed_claimed_by="owner-crash",  # no longer the owner
            observed_claimed_at=start.isoformat(),
        )
        is False
    )
    stored = load_control_plane_operation_global("op-pg-expired")
    assert stored is not None
    assert stored.claimed_by == "owner-new"


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
def test_loser_after_takeover_writes_no_side_effects_real_store(
    postgres_backend_env: object,
) -> None:
    """ERROR-1 (#1): the loser's atomic finalize writes NO side effects (real store).

    Owner A holds a claim that owner B took over and finalized. When A then calls
    the atomic CAS-gated start-phase finalize, the ownership CAS affects ZERO rows,
    so the whole transaction rolls back: NO session binding, NO lock and NO event
    are materialized by the loser, and B's terminal committed row is untouched.
    """
    del postgres_backend_env
    now = datetime(2026, 6, 7, 10, 0, tzinfo=UTC)
    op_id = "op-pg-loser-finalize"

    # A wins a claim, then B takes it over and finalizes it (terminal committed).
    assert claim_control_plane_operation_global(
        _leased_op(op_id, owner="owner-A", claimed_at=now)
    ) is True
    assert (
        takeover_control_plane_operation_global(
            _leased_op(op_id, owner="owner-B", claimed_at=now + timedelta(minutes=10)),
            observed_claimed_by="owner-A",
            observed_claimed_at=now.isoformat(),
        )
        is True
    )
    assert (
        finalize_control_plane_operation_global(
            _op(op_id, status="committed"), owner_token="owner-B"
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
        binding_version="bind-loser",
        updated_at=now,
    )
    lock = StoryExecutionLockRecord(
        project_key="tenant-a",
        story_id="AG3-100",
        run_id="run-loser",
        lock_type="story_execution",
        status="ACTIVE",
        worktree_roots=("T:/worktrees/loser",),
        binding_version="bind-loser",
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
    # NO side effects were materialized by the loser.
    assert load_session_run_binding_global("sess-loser") is None
    assert (
        load_story_execution_lock_global(
            "tenant-a", "AG3-100", "run-loser", "story_execution"
        )
        is None
    )
    # B's terminal committed row is intact.
    stored = load_control_plane_operation_global(op_id)
    assert stored is not None
    assert stored.status == "committed"
    assert stored.claimed_by is None


# ---------------------------------------------------------------------------
# AG3-054 adversarial edges: ERROR-2 (naive/legacy claimed_at takeover),
# ERROR-3 (legacy save refuses to clobber a live claim), WARNING-4 (lease-epoch
# scoped finalize/release) against the REAL Postgres store.
# ---------------------------------------------------------------------------


def _insert_raw_claimed_at_row(op_id: str, *, claimed_by: str, claimed_at_raw: str) -> None:
    """Insert a ``claimed`` op row with a RAW (verbatim) ``claimed_at`` TEXT value.

    Bypasses the canonicalizing mapper so the row carries exactly the legacy /
    naive / malformed text we want to exercise (ERROR-2). Uses the real backend's
    global connection -- the same store the productive runtime writes through.
    """
    from agentkit.state_backend.postgres_store import _connect_global

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
def test_naive_legacy_claimed_at_is_reclaimable_real_store(
    postgres_backend_env: object,
) -> None:
    """ERROR-2 (#2): a NAIVE/legacy ``claimed_at`` row is actually taken over.

    A row stored with a naive ``claimed_at`` (no UTC offset) is judged EXPIRED by
    the runtime, but the takeover CAS must match the RAW stored column -- not the
    mapper-normalized ``'...+00:00'`` value. This test seeds a real naive row,
    loads it through the store (so ``claimed_at_raw`` carries the verbatim text),
    and proves the takeover CAS affects ONE row (rowcount 1). The fake-repo unit
    test compares datetimes and cannot catch this raw-vs-normalized mismatch.
    """
    del postgres_backend_env
    op_id = "op-pg-naive-legacy"
    # A legacy/naive lease instant (NO offset) -- well in the past => EXPIRED.
    naive_raw = "2026-06-07T09:00:00"
    _insert_raw_claimed_at_row(op_id, claimed_by="owner-legacy", claimed_at_raw=naive_raw)

    stored = load_control_plane_operation_global(op_id)
    assert stored is not None
    assert stored.status == "claimed"
    # The mapper normalized claimed_at for the expiry judgement ...
    assert stored.claimed_at is not None
    assert stored.claimed_at.tzinfo is not None
    # ... but the RAW value preserved for the CAS is the verbatim naive text.
    assert stored.claimed_at_raw == naive_raw

    # The takeover CAS must observe the RAW value and affect exactly ONE row.
    taken = _leased_op(
        op_id, owner="owner-new", claimed_at=datetime(2026, 6, 7, 11, 0, tzinfo=UTC)
    )
    assert (
        takeover_control_plane_operation_global(
            taken,
            observed_claimed_by="owner-legacy",
            observed_claimed_at=stored.claimed_at_raw,
        )
        is True
    ), "a naive/legacy claimed_at row must be reclaimable (not poisoned)"
    after = load_control_plane_operation_global(op_id)
    assert after is not None
    assert after.claimed_by == "owner-new"


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
    from agentkit.exceptions import ControlPlaneClaimCollisionError

    del postgres_backend_env
    now = datetime(2026, 6, 7, 10, 0, tzinfo=UTC)
    op_id = "op-pg-clobber-guard"
    # A live claimed start row owned by owner-A.
    assert claim_control_plane_operation_global(
        _leased_op(op_id, owner="owner-A", claimed_at=now)
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
def test_finalize_release_are_lease_epoch_scoped_real_store(
    postgres_backend_env: object,
) -> None:
    """WARNING-4 (#4): finalize/release CAS key on owner AND lease epoch.

    After an expiry-takeover re-stamps a NEW ``claimed_at``, the PREVIOUS owner's
    release/finalize -- even if it reuses the same owner token -- must be a no-op:
    its lease-epoch-scoped CAS cannot match the NEWER lease generation, so it
    neither deletes nor finalizes the new lease.
    """
    del postgres_backend_env
    start = datetime(2026, 6, 7, 10, 0, tzinfo=UTC)
    new_epoch = start + timedelta(minutes=10)
    op_id = "op-pg-epoch-scope"

    # owner-X holds a claim at the OLD epoch.
    assert claim_control_plane_operation_global(
        _leased_op(op_id, owner="owner-X", claimed_at=start)
    ) is True
    # A takeover re-stamps the lease to owner-X again but at a NEW epoch (token
    # reuse + new generation -- the exact WARNING-4 hazard).
    assert (
        takeover_control_plane_operation_global(
            _leased_op(op_id, owner="owner-X", claimed_at=new_epoch),
            observed_claimed_by="owner-X",
            observed_claimed_at=start.isoformat(),
        )
        is True
    )

    # The PREVIOUS generation's release (same token, OLD epoch) is a no-op.
    release_control_plane_operation_global(
        op_id, owner_token="owner-X", owner_claimed_at=start.isoformat()
    )
    stored = load_control_plane_operation_global(op_id)
    assert stored is not None, "the stale-epoch release must not delete the new lease"
    assert stored.status == "claimed"
    assert stored.claimed_at_raw == new_epoch.isoformat()

    # The PREVIOUS generation's finalize (same token, OLD epoch) is also a no-op.
    assert (
        finalize_control_plane_operation_global(
            _op(op_id, status="committed"),
            owner_token="owner-X",
            owner_claimed_at=start.isoformat(),
        )
        is False
    ), "the stale-epoch finalize must not finalize the new lease"
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
    """Seed a LIVE ``claimed`` setup start lease (owner-A, mid-dispatch)."""
    assert claim_control_plane_operation_global(
        _leased_op(op_id, owner="owner-A", claimed_at=now)
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
            binding_version="bind-001",
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
    assert binding.binding_version == "bind-001", "binding must NOT be re-materialized"
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
    from agentkit.exceptions import ControlPlaneBindingCollisionError
    from agentkit.state_backend.postgres_store import (
        _connect_global,
        _insert_session_binding_row,
    )
    from agentkit.state_backend.store.mappers import session_binding_to_row

    del postgres_backend_env
    save_session_run_binding_global(_binding("run-NEW", version="bind-NEW"))

    # A run-OLD save for the same session is refused (foreign run).
    old_row = session_binding_to_row(_binding("run-OLD", version="bind-OLD"))
    with pytest.raises(ControlPlaneBindingCollisionError), _connect_global() as conn:
        _insert_session_binding_row(conn, old_row)

    # The live NEW binding is intact (run + version unchanged).
    survived = load_session_run_binding_global("sess-001")
    assert survived is not None
    assert survived.run_id == "run-NEW"
    assert survived.binding_version == "bind-NEW"

    # A run-matched re-save (the OWNING run) still updates successfully.
    save_session_run_binding_global(_binding("run-NEW", version="bind-NEW-2"))
    updated = load_session_run_binding_global("sess-001")
    assert updated is not None
    assert updated.run_id == "run-NEW"
    assert updated.binding_version == "bind-NEW-2"


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
    save_session_run_binding_global(_binding("run-NEW", version="bind-NEW"))
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
    assert survived.binding_version == "bind-NEW"
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
