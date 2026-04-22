from __future__ import annotations

from datetime import UTC, datetime

from agentkit.control_plane.models import (
    ClosureCompleteRequest,
    PhaseMutationRequest,
    ProjectEdgeSyncRequest,
)
from agentkit.control_plane.runtime import (
    ControlPlaneRuntimeRepository,
    ControlPlaneRuntimeService,
)
from agentkit.state_backend import (
    ControlPlaneOperationRecord,
    ExecutionEventRecord,
    SessionRunBindingRecord,
    StoryExecutionLockRecord,
)


class _RepoState:
    def __init__(self) -> None:
        self.operations: dict[str, ControlPlaneOperationRecord] = {}
        self.bindings: dict[str, SessionRunBindingRecord] = {}
        self.locks: dict[tuple[str, str, str], StoryExecutionLockRecord] = {}
        self.events: list[ExecutionEventRecord] = []


def _repository(state: _RepoState) -> ControlPlaneRuntimeRepository:
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
        delete_binding=lambda session_id: state.bindings.pop(session_id, None),
        load_lock=lambda project_key, story_id, run_id: state.locks.get(
            (project_key, story_id, run_id),
        ),
        save_lock=lambda record: state.locks.__setitem__(
            (record.project_key, record.story_id, record.run_id),
            record,
        ),
        append_event=state.events.append,
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
    assert "sess-001" in state.bindings
    assert ("tenant-a", "AG3-100", "run-100") in state.locks
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
