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


def _persist_ctx(project_dir: Path, story_id: str) -> StoryContext:
    s_dir = resolve_story_dir(project_dir, story_id)
    s_dir.mkdir(parents=True, exist_ok=True)
    ctx = StoryContext(
        project_key=project_dir.name,
        story_id=story_id,
        story_type=StoryType.IMPLEMENTATION,
        execution_route=StoryMode.EXECUTION,
        project_root=project_dir,
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
    """
    overrides = overrides or {}

    def _factory(ctx: StoryContext) -> PipelineEngine:
        workflow = resolve_workflow(ctx.story_type)
        registry = PhaseHandlerRegistry()
        for name in workflow.phase_names:
            registry.register(name, overrides.get(name, NoOpHandler()))  # type: ignore[arg-type]
        return PipelineEngine(workflow, registry, resolve_story_dir(
            ctx.project_root, ctx.story_id  # type: ignore[arg-type]
        ))

    return PhaseDispatcher(engine_factory=_factory, guard_factory=lambda ctx: guard)


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
