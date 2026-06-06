"""Control-plane services for run binding and project-edge sync."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Literal, Protocol, cast

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
from agentkit.control_plane.records import (
    ControlPlaneOperationRecord,
    SessionRunBindingRecord,
)
from agentkit.control_plane.repository import ControlPlaneRuntimeRepository
from agentkit.governance.guard_system.records import StoryExecutionLockRecord
from agentkit.governance.guard_system.story_scoped_guards import (
    should_create_story_lock_records,
)
from agentkit.telemetry.contract.records import ExecutionEventRecord
from agentkit.telemetry.events import EventType

OperatingMode = Literal["ai_augmented", "story_execution", "binding_invalid"]
FreshnessClass = Literal["baseline_read", "guarded_read", "mutation"]

_SYNC_AFTER_BY_CLASS = {
    "baseline_read": timedelta(minutes=5),
    "guarded_read": timedelta(minutes=2),
    "mutation": timedelta(seconds=45),
}


class _ModeResolutionKeys(Protocol):
    """The authoritative ``(project_key, story_id)`` lookup keys for mode resolution.

    Both :class:`PhaseMutationRequest` and :class:`ClosureCompleteRequest` satisfy
    this structurally, so the single sanctioned-surface mode resolution
    (``_story_lock_records_apply``) is shared across setup and closure without
    coupling to a concrete request type.
    """

    @property
    def project_key(self) -> str: ...

    @property
    def story_id(self) -> str: ...


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
        """Complete closure for a story run, tearing down its guard regime.

        AG3-018 FIX-2 (FK-24 §24.3.4; ``no_locks_active``): the authoritative
        story mode is resolved server-side (same sanctioned surface as
        ``_mutate_phase``; fail-closed-to-standard on an unresolvable
        ``StoryContext``). A FAST story never activated story-scoped guards, so
        its closure is a true no-op -- it creates NO ``story_execution`` /
        ``qa_artifact_write`` lock-records and emits NO story-execution
        deactivation events (see :meth:`_complete_fast_closure`). Standard /
        exploration closure is unchanged: it writes the INACTIVE lock-records and
        emits the binding-removed + regime-deactivated events.

        Args:
            run_id: The story run identifier.
            request: The closure completion request.

        Returns:
            The committed (or replayed) closure :class:`ControlPlaneMutationResult`.
        """
        existing = self._load_existing_operation(request.op_id)
        if existing is not None:
            return existing

        now = datetime.now(tz=UTC)
        if not self._story_lock_records_apply(request):
            return self._complete_fast_closure(
                run_id=run_id,
                request=request,
                now=now,
            )

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
        qa_lock = StoryExecutionLockRecord(
            project_key=request.project_key,
            story_id=request.story_id,
            run_id=run_id,
            lock_type="qa_artifact_write",
            status="INACTIVE",
            worktree_roots=tuple(worktree_roots),
            binding_version=binding_version,
            activated_at=now,
            updated_at=now,
            deactivated_at=now,
        )
        self._repo.save_lock(lock)
        self._repo.save_lock(qa_lock)
        self._repo.delete_binding(request.session_id)
        bundle = _build_edge_bundle(
            binding=None,
            lock=lock,
            qa_lock=qa_lock,
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
            "story_execution",
        )
        qa_lock_record = self._repo.load_lock(
            binding.project_key,
            binding.story_id,
            binding.run_id,
            "qa_artifact_write",
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
            qa_lock=qa_lock_record,
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
        if self._story_scoped_materialization_enabled(request):
            bundle = self._materialize_story_scoped_state(
                run_id=run_id,
                phase=phase,
                request=request,
                now=now,
            )
        else:
            bundle = self._materialize_fast_state(
                request=request,
                now=now,
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

    def _story_scoped_materialization_enabled(
        self,
        request: PhaseMutationRequest,
    ) -> bool:
        """Whether story-scoped session/locks must be materialized for this run.

        AG3-018 (FK-24 §24.3.4): a ``fast`` story does NOT activate the
        story-scoped guards and creates NO story lock-records. The mode is
        resolved AUTHORITATIVELY server-side from the state-backend
        ``StoryContext`` keyed by ``(project_key, story_id)`` -- never from an
        agent-supplied request field (which would be forgeable; AG3-018 FIX-1).

        Fail-closed: if the authoritative ``StoryContext`` cannot be resolved,
        story-scoped materialization stays ENABLED (treated as standard), so a
        code story can never silently skip its guards on a lookup gap.

        Args:
            request: The phase mutation request (carries ``project_key`` /
                ``story_id`` -- the authoritative lookup keys).

        Returns:
            ``False`` only for an authoritatively-resolved fast story; ``True``
            otherwise (standard/exploration, and the fail-closed lookup gap).
        """
        return self._story_lock_records_apply(request)

    def _story_lock_records_apply(
        self,
        request: _ModeResolutionKeys,
    ) -> bool:
        """Authoritative server-side decision: are story lock-records in play?

        The single sanctioned-surface mode resolution shared by ``_mutate_phase``
        (setup/phase mutations) and ``complete_closure`` (teardown). The operating
        mode is read from the state-backend ``StoryContext`` keyed by
        ``(project_key, story_id)`` -- NEVER from an agent-supplied request field
        (which would be forgeable; AG3-018 FIX-1).

        Fail-closed: if the authoritative ``StoryContext`` cannot be resolved, the
        run is treated as standard (story lock-records DO apply), so a code story
        can never silently skip its guards/teardown on a lookup gap.

        Args:
            request: Any request carrying the authoritative ``project_key`` /
                ``story_id`` lookup keys (phase mutation or closure completion).

        Returns:
            ``False`` only for an authoritatively-resolved fast story; ``True``
            otherwise (standard/exploration, and the fail-closed lookup gap).
        """
        ctx = self._repo.load_story_context(request.project_key, request.story_id)
        if ctx is None:
            return True
        return should_create_story_lock_records(ctx)

    def _complete_fast_closure(
        self,
        *,
        run_id: str,
        request: ClosureCompleteRequest,
        now: datetime,
    ) -> ControlPlaneMutationResult:
        """No-op closure for a fast story (FK-24 §24.3.4; ``no_locks_active``).

        A fast story never created a session binding or story/QA lock-records at
        setup, so closure deactivates NOTHING: it creates no ``story_execution`` /
        ``qa_artifact_write`` lock-records and emits NO story-execution
        deactivation events. It returns an ``ai_augmented`` bundle with no session
        and no locks. Any session binding that may exist is still cleaned up, but
        a fast run holds none, so this is a pure no-op for the guard regime.

        Args:
            run_id: The story run identifier.
            request: The closure completion request (authoritative lookup keys).
            now: The mutation timestamp.

        Returns:
            An ``ai_augmented`` :class:`ControlPlaneMutationResult` with no
            lock-records created and no deactivation events emitted.
        """
        self._repo.delete_binding(request.session_id)
        bundle = _build_fast_edge_bundle(
            project_key=request.project_key,
            sync_class="mutation",
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

    def _materialize_story_scoped_state(
        self,
        *,
        run_id: str,
        phase: str,
        request: PhaseMutationRequest,
        now: datetime,
    ) -> EdgeBundle:
        """Materialize the full story-scoped binding + locks (standard run)."""
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
        qa_lock = StoryExecutionLockRecord(
            project_key=request.project_key,
            story_id=request.story_id,
            run_id=run_id,
            lock_type="qa_artifact_write",
            status="ACTIVE",
            worktree_roots=tuple(request.worktree_roots),
            binding_version=binding_version,
            activated_at=now,
            updated_at=now,
        )
        self._repo.save_binding(binding)
        self._repo.save_lock(lock)
        self._repo.save_lock(qa_lock)
        bundle = _build_edge_bundle(
            binding=binding,
            lock=lock,
            qa_lock=qa_lock,
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
        return bundle

    def _materialize_fast_state(
        self,
        *,
        request: PhaseMutationRequest,
        now: datetime,
    ) -> EdgeBundle:
        """Skip story-scoped materialization for a fast story (AG3-018 AC3/AC5).

        A fast story materializes NO session binding, NO ``story_execution``
        lock and NO ``qa_artifact_write`` lock, so the edge resolves to
        ``ai_augmented`` and the story-scoped ScopeGuard/ArtifactGuard never
        activate. The BASELINE guards (BranchGuard et al.) are NOT gated on this
        state and stay active in every mode. No ``story_execution_regime``
        activation event is emitted because no regime is entered.
        """
        return _build_fast_edge_bundle(
            project_key=request.project_key,
            sync_class="mutation",
            now=now,
        )

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


def _build_fast_edge_bundle(
    *,
    project_key: str,
    sync_class: FreshnessClass,
    now: datetime,
) -> EdgeBundle:
    """Build an ``ai_augmented`` bundle for a fast story (AG3-018 AC3/AC5).

    A fast story carries no story-scoped session binding and no
    ``story_execution`` / ``qa_artifact_write`` lock. The resulting bundle has
    ``session is None`` and ``lock is None``, so the local edge resolves to
    ``ai_augmented`` and only the baseline guards run.

    Args:
        project_key: The project key for the edge pointer.
        sync_class: Freshness class driving the pointer ``sync_after``.
        now: The mutation timestamp.

    Returns:
        An ``EdgeBundle`` with no session and no locks.
    """
    export_version = f"edge-{uuid.uuid4().hex}"
    pointer = EdgePointer(
        project_key=project_key,
        export_version=export_version,
        operating_mode="ai_augmented",
        bundle_dir=f"_temp/governance/bundles/{export_version}",
        sync_after=now + _SYNC_AFTER_BY_CLASS[sync_class],
        freshness_class=sync_class,
        generated_at=now,
    )
    return EdgeBundle(
        current=pointer,
        session=None,
        lock=None,
        qa_lock=None,
        tombstone_worktree_roots=[],
    )


def _build_edge_bundle(
    *,
    binding: SessionRunBindingRecord | None,
    lock: StoryExecutionLockRecord,
    qa_lock: StoryExecutionLockRecord | None = None,
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
    qa_lock_view = (
        StoryExecutionLockView(
            project_key=qa_lock.project_key,
            story_id=qa_lock.story_id,
            run_id=qa_lock.run_id,
            lock_type=qa_lock.lock_type,
            status=cast("Literal['ACTIVE', 'INACTIVE', 'INVALID']", qa_lock.status),
            worktree_roots=list(qa_lock.worktree_roots),
            binding_version=qa_lock.binding_version,
            activated_at=qa_lock.activated_at,
            updated_at=qa_lock.updated_at,
            deactivated_at=qa_lock.deactivated_at,
        )
        if qa_lock is not None
        else None
    )
    return EdgeBundle(
        current=pointer,
        session=binding_view,
        lock=lock_view,
        qa_lock=qa_lock_view,
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
