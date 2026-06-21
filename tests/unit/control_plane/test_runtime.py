from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
from pydantic import ValidationError

from agentkit.backend.control_plane.models import (
    ClosureCompleteRequest,
    ControlPlaneMutationResult,
    PhaseDispatchResult,
    PhaseMutationRequest,
    ProjectEdgeSyncRequest,
)
from agentkit.backend.control_plane.records import (
    BindingDeleteScope,
    ControlPlaneOperationRecord,
    SessionRunBindingRecord,
)
from agentkit.backend.control_plane.repository import ControlPlaneRuntimeRepository
from agentkit.backend.control_plane.runtime import ControlPlaneRuntimeService
from agentkit.backend.core_types import StoryMode
from agentkit.backend.story_context_manager.models import StoryContext
from agentkit.backend.story_context_manager.story_model import WireStoryMode
from agentkit.backend.story_context_manager.types import StoryType

if TYPE_CHECKING:
    from agentkit.backend.governance.guard_system.records import StoryExecutionLockRecord
    from agentkit.backend.telemetry.contract.records import ExecutionEventRecord


class _RepoState:
    def __init__(self) -> None:
        self.operations: dict[str, ControlPlaneOperationRecord] = {}
        self.bindings: dict[str, SessionRunBindingRecord] = {}
        self.locks: dict[tuple[str, str, str, str], StoryExecutionLockRecord] = {}
        self.events: list[ExecutionEventRecord] = []
        #: Authoritative server-side StoryContext store keyed by
        #: ``(project_key, story_id)``. Empty => unresolvable (fail-closed).
        self.story_contexts: dict[tuple[str, str], StoryContext] = {}


class _FakeOps:
    """In-memory control-plane operation/claim fakes (leased CAS protocol).

    Encapsulates the operation-lifecycle behaviors so ``_repository`` stays a thin
    wiring function (keeps cyclomatic complexity bounded; the leased-claim CAS
    semantics live here next to the state they mutate).
    """

    def __init__(self, state: _RepoState) -> None:
        self._state = state

    def claim(self, record: ControlPlaneOperationRecord) -> bool:
        # Atomic insert-if-absent: win iff the op_id is not already stored.
        if record.op_id in self._state.operations:
            return False
        self._state.operations[record.op_id] = record
        return True

    def takeover(
        self,
        record: ControlPlaneOperationRecord,
        *,
        observed_claimed_by: str | None,
        observed_claimed_at: str | None,
    ) -> bool:
        # CAS: re-stamp the lease iff the row is still the exact observed claim.
        # ERROR-2 (AG3-054): the real store matches against the RAW ``claimed_at``
        # TEXT column, so the fake compares the observed raw value against the
        # stored record's raw text (its ``claimed_at_raw`` round-trip), NOT the
        # normalized datetime. This makes the fake catch a raw-vs-normalized
        # mismatch instead of silently comparing aware datetimes.
        existing = self._state.operations.get(record.op_id)
        if (
            existing is None
            or existing.status != "claimed"
            or existing.claimed_by != observed_claimed_by
            or _stored_claimed_at_raw(existing) != observed_claimed_at
        ):
            return False
        self._state.operations[record.op_id] = record
        return True

    def _still_owned(
        self,
        record: ControlPlaneOperationRecord,
        owner_token: str,
        owner_claimed_at: str | None = None,
    ) -> bool:
        # WARNING-4 (#4): the CAS scopes to BOTH owner token AND lease epoch when
        # the epoch is given. The fake compares the observed raw epoch against the
        # stored record's raw text (mirroring the store's raw-column CAS).
        existing = self._state.operations.get(record.op_id)
        if (
            existing is None
            or existing.status != "claimed"
            or existing.claimed_by != owner_token
        ):
            return False
        if owner_claimed_at is not None:
            return _stored_claimed_at_raw(existing) == owner_claimed_at
        return True

    def finalize(
        self,
        record: ControlPlaneOperationRecord,
        *,
        owner_token: str,
        owner_claimed_at: str | None = None,
    ) -> bool:
        # Ownership-scoped terminal write: apply iff still claimed by owner_token
        # (and lease epoch when given, #4).
        if not self._still_owned(record, owner_token, owner_claimed_at):
            return False
        self._state.operations[record.op_id] = record
        return True

    def finalize_start_phase(
        self,
        record: ControlPlaneOperationRecord,
        *,
        owner_token: str,
        owner_claimed_at: str | None = None,
        binding: SessionRunBindingRecord | None,
        locks: tuple[StoryExecutionLockRecord, ...],
        events: tuple[ExecutionEventRecord, ...],
    ) -> bool:
        # ERROR-1 (#1): ownership CAS finalize + side-effect materialization in ONE
        # atomic step. Apply ONLY if still claimed by owner_token (and lease epoch
        # when given, #4); otherwise write NOTHING.
        if not self._still_owned(record, owner_token, owner_claimed_at):
            return False
        # AG3-054 run-scoping: the binding INSERT is run-scoped at the real store
        # (raises if the session is bound to a DIFFERENT run). Mirror it so the
        # fake catches a foreign-run overwrite and rolls back (raise BEFORE any
        # state mutation -> no orphan op/binding/lock/event).
        if binding is not None:
            _fake_run_scoped_save_binding(self._state, binding)
        self._state.operations[record.op_id] = record
        if binding is not None:
            self._state.bindings[binding.session_id] = binding
        for lock in locks:
            self._state.locks[
                (lock.project_key, lock.story_id, lock.run_id, lock.lock_type)
            ] = lock
        self._state.events.extend(events)
        return True

    def commit_with_side_effects(
        self,
        record: ControlPlaneOperationRecord,
        *,
        binding_to_save: SessionRunBindingRecord | None,
        binding_to_delete: BindingDeleteScope | None,
        locks: tuple[StoryExecutionLockRecord, ...],
        events: tuple[ExecutionEventRecord, ...],
    ) -> None:
        # ERROR-2 (#2): the conditional op-row upsert (collision gate FIRST) and the
        # mutation's side effects apply ATOMICALLY. Mirrors the real store: a LIVE
        # ``claimed`` row makes the op-row upsert raise
        # ``ControlPlaneClaimCollisionError`` BEFORE any side effect is applied, so a
        # collision leaves NO orphan binding/lock/event and the live claim intact.
        from agentkit.backend.exceptions import ControlPlaneClaimCollisionError

        existing = self._state.operations.get(record.op_id)
        if existing is not None and existing.status == "claimed":
            raise ControlPlaneClaimCollisionError(
                f"op_id {record.op_id!r} is held by a live 'claimed' lease "
                "(fake store, AG3-054 ERROR-2 atomic commit)",
            )
        # AG3-054 run-scoping: the binding SAVE/DELETE are run-scoped at the real
        # store. Validate BEFORE any mutation so a foreign-run binding raises and the
        # whole "transaction" rolls back (no orphan op/binding/lock/event), mirroring
        # the store's atomicity.
        if binding_to_save is not None:
            _fake_run_scoped_save_binding(self._state, binding_to_save)
        if binding_to_delete is not None:
            _fake_run_scoped_delete_binding(self._state, binding_to_delete)
        # Collision gate passed -> apply the terminal op AND all side effects.
        self._state.operations[record.op_id] = record
        if binding_to_save is not None:
            self._state.bindings[binding_to_save.session_id] = binding_to_save
        for lock in locks:
            self._state.locks[
                (lock.project_key, lock.story_id, lock.run_id, lock.lock_type)
            ] = lock
        self._state.events.extend(events)

    def release(
        self,
        op_id: str,
        *,
        owner_token: str,
        owner_claimed_at: str | None = None,
    ) -> None:
        # Ownership-scoped release: delete iff still claimed by owner_token (and
        # lease epoch when given, #4).
        existing = self._state.operations.get(op_id)
        if existing is None or existing.status != "claimed":
            return
        if existing.claimed_by != owner_token:
            return
        if (
            owner_claimed_at is not None
            and _stored_claimed_at_raw(existing) != owner_claimed_at
        ):
            return
        self._state.operations.pop(op_id, None)

    def has_committed_for_run(
        self,
        project_key: str,
        story_id: str,
        run_id: str,
    ) -> bool:
        # ERROR-3 (#3): admission evidence must prove an admitted START -- a
        # committed setup ``phase_start`` for THIS exact run. A committed
        # ``phase_complete`` / ``closure_complete`` (or a non-setup start) does
        # NOT admit (mirrors the real store's narrowed SQL).
        return any(
            op.status == "committed"
            and op.operation_kind == "phase_start"
            and op.phase == "setup"
            and op.project_key == project_key
            and op.story_id == story_id
            and op.run_id == run_id
            for op in self._state.operations.values()
        )

    def has_committed_story_exit_for_run(
        self,
        project_key: str,
        story_id: str,
        run_id: str,
    ) -> bool:
        return any(
            op.status == "committed"
            and op.operation_kind == "story_exit"
            and op.project_key == project_key
            and op.story_id == story_id
            and op.run_id == run_id
            for op in self._state.operations.values()
        )

    def save(self, record: ControlPlaneOperationRecord) -> None:
        # ERROR-3 (#3): the legacy upsert REFUSES to overwrite a row that is still
        # LIVE ``claimed`` (a live, owned lease). Mirrors the real store's
        # conditional upsert: a complete/fail reusing a live start's op_id is
        # rejected fail-closed via ``ControlPlaneClaimCollisionError``; a fresh
        # insert and an update of a terminal row are unaffected.
        from agentkit.backend.exceptions import ControlPlaneClaimCollisionError

        existing = self._state.operations.get(record.op_id)
        if existing is not None and existing.status == "claimed":
            raise ControlPlaneClaimCollisionError(
                f"op_id {record.op_id!r} is held by a live 'claimed' lease "
                "(fake store, AG3-054 ERROR-3)",
            )
        self._state.operations[record.op_id] = record

    def delete(self, op_id: str) -> None:
        self._state.operations.pop(op_id, None)


def _fake_run_scoped_save_binding(
    state: _RepoState,
    binding: SessionRunBindingRecord,
) -> None:
    """Mirror the store's RUN-scoped binding upsert in the fake (AG3-054 sweep).

    The real ``_insert_session_binding_row`` upserts only when the session is
    unbound or already bound to the SAME ``(project_key, story_id, run_id)``; a live
    binding for a DIFFERENT run raises ``ControlPlaneBindingCollisionError``. The
    fake validates the same invariant BEFORE mutating, so a foreign-run overwrite is
    caught and rolls back the whole "transaction".
    """
    from agentkit.backend.exceptions import ControlPlaneBindingCollisionError

    existing = state.bindings.get(binding.session_id)
    if existing is None:
        return
    if (
        existing.project_key == binding.project_key
        and existing.story_id == binding.story_id
        and existing.run_id == binding.run_id
    ):
        return
    raise ControlPlaneBindingCollisionError(
        f"session {binding.session_id!r} is bound to run {existing.run_id!r}, not "
        f"{binding.run_id!r} (fake store, AG3-054 run-scoping)",
    )


def _fake_run_scoped_delete_binding(
    state: _RepoState,
    scope: BindingDeleteScope,
) -> None:
    """Mirror the store's RUN-scoped binding delete in the fake (AG3-054 sweep).

    Deletes only when the binding matches the closing run; a missing binding is a
    benign no-op; a foreign-run binding raises ``ControlPlaneBindingCollisionError``
    (never tearing down a foreign run's regime).
    """
    from agentkit.backend.exceptions import ControlPlaneBindingCollisionError

    existing = state.bindings.get(scope.session_id)
    if existing is None:
        return
    if (
        existing.project_key == scope.project_key
        and existing.story_id == scope.story_id
        and existing.run_id == scope.run_id
    ):
        state.bindings.pop(scope.session_id, None)
        return
    raise ControlPlaneBindingCollisionError(
        f"session {scope.session_id!r} is bound to run {existing.run_id!r}, not the "
        f"closing run {scope.run_id!r} (fake store, AG3-054 run-scoping)",
    )


def _stored_claimed_at_raw(record: ControlPlaneOperationRecord) -> str | None:
    """Mimic the store's raw ``claimed_at`` TEXT round-trip for the fake (ERROR-2).

    The real store keeps ``claimed_at`` as raw TEXT; a load re-exposes it via
    ``claimed_at_raw``. The fake holds records in memory without that round-trip,
    so this helper reconstructs the raw text the store would have read back: the
    record's preserved ``claimed_at_raw`` when present (it came from a load), else
    the ``isoformat`` of the written ``claimed_at`` (the writer stamps TEXT).
    """
    if record.claimed_at_raw is not None:
        return record.claimed_at_raw
    if record.claimed_at is None:
        return None
    return record.claimed_at.isoformat()


def _load_operation_with_raw(
    state: _RepoState, op_id: str
) -> ControlPlaneOperationRecord | None:
    """Load an op, attaching the store-equivalent raw ``claimed_at`` (ERROR-2).

    The runtime observes ``stored.claimed_at_raw`` for the takeover CAS, so the
    fake load must expose the raw TEXT the store would have round-tripped (a fresh
    in-memory placeholder carries ``claimed_at_raw=None`` until loaded).
    """
    from dataclasses import replace

    record = state.operations.get(op_id)
    if record is None:
        return None
    return replace(record, claimed_at_raw=_stored_claimed_at_raw(record))


def _repository(state: _RepoState) -> ControlPlaneRuntimeRepository:
    def _delete_binding(session_id: str) -> None:
        state.bindings.pop(session_id, None)

    ops = _FakeOps(state)

    return ControlPlaneRuntimeRepository(
        load_operation=lambda op_id: _load_operation_with_raw(state, op_id),
        save_operation=ops.save,
        claim_operation=ops.claim,
        takeover_operation=ops.takeover,
        finalize_operation=ops.finalize,
        finalize_start_phase=ops.finalize_start_phase,
        commit_operation_with_side_effects=ops.commit_with_side_effects,
        release_operation=ops.release,
        has_committed_operation_for_run=ops.has_committed_for_run,
        has_committed_story_exit_operation_for_run=ops.has_committed_story_exit_for_run,
        delete_operation=ops.delete,
        load_binding=state.bindings.get,
        save_binding=lambda record: state.bindings.__setitem__(
            record.session_id,
            record,
        ),
        delete_binding=_delete_binding,
        load_lock=lambda project_key, story_id, run_id, lock_type: state.locks.get(
            (project_key, story_id, run_id, lock_type),
        ),
        save_lock=lambda record: state.locks.__setitem__(
            (
                record.project_key,
                record.story_id,
                record.run_id,
                record.lock_type,
            ),
            record,
        ),
        append_event=state.events.append,
        load_story_context=lambda project_key, story_id: state.story_contexts.get(
            (project_key, story_id),
        ),
    )


def _story_context(
    *,
    project_key: str,
    story_id: str,
    mode: WireStoryMode,
    story_type: StoryType = StoryType.IMPLEMENTATION,
    project_root: Path | None = None,
) -> StoryContext:
    return StoryContext(
        project_key=project_key,
        story_id=story_id,
        story_type=story_type,
        execution_route=StoryMode.EXECUTION,
        mode=mode,
        project_root=project_root,
    )


def _admitting_service(state: _RepoState) -> ControlPlaneRuntimeService:
    """A runtime service whose fresh-setup-start is admitted by a stub dispatcher.

    A fresh setup start now requires a resolvable, Approved+READY-admitted run
    (FK-20 §20.8.2); the stub dispatcher returns an ``admitted`` dispatch so the
    binding/lock/operation persistence path is exercised without the real engine.
    """
    return ControlPlaneRuntimeService(
        repository=_repository(state),
        phase_dispatcher=_StubDispatcher(_admitted_dispatch()),  # type: ignore[arg-type]
    )


def _resolvable_standard_ctx(state: _RepoState) -> None:
    state.story_contexts[("tenant-a", "AG3-100")] = _story_context(
        project_key="tenant-a",
        story_id="AG3-100",
        mode=WireStoryMode.STANDARD,
        project_root=Path("T:/projects/tenant-a"),
    )


def _seed_admitted_run(
    state: _RepoState,
    *,
    run_id: str,
    session_id: str = "sess-001",
    project_key: str = "tenant-a",
    story_id: str = "AG3-100",
) -> None:
    """Seed run-matched admission evidence (#2/#6): a binding for THIS run.

    A prior admitted start materialized a session binding for
    ``(project_key, story_id, run_id)``. Closure / complete / fail consume it as
    run-matched admission evidence. The binding's keys must match exactly -- a
    binding for a different run does NOT admit (the #2 negative test relies on
    this).
    """
    state.bindings[session_id] = SessionRunBindingRecord(
        session_id=session_id,
        project_key=project_key,
        story_id=story_id,
        run_id=run_id,
        principal_type="orchestrator",
        worktree_roots=("T:/worktrees/ag3-100",),
        binding_version="bind-001",
        updated_at=datetime(2026, 4, 22, 10, 0, tzinfo=UTC),
    )


def test_start_phase_persists_binding_lock_and_operation() -> None:
    state = _RepoState()
    _resolvable_standard_ctx(state)
    service = _admitting_service(state)

    result = service.start_phase(
        run_id="run-100",
        phase="setup",
        request=PhaseMutationRequest(
            project_key="tenant-a",
            story_id="AG3-100",
            session_id="sess-001",
            principal_type="orchestrator",
            worktree_roots=["T:/worktrees/ag3-100"],
        ),
    )

    assert result.operation_kind == "phase_start"
    assert result.edge_bundle is not None
    assert result.edge_bundle.current.operating_mode == "story_execution"
    assert result.edge_bundle.qa_lock is not None
    assert result.edge_bundle.qa_lock.status == "ACTIVE"
    assert "sess-001" in state.bindings
    assert ("tenant-a", "AG3-100", "run-100", "story_execution") in state.locks
    assert ("tenant-a", "AG3-100", "run-100", "qa_artifact_write") in state.locks
    assert "op-" in result.op_id
    assert result.op_id in state.operations
    assert [event.event_type for event in state.events] == [
        "session_run_binding_created",
        "story_execution_regime_activated",
    ]


def test_repeated_op_id_replays_without_second_mutation() -> None:
    state = _RepoState()
    _resolvable_standard_ctx(state)
    service = _admitting_service(state)
    request = PhaseMutationRequest(
        project_key="tenant-a",
        story_id="AG3-100",
        session_id="sess-001",
        principal_type="orchestrator",
        worktree_roots=["T:/worktrees/ag3-100"],
        op_id="op-fixed-001",
    )

    first = service.start_phase(run_id="run-100", phase="setup", request=request)
    second = service.start_phase(run_id="run-100", phase="setup", request=request)

    assert first.status == "committed"
    assert second.status == "replayed"
    assert len(state.operations) == 1
    assert len(state.events) == 2


def test_complete_closure_unbinds_and_returns_tombstone_roots() -> None:
    state = _RepoState()
    now = datetime(2026, 4, 22, 10, 0, tzinfo=UTC)
    state.bindings["sess-001"] = SessionRunBindingRecord(
        session_id="sess-001",
        project_key="tenant-a",
        story_id="AG3-100",
        run_id="run-100",
        principal_type="orchestrator",
        worktree_roots=("T:/worktrees/ag3-100",),
        binding_version="bind-001",
        updated_at=now,
    )
    service = ControlPlaneRuntimeService(repository=_repository(state))

    result = service.complete_closure(
        run_id="run-100",
        request=ClosureCompleteRequest(
            project_key="tenant-a",
            story_id="AG3-100",
            session_id="sess-001",
        ),
    )

    assert result.edge_bundle is not None
    assert result.edge_bundle.current.operating_mode == "ai_augmented"
    assert result.edge_bundle.tombstone_worktree_roots == ["T:/worktrees/ag3-100"]
    assert result.edge_bundle.qa_lock is not None
    assert result.edge_bundle.qa_lock.status == "INACTIVE"
    assert "sess-001" not in state.bindings
    assert [event.event_type for event in state.events] == [
        "session_run_binding_removed",
        "story_execution_regime_deactivated",
    ]


def test_complete_closure_fast_story_is_a_no_op() -> None:
    """AG3-018 FIX-2 (FK-24 §24.3.4): fast closure creates no locks / no events.

    A fast story never activated story-scoped guards, so its closure must be a
    true no-op: no ``story_execution`` / ``qa_artifact_write`` lock-records are
    created and no story-execution deactivation events are emitted. It returns an
    ``ai_augmented`` bundle with no session and no locks.
    """
    state = _RepoState()
    state.story_contexts[("tenant-a", "AG3-100")] = _story_context(
        project_key="tenant-a",
        story_id="AG3-100",
        mode=WireStoryMode.FAST,
    )
    # ERROR-6 (#6): closure now requires a PRIOR admitted run. A fast story's
    # admitted setup leaves a committed start operation for the run (it never
    # creates a binding/lock), so seed that admission evidence; the fast no-op is
    # preserved WHEN there was a prior admitted run.
    _seed_admitted_run(state, run_id="run-100")
    service = ControlPlaneRuntimeService(repository=_repository(state))

    result = service.complete_closure(
        run_id="run-100",
        request=ClosureCompleteRequest(
            project_key="tenant-a",
            story_id="AG3-100",
            session_id="sess-001",
        ),
    )

    # No story/QA lock-records were created during the fast teardown.
    assert state.locks == {}
    # No story-execution deactivation (or any lifecycle) events were emitted.
    assert state.events == []
    # The bundle resolves to ai_augmented with no session / no locks.
    assert result.operation_kind == "closure_complete"
    assert result.edge_bundle is not None
    assert result.edge_bundle.current.operating_mode == "ai_augmented"
    assert result.edge_bundle.session is None
    assert result.edge_bundle.lock is None
    assert result.edge_bundle.qa_lock is None


def test_complete_closure_fast_story_replays_idempotently() -> None:
    """A repeated fast-closure op_id replays without a second mutation."""
    state = _RepoState()
    state.story_contexts[("tenant-a", "AG3-100")] = _story_context(
        project_key="tenant-a",
        story_id="AG3-100",
        mode=WireStoryMode.FAST,
    )
    # ERROR-6 (#6): closure requires a prior admitted run; seed it (see above).
    _seed_admitted_run(state, run_id="run-100")
    service = ControlPlaneRuntimeService(repository=_repository(state))
    request = ClosureCompleteRequest(
        project_key="tenant-a",
        story_id="AG3-100",
        session_id="sess-001",
        op_id="op-fast-closure-001",
    )

    first = service.complete_closure(run_id="run-100", request=request)
    second = service.complete_closure(run_id="run-100", request=request)

    assert first.status == "committed"
    assert second.status == "replayed"
    assert len(state.operations) == 1
    assert state.locks == {}
    assert state.events == []


def test_complete_closure_standard_story_still_deactivates_locks() -> None:
    """Standard closure is unchanged: INACTIVE locks + deactivation events fire."""
    state = _RepoState()
    state.story_contexts[("tenant-a", "AG3-100")] = _story_context(
        project_key="tenant-a",
        story_id="AG3-100",
        mode=WireStoryMode.STANDARD,
    )
    now = datetime(2026, 4, 22, 10, 0, tzinfo=UTC)
    state.bindings["sess-001"] = SessionRunBindingRecord(
        session_id="sess-001",
        project_key="tenant-a",
        story_id="AG3-100",
        run_id="run-100",
        principal_type="orchestrator",
        worktree_roots=("T:/worktrees/ag3-100",),
        binding_version="bind-001",
        updated_at=now,
    )
    service = ControlPlaneRuntimeService(repository=_repository(state))

    result = service.complete_closure(
        run_id="run-100",
        request=ClosureCompleteRequest(
            project_key="tenant-a",
            story_id="AG3-100",
            session_id="sess-001",
        ),
    )

    assert result.edge_bundle is not None
    assert result.edge_bundle.current.operating_mode == "ai_augmented"
    assert result.edge_bundle.tombstone_worktree_roots == ["T:/worktrees/ag3-100"]
    assert ("tenant-a", "AG3-100", "run-100", "story_execution") in state.locks
    assert ("tenant-a", "AG3-100", "run-100", "qa_artifact_write") in state.locks
    assert "sess-001" not in state.bindings
    assert [event.event_type for event in state.events] == [
        "session_run_binding_removed",
        "story_execution_regime_deactivated",
    ]


def test_project_edge_sync_without_binding_returns_ai_augmented() -> None:
    state = _RepoState()
    service = ControlPlaneRuntimeService(repository=_repository(state))

    result = service.sync_project_edge(
        ProjectEdgeSyncRequest(project_key="tenant-a", session_id="sess-001"),
    )

    assert result.status == "synced"
    assert result.edge_bundle is not None
    assert result.edge_bundle.current.operating_mode == "ai_augmented"


def test_project_edge_sync_with_missing_lock_returns_binding_invalid() -> None:
    state = _RepoState()
    state.bindings["sess-001"] = SessionRunBindingRecord(
        session_id="sess-001",
        project_key="tenant-a",
        story_id="AG3-100",
        run_id="run-100",
        principal_type="orchestrator",
        worktree_roots=("T:/worktrees/ag3-100",),
        binding_version="bind-001",
        updated_at=datetime(2026, 4, 22, 10, 0, tzinfo=UTC),
    )
    service = ControlPlaneRuntimeService(repository=_repository(state))

    result = service.sync_project_edge(
        ProjectEdgeSyncRequest(project_key="tenant-a", session_id="sess-001"),
    )

    assert result.edge_bundle is not None
    assert result.edge_bundle.current.operating_mode == "binding_invalid"
    assert result.run_id == "run-100"


def test_get_operation_returns_replayed_result() -> None:
    state = _RepoState()
    _resolvable_standard_ctx(state)
    service = _admitting_service(state)
    created = service.start_phase(
        run_id="run-100",
        phase="setup",
        request=PhaseMutationRequest(
            project_key="tenant-a",
            story_id="AG3-100",
            session_id="sess-001",
            principal_type="orchestrator",
            worktree_roots=["T:/worktrees/ag3-100"],
            op_id="op-fixed-001",
        ),
    )

    replayed = service.get_operation("op-fixed-001")

    assert created.status == "committed"
    assert replayed is not None
    assert replayed.status == "replayed"
    assert replayed.op_id == "op-fixed-001"


def _fast_request() -> PhaseMutationRequest:
    return PhaseMutationRequest(
        project_key="tenant-a",
        story_id="AG3-100",
        session_id="sess-001",
        principal_type="orchestrator",
        worktree_roots=["T:/worktrees/ag3-100"],
    )


def test_fast_story_skips_story_scoped_session_and_locks() -> None:
    """AG3-018 AC3/AC5: a fast story materializes no session/locks.

    ERROR-1 (#1): a non-setup start requires the run to be ADMITTED (a prior
    committed setup phase_start, or a run-matched binding); otherwise it is
    fail-closed REJECTED. This AG3-018 mode-resolution test exercises the
    legitimate ADMITTED non-setup path, so it seeds run-matched op-based admission
    evidence (a committed setup phase_start for run-100) -- which does NOT add any
    binding/lock/event, keeping the AC3/AC5 "no story-scoped state" assertions
    exact.
    """
    state = _RepoState()
    state.story_contexts[("tenant-a", "AG3-100")] = _story_context(
        project_key="tenant-a",
        story_id="AG3-100",
        mode=WireStoryMode.FAST,
    )
    state.operations["op-admit-setup"] = _committed_op_for_run(
        op_id="op-admit-setup", run_id="run-100"
    )
    service = ControlPlaneRuntimeService(repository=_repository(state))

    result = service.start_phase(
        run_id="run-100",
        phase="implementation",
        request=_fast_request(),
    )

    # No story-scoped session binding and no locks were materialized.
    assert state.bindings == {}
    assert state.locks == {}
    # The edge bundle resolves to ai_augmented with no session/lock so the
    # local edge runs only the baseline guards (BranchGuard et al.).
    assert result.edge_bundle is not None
    assert result.edge_bundle.current.operating_mode == "ai_augmented"
    assert result.edge_bundle.session is None
    assert result.edge_bundle.lock is None
    assert result.edge_bundle.qa_lock is None
    # No story_execution regime is entered, so no regime/ binding events fire.
    assert state.events == []


def test_standard_story_still_materializes_session_and_locks() -> None:
    """Standard stories are unchanged: full session + both locks materialized.

    ERROR-1 (#1): the legitimate non-setup path requires an ADMITTED run, so seed
    op-based admission evidence (a committed setup phase_start for run-100) before
    the implementation start.
    """
    state = _RepoState()
    state.story_contexts[("tenant-a", "AG3-100")] = _story_context(
        project_key="tenant-a",
        story_id="AG3-100",
        mode=WireStoryMode.STANDARD,
    )
    state.operations["op-admit-setup"] = _committed_op_for_run(
        op_id="op-admit-setup", run_id="run-100"
    )
    service = ControlPlaneRuntimeService(repository=_repository(state))

    result = service.start_phase(
        run_id="run-100",
        phase="implementation",
        request=_fast_request(),
    )

    assert result.edge_bundle is not None
    assert result.edge_bundle.current.operating_mode == "story_execution"
    assert "sess-001" in state.bindings
    assert ("tenant-a", "AG3-100", "run-100", "story_execution") in state.locks
    assert ("tenant-a", "AG3-100", "run-100", "qa_artifact_write") in state.locks
    assert [event.event_type for event in state.events] == [
        "session_run_binding_created",
        "story_execution_regime_activated",
    ]


def test_agent_supplied_mode_cannot_override_authoritative_store() -> None:
    """The store wins: an agent-forgeable mode field is not even consulted.

    ``PhaseMutationRequest`` carries no ``mode`` (no forgeable input). Even when
    a caller smuggles ``mode=fast`` into the free-form ``detail`` map, the store
    record (standard) is authoritative and full materialization happens.

    ERROR-1 (#1): the legitimate non-setup path requires an ADMITTED run, so seed
    op-based admission evidence (a committed setup phase_start for run-100).
    """
    state = _RepoState()
    state.story_contexts[("tenant-a", "AG3-100")] = _story_context(
        project_key="tenant-a",
        story_id="AG3-100",
        mode=WireStoryMode.STANDARD,
    )
    state.operations["op-admit-setup"] = _committed_op_for_run(
        op_id="op-admit-setup", run_id="run-100"
    )
    service = ControlPlaneRuntimeService(repository=_repository(state))

    result = service.start_phase(
        run_id="run-100",
        phase="implementation",
        request=PhaseMutationRequest(
            project_key="tenant-a",
            story_id="AG3-100",
            session_id="sess-001",
            principal_type="orchestrator",
            worktree_roots=["T:/worktrees/ag3-100"],
            detail={"mode": "fast"},
        ),
    )

    # Store says standard -> story-scoped state IS materialized regardless of
    # the agent-supplied detail.mode.
    assert result.edge_bundle is not None
    assert result.edge_bundle.current.operating_mode == "story_execution"
    assert result.edge_bundle.lock is not None
    assert ("tenant-a", "AG3-100", "run-100", "story_execution") in state.locks


def test_unresolvable_mode_for_code_story_fails_closed() -> None:
    """Fail-closed: no authoritative StoryContext -> guards stay active.

    A missing store record must NEVER silently skip story-scoped guards; the
    run is treated as standard (full materialization), so a code story can never
    lose its guards on a lookup gap.

    ERROR-1 (#1): the unresolvable-MODE concern (fail-closed-to-standard) is
    distinct from the unresolvable-CTX run-admission concern. This test isolates
    the MODE concern on the legitimate ADMITTED non-setup path: it seeds op-based
    run admission (a committed setup phase_start for run-100) so the run is
    admitted, then proves that an unresolvable StoryContext still materializes the
    FULL standard regime (guards active). The UN-admitted unresolvable-ctx
    non-setup REJECT path is covered by
    ``test_non_setup_unresolvable_ctx_unadmitted_rejects_fail_closed``.
    """
    state = _RepoState()  # no story_contexts entry => unresolvable mode
    state.operations["op-admit-setup"] = _committed_op_for_run(
        op_id="op-admit-setup", run_id="run-100"
    )
    service = ControlPlaneRuntimeService(repository=_repository(state))

    result = service.start_phase(
        run_id="run-100",
        phase="implementation",
        request=_fast_request(),
    )

    assert result.edge_bundle is not None
    assert result.edge_bundle.current.operating_mode == "story_execution"
    assert result.edge_bundle.lock is not None
    assert ("tenant-a", "AG3-100", "run-100", "story_execution") in state.locks
    assert ("tenant-a", "AG3-100", "run-100", "qa_artifact_write") in state.locks


class _StubDispatcher:
    """A minimal :class:`PhaseDispatcher`-shaped stub for runtime dispatch tests.

    Returns a fixed normalized result so the runtime's fail-closed admission
    short-circuit can be exercised without standing up the real engine /
    pre-start-guard composition. Records the calls so a test can assert it was
    (or was not) consulted.
    """

    def __init__(self, result: PhaseDispatchResult) -> None:
        self._result = result
        self.calls: list[str] = []
        #: AG3-054 ERROR-1: the run-scoped admission flag the runtime threads in.
        self.run_admitted_calls: list[bool] = []

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
        del ctx, story_dir, run_id, detail
        self.calls.append(phase)
        self.run_admitted_calls.append(run_admitted)
        return self._result


def _rejected_dispatch(reason: str) -> PhaseDispatchResult:
    return PhaseDispatchResult(
        phase="setup",
        status="rejected",
        reaction="rejected",
        dispatched=False,
        rejection_reason=reason,
    )


def _admitted_dispatch() -> PhaseDispatchResult:
    return PhaseDispatchResult(
        phase="setup",
        status="phase_completed",
        reaction="advance",
        dispatched=True,
        next_phase="implementation",
    )


def test_guard_rejected_setup_start_materializes_no_state() -> None:
    """AG3-054 (FK-20 §20.8.2): a REJECTED fresh-run setup start is fail-closed.

    When the pre-start guard rejects a fresh setup start, the control plane must
    NOT materialize the run's story-scoped guard regime: no session binding, no
    story/QA lock-records, and NO committed operation may be persisted (so a
    later retry re-evaluates). The result is the rejection itself, with no edge
    bundle.
    """
    state = _RepoState()
    state.story_contexts[("tenant-a", "AG3-100")] = _story_context(
        project_key="tenant-a",
        story_id="AG3-100",
        mode=WireStoryMode.STANDARD,
        project_root=Path("T:/projects/tenant-a"),
    )
    dispatcher = _StubDispatcher(
        _rejected_dispatch("StoryStatus is not Approved (Tor 1)."),
    )
    service = ControlPlaneRuntimeService(
        repository=_repository(state),
        phase_dispatcher=dispatcher,  # type: ignore[arg-type]
    )

    result = service.start_phase(
        run_id="run-100",
        phase="setup",
        request=PhaseMutationRequest(
            project_key="tenant-a",
            story_id="AG3-100",
            session_id="sess-001",
            principal_type="orchestrator",
            worktree_roots=["T:/worktrees/ag3-100"],
            op_id="op-rejected-001",
        ),
    )

    # The result IS the rejection -- no success that activates the run.
    assert result.status == "rejected"
    assert result.edge_bundle is None
    assert result.phase_dispatch is not None
    assert result.phase_dispatch.dispatched is False
    assert result.phase_dispatch.status == "rejected"
    # Probe the repository state: NO story-scoped state was materialized.
    assert state.bindings == {}, "rejection must persist no session binding"
    assert state.locks == {}, "rejection must persist no lock-records"
    assert state.events == [], "rejection must emit no lifecycle events"
    # NO committed operation was stored for this op_id (retry re-evaluates).
    assert "op-rejected-001" not in state.operations
    assert state.operations == {}


def test_admitted_start_after_rejection_materializes_state() -> None:
    """A later admitted start for the same story succeeds and materializes state.

    Proves the earlier rejection did not poison the path: because the rejection
    stored no committed op, a fresh op_id (once Approved+READY) re-evaluates,
    is admitted, and DOES materialize the full story-scoped regime.
    """
    state = _RepoState()
    state.story_contexts[("tenant-a", "AG3-100")] = _story_context(
        project_key="tenant-a",
        story_id="AG3-100",
        mode=WireStoryMode.STANDARD,
        project_root=Path("T:/projects/tenant-a"),
    )
    rejecting = ControlPlaneRuntimeService(
        repository=_repository(state),
        phase_dispatcher=_StubDispatcher(  # type: ignore[arg-type]
            _rejected_dispatch("not READY (Tor 2)."),
        ),
    )
    rejected = rejecting.start_phase(
        run_id="run-100",
        phase="setup",
        request=PhaseMutationRequest(
            project_key="tenant-a",
            story_id="AG3-100",
            session_id="sess-001",
            principal_type="orchestrator",
            worktree_roots=["T:/worktrees/ag3-100"],
            op_id="op-rejected-002",
        ),
    )
    assert rejected.status == "rejected"
    assert state.operations == {}

    # Now Approved+READY -> a fresh dispatcher admits the same story's start.
    admitting = ControlPlaneRuntimeService(
        repository=_repository(state),
        phase_dispatcher=_StubDispatcher(_admitted_dispatch()),  # type: ignore[arg-type]
    )
    admitted = admitting.start_phase(
        run_id="run-100",
        phase="setup",
        request=PhaseMutationRequest(
            project_key="tenant-a",
            story_id="AG3-100",
            session_id="sess-001",
            principal_type="orchestrator",
            worktree_roots=["T:/worktrees/ag3-100"],
            op_id="op-admitted-001",
        ),
    )

    assert admitted.status == "committed"
    assert admitted.edge_bundle is not None
    assert admitted.edge_bundle.current.operating_mode == "story_execution"
    assert admitted.phase_dispatch is not None
    assert admitted.phase_dispatch.dispatched is True
    # The admitted start materialized the full story-scoped regime.
    assert "sess-001" in state.bindings
    assert ("tenant-a", "AG3-100", "run-100", "story_execution") in state.locks
    assert ("tenant-a", "AG3-100", "run-100", "qa_artifact_write") in state.locks
    assert "op-admitted-001" in state.operations


def _setup_request(op_id: str = "op-fresh-setup-001") -> PhaseMutationRequest:
    return PhaseMutationRequest(
        project_key="tenant-a",
        story_id="AG3-100",
        session_id="sess-001",
        principal_type="orchestrator",
        worktree_roots=["T:/worktrees/ag3-100"],
        op_id=op_id,
    )


def test_fresh_setup_start_with_no_story_context_rejects_fail_closed() -> None:
    """ERROR-1 (FK-20 §20.8.2): unresolvable ctx (None) rejects a fresh setup start.

    A fresh setup start whose ``StoryContext`` cannot be resolved (no store row)
    could not have its Approved+READY run-admission evaluated. The control plane
    must REJECT fail-closed and materialize NOTHING: no binding, no locks, no
    events, no edge bundle, and NO stored operation (a later retry re-evaluates).
    """
    state = _RepoState()  # no story_contexts entry => ctx is None
    service = ControlPlaneRuntimeService(repository=_repository(state))

    result = service.start_phase(
        run_id="run-100",
        phase="setup",
        request=_setup_request(),
    )

    assert result.status == "rejected"
    assert result.edge_bundle is None
    assert result.phase_dispatch is not None
    assert result.phase_dispatch.dispatched is False
    assert result.phase_dispatch.status == "rejected"
    # Repository probe: NOTHING was materialized.
    assert state.bindings == {}, "rejection must persist no session binding"
    assert state.locks == {}, "rejection must persist no lock-records"
    assert state.events == [], "rejection must emit no lifecycle events"
    assert state.operations == {}, "rejection must store no operation"


def test_fresh_setup_start_with_no_project_root_rejects_fail_closed() -> None:
    """ERROR-1: ctx present but ``project_root is None`` also rejects fail-closed.

    The dispatch cannot resolve a story_dir without a project_root, so the run's
    Approved+READY admission cannot be evaluated. Same fail-closed materialize-
    nothing outcome as the ctx-is-None case.
    """
    state = _RepoState()
    state.story_contexts[("tenant-a", "AG3-100")] = _story_context(
        project_key="tenant-a",
        story_id="AG3-100",
        mode=WireStoryMode.STANDARD,
        project_root=None,  # unresolvable story_dir
    )
    service = ControlPlaneRuntimeService(repository=_repository(state))

    result = service.start_phase(
        run_id="run-100",
        phase="setup",
        request=_setup_request("op-fresh-setup-002"),
    )

    assert result.status == "rejected"
    assert result.edge_bundle is None
    assert result.phase_dispatch is not None
    assert result.phase_dispatch.dispatched is False
    assert state.bindings == {}
    assert state.locks == {}
    assert state.events == []
    assert state.operations == {}


def test_non_setup_unresolvable_ctx_unadmitted_rejects_fail_closed() -> None:
    """ERROR-1 (#1): a fresh, UN-admitted, NON-setup start with unresolvable ctx.

    This CORRECTS the prior (wrong) fail-open assertion. The round-8 run-scoped
    first-call enforcement lives inside ``PhaseDispatcher.dispatch``, but
    ``_dispatch_phase`` returns ``None`` when the StoryContext is unresolvable (ctx
    None AND project_root None) BEFORE the dispatcher runs. The run-scoped
    first-call must therefore hold in the RUNTIME on this path too: a non-setup
    start for a run that was NEVER admitted (no committed setup phase_start, no
    run-matched binding) must be fail-closed REJECTED and materialize NOTHING --
    NOT fall through to a standard materialization. An un-admitted run can NEVER
    materialize state via a non-setup start, regardless of ctx resolvability.
    """
    state = _RepoState()  # no story_contexts => unresolvable; no admission evidence
    service = ControlPlaneRuntimeService(repository=_repository(state))

    result = service.start_phase(
        run_id="run-100",
        phase="implementation",
        request=_fast_request(),
    )

    assert result.status == "rejected"
    assert result.edge_bundle is None
    assert result.phase_dispatch is not None
    assert result.phase_dispatch.dispatched is False
    # Repository probe: NOTHING was materialized for the un-admitted run.
    assert state.bindings == {}, "rejection must persist no session binding"
    assert state.locks == {}, "rejection must persist no lock-records"
    assert state.events == [], "rejection must emit no lifecycle events"
    assert state.operations == {}, "rejection must store no operation"


def test_non_setup_unresolvable_ctx_admitted_run_still_materializes() -> None:
    """ERROR-1 (#1) positive: the ADMITTED non-setup path still works.

    The legitimate non-setup path is preserved: when the run WAS admitted (a prior
    committed setup phase_start for THIS run), a non-setup start with an
    unresolvable ctx keeps the AG3-018 fail-closed-to-standard behavior (full
    story-scoped materialization, guards ACTIVE). Only the UN-admitted run is
    rejected.
    """
    state = _RepoState()  # no story_contexts entry => unresolvable ctx/mode
    state.operations["op-admit-setup"] = _committed_op_for_run(
        op_id="op-admit-setup", run_id="run-100"
    )
    service = ControlPlaneRuntimeService(repository=_repository(state))

    result = service.start_phase(
        run_id="run-100",
        phase="implementation",
        request=_fast_request(),
    )

    assert result.status == "committed"
    assert result.edge_bundle is not None
    assert result.edge_bundle.current.operating_mode == "story_execution"
    assert result.edge_bundle.lock is not None
    assert ("tenant-a", "AG3-100", "run-100", "story_execution") in state.locks
    assert ("tenant-a", "AG3-100", "run-100", "qa_artifact_write") in state.locks


def test_replay_returns_same_phase_dispatch_and_dispatches_once() -> None:
    """ERROR-2 (AC7): a replay returns the SAME phase_dispatch; dispatch runs once.

    The first start carries ``phase_dispatch``; a replay of the same op_id must
    return a stored record IDENTICAL to the first response (full equality, not
    just ``status == "replayed"``) and must NOT invoke the dispatcher again.
    """
    state = _RepoState()
    _resolvable_standard_ctx(state)
    dispatcher = _StubDispatcher(_admitted_dispatch())
    service = ControlPlaneRuntimeService(
        repository=_repository(state),
        phase_dispatcher=dispatcher,  # type: ignore[arg-type]
    )
    request = _setup_request("op-replay-dispatch-001")

    first = service.start_phase(run_id="run-100", phase="setup", request=request)
    replay = service.start_phase(run_id="run-100", phase="setup", request=request)

    assert first.status == "committed"
    assert first.phase_dispatch is not None
    assert replay.status == "replayed"
    # Full equality of the carried dispatch outcome (no lost phase_dispatch).
    assert replay.phase_dispatch == first.phase_dispatch
    assert replay.phase_dispatch == _admitted_dispatch()
    # The dispatcher was invoked EXACTLY ONCE across both calls (no re-dispatch).
    assert dispatcher.calls == ["setup"]
    assert len(state.operations) == 1
    # The PERSISTED record is the full first result (no field dropped before store).
    assert (
        state.operations["op-replay-dispatch-001"].response_payload
        == first.model_dump(mode="json")
    )


def test_mutation_result_success_status_requires_edge_bundle() -> None:
    """A non-rejected ControlPlaneMutationResult MUST carry an edge_bundle.

    The field was widened to optional ONLY for fail-closed rejections (AG3-054).
    A committed / replayed / synced result with ``edge_bundle=None`` would let the
    project-edge client silently skip publishing an authoritative bundle (a
    fail-open activation gap) -- the model rejects it at the boundary.
    """
    for status in ("committed", "replayed", "synced"):
        with pytest.raises(ValidationError):
            ControlPlaneMutationResult(
                status=status,  # type: ignore[arg-type]
                op_id="op-x",
                operation_kind="phase_start",
                edge_bundle=None,
            )


def test_mutation_result_rejected_must_not_carry_edge_bundle() -> None:
    """A 'rejected' result materialized no guard regime and must carry no bundle."""
    state = _RepoState()
    _resolvable_standard_ctx(state)
    service = ControlPlaneRuntimeService(
        repository=_repository(state),
        phase_dispatcher=_StubDispatcher(_admitted_dispatch()),  # type: ignore[arg-type]
    )
    committed = service.start_phase(
        run_id="run-100", phase="setup", request=_setup_request("op-bundle-src"),
    )
    assert committed.edge_bundle is not None  # a real bundle to misuse below

    with pytest.raises(ValidationError):
        ControlPlaneMutationResult(
            status="rejected",
            op_id="op-y",
            operation_kind="phase_start",
            edge_bundle=committed.edge_bundle,
        )


# ---------------------------------------------------------------------------
# ERROR-3: complete/fail require a prior admitted run
# ---------------------------------------------------------------------------


def _phase_request(op_id: str) -> PhaseMutationRequest:
    return PhaseMutationRequest(
        project_key="tenant-a",
        story_id="AG3-100",
        session_id="sess-001",
        principal_type="orchestrator",
        worktree_roots=["T:/worktrees/ag3-100"],
        op_id=op_id,
    )


def test_complete_phase_without_admitted_run_rejects_and_materializes_nothing() -> None:
    """ERROR-3: a first-ever complete with no prior admitted start is fail-closed.

    No prior committed start operation, no persisted phase-state, no session
    binding -> the completion must NOT materialize any story-scoped state and must
    store no committed op.
    """
    state = _RepoState()
    state.story_contexts[("tenant-a", "AG3-100")] = _story_context(
        project_key="tenant-a",
        story_id="AG3-100",
        mode=WireStoryMode.STANDARD,
        project_root=Path("T:/projects/tenant-a"),
    )
    service = ControlPlaneRuntimeService(repository=_repository(state))

    result = service.complete_phase(
        run_id="run-100",
        phase="setup",
        request=_phase_request("op-complete-unadmitted"),
    )

    assert result.status == "rejected"
    assert result.operation_kind == "phase_complete"
    assert result.edge_bundle is None
    assert result.phase_dispatch is not None
    assert result.phase_dispatch.dispatched is False
    assert "no prior admitted start" in (result.phase_dispatch.rejection_reason or "")
    assert state.bindings == {}
    assert state.locks == {}
    assert state.events == []
    assert state.operations == {}


def test_fail_phase_without_admitted_run_rejects() -> None:
    """ERROR-3: a first-ever fail with no prior admitted start is fail-closed too."""
    state = _RepoState()
    service = ControlPlaneRuntimeService(repository=_repository(state))

    result = service.fail_phase(
        run_id="run-100",
        phase="implementation",
        request=_phase_request("op-fail-unadmitted"),
    )

    assert result.status == "rejected"
    assert result.operation_kind == "phase_fail"
    assert result.edge_bundle is None
    assert state.operations == {}


def test_complete_phase_with_prior_binding_is_admitted() -> None:
    """ERROR-3 positive: a prior session binding (admitted start) lets complete run."""
    state = _RepoState()
    state.story_contexts[("tenant-a", "AG3-100")] = _story_context(
        project_key="tenant-a",
        story_id="AG3-100",
        mode=WireStoryMode.STANDARD,
    )
    now = datetime(2026, 4, 22, 10, 0, tzinfo=UTC)
    state.bindings["sess-001"] = SessionRunBindingRecord(
        session_id="sess-001",
        project_key="tenant-a",
        story_id="AG3-100",
        run_id="run-100",
        principal_type="orchestrator",
        worktree_roots=("T:/worktrees/ag3-100",),
        binding_version="bind-001",
        updated_at=now,
    )
    service = ControlPlaneRuntimeService(repository=_repository(state))

    result = service.complete_phase(
        run_id="run-100",
        phase="implementation",
        request=_phase_request("op-complete-admitted"),
    )

    assert result.status == "committed"
    assert result.operation_kind == "phase_complete"
    assert result.edge_bundle is not None
    assert "op-complete-admitted" in state.operations


def test_complete_phase_reusing_live_claimed_start_op_id_does_not_clobber() -> None:
    """ERROR-3 (#3): complete/fail reusing a LIVE claimed start op_id is rejected.

    A ``complete_phase`` whose op_id is currently held as a LIVE ``claimed``
    ``start_phase`` lease must NOT overwrite the claimed row and steal/destroy the
    start's ownership. The conditional save refuses fail-closed; the runtime
    surfaces a ``rejected`` result and the claimed start row is left intact.
    """
    state = _RepoState()
    state.story_contexts[("tenant-a", "AG3-100")] = _story_context(
        project_key="tenant-a",
        story_id="AG3-100",
        mode=WireStoryMode.STANDARD,
    )
    now = datetime(2026, 4, 22, 10, 0, tzinfo=UTC)
    # Admitted run (a session binding for THIS run lets the completion be admitted).
    state.bindings["sess-001"] = SessionRunBindingRecord(
        session_id="sess-001",
        project_key="tenant-a",
        story_id="AG3-100",
        run_id="run-100",
        principal_type="orchestrator",
        worktree_roots=("T:/worktrees/ag3-100",),
        binding_version="bind-001",
        updated_at=now,
    )
    op_id = "op-shared-with-live-start"
    # A LIVE claimed start lease holds the SAME op_id (owner-A, mid-dispatch).
    state.operations[op_id] = ControlPlaneOperationRecord(
        op_id=op_id,
        project_key="tenant-a",
        story_id="AG3-100",
        run_id="run-100",
        session_id="sess-001",
        operation_kind="phase_start",
        phase="setup",
        status="claimed",
        response_payload={},
        created_at=now,
        updated_at=now,
        claimed_by="owner-A",
        claimed_at=now,
    )
    service = ControlPlaneRuntimeService(repository=_repository(state))

    result = service.complete_phase(
        run_id="run-100",
        phase="implementation",
        request=_phase_request(op_id),
    )

    assert result.status == "rejected", "a collision with a live claim must reject"
    # The live claimed start row is intact -- ownership NOT stolen/destroyed.
    stored = state.operations[op_id]
    assert stored.status == "claimed"
    assert stored.claimed_by == "owner-A"
    assert stored.operation_kind == "phase_start"
    # ERROR-2 (#2): the rejection is ATOMIC -- NO orphan side effect was written.
    # The pre-existing admission binding is untouched (NOT recreated/overwritten by
    # a second materialization) and no NEW lock / event leaked before the collision.
    assert state.bindings["sess-001"].binding_version == "bind-001"
    assert state.locks == {}, "no orphan lock may be written on a rejected complete"
    assert state.events == [], "no orphan event may be emitted on a rejected complete"
    # The collision rejection stored only the live claimed start row (no committed op).
    assert set(state.operations) == {op_id}


def test_complete_closure_reusing_live_claimed_start_op_id_is_atomic() -> None:
    """ERROR-2 (#2): a closure reusing a LIVE claimed start op_id has NO side effects.

    A ``complete_closure`` whose op_id is currently held as a LIVE ``claimed``
    ``start_phase`` lease must be fail-closed REJECTED and the rejection must be
    ATOMIC: the standard teardown's INACTIVE locks, the binding DELETION and the
    deactivation events must NOT be applied (the prior code committed those side
    effects in separate transactions BEFORE the conditional op-row upsert detected
    the collision -> orphan teardown while the live claim survived). The live
    claimed start row must remain intact.
    """
    state = _RepoState()
    state.story_contexts[("tenant-a", "AG3-100")] = _story_context(
        project_key="tenant-a",
        story_id="AG3-100",
        mode=WireStoryMode.STANDARD,
    )
    now = datetime(2026, 4, 22, 10, 0, tzinfo=UTC)
    # Admitted run: a session binding for THIS run (also the closure teardown target).
    state.bindings["sess-001"] = SessionRunBindingRecord(
        session_id="sess-001",
        project_key="tenant-a",
        story_id="AG3-100",
        run_id="run-100",
        principal_type="orchestrator",
        worktree_roots=("T:/worktrees/ag3-100",),
        binding_version="bind-001",
        updated_at=now,
    )
    op_id = "op-closure-shared-with-live-start"
    # A LIVE claimed start lease holds the SAME op_id (owner-A, mid-dispatch).
    state.operations[op_id] = ControlPlaneOperationRecord(
        op_id=op_id,
        project_key="tenant-a",
        story_id="AG3-100",
        run_id="run-100",
        session_id="sess-001",
        operation_kind="phase_start",
        phase="setup",
        status="claimed",
        response_payload={},
        created_at=now,
        updated_at=now,
        claimed_by="owner-A",
        claimed_at=now,
    )
    service = ControlPlaneRuntimeService(repository=_repository(state))

    result = service.complete_closure(
        run_id="run-100",
        request=ClosureCompleteRequest(
            project_key="tenant-a",
            story_id="AG3-100",
            session_id="sess-001",
            op_id=op_id,
        ),
    )

    assert result.status == "rejected", "a closure colliding with a live claim rejects"
    # ERROR-2 (#2): ATOMIC rejection -- NO orphan teardown side effect.
    assert "sess-001" in state.bindings, "the binding must NOT be deleted on collision"
    assert state.bindings["sess-001"].run_id == "run-100"
    assert state.locks == {}, "no INACTIVE lock may be written on a rejected closure"
    assert state.events == [], "no deactivation event may fire on a rejected closure"
    # The live claimed start row is intact -- ownership NOT stolen/destroyed.
    stored = state.operations[op_id]
    assert stored.status == "claimed"
    assert stored.claimed_by == "owner-A"
    assert stored.operation_kind == "phase_start"
    assert set(state.operations) == {op_id}


def test_complete_phase_with_binding_for_different_run_is_rejected() -> None:
    """ERROR-2 (#2): a binding for a DIFFERENT run does not admit a completion.

    The admission must match the run EXACTLY: a session binding that merely reuses
    the same ``session_id`` for a DIFFERENT project/story/run is NOT admission
    evidence for this run. A completion for ``run-100`` while the only binding
    under ``sess-001`` belongs to ``run-999`` (a different story) is fail-closed
    REJECTED and materializes nothing.
    """
    state = _RepoState()
    state.story_contexts[("tenant-a", "AG3-100")] = _story_context(
        project_key="tenant-a",
        story_id="AG3-100",
        mode=WireStoryMode.STANDARD,
    )
    now = datetime(2026, 4, 22, 10, 0, tzinfo=UTC)
    # A stale binding under the SAME session_id but a DIFFERENT story + run.
    state.bindings["sess-001"] = SessionRunBindingRecord(
        session_id="sess-001",
        project_key="tenant-a",
        story_id="AG3-999",
        run_id="run-999",
        principal_type="orchestrator",
        worktree_roots=("T:/worktrees/ag3-999",),
        binding_version="bind-999",
        updated_at=now,
    )
    service = ControlPlaneRuntimeService(repository=_repository(state))

    result = service.complete_phase(
        run_id="run-100",
        phase="implementation",
        request=_phase_request("op-complete-wrong-run"),
    )

    assert result.status == "rejected"
    assert result.operation_kind == "phase_complete"
    assert result.edge_bundle is None
    assert "op-complete-wrong-run" not in state.operations
    # The unrelated binding is untouched (no materialization for the wrong run).
    assert state.bindings["sess-001"].run_id == "run-999"
    assert state.locks == {}
    assert state.events == []


def test_complete_closure_for_unadmitted_run_is_rejected() -> None:
    """ERROR-6 (#6): closure for a run with NO prior admitted start is rejected.

    Consistent with complete/fail admission: a closure for an unadmitted run (no
    persisted phase-state and no run-matched binding) must NOT commit. Fail-closed
    -- it materializes no tombstone state and stores no op.
    """
    state = _RepoState()
    state.story_contexts[("tenant-a", "AG3-100")] = _story_context(
        project_key="tenant-a",
        story_id="AG3-100",
        mode=WireStoryMode.STANDARD,
    )
    service = ControlPlaneRuntimeService(repository=_repository(state))

    result = service.complete_closure(
        run_id="run-100",
        request=ClosureCompleteRequest(
            project_key="tenant-a",
            story_id="AG3-100",
            session_id="sess-001",
            op_id="op-closure-unadmitted",
        ),
    )

    assert result.status == "rejected"
    assert result.operation_kind == "closure_complete"
    assert result.edge_bundle is None
    assert state.operations == {}
    assert state.locks == {}
    assert state.events == []


def test_complete_closure_for_different_run_binding_is_rejected() -> None:
    """ERROR-6/#2: a closure admitted only by a binding for ANOTHER run is rejected."""
    state = _RepoState()
    state.story_contexts[("tenant-a", "AG3-100")] = _story_context(
        project_key="tenant-a",
        story_id="AG3-100",
        mode=WireStoryMode.STANDARD,
    )
    now = datetime(2026, 4, 22, 10, 0, tzinfo=UTC)
    state.bindings["sess-001"] = SessionRunBindingRecord(
        session_id="sess-001",
        project_key="tenant-a",
        story_id="AG3-999",
        run_id="run-999",
        principal_type="orchestrator",
        worktree_roots=("T:/worktrees/ag3-999",),
        binding_version="bind-999",
        updated_at=now,
    )
    service = ControlPlaneRuntimeService(repository=_repository(state))

    result = service.complete_closure(
        run_id="run-100",
        request=ClosureCompleteRequest(
            project_key="tenant-a",
            story_id="AG3-100",
            session_id="sess-001",
            op_id="op-closure-wrong-run",
        ),
    )

    assert result.status == "rejected"
    assert result.operation_kind == "closure_complete"
    assert state.operations == {}
    assert state.bindings["sess-001"].run_id == "run-999"


# ---------------------------------------------------------------------------
# AG3-054 run-scoping sweep: a stale/late op for an OLD run (admitted via its
# OWN committed setup op) must not clobber/delete a DIFFERENT (NEW) run's live
# binding that has since rebound the same session_id.
# ---------------------------------------------------------------------------


def _new_run_binding(state: _RepoState, *, run_id: str = "run-NEW") -> None:
    """Bind ``sess-001`` to a NEW run (the live regime that must be protected)."""
    state.bindings["sess-001"] = SessionRunBindingRecord(
        session_id="sess-001",
        project_key="tenant-a",
        story_id="AG3-100",
        run_id=run_id,
        principal_type="orchestrator",
        worktree_roots=("T:/worktrees/ag3-100-new",),
        binding_version="bind-NEW",
        updated_at=datetime(2026, 4, 22, 12, 0, tzinfo=UTC),
    )


def _committed_setup_op(state: _RepoState, *, run_id: str, op_id: str) -> None:
    """Seed a COMMITTED setup phase_start op admitting ``run_id`` (run-matched).

    This is the OLD run's own admission evidence: it was legitimately set up, so
    complete/fail/closure for it pass admission. The run-scoping protection must
    then still keep it from touching the NEW run's live binding.
    """
    now = datetime(2026, 4, 22, 9, 0, tzinfo=UTC)
    state.operations[op_id] = ControlPlaneOperationRecord(
        op_id=op_id,
        project_key="tenant-a",
        story_id="AG3-100",
        run_id=run_id,
        session_id="sess-001",
        operation_kind="phase_start",
        phase="setup",
        status="committed",
        response_payload={
            "status": "committed",
            "op_id": op_id,
            "operation_kind": "phase_start",
            "run_id": run_id,
            "phase": "setup",
        },
        created_at=now,
        updated_at=now,
    )


def test_complete_phase_old_run_does_not_overwrite_new_runs_binding() -> None:
    """AG3-054 sweep: an OLD run's complete must not clobber a NEW run's binding.

    Run-OLD is admitted by its OWN committed setup phase_start, so admission
    passes. But ``sess-001`` is now bound to run-NEW (the session was rebound). The
    standard complete would (pre-fix) upsert ``ON CONFLICT (session_id)`` and
    OVERWRITE run-NEW's live binding. The run-scoped save refuses fail-closed: the
    completion is REJECTED, run-NEW's binding is UNCHANGED, and NO op / lock / event
    is written.
    """
    state = _RepoState()
    state.story_contexts[("tenant-a", "AG3-100")] = _story_context(
        project_key="tenant-a",
        story_id="AG3-100",
        mode=WireStoryMode.STANDARD,
    )
    _new_run_binding(state, run_id="run-NEW")
    _committed_setup_op(state, run_id="run-OLD", op_id="op-old-setup")
    service = ControlPlaneRuntimeService(repository=_repository(state))

    result = service.complete_phase(
        run_id="run-OLD",
        phase="implementation",
        request=_phase_request("op-old-complete"),
    )

    assert result.status == "rejected"
    assert result.operation_kind == "phase_complete"
    # run-NEW's live binding is UNCHANGED (run_id + version intact).
    assert state.bindings["sess-001"].run_id == "run-NEW"
    assert state.bindings["sess-001"].binding_version == "bind-NEW"
    # No committed completion op, no lock change, no events for the old run.
    assert "op-old-complete" not in state.operations
    assert state.locks == {}
    assert state.events == []


def test_fail_phase_old_run_does_not_overwrite_new_runs_binding() -> None:
    """AG3-054 sweep: an OLD run's fail must not clobber a NEW run's binding."""
    state = _RepoState()
    state.story_contexts[("tenant-a", "AG3-100")] = _story_context(
        project_key="tenant-a",
        story_id="AG3-100",
        mode=WireStoryMode.STANDARD,
    )
    _new_run_binding(state, run_id="run-NEW")
    _committed_setup_op(state, run_id="run-OLD", op_id="op-old-setup")
    service = ControlPlaneRuntimeService(repository=_repository(state))

    result = service.fail_phase(
        run_id="run-OLD",
        phase="implementation",
        request=_phase_request("op-old-fail"),
    )

    assert result.status == "rejected"
    assert result.operation_kind == "phase_fail"
    assert state.bindings["sess-001"].run_id == "run-NEW"
    assert state.bindings["sess-001"].binding_version == "bind-NEW"
    assert "op-old-fail" not in state.operations
    assert state.locks == {}
    assert state.events == []


def test_standard_closure_old_run_does_not_delete_new_runs_binding() -> None:
    """AG3-054 sweep: an OLD run's standard closure must not delete a NEW binding.

    Run-OLD is admitted by its committed setup op AND resolves to a standard story,
    so the standard teardown path runs. But ``sess-001`` is bound to run-NEW. The
    pre-fix code deleted by ``session_id`` only (clobbering run-NEW) and derived the
    tombstone from whatever binding existed (run-NEW's). The run-scoped teardown
    refuses fail-closed: closure is REJECTED, run-NEW's binding is NOT deleted, and
    NO INACTIVE locks / deactivation events are written for the old run.
    """
    state = _RepoState()
    state.story_contexts[("tenant-a", "AG3-100")] = _story_context(
        project_key="tenant-a",
        story_id="AG3-100",
        mode=WireStoryMode.STANDARD,
    )
    _new_run_binding(state, run_id="run-NEW")
    _committed_setup_op(state, run_id="run-OLD", op_id="op-old-setup")
    service = ControlPlaneRuntimeService(repository=_repository(state))

    result = service.complete_closure(
        run_id="run-OLD",
        request=ClosureCompleteRequest(
            project_key="tenant-a",
            story_id="AG3-100",
            session_id="sess-001",
            op_id="op-old-closure",
        ),
    )

    assert result.status == "rejected"
    assert result.operation_kind == "closure_complete"
    # run-NEW's binding survives untouched.
    assert state.bindings["sess-001"].run_id == "run-NEW"
    assert state.bindings["sess-001"].binding_version == "bind-NEW"
    # No INACTIVE locks and no deactivation events for the foreign run.
    assert state.locks == {}
    assert state.events == []
    assert "op-old-closure" not in state.operations


def test_fast_closure_old_run_does_not_delete_new_runs_binding() -> None:
    """AG3-054 sweep: an OLD fast run's closure must not delete a NEW run's binding.

    Run-OLD resolves to a FAST story (no locks/events of its own) but is admitted by
    its committed setup op. Its fast closure still issues a run-scoped binding
    delete; because ``sess-001`` is bound to run-NEW, the delete refuses fail-closed:
    closure is REJECTED and run-NEW's binding survives. (A fast closure for a session
    it truly owns -- or no binding at all -- remains a benign no-op; see the existing
    fast-closure tests.)
    """
    state = _RepoState()
    state.story_contexts[("tenant-a", "AG3-100")] = _story_context(
        project_key="tenant-a",
        story_id="AG3-100",
        mode=WireStoryMode.FAST,
    )
    _new_run_binding(state, run_id="run-NEW")
    _committed_setup_op(state, run_id="run-OLD", op_id="op-old-setup")
    service = ControlPlaneRuntimeService(repository=_repository(state))

    result = service.complete_closure(
        run_id="run-OLD",
        request=ClosureCompleteRequest(
            project_key="tenant-a",
            story_id="AG3-100",
            session_id="sess-001",
            op_id="op-old-fast-closure",
        ),
    )

    assert result.status == "rejected"
    assert result.operation_kind == "closure_complete"
    assert state.bindings["sess-001"].run_id == "run-NEW"
    assert state.bindings["sess-001"].binding_version == "bind-NEW"
    assert state.locks == {}
    assert state.events == []
    assert "op-old-fast-closure" not in state.operations


def test_complete_phase_owning_run_still_works_atomically() -> None:
    """Positive: a complete for the run that OWNS the current binding still commits.

    The run-scoping guard only rejects FOREIGN-run writes; the owning run's
    completion upserts its own binding (same run), writes its locks/events and
    commits the op atomically.
    """
    state = _RepoState()
    state.story_contexts[("tenant-a", "AG3-100")] = _story_context(
        project_key="tenant-a",
        story_id="AG3-100",
        mode=WireStoryMode.STANDARD,
    )
    _seed_admitted_run(state, run_id="run-100")
    service = ControlPlaneRuntimeService(repository=_repository(state))

    result = service.complete_phase(
        run_id="run-100",
        phase="implementation",
        request=_phase_request("op-own-complete"),
    )

    assert result.status == "committed"
    assert result.operation_kind == "phase_complete"
    assert "op-own-complete" in state.operations
    assert state.bindings["sess-001"].run_id == "run-100"
    assert ("tenant-a", "AG3-100", "run-100", "story_execution") in state.locks


def test_standard_closure_owning_run_still_tears_down() -> None:
    """Positive: closure for the run that OWNS the binding still tears it down."""
    state = _RepoState()
    state.story_contexts[("tenant-a", "AG3-100")] = _story_context(
        project_key="tenant-a",
        story_id="AG3-100",
        mode=WireStoryMode.STANDARD,
    )
    _seed_admitted_run(state, run_id="run-100")
    _committed_setup_op(state, run_id="run-100", op_id="op-own-setup")
    service = ControlPlaneRuntimeService(repository=_repository(state))

    result = service.complete_closure(
        run_id="run-100",
        request=ClosureCompleteRequest(
            project_key="tenant-a",
            story_id="AG3-100",
            session_id="sess-001",
            op_id="op-own-closure",
        ),
    )

    assert result.status == "committed"
    assert "sess-001" not in state.bindings
    assert ("tenant-a", "AG3-100", "run-100", "story_execution") in state.locks
    assert [event.event_type for event in state.events] == [
        "session_run_binding_removed",
        "story_execution_regime_deactivated",
    ]


# ---------------------------------------------------------------------------
# ERROR-4: atomic op claim -- dispatcher runs at most once per op_id
# ---------------------------------------------------------------------------


def test_same_op_id_concurrent_starts_dispatch_once() -> None:
    """ERROR-4: two same-op_id starts run the dispatcher EXACTLY once.

    Simulates the race where both callers pass the pre-check before either stores
    a result: the atomic claim (insert-if-absent) lets only ONE dispatch; the
    loser takes the replay path and never re-runs the dispatcher side effects.
    """
    state = _RepoState()
    _resolvable_standard_ctx(state)
    dispatcher = _StubDispatcher(_admitted_dispatch())
    service = ControlPlaneRuntimeService(
        repository=_repository(state),
        phase_dispatcher=dispatcher,  # type: ignore[arg-type]
    )
    request = _setup_request("op-race-001")

    first = service.start_phase(run_id="run-100", phase="setup", request=request)
    second = service.start_phase(run_id="run-100", phase="setup", request=request)

    assert first.status == "committed"
    assert second.status == "replayed"
    # The dispatcher ran EXACTLY ONCE across both same-op_id calls.
    assert dispatcher.calls == ["setup"]
    assert len(state.operations) == 1


def test_stale_claim_placeholder_is_reclaimable_and_retry_succeeds() -> None:
    """ERROR-1 (#1): a stale ``claimed`` placeholder never poisons the op_id.

    A winner that CRASHED mid-claim (process killed before its terminal commit or
    its except-path release) leaves a stale ``claimed`` row. The OLD behavior
    surfaced an "in flight" rejection FOREVER -- the op_id was poisoned. The fix
    RECLAIMS a stale ``claimed`` placeholder: a retry deletes it, re-claims, and
    proceeds to a committed result. The dispatcher runs (the crashed winner left
    no side effects behind), and the final op is committed.
    """
    state = _RepoState()
    _resolvable_standard_ctx(state)
    now = datetime(2026, 4, 22, 10, 0, tzinfo=UTC)
    state.operations["op-stale-claim"] = ControlPlaneOperationRecord(
        op_id="op-stale-claim",
        project_key="tenant-a",
        story_id="AG3-100",
        run_id="run-100",
        session_id="sess-001",
        operation_kind="phase_start",
        phase="setup",
        status="claimed",
        response_payload={},
        created_at=now,
        updated_at=now,
    )
    dispatcher = _StubDispatcher(_admitted_dispatch())
    service = ControlPlaneRuntimeService(
        repository=_repository(state),
        phase_dispatcher=dispatcher,  # type: ignore[arg-type]
    )

    result = service.start_phase(
        run_id="run-100", phase="setup", request=_setup_request("op-stale-claim")
    )

    # The stale claim was reclaimed and the retry committed (no poison).
    assert result.status == "committed"
    assert dispatcher.calls == ["setup"]
    assert state.operations["op-stale-claim"].status == "committed"


def test_exception_after_claim_releases_claim_and_leaves_op_reclaimable() -> None:
    """ERROR-1 (#1): an exception after a successful claim releases the claim.

    If the dispatch (or the terminal mutation) raises AFTER the atomic claim and
    BEFORE a terminal op is durably stored, the claim MUST be released so the
    op_id is never stranded "in flight" forever, and no half-applied state is
    left. The exception propagates (NO ERROR BYPASSING), but the op_id is left
    CLEAN -- a subsequent retry re-claims and succeeds.
    """
    state = _RepoState()
    _resolvable_standard_ctx(state)

    class _ExplodingThenAdmittedDispatcher:
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
                raise RuntimeError("dispatch boom (mid-flight)")
            return _admitted_dispatch()

    dispatcher = _ExplodingThenAdmittedDispatcher()
    service = ControlPlaneRuntimeService(
        repository=_repository(state),
        phase_dispatcher=dispatcher,  # type: ignore[arg-type]
    )
    request = _setup_request("op-boom")

    # First call: the dispatch raises after the claim -> the claim is released
    # and the exception propagates. NOTHING half-applied, and NO op is stored.
    with pytest.raises(RuntimeError, match="dispatch boom"):
        service.start_phase(run_id="run-100", phase="setup", request=request)
    assert "op-boom" not in state.operations, (
        "the claim must be released on an exception (no stranded op_id)"
    )
    assert state.bindings == {}, "no half-applied session binding"
    assert state.locks == {}, "no half-applied lock-records"
    assert state.events == [], "no half-applied lifecycle events"

    # Retry: the op_id is reclaimable; the retry dispatches and commits.
    result = service.start_phase(run_id="run-100", phase="setup", request=request)
    assert result.status == "committed"
    assert dispatcher.calls == 2
    assert state.operations["op-boom"].status == "committed"


# ---------------------------------------------------------------------------
# ERROR-6: status-rewrite to "replayed" re-runs the model invariant
# ---------------------------------------------------------------------------


def test_replay_revalidates_edge_bundle_invariant() -> None:
    """ERROR-6: a tampered stored payload (replayed + edge_bundle None) is rejected.

    ``model_copy(update={"status": "replayed"})`` would NOT re-run validators, so a
    stored ``committed`` payload that was tampered to drop its ``edge_bundle``
    could be silently surfaced as a valid ``replayed`` success. The hardened
    rebuild revalidates via ``model_validate``, so the edge_bundle/status invariant
    is re-enforced and the tampered payload raises.
    """
    state = _RepoState()
    now = datetime(2026, 4, 22, 10, 0, tzinfo=UTC)
    # A tampered stored payload: a (formerly committed) success with NO edge_bundle.
    state.operations["op-tampered"] = ControlPlaneOperationRecord(
        op_id="op-tampered",
        project_key="tenant-a",
        story_id="AG3-100",
        run_id="run-100",
        session_id="sess-001",
        operation_kind="phase_start",
        phase="setup",
        status="committed",
        response_payload={
            "status": "committed",
            "op_id": "op-tampered",
            "operation_kind": "phase_start",
            "run_id": "run-100",
            "phase": "setup",
            "edge_bundle": None,
        },
        created_at=now,
        updated_at=now,
    )
    service = ControlPlaneRuntimeService(repository=_repository(state))

    with pytest.raises(ValidationError):
        service.get_operation("op-tampered")


# ---------------------------------------------------------------------------
# AG3-054 PART A: leased, owner-scoped claim (lease/CAS protocol)
# ---------------------------------------------------------------------------


class _Clock:
    """A deterministic, injectable lease clock (advanceable in tests)."""

    def __init__(self, start: datetime) -> None:
        self._now = start

    def __call__(self) -> datetime:
        return self._now

    def advance(self, delta: timedelta) -> None:
        self._now += delta


def _owner_token(label: str) -> str:
    """Build a deterministic, UUID-shaped owner token from a readable label (#5).

    WARNING-5 (#5) validates the minted owner token at the seam: it must be a
    non-empty, UUID-shaped token. Tests still want stable, readable owner labels,
    so this derives a deterministic ``owner-<uuid5(label)>`` -- distinct labels map
    to distinct tokens, and the same label maps to the same token across a test.
    """
    import uuid as _uuid

    return f"owner-{_uuid.uuid5(_uuid.NAMESPACE_OID, label).hex}"


class _TokenSequence:
    """A deterministic owner-token factory (one fixed token per service).

    Tokens are passed as readable labels and converted to UUID-shaped owner
    tokens (#5) so the seam validation accepts them while tests stay readable.
    """

    def __init__(self, *labels: str) -> None:
        self._tokens = [_owner_token(label) for label in labels]
        self._idx = 0

    def __call__(self) -> str:
        token = self._tokens[min(self._idx, len(self._tokens) - 1)]
        self._idx += 1
        return token


def _leased_service(
    state: _RepoState,
    *,
    token: str,
    clock: _Clock,
    dispatcher: _StubDispatcher | None = None,
) -> ControlPlaneRuntimeService:
    return ControlPlaneRuntimeService(
        repository=_repository(state),
        phase_dispatcher=(dispatcher or _StubDispatcher(_admitted_dispatch())),  # type: ignore[arg-type]
        now_fn=clock,
        token_factory=_TokenSequence(token),
    )


def test_concurrent_claims_one_wins_loser_gets_in_flight_rejection_mid_dispatch() -> (
    None
):
    """PART A: two same-op_id claims -> ONE wins, the loser is rejected in-flight.

    The winner is simulated as STILL mid-dispatch (its claim not yet finalized):
    the loser must get a fail-closed "operation in flight, retry" rejection and
    must NOT steal the claim or dispatch (no double dispatch). The winner's claim
    row is left intact for it to finalize.
    """
    state = _RepoState()
    _resolvable_standard_ctx(state)
    clock = _Clock(datetime(2026, 6, 7, 10, 0, tzinfo=UTC))

    # Winner A wins the claim but is held mid-dispatch (we do not finalize it):
    # simulate by directly placing A's live claim, then a real B start_phase.
    winner_claim = ControlPlaneOperationRecord(
        op_id="op-race-live",
        project_key="tenant-a",
        story_id="AG3-100",
        run_id="run-100",
        session_id="sess-001",
        operation_kind="phase_start",
        phase="setup",
        status="claimed",
        response_payload={},
        created_at=clock(),
        updated_at=clock(),
        claimed_by="owner-A",
        claimed_at=clock(),  # fresh -> NOT expired
    )
    state.operations["op-race-live"] = winner_claim

    loser_dispatcher = _StubDispatcher(_admitted_dispatch())
    loser = _leased_service(
        state, token="owner-B", clock=clock, dispatcher=loser_dispatcher
    )

    result = loser.start_phase(
        run_id="run-100", phase="setup", request=_setup_request("op-race-live")
    )

    # The loser is rejected in-flight; it never dispatched and never stole.
    assert result.status == "rejected"
    assert result.phase_dispatch is not None
    assert "in flight" in (result.phase_dispatch.rejection_reason or "").lower()
    assert loser_dispatcher.calls == [], "the loser must NOT dispatch"
    # The winner's live claim is untouched (owner-A still holds it).
    assert state.operations["op-race-live"].claimed_by == "owner-A"
    assert state.operations["op-race-live"].status == "claimed"


def test_winner_finalizes_then_loser_retry_replays_terminal_result() -> None:
    """PART A: winner finalizes -> a later same-op_id call replays the terminal row."""
    state = _RepoState()
    _resolvable_standard_ctx(state)
    clock = _Clock(datetime(2026, 6, 7, 10, 0, tzinfo=UTC))
    winner = _leased_service(state, token="owner-A", clock=clock)

    committed = winner.start_phase(
        run_id="run-100", phase="setup", request=_setup_request("op-finalize-replay")
    )
    assert committed.status == "committed"
    assert state.operations["op-finalize-replay"].status == "committed"
    # The finalized terminal row carries NO live owner anymore.
    assert state.operations["op-finalize-replay"].claimed_by is None

    loser_dispatcher = _StubDispatcher(_admitted_dispatch())
    loser = _leased_service(
        state, token="owner-B", clock=clock, dispatcher=loser_dispatcher
    )
    replay = loser.start_phase(
        run_id="run-100", phase="setup", request=_setup_request("op-finalize-replay")
    )

    assert replay.status == "replayed"
    assert replay.op_id == "op-finalize-replay"
    assert loser_dispatcher.calls == [], "a replay never re-dispatches"


def test_owner_release_is_ownership_scoped_and_does_not_delete_foreign_claim() -> None:
    """PART A: owner A's release deletes ONLY A's claim; B's claim/row is untouched.

    After B took over (the expiry case), A's release/finalize must be a no-op (CAS
    rowcount 0) and must NOT delete B's row or result.
    """
    state = _RepoState()
    repo = _repository(state)
    clock = _Clock(datetime(2026, 6, 7, 10, 0, tzinfo=UTC))

    # B holds the live claim.
    b_claim = ControlPlaneOperationRecord(
        op_id="op-ownership",
        project_key="tenant-a",
        story_id="AG3-100",
        run_id="run-100",
        session_id="sess-001",
        operation_kind="phase_start",
        phase="setup",
        status="claimed",
        response_payload={},
        created_at=clock(),
        updated_at=clock(),
        claimed_by="owner-B",
        claimed_at=clock(),
    )
    state.operations["op-ownership"] = b_claim

    # A (a stale former owner) tries an ownership-scoped release: it is a no-op.
    repo.release_operation("op-ownership", owner_token="owner-A")
    assert "op-ownership" in state.operations, "A must not delete B's claim"
    assert state.operations["op-ownership"].claimed_by == "owner-B"

    # A's ownership-scoped finalize is also a no-op (CAS rowcount 0).
    a_terminal = ControlPlaneOperationRecord(
        op_id="op-ownership",
        project_key="tenant-a",
        story_id="AG3-100",
        run_id="run-100",
        session_id="sess-001",
        operation_kind="phase_start",
        phase="setup",
        status="committed",
        response_payload={"forged": "by-A"},
        created_at=clock(),
        updated_at=clock(),
    )
    assert repo.finalize_operation(a_terminal, owner_token="owner-A") is False
    assert state.operations["op-ownership"].status == "claimed"
    assert state.operations["op-ownership"].claimed_by == "owner-B"


def test_expired_claim_is_taken_over_via_cas_non_expired_is_refused() -> None:
    """PART A: an EXPIRED foreign claim is taken over; a NON-expired one is refused."""
    state = _RepoState()
    _resolvable_standard_ctx(state)
    start = datetime(2026, 6, 7, 10, 0, tzinfo=UTC)

    def _seed_foreign_claim(op_id: str, *, claimed_at: datetime) -> None:
        state.operations[op_id] = ControlPlaneOperationRecord(
            op_id=op_id,
            project_key="tenant-a",
            story_id="AG3-100",
            run_id="run-100",
            session_id="sess-001",
            operation_kind="phase_start",
            phase="setup",
            status="claimed",
            response_payload={},
            created_at=claimed_at,
            updated_at=claimed_at,
            claimed_by="owner-crashed",
            claimed_at=claimed_at,
        )

    # NON-expired foreign claim (1 minute old): takeover refused -> in-flight reject.
    _seed_foreign_claim("op-live", claimed_at=start)
    clock_live = _Clock(start + timedelta(minutes=1))
    live_dispatcher = _StubDispatcher(_admitted_dispatch())
    refused = _leased_service(
        state, token="owner-new", clock=clock_live, dispatcher=live_dispatcher
    ).start_phase(run_id="run-100", phase="setup", request=_setup_request("op-live"))
    assert refused.status == "rejected"
    assert live_dispatcher.calls == [], "a live claim must not be stolen"
    assert state.operations["op-live"].claimed_by == "owner-crashed"

    # EXPIRED foreign claim (10 minutes old): CAS takeover succeeds -> commit.
    _seed_foreign_claim("op-expired", claimed_at=start)
    clock_expired = _Clock(start + timedelta(minutes=10))
    takeover_dispatcher = _StubDispatcher(_admitted_dispatch())
    taken = _leased_service(
        state, token="owner-new", clock=clock_expired, dispatcher=takeover_dispatcher
    ).start_phase(
        run_id="run-100", phase="setup", request=_setup_request("op-expired")
    )
    assert taken.status == "committed"
    assert takeover_dispatcher.calls == ["setup"]
    assert state.operations["op-expired"].status == "committed"
    assert state.operations["op-expired"].claimed_by is None


def test_exception_after_claim_releases_only_my_claim_and_retry_succeeds() -> None:
    """PART A: an exception after the claim releases MY claim; a retry then commits.

    No half-applied binding/lock/event survives, and the released claim is
    reclaimable by the same owner-token-injected service on retry.
    """
    state = _RepoState()
    _resolvable_standard_ctx(state)
    clock = _Clock(datetime(2026, 6, 7, 10, 0, tzinfo=UTC))

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
                raise RuntimeError("dispatch boom (leased)")
            return _admitted_dispatch()

    dispatcher = _ExplodingThenAdmitted()
    service = ControlPlaneRuntimeService(
        repository=_repository(state),
        phase_dispatcher=dispatcher,  # type: ignore[arg-type]
        now_fn=clock,
        token_factory=_TokenSequence("owner-A", "owner-A"),
    )
    request = _setup_request("op-leased-boom")

    with pytest.raises(RuntimeError, match="dispatch boom"):
        service.start_phase(run_id="run-100", phase="setup", request=request)
    # MY claim was released -- no stranded op, no half-applied state.
    assert "op-leased-boom" not in state.operations
    assert state.bindings == {}
    assert state.locks == {}
    assert state.events == []

    # Retry reclaims and commits.
    result = service.start_phase(run_id="run-100", phase="setup", request=request)
    assert result.status == "committed"
    assert dispatcher.calls == 2
    assert state.operations["op-leased-boom"].status == "committed"


# ---------------------------------------------------------------------------
# AG3-054 PART C (#3): admission evidence is RUN-scoped, not story-scoped
# ---------------------------------------------------------------------------


def _committed_op_for_run(
    *,
    op_id: str,
    run_id: str,
    project_key: str = "tenant-a",
    story_id: str = "AG3-100",
) -> ControlPlaneOperationRecord:
    now = datetime(2026, 6, 7, 10, 0, tzinfo=UTC)
    return ControlPlaneOperationRecord(
        op_id=op_id,
        project_key=project_key,
        story_id=story_id,
        run_id=run_id,
        session_id="sess-001",
        operation_kind="phase_start",
        phase="setup",
        status="committed",
        response_payload={},
        created_at=now,
        updated_at=now,
    )


def test_new_run_not_admitted_by_old_runs_evidence_for_same_story() -> None:
    """PART C (#3): a NEW run is NOT admitted by an OLD run's committed op/binding.

    Admission is RUN-scoped: a committed start op for ``run-OLD`` (same story) and a
    binding for ``run-OLD`` must NOT admit a complete/fail/closure for ``run-NEW``.
    The prior story-scoped phase-state evidence is gone, so a new run with only
    old-run evidence is fail-closed REJECTED.
    """
    state = _RepoState()
    state.story_contexts[("tenant-a", "AG3-100")] = _story_context(
        project_key="tenant-a",
        story_id="AG3-100",
        mode=WireStoryMode.STANDARD,
    )
    # Only OLD-run evidence exists (committed op + binding for run-OLD).
    state.operations["op-old"] = _committed_op_for_run(op_id="op-old", run_id="run-OLD")
    _seed_admitted_run(state, run_id="run-OLD")
    service = ControlPlaneRuntimeService(repository=_repository(state))

    completed = service.complete_phase(
        run_id="run-NEW",
        phase="implementation",
        request=_phase_request("op-complete-new-run"),
    )
    failed = service.fail_phase(
        run_id="run-NEW",
        phase="implementation",
        request=_phase_request("op-fail-new-run"),
    )
    closed = service.complete_closure(
        run_id="run-NEW",
        request=ClosureCompleteRequest(
            project_key="tenant-a",
            story_id="AG3-100",
            session_id="sess-001",
            op_id="op-closure-new-run",
        ),
    )

    assert completed.status == "rejected"
    assert failed.status == "rejected"
    assert closed.status == "rejected"
    assert "op-complete-new-run" not in state.operations
    assert "op-fail-new-run" not in state.operations
    assert "op-closure-new-run" not in state.operations


def test_new_run_admitted_by_committed_op_for_that_run() -> None:
    """PART C (#3): a committed op for THIS run admits complete/fail/closure.

    A fast start (which materializes no binding) leaves a committed start op for
    the run; that run-matched committed op is sufficient run-scoped admission
    evidence even with no session binding.
    """
    state = _RepoState()
    state.story_contexts[("tenant-a", "AG3-100")] = _story_context(
        project_key="tenant-a",
        story_id="AG3-100",
        mode=WireStoryMode.STANDARD,
    )
    state.operations["op-new-start"] = _committed_op_for_run(
        op_id="op-new-start", run_id="run-NEW"
    )
    service = ControlPlaneRuntimeService(repository=_repository(state))

    completed = service.complete_phase(
        run_id="run-NEW",
        phase="implementation",
        request=_phase_request("op-complete-admitted-by-op"),
    )

    assert completed.status == "committed"
    assert "op-complete-admitted-by-op" in state.operations


def test_committed_story_exit_preferentially_blocks_same_run_admission() -> None:
    """FK-58: story_exit terminal marker wins over binding/start evidence."""

    state = _RepoState()
    state.story_contexts[("tenant-a", "AG3-100")] = _story_context(
        project_key="tenant-a",
        story_id="AG3-100",
        mode=WireStoryMode.STANDARD,
    )
    _seed_admitted_run(state, run_id="run-100")
    state.operations["op-start"] = _committed_op_for_run(
        op_id="op-start",
        run_id="run-100",
    )
    state.operations["exit-1"] = _committed_op(
        op_id="exit-1",
        run_id="run-100",
        operation_kind="story_exit",
        phase=None,
    )
    service = ControlPlaneRuntimeService(repository=_repository(state))

    completed = service.complete_phase(
        run_id="run-100",
        phase="implementation",
        request=_phase_request("op-complete-after-exit"),
    )
    closed = service.complete_closure(
        run_id="run-100",
        request=ClosureCompleteRequest(
            project_key="tenant-a",
            story_id="AG3-100",
            session_id="sess-001",
            op_id="op-closure-after-exit",
        ),
    )

    assert completed.status == "rejected"
    assert closed.status == "rejected"
    assert "op-complete-after-exit" not in state.operations
    assert "op-closure-after-exit" not in state.operations
    assert state.bindings["sess-001"].run_id == "run-100"


def _committed_op(
    *,
    op_id: str,
    run_id: str,
    operation_kind: str,
    phase: str | None,
) -> ControlPlaneOperationRecord:
    now = datetime(2026, 6, 7, 10, 0, tzinfo=UTC)
    return ControlPlaneOperationRecord(
        op_id=op_id,
        project_key="tenant-a",
        story_id="AG3-100",
        run_id=run_id,
        session_id="sess-001",
        operation_kind=operation_kind,
        phase=phase,
        status="committed",
        response_payload={},
        created_at=now,
        updated_at=now,
    )


def test_committed_phase_complete_alone_does_not_admit_run() -> None:
    """ERROR-3 (#3): a committed phase_complete (no committed setup start) is no proof.

    Admission evidence must prove an admitted START. A committed ``phase_complete``
    for the run with NO committed setup ``phase_start`` must NOT bootstrap admission
    -- a later complete/fail/closure for the run is fail-closed REJECTED.
    """
    state = _RepoState()
    state.story_contexts[("tenant-a", "AG3-100")] = _story_context(
        project_key="tenant-a",
        story_id="AG3-100",
        mode=WireStoryMode.STANDARD,
    )
    # Only a committed phase_complete exists -- NO committed setup phase_start.
    state.operations["op-stray-complete"] = _committed_op(
        op_id="op-stray-complete",
        run_id="run-NEW",
        operation_kind="phase_complete",
        phase="implementation",
    )
    service = ControlPlaneRuntimeService(repository=_repository(state))

    rejected = service.complete_phase(
        run_id="run-NEW",
        phase="implementation",
        request=_phase_request("op-complete-not-admitted"),
    )

    assert rejected.status == "rejected"
    assert "op-complete-not-admitted" not in state.operations


def test_committed_setup_phase_start_admits_run() -> None:
    """ERROR-3 (#3) positive: a committed setup phase_start DOES admit the run."""
    state = _RepoState()
    state.story_contexts[("tenant-a", "AG3-100")] = _story_context(
        project_key="tenant-a",
        story_id="AG3-100",
        mode=WireStoryMode.STANDARD,
    )
    state.operations["op-setup-start"] = _committed_op(
        op_id="op-setup-start",
        run_id="run-NEW",
        operation_kind="phase_start",
        phase="setup",
    )
    service = ControlPlaneRuntimeService(repository=_repository(state))

    completed = service.complete_phase(
        run_id="run-NEW",
        phase="implementation",
        request=_phase_request("op-complete-admitted-by-setup"),
    )

    assert completed.status == "committed"
    assert "op-complete-admitted-by-setup" in state.operations


# ---------------------------------------------------------------------------
# ERROR-1 (#1): a loser whose lease was taken over writes NO side effects
# ---------------------------------------------------------------------------


def test_loser_after_takeover_materializes_no_side_effects() -> None:
    """ERROR-1 (#1): owner A (lease taken over by B) writes NO binding/lock/event.

    Owner A's dispatch outran its lease TTL; owner B took over the expired claim AND
    finalized it (B's terminal result + B's side effects stand). When A finally
    returns to finalize, the ownership CAS affects ZERO rows, so A materializes NO
    binding, NO locks and NO events -- no duplicate/conflicting canonical side
    effect. A's late return surfaces B's committed terminal row as a REPLAY.
    """
    state = _RepoState()
    _resolvable_standard_ctx(state)
    clock = _Clock(datetime(2026, 6, 7, 10, 0, tzinfo=UTC))
    a_token = _owner_token("A")

    # A wins the claim (its own placeholder), then is held mid-dispatch.
    a_service = ControlPlaneRuntimeService(
        repository=_repository(state),
        phase_dispatcher=_StubDispatcher(_admitted_dispatch()),  # type: ignore[arg-type]
        now_fn=clock,
        token_factory=_TokenSequence("A"),
    )
    op_id = "op-takeover-loser"
    request = _setup_request(op_id)
    # A claims (insert-if-absent) -- we drive only A's claim, NOT its finalize, by
    # seeding A's live claim placeholder directly (simulating A mid-dispatch).
    placeholder = ControlPlaneOperationRecord(
        op_id=op_id,
        project_key="tenant-a",
        story_id="AG3-100",
        run_id="run-100",
        session_id="sess-001",
        operation_kind="phase_start",
        phase="setup",
        status="claimed",
        response_payload={},
        created_at=clock(),
        updated_at=clock(),
        claimed_by=a_token,
        claimed_at=clock(),
    )
    state.operations[op_id] = placeholder

    # B takes over the EXPIRED claim (10 min later) and finalizes it fully.
    clock_b = _Clock(datetime(2026, 6, 7, 10, 10, tzinfo=UTC))
    b_service = ControlPlaneRuntimeService(
        repository=_repository(state),
        phase_dispatcher=_StubDispatcher(_admitted_dispatch()),  # type: ignore[arg-type]
        now_fn=clock_b,
        token_factory=_TokenSequence("B"),
    )
    b_result = b_service.start_phase(run_id="run-100", phase="setup", request=request)
    assert b_result.status == "committed"
    # B's terminal result + B's side effects stand.
    assert state.operations[op_id].status == "committed"
    assert state.operations[op_id].claimed_by is None
    b_binding_version = state.bindings["sess-001"].binding_version
    b_lock_version = state.locks[
        ("tenant-a", "AG3-100", "run-100", "story_execution")
    ].binding_version
    b_event_count = len(state.events)
    assert b_event_count == 2  # binding_created + regime_activated (B's)

    # Now A returns to finalize its (lost) claim. Its CAS affects zero rows, so it
    # materializes NOTHING and surfaces B's terminal row as a replay.
    a_result = a_service._finalize_start_phase(  # noqa: SLF001 -- drive the late path
        run_id="run-100",
        phase="setup",
        request=request,
        owner_token=a_token,
        # WARNING-4 (#4): A's own RAW lease epoch -- its CAS still loses (the row is
        # now B's terminal), so A materializes nothing and replays B's result.
        owner_claimed_at=datetime(2026, 6, 7, 10, 0, tzinfo=UTC).isoformat(),
        phase_dispatch=_admitted_dispatch(),
    )

    assert a_result.status == "replayed"
    # NO duplicate / conflicting side effects: binding/lock unchanged, no new events.
    assert state.bindings["sess-001"].binding_version == b_binding_version
    assert (
        state.locks[
            ("tenant-a", "AG3-100", "run-100", "story_execution")
        ].binding_version
        == b_lock_version
    )
    assert len(state.events) == b_event_count, "the loser must emit no extra events"
    # B's terminal op is untouched.
    assert state.operations[op_id].status == "committed"


# ---------------------------------------------------------------------------
# ERROR-2 (#2): fresh-setup-start is RUN-scoped, not story-scoped
# ---------------------------------------------------------------------------


def test_new_run_setup_with_only_old_run_evidence_is_fresh_and_rejected() -> None:
    """ERROR-2 (#2): run-NEW setup is FRESH (guard fires) despite run-OLD evidence.

    A new run's setup whose ``StoryContext`` is unresolvable (admission cannot be
    evaluated) and that carries ONLY run-OLD evidence (a committed setup start +
    binding for run-OLD of the SAME story) must be classified FRESH -> the pre-start
    Approved+READY guard fires -> fail-closed REJECTED. The OLD-run evidence must
    NOT make run-NEW "not fresh" (the FAIL-OPEN this fix closes).
    """
    state = _RepoState()  # no story_contexts entry => dispatch returns None
    # Only run-OLD evidence: a committed setup start + a binding for run-OLD.
    state.operations["op-old-start"] = _committed_op(
        op_id="op-old-start",
        run_id="run-OLD",
        operation_kind="phase_start",
        phase="setup",
    )
    _seed_admitted_run(state, run_id="run-OLD")
    service = ControlPlaneRuntimeService(repository=_repository(state))

    result = service.start_phase(
        run_id="run-NEW",
        phase="setup",
        request=_setup_request("op-new-run-setup"),
    )

    assert result.status == "rejected", "run-NEW with only old-run evidence is FRESH"
    assert result.edge_bundle is None
    assert result.phase_dispatch is not None
    assert result.phase_dispatch.dispatched is False
    # Fail-closed: nothing materialized, no op stored for run-NEW.
    assert "op-new-run-setup" not in state.operations
    # The run-OLD binding under sess-001 is for a DIFFERENT run -> not run-NEW
    # evidence; it is left untouched.
    assert state.bindings["sess-001"].run_id == "run-OLD"


def test_runtime_threads_run_scoped_admission_into_dispatcher() -> None:
    """ERROR-1: the runtime passes RUN-scoped ``run_admitted`` to the dispatcher.

    The reset-escalation hazard, exercised through the resolvable-ctx path (where
    the real dispatcher runs): a story whose OLD run left run-matched evidence
    (committed setup start + binding for run-OLD) gets a NEW run posting setup. The
    runtime must compute admission RUN-scoped for run-NEW (no run-matched evidence
    => NOT admitted) and thread ``run_admitted=False`` into the dispatcher, so the
    dispatcher classifies the setup FRESH and fires the pre-start guard. An OLD
    run's evidence must NOT flip run-NEW to admitted.
    """
    state = _RepoState()
    state.story_contexts[("tenant-a", "AG3-100")] = _story_context(
        project_key="tenant-a",
        story_id="AG3-100",
        mode=WireStoryMode.STANDARD,
        project_root=Path("T:/projects/tenant-a"),
    )
    # Only run-OLD evidence exists (committed setup start + binding for run-OLD).
    state.operations["op-old-start"] = _committed_op(
        op_id="op-old-start",
        run_id="run-OLD",
        operation_kind="phase_start",
        phase="setup",
    )
    _seed_admitted_run(state, run_id="run-OLD")
    # The stub records the ``run_admitted`` flag the runtime threaded in. It
    # returns a rejection so the runtime materializes nothing (fail-closed).
    dispatcher = _StubDispatcher(
        _rejected_dispatch("StoryStatus is not Approved (Tor 1)."),
    )
    service = ControlPlaneRuntimeService(
        repository=_repository(state),
        phase_dispatcher=dispatcher,  # type: ignore[arg-type]
    )

    result = service.start_phase(
        run_id="run-NEW",
        phase="setup",
        request=_setup_request("op-new-run-resolvable"),
    )

    # The runtime computed admission RUN-scoped for run-NEW => NOT admitted, and
    # threaded that into the dispatcher (the fix: not the OLD run's evidence).
    assert dispatcher.run_admitted_calls == [False]
    # The fresh setup was guard-rejected -> fail-closed, nothing materialized.
    assert result.status == "rejected"
    assert "op-new-run-resolvable" not in state.operations
    assert state.bindings.get("sess-001") is not None  # the OLD run's binding only
    assert state.bindings["sess-001"].run_id == "run-OLD"


def test_runtime_threads_run_admitted_true_for_its_own_committed_start() -> None:
    """ERROR-1: an admitted run gets ``run_admitted=True`` threaded to the dispatcher.

    When THIS run already has a committed setup start (run-matched evidence), the
    runtime threads ``run_admitted=True`` so the dispatcher does NOT re-guard it.
    """
    state = _RepoState()
    state.story_contexts[("tenant-a", "AG3-100")] = _story_context(
        project_key="tenant-a",
        story_id="AG3-100",
        mode=WireStoryMode.STANDARD,
        project_root=Path("T:/projects/tenant-a"),
    )
    state.operations["op-this-run-start"] = _committed_op(
        op_id="op-this-run-start",
        run_id="run-100",
        operation_kind="phase_start",
        phase="setup",
    )
    dispatcher = _StubDispatcher(_admitted_dispatch())
    service = ControlPlaneRuntimeService(
        repository=_repository(state),
        phase_dispatcher=dispatcher,  # type: ignore[arg-type]
    )

    result = service.start_phase(
        run_id="run-100",
        phase="setup",
        request=_setup_request("op-readmit-this-run"),
    )

    assert dispatcher.run_admitted_calls == [True]
    assert result.status == "committed"


def test_new_run_setup_with_its_own_committed_start_is_not_fresh() -> None:
    """ERROR-2 (#2): a run with its OWN prior committed setup start is not re-guarded.

    When THIS run already has a committed setup ``phase_start`` (run-matched
    admission evidence), the setup start is NOT fresh, so even an unresolvable ctx
    does NOT re-fire the fresh-setup rejection -- it keeps the AG3-018
    fail-closed-to-standard path (admitted run, no double guard).
    """
    state = _RepoState()  # unresolvable ctx => dispatch returns None
    state.operations["op-this-run-start"] = _committed_op(
        op_id="op-this-run-start",
        run_id="run-100",
        operation_kind="phase_start",
        phase="setup",
    )
    service = ControlPlaneRuntimeService(repository=_repository(state))

    result = service.start_phase(
        run_id="run-100",
        phase="setup",
        request=_setup_request("op-not-fresh-setup"),
    )

    # Not fresh -> no fresh-setup rejection; the run was already admitted, so the
    # AG3-018 fail-closed-to-standard materialization runs and commits.
    assert result.status == "committed"
    assert result.edge_bundle is not None
    assert result.edge_bundle.current.operating_mode == "story_execution"


# ---------------------------------------------------------------------------
# WARNING-4 (#4): a naive / malformed claimed_at is treated as EXPIRED
# ---------------------------------------------------------------------------


def test_naive_claimed_at_is_treated_as_expired_takeover_proceeds() -> None:
    """WARNING-4 (#4): a NAIVE claimed_at expires (takeover proceeds), no TypeError.

    A ``claimed`` row whose ``claimed_at`` is tz-NAIVE (e.g. an imported/foreign
    write) must NOT crash ``aware_now - naive_claimed_at`` with a TypeError. The
    lease-expiry compare coerces both operands to aware UTC, treats the naive
    instant as a (past) UTC instant, and -- being older than the TTL -- as EXPIRED,
    so the takeover proceeds and the retry commits.
    """
    state = _RepoState()
    _resolvable_standard_ctx(state)
    naive_old = datetime(2026, 6, 7, 9, 0)  # tz-NAIVE, well older than the TTL
    state.operations["op-naive-claim"] = ControlPlaneOperationRecord(
        op_id="op-naive-claim",
        project_key="tenant-a",
        story_id="AG3-100",
        run_id="run-100",
        session_id="sess-001",
        operation_kind="phase_start",
        phase="setup",
        status="claimed",
        response_payload={},
        created_at=naive_old,
        updated_at=naive_old,
        claimed_by="owner-crashed-naive",
        claimed_at=naive_old,
    )
    clock = _Clock(datetime(2026, 6, 7, 10, 0, tzinfo=UTC))
    service = _leased_service(state, token="new-owner", clock=clock)

    result = service.start_phase(
        run_id="run-100", phase="setup", request=_setup_request("op-naive-claim")
    )

    assert result.status == "committed"
    assert state.operations["op-naive-claim"].status == "committed"


def test_malformed_claimed_at_via_mapper_is_treated_as_expired() -> None:
    """WARNING-4 (#4): an unparseable claimed_at maps to None (EXPIRED), no crash."""
    from agentkit.backend.state_backend.store.mappers import control_plane_op_row_to_record

    row = {
        "op_id": "op-bad-claimed-at",
        "project_key": "tenant-a",
        "story_id": "AG3-100",
        "run_id": "run-100",
        "session_id": "sess-001",
        "operation_kind": "phase_start",
        "phase": "setup",
        "status": "claimed",
        "response_json": "{}",
        "created_at": "2026-06-07T10:00:00+00:00",
        "updated_at": "2026-06-07T10:00:00+00:00",
        "claimed_by": "owner-x",
        "claimed_at": "not-a-timestamp",
    }

    record = control_plane_op_row_to_record(row)

    # Malformed lease instant -> None (treated as EXPIRED downstream, no raise).
    assert record.claimed_at is None


def test_aware_non_utc_claimed_at_is_normalized_to_utc() -> None:
    """WARNING-4 (#4): an aware non-UTC claimed_at is converted to aware UTC."""
    from agentkit.backend.state_backend.store.mappers import control_plane_op_row_to_record

    row = {
        "op_id": "op-offset-claimed-at",
        "project_key": "tenant-a",
        "story_id": "AG3-100",
        "run_id": "run-100",
        "session_id": "sess-001",
        "operation_kind": "phase_start",
        "phase": "setup",
        "status": "claimed",
        "response_json": "{}",
        "created_at": "2026-06-07T12:00:00+02:00",
        "updated_at": "2026-06-07T12:00:00+02:00",
        "claimed_by": "owner-x",
        "claimed_at": "2026-06-07T12:00:00+02:00",
    }

    record = control_plane_op_row_to_record(row)

    assert record.claimed_at is not None
    assert record.claimed_at.tzinfo is not None
    assert record.claimed_at.utcoffset() == timedelta(0)
    assert record.claimed_at == datetime(2026, 6, 7, 10, 0, tzinfo=UTC)


# ---------------------------------------------------------------------------
# WARNING-5 (#5): the owner token is validated at the seam (no cross-match)
# ---------------------------------------------------------------------------


def test_invalid_owner_token_is_rejected_at_the_seam() -> None:
    """WARNING-5 (#5): an empty / non-UUID-shaped owner token is rejected fail-closed."""
    from agentkit.backend.exceptions import ConfigError

    state = _RepoState()
    _resolvable_standard_ctx(state)

    for bad_token in ("", "   ", "owner-A", "not-a-uuid", "owner-"):
        service = ControlPlaneRuntimeService(
            repository=_repository(state),
            phase_dispatcher=_StubDispatcher(_admitted_dispatch()),  # type: ignore[arg-type]
            token_factory=lambda token=bad_token: token,
        )
        with pytest.raises(ConfigError, match="owner token is invalid"):
            service.start_phase(
                run_id="run-100",
                phase="setup",
                request=_setup_request(f"op-bad-token-{bad_token or 'empty'}"),
            )
    # No op was ever claimed/committed under an invalid token.
    assert state.operations == {}


def test_valid_uuid_shaped_owner_token_is_accepted() -> None:
    """WARNING-5 (#5): a valid UUID-shaped token (bare or owner-prefixed) is accepted."""
    import uuid as _uuid

    state = _RepoState()
    _resolvable_standard_ctx(state)
    bare_uuid = _uuid.uuid4().hex
    service = ControlPlaneRuntimeService(
        repository=_repository(state),
        phase_dispatcher=_StubDispatcher(_admitted_dispatch()),  # type: ignore[arg-type]
        token_factory=lambda: bare_uuid,
    )

    result = service.start_phase(
        run_id="run-100", phase="setup", request=_setup_request("op-valid-bare-uuid")
    )

    assert result.status == "committed"


def test_distinct_claims_cannot_cross_match_on_ownership() -> None:
    """WARNING-5 (#5): two distinct owner tokens cannot cross-match a foreign claim.

    With unique, UUID-shaped tokens, owner A's ownership-scoped release/finalize CAS
    can never match owner B's live claim -- B's claim row is untouched.
    """
    state = _RepoState()
    repo = _repository(state)
    clock = _Clock(datetime(2026, 6, 7, 10, 0, tzinfo=UTC))
    a_token = _owner_token("A")
    b_token = _owner_token("B")
    assert a_token != b_token

    # B holds the live claim.
    state.operations["op-cross"] = ControlPlaneOperationRecord(
        op_id="op-cross",
        project_key="tenant-a",
        story_id="AG3-100",
        run_id="run-100",
        session_id="sess-001",
        operation_kind="phase_start",
        phase="setup",
        status="claimed",
        response_payload={},
        created_at=clock(),
        updated_at=clock(),
        claimed_by=b_token,
        claimed_at=clock(),
    )

    # A's release is a no-op (distinct token) -> B's claim survives.
    repo.release_operation("op-cross", owner_token=a_token)
    assert state.operations["op-cross"].claimed_by == b_token
    # A's finalize-start-phase is also a no-op and writes NO side effects.
    a_terminal = ControlPlaneOperationRecord(
        op_id="op-cross",
        project_key="tenant-a",
        story_id="AG3-100",
        run_id="run-100",
        session_id="sess-001",
        operation_kind="phase_start",
        phase="setup",
        status="committed",
        response_payload={"forged": "by-A"},
        created_at=clock(),
        updated_at=clock(),
    )
    assert (
        repo.finalize_start_phase(
            a_terminal, owner_token=a_token, binding=None, locks=(), events=()
        )
        is False
    )
    assert state.operations["op-cross"].claimed_by == b_token
    assert state.operations["op-cross"].status == "claimed"
    assert state.bindings == {}
    assert state.events == []
