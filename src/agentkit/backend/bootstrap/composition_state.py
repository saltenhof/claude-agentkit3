"""State-backend and projection composition builders."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Callable

    from agentkit.backend.bootstrap import composition_project_types as project_types

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
) -> project_types.RuntimeExecutionPurgePort:
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
) -> project_types.RuntimeExecutionResidueProbe:
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


def build_projection_accessor(store_dir: Path | None = None) -> project_types.ProjectionAccessor:
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
    from agentkit.backend.state_backend.store.telemetry_projection_repositories import (
        build_projection_repositories,
    )
    from agentkit.backend.telemetry.projection_accessor import (
        ProjectionAccessor as _ProjectionAccessor,
    )

    repos = build_projection_repositories(store_dir)
    return _ProjectionAccessor(repos)


def build_planning_projection_accessor(
    store_dir: Path | None = None,
) -> project_types.PlanningProjectionAccessor:
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
) -> project_types.PlanningWritePathStoryDependencyRepository:
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

def build_phase_envelope_store(story_dir: Path) -> project_types.PhaseEnvelopeStore:
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
