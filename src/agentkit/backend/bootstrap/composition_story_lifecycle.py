"""Composition builders of the story-lifecycle bounded context.

These three builders wire CORE services -- FK-58 story exit, FK-53 story reset
and the FK-07 §7.6 story read surface. They were extracted from
``composition_project`` by AG3-240: that module carries an edge anchor
(``build_compat_window_reader`` constructs a ``ProjectEdgeClient``) and therefore
falls into the edge distribution under longest-match-wins, which made every
story service it built an edge-to-core boundary crossing. The frozen
classification already named all three as ``core_symbols`` of
``architecture-conformance.symbol_boundary.bootstrap_composition_project``; this
module is where they land.

Deliberately NOT here:

* ``build_story_split_service`` -- it builds a core service AND resolves a
  Weaviate adapter locally. AG3-237 recorded that as an open question owned by
  the Product Owner and refused to decide it a second time; AG3-240 does not
  decide it either, so the builder stays where it is until the owner rules.
* ``build_project_read_model_routes`` -- project-management wiring that happens
  to construct a story service. It belongs to that bounded context, not this one.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from agentkit.backend.bootstrap.composition_state import (
    build_projection_accessor,
    build_runtime_execution_purge_port,
    build_runtime_execution_residue_probe,
)

if TYPE_CHECKING:
    from agentkit.backend.bootstrap import composition_project_types as project_types


def build_story_exit_service() -> object:
    """Build the productive FK-58 story-exit service."""

    from agentkit.backend.control_plane.repository import ControlPlaneRuntimeRepository
    from agentkit.backend.governance.administration import Governance
    from agentkit.backend.state_backend.store.control_plane_writer_lease import (
        load_bound_control_plane_writer_identity,
    )
    from agentkit.backend.state_backend.store.lock_record_repository import LockRecordRepository
    from agentkit.backend.story_context_manager.service import StoryService
    from agentkit.backend.story_exit.service import StoryExitService

    identity = load_bound_control_plane_writer_identity()
    if identity is None:
        raise RuntimeError("story exit requires the active control-plane writer identity")

    governance = Governance(lock_repo=LockRecordRepository())
    return StoryExitService(
        control_plane_repository=ControlPlaneRuntimeRepository(),
        story_service=StoryService(),
        governance=governance,
        instance_identity=identity,
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
        LockPurgeAdapter,
        ReadModelPurgeAdapter,
        ResetDisownAdapter,
        RunScopeAdapter,
        RuntimePurgeAdapter,
        WorkspacePurgeAdapter,
        WorktreePurgeAdapter,
    )
    from agentkit.backend.control_plane.edge_command_repository import EdgeCommandRepository
    from agentkit.backend.control_plane.repository import (
        ControlPlaneRuntimeRepository,
        RunOwnershipRepository,
    )
    from agentkit.backend.governance.administration import Governance
    from agentkit.backend.kpi_analytics.aggregation import RefreshWorker
    from agentkit.backend.kpi_analytics.fact_store import FactStore
    from agentkit.backend.state_backend.store.analytics_source import (
        StateBackendAnalyticsSource,
    )
    from agentkit.backend.state_backend.store.control_plane_writer_lease import (
        load_bound_control_plane_writer_identity,
    )
    from agentkit.backend.state_backend.store.fact_repository import (
        StateBackendFactRepository,
    )
    from agentkit.backend.state_backend.store.lock_record_repository import LockRecordRepository
    from agentkit.backend.state_backend.store.story_read_repository import (
        StateBackendStoryReadRepository,
    )
    from agentkit.backend.story_context_manager.service import StoryService
    from agentkit.backend.story_reset import FileResetRecordStore, StoryResetService

    if load_bound_control_plane_writer_identity() is None:
        raise RuntimeError("story reset requires the active control-plane writer identity")

    resolved_root = project_root or store_dir
    lock_repo = LockRecordRepository(store_dir)
    governance = Governance(lock_repo=lock_repo)
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
        fence=ResetDisownAdapter(cp_repo),
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


__all__ = [
    "build_story_exit_service",
    "build_story_read_service",
    "build_story_reset_service",
]
