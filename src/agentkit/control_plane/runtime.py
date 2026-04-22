"""Control-plane services for run binding and project-edge sync."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Literal, cast

from agentkit.control_plane.models import (
    ClosureCompleteRequest,
    ControlPlaneMutationResult,
    EdgeBundle,
    EdgePointer,
    PhaseMutationRequest,
    ProjectEdgeSyncRequest,
    SessionRunBindingView,
    StoryExecutionLockView,
)
from agentkit.state_backend import (
    ControlPlaneOperationRecord,
    ExecutionEventRecord,
    SessionRunBindingRecord,
    StoryExecutionLockRecord,
    append_execution_event_global,
    delete_session_run_binding_global,
    load_control_plane_operation_global,
    load_session_run_binding_global,
    load_story_execution_lock_global,
    save_control_plane_operation_global,
    save_session_run_binding_global,
    save_story_execution_lock_global,
)
from agentkit.telemetry.events import EventType

if TYPE_CHECKING:
    from collections.abc import Callable

OperatingMode = Literal["ai_augmented", "story_execution", "binding_invalid"]
FreshnessClass = Literal["baseline_read", "guarded_read", "mutation"]

_SYNC_AFTER_BY_CLASS = {
    "baseline_read": timedelta(minutes=5),
    "guarded_read": timedelta(minutes=2),
    "mutation": timedelta(seconds=45),
}


@dataclass(frozen=True)
class ControlPlaneRuntimeRepository:
    """Persistence dependencies for runtime mutations and sync."""

    load_operation: Callable[[str], ControlPlaneOperationRecord | None] = (
        load_control_plane_operation_global
    )
    save_operation: Callable[[ControlPlaneOperationRecord], None] = (
        save_control_plane_operation_global
    )
    load_binding: Callable[[str], SessionRunBindingRecord | None] = (
        load_session_run_binding_global
    )
    save_binding: Callable[[SessionRunBindingRecord], None] = (
        save_session_run_binding_global
    )
    delete_binding: Callable[[str], None] = delete_session_run_binding_global
    load_lock: Callable[[str, str, str], StoryExecutionLockRecord | None] = (
        load_story_execution_lock_global
    )
    save_lock: Callable[[StoryExecutionLockRecord], None] = (
        save_story_execution_lock_global
    )
    append_event: Callable[[ExecutionEventRecord], None] = append_execution_event_global


class ControlPlaneRuntimeService:
    """Implement control-plane mutations with idempotent op replay."""

    def __init__(
        self,
        *,
        repository: ControlPlaneRuntimeRepository | None = None,
    ) -> None:
        self._repo = repository or ControlPlaneRuntimeRepository()

    def start_phase(
        self,
        *,
        run_id: str,
        phase: str,
        request: PhaseMutationRequest,
    ) -> ControlPlaneMutationResult:
        return self._mutate_phase(
            run_id=run_id,
            phase=phase,
            request=request,
            operation_kind="phase_start",
        )

    def complete_phase(
        self,
        *,
        run_id: str,
        phase: str,
        request: PhaseMutationRequest,
    ) -> ControlPlaneMutationResult:
        return self._mutate_phase(
            run_id=run_id,
            phase=phase,
            request=request,
            operation_kind="phase_complete",
        )

    def fail_phase(
        self,
        *,
        run_id: str,
        phase: str,
        request: PhaseMutationRequest,
    ) -> ControlPlaneMutationResult:
        return self._mutate_phase(
            run_id=run_id,
            phase=phase,
            request=request,
            operation_kind="phase_fail",
        )

    def complete_closure(
        self,
        *,
        run_id: str,
        request: ClosureCompleteRequest,
    ) -> ControlPlaneMutationResult:
        existing = self._load_existing_operation(request.op_id)
        if existing is not None:
            return existing

        now = datetime.now(tz=UTC)
        binding = self._repo.load_binding(request.session_id)
        worktree_roots = binding.worktree_roots if binding is not None else ()
        binding_version = (
            binding.binding_version if binding is not None else _next_binding_version()
        )
        lock = StoryExecutionLockRecord(
            project_key=request.project_key,
            story_id=request.story_id,
            run_id=run_id,
            lock_type="story_execution",
            status="INACTIVE",
            worktree_roots=tuple(worktree_roots),
            binding_version=binding_version,
            activated_at=now,
            updated_at=now,
            deactivated_at=now,
        )
        self._repo.save_lock(lock)
        self._repo.delete_binding(request.session_id)
        bundle = _build_edge_bundle(
            binding=None,
            lock=lock,
            sync_class="mutation",
            now=now,
            tombstone_worktree_roots=tuple(worktree_roots),
        )
        self._append_lifecycle_event(
            event_type=EventType.SESSION_RUN_BINDING_REMOVED,
            project_key=request.project_key,
            story_id=request.story_id,
            run_id=run_id,
            source_component=request.source_component,
            payload={"session_id": request.session_id},
            now=now,
        )
        self._append_lifecycle_event(
            event_type=EventType.STORY_EXECUTION_REGIME_DEACTIVATED,
            project_key=request.project_key,
            story_id=request.story_id,
            run_id=run_id,
            source_component=request.source_component,
            payload={"session_id": request.session_id},
            now=now,
        )
        result = ControlPlaneMutationResult(
            status="committed",
            op_id=request.op_id,
            operation_kind="closure_complete",
            run_id=run_id,
            phase="closure",
            edge_bundle=bundle,
        )
        self._store_operation(
            op_id=request.op_id,
            project_key=request.project_key,
            story_id=request.story_id,
            run_id=run_id,
            session_id=request.session_id,
            operation_kind="closure_complete",
            phase="closure",
            result=result,
            now=now,
        )
        return result

    def sync_project_edge(
        self,
        request: ProjectEdgeSyncRequest,
    ) -> ControlPlaneMutationResult:
        now = datetime.now(tz=UTC)
        binding = self._repo.load_binding(request.session_id)
        if binding is None or binding.project_key != request.project_key:
            lock = StoryExecutionLockRecord(
                project_key=request.project_key,
                story_id="",
                run_id="",
                lock_type="story_execution",
                status="INACTIVE",
                worktree_roots=(),
                binding_version=_next_binding_version(),
                activated_at=now,
                updated_at=now,
                deactivated_at=now,
            )
            bundle = _build_edge_bundle(
                binding=None,
                lock=lock,
                sync_class=request.freshness_class,
                now=now,
            )
            return ControlPlaneMutationResult(
                status="synced",
                op_id=request.op_id,
                operation_kind="project_edge_sync",
                edge_bundle=bundle,
            )

        lock_record = self._repo.load_lock(
            binding.project_key,
            binding.story_id,
            binding.run_id,
        )
        if lock_record is None:
            lock = StoryExecutionLockRecord(
                project_key=binding.project_key,
                story_id=binding.story_id,
                run_id=binding.run_id,
                lock_type="story_execution",
                status="INVALID",
                worktree_roots=binding.worktree_roots,
                binding_version=binding.binding_version,
                activated_at=now,
                updated_at=now,
            )
        else:
            lock = lock_record
        bundle = _build_edge_bundle(
            binding=binding,
            lock=lock,
            sync_class=request.freshness_class,
            now=now,
        )
        return ControlPlaneMutationResult(
            status="synced",
            op_id=request.op_id,
            operation_kind="project_edge_sync",
            run_id=binding.run_id,
            edge_bundle=bundle,
        )

    def get_operation(self, op_id: str) -> ControlPlaneMutationResult | None:
        record = self._repo.load_operation(op_id)
        if record is None:
            return None
        result = ControlPlaneMutationResult.model_validate(record.response_payload)
        return result.model_copy(update={"status": "replayed"})

    def _mutate_phase(
        self,
        *,
        run_id: str,
        phase: str,
        request: PhaseMutationRequest,
        operation_kind: str,
    ) -> ControlPlaneMutationResult:
        existing = self._load_existing_operation(request.op_id)
        if existing is not None:
            return existing

        now = datetime.now(tz=UTC)
        binding_version = _next_binding_version()
        binding = SessionRunBindingRecord(
            session_id=request.session_id,
            project_key=request.project_key,
            story_id=request.story_id,
            run_id=run_id,
            principal_type=request.principal_type,
            worktree_roots=tuple(request.worktree_roots),
            binding_version=binding_version,
            updated_at=now,
        )
        lock = StoryExecutionLockRecord(
            project_key=request.project_key,
            story_id=request.story_id,
            run_id=run_id,
            lock_type="story_execution",
            status="ACTIVE",
            worktree_roots=tuple(request.worktree_roots),
            binding_version=binding_version,
            activated_at=now,
            updated_at=now,
        )
        self._repo.save_binding(binding)
        self._repo.save_lock(lock)
        bundle = _build_edge_bundle(
            binding=binding,
            lock=lock,
            sync_class="mutation",
            now=now,
        )
        self._append_lifecycle_event(
            event_type=EventType.SESSION_RUN_BINDING_CREATED,
            project_key=request.project_key,
            story_id=request.story_id,
            run_id=run_id,
            source_component=request.source_component,
            payload={
                "session_id": request.session_id,
                "principal_type": request.principal_type,
                "worktree_roots": list(request.worktree_roots),
            },
            now=now,
            phase=phase,
        )
        self._append_lifecycle_event(
            event_type=EventType.STORY_EXECUTION_REGIME_ACTIVATED,
            project_key=request.project_key,
            story_id=request.story_id,
            run_id=run_id,
            source_component=request.source_component,
            payload={"session_id": request.session_id},
            now=now,
            phase=phase,
        )
        result = ControlPlaneMutationResult(
            status="committed",
            op_id=request.op_id,
            operation_kind=operation_kind,
            run_id=run_id,
            phase=phase,
            edge_bundle=bundle,
        )
        self._store_operation(
            op_id=request.op_id,
            project_key=request.project_key,
            story_id=request.story_id,
            run_id=run_id,
            session_id=request.session_id,
            operation_kind=operation_kind,
            phase=phase,
            result=result,
            now=now,
        )
        return result

    def _store_operation(
        self,
        *,
        op_id: str,
        project_key: str,
        story_id: str,
        run_id: str | None,
        session_id: str | None,
        operation_kind: str,
        phase: str | None,
        result: ControlPlaneMutationResult,
        now: datetime,
    ) -> None:
        self._repo.save_operation(
            ControlPlaneOperationRecord(
                op_id=op_id,
                project_key=project_key,
                story_id=story_id,
                run_id=run_id,
                session_id=session_id,
                operation_kind=operation_kind,
                phase=phase,
                status=result.status,
                response_payload=result.model_dump(mode="json"),
                created_at=now,
                updated_at=now,
            ),
        )

    def _append_lifecycle_event(
        self,
        *,
        event_type: EventType,
        project_key: str,
        story_id: str,
        run_id: str,
        source_component: str,
        payload: dict[str, object],
        now: datetime,
        phase: str | None = None,
    ) -> None:
        self._repo.append_event(
            ExecutionEventRecord(
                project_key=project_key,
                story_id=story_id,
                run_id=run_id,
                event_id=f"evt-{uuid.uuid4().hex}",
                event_type=event_type.value,
                occurred_at=now,
                source_component=source_component,
                severity="info",
                phase=phase,
                payload=payload,
            ),
        )

    def _load_existing_operation(
        self,
        op_id: str,
    ) -> ControlPlaneMutationResult | None:
        existing = self._repo.load_operation(op_id)
        if existing is None:
            return None
        result = ControlPlaneMutationResult.model_validate(existing.response_payload)
        return result.model_copy(update={"status": "replayed"})


def _build_edge_bundle(
    *,
    binding: SessionRunBindingRecord | None,
    lock: StoryExecutionLockRecord,
    sync_class: FreshnessClass,
    now: datetime,
    tombstone_worktree_roots: tuple[str, ...] = (),
) -> EdgeBundle:
    operating_mode = _resolve_operating_mode(binding=binding, lock=lock)
    export_version = f"edge-{uuid.uuid4().hex}"
    pointer = EdgePointer(
        project_key=lock.project_key or (binding.project_key if binding else ""),
        export_version=export_version,
        operating_mode=operating_mode,
        bundle_dir=f"_temp/governance/bundles/{export_version}",
        sync_after=now + _SYNC_AFTER_BY_CLASS[sync_class],
        freshness_class=sync_class,
        generated_at=now,
    )
    binding_view = (
        SessionRunBindingView(
            session_id=binding.session_id,
            project_key=binding.project_key,
            story_id=binding.story_id,
            run_id=binding.run_id,
            principal_type=binding.principal_type,
            worktree_roots=list(binding.worktree_roots),
            binding_version=binding.binding_version,
            operating_mode=operating_mode,
        )
        if binding is not None
        else None
    )
    lock_view = StoryExecutionLockView(
        project_key=lock.project_key,
        story_id=lock.story_id,
        run_id=lock.run_id,
        lock_type=lock.lock_type,
        status=cast("Literal['ACTIVE', 'INACTIVE', 'INVALID']", lock.status),
        worktree_roots=list(lock.worktree_roots),
        binding_version=lock.binding_version,
        activated_at=lock.activated_at,
        updated_at=lock.updated_at,
        deactivated_at=lock.deactivated_at,
    )
    return EdgeBundle(
        current=pointer,
        session=binding_view,
        lock=lock_view,
        tombstone_worktree_roots=list(tombstone_worktree_roots),
    )


def _resolve_operating_mode(
    *,
    binding: SessionRunBindingRecord | None,
    lock: StoryExecutionLockRecord,
) -> OperatingMode:
    if binding is None:
        return "ai_augmented"
    if lock.status == "ACTIVE":
        return "story_execution"
    return "binding_invalid"


def _next_binding_version() -> str:
    return f"bind-{uuid.uuid4().hex}"
