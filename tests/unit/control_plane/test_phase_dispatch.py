"""Unit tests for the deterministic single-phase dispatch (AG3-054).

Drives :class:`PhaseDispatcher` against a REAL ``PipelineEngine`` (the engine /
transition-enforcement is called, not rebuilt) with scripted handlers at the
phase boundary. Pins FK-45 §45.1.2/§45.2/§45.3: one dispatch == one phase,
first-call-only-setup, invalid transition rejected, PAUSED/ESCALATED does not
start a follow-up phase, resume of the same PAUSED phase continues, and the
pre-start guard fires ONLY on the fresh-run setup start (never on follow-ups).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from tests.phase_state_factory import make_phase_state

from agentkit.backend.control_plane.dispatch import (
    PhaseDispatcher,
    PreStartGuard,
    _enforce_transition,
)
from agentkit.backend.control_plane.workspace_locator import (
    StoryWorkspace,
    StoryWorkspaceUnresolvedError,
)
from agentkit.backend.pipeline_engine.engine import PipelineEngine
from agentkit.backend.pipeline_engine.lifecycle import (
    HandlerResult,
    NoOpHandler,
    PhaseHandlerRegistry,
)
from agentkit.backend.pipeline_engine.phase_executor import PhaseState, PhaseStatus
from agentkit.backend.process.language.definitions import resolve_workflow
from agentkit.backend.state_backend.config import ALLOW_SQLITE_ENV, STATE_BACKEND_ENV
from agentkit.backend.state_backend.persistence_test_support import reset_backend_cache_for_tests
from agentkit.backend.state_backend.story_lifecycle_store import save_story_context
from agentkit.backend.story_context_manager.models import StoryContext
from agentkit.backend.story_context_manager.types import StoryMode, StoryType

if TYPE_CHECKING:
    from collections.abc import Generator
    from pathlib import Path

    from agentkit.backend.pipeline_engine.phase_envelope.envelope import PhaseEnvelope


@pytest.fixture(autouse=True)
def sqlite_backend_env(
    monkeypatch: pytest.MonkeyPatch,
) -> Generator[None, None, None]:
    monkeypatch.setenv(STATE_BACKEND_ENV, "sqlite")
    monkeypatch.setenv(ALLOW_SQLITE_ENV, "1")
    reset_backend_cache_for_tests()
    yield
    reset_backend_cache_for_tests()


# ---------------------------------------------------------------------------
# Scripted handlers / fakes (boundary only)
# ---------------------------------------------------------------------------


class _PausingHandler:
    def on_enter(
        self, ctx: StoryContext, envelope: PhaseEnvelope
    ) -> HandlerResult:
        del ctx, envelope
        return HandlerResult(
            status=PhaseStatus.PAUSED, yield_status="awaiting_design_review"
        )

    def on_exit(self, ctx: StoryContext, envelope: PhaseEnvelope) -> None:
        del ctx, envelope

    def on_resume(
        self, ctx: StoryContext, envelope: PhaseEnvelope, trigger: str
    ) -> HandlerResult:
        del ctx, envelope, trigger
        return HandlerResult(status=PhaseStatus.COMPLETED)


class _EscalatingHandler:
    def on_enter(
        self, ctx: StoryContext, envelope: PhaseEnvelope
    ) -> HandlerResult:
        del ctx, envelope
        return HandlerResult(
            status=PhaseStatus.ESCALATED, errors=("worker_blocked",)
        )

    def on_exit(self, ctx: StoryContext, envelope: PhaseEnvelope) -> None:
        del ctx, envelope

    def on_resume(
        self, ctx: StoryContext, envelope: PhaseEnvelope, trigger: str
    ) -> HandlerResult:
        del ctx, envelope, trigger
        return HandlerResult(status=PhaseStatus.ESCALATED)


def _allow_guard() -> PreStartGuard:
    return PreStartGuard(
        approval_reader=_AlwaysApprovedReader(),
        scheduling_reader=_AlwaysAdmittedReader(),
    )


def _deny_guard() -> PreStartGuard:
    return PreStartGuard(
        approval_reader=_NeverApprovedReader(),
        scheduling_reader=_AlwaysAdmittedReader(),
    )


class _AlwaysApprovedReader:
    def is_approved(self, project_key: str, story_display_id: str) -> bool:
        del project_key, story_display_id
        return True


class _NeverApprovedReader:
    def is_approved(self, project_key: str, story_display_id: str) -> bool:
        del project_key, story_display_id
        return False


class _AlwaysAdmittedReader:
    def is_ready_and_admitted(self, project_key: str, story_display_id: str) -> bool:
        del project_key, story_display_id
        return True


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _ctx(
    story_dir: Path,
    *,
    story_type: StoryType = StoryType.IMPLEMENTATION,
    execution_route: StoryMode | None = StoryMode.EXECUTION,
) -> StoryContext:
    ctx = StoryContext(
        project_key="test-project",
        story_id="AG3-700",
        story_type=story_type,
        execution_route=execution_route,
        project_root=story_dir.parent,
    )
    save_story_context(story_dir, ctx)
    return ctx


class _FakeWorkspaceLocator:
    """Backend workspace locator fake: returns the test story_dir as the anchor.

    AG3-123: the dispatcher resolves the FS anchor Backend-side via this port, NOT
    from ``ctx.project_root``. The unit tests inject this fake so the workspace is
    deterministic; the productive ``StateBackendStoryWorkspaceLocator`` is proven
    separately (resolver tests + the real-runtime integration flow).
    """

    def __init__(self, story_dir: Path) -> None:
        self._story_dir = story_dir

    def resolve(
        self, project_key: str, story_id: str, run_id: str
    ) -> StoryWorkspace:
        return StoryWorkspace(
            project_key=project_key,
            story_id=story_id,
            run_id=run_id,
            project_root=self._story_dir.parent,
            story_dir=self._story_dir,
        )


def _engine_factory(
    overrides: dict[str, object] | None = None,
):
    overrides = overrides or {}

    def _factory(ctx: StoryContext, workspace: StoryWorkspace) -> PipelineEngine:
        workflow = resolve_workflow(ctx.story_type)
        registry = PhaseHandlerRegistry()
        for name in workflow.phase_names:
            registry.register(name, overrides.get(name, NoOpHandler()))  # type: ignore[arg-type]
        return PipelineEngine(workflow, registry, workspace.story_dir)

    return _factory


def _dispatcher(
    story_dir: Path,
    *,
    guard: PreStartGuard | None = None,
    overrides: dict[str, object] | None = None,
) -> PhaseDispatcher:
    resolved_guard = guard or _allow_guard()
    return PhaseDispatcher(
        workspace_locator=_FakeWorkspaceLocator(story_dir),
        engine_factory=_engine_factory(overrides),
        guard_factory=lambda workspace: resolved_guard,
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

#: AG3-054: the run id threaded into every dispatch. A FRESH setup start passes
#: ``run_admitted=False`` (the run is not yet admitted -> the pre-start guard must
#: fire); a follow-up phase / resume of an already-admitted run passes
#: ``run_admitted=True`` (the run was admitted by its prior committed setup start).
#: The admission flag is now RUN-scoped data threaded by the caller, NOT derived
#: from story-scoped phase-state.
_RUN_ID = "run-700"


class TestSinglePhaseDispatch:
    def test_one_call_runs_exactly_one_phase(self, tmp_path: Path) -> None:
        """A single start dispatch runs ONE phase and returns its normalized result."""
        story_dir = tmp_path / "stories" / "AG3-700"
        story_dir.mkdir(parents=True)
        ctx = _ctx(story_dir)
        dispatcher = _dispatcher(story_dir)

        result = dispatcher.dispatch(
            ctx=ctx,
            phase="setup",
            run_id=_RUN_ID,
            run_admitted=False,
        )

        assert result.dispatched is True
        assert result.phase == "setup"
        assert result.status == "phase_completed"
        # setup completed and a next phase exists -> the orchestrator should run a
        # worker (FK-45 §45.3), NOT start the next phase itself.
        assert result.reaction == "run_worker"
        assert result.next_phase in {"implementation", "exploration"}

    def test_first_call_must_be_setup(self, tmp_path: Path) -> None:
        """First call (un-admitted run) for a non-setup phase is rejected (FK-45 §45.2).

        AG3-054 ERROR-1: first-call enforcement is RUN-scoped. An un-admitted run
        (``run_admitted=False``) requesting a non-setup phase is rejected even
        though no story-scoped phase-state exists either.
        """
        story_dir = tmp_path / "stories" / "AG3-700"
        story_dir.mkdir(parents=True)
        ctx = _ctx(story_dir)
        dispatcher = _dispatcher(story_dir)

        result = dispatcher.dispatch(
            ctx=ctx,
            phase="implementation",
            run_id=_RUN_ID,
            run_admitted=False,
        )

        assert result.status == "rejected"
        assert result.dispatched is False
        assert result.rejection_reason is not None
        assert "setup" in result.rejection_reason

    def test_invalid_transition_is_rejected(self, tmp_path: Path) -> None:
        """An out-of-graph forward jump never enters the phase (fail-closed).

        After setup completes, jumping straight to closure (skipping
        implementation) is not a workflow edge -> the dispatch rejects it via the
        phase-transition-enforcement BEFORE the engine is invoked (FK-45 §45.2).
        """
        story_dir = tmp_path / "stories" / "AG3-700"
        story_dir.mkdir(parents=True)
        ctx = _ctx(story_dir)
        dispatcher = _dispatcher(story_dir)
        dispatcher.dispatch(
            ctx=ctx,
            phase="setup",
            run_id=_RUN_ID,
            run_admitted=False,
        )

        result = dispatcher.dispatch(
            ctx=ctx,
            phase="closure",
            run_id=_RUN_ID,
            run_admitted=True,
        )

        assert result.status == "rejected"
        assert result.dispatched is False
        assert result.reaction == "rejected"
        reason = result.rejection_reason or ""
        assert "Invalid phase transition" in reason
        assert "from_phase='setup'" in reason
        assert "to_phase='closure'" in reason
        assert "from_status='completed'" in reason
        assert "allowed transitions" in reason

    def test_escalated_phase_does_not_start_follow_up(self, tmp_path: Path) -> None:
        """An ESCALATED implementation result yields no next_phase (no closure start)."""
        story_dir = tmp_path / "stories" / "AG3-700"
        story_dir.mkdir(parents=True)
        ctx = _ctx(story_dir)
        dispatcher = _dispatcher(
            story_dir, overrides={"implementation": _EscalatingHandler()}
        )
        dispatcher.dispatch(
            ctx=ctx,
            phase="setup",
            run_id=_RUN_ID,
            run_admitted=False,
        )

        result = dispatcher.dispatch(
            ctx=ctx,
            phase="implementation",
            run_id=_RUN_ID,
            run_admitted=True,
        )

        assert result.status == "escalated"
        assert result.reaction == "escalate"
        assert result.next_phase is None

    def test_paused_phase_does_not_start_follow_up(self, tmp_path: Path) -> None:
        """A PAUSED phase result awaits external input, never advancing."""
        story_dir = tmp_path / "stories" / "AG3-700"
        story_dir.mkdir(parents=True)
        ctx = _ctx(story_dir)
        dispatcher = _dispatcher(
            story_dir, overrides={"implementation": _PausingHandler()}
        )
        dispatcher.dispatch(
            ctx=ctx,
            phase="setup",
            run_id=_RUN_ID,
            run_admitted=False,
        )

        result = dispatcher.dispatch(
            ctx=ctx,
            phase="implementation",
            run_id=_RUN_ID,
            run_admitted=True,
        )

        assert result.status == "yielded"
        assert result.reaction == "await_external"
        assert result.next_phase is None
        assert result.yield_status == "awaiting_design_review"


def _exploration_ctx(story_dir: Path) -> StoryContext:
    """Persist an EXPLORATION-mode story context (setup -> exploration path)."""
    ctx = StoryContext(
        project_key="test-project",
        story_id="AG3-700",
        story_type=StoryType.IMPLEMENTATION,
        execution_route=StoryMode.EXPLORATION,
        project_root=story_dir.parent,
    )
    save_story_context(story_dir, ctx)
    return ctx


class TestResume:
    def test_resume_same_paused_phase_continues(self, tmp_path: Path) -> None:
        """A second start of the same PAUSED phase resumes (no restart, no jump).

        Pauses on ``exploration`` (whose ``design_review`` yield-point declares the
        ``design_approved`` resume trigger) so the resume drives the real
        ``on_resume`` path, not a re-entry.
        """
        story_dir = tmp_path / "stories" / "AG3-700"
        story_dir.mkdir(parents=True)
        ctx = _exploration_ctx(story_dir)
        dispatcher = _dispatcher(
            story_dir, overrides={"exploration": _PausingHandler()}
        )
        dispatcher.dispatch(
            ctx=ctx,
            phase="setup",
            run_id=_RUN_ID,
            run_admitted=False,
        )
        paused = dispatcher.dispatch(
            ctx=ctx,
            phase="exploration",
            run_id=_RUN_ID,
            run_admitted=True,
        )
        assert paused.status == "yielded"

        resumed = dispatcher.dispatch(
            ctx=ctx,
            phase="exploration",
            run_id=_RUN_ID,
            run_admitted=True,
            detail={"resume_trigger": "design_approved"},
        )

        assert resumed.status == "phase_completed"
        assert resumed.phase == "exploration"


class TestGuardScope:
    def test_guard_rejects_fresh_setup_start(self, tmp_path: Path) -> None:
        """A denying guard rejects the fresh-run setup start (no setup dispatch)."""
        story_dir = tmp_path / "stories" / "AG3-700"
        story_dir.mkdir(parents=True)
        ctx = _ctx(story_dir)
        dispatcher = _dispatcher(story_dir, guard=_deny_guard())

        result = dispatcher.dispatch(
            ctx=ctx,
            phase="setup",
            run_id=_RUN_ID,
            run_admitted=False,
        )

        assert result.status == "rejected"
        assert result.dispatched is False
        assert "Approved" in (result.rejection_reason or "")

    def test_guard_does_not_fire_on_follow_up_phase(self, tmp_path: Path) -> None:
        """The guard does NOT fire for a follow-up phase, even when it would deny.

        Once the run is admitted (``run_admitted=True``), the guard must not re-gate
        implementation. A DENYING guard here must NOT block it.
        """
        story_dir = tmp_path / "stories" / "AG3-700"
        story_dir.mkdir(parents=True)
        ctx = _ctx(story_dir)
        # First, run setup with a permissive guard (admit the run).
        _dispatcher(story_dir).dispatch(
            ctx=ctx,
            phase="setup",
            run_id=_RUN_ID,
            run_admitted=False,
        )

        # Now dispatch implementation with a DENYING guard -- it must not fire
        # because the run is admitted.
        deny_dispatcher = _dispatcher(story_dir, guard=_deny_guard())
        result = deny_dispatcher.dispatch(
            ctx=ctx,
            phase="implementation",
            run_id=_RUN_ID,
            run_admitted=True,
        )

        assert result.dispatched is True
        assert result.status != "rejected"

    def test_guard_does_not_fire_on_resume(self, tmp_path: Path) -> None:
        """The guard does NOT fire on a same-phase resume (run already admitted)."""
        story_dir = tmp_path / "stories" / "AG3-700"
        story_dir.mkdir(parents=True)
        ctx = _exploration_ctx(story_dir)
        permissive = _dispatcher(
            story_dir, overrides={"exploration": _PausingHandler()}
        )
        permissive.dispatch(
            ctx=ctx,
            phase="setup",
            run_id=_RUN_ID,
            run_admitted=False,
        )
        permissive.dispatch(
            ctx=ctx,
            phase="exploration",
            run_id=_RUN_ID,
            run_admitted=True,
        )

        deny = _dispatcher(
            story_dir,
            guard=_deny_guard(),
            overrides={"exploration": _PausingHandler()},
        )
        resumed = deny.dispatch(
            ctx=ctx,
            phase="exploration",
            run_id=_RUN_ID,
            run_admitted=True,
            detail={"resume_trigger": "design_approved"},
        )

        assert resumed.dispatched is True
        assert resumed.status != "rejected"


class TestStoryTypeSwitch:
    def test_bugfix_never_offers_exploration(self, tmp_path: Path) -> None:
        """Execution-mode bugfix advances setup -> implementation (no exploration)."""
        story_dir = tmp_path / "stories" / "AG3-700"
        story_dir.mkdir(parents=True)
        ctx = _ctx(story_dir, story_type=StoryType.BUGFIX)
        dispatcher = _dispatcher(story_dir)

        result = dispatcher.dispatch(
            ctx=ctx,
            phase="setup",
            run_id=_RUN_ID,
            run_admitted=False,
        )

        assert result.next_phase == "implementation"

    @pytest.mark.parametrize(
        "story_type",
        [StoryType.IMPLEMENTATION, StoryType.BUGFIX],
    )
    def test_implementation_and_bugfix_exploration_mode_enter_exploration(
        self,
        tmp_path: Path,
        story_type: StoryType,
    ) -> None:
        """AC5 correction: implementation and bugfix exploration routes admit."""
        story_dir = tmp_path / f"stories/{story_type.value}" / "AG3-700"
        story_dir.mkdir(parents=True)
        ctx = _ctx(
            story_dir,
            story_type=story_type,
            execution_route=StoryMode.EXPLORATION,
        )
        spy = _SpyExplorationHandler()
        dispatcher = _dispatcher(story_dir, overrides={"exploration": spy})
        dispatcher.dispatch(
            ctx=ctx,
            phase="setup",
            run_id=_RUN_ID,
            run_admitted=False,
        )

        result = dispatcher.dispatch(
            ctx=ctx,
            phase="exploration",
            run_id=_RUN_ID,
            run_admitted=True,
        )

        assert result.dispatched is True
        assert result.status == "phase_completed"
        assert spy.entered is True

    @pytest.mark.parametrize(
        "story_type",
        [StoryType.CONCEPT, StoryType.RESEARCH],
    )
    def test_concept_and_research_reject_setup_to_exploration(
        self,
        tmp_path: Path,
        story_type: StoryType,
    ) -> None:
        """AC5 correction: non-implementation workflows reject exploration entry."""
        story_dir = tmp_path / f"stories/{story_type.value}" / "AG3-700"
        story_dir.mkdir(parents=True)
        ctx = _ctx(story_dir, story_type=story_type, execution_route=None)
        spy = _SpyExplorationHandler()
        dispatcher = _dispatcher(story_dir, overrides={"exploration": spy})
        dispatcher.dispatch(
            ctx=ctx,
            phase="setup",
            run_id=_RUN_ID,
            run_admitted=False,
        )

        result = dispatcher.dispatch(
            ctx=ctx,
            phase="exploration",
            run_id=_RUN_ID,
            run_admitted=True,
        )

        assert result.status == "rejected"
        assert result.dispatched is False
        assert result.reaction == "rejected"
        assert "not a workflow edge" in (result.rejection_reason or "")
        assert spy.entered is False


class _SpyExplorationHandler:
    """A handler that records whether the exploration phase was ever entered."""

    def __init__(self) -> None:
        self.entered = False

    def on_enter(
        self, ctx: StoryContext, envelope: PhaseEnvelope
    ) -> HandlerResult:
        del ctx, envelope
        self.entered = True
        return HandlerResult(status=PhaseStatus.COMPLETED)

    def on_exit(self, ctx: StoryContext, envelope: PhaseEnvelope) -> None:
        del ctx, envelope

    def on_resume(
        self, ctx: StoryContext, envelope: PhaseEnvelope, trigger: str
    ) -> HandlerResult:
        del ctx, envelope, trigger
        return HandlerResult(status=PhaseStatus.COMPLETED)


class _CountingSetupHandler:
    """Records how many times its ``on_enter`` ran (E5 re-entry probe)."""

    def __init__(self, *, status: PhaseStatus = PhaseStatus.COMPLETED) -> None:
        self.enter_calls = 0
        self._status = status

    def on_enter(
        self, ctx: StoryContext, envelope: PhaseEnvelope
    ) -> HandlerResult:
        del ctx, envelope
        self.enter_calls += 1
        return HandlerResult(status=self._status)

    def on_exit(self, ctx: StoryContext, envelope: PhaseEnvelope) -> None:
        del ctx, envelope

    def on_resume(
        self, ctx: StoryContext, envelope: PhaseEnvelope, trigger: str
    ) -> HandlerResult:
        del ctx, envelope, trigger
        return HandlerResult(status=PhaseStatus.COMPLETED)


class TestSamePhaseReentry:
    """E5 (FK-45 §45.2): a same-phase non-PAUSED re-entry must NOT re-run on_enter."""

    def test_completed_setup_restart_is_rejected_and_not_reentered(
        self, tmp_path: Path
    ) -> None:
        """A duplicate setup start after setup COMPLETED rejects, no re-execution."""
        story_dir = tmp_path / "stories" / "AG3-700"
        story_dir.mkdir(parents=True)
        ctx = _ctx(story_dir)
        handler = _CountingSetupHandler()
        dispatcher = _dispatcher(story_dir, overrides={"setup": handler})

        first = dispatcher.dispatch(
            ctx=ctx,
            phase="setup",
            run_id=_RUN_ID,
            run_admitted=False,
        )
        assert first.status == "phase_completed"
        assert handler.enter_calls == 1

        # The run is now admitted; a duplicate setup start is NOT re-guarded but is
        # rejected by the E5 same-phase already-completed rule (not re-executed).
        second = dispatcher.dispatch(
            ctx=ctx,
            phase="setup",
            run_id=_RUN_ID,
            run_admitted=True,
        )

        assert second.status == "rejected"
        assert second.dispatched is False
        assert "already completed" in (second.rejection_reason or "")
        # The handler's on_enter was NOT run a second time (no stale re-execution).
        assert handler.enter_calls == 1

    def test_escalated_implementation_restart_is_rejected_and_not_reentered(
        self, tmp_path: Path
    ) -> None:
        """A same-phase start of an ESCALATED phase rejects fail-closed (no re-run)."""
        story_dir = tmp_path / "stories" / "AG3-700"
        story_dir.mkdir(parents=True)
        ctx = _ctx(story_dir)
        impl = _EscalatingHandler()
        dispatcher = _dispatcher(story_dir, overrides={"implementation": impl})
        dispatcher.dispatch(
            ctx=ctx,
            phase="setup",
            run_id=_RUN_ID,
            run_admitted=False,
        )
        escalated = dispatcher.dispatch(
            ctx=ctx,
            phase="implementation",
            run_id=_RUN_ID,
            run_admitted=True,
        )
        assert escalated.status == "escalated"

        # Wrap the implementation handler in a counting probe for the re-entry.
        counting = _CountingSetupHandler()
        reentry_dispatcher = _dispatcher(
            story_dir, overrides={"implementation": counting}
        )
        result = reentry_dispatcher.dispatch(
            ctx=ctx,
            phase="implementation",
            run_id=_RUN_ID,
            run_admitted=True,
        )

        assert result.status == "rejected"
        assert result.dispatched is False
        assert "escalated" in (result.rejection_reason or "")
        # The re-entry handler was never entered (no on_enter on stale state).
        assert counting.enter_calls == 0


class TestTransitionGuardEnforcement:
    """ERROR-3 (FK-45 §45.2): the transition edge GUARD is enforced, not skipped."""

    def test_execution_story_cannot_enter_exploration(self, tmp_path: Path) -> None:
        """An execution-route story is REJECTED on exploration (exploration-skip).

        The ``setup -> exploration`` edge EXISTS in the implementation workflow but
        is guarded by ``mode_is_exploration``; an execution-route story must not be
        able to complete setup and then ENTER exploration. The dispatch evaluates
        the edge guard and rejects fail-closed -- the exploration handler is never
        entered.
        """
        story_dir = tmp_path / "stories" / "AG3-700"
        story_dir.mkdir(parents=True)
        ctx = _ctx(story_dir)  # execution_route=EXECUTION (not exploration)
        spy = _SpyExplorationHandler()
        dispatcher = _dispatcher(story_dir, overrides={"exploration": spy})
        dispatcher.dispatch(
            ctx=ctx,
            phase="setup",
            run_id=_RUN_ID,
            run_admitted=False,
        )

        result = dispatcher.dispatch(
            ctx=ctx,
            phase="exploration",
            run_id=_RUN_ID,
            run_admitted=True,
        )

        assert result.status == "rejected"
        assert result.dispatched is False
        assert result.reaction == "rejected"
        # W9/#7: the engine would select the FIRST-passing outgoing edge from
        # setup -- for an execution-route story that is setup -> implementation
        # (guard _mode_is_not_exploration), NOT setup -> exploration. The dispatch
        # mirrors that selection and rejects the exploration request because the
        # engine's first-passing edge targets a DIFFERENT phase.
        reason = result.rejection_reason or ""
        assert "first-passing edge to 'implementation'" in reason
        assert "not the requested phase 'exploration'" in reason
        assert spy.entered is False, "exploration handler must never be entered"

    def test_two_edges_same_target_first_passing_admits(
        self, tmp_path: Path
    ) -> None:
        """W9 (FK-45 §45.2): two edges to ONE target -- the first-passing one admits.

        Mirrors the engine's ``_evaluate_transitions`` (which returns the FIRST
        outgoing edge whose guard passes). Two ``setup -> implementation`` edges,
        a FIRST (priority 10) whose guard FAILS and a SECOND (priority 5) whose
        guard PASSES: the engine selects the second, which targets implementation,
        so the requested implementation transition is ADMITTED.
        """
        from agentkit.backend.process.language.guards import GuardResult
        from agentkit.backend.process.language.model import (
            EdgeRule,
            FlowDefinition,
            NodeDefinition,
        )
        story_dir = tmp_path / "stories" / "AG3-700"
        story_dir.mkdir(parents=True)
        ctx = _ctx(story_dir)

        def _failing_guard(c: StoryContext, s: PhaseState) -> GuardResult:
            del c, s
            return GuardResult.fail(reason="first edge guard fails")

        def _passing_guard(c: StoryContext, s: PhaseState) -> GuardResult:
            del c, s
            return GuardResult.pass_()

        workflow = FlowDefinition(
            flow_id="two-edge-test",
            nodes=(
                NodeDefinition(name="setup"),
                NodeDefinition(name="implementation"),
            ),
            edges=(
                EdgeRule(
                    source="setup",
                    target="implementation",
                    guard=_failing_guard,
                    priority=10,
                ),
                EdgeRule(
                    source="setup",
                    target="implementation",
                    guard=_passing_guard,
                    priority=5,
                ),
            ),
        )
        completed_setup = make_phase_state(
            story_id=ctx.story_id,
            phase="setup",
            status=PhaseStatus.COMPLETED,
        )

        rejection = _enforce_transition(
            workflow, ctx, completed_setup, "implementation"
        )

        assert rejection is None, (
            "the first-passing edge targets implementation, so it must admit"
        )

    def test_first_passing_edge_to_different_phase_rejects_requested(
        self, tmp_path: Path
    ) -> None:
        """W9/#7 (FK-45 §45.2): requested phase rejected when engine picks another.

        The real divergence the dispatch must mirror: from ``setup`` there are two
        outgoing edges in priority order -- a FIRST (priority 10) to
        ``exploration`` whose guard PASSES, and a SECOND (priority 5) to
        ``implementation`` (unguarded). The engine's ``_evaluate_transitions``
        selects the FIRST passing edge -> ``exploration``. A request for
        ``implementation`` must therefore be REJECTED: admitting whenever ANY edge
        to the requested target passes would wrongly admit ``implementation`` even
        though the engine would have entered ``exploration`` instead.
        """
        from agentkit.backend.process.language.guards import GuardResult
        from agentkit.backend.process.language.model import (
            EdgeRule,
            FlowDefinition,
            NodeDefinition,
        )
        story_dir = tmp_path / "stories" / "AG3-700"
        story_dir.mkdir(parents=True)
        ctx = _ctx(story_dir)

        def _passing_guard(c: StoryContext, s: PhaseState) -> GuardResult:
            del c, s
            return GuardResult.pass_()

        workflow = FlowDefinition(
            flow_id="diverging-edge-test",
            nodes=(
                NodeDefinition(name="setup"),
                NodeDefinition(name="exploration"),
                NodeDefinition(name="implementation"),
            ),
            edges=(
                # FIRST in priority order: a PASSING guard to exploration.
                EdgeRule(
                    source="setup",
                    target="exploration",
                    guard=_passing_guard,
                    priority=10,
                ),
                # SECOND: an unguarded (would-pass) edge to implementation.
                EdgeRule(
                    source="setup",
                    target="implementation",
                    guard=None,
                    priority=5,
                ),
            ),
        )
        completed_setup = make_phase_state(
            story_id=ctx.story_id,
            phase="setup",
            status=PhaseStatus.COMPLETED,
        )

        # Requesting implementation: the engine would select exploration first.
        rejection = _enforce_transition(
            workflow, ctx, completed_setup, "implementation"
        )
        assert rejection is not None, (
            "the engine selects the first-passing edge (exploration), so the "
            "implementation request must be rejected"
        )
        assert "first-passing edge to 'exploration'" in rejection
        assert "not the requested phase 'implementation'" in rejection

        # Requesting exploration (what the engine WOULD select): admitted.
        admit = _enforce_transition(
            workflow, ctx, completed_setup, "exploration"
        )
        assert admit is None, (
            "the engine's first-passing edge targets exploration, so an "
            "exploration request must be admitted"
        )

    def test_all_edges_fail_rejects(self, tmp_path: Path) -> None:
        """W9: when EVERY edge to the target fails its guard, the transition rejects."""
        from agentkit.backend.process.language.guards import GuardResult
        from agentkit.backend.process.language.model import (
            EdgeRule,
            FlowDefinition,
            NodeDefinition,
        )
        story_dir = tmp_path / "stories" / "AG3-700"
        story_dir.mkdir(parents=True)
        ctx = _ctx(story_dir)

        def _failing_guard(c: StoryContext, s: PhaseState) -> GuardResult:
            del c, s
            return GuardResult.fail(reason="closed")

        workflow = FlowDefinition(
            flow_id="all-fail-test",
            nodes=(
                NodeDefinition(name="setup"),
                NodeDefinition(name="implementation"),
            ),
            edges=(
                EdgeRule(
                    source="setup",
                    target="implementation",
                    guard=_failing_guard,
                ),
            ),
        )
        completed_setup = make_phase_state(
            story_id=ctx.story_id,
            phase="setup",
            status=PhaseStatus.COMPLETED,
        )

        rejection = _enforce_transition(
            workflow, ctx, completed_setup, "implementation"
        )

        assert rejection is not None
        assert "no outgoing transition guard is satisfied" in rejection

    def test_exploration_story_may_enter_exploration(self, tmp_path: Path) -> None:
        """The exploration-mode positive path stays green (guard satisfied)."""
        story_dir = tmp_path / "stories" / "AG3-700"
        story_dir.mkdir(parents=True)
        ctx = _exploration_ctx(story_dir)  # execution_route=EXPLORATION
        spy = _SpyExplorationHandler()
        dispatcher = _dispatcher(story_dir, overrides={"exploration": spy})
        dispatcher.dispatch(
            ctx=ctx,
            phase="setup",
            run_id=_RUN_ID,
            run_admitted=False,
        )

        result = dispatcher.dispatch(
            ctx=ctx,
            phase="exploration",
            run_id=_RUN_ID,
            run_admitted=True,
        )

        assert result.status == "phase_completed"
        assert result.dispatched is True
        assert spy.entered is True


class TestRunScopedAdmissionGate:
    """AG3-054 ERROR-1: the fresh-setup / first-call gate is RUN-scoped.

    The reset-escalation hazard: a story's OLD run leaves setup phase-state under
    the per-story ``story_dir``; a NEW run (new run id) reuses that same story_dir.
    The admission gate must NOT derive "fresh" from the OLD run's story-scoped
    phase-state -- a NEW, un-admitted run's setup must still be classified FRESH so
    the fail-closed Approved+READY pre-start guard fires (the fail-open this fix
    closes). Story-scoped phase-state only drives the engine's transition/resume
    mechanics, never the admission decision.
    """

    def test_new_unadmitted_run_setup_is_fresh_despite_old_run_state(
        self, tmp_path: Path
    ) -> None:
        """Old run's setup state present + run NOT admitted -> FRESH -> guard fires.

        Drives the EXACT reachable scenario: setup phase-state from a prior run is
        persisted under the per-story story_dir, then a new run posts setup while
        NOT Approved/READY and with NO run-matched admission evidence
        (``run_admitted=False``). The dispatch must classify it FRESH so the DENY
        guard FIRES and the start is REJECTED -- the old phase-state must NOT make
        it "not fresh". No phase is dispatched (no materialization).
        """
        story_dir = tmp_path / "stories" / "AG3-700"
        story_dir.mkdir(parents=True)
        ctx = _ctx(story_dir)

        # An OLD run fully ran setup, leaving setup phase-state under story_dir.
        old_run = _dispatcher(story_dir)
        old = old_run.dispatch(
            ctx=ctx,
            phase="setup",
            run_id="run-OLD",
            run_admitted=False,
        )
        assert old.status == "phase_completed"
        # Probe: the story-scoped setup phase-state IS persisted (the prior run's).
        from agentkit.backend.control_plane.dispatch import _load_phase_state
        from agentkit.backend.process.language.definitions import resolve_workflow

        phase_names = tuple(resolve_workflow(ctx.story_type).phase_names)
        persisted = _load_phase_state(ctx, story_dir, phase_names)
        assert persisted is not None, "the old run left story-scoped phase-state"

        # A NEW run posts setup, NOT admitted, with a DENY guard. It MUST be FRESH
        # (guard fires) -- the old run's phase-state must not bypass the guard.
        new_run = _dispatcher(story_dir, guard=_deny_guard())
        result = new_run.dispatch(
            ctx=ctx,
            phase="setup",
            run_id="run-NEW",
            run_admitted=False,
        )

        assert result.status == "rejected", (
            "a NEW un-admitted run's setup is FRESH despite the old run's "
            "story-scoped phase-state; the pre-start guard MUST fire"
        )
        assert result.dispatched is False
        assert "Approved" in (result.rejection_reason or "")

    def test_admitted_run_is_not_re_guarded(self, tmp_path: Path) -> None:
        """A legitimately admitted run (run_admitted=True) is NOT re-guarded.

        Even a DENY guard must not reject an already-admitted in-flight run's setup
        -- the run passed admission once and is not re-evaluated. (Here the same run
        re-enters setup before it completed, so the engine path runs.)
        """
        story_dir = tmp_path / "stories" / "AG3-700"
        story_dir.mkdir(parents=True)
        ctx = _ctx(story_dir)

        dispatcher = _dispatcher(story_dir, guard=_deny_guard())
        result = dispatcher.dispatch(
            ctx=ctx,
            phase="setup",
            run_id="run-NEW",
            run_admitted=True,
        )

        # The DENY guard did NOT fire (run admitted) -> the setup phase dispatched.
        assert result.dispatched is True
        assert result.status != "rejected"

    def test_new_unadmitted_run_cannot_jump_to_implementation(
        self, tmp_path: Path
    ) -> None:
        """First-call run-scoped: a NEW un-admitted run cannot ride sibling state.

        An OLD run advanced through setup (and into implementation), leaving
        story-scoped phase-state under the shared story_dir. A NEW, un-admitted run
        (``run_admitted=False``) posting ``/phases/implementation/start`` must be
        REJECTED (first call must be setup) -- it must NOT be admitted via the
        sibling run's story-scoped phase-state.
        """
        story_dir = tmp_path / "stories" / "AG3-700"
        story_dir.mkdir(parents=True)
        ctx = _ctx(story_dir)

        # OLD run: setup completes and implementation runs, leaving phase-state.
        old_run = _dispatcher(story_dir)
        old_run.dispatch(
            ctx=ctx,
            phase="setup",
            run_id="run-OLD",
            run_admitted=False,
        )
        old_impl = old_run.dispatch(
            ctx=ctx,
            phase="implementation",
            run_id="run-OLD",
            run_admitted=True,
        )
        assert old_impl.dispatched is True

        # NEW un-admitted run jumps straight to implementation -> rejected.
        new_run = _dispatcher(story_dir)
        result = new_run.dispatch(
            ctx=ctx,
            phase="implementation",
            run_id="run-NEW",
            run_admitted=False,
        )

        assert result.status == "rejected"
        assert result.dispatched is False
        assert "only 'setup' may start a fresh run" in (result.rejection_reason or "")


class _UnresolvableWorkspaceLocator:
    """A locator that always fails closed (AG3-123 AC3)."""

    def resolve(
        self, project_key: str, story_id: str, run_id: str
    ) -> StoryWorkspace:
        raise StoryWorkspaceUnresolvedError(
            "no project_registry entry (fail-closed)",
            detail={
                "project_key": project_key,
                "story_id": story_id,
                "run_id": run_id,
            },
        )


def _project_root_less_ctx(story_id: str = "AG3-700") -> StoryContext:
    """A run context carrying NO dev-local ``project_root`` (AG3-123)."""
    return StoryContext(
        project_key="test-project",
        story_id=story_id,
        story_type=StoryType.IMPLEMENTATION,
        execution_route=StoryMode.EXECUTION,
        project_root=None,
    )


class TestBackendResolvedWorkspace:
    """AG3-123 AC1/AC3: the FS anchor is Backend-resolved, never from ctx."""

    def test_dispatch_succeeds_with_backend_resolved_workspace_no_project_root(
        self, tmp_path: Path
    ) -> None:
        """AC1: dispatch succeeds with a Backend-resolved workspace and NO dev path.

        The run ``StoryContext`` carries ``project_root=None`` (the dev process
        supplies no canonical FS input); the injected locator resolves the
        workspace Backend-side. The setup phase still dispatches -- the decoupling
        is proven by the absence of any dev-local path parameter / ctx anchor.
        """
        story_dir = tmp_path / "stories" / "AG3-700"
        story_dir.mkdir(parents=True)
        ctx = _project_root_less_ctx()
        save_story_context(story_dir, ctx)
        dispatcher = _dispatcher(story_dir)

        result = dispatcher.dispatch(
            ctx=ctx,
            phase="setup",
            run_id=_RUN_ID,
            run_admitted=False,
        )

        assert result.dispatched is True
        assert result.phase == "setup"
        assert result.status == "phase_completed"

    def test_unresolvable_workspace_rejects_fail_closed(self) -> None:
        """AC3: an unresolvable workspace rejects fail-closed (no silent no-op)."""
        ctx = _project_root_less_ctx()
        dispatcher = PhaseDispatcher(
            workspace_locator=_UnresolvableWorkspaceLocator(),
            engine_factory=_engine_factory(),
            guard_factory=lambda workspace: _allow_guard(),
        )

        result = dispatcher.dispatch(
            ctx=ctx,
            phase="setup",
            run_id=_RUN_ID,
            run_admitted=False,
        )

        assert result.status == "rejected"
        assert result.dispatched is False
        assert "fail-closed" in (result.rejection_reason or "")

    def test_relative_registry_row_dispatch_normalizes_not_escapes(self) -> None:
        """AG3-123 r2 (MAJOR 2): a relative/corrupt registry row -> normalized reject.

        The PRODUCTIVE ``StateBackendStoryWorkspaceLocator`` decodes the row through
        the ``ProjectRegistration`` model; a legacy relative-root row makes that
        decode raise a pydantic ``ValidationError``. The locator converts it to
        ``StoryWorkspaceUnresolvedError`` (a ``PipelineError``), so the dispatcher
        normalizes it to a fail-closed rejection INSTEAD of letting the
        ``ValidationError`` ESCAPE the dispatch (the fail-OPEN crash this fix closes).
        """
        from pydantic import ValidationError

        from agentkit.backend.control_plane.workspace_locator import (
            StateBackendStoryWorkspaceLocator,
        )
        from agentkit.backend.installer.registration import (
            ProjectRegistration,
            RuntimeProfile,
        )

        class _RelativeRowLookup:
            """Reproduces the repository decode of a relative-root ``project_registry`` row."""

            def get(self, project_key: str) -> ProjectRegistration:
                from datetime import UTC, datetime
                from pathlib import Path

                return ProjectRegistration(
                    project_key=project_key,
                    project_root=Path("relative/legacy/root"),
                    github_owner="acme",
                    github_repo="demo",
                    runtime_profile=RuntimeProfile.CORE,
                    config_version="3.0",
                    config_digest="deadbeef",
                    registered_at=datetime.now(tz=UTC),
                )

        ctx = _project_root_less_ctx()
        dispatcher = PhaseDispatcher(
            workspace_locator=StateBackendStoryWorkspaceLocator(
                registration_lookup=_RelativeRowLookup()
            ),
            engine_factory=_engine_factory(),
            guard_factory=lambda workspace: _allow_guard(),
        )

        # No escaping ValidationError -- a normalized fail-closed rejection.
        try:
            result = dispatcher.dispatch(
                ctx=ctx,
                phase="setup",
                run_id=_RUN_ID,
                run_admitted=False,
            )
        except ValidationError as exc:  # pragma: no cover - the regression we close
            pytest.fail(f"ValidationError escaped the dispatch (fail-open): {exc}")

        assert result.status == "rejected"
        assert result.dispatched is False
        assert "fail-closed" in (result.rejection_reason or "")
