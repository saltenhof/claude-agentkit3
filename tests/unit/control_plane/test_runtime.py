from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

from agentkit.control_plane.models import (
    ClosureCompleteRequest,
    PhaseMutationRequest,
    ProjectEdgeSyncRequest,
)
from agentkit.control_plane.records import (
    ControlPlaneOperationRecord,
    SessionRunBindingRecord,
)
from agentkit.control_plane.repository import ControlPlaneRuntimeRepository
from agentkit.control_plane.runtime import ControlPlaneRuntimeService
from agentkit.core_types import StoryMode
from agentkit.story_context_manager.models import StoryContext
from agentkit.story_context_manager.story_model import WireStoryMode
from agentkit.story_context_manager.types import StoryType

if TYPE_CHECKING:
    from agentkit.governance.guard_system.records import StoryExecutionLockRecord
    from agentkit.telemetry.contract.records import ExecutionEventRecord


class _RepoState:
    def __init__(self) -> None:
        self.operations: dict[str, ControlPlaneOperationRecord] = {}
        self.bindings: dict[str, SessionRunBindingRecord] = {}
        self.locks: dict[tuple[str, str, str, str], StoryExecutionLockRecord] = {}
        self.events: list[ExecutionEventRecord] = []
        #: Authoritative server-side StoryContext store keyed by
        #: ``(project_key, story_id)``. Empty => unresolvable (fail-closed).
        self.story_contexts: dict[tuple[str, str], StoryContext] = {}


def _repository(state: _RepoState) -> ControlPlaneRuntimeRepository:
    def _delete_binding(session_id: str) -> None:
        state.bindings.pop(session_id, None)

    return ControlPlaneRuntimeRepository(
        load_operation=state.operations.get,
        save_operation=lambda record: state.operations.__setitem__(
            record.op_id,
            record,
        ),
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
) -> StoryContext:
    return StoryContext(
        project_key=project_key,
        story_id=story_id,
        story_type=story_type,
        execution_route=StoryMode.EXECUTION,
        mode=mode,
    )


def test_start_phase_persists_binding_lock_and_operation() -> None:
    state = _RepoState()
    service = ControlPlaneRuntimeService(repository=_repository(state))

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
    service = ControlPlaneRuntimeService(repository=_repository(state))
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

    assert result.edge_bundle.current.operating_mode == "binding_invalid"
    assert result.run_id == "run-100"


def test_get_operation_returns_replayed_result() -> None:
    state = _RepoState()
    service = ControlPlaneRuntimeService(repository=_repository(state))
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
    """AG3-018 AC3/AC5: a fast story materializes no session/locks."""
    state = _RepoState()
    state.story_contexts[("tenant-a", "AG3-100")] = _story_context(
        project_key="tenant-a",
        story_id="AG3-100",
        mode=WireStoryMode.FAST,
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
    assert result.edge_bundle.current.operating_mode == "ai_augmented"
    assert result.edge_bundle.session is None
    assert result.edge_bundle.lock is None
    assert result.edge_bundle.qa_lock is None
    # No story_execution regime is entered, so no regime/ binding events fire.
    assert state.events == []


def test_standard_story_still_materializes_session_and_locks() -> None:
    """Standard stories are unchanged: full session + both locks materialized."""
    state = _RepoState()
    state.story_contexts[("tenant-a", "AG3-100")] = _story_context(
        project_key="tenant-a",
        story_id="AG3-100",
        mode=WireStoryMode.STANDARD,
    )
    service = ControlPlaneRuntimeService(repository=_repository(state))

    result = service.start_phase(
        run_id="run-100",
        phase="implementation",
        request=_fast_request(),
    )

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
    """
    state = _RepoState()
    state.story_contexts[("tenant-a", "AG3-100")] = _story_context(
        project_key="tenant-a",
        story_id="AG3-100",
        mode=WireStoryMode.STANDARD,
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
    assert result.edge_bundle.current.operating_mode == "story_execution"
    assert result.edge_bundle.lock is not None
    assert ("tenant-a", "AG3-100", "run-100", "story_execution") in state.locks


def test_unresolvable_mode_for_code_story_fails_closed() -> None:
    """Fail-closed: no authoritative StoryContext -> guards stay active.

    A missing store record must NEVER silently skip story-scoped guards; the
    run is treated as standard (full materialization), so a code story can never
    lose its guards on a lookup gap.
    """
    state = _RepoState()  # no story_contexts entry => unresolvable
    service = ControlPlaneRuntimeService(repository=_repository(state))

    result = service.start_phase(
        run_id="run-100",
        phase="implementation",
        request=_fast_request(),
    )

    assert result.edge_bundle.current.operating_mode == "story_execution"
    assert result.edge_bundle.lock is not None
    assert ("tenant-a", "AG3-100", "run-100", "story_execution") in state.locks
    assert ("tenant-a", "AG3-100", "run-100", "qa_artifact_write") in state.locks
