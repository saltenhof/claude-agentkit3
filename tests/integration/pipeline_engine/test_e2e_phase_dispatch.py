"""Dispatch/Guard CONTRACT integration test (AG3-054).

Explicitly NOT a productive worker-spawn run (story §2.1.5 / §1.1): it drives the
PRODUCTIVE control-plane entrypoint ``ControlPlaneRuntimeService.start_phase``
across MULTIPLE sequential calls Setup -> Implementation -> Closure and proves the
DISPATCH behaviour -- one phase per call, transitions follow the typed workflow, a
normalized phase result rides back on the SAME mutation result, ESCALATED stops
the run, and a same-phase resume continues. ALL external boundaries are stubbed
(the engine handlers are NoOp/scripted at the boundary, worker-spawn is not
exercised); the dispatcher + pre-start guard + engine + transition-enforcement +
idempotent persistence run for real (one truth, no second state/dispatch path).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from tests.fixtures.git_repo import ensure_git_repo

from agentkit.backend.control_plane.dispatch import PhaseDispatcher, PreStartGuard
from agentkit.backend.control_plane.models import PhaseMutationRequest
from agentkit.backend.control_plane.runtime import ControlPlaneRuntimeService
from agentkit.backend.control_plane.workspace_locator import (
    StoryWorkspace,
    build_story_workspace_locator,
)
from agentkit.backend.installer import InstallConfig, install_agentkit
from agentkit.backend.installer.paths import story_dir as resolve_story_dir
from agentkit.backend.pipeline_engine.engine import PipelineEngine
from agentkit.backend.pipeline_engine.lifecycle import (
    HandlerResult,
    NoOpHandler,
    PhaseHandlerRegistry,
)
from agentkit.backend.pipeline_engine.phase_executor import PhaseStatus
from agentkit.backend.process.language.definitions import resolve_workflow
from agentkit.backend.state_backend.store import save_story_context
from agentkit.backend.story_context_manager.models import StoryContext
from agentkit.backend.story_context_manager.types import StoryMode, StoryType

if TYPE_CHECKING:
    from pathlib import Path

    from agentkit.backend.pipeline_engine.phase_envelope.envelope import PhaseEnvelope


# ---------------------------------------------------------------------------
# Boundary stubs / fakes
# ---------------------------------------------------------------------------


class _AllowApproval:
    def is_approved(self, project_key: str, story_display_id: str) -> bool:
        del project_key, story_display_id
        return True


class _AllowScheduling:
    def is_ready_and_admitted(self, project_key: str, story_display_id: str) -> bool:
        del project_key, story_display_id
        return True


class _EscalatingHandler:
    def on_enter(
        self, ctx: StoryContext, envelope: PhaseEnvelope
    ) -> HandlerResult:
        del ctx, envelope
        return HandlerResult(status=PhaseStatus.ESCALATED, errors=("blocked",))

    def on_exit(self, ctx: StoryContext, envelope: PhaseEnvelope) -> None:
        del ctx, envelope

    def on_resume(
        self, ctx: StoryContext, envelope: PhaseEnvelope, trigger: str
    ) -> HandlerResult:
        del ctx, envelope, trigger
        return HandlerResult(status=PhaseStatus.ESCALATED)


def _install_project(project_dir: Path) -> None:
    # AG3-088 CI regression (Jenkins #314): CP 11 (cp11_to_12.py, FK-50 §50.3)
    # runs ``git config core.hooksPath`` and hard-aborts (reason
    # ``git_config_failed``) when the target is not a git repo. Real AgentKit
    # targets ARE git repos; a clean Linux CI agent puts ``tmp_path`` under
    # ``/tmp`` (no ambient parent repo), so git-init the project root first via
    # the shared helper — mirrors the unit installer tests.
    ensure_git_repo(project_dir)
    result = install_agentkit(
        InstallConfig(
            project_key=project_dir.name,
            project_name=project_dir.name,
            project_root=project_dir,
            github_owner="acme",
            github_repo="demo",
            sonarqube_available=False,
            ci_available=False,
        )
    )
    assert result.success


def _persist_ctx(
    project_dir: Path, story_id: str, *, with_project_root: bool = True
) -> StoryContext:
    s_dir = resolve_story_dir(project_dir, story_id)
    s_dir.mkdir(parents=True, exist_ok=True)
    ctx = StoryContext(
        project_key=project_dir.name,
        story_id=story_id,
        story_type=StoryType.IMPLEMENTATION,
        execution_route=StoryMode.EXECUTION,
        # AG3-123: ``project_root`` is no longer the canonical FS input. The
        # default leaves it set for the legacy assertions; the decoupling test
        # passes ``with_project_root=False`` to prove the Backend resolves the
        # anchor itself from the level-1 ``project_registry``.
        project_root=project_dir if with_project_root else None,
    )
    save_story_context(s_dir, ctx)
    return ctx


def _boundary_dispatcher(
    *,
    guard: PreStartGuard,
    overrides: dict[str, object] | None = None,
) -> PhaseDispatcher:
    """Build a dispatcher whose engine uses NoOp handlers at the boundaries.

    This is the sanctioned external-boundary test cut: the dispatch / engine /
    transition-enforcement / normalization run for real; only the phase handlers
    (which would otherwise spawn workers / call git / Sonar) are stubbed.

    AG3-123: the story-workspace FS anchor is resolved by the PRODUCTIVE
    ``StoryWorkspaceLocator`` (canonical level-1 ``project_registry`` written by
    the real install), NOT a fake and NOT ``ctx.project_root``. The engine's
    persistence root is ``workspace.story_dir`` -- proving the decoupling on the
    real ``ControlPlaneRuntimeService`` flow (AC4: not a fake-locator proof).
    """
    overrides = overrides or {}

    def _factory(ctx: StoryContext, workspace: StoryWorkspace) -> PipelineEngine:
        workflow = resolve_workflow(ctx.story_type)
        registry = PhaseHandlerRegistry()
        for name in workflow.phase_names:
            registry.register(name, overrides.get(name, NoOpHandler()))  # type: ignore[arg-type]
        return PipelineEngine(workflow, registry, workspace.story_dir)

    return PhaseDispatcher(
        workspace_locator=build_story_workspace_locator(),
        engine_factory=_factory,
        guard_factory=lambda workspace: guard,
    )


def _request(project_dir: Path, story_id: str, op_suffix: str) -> PhaseMutationRequest:
    return PhaseMutationRequest(
        project_key=project_dir.name,
        story_id=story_id,
        session_id="sess-1",
        principal_type="worker",
        worktree_roots=[str(project_dir)],
        op_id=f"op-{story_id}-{op_suffix}",
    )


@pytest.mark.integration
class TestSequentialDispatchContract:
    """Sequential start_phase calls drive one phase each across the workflow."""

    def test_setup_implementation_closure_one_phase_per_call(
        self, tmp_path: Path
    ) -> None:
        """Setup -> Implementation -> Closure, exactly one phase per start call."""
        project_dir = tmp_path / "proj"
        project_dir.mkdir()
        _install_project(project_dir)
        story_id = "DISP-001"
        _persist_ctx(project_dir, story_id)

        guard = PreStartGuard(
            approval_reader=_AllowApproval(),
            scheduling_reader=_AllowScheduling(),
        )
        service = ControlPlaneRuntimeService(
            phase_dispatcher=_boundary_dispatcher(guard=guard)
        )

        # 1. Setup
        setup = service.start_phase(
            run_id="run-1",
            phase="setup",
            request=_request(project_dir, story_id, "setup"),
        )
        assert setup.phase_dispatch is not None
        assert setup.phase_dispatch.phase == "setup"
        assert setup.phase_dispatch.status == "phase_completed"
        # EXECUTION mode -> next is implementation (exploration skipped).
        assert setup.phase_dispatch.next_phase == "implementation"
        # The idempotent edge-bundle persistence still produced its result.
        assert setup.status == "committed"
        assert setup.edge_bundle is not None

        # 2. Implementation
        impl = service.start_phase(
            run_id="run-1",
            phase="implementation",
            request=_request(project_dir, story_id, "impl"),
        )
        assert impl.phase_dispatch is not None
        assert impl.phase_dispatch.phase == "implementation"
        assert impl.phase_dispatch.status == "phase_completed"
        assert impl.phase_dispatch.next_phase == "closure"

        # 3. Closure
        closure = service.start_phase(
            run_id="run-1",
            phase="closure",
            request=_request(project_dir, story_id, "closure"),
        )
        assert closure.phase_dispatch is not None
        assert closure.phase_dispatch.phase == "closure"
        assert closure.phase_dispatch.status == "phase_completed"
        # Terminal phase -> no next phase to advance to.
        assert closure.phase_dispatch.next_phase is None

    def test_escalated_implementation_stops_before_closure(
        self, tmp_path: Path
    ) -> None:
        """An ESCALATED implementation yields no next phase -> closure not started."""
        project_dir = tmp_path / "proj"
        project_dir.mkdir()
        _install_project(project_dir)
        story_id = "DISP-002"
        _persist_ctx(project_dir, story_id)

        guard = PreStartGuard(
            approval_reader=_AllowApproval(),
            scheduling_reader=_AllowScheduling(),
        )
        service = ControlPlaneRuntimeService(
            phase_dispatcher=_boundary_dispatcher(
                guard=guard,
                overrides={"implementation": _EscalatingHandler()},
            )
        )

        service.start_phase(
            run_id="run-1",
            phase="setup",
            request=_request(project_dir, story_id, "setup"),
        )
        impl = service.start_phase(
            run_id="run-1",
            phase="implementation",
            request=_request(project_dir, story_id, "impl"),
        )

        assert impl.phase_dispatch is not None
        assert impl.phase_dispatch.status == "escalated"
        assert impl.phase_dispatch.reaction == "escalate"
        assert impl.phase_dispatch.next_phase is None

    def test_idempotent_replay_does_not_redispatch(self, tmp_path: Path) -> None:
        """A replayed op_id returns the stored result without a second dispatch.

        The dispatch AUGMENTS the idempotent persistence -- it does not create a
        second state-write or dispatch path. A re-send of the same op_id replays.
        """
        project_dir = tmp_path / "proj"
        project_dir.mkdir()
        _install_project(project_dir)
        story_id = "DISP-003"
        _persist_ctx(project_dir, story_id)

        guard = PreStartGuard(
            approval_reader=_AllowApproval(),
            scheduling_reader=_AllowScheduling(),
        )
        service = ControlPlaneRuntimeService(
            phase_dispatcher=_boundary_dispatcher(guard=guard)
        )
        req = _request(project_dir, story_id, "setup")

        first = service.start_phase(run_id="run-1", phase="setup", request=req)
        replay = service.start_phase(run_id="run-1", phase="setup", request=req)

        assert first.status == "committed"
        assert replay.status == "replayed"

    def test_guard_rejection_blocks_setup_dispatch(self, tmp_path: Path) -> None:
        """A denying pre-start guard rejects the fresh setup start (no dispatch)."""
        project_dir = tmp_path / "proj"
        project_dir.mkdir()
        _install_project(project_dir)
        story_id = "DISP-004"
        _persist_ctx(project_dir, story_id)

        class _Deny:
            def is_approved(self, project_key: str, story_display_id: str) -> bool:
                del project_key, story_display_id
                return False

        guard = PreStartGuard(
            approval_reader=_Deny(),
            scheduling_reader=_AllowScheduling(),
        )
        service = ControlPlaneRuntimeService(
            phase_dispatcher=_boundary_dispatcher(guard=guard)
        )

        setup = service.start_phase(
            run_id="run-1",
            phase="setup",
            request=_request(project_dir, story_id, "setup"),
        )

        assert setup.phase_dispatch is not None
        assert setup.phase_dispatch.status == "rejected"
        assert setup.phase_dispatch.dispatched is False

    def test_productive_engine_builds_closure_without_ctx_project_root(
        self, tmp_path: Path
    ) -> None:
        """AG3-123 AC1/AC4 (BLOCKER): the PRODUCTIVE engine-construction path builds.

        Drives the REAL composition-root wiring
        (``build_pipeline_engine`` -> ``build_pipeline_handler_registry`` ->
        ``build_closure_phase_handler`` -> ``_resolve_pre_merge_configs``) -- NOT a
        NoOp-replacement engine factory -- with a persisted ``StoryContext`` whose
        ``project_root`` is ``None``. Pre-AG3-123 the eager closure wiring hard-failed
        with ``ClosureConfigUnavailableError`` here (it reloaded the context and read
        ``ctx.project_root``); now the closure pre-merge config root is the
        Backend-resolved ``StoryWorkspace.project_root`` threaded down, so the full
        closure-bearing engine wires from the workspace anchor alone.
        """
        from agentkit.backend.bootstrap.composition_root import (
            build_pipeline_engine,
            build_pipeline_handler_registry,
        )
        from agentkit.backend.control_plane.workspace_locator import (
            build_story_workspace_locator,
        )

        project_dir = tmp_path / "proj"
        project_dir.mkdir()
        _install_project(project_dir)
        story_id = "DISP-006"
        # No dev-local project_root on the persisted context.
        _persist_ctx(project_dir, story_id, with_project_root=False)

        workspace = build_story_workspace_locator().resolve(
            project_dir.name, story_id, "run-1"
        )
        # IMPLEMENTATION workflow includes the closure phase -> the eager closure
        # handler wiring runs during construction. Thread ONLY the Backend-resolved
        # workspace anchor (exactly as the productive ``build_phase_dispatcher``
        # engine factory does); the persisted ctx carries no project_root.
        registry = build_pipeline_handler_registry(
            workspace.story_dir,
            story_type=StoryType.IMPLEMENTATION,
            project_key=project_dir.name,
            project_root=workspace.project_root,
        )
        # The closure handler was actually wired (the eager pre-merge resolution
        # succeeded against the Backend-resolved root, not ctx.project_root).
        assert "closure" in registry.registered_phases
        # The full engine also composes over the productive wiring.
        engine = build_pipeline_engine(
            workspace.story_dir,
            story_type=StoryType.IMPLEMENTATION,
            project_key=project_dir.name,
            project_root=workspace.project_root,
        )
        assert engine is not None

    def test_backend_resolved_workspace_without_ctx_project_root(
        self, tmp_path: Path
    ) -> None:
        """AG3-123 AC1/AC4: the REAL flow dispatches with NO dev-local project_root.

        Drives the productive ``ControlPlaneRuntimeService`` phase-boundary flow:
        the run ``StoryContext`` carries ``project_root=None`` (the dev process
        supplies no canonical FS input), yet the PRODUCTIVE
        ``StoryWorkspaceLocator`` resolves the workspace from the level-1
        ``project_registry`` the real install wrote. Setup dispatches and produces
        state; the follow-up implementation start (state produced by the setup
        predecessor, NOT manually set) dispatches along the valid workflow edge --
        proving the decoupling on the real runtime, not via a fake locator.
        """
        project_dir = tmp_path / "proj"
        project_dir.mkdir()
        _install_project(project_dir)
        story_id = "DISP-005"
        # No dev-local project_root on the context -> Backend-resolved anchor only.
        _persist_ctx(project_dir, story_id, with_project_root=False)

        guard = PreStartGuard(
            approval_reader=_AllowApproval(),
            scheduling_reader=_AllowScheduling(),
        )
        service = ControlPlaneRuntimeService(
            phase_dispatcher=_boundary_dispatcher(guard=guard)
        )

        setup = service.start_phase(
            run_id="run-1",
            phase="setup",
            request=_request(project_dir, story_id, "setup"),
        )
        assert setup.phase_dispatch is not None
        assert setup.phase_dispatch.status == "phase_completed"
        assert setup.phase_dispatch.next_phase == "implementation"

        impl = service.start_phase(
            run_id="run-1",
            phase="implementation",
            request=_request(project_dir, story_id, "impl"),
        )
        assert impl.phase_dispatch is not None
        assert impl.phase_dispatch.status == "phase_completed"
