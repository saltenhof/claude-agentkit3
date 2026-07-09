"""Integration: AG3-142 ownership-fencing row functions against REAL Postgres.

Exercises the transactional AT/T mechanics that only a real Postgres can prove:

* AC1 -- the setup-start's ``run_ownership_records`` INSERT is atomic with the
  claim-CAS finalize (``finalize_control_plane_start_phase_global``): a winner's
  finalize commits BOTH the terminal op and the new active record together; a
  CAS-losing finalize (the claim was resolved by a concurrent admin-abort in the
  meantime -- the exact "late executor" scenario AG3-138 already established a
  precedent for) writes NEITHER the op NOR the ownership record.
* AC3 -- a historical (non-``active``) record is never returned by
  ``load_active_run_ownership_record_global`` (audit-only,
  ``historical_ownership_records_are_never_admission_evidence``).
* AC4/AC5 (no TOCTOU) -- the commit-time fence
  (``_enforce_ownership_fence_row``, consumed via ``expected_ownership_epoch``)
  re-reads the CURRENT ``run_ownership_records`` row inside the SAME
  transaction as the commit, not a value cached at an earlier "admission"
  moment: a caller whose observed ``(run_id, owner_session_id,
  ownership_epoch)`` snapshot has since gone stale (the row was directly
  mutated -- the sanctioned AG3-137 single-writer surface, simulating a
  not-yet-built AG3-148 transfer) is rejected with NO state written, even
  though nothing about the CALLER's own request changed.

The ``postgres_isolated_schema`` fixture is auto-attached to every
``/integration/state_backend/`` item (``tests/integration/conftest.py``).

Resource note (parallel-agent budget): the shared test Postgres pool is
capped at ONE physical connection per worker (``AGENTKIT_STATE_POOL_MAX_SIZE``
default 1). These tests therefore prove the fence's transactional correctness
via SEQUENTIAL simulation on a single connection -- exactly the pattern the
pre-existing claim-CAS "concurrency" tests in
``tests/contract/state_backend/test_control_plane_operation_store_postgres.py``
already use (``test_atomic_claim_winner_then_loser_against_real_store`` et
al.), never real multi-connection threading. The full mutual-exclusion
guarantee of the ``SELECT ... FOR UPDATE`` row lock against a GENUINELY
concurrent second physical connection is therefore not exercised here (see
the story handover's WARNING); what IS proven, deterministically, is the
functionally load-bearing property: the fence reads the row's CURRENT state
at commit time, not a value cached earlier in the call.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from agentkit.backend.control_plane.ownership import (
    OwnershipAcquisition,
    OwnershipStatus,
)
from agentkit.backend.control_plane.records import (
    BindingDeleteScope,
    ControlPlaneOperationRecord,
    RunOwnershipRecord,
)
from agentkit.backend.exceptions import OwnershipFenceViolationError
from agentkit.backend.state_backend import postgres_store
from agentkit.backend.state_backend.operation_ledger import (
    admin_abort_control_plane_operation_global,
    claim_control_plane_operation_global,
    commit_control_plane_operation_with_side_effects_global,
    finalize_control_plane_start_phase_global,
    load_control_plane_operation_global,
)
from agentkit.backend.state_backend.story_lifecycle_store import (
    insert_run_ownership_record_global,
    load_active_run_ownership_record_global,
    load_run_ownership_record_global,
)

pytestmark = pytest.mark.integration

_NOW = datetime(2026, 7, 4, 10, 0, tzinfo=UTC)


def _op(
    op_id: str,
    *,
    project_key: str = "tenant-a",
    story_id: str = "AG3-600",
    run_id: str = "run-600",
    session_id: str = "sess-A",
    status: str = "claimed",
    claimed_by: str | None = None,
    claimed_at: datetime | None = None,
) -> ControlPlaneOperationRecord:
    return ControlPlaneOperationRecord(
        op_id=op_id,
        project_key=project_key,
        story_id=story_id,
        run_id=run_id,
        session_id=session_id,
        operation_kind="phase_start",
        phase="setup",
        status=status,
        response_payload={},
        created_at=_NOW,
        updated_at=_NOW,
        claimed_by=claimed_by,
        claimed_at=claimed_at,
    )


def _ownership_record(
    *,
    project_key: str = "tenant-a",
    story_id: str = "AG3-600",
    run_id: str = "run-600",
    owner_session_id: str = "sess-A",
    epoch: int = 1,
    status: OwnershipStatus = OwnershipStatus.ACTIVE,
    acquired_via: OwnershipAcquisition = OwnershipAcquisition.SETUP,
) -> RunOwnershipRecord:
    return RunOwnershipRecord(
        project_key=project_key,
        story_id=story_id,
        run_id=run_id,
        owner_session_id=owner_session_id,
        ownership_epoch=epoch,
        status=status,
        acquired_via=acquired_via,
        acquired_at=_NOW,
        audit_ref="audit:x",
    )


def _raw_update_ownership_row(
    *,
    project_key: str,
    story_id: str,
    new_owner_session_id: str,
    new_ownership_epoch: int,
) -> None:
    """Directly mutate the story's active ownership row (test-only).

    AG3-148 (the productive transfer confirm CAS) does not exist yet; this
    mirrors the story's own sanctioned pattern (the ``transferred`` state
    arises only in tests, via the sanctioned AG3-137 write surface) by
    touching the table directly through the SAME global connection the
    productive store uses -- never a second physical connection, never a new
    production write primitive.
    """
    with postgres_store._connect_global() as conn:  # noqa: SLF001 -- sanctioned test-only direct touch
        conn.execute(
            """
            UPDATE run_ownership_records
            SET owner_session_id = ?, ownership_epoch = ?
            WHERE project_key = ? AND story_id = ? AND status = 'active'
            """,
            (new_owner_session_id, new_ownership_epoch, project_key, story_id),
        )


# ---------------------------------------------------------------------------
# AC1: setup-start record INSERT atomic with the claim-CAS finalize
# ---------------------------------------------------------------------------


def test_winner_finalize_atomically_commits_op_and_ownership_record() -> None:
    """AC1 positive: a winning claim-CAS finalize commits the terminal op AND
    the NEW active ``run_ownership_records`` row together, in ONE transaction.
    """
    op_id = "op-pg-fence-winner"
    assert claim_control_plane_operation_global(
        _op(op_id, claimed_by="owner-A", claimed_at=_NOW)
    ) is True

    applied = finalize_control_plane_start_phase_global(
        _op(op_id, status="committed"),
        owner_token="owner-A",
        binding=None,
        locks=(),
        events=(),
        ownership_record_to_insert=_ownership_record(),
    )

    assert applied is True
    stored_op = load_control_plane_operation_global(op_id)
    assert stored_op is not None
    assert stored_op.status == "committed"
    active = load_active_run_ownership_record_global("tenant-a", "AG3-600")
    assert active is not None
    assert active.run_id == "run-600"
    assert active.owner_session_id == "sess-A"
    assert active.ownership_epoch == 1
    assert active.acquired_via == OwnershipAcquisition.SETUP


def test_finalize_cas_loser_writes_no_ownership_record() -> None:
    """AC1 negative (the crux): a claim-CAS LOSER writes NEITHER the terminal
    op NOR the ownership record -- mirrors the AG3-138 precedent
    (``test_late_finalize_after_admin_abort_writes_no_side_effects_real_store``)
    extended with the AG3-142 ownership INSERT: A's claim is admin-aborted
    (the AG3-138 end-way for a stuck/late claim) before A's finalize runs; A's
    CAS then affects ZERO rows, so the WHOLE transaction -- including the
    ownership INSERT -- rolls back atomically.
    """
    op_id = "op-pg-fence-loser"
    assert claim_control_plane_operation_global(
        _op(op_id, claimed_by="owner-A", claimed_at=_NOW)
    ) is True
    abort_payload: dict[str, object] = {
        "status": "aborted",
        "op_id": op_id,
        "operation_kind": "phase_start",
        "run_id": "run-600",
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
            now=_NOW + timedelta(minutes=10),
        )
        is True
    )

    # A (the loser) now attempts its OWN atomic finalize, INCLUDING the
    # ownership-record insert it planned before the abort raced it.
    applied = finalize_control_plane_start_phase_global(
        _op(op_id, status="committed"),
        owner_token="owner-A",
        binding=None,
        locks=(),
        events=(),
        ownership_record_to_insert=_ownership_record(),
    )

    assert applied is False, "the loser's CAS finalize must not apply"
    # NO ownership record was materialized by the loser.
    assert load_active_run_ownership_record_global("tenant-a", "AG3-600") is None
    assert load_run_ownership_record_global("tenant-a", "AG3-600", "run-600") is None
    # The aborted terminal row is intact (untouched by the loser).
    stored = load_control_plane_operation_global(op_id)
    assert stored is not None
    assert stored.status == "aborted"


# ---------------------------------------------------------------------------
# AC3: a historical record is audit-only, never admission evidence
# ---------------------------------------------------------------------------


def test_historical_record_never_returned_as_active() -> None:
    """AC3: a record with any status other than 'active' is never returned by
    the active-record loader (the SOLE admission source consumed by the
    runtime's fence) -- prepared via the sanctioned AG3-137 single-writer
    surface (a direct insert, exactly how a real disown/reset writer would
    produce one; AG3-137 fixture-precedent).
    """
    insert_run_ownership_record_global(
        _ownership_record(story_id="AG3-601", run_id="run-old", status=OwnershipStatus.ENDED)
    )

    assert load_active_run_ownership_record_global("tenant-a", "AG3-601") is None
    # The historical record is still readable by direct identity (audit trail).
    historical = load_run_ownership_record_global("tenant-a", "AG3-601", "run-old")
    assert historical is not None
    assert historical.status is OwnershipStatus.ENDED


# ---------------------------------------------------------------------------
# AC4/AC5 (no TOCTOU): the commit-time fence reads CURRENT state, not a
# value cached earlier in the call
# ---------------------------------------------------------------------------


def test_commit_time_fence_rejects_wrong_owner_and_writes_nothing() -> None:
    """AC4 (owner mismatch, complete/fail/closure path): the fence rejects a
    ``expected_ownership_epoch`` snapshot whose owner no longer matches the
    row's CURRENT owner -- nothing committed, the collision-gated upsert is
    rolled back too.
    """
    insert_run_ownership_record_global(
        _ownership_record(story_id="AG3-602", run_id="run-602", owner_session_id="sess-REAL-OWNER")
    )
    op_id = "op-pg-fence-wrong-owner"

    with pytest.raises(OwnershipFenceViolationError) as excinfo:
        commit_control_plane_operation_with_side_effects_global(
            _op(
                op_id,
                story_id="AG3-602",
                run_id="run-602",
                session_id="sess-IMPOSTOR",
                status="committed",
            ),
            binding_to_save=None,
            binding_to_delete=None,
            locks=(),
            events=(),
            expected_ownership_epoch=1,
        )

    assert excinfo.value.detail["current_owner_session_id"] == "sess-REAL-OWNER"
    assert excinfo.value.detail["current_ownership_epoch"] == 1
    # NOTHING committed: no op row for this attempt.
    assert load_control_plane_operation_global(op_id) is None
    # The real owner's record is untouched.
    active = load_active_run_ownership_record_global("tenant-a", "AG3-602")
    assert active is not None
    assert active.owner_session_id == "sess-REAL-OWNER"


def test_commit_time_fence_rejects_stale_epoch_and_writes_nothing() -> None:
    """AC4 (stale epoch, SAME owner_session_id): even when the caller's
    session_id still equals the row's CURRENT owner, a mismatched
    ``ownership_epoch`` (the row moved on since the caller's own admission
    check) fences the commit -- FK-56 §56.8a fences on BOTH
    ``owner_session_id`` AND ``ownership_epoch``,
    ``story_execution_mutations_require_current_ownership_epoch``.
    """
    insert_run_ownership_record_global(
        _ownership_record(story_id="AG3-603", run_id="run-603", owner_session_id="sess-A", epoch=1)
    )
    op_id = "op-pg-fence-stale-epoch"

    with pytest.raises(OwnershipFenceViolationError) as excinfo:
        commit_control_plane_operation_with_side_effects_global(
            _op(
                op_id,
                story_id="AG3-603",
                run_id="run-603",
                session_id="sess-A",
                status="committed",
            ),
            binding_to_save=None,
            binding_to_delete=None,
            locks=(),
            events=(),
            # The caller observed epoch=1 at admission time, but is committing
            # against a claimed epoch=2 -- fences even though owner matches.
            expected_ownership_epoch=2,
        )

    assert excinfo.value.detail["current_owner_session_id"] == "sess-A"
    assert excinfo.value.detail["current_ownership_epoch"] == 1
    assert load_control_plane_operation_global(op_id) is None


def test_commit_time_fence_reads_current_state_not_a_stale_admission_snapshot() -> None:
    """AC4/AC5 (no TOCTOU): the fence reads the row's state AT COMMIT TIME, not
    a value cached earlier -- proves the exact property the "dispatch races
    finalize" scenario depends on. A caller's early admission check observed
    (owner=sess-A, epoch=1); by the time its commit runs, the row has been
    directly mutated (simulating a not-yet-built AG3-148 transfer landing in
    the window between admission and commit) to (owner=sess-HIJACK, epoch=2).
    The commit -- which still presents the STALE (sess-A, epoch=1) snapshot --
    must be rejected, and the run's op/side effects must be untouched.
    """
    insert_run_ownership_record_global(
        _ownership_record(story_id="AG3-604", run_id="run-604", owner_session_id="sess-A", epoch=1)
    )
    # Simulate the race: something changes the row AFTER the caller's own
    # admission check but BEFORE its commit reaches the fence.
    _raw_update_ownership_row(
        project_key="tenant-a",
        story_id="AG3-604",
        new_owner_session_id="sess-HIJACK",
        new_ownership_epoch=2,
    )
    op_id = "op-pg-fence-toctou"

    with pytest.raises(OwnershipFenceViolationError) as excinfo:
        commit_control_plane_operation_with_side_effects_global(
            _op(
                op_id,
                story_id="AG3-604",
                run_id="run-604",
                session_id="sess-A",
                status="committed",
            ),
            binding_to_save=None,
            binding_to_delete=None,
            locks=(),
            events=(),
            expected_ownership_epoch=1,  # the STALE, pre-race snapshot
        )

    assert excinfo.value.detail["current_owner_session_id"] == "sess-HIJACK"
    assert excinfo.value.detail["current_ownership_epoch"] == 2
    assert load_control_plane_operation_global(op_id) is None
    active = load_active_run_ownership_record_global("tenant-a", "AG3-604")
    assert active is not None
    assert active.owner_session_id == "sess-HIJACK"
    assert active.ownership_epoch == 2


def test_commit_time_fence_rejects_when_no_active_record_exists_at_all() -> None:
    """Fail-closed: the fence rejects (with an empty ``detail``) when the
    story has no active ownership record at all -- never confused with a
    genuine transfer (which always carries a ``current_owner_session_id``).
    """
    op_id = "op-pg-fence-no-record"

    with pytest.raises(OwnershipFenceViolationError) as excinfo:
        commit_control_plane_operation_with_side_effects_global(
            _op(
                op_id,
                story_id="AG3-605",
                run_id="run-605",
                session_id="sess-A",
                status="committed",
            ),
            binding_to_save=None,
            binding_to_delete=None,
            locks=(),
            events=(),
            expected_ownership_epoch=1,
        )

    assert excinfo.value.detail["current_owner_session_id"] is None
    assert excinfo.value.detail["current_ownership_epoch"] is None
    assert load_control_plane_operation_global(op_id) is None


def test_finalize_start_phase_commit_time_fence_also_applies_to_resume_shape() -> None:
    """AC4 path (resume, via ``finalize_control_plane_start_phase_global``
    with NO ``ownership_row_to_insert``): the SAME row function ``resume_phase``
    reuses for its ownership-CAS finalize also fences on
    ``expected_ownership_epoch`` -- a stale resume writes nothing.
    """
    insert_run_ownership_record_global(
        _ownership_record(story_id="AG3-606", run_id="run-606", owner_session_id="sess-A", epoch=1)
    )
    _raw_update_ownership_row(
        project_key="tenant-a",
        story_id="AG3-606",
        new_owner_session_id="sess-HIJACK",
        new_ownership_epoch=2,
    )
    op_id = "op-pg-fence-resume"
    assert claim_control_plane_operation_global(
        _op(op_id, story_id="AG3-606", run_id="run-606", claimed_by="owner-A", claimed_at=_NOW)
    ) is True

    with pytest.raises(OwnershipFenceViolationError):
        finalize_control_plane_start_phase_global(
            _op(op_id, story_id="AG3-606", run_id="run-606", status="committed"),
            owner_token="owner-A",
            binding=None,
            locks=(),
            events=(),
            expected_ownership_epoch=1,  # the stale, pre-race snapshot
        )

    # The claim-CAS itself is rolled back too (same transaction): the op row
    # is still 'claimed', never a spurious 'committed'.
    stored = load_control_plane_operation_global(op_id)
    assert stored is not None
    assert stored.status == "claimed"


def test_binding_delete_scope_ignored_when_fence_rejects_first() -> None:
    """The fence runs BEFORE the binding delete (closure shape): a rejected
    fence means the binding delete is never even attempted, let alone
    committed.
    """
    insert_run_ownership_record_global(
        _ownership_record(story_id="AG3-607", run_id="run-607", owner_session_id="sess-REAL")
    )
    op_id = "op-pg-fence-closure-shape"

    with pytest.raises(OwnershipFenceViolationError):
        commit_control_plane_operation_with_side_effects_global(
            _op(
                op_id,
                story_id="AG3-607",
                run_id="run-607",
                session_id="sess-IMPOSTOR",
                status="committed",
            ),
            binding_to_save=None,
            binding_to_delete=BindingDeleteScope(
                session_id="sess-IMPOSTOR",
                project_key="tenant-a",
                story_id="AG3-607",
                run_id="run-607",
            ),
            locks=(),
            events=(),
            expected_ownership_epoch=1,
        )

    assert load_control_plane_operation_global(op_id) is None
