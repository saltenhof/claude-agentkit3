"""Project, story, KPI, dashboard, and CLI boundary composition builders."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from agentkit.backend.bootstrap.composition_state import (
    build_projection_accessor,
    build_runtime_execution_purge_port,
    build_runtime_execution_residue_probe,
)

if TYPE_CHECKING:
    from collections.abc import Callable

    from agentkit.backend.bootstrap import composition_project_types as project_types

def build_story_exit_service(*, project_key: str) -> object:
    """Build the productive FK-58 story-exit service."""

    from agentkit.backend.control_plane.repository import ControlPlaneRuntimeRepository
    from agentkit.backend.governance.runner import Governance
    from agentkit.backend.state_backend.store.governance_hook_repository import (
        StateBackendHookRegistrationRepository,
    )
    from agentkit.backend.state_backend.store.lock_record_repository import LockRecordRepository
    from agentkit.backend.story_context_manager.service import StoryService
    from agentkit.backend.story_exit.service import StoryExitService

    governance = Governance(
        hook_repo=StateBackendHookRegistrationRepository(),
        lock_repo=LockRecordRepository(),
        project_key=project_key,
    )
    return StoryExitService(
        control_plane_repository=ControlPlaneRuntimeRepository(),
        story_service=StoryService(),
        governance=governance,
    )


def _default_split_source_state_loader(
    request: project_types.StorySplitRequest,
) -> project_types.SplitSourceState:
    """Derive the §54.4 entry-gate source state from real run telemetry.

    Reads the FK-25 scope-explosion evidence from the ``execution_events`` stream
    (``scope_explosion_check`` with ``status="exploded"`` and a
    ``mandate_classification`` carrying ``escalation_class="scope_explosion"``)
    and the competing-administrative-operation signal from the control plane.
    This CONSUMES the existing FK-25 detection; it does not rebuild it.
    """
    from agentkit.backend.control_plane.repository import ControlPlaneRuntimeRepository
    from agentkit.backend.state_backend.store.story_read_repository import (
        StateBackendStoryReadRepository,
    )
    from agentkit.backend.story_split.service import SplitSourceState

    scope_exploded = False
    paused_with_scope_explosion = False
    # No store_dir in scope here; this path reads only the inherently global
    # execution-events stream (load_recent_execution_events takes no store_dir).
    events = StateBackendStoryReadRepository().load_recent_execution_events(
        request.project_key, request.source_story_id, request.run_id, 1000
    )
    for event in events:
        payload = event.payload if isinstance(event.payload, dict) else {}
        if event.event_type == "scope_explosion_check" and str(payload.get("status")) == "exploded":
            scope_exploded = True
        if event.event_type == "mandate_classification" and str(payload.get("escalation_class")) == "scope_explosion":
            paused_with_scope_explosion = True

    repo = ControlPlaneRuntimeRepository()
    competing = repo.has_committed_story_exit_operation_for_run(request.project_key, request.source_story_id, request.run_id)
    return SplitSourceState(
        scope_explosion_established=scope_exploded,
        paused_with_scope_explosion=paused_with_scope_explosion,
        competing_admin_operation_active=competing,
    )


def build_story_split_service(
    *,
    project_key: str,
    stories_root: Path,
    project_root: str | None,
    source_state_loader: Callable[[project_types.StorySplitRequest], project_types.SplitSourceState] | None = None,
) -> object:
    """Build the productive FK-54 story-split service (AG3-072).

    Wires the real story service, dependency repository, the narrow
    ``phase_state_projection`` quiesce owner (FacadePhaseStateProjectionRepository,
    NOT the full analytics purge), the governance lock/worktree teardown, and the
    AG3-068 reindex interface (``export_story_md`` -> ``story_sync``) for both
    successor export and the superseded-source re-index.

    Args:
        project_key: The bound project key.
        stories_root: The ``stories/`` directory for successor ``story.md`` export.
        project_root: Project root carrying the Weaviate host/port config.
        source_state_loader: Loader for the §54.4 entry-gate source state. When
            ``None`` the real telemetry-derived loader (FK-25 scope-explosion
            evidence + competing-operation signal) is wired here.

    Returns:
        A wired ``StorySplitService``.
    """
    from agentkit.backend.control_plane.repository import ControlPlaneRuntimeRepository
    from agentkit.backend.governance.runner import Governance
    from agentkit.backend.state_backend.store.governance_hook_repository import (
        StateBackendHookRegistrationRepository,
    )
    from agentkit.backend.state_backend.store.lock_record_repository import LockRecordRepository
    from agentkit.backend.state_backend.store.projection_repositories import (
        FacadePhaseStateProjectionRepository,
    )
    from agentkit.backend.state_backend.store.story_dependency_repository import (
        StateBackendStoryDependencyRepository,
    )
    from agentkit.backend.story_context_manager.service import StoryService
    from agentkit.backend.story_creation.story_md_export import export_story_md
    from agentkit.backend.story_creation.weaviate_index import WeaviateStoryIndex
    from agentkit.backend.story_split.service import StorySplitError, StorySplitService
    from agentkit.backend.vectordb.wait_for_weaviate import _resolve_host_port
    from agentkit.integration_clients.vectordb import WeaviateStoryAdapter

    governance = Governance(
        hook_repo=StateBackendHookRegistrationRepository(),
        lock_repo=LockRecordRepository(),
        project_key=project_key,
    )
    story_attributes = StoryService()
    host, port = _resolve_host_port(project_root)
    index = WeaviateStoryIndex(WeaviateStoryAdapter.connect(host=host, port=port))
    if source_state_loader is None:
        source_state_loader = _default_split_source_state_loader

    class _SuccessorExport:
        def export(self, *, story_id: str, story_dir: Path) -> object:
            return export_story_md(
                story_id,
                story_dir,
                story_attributes=story_attributes,
                index=index,
            )

    class _SupersededIndex:
        def mark_superseded(self, *, story_id: str, superseded_by: tuple[str, ...]) -> int:
            # HONOR superseded_by (AG3-072 review #4): persist the superseded_by
            # ids onto the source story's authoritative lineage FIRST, so the
            # (re-)export below indexes the source as Cancelled WITH
            # superseded_by=[...] — not a stale In Progress / empty-lineage state.
            # ``materialize_split_lineage`` writes ``split_successors`` (which IS
            # the superseded_by set); re-asserting it here keeps the index
            # honoring superseded_by independent of step ordering. Idempotent.
            story_attributes.materialize_split_lineage(
                source_story_id=story_id,
                successor_ids=superseded_by,
            )
            # Re-export the cancelled source so AG3-068 re-indexes it (NOT deletes
            # it). The source stays in the index as Cancelled + superseded_by.
            result = export_story_md(
                story_id,
                stories_root / story_id,
                story_attributes=story_attributes,
                index=index,
            )
            # FAIL-CLOSED (AG3-072 review r4 / §54.5 / AK5 / AK12): export_story_md
            # signals a missing story / write / validation / VectorDB failure by
            # RETURNING success=False, NOT by raising. Returning 0 here would let
            # the split finalize with the source left un-exported / un-indexed —
            # a silent integration-consequences gap (FK-54 §54.11,
            # "Integrationsfolgen"). Propagate the REAL failure instead
            # so the split stays fail-closed and a later rerun resumes.
            if not result.success:
                raise StorySplitError(
                    f"source superseded re-export/reindex failed for {story_id!r}: {result.error or 'no detail reported'}",
                )
            return 1

    return StorySplitService(
        control_plane_repository=ControlPlaneRuntimeRepository(),
        # Share the single StoryService instance with the export/superseded path
        # so lineage materialization and the superseded re-index see one
        # authoritative story surface (no divergent shadow service).
        story_service=story_attributes,
        dependency_repository=StateBackendStoryDependencyRepository(),
        phase_state_quiesce=FacadePhaseStateProjectionRepository(),
        governance=governance,
        successor_export=_SuccessorExport(),
        superseded_index=_SupersededIndex(),
        stories_root=stories_root,
        source_state_loader=source_state_loader,
    )


def build_story_reset_service(
    *,
    project_key: str,
    store_dir: Path,
    project_root: Path | None = None,
    audit_root: Path | None = None,
) -> object:
    """Build the productive FK-53 Story-Reset service (AG3-071).

    Wires the four §53.10 contract operations onto the REAL purge owners (no second
    purge truth): the Runtime-Execution purge port + governance lock owner
    (Schritt 5, SEPARATE owners), the FK-69 ``ProjectionAccessor`` + the AG3-082
    analytics ``purge_story_analytics`` path (Schritt 6, SEPARATE owners), the
    workspace/worktree teardown (Schritt 7/8), the story-status owner
    (``StoryService``) and the ``ControlPlaneRuntimeRepository`` reset fence.

    Args:
        project_key: The project scope.
        store_dir: State-backend base dir (story dir for SQLite). Drives the purge
            ports + lock repository.
        project_root: Target project root used to resolve worktrees (defaults to
            ``store_dir``).
        audit_root: Durable reset-record audit root (defaults to
            ``var/story_reset``).

    Returns:
        A fully wired :class:`agentkit.backend.story_reset.StoryResetService`.
    """
    from agentkit.backend.bootstrap.story_reset_adapters import (
        AnalyticsPurgeAdapter,
        CompetingOperationAdapter,
        EscalationEvidenceAdapter,
        FenceAdapter,
        LockPurgeAdapter,
        ReadModelPurgeAdapter,
        RunScopeAdapter,
        RuntimePurgeAdapter,
        WorkspacePurgeAdapter,
        WorktreePurgeAdapter,
    )
    from agentkit.backend.control_plane.repository import (
        ControlPlaneRuntimeRepository,
        EdgeCommandRepository,
        RunOwnershipRepository,
    )
    from agentkit.backend.governance.runner import Governance
    from agentkit.backend.kpi_analytics.aggregation import RefreshWorker
    from agentkit.backend.kpi_analytics.fact_store import FactStore
    from agentkit.backend.state_backend.store.analytics_source import (
        StateBackendAnalyticsSource,
    )
    from agentkit.backend.state_backend.store.fact_repository import (
        StateBackendFactRepository,
    )
    from agentkit.backend.state_backend.store.governance_hook_repository import (
        StateBackendHookRegistrationRepository,
    )
    from agentkit.backend.state_backend.store.lock_record_repository import LockRecordRepository
    from agentkit.backend.state_backend.store.story_read_repository import (
        StateBackendStoryReadRepository,
    )
    from agentkit.backend.story_context_manager.service import StoryService
    from agentkit.backend.story_reset import FileResetRecordStore, StoryResetService

    resolved_root = project_root or store_dir
    lock_repo = LockRecordRepository(store_dir)
    governance = Governance(
        hook_repo=StateBackendHookRegistrationRepository(),
        lock_repo=lock_repo,
        project_key=project_key,
        project_root=resolved_root,
    )
    cp_repo = ControlPlaneRuntimeRepository()
    story_repo = StateBackendStoryReadRepository(store_dir=store_dir)
    accessor = build_projection_accessor(store_dir)
    refresh_worker = RefreshWorker(
        FactStore(StateBackendFactRepository(store_dir)),
        StateBackendAnalyticsSource(accessor, project_key=project_key),
    )

    return StoryResetService(
        story_status=StoryService(),
        record_store=FileResetRecordStore(audit_root or Path("var/story_reset")),
        run_scope=RunScopeAdapter(story_repo),
        escalation_evidence=EscalationEvidenceAdapter(story_repo),
        competing_operation=CompetingOperationAdapter(cp_repo),
        fence=FenceAdapter(cp_repo),
        runtime_purge=RuntimePurgeAdapter(
            build_runtime_execution_purge_port(store_dir),
            build_runtime_execution_residue_probe(store_dir),
        ),
        lock_purge=LockPurgeAdapter(governance, lock_repo),
        read_model_purge=ReadModelPurgeAdapter(accessor),
        analytics_purge=AnalyticsPurgeAdapter(refresh_worker),
        workspace=WorkspacePurgeAdapter(resolved_root),
        worktree=WorktreePurgeAdapter(
            edge_commands=EdgeCommandRepository(),
            ownership_repo=RunOwnershipRepository(),
            project_root=resolved_root,
        ),
    )


def build_kpi_analytics(store_dir: Path, *, project_key: str) -> project_types.KpiAnalytics:
    """Wire a ``KpiAnalytics`` facade onto the real FactStore + RefreshWorker.

    Composition-Root for the analytics path (AG3-038 read side + AG3-082 worker):

    - binds the StateBackend fact repository onto the ``FactStore`` (the ONLY write
      path into ``analytics.*``, FK-62 §62.6.2) so ``get_dashboard_view`` reads the
      canonical fact tables;
    - builds the productive runtime read port
      (``StateBackendAnalyticsSource``) over the project-global ``execution_events``
      stream and the FK-69 ``ProjectionAccessor`` (the ONLY runtime read path AND the
      run-scoped reset purge surface, FK-62 §62.6.1 / FK-69 §69.10.1);
    - assembles the real ``RefreshWorker`` from those two and injects it into
      ``KpiAnalytics`` — so ``refresh_analytics`` reaches the REAL worker
      (``trigger=CLOSURE``) instead of returning the not-configured SKIPPED.

    The consumer BC knows only the ``FactRepository`` / ``AnalyticsSourcePort``
    Protocols (AC6/AC8); the concrete adapters are bound here.

    Args:
        store_dir: State-backend base dir (SQLite stores under
            ``store_dir/.agentkit/...``; Postgres ignores it).
        project_key: The project scope the analytics source reads (FK-62 §62.2
            tenant rule: analytics is per-project isolable).

    Returns:
        A ``KpiAnalytics`` facade with a live FactStore read path AND a real
        RefreshWorker (no SKIPPED-not-configured branch in production).
    """
    from agentkit.backend.kpi_analytics import KpiAnalytics, KpiCatalog
    from agentkit.backend.kpi_analytics.aggregation import RefreshWorker
    from agentkit.backend.kpi_analytics.fact_store import FactStore
    from agentkit.backend.state_backend.store.analytics_source import (
        StateBackendAnalyticsSource,
    )
    from agentkit.backend.state_backend.store.fact_repository import (
        StateBackendFactRepository,
    )

    fact_store = FactStore(StateBackendFactRepository(store_dir))
    accessor = build_projection_accessor(store_dir)
    source = StateBackendAnalyticsSource(accessor, project_key=project_key)
    refresh_worker = RefreshWorker(fact_store, source)
    return KpiAnalytics(
        catalog=KpiCatalog(),
        fact_store=fact_store,
        refresh_worker=refresh_worker,
    )


def build_kpi_analytics_read_facade(store_dir: Path | None = None) -> project_types.KpiAnalytics:
    """Wire the read-only KPI facade used by the HTTP KPI routes."""
    from agentkit.backend.kpi_analytics import KpiAnalytics, KpiCatalog
    from agentkit.backend.kpi_analytics.fact_store import FactStore
    from agentkit.backend.state_backend.store.fact_repository import (
        StateBackendFactRepository,
    )

    fact_repository = StateBackendFactRepository() if store_dir is None else StateBackendFactRepository(store_dir)
    return KpiAnalytics(catalog=KpiCatalog(), fact_store=FactStore(fact_repository))


def build_story_read_service() -> project_types.StoryService:
    """Wire the Story-BC read service over the productive ``StoryReadPort`` adapter.

    Composition root for :class:`agentkit.backend.story.service.StoryService`
    (FK-07 §7.6): injects the ``StateBackendStoryReadRepository`` adapter so the
    BFF/HTTP story list/detail endpoints read exclusively through the published
    port, never through a ``state_backend.store`` passthrough.
    """
    from agentkit.backend.state_backend.store.story_read_repository import (
        StateBackendStoryReadRepository,
    )
    from agentkit.backend.story import StoryService

    return StoryService(repository=StateBackendStoryReadRepository())


def build_project_telemetry_event_source() -> project_types.ProjectTelemetryEventSource:
    """Wire the telemetry-BC read edge over the productive event-source adapter.

    Composition root for the ``ProjectTelemetryEventSource`` port (FK-07
    §7.6/§7.8, AG3-127): injects the ``StateBackendProjectTelemetryEventSource``
    adapter so the SSE live-view route reads project execution events
    exclusively through the published port, never through a
    ``state_backend.store`` passthrough inside the telemetry BC.
    """
    from agentkit.backend.state_backend.store.telemetry_read_repository import (
        StateBackendProjectTelemetryEventSource,
    )

    return StateBackendProjectTelemetryEventSource()


def build_dashboard_service(
    story_service: project_types.StoryService,
    store_dir: Path | None = None,
) -> project_types.DashboardService:
    """Wire the legacy dashboard service without leaking fact persistence to HTTP."""
    from agentkit.backend.kpi_analytics.dashboard import DashboardService
    from agentkit.backend.kpi_analytics.fact_store import FactStore
    from agentkit.backend.state_backend.store.fact_repository import (
        StateBackendFactRepository,
    )

    fact_repository = StateBackendFactRepository() if store_dir is None else StateBackendFactRepository(store_dir)
    return DashboardService(
        story_service=story_service,
        fact_store=FactStore(fact_repository),
    )


def build_task_management_routes(store_dir: Path | None = None) -> project_types.TaskManagementRoutes:
    """Wire task-management HTTP routes through the telemetry projection port."""
    import os

    from agentkit.backend.task_management.http.routes import TaskManagementRoutes
    from agentkit.backend.task_management.service import TaskManagement

    resolved_store_dir = store_dir or Path(os.environ.get("AGENTKIT_STORE_DIR", "."))
    service = TaskManagement(build_projection_accessor(resolved_store_dir))
    return TaskManagementRoutes(task_management=service)


def build_project_repository(store_dir: Path | None = None) -> project_types.ProjectRepository:
    """Wire the project-management repository adapter."""
    from agentkit.backend.state_backend.store.project_management_repository import (
        StateBackendProjectRepository,
    )

    return StateBackendProjectRepository(store_dir)


def build_project_read_model_routes(store_dir: Path | None = None) -> project_types.ReadModelRoutes:
    """Wire project-scoped frontend read-model routes outside the HTTP boundary."""
    from agentkit.backend.project_management.read_model_routes import ReadModelRoutes
    from agentkit.backend.state_backend.store.parallelization_config_repository import (
        StateBackendParallelizationConfigRepository,
    )
    from agentkit.backend.state_backend.store.project_management_repository import (
        StateBackendProjectRepository,
    )
    from agentkit.backend.state_backend.store.story_are_link_repository import (
        StateBackendStoryAreLinkRepository,
    )
    from agentkit.backend.state_backend.store.story_dependency_repository import (
        StateBackendStoryDependencyRepository,
    )
    from agentkit.backend.state_backend.store.story_read_repository import (
        StateBackendStoryReadRepository,
    )
    from agentkit.backend.state_backend.store.story_repository import (
        StateBackendStoryRepository,
    )
    from agentkit.backend.story_context_manager.service import StoryService as _StoryContextService

    # Thread store_dir into EVERY state-backend repository the story service uses
    # for reads (story stammdaten, project, dependency edges). _handle_flow reads
    # story.get_story BEFORE the phase_state_loader; without store_dir-aware
    # injection the default StoryService falls back to Path.cwd() and returns
    # story_not_found for stories persisted only under store_dir.
    #
    # AG3-140: this is a read-model wiring; the unified in-flight idempotency guard
    # (default StateBackendInflightIdempotencyGuard) is only exercised on the
    # mutation surface, which this read-only route never drives, so no store_dir
    # threading of the guard is required here.
    story_service = _StoryContextService(
        story_repository=StateBackendStoryRepository(store_dir),
        project_repository=StateBackendProjectRepository(store_dir),
        dependency_repository=StateBackendStoryDependencyRepository(store_dir),
    )

    return ReadModelRoutes(
        project_repository=build_project_repository(store_dir),
        story_service=story_service,
        config_repository=StateBackendParallelizationConfigRepository(store_dir),
        are_link_repository=StateBackendStoryAreLinkRepository(store_dir),
        phase_state_loader=StateBackendStoryReadRepository(store_dir=store_dir).load_phase_state,
    )

def cli_load_story_context(story_dir: Path) -> project_types.StoryContext | None:
    """Load a :class:`~agentkit.backend.story_context_manager.models.StoryContext` for the CLI.

    Thin composition-root wrapper over ``facade.load_story_context`` so the
    operator/recovery CLI (AG3-076) can read story context without importing
    ``agentkit.backend.state_backend.store`` directly.

    Args:
        story_dir: Story working directory (``<project_root>/stories/<story_id>``).

    Returns:
        The persisted :class:`StoryContext`, or ``None`` when absent.
    """
    from agentkit.backend.state_backend.store.facade import load_story_context

    return load_story_context(story_dir)


def cli_read_phase_state_record(story_dir: Path) -> object:
    """Read the current phase-state record for the CLI.

    Thin composition-root wrapper over ``facade.read_phase_state_record`` so
    the operator/recovery CLI (AG3-076) can read phase state without importing
    ``agentkit.backend.state_backend.store`` directly.

    Args:
        story_dir: Story working directory (``<project_root>/stories/<story_id>``).

    Returns:
        The persisted phase-state model instance, or ``None`` when absent.
    """
    from agentkit.backend.state_backend.store.facade import read_phase_state_record

    return read_phase_state_record(story_dir)


def build_compat_window_reader(
    base_url: str,
    *,
    skill_bundle_version: str | None = None,
) -> Callable[[], dict[str, object]]:
    """Build a reader for the Core compat window (FK-10 §10.2.8, AG3-122).

    Wires the official ProjectEdge HTTPS transport and returns a zero-arg callable
    that performs ``GET /v1/compat`` (AG3-121). The level-2 ``agentkit update``
    driver consumes this read path; it never rebuilds the endpoint. The CLI is an
    entry boundary that cannot import the ProjectEdge adapter directly, so this
    wiring lives in the composition root.

    Args:
        base_url: The Core control-plane base URL.
        skill_bundle_version: The locally bound skill-bundle version (handshake
            header); ``None`` when no bundle is bound (``/v1/compat`` is exempt).

    Returns:
        A callable returning the decoded compat-window body.
    """
    from agentkit.harness_client.projectedge.client import (
        HttpsJsonTransport,
        fetch_compat_window,
    )

    transport = HttpsJsonTransport(
        base_url=base_url,
        skill_bundle_version=skill_bundle_version,
    )

    def _read() -> dict[str, object]:
        return fetch_compat_window(transport)

    return _read
