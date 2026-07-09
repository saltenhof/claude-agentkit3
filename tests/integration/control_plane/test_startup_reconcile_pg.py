"""Postgres integration tests for AG3-138 startup reconciliation + admin-abort.

Exercises the REAL Postgres control-plane store (K5 Postgres-only) through the
productive runtime / startup-hook paths -- NOT the injected fakes the unit tests
use:

* AC1 -- prepared orphaned ``claimed`` operations of THIS instance's own earlier
  incarnation are finalized by the pre-serve startup hook BEFORE the listener
  would serve, and the reconciliation runs against the genuine identity-fenced
  scan/finalize SQL.
* AC2 -- a foreign-identity orphan is NEVER touched by reconciliation.
* AC3 -- ``backend_instance_id`` is stable across boots; ``instance_incarnation``
  is strictly monotone at the real store.
* AC4 -- the ``operation_epoch`` CAS fence is enforced by the real finalize SQL.
* AC5 -- a partial write (engine writes persisted through the REAL dispatch path)
  routes an admin-abort into the explicit ``repair`` state, visible via the
  operation load surface.
* AC9 -- a failing reconciliation makes the pre-serve startup hook fail closed.
* AC10 -- a story in an open ``repair`` state mutation-locks a new dispatch, and the
  admin-abort repair-resolve service path productively lifts that lock (no deadlock).

The Postgres backend is auto-attached to every ``tests/integration`` item
(``tests/integration/conftest.py``); no explicit fixture parameter is needed.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

import pytest

from agentkit.backend.control_plane.instance_identity import (
    resolve_backend_instance_identity,
)
from agentkit.backend.control_plane.models import PhaseDispatchResult, PhaseMutationRequest
from agentkit.backend.control_plane.records import (
    BackendInstanceIdentityRecord,
    ControlPlaneOperationRecord,
)
from agentkit.backend.control_plane.repository import (
    BackendInstanceIdentityRepository,
    ControlPlaneRuntimeRepository,
)
from agentkit.backend.control_plane.runtime import ControlPlaneRuntimeService
from agentkit.backend.control_plane.startup_reconcile import (
    StartupReconciliationError,
    run_startup_reconciliation,
)
from agentkit.backend.control_plane_http.app import ControlPlaneApplication
from agentkit.backend.state_backend.operation_ledger import (
    claim_control_plane_operation_global,
    finalize_control_plane_operation_global,
    finalize_orphaned_control_plane_operation_global,
    load_control_plane_operation_global,
)
from agentkit.backend.state_backend.state_backend_connection_manager import (
    boot_backend_instance_identity_global,
    save_backend_instance_identity_global,
)
from agentkit.backend.state_backend.story_lifecycle_store import save_story_context_global
from agentkit.backend.story_context_manager.models import StoryContext
from agentkit.backend.story_context_manager.types import StoryMode, StoryType

if TYPE_CHECKING:
    from pathlib import Path

pytestmark = pytest.mark.integration


@pytest.fixture(autouse=True)
def _isolated_postgres(postgres_isolated_schema: object) -> None:
    """Bind the per-test isolated Postgres control-plane schema (K5 Postgres-only).

    ``tests/integration/control_plane/`` is not in the conftest Postgres
    auto-attach allow-list (its other tests are host-independent), so this module
    requests the isolation fixture explicitly for every test.
    """
    del postgres_isolated_schema


_T0 = datetime(2026, 7, 2, 10, 0, tzinfo=UTC)
_OWNER = "owner-00000000000000000000000000000000"


def _identity(instance_id: str, incarnation: int) -> BackendInstanceIdentityRecord:
    return BackendInstanceIdentityRecord(
        backend_instance_id=instance_id,
        instance_incarnation=incarnation,
        updated_at=_T0,
    )


def _claimed_op(
    op_id: str,
    *,
    backend_instance_id: str,
    incarnation: int,
    epoch: int = 1,
    claimed_at: datetime = _T0,
    story_id: str = "AG3-300",
    run_id: str | None = "run-1",
) -> ControlPlaneOperationRecord:
    return ControlPlaneOperationRecord(
        op_id=op_id,
        project_key="tenant-a",
        story_id=story_id,
        run_id=run_id,
        session_id="sess-1",
        operation_kind="phase_start",
        phase="implementation",
        status="claimed",
        response_payload={},
        created_at=claimed_at,
        updated_at=claimed_at,
        claimed_by=_OWNER,
        claimed_at=claimed_at,
        operation_epoch=epoch,
        backend_instance_id=backend_instance_id,
        instance_incarnation=incarnation,
        declared_serialization_scope=f"tenant-a:{story_id}",
    )


def _abort_request() -> object:
    from agentkit.backend.control_plane.models import AdminAbortRequest

    return AdminAbortRequest(
        session_id="admin-sess-1",
        principal_type="operator",
        reason="hung executor; operator decision",
    )


# --- AC3: backend_instance_id stable, instance_incarnation strictly monotone ---


def test_boot_identity_is_stable_and_incarnation_is_strictly_monotone() -> None:
    """AC3: the id is stable across boots; the incarnation increments by +1."""
    first = boot_backend_instance_identity_global("inst-candidate-1", _T0)
    # A DIFFERENT candidate on later boots is ignored -- the stored id wins.
    second = boot_backend_instance_identity_global("inst-candidate-IGNORED", _T0)
    third = resolve_backend_instance_identity(BackendInstanceIdentityRepository())

    assert first.backend_instance_id == "inst-candidate-1"
    assert second.backend_instance_id == "inst-candidate-1"
    assert third.backend_instance_id == "inst-candidate-1"
    assert (first.instance_incarnation, second.instance_incarnation) == (1, 2)
    assert third.instance_incarnation == 3


# --- AC1 / AC2: identity-fenced reconciliation against the real store ----------


def test_reconciliation_finalizes_own_earlier_incarnation_only() -> None:
    """AC1/AC2: own earlier-incarnation orphans -> failed; foreign untouched."""
    save_backend_instance_identity_global(_identity("inst-me", 1))
    # Own orphan from incarnation 1 (this boot is incarnation 2): reconcilable.
    assert claim_control_plane_operation_global(
        _claimed_op("op-own", backend_instance_id="inst-me", incarnation=1)
    )
    # Foreign identity: never touched by this instance's reconciliation.
    assert claim_control_plane_operation_global(
        _claimed_op(
            "op-foreign", backend_instance_id="inst-other", incarnation=1,
            story_id="AG3-301",
        )
    )

    outcome = run_startup_reconciliation(
        ControlPlaneRuntimeRepository(), _identity("inst-me", 2)
    )

    assert outcome.finalized_op_ids == ("op-own",)
    own = load_control_plane_operation_global("op-own")
    assert own is not None and own.status == "failed"
    assert own.claimed_by is None
    foreign = load_control_plane_operation_global("op-foreign")
    assert foreign is not None and foreign.status == "claimed", "foreign untouched"


def test_pre_serve_startup_hook_finalizes_orphans_before_serving() -> None:
    """AC1: the pre-serve startup hook reconciles orphans before the listener serves.

    A pre-seeded installation identity (incarnation 1) with an orphaned own-claim
    from that incarnation is finalized when the app's ``run_pre_serve_startup_hook``
    runs (which boots the identity to incarnation 2 and reconciles) -- proving the
    real wiring finalizes BEFORE the socket is bound (``serve_control_plane`` calls
    this hook before ``serve_forever``).
    """
    save_backend_instance_identity_global(_identity("known-backend", 1))
    assert claim_control_plane_operation_global(
        _claimed_op("op-hook-orphan", backend_instance_id="known-backend", incarnation=1)
    )

    application = ControlPlaneApplication()
    application.run_pre_serve_startup_hook()

    finalized = load_control_plane_operation_global("op-hook-orphan")
    assert finalized is not None
    assert finalized.status == "failed", "the orphan is finalized by the startup hook"


def test_pre_serve_startup_hook_is_fail_closed_on_reconcile_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AC9: a failing reconciliation makes the pre-serve startup hook fail closed."""

    def _boom(*_args: object, **_kwargs: object) -> object:
        raise StartupReconciliationError("simulated reconcile failure")

    monkeypatch.setattr(
        "agentkit.backend.control_plane.startup_reconcile.run_startup_reconciliation",
        _boom,
    )
    application = ControlPlaneApplication()
    with pytest.raises(StartupReconciliationError):
        application.run_pre_serve_startup_hook()


# --- AC4: operation_epoch CAS fence at the real finalize SQL -------------------


def test_operation_epoch_cas_fence_at_real_store() -> None:
    """AC4: a finalize carrying a stale ``operation_epoch`` is fenced out (0 rows).

    A claim at epoch 1 finalizes when the caller presents epoch 1. But when the
    stored epoch has advanced (as an admin-abort would bump it), a finalize still
    presenting the STALE epoch 1 matches zero rows -- deterministic, no second
    result (``operation_finalize_requires_cas_on_operation_epoch``).
    """
    from dataclasses import replace

    # Matching epoch -> finalize applies.
    assert claim_control_plane_operation_global(
        _claimed_op("op-epoch-ok", backend_instance_id="inst-me", incarnation=1, epoch=1)
    )
    terminal_ok = replace(
        _claimed_op("op-epoch-ok", backend_instance_id="inst-me", incarnation=1),
        status="committed",
    )
    assert (
        finalize_control_plane_operation_global(
            terminal_ok,
            owner_token=_OWNER,
            owner_claimed_at=_T0.isoformat(),
            owner_operation_epoch=1,
        )
        is True
    )

    # Stale epoch -> fenced out. Seed a claim whose stored epoch is 2.
    assert claim_control_plane_operation_global(
        _claimed_op("op-epoch-stale", backend_instance_id="inst-me", incarnation=1, epoch=2)
    )
    terminal_stale = replace(
        _claimed_op("op-epoch-stale", backend_instance_id="inst-me", incarnation=1),
        status="committed",
    )
    assert (
        finalize_control_plane_operation_global(
            terminal_stale,
            owner_token=_OWNER,
            owner_claimed_at=_T0.isoformat(),
            owner_operation_epoch=1,  # STALE: stored epoch is 2
        )
        is False
    ), "a stale-epoch finalize must be fenced out"
    still = load_control_plane_operation_global("op-epoch-stale")
    assert still is not None and still.status == "claimed"


def test_orphan_finalize_operation_epoch_cas_fence_at_real_store() -> None:
    """AG3-138 P3: the startup orphan finalize is fenced on the scanned ``operation_epoch``.

    The startup-reconciliation orphan finalize must apply the SAME
    ``operation_epoch`` CAS fence as the normal finalize
    (``operation_finalize_requires_cas_on_operation_epoch``): a finalize presenting
    the epoch OBSERVED BY THE SCAN applies, but one presenting a STALE epoch (the row
    moved between scan and finalize) matches zero rows and is a deterministic no-op --
    so a late finalize can never stamp a terminal status over a row that already
    advanced under the same still-``claimed`` identity.
    """
    save_backend_instance_identity_global(_identity("inst-me", 1))
    assert claim_control_plane_operation_global(
        _claimed_op(
            "op-orphan-epoch",
            backend_instance_id="inst-me",
            incarnation=1,
            epoch=2,
            story_id="AG3-360",
        )
    )

    # Stale epoch (scan thought epoch was 1, stored is 2) -> fenced out, no-op.
    assert (
        finalize_orphaned_control_plane_operation_global(
            op_id="op-orphan-epoch",
            backend_instance_id="inst-me",
            status="failed",
            response_payload={"status": "failed", "op_id": "op-orphan-epoch"},
            now=_T0,
            owner_operation_epoch=1,
        )
        is False
    ), "a stale-epoch orphan finalize must be fenced out"
    still = load_control_plane_operation_global("op-orphan-epoch")
    assert still is not None and still.status == "claimed"

    # Matching epoch (scan observed 2, stored is 2) -> finalize applies.
    assert (
        finalize_orphaned_control_plane_operation_global(
            op_id="op-orphan-epoch",
            backend_instance_id="inst-me",
            status="failed",
            response_payload={"status": "failed", "op_id": "op-orphan-epoch"},
            now=_T0,
            owner_operation_epoch=2,
        )
        is True
    )
    finalized = load_control_plane_operation_global("op-orphan-epoch")
    assert finalized is not None and finalized.status == "failed"
    assert finalized.operation_epoch == 3  # bumped past the scanned epoch


# --- AC5 / AC10: partial write via the real dispatch path -> repair + lock --------


class _EngineWritingDispatcher:
    """A dispatcher that persists a real ``flow_executions`` engine write mid-dispatch.

    Mirrors ``engine.run_phase`` persisting engine state in its OWN transaction
    during dispatch (BEFORE the control-plane finalize), so the partial write fixture
    arises through the REAL dispatch path -- not a hand-fabricated pipeline state.
    """

    def __init__(self, *, story_id: str, run_id: str, started_at: datetime) -> None:
        self._story_id = story_id
        self._run_id = run_id
        self._started_at = started_at

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
        from agentkit.backend.state_backend.postgres_store import _connect_global

        with _connect_global() as conn:
            conn.execute(
                """
                INSERT INTO flow_executions (
                    story_id, project_key, run_id, flow_id, level, owner,
                    status, attempt_no, started_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT (story_id) DO NOTHING
                """,
                (
                    self._story_id,
                    "tenant-a",
                    self._run_id,
                    "flow-1",
                    "story",
                    "engine",
                    "running",
                    1,
                    self._started_at.isoformat(),
                ),
            )
        return PhaseDispatchResult(
            phase=phase,
            status="phase_completed",
            reaction="advance",
            dispatched=True,
            next_phase="implementation",
        )


def _seed_story_context(tmp_path: Path, story_id: str) -> None:
    project_root = tmp_path / "tenant-a"
    (project_root / "stories" / story_id).mkdir(parents=True, exist_ok=True)
    save_story_context_global(
        None,
        StoryContext(
            project_key="tenant-a",
            story_id=story_id,
            story_type=StoryType.IMPLEMENTATION,
            execution_route=StoryMode.EXECUTION,
            project_root=project_root,
        ),
    )


def test_admin_abort_partial_write_goes_to_repair_and_locks_story(
    tmp_path: Path,
) -> None:
    """AC5/AC10: a partial write admin-abort -> ``repair``; the story is mutation-locked.

    1. A REAL ``start_phase`` dispatch persists a ``flow_executions`` engine write
       for the run (through the dispatch path).
    2. An orphaned in-flight claim of the run (claimed BEFORE that write) is
       admin-aborted -> the deterministic partial write detection routes it to the
       explicit ``repair`` state (visible via the operation load surface, AC5).
    3. A new mutating dispatch against the now-in-repair story is fail-closed
       ``rejected`` at the operations layer (AC10).
    4. The open repair is productively resolved via the REAL admin-abort service path
       (repair -> ``resolved``), lifting the story-scoped mutation lock (AC10 exit).
    5. A mutating start for the SAME run/owner is re-admitted -- proving there is a
       productive way out of repair (no permanent deadlock; E1/E2). AG3-142: the
       rightful owner's SAME run_id/session_id is used deliberately (not a brand
       new run_id) -- the story's active ``run_ownership_records`` row is still
       ``run_id`` (from step 1) at this point, and AG3-142's fence now correctly
       enforces ``at_most_one_active_ownership_per_story`` (FK-56 §56.8a): a
       genuinely NEW run_id for the SAME story is fenced OUT (``RUN_MISMATCH``)
       until AG3-149 wires the disown/reset behaviour that retires the old
       active record. That is a NEW, correct, fail-closed guarantee AG3-142
       adds, not a repair-lock concern -- proven separately in
       ``test_run_mismatch_fences_out_before_the_dispatcher_is_ever_consulted``
       (``tests/unit/control_plane/test_runtime.py``).
    """
    story_id = "AG3-350"
    run_id = "run-350"
    _seed_story_context(tmp_path, story_id)
    identity = boot_backend_instance_identity_global("inst-abort", _T0)

    # (1) real dispatch persists an engine write at T0+2min.
    engine_write_at = _T0 + timedelta(minutes=2)
    dispatcher = _EngineWritingDispatcher(
        story_id=story_id, run_id=run_id, started_at=engine_write_at
    )
    service = ControlPlaneRuntimeService(
        phase_dispatcher=dispatcher,  # type: ignore[arg-type]
        now_fn=lambda: _T0,
        instance_identity=identity,
    )
    started = service.start_phase(
        run_id=run_id,
        phase="setup",
        request=PhaseMutationRequest(
            project_key="tenant-a",
            story_id=story_id,
            session_id="sess-1",
            principal_type="orchestrator",
            worktree_roots=["T:/worktrees/ag3-350"],
            op_id="op-350-start",
        ),
    )
    assert started.status == "committed"

    # (2) an orphaned claim of the run (claimed BEFORE the engine write) is aborted.
    assert claim_control_plane_operation_global(
        _claimed_op(
            "op-350-crash",
            backend_instance_id="inst-abort",
            incarnation=identity.instance_incarnation,
            claimed_at=_T0,
            story_id=story_id,
            run_id=run_id,
        )
    )
    abort_service = ControlPlaneRuntimeService(
        now_fn=lambda: _T0 + timedelta(minutes=5),
        instance_identity=identity,
    )
    result = abort_service.admin_abort_inflight_operation("op-350-crash", _abort_request())

    assert result.status == "repair", "a partial write abort enters the explicit repair state"
    stored = load_control_plane_operation_global("op-350-crash")
    assert stored is not None and stored.status == "repair", "repair visible via GET"

    # (3) a new mutating dispatch against the in-repair story is fail-closed rejected.
    locked = service.start_phase(
        run_id="run-350-new",
        phase="setup",
        request=PhaseMutationRequest(
            project_key="tenant-a",
            story_id=story_id,
            session_id="sess-1",
            principal_type="orchestrator",
            worktree_roots=["T:/worktrees/ag3-350"],
            op_id="op-350-blocked",
        ),
    )
    assert locked.status == "rejected", "the story is mutation-locked while in repair"
    assert load_control_plane_operation_global("op-350-blocked") is None

    # (4) resolve the repair via the REAL service path (admin-abort of the repair op)
    #     -> 'resolved'; this is the productive exit from the AC10 lock (no fake edit).
    resolve_service = ControlPlaneRuntimeService(
        now_fn=lambda: _T0 + timedelta(minutes=6),
        instance_identity=identity,
    )
    resolved = resolve_service.admin_abort_inflight_operation(
        "op-350-crash", _abort_request()
    )
    assert resolved.status == "resolved", "the open repair is productively closed out"
    reloaded = load_control_plane_operation_global("op-350-crash")
    assert reloaded is not None and reloaded.status == "resolved"

    # (5) the story is no longer repair-locked: the RIGHTFUL owner (the SAME
    #     run_id/session_id whose active ownership record was minted in step 1)
    #     is re-admitted -- proving the lifted lock, not ownership, was step
    #     (3)'s blocker. AG3-142: a genuinely NEW run_id is deliberately NOT
    #     used here (see the docstring forward-dependency note on AG3-149).
    unlocked = service.start_phase(
        run_id=run_id,
        phase="setup",
        request=PhaseMutationRequest(
            project_key="tenant-a",
            story_id=story_id,
            session_id="sess-1",
            principal_type="orchestrator",
            worktree_roots=["T:/worktrees/ag3-350"],
            op_id="op-350-after-repair",
        ),
    )
    assert unlocked.status == "committed", "repair resolved -> mutations allowed again"
    assert load_control_plane_operation_global("op-350-after-repair") is not None
