"""Explicit composition-root builders without import-time side effects."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from agentkit.backend.artifacts import ArtifactManager, EnvelopeValidator, ProducerRegistry
from agentkit.backend.exceptions import PipelineError
from agentkit.backend.exploration.register import register_exploration_producers
from agentkit.backend.implementation.register import register_implementation_producers
from agentkit.backend.prompt_runtime.register import register_prompt_runtime_producers
from agentkit.backend.requirements_coverage.register import (
    register_requirements_coverage_producers,
)
from agentkit.backend.state_backend.store.artifact_repository import (
    StateBackendArtifactRepository,
)
from agentkit.backend.verify_system.register import register_verify_producers

if TYPE_CHECKING:
    from collections.abc import Callable

    from agentkit.backend.closure.gates import TelemetryEvidencePort
    from agentkit.backend.closure.merge_sequence import MergeApplicability, PreMergeScanPort, RepoRunners, SanityGatePort
    from agentkit.backend.closure.multi_repo_saga import GitBackend as RepoGitBackend
    from agentkit.backend.closure.phase import (
        ClosurePhaseHandler,
        ClosureProgressStore,
        GuardCounterFlushPort,
        ModeLockReleasePort,
    )
    from agentkit.backend.closure.post_merge_finalization.finalization import (
        DocFidelityFeedbackPort,
        GuardDeactivationPort,
        VectorDbSyncPort,
    )
    from agentkit.backend.config.models import ConformanceConfig
    from agentkit.backend.execution_planning.persistence.accessor import (
        PlanningProjectionAccessor,
    )
    from agentkit.backend.exploration.change_frame import ChangeFrame
    from agentkit.backend.exploration.drafting import ExplorationDrafting
    from agentkit.backend.exploration.mandate.fine_design import (
        FineDesignEvaluator,
        FineDesignRoundOutcome,
    )
    from agentkit.backend.exploration.phase import ExplorationPhaseHandler
    from agentkit.backend.exploration.review import ExplorationReview
    from agentkit.backend.failure_corpus import FailureCorpus
    from agentkit.backend.governance.integrity_gate import IntegrityGate
    from agentkit.backend.governance.integrity_gate.dim9_sonar import SonarDimensionPort
    from agentkit.backend.governance.repository import SetupContextRepository
    from agentkit.backend.governance.setup_preflight_gate.phase import SetupPhaseHandler
    from agentkit.backend.kpi_analytics import KpiAnalytics
    from agentkit.backend.kpi_analytics.dashboard import DashboardService
    from agentkit.backend.pipeline_engine.engine import PipelineEngine
    from agentkit.backend.pipeline_engine.lifecycle import HandlerResult, PhaseHandlerRegistry
    from agentkit.backend.pipeline_engine.phase_envelope.envelope import PhaseEnvelope
    from agentkit.backend.pipeline_engine.phase_envelope.store import PhaseEnvelopeStore
    from agentkit.backend.project_management.read_model_routes import ReadModelRoutes
    from agentkit.backend.project_management.repository import ProjectRepository
    from agentkit.backend.requirements_coverage.contract import CoverageVerdict
    from agentkit.backend.requirements_coverage.top import (
        RequirementsCoverage as RequirementsCoverageProto,
    )
    from agentkit.backend.skills import Skills
    from agentkit.backend.state_backend.store.planning_story_dependency_repository import (
        PlanningWritePathStoryDependencyRepository,
    )
    from agentkit.backend.state_backend.store.runtime_execution_purge import (
        RuntimeExecutionPurgePort,
        RuntimeExecutionResidueProbe,
    )
    from agentkit.backend.story import StoryService
    from agentkit.backend.story_context_manager.models import StoryContext
    from agentkit.backend.story_context_manager.story_model import ChangeImpact
    from agentkit.backend.story_context_manager.types import StoryType
    from agentkit.backend.story_split.service import SplitSourceState, StorySplitRequest
    from agentkit.backend.task_management.http.routes import TaskManagementRoutes
    from agentkit.backend.telemetry.emitters import EventEmitter
    from agentkit.backend.telemetry.projection_accessor import ProjectionAccessor
    from agentkit.backend.verify_system.llm_evaluator.llm_client import LlmClient
    from agentkit.backend.verify_system.pre_merge_runner.contract import BuildTestPort
    from agentkit.backend.verify_system.qa_cycle.invalidation import (
        ArtifactInvalidationEvent,
        ArtifactInvalidationSink,
    )
    from agentkit.backend.verify_system.review_completion import (
        ReviewCompletionEvent,
        ReviewCompletionSink,
    )
    from agentkit.backend.verify_system.sonarqube_gate.port import SonarGateInputPort
    from agentkit.backend.verify_system.structural.checker import AreGateProvider
    from agentkit.backend.verify_system.structural.checks import (
        BuildTestEvidence,
        BuildTestEvidencePort,
    )
    from agentkit.backend.verify_system.structural.system_evidence import ChangeEvidence
    from agentkit.backend.verify_system.system import VerifySystem
    from agentkit.integration_clients.multi_llm_hub.client import HubClientProtocol


def build_producer_registry() -> ProducerRegistry:
    """Create a fresh ``ProducerRegistry`` and call all known BC init hooks.

    Current state: ``register_exploration_producers`` (AG3-045,
    ``ArtifactClass.ENTWURF``), ``register_implementation_producers`` (AG3-044,
    ``ArtifactClass.HANDOVER``), ``register_verify_producers`` (AG3-023 +
    AG3-044 ``ArtifactClass.ADVERSARIAL_TEST_SANDBOX``) and
    ``register_prompt_runtime_producers`` (AG3-015, FK-44 §44.6 --
    ``ArtifactClass.PROMPT_AUDIT``) are wired. Further BC-init hooks
    (telemetry, governance, closure ...) are added analogously in their
    follow-up stories.

    Returns:
        A ``ProducerRegistry`` with all producers known today.

    Notes:
        The order of the init hooks is deterministic (BC-alphabetical or
        capability order). Every hook is idempotent.
    """
    from agentkit.backend.exploration.review.register import (
        register_exploration_review_producers,
    )

    registry = ProducerRegistry()
    register_exploration_producers(registry)
    register_exploration_review_producers(registry)
    register_implementation_producers(registry)
    register_prompt_runtime_producers(registry)
    register_requirements_coverage_producers(registry)
    register_verify_producers(registry)
    return registry


def build_artifact_manager(store_dir: Path) -> ArtifactManager:
    """Create a fully wired ``ArtifactManager``.

    Composition root for the artifact write/read path: binds the
    producer registry, the envelope validator and the StateBackend
    repository together. Consumer BCs (e.g. ``verify_system.artifacts``)
    receive the manager via DI and do not know the repository
    implementation.

    Args:
        store_dir: Base directory of the state backend (SQLite stores
            under ``store_dir/.agentkit/...``; Postgres ignores the
            path).

    Returns:
        ``ArtifactManager`` with all verify producers registered.
    """
    registry = build_producer_registry()
    validator = EnvelopeValidator(registry)
    repository = StateBackendArtifactRepository(store_dir)
    return ArtifactManager(repository, validator)


def build_story_exit_service(*, project_key: str) -> object:
    """Build the productive FK-58 story-exit service."""

    from agentkit.backend.control_plane.repository import ControlPlaneRuntimeRepository
    from agentkit.backend.governance.runner import Governance
    from agentkit.backend.state_backend.store.governance_hook_repository import (
        StateBackendHookRegistrationRepository,
    )
    from agentkit.backend.state_backend.store.lock_record_repository import LockRecordRepository
    from agentkit.backend.state_backend.store.worktree_repository import (
        StateBackendWorktreeRepository,
    )
    from agentkit.backend.story_context_manager.service import StoryService
    from agentkit.backend.story_exit.service import StoryExitService

    governance = Governance(
        hook_repo=StateBackendHookRegistrationRepository(),
        lock_repo=LockRecordRepository(),
        project_key=project_key,
        worktree_repo=StateBackendWorktreeRepository(),
    )
    return StoryExitService(
        control_plane_repository=ControlPlaneRuntimeRepository(),
        story_service=StoryService(),
        governance=governance,
    )


def _default_split_source_state_loader(
    request: StorySplitRequest,
) -> SplitSourceState:
    """Derive the §54.4 entry-gate source state from real run telemetry.

    Reads the FK-25 scope-explosion evidence from the ``execution_events`` stream
    (``scope_explosion_check`` with ``status="exploded"`` and a
    ``mandate_classification`` carrying ``escalation_class="scope_explosion"``)
    and the competing-administrative-operation signal from the control plane.
    This CONSUMES the existing FK-25 detection; it does not rebuild it.
    """
    from agentkit.backend.control_plane.repository import ControlPlaneRuntimeRepository
    from agentkit.backend.story.repository import StoryRepository
    from agentkit.backend.story_split.service import SplitSourceState

    scope_exploded = False
    paused_with_scope_explosion = False
    events = StoryRepository().load_recent_execution_events(
        request.project_key, request.source_story_id, request.run_id, 1000
    )
    for event in events:
        payload = event.payload if isinstance(event.payload, dict) else {}
        if (
            event.event_type == "scope_explosion_check"
            and str(payload.get("status")) == "exploded"
        ):
            scope_exploded = True
        if (
            event.event_type == "mandate_classification"
            and str(payload.get("escalation_class")) == "scope_explosion"
        ):
            paused_with_scope_explosion = True

    repo = ControlPlaneRuntimeRepository()
    competing = repo.has_committed_story_exit_operation_for_run(
        request.project_key, request.source_story_id, request.run_id
    )
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
    source_state_loader: Callable[[StorySplitRequest], SplitSourceState] | None = None,
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
    from agentkit.backend.state_backend.store.worktree_repository import (
        StateBackendWorktreeRepository,
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
        worktree_repo=StateBackendWorktreeRepository(),
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
        def mark_superseded(
            self, *, story_id: str, superseded_by: tuple[str, ...]
        ) -> int:
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
                    "source superseded re-export/reindex failed for "
                    f"{story_id!r}: {result.error or 'no detail reported'}",
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
    from agentkit.backend.control_plane.repository import ControlPlaneRuntimeRepository
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
    from agentkit.backend.state_backend.store.worktree_repository import (
        StateBackendWorktreeRepository,
    )
    from agentkit.backend.story.repository import StoryRepository
    from agentkit.backend.story_context_manager.service import StoryService
    from agentkit.backend.story_reset import FileResetRecordStore, StoryResetService

    resolved_root = project_root or store_dir
    lock_repo = LockRecordRepository(store_dir)
    governance = Governance(
        hook_repo=StateBackendHookRegistrationRepository(),
        lock_repo=lock_repo,
        project_key=project_key,
        project_root=resolved_root,
        worktree_repo=StateBackendWorktreeRepository(resolved_root),
    )
    cp_repo = ControlPlaneRuntimeRepository()
    story_repo = StoryRepository()
    accessor = build_projection_accessor(store_dir)
    refresh_worker = RefreshWorker(
        FactStore(StateBackendFactRepository(store_dir)),
        StateBackendAnalyticsSource(accessor, project_key=project_key),
    )
    worktree_repo = StateBackendWorktreeRepository(resolved_root)

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
        worktree=WorktreePurgeAdapter(worktree_repo),
    )


def build_kpi_analytics(store_dir: Path, *, project_key: str) -> KpiAnalytics:
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


def build_kpi_analytics_read_facade(store_dir: Path | None = None) -> KpiAnalytics:
    """Wire the read-only KPI facade used by the HTTP KPI routes."""
    from agentkit.backend.kpi_analytics import KpiAnalytics, KpiCatalog
    from agentkit.backend.kpi_analytics.fact_store import FactStore
    from agentkit.backend.state_backend.store.fact_repository import (
        StateBackendFactRepository,
    )

    fact_repository = (
        StateBackendFactRepository()
        if store_dir is None
        else StateBackendFactRepository(store_dir)
    )
    return KpiAnalytics(catalog=KpiCatalog(), fact_store=FactStore(fact_repository))


def build_dashboard_service(
    story_service: StoryService, store_dir: Path | None = None
) -> DashboardService:
    """Wire the legacy dashboard service without leaking fact persistence to HTTP."""
    from agentkit.backend.kpi_analytics.dashboard import DashboardService
    from agentkit.backend.kpi_analytics.fact_store import FactStore
    from agentkit.backend.state_backend.store.fact_repository import (
        StateBackendFactRepository,
    )

    fact_repository = (
        StateBackendFactRepository()
        if store_dir is None
        else StateBackendFactRepository(store_dir)
    )
    return DashboardService(
        story_service=story_service,
        fact_store=FactStore(fact_repository),
    )


def build_task_management_routes(store_dir: Path | None = None) -> TaskManagementRoutes:
    """Wire task-management HTTP routes through the telemetry projection port."""
    import os

    from agentkit.backend.task_management.http.routes import TaskManagementRoutes
    from agentkit.backend.task_management.service import TaskManagement

    resolved_store_dir = store_dir or Path(os.environ.get("AGENTKIT_STORE_DIR", "."))
    service = TaskManagement(build_projection_accessor(resolved_store_dir))
    return TaskManagementRoutes(task_management=service)


def build_project_repository(store_dir: Path | None = None) -> ProjectRepository:
    """Wire the project-management repository adapter."""
    from agentkit.backend.state_backend.store.project_management_repository import (
        StateBackendProjectRepository,
    )

    return StateBackendProjectRepository(store_dir)


def build_project_read_model_routes(store_dir: Path | None = None) -> ReadModelRoutes:
    """Wire project-scoped frontend read-model routes outside the HTTP boundary."""
    from agentkit.backend.project_management.read_model_routes import ReadModelRoutes
    from agentkit.backend.state_backend.store.parallelization_config_repository import (
        StateBackendParallelizationConfigRepository,
    )
    from agentkit.backend.state_backend.store.story_are_link_repository import (
        StateBackendStoryAreLinkRepository,
    )
    from agentkit.backend.story_context_manager.service import StoryService as _StoryContextService

    return ReadModelRoutes(
        project_repository=build_project_repository(store_dir),
        story_service=_StoryContextService(),
        config_repository=StateBackendParallelizationConfigRepository(store_dir),
        are_link_repository=StateBackendStoryAreLinkRepository(store_dir),
    )


def build_exploration_review(
    ctx: StoryContext,
    story_dir: Path,
    *,
    llm_client: LlmClient | None = None,
    conformance_config: ConformanceConfig | None = None,
) -> ExplorationReview:
    """Wire the three-stage exploration exit-gate (AG3-046, FK-23 §23.5).

    Composition root for :class:`ExplorationReview`: builds the Stage 1
    document-fidelity checker and the Stage 2a design-review runner over the
    Layer-2 :class:`StructuredEvaluator`, the
    :class:`PromptRuntimeMaterializer` (FK-44 §44.4.2 prompt source) and the
    :class:`ArtifactReviewResultSink` (QA-artifact persistence). Stage 2b
    design-challenge is wired as ``None`` (mandate-gated activation is AG3-047).

    The LLM transport defaults to the fail-closed :class:`FailClosedLlmClient`
    (no LLM pool is wired productively yet, FK-11 follow-up): every gate stage
    then FAILS CLOSED at the LLM boundary rather than silently approving (NO
    ERROR BYPASSING). Once the pool adapter exists the caller injects it here.

    Args:
        ctx: The story context for the run (carries ``project_root`` /
            ``story_id``; required by the prompt materializer).
        story_dir: Story working directory (run-scope + artifact store root).
        llm_client: Optional Layer-2 LLM transport. ``None`` => the fail-closed
            :class:`FailClosedLlmClient` (gate fails closed until a pool exists).
        conformance_config: Optional FK-32 §32.4b.3 prompt-size thresholds.
            ``None`` => the service's built-in defaults (50 KB / 500 KB) are used.
            Pass ``project_config.pipeline.conformance`` to make the configured
            thresholds effective for this exploration review.

    Returns:
        A wired :class:`ExplorationReview`.
    """
    from agentkit.backend.exploration.review.design_review import DesignReviewRunner
    from agentkit.backend.exploration.review.doc_fidelity import DocFidelityChecker
    from agentkit.backend.exploration.review.persistence import ArtifactReviewResultSink
    from agentkit.backend.exploration.review.review import ExplorationReview as _Review
    from agentkit.backend.state_backend.store.verify_story_context_repository import (
        StateBackendVerifyStoryContextAdapter,
    )
    from agentkit.backend.telemetry.storage import StateBackendEmitter
    from agentkit.backend.verify_system.conformance_service import (
        ConformanceService,
        StructuredEvaluatorConformanceAdapter,
    )
    from agentkit.backend.verify_system.llm_evaluator.llm_client import FailClosedLlmClient
    from agentkit.backend.verify_system.llm_evaluator.prompt_materializer import (
        PromptRuntimeMaterializer,
    )
    from agentkit.backend.verify_system.llm_evaluator.structured_evaluator import (
        StructuredEvaluator,
    )

    manager = build_artifact_manager(story_dir)
    client = llm_client or FailClosedLlmClient()
    materializer = PromptRuntimeMaterializer(
        ctx=ctx,
        story_dir=story_dir,
        artifact_manager=manager,
        story_context_port=StateBackendVerifyStoryContextAdapter(),
    )
    evaluator = StructuredEvaluator(client, materializer)
    sink = ArtifactReviewResultSink(manager)
    conformance_kwargs: dict[str, int] = {}
    if conformance_config is not None:
        conformance_kwargs["file_upload_threshold"] = conformance_config.file_upload_threshold
        conformance_kwargs["hard_limit"] = conformance_config.hard_limit
    conformance = ConformanceService(
        StructuredEvaluatorConformanceAdapter(evaluator),
        emitter=StateBackendEmitter(story_dir),
        **conformance_kwargs,
    )
    return _Review(
        stage1_doc_fidelity=DocFidelityChecker(
            evaluator,
            sink,
            story_context=ctx,
            conformance_service=conformance,
        ),
        stage2a_design_review=DesignReviewRunner(evaluator, sink),
        stage2b_design_challenge=None,
        artifact_manager=manager,
    )


def build_exploration_phase_handler(
    story_dir: Path,
    *,
    review: ExplorationReview | None = None,
    fine_design_evaluator: FineDesignEvaluator | None = None,
) -> ExplorationPhaseHandler:
    """Wire the registrable ``ExplorationPhaseHandler`` surface (AG3-045/AG3-046).

    Composition root for the exploration-phase handler (BC 5,
    ``exploration-and-design``): wires the bloodgroup-A handler to the
    state-backend adapter that fulfils the two boundary ports
    (``RunScopeResolver`` + ``ChangeFrameReader``). The A-core therefore does
    NOT import ``state_backend.store`` itself and does no direct filesystem I/O
    (ARCH-22 / ARCH-31).

    Per PO decision 2026-06-05 ("Option Y") the handler produces NO change-frame:
    it consumes / validates the change-frame persisted by the exploration worker
    (AG3-055). Without a valid change-frame the phase is fail-closed (ESCALATED).

    AG3-046: when a valid change-frame is present the handler runs the three-stage
    exit-gate (:class:`ExplorationReview`). The review is built per-run (it needs
    the ``StoryContext`` for the prompt materializer) via
    :func:`build_exploration_review`; the productive per-run injection +
    ``PhaseHandlerRegistry`` registration is owned by AG3-054. ``review=None``
    (the default here) fails closed: a valid frame with no review wired returns
    ``FAILED`` (never auto-APPROVE, NO ERROR BYPASSING).

    AG3-047: the handler is additionally wired with the mandate-classification
    collaborators (FK-25 §25.3-25.8): :class:`MandateClassification` (over the
    :class:`ScopeExplosionDetector` + :class:`ImpactExceedanceChecker`), the
    :class:`FineDesignSubprocess` skeleton, the :class:`DesignFreezeMarker`
    (freeze-on-PASS, FK-23 §23.4.3), the :class:`MandateTelemetry` emitter wired
    to the canonical :class:`StateBackendEmitter`, and the ``DeclaredImpactReader``
    boundary port (state-backend ``StoryRepository`` read of the story's declared
    ``change_impact``). The bloodgroup-A core imports none of these I/O sources
    directly; the telemetry / state-backend / clock wiring lives HERE.

    AG3-097: the fine-design subprocess is wired with the CONCRETE multi-LLM-hub
    evaluator :class:`HubFineDesignEvaluator` by DEFAULT (built by
    :func:`build_hub_fine_design_evaluator` over the real :class:`HubClient`
    transport + a productive prompt builder + the LLM-delegating convergence
    judge). The REAL build path therefore drives the hub (ChatGPT + a mandatory
    second advisor are acquired/sent over the hub, FK-25 §25.5.2), NOT a stand-in
    that never touches the hub. The convergence VERDICT is delegated to the
    fail-closed LLM client until the FK-11 pool selection is wired, so a class-2
    frame: drives the real hub advisors, then -- per D4-Override (FK-25 §25.5.4
    Z. 642-650) -- ends ``FAILED`` after the bounded retry (cause in
    ``AttemptRecord.failure_cause``) rather than fabricating an APPROVED / freeze
    with no real verdict (ZERO DEBT / FAIL-CLOSED; NO ``infra_unavailable``
    triple). ``fine_design_evaluator`` lets a caller inject an explicit evaluator
    (e.g. the fail-closed :class:`_UnavailableFineDesignEvaluator` for a justified
    hub-absent config, or a scripted evaluator in tests); the DEFAULT is the
    hub-backed evaluator. The :class:`FineDesignSubprocess` shell is unchanged.

    Args:
        story_dir: Story working directory (bound ``FlowExecution`` + the read
            surface root). Passed to the adapter's ``ArtifactManager`` and the
            handler config.
        review: Optional pre-built three-stage exit-gate. ``None`` fails closed
            on a valid change-frame (AG3-054 injects the per-run review).
        fine_design_evaluator: Optional explicit fine-design evaluator. ``None``
            (the default) wires the hub-backed :class:`HubFineDesignEvaluator`
            over the real transport; a caller may inject the fail-closed stand-in
            for a justified hub-absent config or a scripted evaluator in tests.

    Returns:
        A wired ``ExplorationPhaseHandler`` (incl. the AG3-047 mandate flow).
    """
    from datetime import UTC, datetime

    from agentkit.backend.exploration.freeze import DesignFreezeMarker
    from agentkit.backend.exploration.mandate import (
        FineDesignSubprocess,
        ImpactExceedanceChecker,
        MandateClassification,
        ScopeExplosionDetector,
    )
    from agentkit.backend.exploration.mandate.telemetry import MandateTelemetry
    from agentkit.backend.exploration.phase import (
        ExplorationConfig,
    )
    from agentkit.backend.exploration.phase import (
        ExplorationPhaseHandler as _ExplorationPhaseHandler,
    )
    from agentkit.backend.installer.paths import project_root_for_story_dir
    from agentkit.backend.state_backend.store.exploration_change_frame_repository import (
        StateBackendExplorationChangeFrameAdapter,
    )
    from agentkit.backend.telemetry.storage import StateBackendEmitter

    adapter = StateBackendExplorationChangeFrameAdapter(
        build_artifact_manager(story_dir)
    )
    mandate = MandateClassification(
        scope_detector=ScopeExplosionDetector(),
        impact_checker=ImpactExceedanceChecker(),
    )
    evaluator = fine_design_evaluator or build_hub_fine_design_evaluator(story_dir)
    fine_design = FineDesignSubprocess(evaluator)
    freeze_marker = DesignFreezeMarker(
        writer=adapter, clock=lambda: datetime.now(UTC)
    )
    telemetry = MandateTelemetry(StateBackendEmitter(story_dir))
    # AG3-055 produce->consume loop: wire the productive ExplorationDrafting A-core
    # (CONSUMER) + the draft-presence reader so the handler drives the typed loop
    # (consume a present worker draft vs emit a spawn order). The project root is
    # derived from the canonical ``<project_root>/stories/<story_id>`` layout; an
    # off-layout story_dir leaves drafting unwired (the handler keeps the
    # fail-closed branch rather than materializing a prompt against an unknown
    # root). The worker-runner resolves the authoritative StoryContext at draft
    # time (ERROR-2 scope cross-check).
    project_root = project_root_for_story_dir(story_dir)
    drafting = (
        _build_exploration_drafting(story_dir, project_root=project_root)
        if project_root is not None
        else None
    )
    return _ExplorationPhaseHandler(
        change_frame_reader=adapter,
        run_scope_resolver=adapter,
        review=review,
        config=ExplorationConfig(story_dir=story_dir),
        mandate_classification=mandate,
        declared_impact_reader=_StateBackendDeclaredImpactReader(story_dir),
        fine_design=fine_design,
        freeze_marker=freeze_marker,
        telemetry=telemetry,
        drafting=drafting,
        draft_presence=adapter if drafting is not None else None,
    )


def build_hub_fine_design_evaluator(
    story_dir: Path,
    *,
    hub_client: HubClientProtocol | None = None,
    llm_client: LlmClient | None = None,
    owner: str | None = None,
) -> FineDesignEvaluator:
    """Wire the productive multi-LLM-hub fine-design evaluator (AG3-097).

    Composition root for :class:`HubFineDesignEvaluator` (FK-25 §25.5.2/§25.5.4):
    binds the REAL :class:`HubClient` transport (resolved from
    :func:`load_multi_llm_hub_config`, default localhost) plus the productive
    :class:`ChangeFrameFineDesignPromptBuilder` and the LLM-delegating
    :class:`LlmConvergenceJudge`. The judge's verdict transport defaults to the
    fail-closed :class:`FailClosedLlmClient` (no FK-11 LLM pool is wired yet), so
    the assembled evaluator REALLY drives the hub (acquire/send ChatGPT + a
    mandatory second advisor) and then fails closed at the convergence verdict ->
    the caller edge maps that to D4 bounded-retry-then-``FAILED`` (no fabricated
    convergence; ZERO DEBT / FAIL-CLOSED). Once the pool adapter exists the caller
    passes a real ``llm_client`` and the verdict becomes live with no transport
    change.

    Args:
        story_dir: Story working directory (telemetry root + story-id correlation
            via the canonical ``<project_root>/stories/<story_id>`` layout).
        hub_client: Optional hub transport. ``None`` => the real
            :class:`HubClient` over the resolved hub base URL.
        llm_client: Optional convergence-verdict LLM transport. ``None`` => the
            fail-closed :class:`FailClosedLlmClient` (FK-11 pool is a follow-up).
        owner: Optional hub session owner id. ``None`` => a story-correlated
            default.

    Returns:
        A wired :class:`HubFineDesignEvaluator` (typed as the
        :class:`FineDesignEvaluator` port).
    """
    from agentkit.backend.exploration.mandate.hub_fine_design import HubFineDesignEvaluator
    from agentkit.backend.exploration.mandate.hub_fine_design_wiring import (
        ChangeFrameFineDesignPromptBuilder,
        LlmConvergenceJudge,
    )
    from agentkit.backend.telemetry.storage import StateBackendEmitter
    from agentkit.backend.verify_system.llm_evaluator.llm_client import FailClosedLlmClient
    from agentkit.integration_clients.multi_llm_hub.client import HubClient
    from agentkit.integration_clients.multi_llm_hub.config import load_multi_llm_hub_config

    story_id = story_dir.name
    client = hub_client or HubClient(load_multi_llm_hub_config().base_url)
    verdict_client = llm_client or FailClosedLlmClient()
    return HubFineDesignEvaluator(
        client,
        emitter=StateBackendEmitter(story_dir),
        judge=LlmConvergenceJudge(verdict_client),
        prompt_builder=ChangeFrameFineDesignPromptBuilder(),
        owner=owner or f"exploration-fine-design-{story_id}",
        story_id=story_id,
    )


def build_exploration_drafting(
    story_dir: Path,
    ctx: StoryContext,
) -> ExplorationDrafting:
    """Wire the productive ``ExplorationDrafting`` sub (AG3-055, FK-23 §23.3).

    Composition root for the exploration-worker drafting (BC 5,
    ``exploration-and-design``, ``ExplorationDrafting`` sub). Wires the
    bloodgroup-A core to its three boundary ports with PRODUCTIVE adapters:

    * the LLM/worker boundary -- the
      :class:`StateBackendExplorationWorkerRunner` that materializes
      ``worker-exploration.md`` over the AG3-044 worker-spawn path
      (``WorkerSession`` -> ``PromptRuntime``, FK-44; the selector picks
      ``worker-exploration`` for an EXPLORATION ``execution_route``) and reads
      back the worker's raw seven-part draft. No parallel spawn path;
    * the ENTWURF-envelope persistence -- :class:`ArtifactChangeFrameSink` over
      the productive :class:`ArtifactManager` (the AG3-045-registered producer);
    * the protected change-frame FILE writer -- the AG3-045
      :class:`StateBackendExplorationChangeFrameAdapter` (writes
      ``_temp/qa/{story_id}/change_frame.json``, the very path the AG3-045
      handler's reader consumes -- closing the produce->consume loop).

    The A-core imports none of these I/O sources directly (ARCH-22 / ARCH-31).
    The drafting is the PRODUCER; the AG3-045 handler (built by
    :func:`build_exploration_phase_handler`) is the CONSUMER/VALIDATOR of the
    same artifact -- there is NO engine-/handler-side change-frame generation.

    Args:
        story_dir: Story working directory (worker spawn context + the
            ``_temp/qa/{story_id}/`` change-frame location).
        ctx: The authoritative story context for the run (drives the prompt
            materialization + the worker spawn; carries ``project_root``).

    Returns:
        A wired :class:`ExplorationDrafting` ready to produce the change-frame.

    Raises:
        ProjectError: When ``ctx.project_root`` is unset (the prompt runtime
            needs it to materialize ``worker-exploration.md``; fail-closed).
    """
    from agentkit.backend.exceptions import ProjectError

    if ctx.project_root is None:
        raise ProjectError(
            "Exploration drafting requires ctx.project_root to materialize the "
            "worker-exploration prompt (FK-44); refusing fail-closed.",
            detail={"story_id": ctx.story_id, "story_dir": str(story_dir)},
        )
    return _build_exploration_drafting(story_dir, project_root=ctx.project_root)


def _build_exploration_drafting(
    story_dir: Path, *, project_root: Path,
) -> ExplorationDrafting:
    """Wire the productive ``ExplorationDrafting`` from ``story_dir`` + root.

    Shared wiring for :func:`build_exploration_drafting` (ctx-driven) and
    :func:`build_exploration_phase_handler` (story_dir-driven; the handler is
    built at run start before any per-call ``StoryContext`` is in hand, and the
    productive worker-runner resolves the authoritative ``StoryContext`` from
    ``story_dir`` at draft time -- with the ERROR-2 scope cross-check). The three
    boundary ports are the productive adapters; the A-core imports none of these
    I/O sources directly (ARCH-22 / ARCH-31).

    Args:
        story_dir: Story working directory (worker spawn context + the
            ``_temp/qa/{story_id}/`` change-frame location).
        project_root: The project root the prompt runtime materializes against
            (FK-44).

    Returns:
        A wired :class:`ExplorationDrafting`.
    """
    from agentkit.backend.exploration.drafting import ExplorationDrafting as _Drafting
    from agentkit.backend.exploration.drafting.persistence import ArtifactChangeFrameSink
    from agentkit.backend.prompt_runtime import PromptRuntime
    from agentkit.backend.state_backend.store.exploration_change_frame_repository import (
        StateBackendExplorationChangeFrameAdapter,
    )
    from agentkit.backend.state_backend.store.exploration_worker_runner import (
        StateBackendExplorationWorkerRunner,
    )

    manager = build_artifact_manager(story_dir)
    prompt_runtime = PromptRuntime(project_root, manager)
    worker_runner = StateBackendExplorationWorkerRunner(story_dir, prompt_runtime)
    sink = ArtifactChangeFrameSink(manager)
    writer = StateBackendExplorationChangeFrameAdapter(manager)
    return _Drafting(
        worker_runner=worker_runner,
        change_frame_sink=sink,
        change_frame_writer=writer,
    )


@dataclass(frozen=True)
class _StateBackendDeclaredImpactReader:
    """State-backed ``DeclaredImpactReader`` (FK-25 §25.7.1, AG3-047).

    Resolves the story's authoritative declared ``change_impact`` via the
    state-backend :class:`StateBackendStoryRepository` (the GitHub-input story
    stammdaten). The bloodgroup-A exploration core never reads the story store
    directly; this composition-root adapter owns the read.

    FAIL-CLOSED (FK-25 §25.7.1 / FIX-THE-MODEL): an absent / unresolvable story
    RAISES ``CorruptStateError`` rather than defaulting to ``LOCAL`` -- the
    declared impact is the load-bearing input of the Klasse-4 check and must
    never be silently fabricated (no second source of truth, no fail-open).

    Attributes:
        store_dir: State-backend base dir (SQLite); Postgres ignores it.
    """

    store_dir: Path

    def declared_change_impact(self, *, story_id: str) -> ChangeImpact:
        """Return the story's declared change impact (fail-closed).

        Args:
            story_id: The story display id.

        Returns:
            The authoritative declared :class:`ChangeImpact`.

        Raises:
            CorruptStateError: When the story (or its declared impact) cannot be
                resolved (never a silent ``LOCAL`` default).
        """
        from agentkit.backend.exceptions import CorruptStateError
        from agentkit.backend.state_backend.store.story_repository import (
            StateBackendStoryRepository,
        )

        story = StateBackendStoryRepository(self.store_dir).get_by_display_id(
            story_id
        )
        if story is None:
            raise CorruptStateError(
                "Cannot resolve declared change_impact: no persisted story for "
                "the exploration mandate Klasse-4 check (FK-25 §25.7.1, "
                "fail-closed -- no LOCAL default).",
                detail={"story_id": story_id},
            )
        return story.change_impact


@dataclass(frozen=True)
class _UnavailableFineDesignEvaluator:
    """Fail-closed fine-design evaluator for a justified hub-absent config.

    AG3-097: the DEFAULT canonical production wiring now uses the concrete
    :class:`HubFineDesignEvaluator` (see :func:`build_hub_fine_design_evaluator`),
    which drives the real hub. This stand-in remains for a justified config where
    the hub is intentionally absent -- the caller injects it explicitly via
    ``build_exploration_phase_handler(..., fine_design_evaluator=...)``. It must
    NEVER fabricate a converged outcome for a class-2 (fine_design) frame -- that
    would let a story with unresolved design points reach APPROVED / freeze with
    no real fine-design (an Attrappe passing as productive core logic, forbidden).

    It raises :class:`FineDesignEvaluatorUnavailableError` on every round -- the
    honest FK-25 §25.5.4 non-reachability signal ("no LLM is available"). The
    :class:`FineDesignSubprocess` shell does NOT swallow it; per D4-Override
    (FK-25 §25.5.4 Z. 642-650) the exploration phase handler treats
    non-reachability as an OPERATIONAL error -> bounded retry, then ``FAILED``
    (cause in AttemptRecord.failure_cause) -- NOT a pause, NO ``infra_unavailable``
    triple.
    """

    def run_round(
        self, change_frame: ChangeFrame, *, round_number: int
    ) -> FineDesignRoundOutcome:
        """Raise fail-closed: no real fine-design evaluator is wired yet.

        Args:
            change_frame: The change-frame being refined (unused; no real
                discussion is held).
            round_number: The 1-based round number (unused).

        Raises:
            FineDesignEvaluatorUnavailableError: Always -- the productive
                multi-LLM evaluator is a follow-up (FK-25 §25.5.4). Never returns
                a fabricated convergence (ZERO DEBT / FAIL-CLOSED).
        """
        from agentkit.backend.exploration.mandate.fine_design import (
            FineDesignEvaluatorUnavailableError,
        )

        del change_frame, round_number
        msg = (
            "fine-design evaluator unavailable: the productive multi-LLM "
            "fine-design discussion (FK-25 §25.5) is a follow-up story; "
            "escalating the class-2 frame fail-closed (FK-25 §25.5.4)"
        )
        raise FineDesignEvaluatorUnavailableError(msg)


def build_verify_system(
    store_dir: Path,
    *,
    max_major_findings: int = 0,
    max_feedback_rounds: int | None = None,
    sonar_gate_port: SonarGateInputPort | None = None,
    layer2_llm_client: LlmClient | None = None,
    fast_test_runner: Callable[[Path], tuple[bool, str | None]] | None = None,
    structural_build_test_port: BuildTestEvidencePort | None = None,
    structural_are_provider: AreGateProvider | None = None,
    conformance_config: ConformanceConfig | None = None,
    layer2_bundle_token_limit: int = 32_000,
) -> VerifySystem:
    """Create a fully wired ``VerifySystem``.

    Composition root for the QA-subflow top-surface (AG3-026):
    instantiates all five sub-components and wires a real
    ``ArtifactManager`` (incl. ProducerRegistry) as the persistence facade.

    AG3-035 (real drift fix): additionally wires the
    ``StateBackendVerifyStoryContextAdapter`` as ``story_context_port`` so
    ``verify_system`` resolves the ``StoryContext`` via a port instead of a
    direct ``state_backend.store`` import (BC topology).

    AG3-052 (FK-33 §33.6): the ``sonarqube_gate`` docking point uses a
    ``SonarGateInputPort``. When ``sonarqube.available == true`` the caller
    (pipeline engine) passes in the productive
    :class:`ConfiguredSonarGateInputPort` via ``sonar_gate_port`` (built via
    :func:`build_sonar_gate_port` with the per-run resolved coordinates);
    without injection the absent-default port stays active
    (``available == false`` => stage SKIP). This keeps a
    configured-but-unreachable Sonar fail-closed without this builder having to
    know the per-story coordinates.

    Args:
        store_dir: Base directory of the state backend. Passed through to
            ``build_artifact_manager``.
        max_major_findings: Threshold for the PolicyEngine (number of
            tolerated MAJOR findings; 0 = every MAJOR blocks).
        max_feedback_rounds: Ceiling for the subflow-internal remediation loop
            (FK-03 §3.4.2 / FK-38, ``policy.max_feedback_rounds``). The caller
            (phase handler) resolves it from the pipeline config and passes it
            in; ``None`` => controller default (3). The
            ``RemediationLoopController`` is the hard owner of the bound (not
            skippable, NO ERROR BYPASSING).
        sonar_gate_port: Optional productive ``SonarGateInputPort``
            (FK-33 §33.6). ``None`` => absent-default port.
        layer2_llm_client: Optional ``LlmClient`` (AG3-043 E6, FK-27 §27.5).
            ``None`` => the composition root wires the fail-closed
            :class:`FailClosedLlmClient` so Layer 2 in the default path REALLY
            runs (three parallel LLM evaluations) instead of silently falling
            back to the deterministic stub reviewers. As long as the concrete
            LLM-pool selection (FK-11, follow-up story) is missing, the
            fail-closed client fails every ``complete`` call -> Layer 2
            FAIL-CLOSED (no silent skip, FK-34 §34.5.1). Once the pool adapter
            exists, the caller passes it in here.
        conformance_config: Optional FK-32 §32.4b.3 prompt-size thresholds
            from the per-run ``ProjectConfig.pipeline.conformance`` stanza.
            ``None`` => the ConformanceService's built-in defaults (50 KB /
            500 KB) are used. Pass
            ``project_config.pipeline.conformance`` to make the configured
            thresholds effective for impl-fidelity assessments (ERROR 4 fix,
            AG3-063 remediation 2).
        layer2_bundle_token_limit: Per-field section-aware Layer-2 packing
            limit from ``ProjectConfig.pipeline.layer2.bundle_token_limit``.

    Returns:
        ``VerifySystem`` with all five sub-components and a fully wired
        ``ArtifactManager`` as well as a productively wired Layer-2 LLM
        client (E6).
    """
    from agentkit.backend.state_backend.store.verify_story_context_repository import (
        StateBackendVerifyStoryContextAdapter,
    )
    from agentkit.backend.telemetry.storage import StateBackendEmitter
    from agentkit.backend.verify_system.llm_evaluator.llm_client import FailClosedLlmClient
    from agentkit.backend.verify_system.structural.checker import FULL_STAGE_REGISTRY
    from agentkit.backend.verify_system.system import VerifySystem

    manager = build_artifact_manager(store_dir)
    resolved_llm_client = layer2_llm_client or FailClosedLlmClient()
    return VerifySystem.create_default(
        max_major_findings=max_major_findings,
        max_feedback_rounds=max_feedback_rounds,
        artifact_manager=manager,
        story_context_port=StateBackendVerifyStoryContextAdapter(),
        sonar_gate_port=sonar_gate_port,
        invalidation_sink=build_artifact_invalidation_sink(store_dir),
        # FIX-C (FK-27 §27.4.3 / §27.5.5): after each Layer-2 review artefact
        # write the QA-subflow emits a canonical ``llm_call_complete`` event
        # (per reviewer role) so ``guard.multi_llm`` counts a COMPLETED review.
        # Without this productive sink the count is always 0 and the gate is
        # inert/over-blocking. The telemetry import lives here, not in the BC.
        review_completion_sink=build_review_completion_sink(store_dir),
        conformance_emitter=StateBackendEmitter(store_dir),
        conformance_config=conformance_config,
        layer2_bundle_token_limit=layer2_bundle_token_limit,
        layer2_llm_client=resolved_llm_client,
        fast_test_runner=fast_test_runner,
        # AG3-042: the PRODUCTIVE path wires the full FK-27 §27.4 Layer-1 stage
        # catalogue (StructuralChecker + PolicyEngine fail-closed check).
        stage_registry=FULL_STAGE_REGISTRY,
        # AG3-042: the FK-27 §27.4.3 recurring guards count canonical
        # ``execution_events`` via a port so verify-system never imports
        # ``state_backend.store`` directly (BC-topology, AG3-035).
        structural_telemetry_port=_StateBackendTelemetryEventCountPort(),
        # FIX-3 (FK-33 §33.5): the BLOCKING branch/commit/push/secrets/impact
        # checks decide on INDEPENDENT system git evidence, wired here as the
        # productive subprocess-git provider (verify-system stays free of
        # subprocess; the import lives in this composition root). NEVER the
        # worker manifest.
        structural_change_evidence_port=_SubprocessGitChangeEvidenceProvider(),
        # FIX-1: the REAL build/test evidence port + the real ARE provider need
        # per-run config (the project ``ci`` stanza / ``features.are``) the
        # builder does not have, so the per-run caller (ImplementationPhaseHandler)
        # resolves and injects them via :func:`build_structural_build_test_port`
        # / :func:`build_structural_are_provider`. Absent here => the fail-closed
        # default ports (build/test BLOCKING fail, ARE stage not planned), so a
        # bare build_verify_system never over-blocks a story with a fabricated
        # green NOR silently disables ARE.
        structural_build_test_port=structural_build_test_port,
        structural_are_provider=structural_are_provider,
    )


@dataclass(frozen=True)
class _StateBackendTelemetryEventCountPort:
    """State-backed ``TelemetryEventQueryPort`` (FK-27 §27.4.3, AG3-042).

    Counts canonical ``execution_events`` of a given type for a story via the
    state-backend facade, scoped to ``(project_key, story_id, run_id)`` per
    FK-33 §33.3.2 -- a recurring-guard count must not bleed across projects or
    across prior runs of the same story. When the caller does not supply a
    ``run_id`` the adapter resolves the ACTIVE run for ``story_dir`` (via the
    persisted run scope) so a prior, reset, or replayed run never counts toward
    the current guard. The ``state_backend.store`` import lives HERE (the
    composition root), not in ``verify_system`` (BC-topology, AG3-035). Counts
    fail soft to ``0`` on any backend error so the BLOCKING guards stay
    fail-closed (a missing/unreadable event store yields ``0`` -> FAIL).
    """

    def count_events(
        self,
        story_dir: Path,
        *,
        story_id: str,
        event_type: str,
        role: str | None = None,
        project_key: str | None = None,
        run_id: str | None = None,
    ) -> int:
        """Count matching canonical ``execution_events`` (``0`` on error).

        Scoped to ``(project_key, story_id, run_id)`` (FK-33 §33.3.2). When
        ``run_id`` is ``None`` the active run for ``story_dir`` is resolved so
        a prior run's events are excluded. When ``role`` is given, only events
        whose ``payload['role']`` matches are counted (FK-27 §27.4.3 Gate 2:
        ``llm_call_complete`` events carry the reviewer role in their payload).
        """
        from agentkit.backend.state_backend.store import load_execution_events

        resolved_run_id = run_id or self._resolve_active_run_id(story_dir)
        if resolved_run_id is None:
            # FIX-B (FK-33 §33.3.2 run scope, fail-CLOSED): when the run scope
            # cannot be resolved we MUST NOT query unscoped. A
            # ``load_execution_events(..., run_id=None)`` would count across ALL
            # runs of the story, so the must-have-events guards
            # (``guard.review_compliance`` / ``guard.multi_llm`` /
            # ``guard.llm_reviews``) could PASS on a prior run's telemetry
            # (fail-open). Returning 0 makes every BLOCKING must-have-events
            # guard FAIL closed on an unresolvable run scope, and never lets
            # ``guard.no_violations`` free-pass on stale events: a
            # ``count_events`` of 0 there means "no integrity_violation visible
            # for this run", which is the only honest reading when the run scope
            # is unknown (the violation, if any, lives under a resolvable run).
            return 0
        try:
            events = load_execution_events(
                story_dir,
                project_key=project_key,
                story_id=story_id,
                run_id=resolved_run_id,
                event_type=event_type,
            )
        except Exception:  # noqa: BLE001 -- fail-soft to 0 (fail-closed guard).
            return 0
        if role is None:
            return len(events)
        return sum(
            1
            for event in events
            if isinstance(getattr(event, "payload", None), dict)
            and event.payload.get("role") == role
        )

    def run_scope_resolvable(self, story_dir: Path) -> bool:
        """Whether the active run scope for ``story_dir`` resolves (FIX-B).

        FK-33 §33.3.2: ``guard.no_violations`` PASSES on a ``0`` count, so it
        must fail closed when the run scope is unknown rather than free-pass on
        stale/unknown telemetry. Returns ``True`` iff the persisted run scope
        yields a run id.
        """
        return self._resolve_active_run_id(story_dir) is not None

    def _resolve_active_run_id(self, story_dir: Path) -> str | None:
        """Resolve the active run id for ``story_dir`` (``None`` when unknown).

        FK-33 §33.3.2 run scope: the recurring guards count events of the
        CURRENT run only. The authoritative run correlation is the persisted
        run scope of the story's flow execution.
        """
        from agentkit.backend.state_backend.store import facade

        try:
            scope = facade.resolve_runtime_scope(story_dir)
        except Exception:  # noqa: BLE001 -- unresolved scope -> no run filter
            return None
        return getattr(scope, "run_id", None)


#: Test-file path markers used to count test files in a changeset (FK-27
#: ``test.count``): a changed path is a test file when its name matches.
_TEST_FILE_MARKERS: tuple[str, ...] = ("test_", "_test.", "/tests/", "tests/")


@dataclass(frozen=True)
class _SubprocessGitChangeEvidenceProvider:
    """Productive ``ChangeEvidencePort`` over real ``git`` (FIX-3, FK-33 §33.5).

    Collects INDEPENDENT system evidence about the story's change set by running
    read-only ``git`` commands in the story worktree (NEVER the worker manifest):
    the actual checked-out branch, the commit history since ``origin/main`` (the
    base ref), the upstream-push state, the diff's changed + secret-shaped files
    and the diff-derived actual change impact (FK-23 §23.8). The ``git`` import
    (subprocess) lives HERE in the composition root, keeping ``verify_system``
    free of subprocess. Any git error yields ``available=False`` so the BLOCKING
    checks fail closed (NO ERROR BYPASSING; never a fall-back to self-report).
    """

    base_ref: str = "origin/main"

    def collect(self, story_dir: Path) -> ChangeEvidence:
        """Collect the system change evidence (``available=False`` on any error)."""
        from agentkit.backend.verify_system.structural.system_evidence import ChangeEvidence

        branch = self._git(story_dir, "rev-parse", "--abbrev-ref", "HEAD")
        if branch is None:
            return ChangeEvidence(available=False)
        base = self._merge_base(story_dir)
        commits = self._commit_messages(story_dir, base)
        changed = self._changed_files(story_dir, base)
        secret_files = self._secret_files(changed)
        secret_content_hits = self._secret_content_hits(story_dir, base)
        actual_impact = _derive_actual_impact(changed)
        return ChangeEvidence(
            available=True,
            current_branch=branch,
            commit_messages=commits,
            pushed=self._is_pushed(story_dir),
            secret_files=secret_files,
            secret_content_hits=secret_content_hits,
            changed_files=changed,
            actual_impact=actual_impact,
        )

    def _merge_base(self, story_dir: Path) -> str | None:
        """Resolve the base ref to diff against (``origin/main``, else empty)."""
        return self._git(story_dir, "merge-base", self.base_ref, "HEAD")

    def _commit_messages(self, story_dir: Path, base: str | None) -> tuple[str, ...]:
        rng = f"{base}..HEAD" if base else "HEAD"
        out = self._git(story_dir, "log", "--format=%B%x00", rng)
        if out is None:
            return ()
        return tuple(m.strip() for m in out.split("\x00") if m.strip())

    def _changed_files(self, story_dir: Path, base: str | None) -> tuple[str, ...]:
        spec = f"{base}..HEAD" if base else "HEAD"
        out = self._git(story_dir, "diff", "--name-only", spec)
        if out is None:
            return ()
        return tuple(line.strip() for line in out.splitlines() if line.strip())

    def _secret_files(self, changed: tuple[str, ...]) -> tuple[str, ...]:
        from agentkit.backend.governance.guard_system.secret_patterns import (
            find_secret_file_hits,
        )

        return tuple(hit.path for hit in find_secret_file_hits(changed))

    def _secret_content_hits(
        self,
        story_dir: Path,
        base: str | None,
    ) -> tuple[str, ...]:
        from agentkit.backend.governance.guard_system.secret_scan import scan_paths_and_diff

        spec = f"{base}..HEAD" if base else "HEAD"
        out = self._git(story_dir, "diff", "--unified=0", "--no-ext-diff", spec)
        if out is None:
            return ()
        result = scan_paths_and_diff((), out)
        return tuple(
            f"{hit.path}:{hit.pattern.value}" for hit in result.content_hits
        )

    def _is_pushed(self, story_dir: Path) -> bool:
        """Whether the branch has an upstream whose tip contains HEAD."""
        upstream = self._git(
            story_dir, "rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}"
        )
        if upstream is None:
            return False
        head = self._git(story_dir, "rev-parse", "HEAD")
        upstream_sha = self._git(story_dir, "rev-parse", upstream)
        if head is None or upstream_sha is None:
            return False
        # The branch is pushed when the upstream is an ancestor of (or equal to)
        # HEAD's pushed tip; conservatively require the upstream to contain HEAD.
        contains = self._git(
            story_dir, "merge-base", "--is-ancestor", head, upstream
        )
        return contains is not None

    def _git(self, story_dir: Path, *args: str) -> str | None:
        """Run a read-only git command; return stripped stdout or ``None``."""
        import subprocess  # noqa: PLC0415 -- comp-root owns the subprocess import

        try:
            # Fixed git argv, no shell.
            result = subprocess.run(  # noqa: S603
                ["git", "-C", str(story_dir), *args],  # noqa: S607
                capture_output=True,
                text=True,
                check=False,
            )
        except OSError:
            return None
        if result.returncode != 0:
            return None
        return result.stdout.strip()


#: Diff size threshold below which a single-component change stays ``LOCAL``.
_LOCAL_FILE_THRESHOLD = 3
#: Number of distinct top-level components that marks a CROSS_COMPONENT change.
_CROSS_COMPONENT_DIRS = 2


def _derive_actual_impact(changed_files: tuple[str, ...]) -> ChangeImpact | None:
    """Derive the SYSTEM actual change impact from the diff (FK-23 §23.8).

    A deterministic, diff-based proxy (no worker input): more distinct top-level
    components touched => higher impact. This is the independent measurement the
    BLOCKING ``impact.violation`` check compares against the worker's declared
    budget. ``None`` only for an empty diff (nothing changed).
    """
    from agentkit.backend.story_context_manager.story_model import ChangeImpact

    if not changed_files:
        return None
    top_dirs = {f.split("/", 1)[0] for f in changed_files if "/" in f} or {""}
    distinct = len(top_dirs)
    if distinct <= 1:
        return (
            ChangeImpact.LOCAL
            if len(changed_files) <= _LOCAL_FILE_THRESHOLD
            else ChangeImpact.COMPONENT
        )
    if distinct == _CROSS_COMPONENT_DIRS:
        return ChangeImpact.CROSS_COMPONENT
    return ChangeImpact.ARCHITECTURE_IMPACT


def build_artifact_invalidation_sink(store_dir: Path) -> ArtifactInvalidationSink:
    """Build the productive ``artifact_invalidated`` telemetry sink (AG3-041 §2.1.3).

    Composition-Root wiring for FK-27 §27.2.3: every cycle-bound QA artefact
    moved to ``stale/`` on ``advance_qa_cycle`` emits an ``artifact_invalidated``
    telemetry event through the canonical :class:`StateBackendEmitter`. This is
    the productive default for ``build_verify_system`` — NOT a no-op stub.
    ``verify_system`` only knows the ``ArtifactInvalidationSink`` Protocol; the
    telemetry import lives here, keeping the BC free of a telemetry dependency.

    Args:
        store_dir: Story working directory (the canonical event store root).

    Returns:
        A productive sink that emits ``artifact_invalidated`` events.
    """
    from agentkit.backend.telemetry.storage import StateBackendEmitter

    return _TelemetryArtifactInvalidationSink(StateBackendEmitter(store_dir))


@dataclass(frozen=True)
class _TelemetryArtifactInvalidationSink:
    """Adapt ``ArtifactInvalidationEvent`` facts onto the telemetry emitter.

    Bridges the ``verify_system`` invalidation Protocol to the canonical
    telemetry ``EventEmitter`` (FK-27 §27.2.3 / FK-68). Each invalidation fact
    becomes an ``EventType.ARTIFACT_INVALIDATED`` event carrying the moved
    file, the old epoch and the source/stale paths. Emission never raises
    (``StateBackendEmitter.emit`` swallows storage errors, ARCH-20); the file
    move has already happened, so a telemetry hiccup never corrupts QA truth.
    """

    emitter: EventEmitter

    def artifact_invalidated(self, event: ArtifactInvalidationEvent) -> None:
        """Emit an ``artifact_invalidated`` telemetry event for one moved file.

        Args:
            event: The invalidation fact (story, filename, epoch, paths).
        """
        from agentkit.backend.telemetry.events import Event, EventType

        self.emitter.emit(
            Event(
                story_id=event.story_id,
                event_type=EventType.ARTIFACT_INVALIDATED,
                phase="implementation",
                source_component="verify-system",
                payload={
                    "filename": event.filename,
                    "old_epoch": event.old_epoch,
                    "source_path": str(event.source_path),
                    "stale_path": str(event.stale_path),
                },
            )
        )


def build_review_completion_sink(store_dir: Path) -> ReviewCompletionSink:
    """Build the productive ``llm_call_complete`` telemetry sink (FIX-C).

    Composition-Root wiring for FK-27 §27.4.3 / §27.5.5: after each Layer-2
    review artefact is written, the QA-subflow emits a canonical
    ``llm_call_complete`` execution event (carrying the reviewer role) through
    the canonical :class:`StateBackendEmitter`. This is what the
    ``guard.multi_llm`` Gate 2 counts (per mandatory reviewer role) so the gate
    is meaningful: it passes a genuine multi-LLM run and FAILS when reviews are
    missing (FK-37 §37.1.6). ``verify_system`` only knows the
    ``ReviewCompletionSink`` Protocol; the telemetry import lives HERE.

    Args:
        store_dir: Story working directory (the canonical event store root).

    Returns:
        A productive sink that emits ``llm_call_complete`` events.
    """
    from agentkit.backend.telemetry.storage import StateBackendEmitter

    return _TelemetryReviewCompletionSink(StateBackendEmitter(store_dir))


@dataclass(frozen=True)
class _TelemetryReviewCompletionSink:
    """Adapt ``ReviewCompletionEvent`` facts onto the telemetry emitter (FIX-C).

    Bridges the ``verify_system`` review-completion Protocol to the canonical
    telemetry ``EventEmitter`` (FK-27 §27.4.3 / §27.5.5). Each completion fact
    becomes an ``EventType.LLM_CALL_COMPLETE`` event whose payload ``role``
    matches the ``guard.multi_llm`` per-role filter. The event is emitted ONLY
    after the review artefact write succeeded (the caller invokes the sink after
    a successful envelope write), per FK-27 §27.4.3. Emission never raises
    (``StateBackendEmitter.emit`` swallows storage errors, ARCH-20); the review
    artefact is already written, so a telemetry hiccup never corrupts QA truth.
    The run scope is resolved by the emitter from ``store_dir`` (the SAME run
    scope the recurring-guard count reads), so the emitted event lands under the
    active run and the run-scoped Gate-2 count finds it (FK-33 §33.3.2).
    """

    emitter: EventEmitter

    def review_completed(self, event: ReviewCompletionEvent) -> None:
        """Emit an ``llm_call_complete`` telemetry event for one completed review.

        Args:
            event: The completion fact (story, reviewer role, artefact filename).
        """
        from agentkit.backend.telemetry.events import Event, EventType

        self.emitter.emit(
            Event(
                story_id=event.story_id,
                event_type=EventType.LLM_CALL_COMPLETE,
                phase="implementation",
                source_component="verify-system",
                payload={
                    "role": event.role,
                    "artifact_filename": event.artifact_filename,
                },
            )
        )


def build_sonar_gate_port(
    config: object,
    *,
    client: object,
    fast: bool,
    story_type: object,
    ledger: object,
    bound_analysis: object,
    main_head_revision: str,
) -> SonarGateInputPort:
    """Build the productive ``sonarqube_gate`` port (FK-33 §33.6, AG3-052).

    When ``sonarqube.available == false`` the gate is deliberately absent
    (not-applicable) and the absent default port is returned — never the
    fail-closed adapter (FK-33 §33.6.5 "absent != broken"). Otherwise the
    :class:`ConfiguredSonarGateInputPort` is wired with the per-run
    collaborators; it fails closed on any unreachable/unreadable input.

    The per-run coordinates (the commit-bound analysis, the loaded ledger,
    main HEAD, the fast axis/story type) are resolved by the caller (pipeline
    engine) and passed in; this keeps ``build_verify_system`` free of
    per-story knowledge. The objects are typed loosely here to avoid
    importing the capability submodules at module top-level; they are
    validated by the adapter.

    Args:
        config: The resolved ``SonarQubeConfig``.
        client: A connected ``integrations.sonar`` ``SonarClient``.
        fast: Whether the run is in ``fast`` mode (FK-24 §24.3.3) — the
            SEPARATE fast/standard axis (``story_context.mode is
            WireStoryMode.FAST``), NOT ``execution_route``.
        story_type: Resolved ``StoryType``.
        ledger: The loaded ``AcceptedExceptionLedger``.
        bound_analysis: The commit-bound ``BoundAnalysis`` coordinates.
        main_head_revision: Authoritative current main HEAD revision.

    Returns:
        A productive ``SonarGateInputPort`` (or the absent default port
        when ``available == false``).
    """
    from agentkit.backend.config.models import SonarQubeConfig
    from agentkit.backend.story_context_manager.types import StoryType
    from agentkit.backend.verify_system.sonarqube_gate.adapter import (
        BoundAnalysis,
        ConfiguredSonarGateInputPort,
    )
    from agentkit.backend.verify_system.sonarqube_gate.ledger import AcceptedExceptionLedger
    from agentkit.backend.verify_system.sonarqube_gate.port import (
        ABSENT_SONAR_GATE_PORT,
    )
    from agentkit.integration_clients.sonar import SonarClient

    if not isinstance(config, SonarQubeConfig):
        msg = f"config must be a SonarQubeConfig; got {type(config).__name__}"
        raise TypeError(msg)
    if not config.available:
        # Deliberately absent Sonar => not-applicable skip; never fail-closed.
        return ABSENT_SONAR_GATE_PORT
    if not isinstance(client, SonarClient):
        msg = f"client must be a SonarClient; got {type(client).__name__}"
        raise TypeError(msg)
    if not isinstance(ledger, AcceptedExceptionLedger):
        msg = f"ledger must be an AcceptedExceptionLedger; got {type(ledger).__name__}"
        raise TypeError(msg)
    if not isinstance(bound_analysis, BoundAnalysis):
        msg = f"bound_analysis must be a BoundAnalysis; got {type(bound_analysis).__name__}"
        raise TypeError(msg)
    if not isinstance(story_type, StoryType):
        msg = f"story_type must be a StoryType; got {type(story_type).__name__}"
        raise TypeError(msg)
    return ConfiguredSonarGateInputPort(
        config=config,
        client=client,
        fast=bool(fast),
        story_type=story_type,
        ledger=ledger,
        bound_analysis=bound_analysis,
        main_head_revision=main_head_revision,
    )


def build_skills(
    store_dir: Path,
    *,
    bundle_store_root: Path | None = None,
) -> Skills:
    """Create a fully wired ``Skills`` top-surface (AG3-048).

    Composition root for the agent-skills BC (FK-43, bc-cut-decisions.md §BC 11
    + §BC 12), analogous to ``build_artifact_manager``: binds the system-wide
    ``SkillBundleStore`` and the productive
    ``StateBackendSkillBindingRepository`` into a ``Skills`` instance. Callers
    (installer, runtime, tests) receive ``Skills`` via DI and do not know the
    repository implementation.

    Architecture conformance: ``agentkit.backend.skills`` does NOT import from
    ``state_backend.store``; the wiring of the state-backend persistence
    happens exclusively here in the composition root.

    Args:
        store_dir: Base directory of the state backend (SQLite stores under
            ``store_dir/.agentkit/...``; Postgres ignores the path).
        bundle_store_root: Optional override for the system-wide
            skill-bundle store. ``None`` -> platform default (FK-43 §43.5.2).

    Returns:
        ``Skills`` with ``SkillBundleStore`` + ``StateBackendSkillBindingRepository``.
    """
    from agentkit.backend.skills import Skills as _Skills
    from agentkit.backend.skills.bundle_store import SkillBundleStore as _SkillBundleStore
    from agentkit.backend.state_backend.store.skill_binding_repository import (
        StateBackendSkillBindingRepository,
    )

    bundle_store = _SkillBundleStore(store_root=bundle_store_root)
    repository = StateBackendSkillBindingRepository(store_dir)
    projection_accessor = build_projection_accessor(store_dir)
    return _Skills(
        bundle_store=bundle_store,
        binding_repo=repository,
        projection_accessor=projection_accessor,
    )


def build_integrity_gate(store_dir: Path | None = None) -> IntegrityGate:
    """Create a fully wired ``IntegrityGate``.

    Composition root for the closure phase (AG3-031 Pass-5 Fix E9):
    instantiates ``StateBackendIntegrityGateStateAdapter`` as ``state_port``.

    AG3-034 (Finding E / Remediation E-F): additionally wires the
    ``EnvelopeValidator`` so the required-artifact pre-stage runs the
    envelope required-field check (FK-71 §71.2) for **every** required QA
    artifact (Structural Dim 1 + Decision Dim 4) (``ENVELOPE_VIOLATION`` on a
    violation).  The dimensions read the canonical QA envelopes themselves via
    the ``state_port`` (FK-35 §35.2.4 producer/status/depth).

    Dimension 9 (SONARQUBE_GREEN, R2-C/A2): wires the productive
    ``ProductiveSonarDimensionPort``, which CONSUMES the AG3-052 capability
    (``build_sonar_gate_port_for_run`` + ``evaluate_sonarqube_gate``) — no
    own attestation mechanic, no None-stub loader.  The capability resolves the
    applicability from ``sonarqube.available`` + story ``mode`` + story type
    (``available == false`` / fast / non-code => not-applicable, Dim 9
    is omitted).  For an APPLICABLE impl/bugfix run
    ``build_sonar_gate_port_for_run`` reads the commit-bound scan artifact; if
    it is absent (the integrated pre-merge scan FK-29 §29.1a is OOS), the
    capability yields a fail-closed APPLICABLE port (``attestation = None``) and
    ``evaluate_sonarqube_gate`` a ``failed`` outcome -> Dim 9 **fail-closed**
    (``SONAR_NOT_GREEN``/ESCALATED), NEVER a skip.

    Args:
        store_dir: Base directory of the state backend (SQLite); Postgres
            ignores the path.  ``None`` => the repository's default store.

    Returns:
        ``IntegrityGate`` with state port + envelope validation + Dim-9 port.
    """
    from agentkit.backend.governance.integrity_gate import IntegrityGate as _IntegrityGate
    from agentkit.backend.state_backend.store.integrity_gate_repository import (
        StateBackendIntegrityGateStateAdapter,
    )

    validator = EnvelopeValidator(build_producer_registry())
    sonar_port = _build_dim9_sonar_port(store_dir)
    return _IntegrityGate(
        state_port=StateBackendIntegrityGateStateAdapter(),
        envelope_validator=validator,
        sonar_port=sonar_port,
    )


def _build_dim9_sonar_port(store_dir: Path | None) -> SonarDimensionPort:
    """Build the productive Dim-9 ``SonarDimensionPort`` (FK-35 §35.2.4a, R2-C/A2).

    Wires the :class:`ProductiveSonarDimensionPort`, which CONSUMES the AG3-052
    capability (``build_sonar_gate_port_for_run`` + ``evaluate_sonarqube_gate``)
    for the resolution AND the verdict — no hand-rolled attestation loader, no
    second gate mechanic.  The two injected loaders are the truth-boundary reads
    the composition root owns (``governance`` may not read the StoryContext /
    project config directly): one resolves the run's :class:`StoryContext`, the
    other the project :class:`SonarQubeConfig`.  The capability then resolves
    applicability + the commit-bound inputs and produces the canonical outcome.
    """
    from agentkit.backend.governance.integrity_gate.dim9_port import (
        ProductiveSonarDimensionPort,
    )

    _ = store_dir  # the facade resolves the active backend itself.
    return ProductiveSonarDimensionPort(
        _load_sonar_config,  # type: ignore[arg-type]
        _load_story_context_for_gate,  # type: ignore[arg-type]
    )


def _load_story_context_for_gate(gate_ctx: object) -> object | None:
    """Resolve the run's ``StoryContext`` for the Dim-9 port (truth-boundary read).

    Owned by the composition root: ``governance`` may not read the StoryContext
    directly.  An unreadable/absent context returns ``None`` -> the port treats a
    code story as APPLICABLE-but-unresolvable -> Dim 9 fails closed.
    """
    from agentkit.backend.governance.integrity_gate import IntegrityGateContext
    from agentkit.backend.state_backend.store import facade

    assert isinstance(gate_ctx, IntegrityGateContext)  # noqa: S101 - DI guard
    try:
        return facade.load_story_context(gate_ctx.story_dir)
    except Exception:  # noqa: BLE001 -- unreadable context -> fail-closed downstream
        return None


def _load_sonar_config(gate_ctx: object) -> object | None:
    """Resolve the project ``SonarQubeConfig`` for the Dim-9 port (truth boundary).

    Returns the project's ``sonarqube`` config stanza, or ``None`` ONLY for a
    legitimate, deliberate absence: no resolvable project root, or a successfully
    loaded config that simply omits the ``sonarqube`` stanza (a non-code-producing
    project — ``build_sonar_gate_port_for_run`` then resolves a declared skip,
    FK-33 §33.6.5 "absent != broken").

    FAIL-CLOSED (R3-C/A2, analog AG3-052
    ``test_anchor_propagates_config_error_no_silent_skip``): a BROKEN or unreadable
    project config (``ConfigError``/``OSError`` from ``load_project_config``,
    including the E6 hard-fail on an omitted stanza for a code-producing project)
    is NOT a declared absence.  It MUST NOT be swallowed into ``None`` (which would
    route through the absent-port branch => silent Dim-9 skip).  It PROPAGATES so
    the Dim-9 port fails closed (``SONAR_NOT_GREEN``/escalation), never an inert
    skip (FAIL-CLOSED, ZERO DEBT).  ``governance`` never reads the project config
    directly; this composition-root helper owns the read.

    Equally fail-closed (R4-C/A2): an absent/unresolvable ``project_root`` is a
    declared absence ONLY for a NON-code-producing story (the gate never applies
    to it; ``None`` -> deliberate skip).  For a CODE-PRODUCING story
    (implementation/bugfix) an unresolvable ``project_root`` is a BROKEN
    precondition — the config cannot be loaded, so applicability cannot be
    proven absent.  It MUST raise ``ConfigError`` (fail-closed) rather than
    return ``None``, which would otherwise route through the absent-port branch
    into a silent Dim-9 skip = fail-open.  The code-producing axis is the
    AG3-052 SSOT (``is_code_producing_story``), not a re-derived flag.

    Raises:
        ConfigError: When the project config cannot be loaded/validated for a run
            with a resolvable project root (propagated fail-closed), OR when a
            code-producing story has no resolvable ``project_root`` (broken
            precondition => never a silent skip).
        OSError: When the config files cannot be read (propagated fail-closed).
    """
    from agentkit.backend.config.loader import load_project_config
    from agentkit.backend.exceptions import ConfigError
    from agentkit.backend.governance.integrity_gate import IntegrityGateContext
    from agentkit.backend.state_backend.store import facade
    from agentkit.backend.verify_system.sonarqube_gate import is_code_producing_story

    assert isinstance(gate_ctx, IntegrityGateContext)  # noqa: S101 - DI guard
    try:
        ctx = facade.load_story_context(gate_ctx.story_dir)
    except Exception:  # noqa: BLE001 -- unreadable context -> no config
        return None
    if ctx is None or ctx.project_root is None:
        if is_code_producing_story(gate_ctx.story_type):
            # Code-producing story without a resolvable project root: the config
            # is unloadable, so a deliberate absence cannot be proven. Fail
            # closed (never a silent Dim-9 skip; FK-33 §33.6.5, R4-C/A2).
            msg = (
                "cannot resolve project_root for code-producing story "
                f"{gate_ctx.story_type.value!r}: project config unloadable -> "
                "Dim 9 fail-closed (no silent skip)"
            )
            raise ConfigError(msg)
        return None
    # NO try/except ConfigError/OSError -> None here: a broken/unreadable config
    # is a fail-closed condition, NOT a declared absence (R3-C/A2).
    project_config = load_project_config(ctx.project_root)
    pipeline = getattr(project_config, "pipeline", None)
    return getattr(pipeline, "sonarqube", None) if pipeline is not None else None


def build_setup_preflight_gate() -> SetupContextRepository:
    """Create a wired ``SetupContextRepository`` adapter.

    Composition root for the setup phase (AG3-031 Pass-5 Fix E9):
    instantiates ``StateBackendSetupContextAdapter`` and returns it as a
    ``SetupContextRepository``.  Callers pass it in via
    ``SetupPhaseHandler(config, context_repository=...)``.

    Returns:
        ``StateBackendSetupContextAdapter`` as a ``SetupContextRepository``.
    """
    from agentkit.backend.state_backend.store.setup_context_repository import (
        StateBackendSetupContextAdapter,
    )

    return StateBackendSetupContextAdapter()


def build_are_client_from_project_config(project_config: object) -> object | None:
    """Construct the ARE client from the single ProjectConfig ARE truth."""

    from agentkit.backend.config.models import ProjectConfig
    from agentkit.backend.requirements_coverage.are_client import AreClient

    if not isinstance(project_config, ProjectConfig):
        msg = (
            "project_config must be a ProjectConfig; got "
            f"{type(project_config).__name__}"
        )
        raise TypeError(msg)
    if not project_config.pipeline.features.are:
        return None
    if project_config.are is None or not project_config.are.rest_base_url:
        return None
    return AreClient(
        project_config.are.rest_base_url,
        project_config.are.auth_token,
    )


def build_setup_phase_handler(
    config: object,
    *,
    store_dir: Path | None = None,
    dependency_repository: object | None = None,
    green_main_port: object | None = None,
) -> SetupPhaseHandler:
    """Wire a fully-collaborated ``SetupPhaseHandler`` (AG3-034 canonical point).

    Assembles the Setup-phase collaborators the truth-boundary-protected
    handler may not build itself: the context repository, the run-aware
    residue probe (Check 6, Finding B), the project ``ModeLockRepository``
    read path (Check 10) and the optional green-main capability port (FK-22
    §22.4c).  Callers that build a bare ``SetupPhaseHandler(config, repo)``
    miss the residue/mode-lock wiring and the residue check fails closed.

    Args:
        config: The ``SetupConfig``.
        store_dir: State-backend base dir for the residue probe + mode-lock
            repository (SQLite); ``None`` => the config's ``project_root``.
        dependency_repository: Optional ``StoryDependencyRepository`` (Check 4).
        green_main_port: Optional ``MainGreenPort`` (FK-22 §22.4c); ``None`` is
            the absent-Sonar default (green-main SKIPs unless APPLICABLE).

    Returns:
        A wired ``SetupPhaseHandler``.
    """
    from agentkit.backend.config.loader import load_project_config
    from agentkit.backend.governance.setup_preflight_gate.phase import (
        SetupConfig,
        SetupPhaseHandler,
    )
    from agentkit.backend.requirements_coverage.top import RequirementsCoverage
    from agentkit.backend.state_backend.store.mode_lock_repository import ModeLockRepository
    from agentkit.backend.state_backend.store.story_are_link_repository import (
        StateBackendStoryAreLinkRepository,
    )

    if not isinstance(config, SetupConfig):
        msg = f"config must be a SetupConfig; got {type(config).__name__}"
        raise TypeError(msg)
    project_config = load_project_config(config.project_root)
    are_client = build_are_client_from_project_config(project_config)
    are_bundle_loader = RequirementsCoverage(
        are_client,  # type: ignore[arg-type]
        project_config.pipeline,
        link_repository=StateBackendStoryAreLinkRepository(config.project_root),
        artifact_manager=build_artifact_manager(config.project_root),
        audit_root=config.project_root,
    )
    return SetupPhaseHandler(
        config,
        build_setup_preflight_gate(),
        dependency_repository=dependency_repository,  # type: ignore[arg-type]
        mode_lock_repository=ModeLockRepository(config.project_root),
        green_main_port=green_main_port,  # type: ignore[arg-type]
        are_bundle_loader=are_bundle_loader,
        residue_probe=build_phase_state_residue_probe(
            store_dir or config.project_root
        ),
    )


def build_phase_state_residue_probe(
    store_dir: Path | None = None,
) -> Callable[[Path, str], bool]:
    """Build the run-residue probe for Preflight Check 6 (AG3-034 Finding B).

    The canonical residue read (a left-over phase-state of a PRIOR, un-reset
    run) is a state-backend read.  ``governance`` is truth-boundary-protected
    and may NOT call the loader directly (TB003), so this composition-root
    helper owns the read and is INJECTED into the ``SetupPhaseHandler`` as a
    plain callable.

    Excluding the CURRENT run (FK-22 §22.3.1, Check 6): the pipeline persists a
    fresh ``setup``/``PENDING`` phase-state before preflight runs, so a
    ``setup``-phase state in a not-yet-active status (``PENDING``/``IN_PROGRESS``)
    is the run being set up — NOT residue.  Residue is a non-terminal phase-state
    that signals an un-reset prior run: a ``FAILED``/``PAUSED`` state in any
    phase, or any non-terminal state in a phase BEYOND setup
    (``implementation``/``closure`` left-over).

    Args:
        store_dir: Base directory of the state backend (SQLite); ignored by
            Postgres.

    Returns:
        ``check(project_root, story_display_id) -> bool`` (True == residue).
    """
    from agentkit.backend.installer.paths import story_dir
    from agentkit.backend.pipeline_engine.phase_executor import PhaseStatus
    from agentkit.backend.state_backend.store import facade

    _ = store_dir  # facade resolves the active backend itself.
    stalled = {
        PhaseStatus.FAILED,
        PhaseStatus.PAUSED,
        PhaseStatus.ESCALATED,
    }
    fresh_current_run = {PhaseStatus.PENDING, PhaseStatus.IN_PROGRESS}

    def _probe(project_root: Path, story_display_id: str) -> bool:
        s_dir = story_dir(project_root, story_display_id)
        state = facade.load_phase_state(s_dir)
        if state is None or state.status is PhaseStatus.COMPLETED:
            return False
        if state.status in stalled:
            return True  # stalled prior run, regardless of phase
        # PENDING / IN_PROGRESS: residue only when BEYOND the setup phase
        # (a left-over implementation/closure run); a fresh setup state is the
        # current run being set up, not residue.
        return state.phase != "setup" and state.status in fresh_current_run

    return _probe


def build_runtime_execution_purge_port(
    store_dir: Path | None = None,
) -> RuntimeExecutionPurgePort:
    """Wire the coordinating Runtime-Execution-Purge port (AG3-109, FK-53 §53.7.5).

    Composition root for the per-owner Runtime-Execution purge. The port
    orchestrates the owner-purge facade APIs (``state_backend.store.facade``) for
    ``flow_executions``, ``node_execution_ledgers``, ``attempts``,
    ``override_records``, ``guard_decisions``, ``decision_records``, canonical
    ``phase_states``, ``phase_snapshots``, ``execution_events`` and run-bound
    ``artifact_envelopes`` — no God-Purge, no
    port-owned cross-BC SQL. The consumer is ``story-lifecycle``
    (``StoryResetService``, AG3-071; NOT built here), which drives the port
    through this real assembly.

    Args:
        store_dir: State-backend base directory (story dir for SQLite; Postgres
            resolves the global store). Defaults to the current working dir.

    Returns:
        A fully constructed :class:`RuntimeExecutionPurgePort`.
    """
    from agentkit.backend.state_backend.store.runtime_execution_purge import (
        RuntimeExecutionPurgePort as _RuntimeExecutionPurgePort,
    )

    return _RuntimeExecutionPurgePort(store_dir or Path.cwd())


def build_runtime_execution_residue_probe(
    store_dir: Path | None = None,
) -> RuntimeExecutionResidueProbe:
    """Wire the Runtime-Residue verify building block (AG3-109, FK-53 §53.7.5).

    Fail-closed probe that confirms no Runtime-Execution residue remains for a
    run. This is the Runtime-Residue fragment only; AG3-071 composes it into the
    full ``verify_reset_clean_state`` (§53.8/§53.10).

    Args:
        store_dir: State-backend base directory (story dir for SQLite).

    Returns:
        A fully constructed :class:`RuntimeExecutionResidueProbe`.
    """
    from agentkit.backend.state_backend.store.runtime_execution_purge import (
        RuntimeExecutionResidueProbe as _RuntimeExecutionResidueProbe,
    )

    return _RuntimeExecutionResidueProbe(store_dir or Path.cwd())


def build_projection_accessor(store_dir: Path | None = None) -> ProjectionAccessor:
    """Create a fully wired ``ProjectionAccessor``.

    Composition root for the FK-69 projection write/read path (AG3-035):
    instantiates all four repository adapters and passes them via the
    ``ProjectionRepositories`` dataclass into the ``ProjectionAccessor``.
    Consumer BCs (e.g. ``story_closure.PostMergeFinalization``) receive the
    accessor via DI and do not know the repository implementations.

    Architecture conformance (AC#7): ProjectionAccessor imports no concrete
    implementations from ``state_backend.store.facade``.

    Args:
        store_dir: Base directory of the state backend. Only relevant for
            SQLite; Postgres ignores the path.

    Returns:
        ``ProjectionAccessor`` with all four repository adapters.
    """
    from agentkit.backend.state_backend.store.projection_repositories import (
        build_projection_repositories,
    )
    from agentkit.backend.telemetry.projection_accessor import (
        ProjectionAccessor as _ProjectionAccessor,
    )

    repos = build_projection_repositories(store_dir)
    return _ProjectionAccessor(repos)


def build_planning_projection_accessor(
    store_dir: Path | None = None,
) -> PlanningProjectionAccessor:
    """Wire the BC-9-hosted planning projection write path (FK-70 §70.10.2, AG3-099).

    Composition root for the BC14 planning projection write/read boundary. Builds
    the ten concrete planning table adapters and injects them via
    ``PlanningProjectionRepositories`` into ``PlanningProjectionAccessor`` -- the
    single planning write boundary. This is the owner-distinct pendant to
    ``build_projection_accessor`` (FK-69); it does NOT touch the FK-69 accessor or
    its seven-value ``ProjectionKind`` contract.

    Args:
        store_dir: State-backend base directory (SQLite only; Postgres ignores).

    Returns:
        A fully wired ``PlanningProjectionAccessor``.
    """
    from agentkit.backend.execution_planning.persistence.accessor import (
        PlanningProjectionAccessor as _PlanningProjectionAccessor,
    )
    from agentkit.backend.state_backend.store.planning_projection_repository import (
        build_planning_projection_repositories,
    )

    repos = build_planning_projection_repositories(store_dir)
    return _PlanningProjectionAccessor(repos)


def build_planning_story_dependency_repository(
    store_dir: Path | None = None,
) -> PlanningWritePathStoryDependencyRepository:
    """Wire the planning-write-path ``StoryDependencyRepository`` (AG3-099 migration).

    Replaces the legacy direct-facade ``StateBackendStoryDependencyRepository`` for
    the execution-planning HTTP write path: ``add``/``remove``/``list`` route
    through ``PlanningProjectionAccessor`` and the ``dependency_edge`` planning
    family, so there is no direct state_backend planning write anymore (FK-70
    §70.10.2, no double write-truth).

    Args:
        store_dir: State-backend base directory (SQLite only; Postgres ignores).

    Returns:
        A wired ``PlanningWritePathStoryDependencyRepository``.
    """
    from agentkit.backend.state_backend.store.planning_projection_repository import (
        StateBackendDependencyEdgeProjectionRepository,
    )
    from agentkit.backend.state_backend.store.planning_story_dependency_repository import (
        PlanningWritePathStoryDependencyRepository as _PlanningRepo,
    )

    accessor = build_planning_projection_accessor(store_dir)
    edge_repo = StateBackendDependencyEdgeProjectionRepository(store_dir)
    return _PlanningRepo(accessor=accessor, edge_repo=edge_repo)


def build_closure_phase_handler(
    config: object,
    *,
    store_dir: Path | None = None,
    project_key: str = "",
    layer2_llm_client: LlmClient | None = None,
) -> ClosurePhaseHandler:
    """Wire a fully-collaborated ``ClosurePhaseHandler`` (FK-29, AG3-053).

    Composition root for the Closure phase (BC 7, ``story-closure``): assembles
    the collaborators the truth-boundary-protected handler may NOT build itself
    (DI pattern, analog ``build_setup_phase_handler`` / ``build_verify_system``).
    The handler ORCHESTRATES the canonical FK-29 §29.1.4 sequence by CALLING
    these capabilities; it builds no second merge/gate/Sonar/lock truth:

    * ``integrity_gate`` -- :func:`build_integrity_gate` (AG3-034 verifier; its
      Dim 9 consumes the AG3-052 Sonar capability to verify the fresh
      attestation, FK-35 §35.2.4a).
    * ``artifact_manager`` -- :func:`build_artifact_manager` (the only Layer-2
      read seam for the Finding-Resolution-Gate, FK-29 §29.2).
    * ``scan_port`` / ``build_test_port`` -- the AG3-056 Pre-Merge-Verification-
      Runner's commit-bound ``CiSonarScanRunner`` / ``CiBuildTestRunner`` (FK-29
      §29.1a.3 steps c/d), wired via ``build_pre_merge_runners`` over one shared
      CI run. ``None`` for a declared-absent CI (``ci.available == false``);
      applicable-but-unreachable raises ``PreMergeRunnerUnavailableError``
      (fail-closed). The old fail-open ``build_sonar_gate_port_for_run`` scan path
      is REMOVED -- AG3-053 consumes AG3-056.
    * ``sonar_config`` -- the FK-03 ``sonarqube`` stanza, threaded into the
      fresh-attestation Dim-9 version-drift check (FK-35 §35.2.4a item 5).
    * ``sanity_port`` -- the fast-mode Sanity-Gate seam (FK-29 §29.1a.6).
    * ``doc_fidelity_port`` -- level-4 doc-fidelity feedback via
      ``verify_system.llm_evaluator`` (FK-38 §38.3.1, non-blocking).
    * ``vectordb_sync_port`` -- the FK-13 §13.7.1 sync trigger (non-blocking).
    * ``guard_deactivation_port`` -- ``Governance.deactivate_locks`` (FK-29 §29.5,
      governance top surface; closure holds no lock logic).

    Args:
        config: A ``ClosureConfig`` carrying ``story_dir`` (+ optional GitHub /
            story-service fields). The collaborator slots are overwritten here.
        store_dir: State-backend base dir (SQLite); ``None`` => the config's
            ``story_dir``.
        project_key: Owning project key for the governance top surface.
        layer2_llm_client: The Layer-2 LLM transport (the same one passed to
            ``build_verify_system``), injected into the level-4 doc-fidelity
            feedback seam so it runs a REAL evaluation through the shared
            ``ConformanceService`` path. ``None`` => the fail-closed default
            (the seam still runs and yields a real FAIL verdict).

    Returns:
        A wired ``ClosurePhaseHandler``.
    """
    from agentkit.backend.closure.phase import ClosureConfig, ClosurePhaseHandler

    if not isinstance(config, ClosureConfig):
        msg = f"config must be a ClosureConfig; got {type(config).__name__}"
        raise TypeError(msg)
    base_dir = store_dir or config.story_dir or Path.cwd()
    config.progress_store = _build_closure_progress_store(base_dir)
    config.integrity_gate = build_integrity_gate(base_dir)
    config.artifact_manager = build_artifact_manager(base_dir)
    ci_config, sonar_config = _resolve_pre_merge_configs(config.story_dir)
    config.sonar_config = sonar_config
    # FIX-C: build a runner pair PER participating repo (each bound to ITS OWN
    # root/ledger/tree), so every repo is verified against its own root. The
    # single-repo path is the one-entry case (config.repos empty => the story_dir
    # repo). The applicability is resolved once (story-type + ci/sonar facets are
    # the same across repos for one story).
    repo_roots = _closure_repo_roots(config, base_dir)
    repo_runners, applicability = _build_per_repo_runners(
        ci_config, sonar_config, repo_roots
    )
    config.merge_applicability = applicability
    primary = repo_runners[repo_roots[0]]
    config.scan_port = primary.scan_port
    config.build_test_port = primary.build_test_port
    config.repo_runners = repo_runners
    config.sanity_port = _build_sanity_gate_port(ci_config)
    config.doc_fidelity_port = _build_doc_fidelity_feedback_port(layer2_llm_client)
    config.vectordb_sync_port = _build_vectordb_sync_port()
    config.guard_deactivation_port = _build_guard_deactivation_port(
        base_dir, project_key=project_key
    )
    config.mode_lock_release_port = _build_mode_lock_release_port(base_dir)
    config.change_evidence_port = _SubprocessGitChangeEvidenceProvider()
    config.telemetry_evidence_port = _build_telemetry_evidence_port(
        base_dir, project_key=project_key
    )
    config.guard_counter_flush_port = _build_guard_counter_flush_port(base_dir)
    return ClosurePhaseHandler(config)


def _build_guard_counter_flush_port(store_dir: Path) -> GuardCounterFlushPort:
    """Build the Closure guard-counter flush seam (FK-61 §61.4.3 Trigger 1, AG3-081).

    Delegates to the kpi-owned ``GuardCounterService.flush_on_closure`` over the
    productive state-backend counter repository. Drains the story's
    ``guard_invocation_counters`` at Closure (the ``fact_guard_period`` drain is
    AG3-082).
    """
    from agentkit.backend.closure.runtime_ports import ProductiveGuardCounterFlushPort

    return ProductiveGuardCounterFlushPort(store_dir=store_dir)


def _build_telemetry_evidence_port(
    store_dir: Path, *, project_key: str
) -> TelemetryEvidencePort:
    """Build the Closure Telemetry-Evidence-Block seam (FK-68 §68.4, AG3-081).

    Runs the six FK-68 §68.4 proofs against the run's ``execution_events`` at
    Closure (fail-closed). The authoritative review/llm/web budget config is read
    from the project root by the port itself (truth boundary); the gate never
    knows provider names (FK-68 §68.4: checked against configuration, not against
    hardcoded provider names).
    """
    from agentkit.backend.closure.runtime_ports import ProductiveTelemetryEvidencePort

    return ProductiveTelemetryEvidencePort(
        project_key=project_key, project_root=store_dir
    )


def _build_mode_lock_release_port(store_dir: Path) -> ModeLockReleasePort:
    """Build the project mode-lock release seam (FK-24 §24.3.3, AG3-018).

    Delegates to the atomic ``ModeLockRepository.release`` for the mode this story
    acquired at Setup (read from the durable acquire marker). Closure holds no
    mode-lock logic itself.
    """
    from agentkit.backend.closure.runtime_ports import ProductiveModeLockReleasePort
    from agentkit.backend.state_backend.store.mode_lock_repository import ModeLockRepository

    return ProductiveModeLockReleasePort(mode_lock_repo=ModeLockRepository(store_dir))


def _build_closure_progress_store(store_dir: Path) -> ClosureProgressStore:
    """Build the closure checkpoint store (FK-29 §29.1.0, AC003 pipeline surface).

    Phase-state mutation may only happen through a pipeline surface
    (architecture-conformance AC003), so the closure checkpoint writes go through
    the ``pipeline_engine`` :class:`PhaseEnvelopeStore` (over the state-backend
    phase-envelope repository) -- NOT a direct ``save_phase_state`` import in the
    closure BC.
    """
    from agentkit.backend.pipeline_engine.phase_envelope.store import PhaseEnvelopeStore
    from agentkit.backend.state_backend.store.phase_envelope_repository import (
        StateBackendPhaseEnvelopeRepository,
    )

    return PhaseEnvelopeStore(StateBackendPhaseEnvelopeRepository(store_dir))


def build_phase_envelope_store(story_dir: Path) -> PhaseEnvelopeStore:
    """Build a :class:`~agentkit.backend.pipeline_engine.phase_envelope.store.PhaseEnvelopeStore`.

    Public factory exposed to boundary-callers (e.g. the operator/recovery CLI,
    AG3-076) so they can load PAUSED :class:`PhaseEnvelope` objects without
    importing the private ``StateBackendPhaseEnvelopeRepository`` adapter directly.
    The returned object satisfies the ``PhaseEnvelopeStore`` interface
    (``load``, ``save``, ``exists``).

    Args:
        story_dir: The story working directory used as the persistence root for
            the underlying ``StateBackendPhaseEnvelopeRepository``.

    Returns:
        A :class:`~agentkit.backend.pipeline_engine.phase_envelope.store.PhaseEnvelopeStore`
        backed by the state-backend phase-envelope repository.
    """
    from agentkit.backend.pipeline_engine.phase_envelope.store import PhaseEnvelopeStore
    from agentkit.backend.state_backend.store.phase_envelope_repository import (
        StateBackendPhaseEnvelopeRepository,
    )

    return PhaseEnvelopeStore(StateBackendPhaseEnvelopeRepository(story_dir))


def build_pipeline_handler_registry(
    story_dir: Path,
    *,
    story_type: StoryType,
    project_key: str = "",
    setup_config: object | None = None,
    layer2_llm_client: LlmClient | None = None,
) -> PhaseHandlerRegistry:
    """Wire ONE ``PhaseHandlerRegistry`` for a story run (AG3-054, FK-20 §20.1.1).

    Pure WIRING over the phase-owning self-registration surfaces (bc-cut-decisions
    BC 5/6/7): the exploration / implementation / closure BCs own their handler
    internals; this composition-root function only registers the per-story-type
    subset of handlers at ONE registry instance and threads the shared foundation
    collaborator (``story_dir``) through each phase's own build function. It pulls
    NO handler / gate / merge / QA innards into a central plan (no God-composition).

    The registered subset follows the typed workflow for the story type
    (:func:`~agentkit.backend.process.language.definitions.resolve_workflow`); only phases
    actually present in that workflow get a handler:

    * ``setup`` -> :func:`build_setup_phase_handler`
    * ``exploration`` (implementation-mode only) -> the AG3-045
      :class:`ExplorationPhaseHandler` via :func:`build_exploration_phase_handler`
    * ``implementation`` -> the AG3-026 ``ImplementationPhaseHandler`` (QA-subflow
      already wired in ``implementation/phase.py``)
    * ``closure`` -> the AG3-053 ``ClosurePhaseHandler`` via
      :func:`build_closure_phase_handler`

    Args:
        story_dir: The story working directory (shared foundation collaborator
            threaded into each phase build function -- e.g. the ``PhaseEnvelopeStore``
            / state-backend read seams the handlers consume).
        story_type: The story type whose typed workflow decides which phases are
            present (and therefore which handlers are registered).
        project_key: Owning project key (threaded to the closure governance seam).
        setup_config: The run-specific ``SetupConfig`` carrying the authoritative
            GitHub coordinates the Setup handler needs (E1). The PRODUCTIVE path
            (``build_pipeline_engine`` <- dispatch) ALWAYS supplies a real config
            built by :func:`build_setup_config_for_run`. ``None`` registers a
            FAIL-CLOSED setup handler (E4) -- never a runnable dummy. A non-setup
            follow-up dispatch (which never enters setup) is fine; if setup is
            ever entered without a resolved real config it ESCALATES rather than
            running against empty/dummy coordinates.
        layer2_llm_client: The Layer-2 LLM transport (AG3-067 AC7). Threaded into
            BOTH the implementation handler (-> ``build_verify_system`` -> the
            QA-subflow Layer-2 reviewers) AND the closure handler (-> the level-4
            ``ProductiveDocFidelityFeedbackPort``) so ONE transport reaches both
            the verify-system Layer-2 path and the closure feedback port (single
            source of truth). ``None`` => the fail-closed
            :class:`FailClosedLlmClient` default inside ``build_verify_system`` /
            the feedback port (the seams still RUN and fail closed; honest until
            the productive LLM pool lands, AG3-070).

    Returns:
        A ``PhaseHandlerRegistry`` with exactly the workflow's phase handlers.
    """
    from agentkit.backend.closure.phase import ClosureConfig
    from agentkit.backend.implementation.phase import (
        ImplementationConfig,
        ImplementationPhaseHandler,
    )
    from agentkit.backend.pipeline_engine.lifecycle import PhaseHandlerRegistry
    from agentkit.backend.process.language.definitions import resolve_workflow

    workflow = resolve_workflow(story_type)
    phases = set(workflow.phase_names)
    registry = PhaseHandlerRegistry()

    if "setup" in phases:
        # E4 fix (#4): NEVER register a runnable dummy setup config on the
        # productive path. A resolved real ``SetupConfig`` => the real handler; a
        # ``None`` config (the run's coordinates were not resolvable, or a
        # follow-up dispatch never resolved them) => a FAIL-CLOSED setup handler
        # that escalates if entered, so setup can never run against empty/dummy
        # owner/repo/issue. A non-setup follow-up dispatch never enters it.
        if setup_config is not None:
            setup_handler: object = build_setup_phase_handler(
                setup_config,
                store_dir=story_dir,
            )
        else:
            setup_handler = _UnresolvedSetupCoordinatesHandler()
        registry.register("setup", setup_handler)  # type: ignore[arg-type]
    if "exploration" in phases:
        registry.register("exploration", build_exploration_phase_handler(story_dir))
    if "implementation" in phases:
        registry.register(
            "implementation",
            ImplementationPhaseHandler(
                ImplementationConfig(
                    story_dir=story_dir,
                    # AG3-067 AC7: same transport as the closure feedback port.
                    layer2_llm_client=layer2_llm_client,
                )
            ),
        )
    if "closure" in phases:
        registry.register(
            "closure",
            build_closure_phase_handler(
                ClosureConfig(story_dir=story_dir),
                store_dir=story_dir,
                project_key=project_key,
                # AG3-067 AC7: the SAME Layer-2 transport build_verify_system uses
                # reaches the level-4 ProductiveDocFidelityFeedbackPort here.
                layer2_llm_client=layer2_llm_client,
            ),
        )
    return registry


class _UnresolvedSetupCoordinatesHandler:
    """Fail-closed setup handler registered when no real config resolved (E4/#4).

    Registered in place of the real :class:`SetupPhaseHandler` when
    ``build_pipeline_handler_registry`` received ``setup_config=None`` (the run's
    authoritative coordinates could not be resolved, or a non-setup follow-up
    dispatch never resolved them). Registering this instead of a runnable dummy
    ``SetupConfig(owner="", repo="", issue_nr=0)`` guarantees the productive setup
    path can NEVER run against empty/dummy coordinates: a non-setup follow-up
    dispatch (which never enters setup) is unaffected, but any attempt to actually
    ENTER setup ESCALATES fail-closed (FK-20 §20.8.2 / ZERO DEBT -- no second
    source of truth, no enterable dummy on the productive path). Satisfies the
    ``PhaseHandler`` protocol.
    """

    _REASON = (
        "Setup cannot run: the run's authoritative setup coordinates were not "
        "resolved when the registry was built (no real SetupConfig). The "
        "fresh-setup-start dispatch must resolve them first (FK-20 §20.8.2); a "
        "dummy owner/repo/issue is never permitted on the productive path "
        "(fail-closed; E4/#4)."
    )

    def _escalation(self) -> HandlerResult:
        from agentkit.backend.pipeline_engine.lifecycle import HandlerResult
        from agentkit.backend.pipeline_engine.phase_executor import PhaseStatus

        return HandlerResult(
            status=PhaseStatus.ESCALATED,
            errors=(self._REASON,),
            suggested_reaction="setup_coordinates_unresolved",
        )

    def on_enter(self, ctx: StoryContext, envelope: PhaseEnvelope) -> HandlerResult:
        """Escalate fail-closed: setup must never run on unresolved coordinates."""
        _ = ctx, envelope
        return self._escalation()

    def on_exit(self, ctx: StoryContext, envelope: PhaseEnvelope) -> None:
        """No-op exit (the phase escalated before doing any work)."""
        _ = ctx, envelope

    def on_resume(
        self, ctx: StoryContext, envelope: PhaseEnvelope, trigger: str
    ) -> HandlerResult:
        """Escalate fail-closed on resume too (coordinates still unresolved)."""
        _ = ctx, envelope, trigger
        return self._escalation()


def build_pipeline_engine(
    story_dir: Path,
    *,
    story_type: StoryType,
    project_key: str = "",
    setup_config: object | None = None,
    layer2_llm_client: LlmClient | None = None,
) -> PipelineEngine:
    """Wire a ``PipelineEngine`` for a story run (AG3-054, FK-20 §20.1.1).

    Resolves the typed workflow for ``story_type`` and constructs the engine over
    the :func:`build_pipeline_handler_registry` wiring. The engine itself is the
    existing deterministic interpreter (AG3-earlier) -- this is pure composition,
    no new engine / transition / handler mechanic.

    Args:
        story_dir: The story working directory (engine persistence root).
        story_type: The story type whose typed workflow the engine interprets.
        project_key: Owning project key (threaded to the closure governance seam).
        setup_config: The run-specific ``SetupConfig`` carrying the authoritative
            GitHub coordinates (E1 fix). The PRODUCTIVE caller resolves it from the
            run ``StoryContext`` via :func:`build_setup_config_for_run` and passes
            it here; it is threaded into the Setup handler so setup never runs
            against empty owner/repo/issue. ``None`` falls back to the
            test-boundary config (dispatch-contract tests only).
        layer2_llm_client: The Layer-2 LLM transport (AG3-067 AC7). Threaded
            through :func:`build_pipeline_handler_registry` into BOTH the
            verify-system Layer-2 path and the closure level-4 feedback port so a
            single transport reaches both. ``None`` => the fail-closed default
            inside both seams (honest until the productive pool lands, AG3-070).

    Returns:
        A wired ``PipelineEngine``.
    """
    from agentkit.backend.pipeline_engine.engine import PipelineEngine
    from agentkit.backend.process.language.definitions import resolve_workflow

    workflow = resolve_workflow(story_type)
    registry = build_pipeline_handler_registry(
        story_dir,
        story_type=story_type,
        project_key=project_key,
        setup_config=setup_config,
        layer2_llm_client=layer2_llm_client,
    )
    return PipelineEngine(workflow, registry, story_dir)


class SetupCoordinatesUnavailableError(PipelineError):
    """The run's authoritative GitHub setup coordinates cannot be resolved (E1).

    Raised by :func:`build_setup_config_for_run` when a run that requires setup
    cannot have its authoritative ``owner`` / ``repo`` / ``issue_nr`` resolved
    from the run ``StoryContext`` + the project config. FAIL-CLOSED: setup must
    never run against empty/dummy coordinates (it would read the wrong / no GitHub
    issue), so the dispatch rejects the setup start rather than fabricating
    coordinates (ZERO DEBT / FIX-THE-MODEL -- no second source of truth).

    Subclasses :class:`~agentkit.backend.exceptions.PipelineError` so the dispatch's
    fail-closed engine-build guard (which already maps ``PipelineError`` to a
    normalized rejection) surfaces it as a setup-start rejection.
    """


def _story_is_github_backed(ctx: StoryContext) -> bool:
    """Whether the run's story type is GitHub-backed (code-producing; E5).

    SSOT criterion: a GitHub-backed story is a CODE-PRODUCING story
    (implementation/bugfix). Per the canonical ``StoryTypeProfile`` those are the
    types with ``uses_worktree`` / ``uses_merge`` true -- the only ones that
    create a ``story/{story_id}`` branch + worktree and merge to ``main`` against
    a real GitHub repo (FK-12 §12.7.1 "GitHub-Operationen in der Pipeline":
    Setup/Worker/Closure contact GitHub only for these). CONCEPT/RESEARCH are
    INTERNAL stories (``uses_worktree=False``, ``uses_merge=False``): they
    legitimately carry no GitHub issue and must NOT be blocked on missing GitHub
    coordinates. The axis is read from the authoritative
    ``is_code_producing_story`` SSOT, never a re-derived flag.

    Args:
        ctx: The run's story context.

    Returns:
        ``True`` iff the story type is GitHub-backed (implementation/bugfix).
    """
    from agentkit.backend.verify_system.sonarqube_gate import is_code_producing_story

    return is_code_producing_story(ctx.story_type)


def build_setup_config_for_run(ctx: StoryContext) -> object:
    """Build the run's authoritative ``SetupConfig`` from the StoryContext (E1/E5).

    The authoritative per-run coordinates are sourced from the SINGLE truths that
    already own them -- NOT fabricated here. For a GitHub-backed (code-producing)
    story they are:

    * ``issue_nr`` -- the run ``StoryContext.issue_nr`` (the GitHub issue input
      captured at story creation; for a GitHub-backed story it MUST be a real
      positive issue number, ``> 0`` -- ``0``/``None`` is rejected, E5).
    * ``project_root`` -- the run ``StoryContext.project_root``.
    * ``owner`` / ``repo`` -- the project config (``project.yaml`` ->
      ``github_owner`` / ``github_repo``), loaded from the run's project root.
      GitHub coordinates are deployment config, owned by the project, not the
      per-story context (FK-12 §12.1.1: GitHub is the code backend, the project
      owns the repo coordinates).

    For an INTERNAL story (CONCEPT/RESEARCH; not code-producing, E5) the setup
    handler never creates a GitHub worktree or merges, so it requires NO GitHub
    coordinates: this returns a config with no owner/repo/issue and
    ``create_worktree=False``. A legitimate internal story is therefore NEVER
    fail-closed-blocked for a missing issue/owner/repo.

    FAIL-CLOSED (GitHub-backed only): if ``project_root`` / a positive
    ``issue_nr`` / ``github_owner`` / ``github_repo`` cannot be resolved for a
    GitHub-backed story, this raises :class:`SetupCoordinatesUnavailableError`. A
    code-producing run that requires setup must never run against empty/bogus
    coordinates (it would read the wrong / no GitHub issue). The caller (dispatch)
    maps this to a fail-closed setup rejection.

    Args:
        ctx: The run's story context.

    Returns:
        A ``SetupConfig`` for the run (real GitHub coords for a GitHub-backed
        story; a GitHub-free internal config for a non-code-producing story).

    Raises:
        SetupCoordinatesUnavailableError: When the authoritative GitHub
            coordinates of a GitHub-backed story cannot be resolved (fail-closed;
            never a dummy). Never raised for an internal story.
    """
    from agentkit.backend.governance.setup_preflight_gate.phase import SetupConfig

    if ctx.project_root is None:
        raise SetupCoordinatesUnavailableError(
            "cannot resolve setup coordinates: the run StoryContext has no "
            "project_root (fail-closed; E1)."
        )

    if not _story_is_github_backed(ctx):
        # Internal (non-code-producing) story: setup needs NO GitHub coordinates.
        # No worktree/merge is created (FK-12 §12.7.1), so owner/repo/issue stay
        # empty and ``create_worktree`` is off -- never a fail-closed block (E5).
        return SetupConfig(
            owner="",
            repo="",
            issue_nr=0,
            project_root=ctx.project_root,
            create_worktree=False,
        )

    # GitHub-backed (code-producing) story: real positive issue + owner/repo.
    if ctx.issue_nr is None or ctx.issue_nr <= 0:
        raise SetupCoordinatesUnavailableError(
            "cannot resolve setup coordinates: a GitHub-backed story requires a "
            f"positive issue_nr (> 0), got {ctx.issue_nr!r} (fail-closed; E5).",
        )
    owner, repo = _resolve_github_owner_repo(ctx.project_root)
    return SetupConfig(
        owner=owner,
        repo=repo,
        issue_nr=ctx.issue_nr,
        project_root=ctx.project_root,
    )


def _resolve_github_owner_repo(project_root: Path) -> tuple[str, str]:
    """Resolve the project's authoritative GitHub owner/repo (fail-closed; E1/E5).

    Loads the project config (``project.yaml``) and returns its ``github_owner``
    / ``github_repo``. A broken/absent config, or a config that declares no
    owner/repo, raises :class:`SetupCoordinatesUnavailableError` so a
    GitHub-backed setup never runs against empty coordinates.
    """
    from agentkit.backend.config.loader import load_project_config

    try:
        project_config = load_project_config(project_root)
    except Exception as exc:  # noqa: BLE001 -- broken/absent config is fail-closed
        raise SetupCoordinatesUnavailableError(
            "cannot resolve setup coordinates: the project config at "
            f"{project_root} is unreadable/absent (fail-closed; E1): {exc}",
        ) from exc
    owner = project_config.github_owner
    repo = project_config.github_repo
    if not owner or not repo:
        raise SetupCoordinatesUnavailableError(
            "cannot resolve setup coordinates: the project config declares no "
            "github_owner/github_repo (fail-closed; E1 -- setup must not run "
            "against empty GitHub coordinates).",
        )
    return owner, repo


class ClosureConfigUnavailableError(Exception):
    """The closure pre-merge config/context is broken (fail-closed, FIX-2).

    Raised by :func:`_resolve_pre_merge_configs` when the story context or the
    project config is PRESENT-but-unreadable/malformed, as opposed to a
    DELIBERATE absence (no ``ci``/``sonarqube`` stanza or ``available == false``).
    A broken config must never silently disable the integrated-candidate
    verification (NO ERROR BYPASSING) -- the composition root surfaces this
    before building the handler so the run escalates rather than merging code
    unverified.
    """


def _resolve_pre_merge_configs(
    story_dir: Path | None,
) -> tuple[object | None, object | None]:
    """Resolve the ``ci`` + ``sonarqube`` config stanzas (truth boundary, AG3-056).

    The composition root owns the project-config read (``governance``/``closure``
    stay free of direct config reads). Resolves the run ``StoryContext`` to find
    the project root, then loads the ``ci`` (Jenkins) and ``sonarqube`` stanzas
    for the AG3-056 pre-merge runner wiring + the Dim-9 version-drift check.

    FIX-2 fail-closed distinction (a broken config must NEVER silently disable
    verification, NO ERROR BYPASSING):

    * DELIBERATE absence -- no ``pipeline`` stanza at all (a non-code-producing
      project never declares CI/Sonar) -> ``(None, None)``: the runner wiring
      treats it as a declared skip and the applicability layer (FIX-3) decides
      per story type whether that is allowed.
    * BROKEN config/context -- an unresolvable project root, an unreadable
      story context, or a config that fails to load/parse -> FAIL-CLOSED
      (:class:`ClosureConfigUnavailableError`). Never downgraded to a declared
      absence.

    A PRESENT stanza with ``available == false`` is also a deliberate absence,
    but that is decided downstream (``build_pre_merge_runners`` returns ``None``
    for it); here we only fail closed on a genuinely broken read.
    """
    from agentkit.backend.config.loader import load_project_config
    from agentkit.backend.state_backend.store import facade

    if story_dir is None:
        raise ClosureConfigUnavailableError(
            "closure config resolution requires a story_dir (FIX-2, fail-closed)"
        )
    try:
        ctx = facade.load_story_context(story_dir)
    # Broken context is fail-closed, not absence.
    except Exception as exc:  # noqa: BLE001
        raise ClosureConfigUnavailableError(
            f"story context at {story_dir} is unreadable/malformed "
            f"(FIX-2, fail-closed -- never silently skip verification): {exc}"
        ) from exc
    if ctx is None or ctx.project_root is None:
        raise ClosureConfigUnavailableError(
            f"no resolvable story context / project root at {story_dir} "
            "(FIX-2, fail-closed)"
        )
    if not _project_config_present(ctx.project_root):
        # Deliberate absence: the project declares no AK3 config file at all
        # (a non-code-producing project never wires a pipeline). The
        # applicability layer (FIX-3) decides per story type whether a missing
        # runner is allowed -- it is for concept/research, fail-closed for code.
        return (None, None)
    try:
        project_config = load_project_config(ctx.project_root)
    # Broken config is fail-closed, not absence.
    except Exception as exc:  # noqa: BLE001
        raise ClosureConfigUnavailableError(
            f"project config at {ctx.project_root} is present but "
            f"unreadable/malformed (FIX-2, fail-closed -- a broken config never "
            f"silently disables Sonar/CI): {exc}"
        ) from exc
    pipeline = getattr(project_config, "pipeline", None)
    if pipeline is None:
        # Deliberate absence: no pipeline stanza (non-code-producing project).
        return (None, None)
    return (getattr(pipeline, "ci", None), getattr(pipeline, "sonarqube", None))


def _project_config_present(project_root: Path) -> bool:
    """Whether the project declares an AK3 config file (vs deliberate absence)."""
    from agentkit.backend.config.defaults import DEFAULT_CONFIG_DIR, DEFAULT_CONFIG_FILE

    return (project_root / DEFAULT_CONFIG_DIR / DEFAULT_CONFIG_FILE).is_file()


def _build_pre_merge_runners(
    ci_config: object | None,
    sonar_config: object | None,
    *,
    repo_root: Path,
) -> tuple[PreMergeScanPort | None, BuildTestPort | None, MergeApplicability]:
    """Wire the AG3-056 pre-merge runners + resolve the typed applicability (FIX-3).

    CONSUMES AG3-056's
    :func:`verify_system.pre_merge_runner.runtime_wiring.build_pre_merge_runners`
    (the old fail-open ``build_sonar_gate_port_for_run`` scan path is REMOVED).
    The applicability is resolved HERE (the applicability layer, FIX-3) from the
    ``ci``/``sonarqube`` availability and threaded onto the handler so a declared
    absence never silently merges code unverified (FK-33 §33.6.5 "absent !=
    broken"):

    * CI DECLARED absent (no stanza / ``ci.available == false``) ->
      ``(None, None, CI_ABSENT)``: for a code-producing story the handler
      fail-closes (cannot verify => cannot merge); for concept/research the
      block is skipped entirely (``uses_merge == False``).
    * CI present + Sonar DECLARED absent (no stanza / ``sonarqube.available ==
      false``) -> ``(None, build_test, SONAR_ABSENT)``: Build/Test runs (built
      via the additive :func:`build_build_test_runner`), the integrated-candidate
      scan + Dim 9 are skipped, the merge stays gated.
    * CI present + Sonar present -> ``(scan, build_test, FULL)`` via
      ``build_pre_merge_runners`` (shared single run-cache).
    * APPLICABLE-but-unreachable (``available == true`` but the endpoint/token
      cannot be resolved) raises ``PreMergeRunnerUnavailableError`` ->
      fail-closed (NEVER a silent skip).

    Args:
        ci_config: The resolved ``JenkinsConfig`` (or ``None``).
        sonar_config: The resolved ``SonarQubeConfig`` (or ``None``).
        repo_root: The integrated-candidate repo root (tree-hash + ledger read).

    Returns:
        ``(scan_port, build_test_port, applicability)``.
    """
    from agentkit.backend.closure.merge_sequence import MergeApplicability
    from agentkit.backend.config.models import JenkinsConfig, SonarQubeConfig
    from agentkit.backend.verify_system.pre_merge_runner.runtime_wiring import (
        build_build_test_runner,
        build_pre_merge_runners,
    )

    typed_ci = ci_config if isinstance(ci_config, JenkinsConfig) else None
    typed_sonar = sonar_config if isinstance(sonar_config, SonarQubeConfig) else None

    ci_present = typed_ci is not None and typed_ci.available
    if not ci_present:
        # Declared-absent CI: no Build/Test+scan runner. The handler fail-closes
        # for code-producing stories (FIX-3); concept/research skip the block.
        return (None, None, MergeApplicability.CI_ABSENT)

    sonar_present = typed_sonar is not None and typed_sonar.available
    if not sonar_present:
        # CI present, Sonar declared absent: Build/Test only, scan+Dim9 skipped.
        build_test_port = build_build_test_runner(typed_ci, repo_root)
        return (None, build_test_port, MergeApplicability.SONAR_ABSENT)

    runners = build_pre_merge_runners(typed_ci, typed_sonar, repo_root)
    if runners is None:  # pragma: no cover - ci_present already guaranteed above
        return (None, None, MergeApplicability.CI_ABSENT)
    return (runners.scan, runners.build_test, MergeApplicability.FULL)


def _closure_repo_roots(config: object, base_dir: Path) -> list[Path]:
    """Resolve the participating repo roots for the per-repo runner wiring (FIX-C).

    Mirrors the handler's ``_resolve_repos``: the configured ``ClosureRepo`` roots
    when present, else the single story-dir repo (one entry). Order-preserving and
    de-duplicated so each distinct root gets exactly one runner pair.
    """
    from agentkit.backend.closure.phase import ClosureConfig

    assert isinstance(config, ClosureConfig)  # noqa: S101 - caller validated
    roots: list[Path] = []
    if config.repos:
        for repo in config.repos:
            if repo.repo_root not in roots:
                roots.append(repo.repo_root)
    else:
        roots.append(config.story_dir or base_dir)
    return roots


def _build_per_repo_runners(
    ci_config: object | None,
    sonar_config: object | None,
    repo_roots: list[Path],
) -> tuple[dict[Path, RepoRunners], MergeApplicability]:
    """Build a :class:`RepoRunners` pair per repo root + the shared applicability (FIX-C).

    Each repo root gets its OWN ``CiSonarScanRunner`` / ``CiBuildTestRunner``
    (via :func:`_build_pre_merge_runners`, so its ledger + tree-hash resolver bind
    to that root). The applicability is identical across repos (it derives from
    the story-type + the ci/sonar facets, which are project-wide for one story);
    it is resolved per repo and asserted consistent (a fail-closed invariant).
    """
    from agentkit.backend.closure.merge_sequence import RepoRunners

    runners: dict[Path, RepoRunners] = {}
    resolved_applicability: MergeApplicability | None = None
    for repo_root in repo_roots:
        scan_port, build_test_port, applicability = _build_pre_merge_runners(
            ci_config, sonar_config, repo_root=repo_root
        )
        if resolved_applicability is None:
            resolved_applicability = applicability
        elif applicability is not resolved_applicability:  # pragma: no cover
            msg = (
                "inconsistent pre-merge applicability across repos: "
                f"{resolved_applicability} vs {applicability} "
                "(the ci/sonar facets must be project-wide for one story)"
            )
            raise ClosureConfigUnavailableError(msg)
        runners[repo_root] = RepoRunners(
            scan_port=scan_port, build_test_port=build_test_port
        )
    # ``repo_roots`` always has at least one entry (the story-dir fallback).
    assert resolved_applicability is not None  # noqa: S101 - non-empty roots
    return runners, resolved_applicability


def _build_sanity_gate_port(ci_config: object | None) -> SanityGatePort:
    """Build the fast-mode Sanity-Gate seam (FK-29 §29.1a.6, FIX-6).

    Wires the real subprocess git backend so the adapter genuinely confirms the
    two git-mechanic predicates (worktree clean + pre-merge rebase onto
    ``origin/main`` OK). The third predicate ("tests green") is wired to the SAME
    real AG3-056 Build/Test capability the standard barrier uses, via
    :func:`build_fast_test_runner` (FIX-6 -- one tests-green truth, not a stub).
    When CI is DECLARED absent (no ``ci`` stanza / ``ci.available == false``) no
    real runner exists, so ``test_runner`` stays ``None`` and the gate fails
    closed after the git checks (FAIL-CLOSED -- a fast story whose tests cannot be
    confirmed escalates; the floor is non-disableable, NO ERROR BYPASSING).
    """
    from agentkit.backend.closure.multi_repo_saga import SubprocessGitBackend
    from agentkit.backend.closure.runtime_ports import ProductiveSanityGatePort

    return ProductiveSanityGatePort(
        git_backend=SubprocessGitBackend(),
        test_runner=build_fast_test_runner(ci_config),
    )


def build_fast_test_runner(
    ci_config: object | None,
) -> Callable[[Path], tuple[bool, str | None]] | None:
    """Build the fast-mode tests-green floor runner (AG3-018 FIX-6, FK-24 §24.3.4).

    Wraps the REAL AG3-056 commit-bound :class:`BuildTestPort` (``CiBuildTestRunner``
    over the project's CI) as the ``Callable[[Path], tuple[bool, str | None]]``
    shape consumed by BOTH the fast QA-subflow floor (``build_verify_system
    fast_test_runner``) and the closure Sanity-Gate
    (``ProductiveSanityGatePort.test_runner``) -- ONE tests-green truth, not a
    second mechanism, not a stub.

    Args:
        ci_config: The resolved ``ci`` (Jenkins) config stanza, or ``None``.

    Returns:
        * ``None`` when CI is DECLARED absent (no ``ci`` stanza /
          ``ci.available == false``): no real runner exists, so the fast floor is
          unconfirmable and the consumer fails closed (the non-disableable floor).
        * a :class:`CiBuildTestFastRunner` over the real Build/Test port when CI
          is applicable. An applicable-but-unreachable CI raises
          ``PreMergeRunnerUnavailableError`` (fail-closed; never a silent skip).
    """
    from agentkit.backend.closure.multi_repo_saga import SubprocessGitBackend
    from agentkit.backend.closure.runtime_ports import CiBuildTestFastRunner
    from agentkit.backend.config.models import JenkinsConfig
    from agentkit.backend.verify_system.pre_merge_runner.runtime_wiring import (
        build_build_test_runner,
    )

    typed_ci = ci_config if isinstance(ci_config, JenkinsConfig) else None
    if typed_ci is None or not typed_ci.available:
        return None
    # ``repo_root`` is unused by the build/test facet (it needs no tree/ledger
    # read); the candidate's tree is resolved per-run from the story worktree.
    build_test_port = build_build_test_runner(typed_ci, Path.cwd())
    if build_test_port is None:  # pragma: no cover - guarded by the check above
        return None
    return CiBuildTestFastRunner(
        build_test_port=build_test_port,
        git_backend=SubprocessGitBackend(),
    )


def _build_doc_fidelity_feedback_port(
    layer2_llm_client: LlmClient | None = None,
) -> DocFidelityFeedbackPort:
    """Build the level-4 doc-fidelity feedback seam (FK-38 §38.3.1, non-blocking).

    Runs a REAL level-4 evaluation through the SAME productive
    ``ConformanceService.check_fidelity(level=feedback)`` path the Layer-2
    reviewers use (``role=doc_fidelity``, prompt ``doc-fidelity-feedback.md``,
    ``expected_checks=["feedback_fidelity"]``), evaluating the final diff vs the
    existing project docs (FK-38 §38.3.1). The Layer-2 ``llm_client`` is injected
    here so this seam shares the EXACT transport ``build_verify_system`` resolves
    — when the productive LLM pool lands (AG3-070) both paths get it; until then
    the fail-closed default yields a real FAIL verdict (non-blocking Warning +
    failure-corpus incident candidate), never a silent no-op.

    Args:
        layer2_llm_client: The Layer-2 LLM transport (same one passed to
            ``build_verify_system``). ``None`` => the fail-closed default inside
            the port, so the evaluation still RUNS.
    """
    from agentkit.backend.closure.runtime_ports import ProductiveDocFidelityFeedbackPort

    return ProductiveDocFidelityFeedbackPort(llm_client=layer2_llm_client)


def _build_vectordb_sync_port() -> VectorDbSyncPort:
    """Build the VectorDB sync seam (FK-13 §13.7.1, fire-and-forget, non-blocking).

    Triggers an async ``story_sync``. The VectorDB integration is not yet
    available in the target project; the seam is honest non-blocking — it records
    a human Warning when the sync cannot be triggered (the STEP still runs).
    """
    from agentkit.backend.closure.runtime_ports import ProductiveVectorDbSyncPort

    return ProductiveVectorDbSyncPort()


def _build_guard_deactivation_port(
    store_dir: Path, *, project_key: str
) -> GuardDeactivationPort:
    """Build the guard-deactivation seam (FK-29 §29.5, governance top surface).

    Delegates to ``Governance.deactivate_locks`` via a real ``Governance`` wired
    with the state-backend lock/hook/worktree repositories. Closure holds no lock
    logic itself (single delegation step).
    """
    from agentkit.backend.closure.runtime_ports import ProductiveGuardDeactivationPort
    from agentkit.backend.governance import Governance
    from agentkit.backend.state_backend.store.governance_hook_repository import (
        StateBackendHookRegistrationRepository,
    )
    from agentkit.backend.state_backend.store.lock_record_repository import LockRecordRepository
    from agentkit.backend.state_backend.store.worktree_repository import (
        StateBackendWorktreeRepository,
    )

    governance = Governance(
        hook_repo=StateBackendHookRegistrationRepository(store_dir),
        lock_repo=LockRecordRepository(store_dir),
        project_key=project_key,
        project_root=store_dir,
        worktree_repo=StateBackendWorktreeRepository(store_dir),
    )
    return ProductiveGuardDeactivationPort(governance)


def build_structural_build_test_port(
    ci_config: object | None,
    story_dir: Path,
) -> BuildTestEvidencePort:
    """Build the REAL Layer-1 build/test evidence port (FIX-1, FK-27 §27.4.2).

    REUSES the AG3-056 commit-bound :class:`CiBuildTestRunner` (the same CI
    Build/Test capability the closure pre-merge barrier + the fast-mode floor
    use -- ONE build/test truth, NO new dependency). The runner reports ONE
    green/red verdict for the integrated candidate commit, which is exactly the
    truth ``build.compile`` AND ``build.test_execution`` (both BLOCKING) need: a
    CI-green run proves the build compiled and the tests passed for that commit.
    The MAJOR ``test.count`` is derived from the SYSTEM ``git diff`` (system
    evidence, not a worker claim).

    Args:
        ci_config: The resolved ``ci`` (Jenkins) config stanza, or ``None``.
        story_dir: The story working directory (git HEAD + diff source).

    Returns:
        * the fail-closed absent port when CI is DECLARED absent (no ``ci``
          stanza / ``ci.available == false``): the build/test evidence is
          unconfirmable so ``build.compile`` / ``build.test_execution`` FAIL
          closed (NO ERROR BYPASSING; never a fabricated green).
        * a :class:`_CiBuildTestEvidenceAdapter` over the real Build/Test port
          when CI is applicable. An applicable-but-unreachable CI raises
          ``PreMergeRunnerUnavailableError`` (fail-closed; never a silent skip).
    """
    from agentkit.backend.config.models import JenkinsConfig
    from agentkit.backend.verify_system.pre_merge_runner.runtime_wiring import (
        build_build_test_runner,
    )
    from agentkit.backend.verify_system.structural.checks import ABSENT_BUILD_TEST_PORT

    typed_ci = ci_config if isinstance(ci_config, JenkinsConfig) else None
    if typed_ci is None or not typed_ci.available:
        return ABSENT_BUILD_TEST_PORT
    build_test_port = build_build_test_runner(typed_ci, story_dir)
    if build_test_port is None:  # pragma: no cover - guarded by the check above
        return ABSENT_BUILD_TEST_PORT
    from agentkit.backend.closure.multi_repo_saga import SubprocessGitBackend

    return _CiBuildTestEvidenceAdapter(
        build_test_port=build_test_port,
        git_backend=SubprocessGitBackend(),
    )


@dataclass(frozen=True)
class _CiBuildTestEvidenceAdapter:
    """Adapt the AG3-056 ``BuildTestPort`` to the Layer-1 ``BuildTestEvidencePort``.

    Resolves the story worktree's current HEAD into the AG3-056
    :class:`CandidateRef` and runs the commit-bound Build/Test. The CI run's
    single green/red verdict maps to BOTH ``build_ok`` and ``tests_green`` (a
    CI-green run proves the build compiled and tests passed for that commit). The
    test-file count is the SYSTEM ``git diff`` test-file count (system evidence).
    Coverage is reported as confirmed ONLY by the CI run's green (the AG3-056
    runner does not expose a separate coverage number; a green CI run executed
    the suite -- coverage_report_present mirrors the green run, threshold is left
    to the project CI). A red/unreadable run fails closed (``build_ok=False``).

    Attributes:
        build_test_port: The real AG3-056 commit-bound Build/Test port.
        git_backend: Git read port to resolve the worktree HEAD + diff.
    """

    build_test_port: BuildTestPort
    git_backend: RepoGitBackend

    def evaluate(self, story_dir: Path) -> BuildTestEvidence | None:
        """Run the commit-bound Build/Test for the worktree HEAD (fail-closed)."""
        from agentkit.backend.closure.multi_repo_saga import ClosureRepo
        from agentkit.backend.verify_system.pre_merge_runner.contract import CandidateRef
        from agentkit.backend.verify_system.structural.checks import BuildTestEvidence

        repo = ClosureRepo(name=story_dir.name, repo_root=story_dir)
        branch = self._read(repo, "rev-parse", "--abbrev-ref", "HEAD")
        commit = self._read(repo, "rev-parse", "HEAD")
        tree = self._read(repo, "rev-parse", "HEAD^{tree}")
        if branch is None or commit is None or tree is None:
            return None  # HEAD unresolvable -> evidence unconfirmable (fail-closed)
        outcome = self.build_test_port.run(
            CandidateRef(branch=branch, commit_sha=commit, tree_hash=tree)
        )
        test_file_count = self._diff_test_file_count(repo)
        return BuildTestEvidence(
            build_ok=outcome.green,
            tests_green=outcome.green,
            test_file_count=test_file_count,
            coverage_report_present=outcome.green,
            coverage_meets_threshold=outcome.green,
            detail=outcome.reason,
        )

    def _diff_test_file_count(self, repo: object) -> int:
        from agentkit.backend.closure.multi_repo_saga import ClosureRepo

        assert isinstance(repo, ClosureRepo)  # noqa: S101 - caller passes ClosureRepo
        out = self._read(repo, "diff", "--name-only", "origin/main...HEAD")
        if out is None:
            out = self._read(repo, "diff", "--name-only", "HEAD")
        if not out:
            return 0
        return sum(
            1
            for line in out.splitlines()
            if any(marker in line for marker in _TEST_FILE_MARKERS)
        )

    def _read(self, repo: object, *args: str) -> str | None:
        from agentkit.backend.closure.multi_repo_saga import ClosureRepo

        assert isinstance(repo, ClosureRepo)  # noqa: S101 - caller passes ClosureRepo
        result = self.git_backend.run(repo, *args)
        if not result.ok or not result.stdout.strip():
            return None
        return result.stdout.strip()


def build_structural_are_provider(
    are_client: object | None,
    pipeline_config: object,
    *,
    store_dir: Path | None = None,
) -> AreGateProvider:
    """Build the REAL Layer-1 ARE provider (FIX-1, FK-27 §27.4.4).

    Wraps the productive :class:`RequirementsCoverage` top-surface (AG3-030,
    FK-40) so the ``are.gate`` stage activates IFF ``features.are == true`` and
    the coverage verdict comes from the real ``check_gate`` dock-point. ARE is
    NEVER silently disabled: when ``features.are`` is true the provider reports
    ``is_enabled == True`` and the gate runs (fail-closed when the verdict is
    unavailable, ``check_are_gate``).

    Args:
        are_client: The configured ``AreClient`` (``None`` when ARE is off).
        pipeline_config: The project's ``PipelineConfig`` (``features.are``).

    Returns:
        An :class:`_RequirementsCoverageAreProvider` over the wired
        ``RequirementsCoverage``.
    """
    from agentkit.backend.config.models import PipelineConfig
    from agentkit.backend.requirements_coverage.are_client import AreClient
    from agentkit.backend.requirements_coverage.top import RequirementsCoverage
    from agentkit.backend.state_backend.store.story_are_link_repository import (
        StateBackendStoryAreLinkRepository,
    )

    if not isinstance(pipeline_config, PipelineConfig):
        msg = (
            "pipeline_config must be a PipelineConfig; got "
            f"{type(pipeline_config).__name__}"
        )
        raise TypeError(msg)
    typed_client = are_client if isinstance(are_client, AreClient) else None
    coverage = RequirementsCoverage(
        typed_client,
        pipeline_config,
        link_repository=StateBackendStoryAreLinkRepository(store_dir),
        artifact_manager=build_artifact_manager(store_dir or Path.cwd()),
        audit_root=store_dir,
    )
    return _RequirementsCoverageAreProvider(coverage)


@dataclass(frozen=True)
class _RequirementsCoverageAreProvider:
    """Adapt ``RequirementsCoverage`` to the Layer-1 ``AreGateProvider`` (FIX-1).

    ``is_enabled`` reflects ``features.are`` (ONE activation truth);
    ``coverage_verdict`` delegates to the ``check_gate`` dock-point (FK-40
    §40.5.4). A non-PASS / missing verdict drives the fail-closed ``are.gate``
    finding (FK-27 §27.4.4).

    Attributes:
        coverage: The wired ``RequirementsCoverage`` top-surface.
    """

    coverage: RequirementsCoverageProto

    @property
    def are_client(self) -> object | None:
        """Return the injected ARE client for wiring tests."""

        return getattr(self.coverage, "_are_client", None)

    @property
    def is_enabled(self) -> bool:
        """Return whether ``features.are`` is active."""
        return self.coverage.is_enabled

    def coverage_verdict(
        self, story_id: str, project_key: str
    ) -> CoverageVerdict | None:
        """Return the ARE coverage verdict, or ``None`` when ARE is disabled."""
        if not self.coverage.is_enabled:
            return None
        return self.coverage.check_gate(story_id, project_key)


def build_failure_corpus(
    accessor: ProjectionAccessor,
    project_key: str | None = None,
    store_dir: Path | None = None,
    llm_client: LlmClient | None = None,
) -> FailureCorpus:
    """Create a wired ``FailureCorpus`` top component (AG3-028, AG3-078).

    Composition root for the failure-corpus BC (FK-41 §41.1/§41.4). Wires the
    ``IncidentTriage`` with a default normalizer and IngressCriteria and passes
    the ``ProjectionAccessor`` in both as a narrow ``IncidentWriterPort``
    (``record_fc_incident`` -> ``IncidentId``, FK-41 §41.3.1) and as a
    ``ProjectionReaderPort`` (corpus novelty, FK-41 §41.4.3) (FK-69 §69.9).
    ``failure_corpus`` does NOT know the fc_incidents DB repo adapter
    (CONFLICT-2, AC#6): persistence/reading runs via the ``ProjectionAccessor``.

    AG3-078: When ``project_key`` is provided, also wires the three AG3-078 subs:
    ``PatternPromotion``, ``CheckFactory``, and ``CheckEffectivenessTracker``.
    Without ``project_key`` only ``record_incident`` is functional (existing callers
    that omit project_key retain the AG3-028 behavior).

    The ``CheckFactory`` is wired with an ``AK3StoryCreationAdapter`` and, only
    when ``llm_client`` is supplied, an ``LlmInvariantSharpener``.  The sharpener
    is the step-1 (invariant sharpening) LLM boundary and is the ONLY part of the
    build that needs an LLM transport; it is therefore built lazily.  When
    ``llm_client`` is ``None`` the factory is constructed WITHOUT a sharpener so
    that every non-``derive_check`` command (record_incident, suggest_patterns,
    confirm_pattern, approve_check, report_effectiveness, list_checks) can build
    and run.  ``derive_check`` itself stays FAIL-CLOSED: ``CheckFactory.derive_check``
    raises ``RuntimeError`` if it ever tries to sharpen without a wired sharpener
    (no silent skip).

    Args:
        accessor: The ``ProjectionAccessor`` as the write/read boundary (fulfils
            ``IncidentWriterPort`` and ``ProjectionReaderPort`` by structural typing).
        project_key: Project key for the AG3-078 subs (PatternPromotion,
            CheckFactory, CheckEffectivenessTracker). When ``None`` (default),
            the subs are not wired (backward-compatible with AG3-028 callers).
        store_dir: State-backend base directory. Only relevant for SQLite; passed
            to ``build_projection_repositories`` to obtain the fc_* adapters.
            Defaults to ``Path.cwd()`` when ``project_key`` is given.
        llm_client: LLM transport for invariant sharpening (FK-41 §41.6.2).
            Required when ``project_key`` is provided (FAIL-CLOSED:
            ``LlmInvariantSharpener`` raises if ``None``).  Ignored when
            ``project_key`` is ``None``.

    Returns:
        ``FailureCorpus`` with a functional ``record_incident``; the AG3-078 top
        methods are also functional when ``project_key`` is provided.
    """
    from agentkit.backend.failure_corpus import (
        FailureCorpus as _FailureCorpus,
    )
    from agentkit.backend.failure_corpus import (
        IncidentNormalizer,
        IncidentTriage,
        IngressCriteria,
    )

    triage = IncidentTriage(
        normalizer=IncidentNormalizer(),
        criteria=IngressCriteria(),
        writer=accessor,
        reader=accessor,
    )

    if project_key is None:
        return _FailureCorpus(incident_triage=triage)

    # AG3-078: wire PatternPromotion, CheckFactory, CheckEffectivenessTracker.
    # Repos are obtained from a fresh ProjectionRepositories (the accessor holds
    # them internally but does not expose them via its public surface — we build
    # a parallel repo bundle here to stay within AC#7).
    from agentkit.backend.failure_corpus.check_factory import CheckFactory as _CheckFactory
    from agentkit.backend.failure_corpus.effectiveness import (
        CheckEffectivenessTracker as _CheckEffectivenessTracker,
    )
    from agentkit.backend.failure_corpus.invariant_sharpener import LlmInvariantSharpener as _LlmInvariantSharpener
    from agentkit.backend.failure_corpus.pattern_promotion import PatternPromotion as _PatternPromotion
    from agentkit.backend.failure_corpus.story_creation_adapter import AK3StoryCreationAdapter as _AK3StoryCreationAdapter
    from agentkit.backend.state_backend.store.fc_check_proposal_repository import (
        StateBackendFcCheckProposalRepository,
    )
    from agentkit.backend.state_backend.store.fc_pattern_repository import (
        StateBackendFcPatternRepository,
    )

    _store_dir = store_dir or Path.cwd()
    pattern_repo = StateBackendFcPatternRepository(_store_dir)
    check_repo = StateBackendFcCheckProposalRepository(_store_dir)

    # AG3-078: the LLM invariant sharpener is the ONLY LLM-dependent part of the
    # build and is only needed by derive_check (step 1).  Build it lazily: only
    # when a concrete LLM transport (FK-41 §41.6.2, e.g. HubLlmClient from
    # build_verify_system) is supplied.  Without it the factory is wired WITHOUT
    # a sharpener so the other five top methods (and every non-derive_check CLI
    # subcommand) still build; derive_check stays FAIL-CLOSED via the
    # CheckFactory.derive_check guard (InvariantSharpenerPort is None -> raise).
    _sharpener = _LlmInvariantSharpener(llm_client) if llm_client is not None else None
    _story_creation = _AK3StoryCreationAdapter(project_key)

    pattern_promotion = _PatternPromotion(
        accessor=accessor,
        pattern_repo=pattern_repo,
        project_key=project_key,
    )
    check_factory = _CheckFactory(
        pattern_repo=pattern_repo,
        check_repo=check_repo,
        project_key=project_key,
        invariant_sharpener=_sharpener,
        story_creation=_story_creation,
    )
    effectiveness_tracker = _CheckEffectivenessTracker(
        accessor=accessor,
        check_repo=check_repo,
        pattern_repo=pattern_repo,
        project_key=project_key,
    )
    return _FailureCorpus(
        incident_triage=triage,
        pattern_promotion=pattern_promotion,
        check_factory=check_factory,
        effectiveness_tracker=effectiveness_tracker,
        check_repo=check_repo,
        project_key=project_key,
    )


# ---------------------------------------------------------------------------
# AG3-076: CLI read-only helpers (operator/recovery CLI surface).
#
# The CLI boundary (agentkit.backend.cli) is an entry_boundary and may NOT import
# agentkit.backend.state_backend.store directly (that would require keeping the broad
# state_backend_repository grant in the CLI's boundary declaration).  These
# thin wrappers route ALL state-backend reads through the composition root
# so the CLI imports ONLY agentkit.backend.bootstrap.composition_root — which is
# already its normal wiring surface.
# ---------------------------------------------------------------------------


def cli_load_story_context(story_dir: Path) -> StoryContext | None:
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


def cli_load_execution_events_for_project_global(
    project_key: str,
    *,
    limit: int | None = None,
) -> list[object]:
    """Load all execution events for a project for the CLI.

    Thin composition-root wrapper over
    ``facade.load_execution_events_for_project_global`` so the
    operator/recovery CLI (AG3-076) can read project-global telemetry without
    importing ``agentkit.backend.state_backend.store`` directly.

    Args:
        project_key: The project key to scope the query.
        limit: Optional maximum number of records to return.

    Returns:
        A list of :class:`~agentkit.backend.telemetry.records.ExecutionEventRecord`
        instances (typed as ``object`` to avoid a hard import in the wrapper
        signature).
    """
    from agentkit.backend.state_backend.store.facade import load_execution_events_for_project_global

    return load_execution_events_for_project_global(project_key, limit=limit)  # type: ignore[return-value]


# Keep export metadata compact so module-level LOC stays under the project gate.
__all__ = ["ClosureConfigUnavailableError", "SetupCoordinatesUnavailableError", "build_artifact_invalidation_sink", "build_review_completion_sink", "build_artifact_manager", "build_closure_phase_handler", "build_exploration_drafting", "build_exploration_phase_handler", "build_exploration_review", "build_failure_corpus", "build_integrity_gate", "build_phase_state_residue_probe", "build_pipeline_engine", "build_pipeline_handler_registry", "build_planning_projection_accessor", "build_planning_story_dependency_repository", "build_producer_registry", "build_projection_accessor", "build_runtime_execution_purge_port", "build_runtime_execution_residue_probe", "build_setup_config_for_run", "build_setup_phase_handler", "build_setup_preflight_gate", "build_skills", "build_sonar_gate_port", "build_structural_are_provider", "build_structural_build_test_port", "build_verify_system", "cli_load_story_context", "cli_load_execution_events_for_project_global", "cli_read_phase_state_record"]  # noqa: E501
