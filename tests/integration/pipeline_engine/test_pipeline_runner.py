"""Integration tests for the AgentKit pipeline runner.

These tests verify the runner's orchestration logic:
1. Install AgentKit into a simulated target project
2. Create a story context (manually -- acceptable for integration level)
3. Run the pipeline through all phases using NoOpHandler
4. Verify artifacts, state, and workflow topology

Note: These tests use NoOpHandler for all phases, which means they
test the runner/engine orchestration, NOT the real production path.
For real E2E tests that exercise actual handlers, see
``tests/e2e/smoke/test_real_pipeline.py``.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import pytest

from agentkit.bootstrap.composition_root import build_exploration_phase_handler
from agentkit.config.loader import load_project_config
from agentkit.exceptions import PipelineError
from agentkit.installer import InstallConfig, install_agentkit
from agentkit.installer.paths import story_dir
from agentkit.pipeline_engine.lifecycle import (
    HandlerResult,
    NoOpHandler,
    PhaseHandlerRegistry,
)
from agentkit.pipeline_engine.runner import PipelineRunResult, run_pipeline
from agentkit.process.language.definitions import (
    BUGFIX_WORKFLOW,
    IMPLEMENTATION_WORKFLOW,
    RESEARCH_WORKFLOW,
    resolve_workflow,
)
from agentkit.state_backend.store import (
    load_attempts,
    read_phase_snapshot_record,
    read_phase_state_record,
    read_story_context_record,
    save_story_context,
)
from agentkit.story_context_manager.models import (
    PhaseStatus,
    StoryContext,
)
from agentkit.story_context_manager.types import StoryMode, StoryType

if TYPE_CHECKING:
    from pathlib import Path

    from agentkit.pipeline_engine.phase_envelope.envelope import PhaseEnvelope


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _setup_story(
    project_dir: Path,
    story_id: str,
    story_type: StoryType,
    mode: StoryMode | None,
) -> tuple[StoryContext, Path]:
    """Create a story context and persist it to the story directory.

    Returns:
        Tuple of (StoryContext, story_dir path).
    """
    s_dir = story_dir(project_dir, story_id)
    s_dir.mkdir(parents=True, exist_ok=True)
    ctx = StoryContext(
        project_key=project_dir.parent.name,
        story_id=story_id,
        story_type=story_type,
        execution_route=mode,
        project_root=project_dir,
    )
    save_story_context(s_dir, ctx)
    return ctx, s_dir


def _install_project(project_dir: Path) -> None:
    # AG3-051: un-gated. The host-independent install path binds skills via a
    # Windows directory junction / POSIX symlink (FK-43 §43.4.1.1), and the
    # per-test ``postgres_isolated_schema`` fixture (attached by the integration
    # conftest) TRUNCATEs the test schema so fixed story ids no longer collide.
    install_result = install_agentkit(
        InstallConfig(
            project_key=project_dir.name,
            project_name=project_dir.name,
            project_root=project_dir,
            # AG3-039 R6: CP 7 github coordinates are MANDATORY (fail-closed).
            github_owner="acme",
            github_repo="demo",
            # AG3-052: scaffold default is available:true (FK-03 §3); no live
            # Sonar in CI => conscious opt-out so the completing CP 10d SKIPs.
            sonarqube_available=False,
            # AG3-056 (FIX-5): no live Jenkins in CI => conscious opt-out so the
            # CI preflight SKIPS.
            ci_available=False,
        )
    )
    assert install_result.success


def _registry_for_workflow(
    workflow_def: object,
) -> PhaseHandlerRegistry:
    """Build a PhaseHandlerRegistry with NoOpHandler for all phases in a workflow."""
    from agentkit.process.language.model import WorkflowDefinition

    assert isinstance(workflow_def, WorkflowDefinition)
    registry = PhaseHandlerRegistry()
    for name in workflow_def.phase_names:
        registry.register(name, NoOpHandler())
    return registry


def _exploration_registry_for_workflow(
    workflow_def: object,
    story_dir_path: Path,
) -> PhaseHandlerRegistry:
    """Like ``_registry_for_workflow`` but with the REAL ExplorationPhaseHandler.

    Option Y (AG3-045, PO 2026-06-05): no fake-approve stub. The exploration
    slot runs the productive :class:`ExplorationPhaseHandler` wired via
    ``build_exploration_phase_handler`` over the SAME state backend the runner
    uses. Without a worker-produced change-frame (AG3-055) the handler is
    honestly fail-closed: it ESCALATES (it does NOT fabricate a draft and does
    NOT fake an APPROVED). The engine persists the run-bound ``FlowExecution``
    (status IN_PROGRESS) BEFORE calling ``on_enter``, which is exactly how the
    handler resolves its run id in production; this test relies on that real
    ordering, not a seeded run id.
    """
    registry = _registry_for_workflow(workflow_def)
    registry.register(
        "exploration", build_exploration_phase_handler(story_dir_path)
    )
    return registry


# ---------------------------------------------------------------------------
# Implementation Story Smoke Tests
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestSmokeImplementationStory:
    """Smoke test: Implementation story — full pipeline with real workflow."""

    def test_full_pipeline_completes(self, tmp_path: Path) -> None:
        """Implementation story in EXECUTION mode completes all phases."""
        # 1. Install AgentKit
        project_dir = tmp_path / "my-project"
        project_dir.mkdir()
        _install_project(project_dir)

        # 2. Verify install created loadable config
        config = load_project_config(project_dir)
        assert config.project_name == "my-project"

        # 3. Create story
        ctx, s_dir = _setup_story(
            project_dir,
            "TEST-001",
            StoryType.IMPLEMENTATION,
            StoryMode.EXECUTION,
        )

        # 4. Use real IMPLEMENTATION_WORKFLOW
        workflow = IMPLEMENTATION_WORKFLOW
        registry = _registry_for_workflow(workflow)

        # 5. Run pipeline
        result = run_pipeline(ctx, s_dir, registry, workflow)

        # 6. Verify completion — EXECUTION mode skips exploration
        assert result.final_status == "completed"
        assert result.final_phase == "closure"
        assert result.phases_executed == (
            "setup",
            "implementation",
            "closure",
        )

        # 7. Verify canonical persisted records and optional projections
        assert read_phase_state_record(s_dir) is not None
        assert read_phase_snapshot_record(s_dir, "setup") is not None
        assert read_phase_snapshot_record(s_dir, "closure") is not None
        assert (s_dir / "phase-state.json").exists()
        assert (s_dir / "context.json").exists()
        assert len(load_attempts(s_dir, "setup")) >= 1
        assert len(load_attempts(s_dir, "closure")) >= 1

    def test_execution_mode_skips_exploration(self, tmp_path: Path) -> None:
        """EXECUTION mode uses transition guard to skip exploration."""
        project_dir = tmp_path / "proj"
        project_dir.mkdir()
        _install_project(project_dir)

        ctx, s_dir = _setup_story(
            project_dir,
            "TEST-002",
            StoryType.IMPLEMENTATION,
            StoryMode.EXECUTION,
        )

        workflow = IMPLEMENTATION_WORKFLOW
        registry = _registry_for_workflow(workflow)
        result = run_pipeline(ctx, s_dir, registry, workflow)

        assert result.final_status == "completed"
        assert "exploration" not in result.phases_executed
        assert "setup" in result.phases_executed
        assert "implementation" in result.phases_executed
        assert "closure" in result.phases_executed

    def test_implementation_routes_to_closure_without_remediation(
        self,
        tmp_path: Path,
    ) -> None:
        """When implementation completes, the guarded closure transition wins."""
        project_dir = tmp_path / "proj"
        project_dir.mkdir()
        _install_project(project_dir)

        ctx, s_dir = _setup_story(
            project_dir,
            "TEST-003",
            StoryType.IMPLEMENTATION,
            StoryMode.EXECUTION,
        )

        workflow = IMPLEMENTATION_WORKFLOW
        registry = _registry_for_workflow(workflow)
        result = run_pipeline(ctx, s_dir, registry, workflow)

        assert result.final_status == "completed"
        # Each phase appears exactly once — no remediation loop
        assert result.phases_executed.count("implementation") == 1

    def test_projection_files_are_valid_json(self, tmp_path: Path) -> None:
        """Projection files remain valid JSON alongside canonical DB records."""
        project_dir = tmp_path / "proj"
        project_dir.mkdir()
        _install_project(project_dir)

        ctx, s_dir = _setup_story(
            project_dir,
            "TEST-004",
            StoryType.IMPLEMENTATION,
            StoryMode.EXECUTION,
        )

        workflow = IMPLEMENTATION_WORKFLOW
        registry = _registry_for_workflow(workflow)
        run_pipeline(ctx, s_dir, registry, workflow)

        assert read_phase_state_record(s_dir) is not None
        assert read_phase_snapshot_record(s_dir, "setup") is not None
        assert read_phase_snapshot_record(s_dir, "implementation") is not None
        assert read_phase_snapshot_record(s_dir, "closure") is not None

        # Projections are not canonical, but they should still be parseable.
        json_files = list(s_dir.rglob("*.json"))
        assert len(json_files) > 0, "No JSON files produced"

        for json_file in json_files:
            content = json_file.read_text(encoding="utf-8")
            parsed = json.loads(content)
            assert isinstance(parsed, dict), f"{json_file.name} is not a JSON object"

    def test_attempt_records_created_per_phase(self, tmp_path: Path) -> None:
        """Each phase creates canonical attempt records."""
        project_dir = tmp_path / "proj"
        project_dir.mkdir()
        _install_project(project_dir)

        ctx, s_dir = _setup_story(
            project_dir,
            "TEST-005",
            StoryType.IMPLEMENTATION,
            StoryMode.EXECUTION,
        )

        workflow = IMPLEMENTATION_WORKFLOW
        registry = _registry_for_workflow(workflow)
        result = run_pipeline(ctx, s_dir, registry, workflow)

        assert result.final_status == "completed"

        # Every executed phase should have canonical attempt records.
        for phase_name in result.phases_executed:
            attempts = load_attempts(s_dir, phase_name)
            assert len(attempts) >= 1, f"No canonical attempts for phase '{phase_name}'"
            for attempt in attempts:
                assert attempt.run_id, f"attempt.run_id is empty for phase '{phase_name}'"
                assert attempt.phase == phase_name


# ---------------------------------------------------------------------------
# Exploration Mode Smoke Tests
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestSmokeExplorationMode:
    """Smoke test: Implementation story with EXPLORATION mode (Option Y).

    AG3-045 delivers only the deterministic plumbing; the content drafting is
    AG3-055 and the gate review is AG3-046. With no worker-produced change-frame
    the real handler is honestly fail-closed: the pipeline ESCALATES at the
    exploration phase instead of fake-completing to closure. The 4-phase
    completion path is pending AG3-055 (drafting) + AG3-046 (review).
    """

    def test_exploration_mode_escalates_without_change_frame(
        self,
        tmp_path: Path,
    ) -> None:
        """EXPLORATION mode stops at exploration fail-closed (pending AG3-055)."""
        project_dir = tmp_path / "proj"
        project_dir.mkdir()
        _install_project(project_dir)

        ctx, s_dir = _setup_story(
            project_dir,
            "EXPL-001",
            StoryType.IMPLEMENTATION,
            StoryMode.EXPLORATION,
        )

        workflow = IMPLEMENTATION_WORKFLOW
        registry = _exploration_registry_for_workflow(workflow, s_dir)

        result = run_pipeline(ctx, s_dir, registry, workflow)

        # Honest fail-closed: no fake-approve, no silent completion to closure.
        assert result.final_status == "escalated"
        assert result.final_phase == "exploration"
        assert result.phases_executed == ("setup", "exploration")
        assert "closure" not in result.phases_executed

    def test_exploration_mode_records_exploration_attempt(
        self,
        tmp_path: Path,
    ) -> None:
        """EXPLORATION mode still records a canonical exploration attempt."""
        project_dir = tmp_path / "proj"
        project_dir.mkdir()
        _install_project(project_dir)

        ctx, s_dir = _setup_story(
            project_dir,
            "EXPL-002",
            StoryType.IMPLEMENTATION,
            StoryMode.EXPLORATION,
        )

        workflow = IMPLEMENTATION_WORKFLOW
        registry = _exploration_registry_for_workflow(workflow, s_dir)
        result = run_pipeline(ctx, s_dir, registry, workflow)

        assert result.final_status == "escalated"
        assert len(load_attempts(s_dir, "exploration")) >= 1
        # No pseudo-draft is fabricated: no change_frame.json is written by
        # the handler (the worker AG3-055 would write it; it is absent here).
        change_frame = (
            project_dir / "_temp" / "qa" / "EXPL-002" / "change_frame.json"
        )
        assert not change_frame.exists()


# ---------------------------------------------------------------------------
# Bugfix Story Smoke Tests
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestSmokeBugfixStory:
    """Smoke test: Bugfix story (no exploration, no mode routing)."""

    def test_full_pipeline_completes(self, tmp_path: Path) -> None:
        """Bugfix story runs setup -> implementation -> closure."""
        project_dir = tmp_path / "proj"
        project_dir.mkdir()
        _install_project(project_dir)

        ctx, s_dir = _setup_story(
            project_dir,
            "BUG-001",
            StoryType.BUGFIX,
            StoryMode.EXECUTION,
        )

        workflow = BUGFIX_WORKFLOW
        registry = _registry_for_workflow(workflow)

        result = run_pipeline(ctx, s_dir, registry, workflow)

        assert result.final_status == "completed"
        assert result.final_phase == "closure"
        assert result.phases_executed == (
            "setup",
            "implementation",
            "closure",
        )

    def test_bugfix_skips_exploration(self, tmp_path: Path) -> None:
        """Bugfix workflow never touches exploration phase."""
        project_dir = tmp_path / "proj"
        project_dir.mkdir()
        _install_project(project_dir)

        ctx, s_dir = _setup_story(
            project_dir,
            "BUG-002",
            StoryType.BUGFIX,
            StoryMode.EXECUTION,
        )

        workflow = BUGFIX_WORKFLOW
        registry = _registry_for_workflow(workflow)

        result = run_pipeline(ctx, s_dir, registry, workflow)

        # Exploration must never appear
        assert "exploration" not in result.phases_executed
        # Setup and implementation must appear
        assert "setup" in result.phases_executed
        assert "implementation" in result.phases_executed

    def test_bugfix_workflow_has_no_exploration_phase(self) -> None:
        """BUGFIX_WORKFLOW does not define an exploration phase."""
        assert "exploration" not in BUGFIX_WORKFLOW.phase_names


# ---------------------------------------------------------------------------
# Concept Story Smoke Tests
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestSmokeConceptStory:
    """Smoke test: Concept story (no worktree, no full QA)."""

    def test_full_pipeline_completes(self, tmp_path: Path) -> None:
        """Concept story runs setup -> implementation -> closure."""
        project_dir = tmp_path / "proj"
        project_dir.mkdir()
        _install_project(project_dir)

        ctx, s_dir = _setup_story(
            project_dir,
            "CONCEPT-001",
            StoryType.CONCEPT,
            None,
        )

        workflow = resolve_workflow(StoryType.CONCEPT)
        registry = _registry_for_workflow(workflow)

        result = run_pipeline(ctx, s_dir, registry, workflow)

        assert result.final_status == "completed"
        assert result.final_phase == "closure"
        assert result.phases_executed == (
            "setup",
            "implementation",
            "closure",
        )

    def test_concept_story_context_persisted(self, tmp_path: Path) -> None:
        """Story context is loadable after pipeline completion."""
        project_dir = tmp_path / "proj"
        project_dir.mkdir()
        _install_project(project_dir)

        ctx, s_dir = _setup_story(
            project_dir,
            "CONCEPT-002",
            StoryType.CONCEPT,
            None,
        )

        workflow = resolve_workflow(StoryType.CONCEPT)
        registry = _registry_for_workflow(workflow)
        run_pipeline(ctx, s_dir, registry, workflow)

        loaded = read_story_context_record(s_dir)
        assert loaded is not None
        assert loaded.story_id == "CONCEPT-002"
        assert loaded.story_type == StoryType.CONCEPT


# ---------------------------------------------------------------------------
# Research Story Smoke Tests
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestSmokeResearchStory:
    """Smoke test: Research story (minimal pipeline, no verify)."""

    def test_full_pipeline_completes(self, tmp_path: Path) -> None:
        """Research story runs setup -> implementation -> closure."""
        project_dir = tmp_path / "proj"
        project_dir.mkdir()
        _install_project(project_dir)

        ctx, s_dir = _setup_story(
            project_dir,
            "RES-001",
            StoryType.RESEARCH,
            None,
        )

        workflow = resolve_workflow(StoryType.RESEARCH)
        registry = _registry_for_workflow(workflow)

        result = run_pipeline(ctx, s_dir, registry, workflow)

        assert result.final_status == "completed"
        assert result.final_phase == "closure"
        assert result.phases_executed == (
            "setup",
            "implementation",
            "closure",
        )

    def test_research_skips_verify(self, tmp_path: Path) -> None:
        """Research workflow has no verify phase."""
        project_dir = tmp_path / "proj"
        project_dir.mkdir()
        _install_project(project_dir)

        ctx, s_dir = _setup_story(
            project_dir,
            "RES-002",
            StoryType.RESEARCH,
            None,
        )

        workflow = resolve_workflow(StoryType.RESEARCH)
        registry = _registry_for_workflow(workflow)

        result = run_pipeline(ctx, s_dir, registry, workflow)

        assert "verify" not in result.phases_executed
        assert result.final_status == "completed"

    def test_research_workflow_has_no_verify_phase(self) -> None:
        """RESEARCH_WORKFLOW does not define a verify phase."""
        assert "verify" not in RESEARCH_WORKFLOW.phase_names


# ---------------------------------------------------------------------------
# Pipeline Robustness Tests (per testing-standards.md)
# ---------------------------------------------------------------------------


class _FailingHandler:
    """Handler that returns FAILED status with a message."""

    def __init__(self, error_msg: str = "Deliberate test failure") -> None:
        self._error_msg = error_msg

    def on_enter(
        self,
        ctx: StoryContext,
        envelope: PhaseEnvelope,
    ) -> HandlerResult:
        """Return FAILED status.

        Args:
            ctx: Story context (unused).
            envelope: Phase envelope (unused).

        Returns:
            HandlerResult with FAILED status.
        """
        return HandlerResult(
            status=PhaseStatus.FAILED,
            errors=(self._error_msg,),
        )

    def on_exit(self, ctx: StoryContext, envelope: PhaseEnvelope) -> None:
        """No-op exit.

        Args:
            ctx: Story context (unused).
            envelope: Phase envelope (unused).
        """

    def on_resume(
        self,
        ctx: StoryContext,
        envelope: PhaseEnvelope,
        trigger: str,
    ) -> HandlerResult:
        """Return FAILED status on resume.

        Args:
            ctx: Story context (unused).
            envelope: Phase envelope (unused).
            trigger: Resume trigger (unused).

        Returns:
            HandlerResult with FAILED status.
        """
        return HandlerResult(
            status=PhaseStatus.FAILED,
            errors=(self._error_msg,),
        )


class _YieldingHandler:
    """Handler that returns PAUSED status on first entry."""

    def __init__(self, yield_status: str = "awaiting_test") -> None:
        self._yield_status = yield_status

    def on_enter(
        self,
        ctx: StoryContext,
        envelope: PhaseEnvelope,
    ) -> HandlerResult:
        """Return PAUSED status.

        Args:
            ctx: Story context (unused).
            envelope: Phase envelope (unused).

        Returns:
            HandlerResult with PAUSED status.
        """
        return HandlerResult(
            status=PhaseStatus.PAUSED,
            yield_status=self._yield_status,
        )

    def on_exit(self, ctx: StoryContext, envelope: PhaseEnvelope) -> None:
        """No-op exit.

        Args:
            ctx: Story context (unused).
            envelope: Phase envelope (unused).
        """

    def on_resume(
        self,
        ctx: StoryContext,
        envelope: PhaseEnvelope,
        trigger: str,
    ) -> HandlerResult:
        """Return COMPLETED status on resume.

        Args:
            ctx: Story context (unused).
            envelope: Phase envelope (unused).
            trigger: Resume trigger (unused).

        Returns:
            HandlerResult with COMPLETED status.
        """
        return HandlerResult(status=PhaseStatus.COMPLETED)


@pytest.mark.integration
class TestSmokePipelineRobustness:
    """Pipeline robustness tests per testing-standards.md."""

    def test_missing_handler_for_phase(self, tmp_path: Path) -> None:
        """Pipeline fails clearly when a phase has no registered handler."""
        project_dir = tmp_path / "proj"
        project_dir.mkdir()
        _install_project(project_dir)

        ctx, s_dir = _setup_story(
            project_dir,
            "ROBUST-001",
            StoryType.RESEARCH,
            None,
        )

        workflow = resolve_workflow(StoryType.RESEARCH)

        # Register handlers for all phases EXCEPT implementation
        registry = PhaseHandlerRegistry()
        registry.register("setup", NoOpHandler())
        registry.register("closure", NoOpHandler())
        # Deliberately omit "implementation"

        with pytest.raises(PipelineError, match="No handler registered"):
            run_pipeline(ctx, s_dir, registry, workflow)

    def test_corrupt_projection_file_during_run(self, tmp_path: Path) -> None:
        """Corrupt projection JSON does not override canonical backend truth."""
        project_dir = tmp_path / "proj"
        project_dir.mkdir()
        _install_project(project_dir)

        ctx, s_dir = _setup_story(
            project_dir,
            "ROBUST-002",
            StoryType.RESEARCH,
            None,
        )

        # Write corrupt state file before running
        state_file = s_dir / "phase-state.json"
        state_file.write_text("{invalid json!@#$", encoding="utf-8")

        workflow = resolve_workflow(StoryType.RESEARCH)
        registry = _registry_for_workflow(workflow)

        result = run_pipeline(ctx, s_dir, registry, workflow)

        assert result.final_status == "completed"
        assert result.phases_executed == ("setup", "implementation", "closure")
        assert read_phase_state_record(s_dir) is not None

    def test_pipeline_with_yielding_handler(self, tmp_path: Path) -> None:
        """Pipeline correctly yields when a handler returns PAUSED."""
        project_dir = tmp_path / "proj"
        project_dir.mkdir()
        _install_project(project_dir)

        ctx, s_dir = _setup_story(
            project_dir,
            "ROBUST-003",
            StoryType.RESEARCH,
            None,
        )

        workflow = resolve_workflow(StoryType.RESEARCH)

        # Make implementation yield. Seit AG3-021 muss yield_status auf einen
        # normierten PauseReason mappen — verwende den Synonym-Wert
        # 'awaiting_design_review'.
        registry = PhaseHandlerRegistry()
        registry.register("setup", NoOpHandler())
        registry.register(
            "implementation", _YieldingHandler("awaiting_design_review"),
        )
        registry.register("closure", NoOpHandler())

        result = run_pipeline(ctx, s_dir, registry, workflow)

        assert result.final_status == "yielded"
        assert result.yielded is True
        assert result.yield_status == "awaiting_design_review"
        assert result.final_phase == "implementation"
        assert result.phases_executed == ("setup", "implementation")

        # Verify persisted state reflects the yield
        loaded_state = read_phase_state_record(s_dir)
        assert loaded_state is not None
        assert loaded_state.status == PhaseStatus.PAUSED

    def test_pipeline_with_failing_handler(self, tmp_path: Path) -> None:
        """Pipeline stops cleanly when a handler fails."""
        project_dir = tmp_path / "proj"
        project_dir.mkdir()
        _install_project(project_dir)

        ctx, s_dir = _setup_story(
            project_dir,
            "ROBUST-004",
            StoryType.RESEARCH,
            None,
        )

        workflow = resolve_workflow(StoryType.RESEARCH)

        # Make implementation fail
        registry = PhaseHandlerRegistry()
        registry.register("setup", NoOpHandler())
        registry.register(
            "implementation",
            _FailingHandler("Test failure in implementation"),
        )
        registry.register("closure", NoOpHandler())

        result = run_pipeline(ctx, s_dir, registry, workflow)

        assert result.final_status == "failed"
        assert result.final_phase == "implementation"
        assert "Test failure in implementation" in result.errors
        # Pipeline must NOT continue to closure
        assert "closure" not in result.phases_executed

    def test_full_pipeline_creates_snapshots(self, tmp_path: Path) -> None:
        """Completed phases produce canonical phase snapshots."""
        project_dir = tmp_path / "proj"
        project_dir.mkdir()
        _install_project(project_dir)

        ctx, s_dir = _setup_story(
            project_dir,
            "ROBUST-005",
            StoryType.RESEARCH,
            None,
        )

        workflow = resolve_workflow(StoryType.RESEARCH)
        registry = _registry_for_workflow(workflow)

        result = run_pipeline(ctx, s_dir, registry, workflow)

        assert result.final_status == "completed"

        # Each completed phase should have a canonical snapshot record.
        for phase_name in result.phases_executed:
            snapshot = read_phase_snapshot_record(s_dir, phase_name)
            assert snapshot is not None, (
                f"No canonical snapshot for completed phase '{phase_name}'"
            )
            assert snapshot.phase == phase_name
            assert snapshot.status == PhaseStatus.COMPLETED

    def test_handler_exception_produces_failed_result(
        self,
        tmp_path: Path,
    ) -> None:
        """An unhandled exception in a handler produces a failed result."""
        project_dir = tmp_path / "proj"
        project_dir.mkdir()
        _install_project(project_dir)

        ctx, s_dir = _setup_story(
            project_dir,
            "ROBUST-006",
            StoryType.RESEARCH,
            None,
        )

        workflow = resolve_workflow(StoryType.RESEARCH)

        class _ExplodingHandler:
            """Handler that raises an exception."""

            def on_enter(
                self,
                ctx: StoryContext,
                envelope: PhaseEnvelope,
            ) -> HandlerResult:
                msg = "Boom!"
                raise RuntimeError(msg)

            def on_exit(
                self,
                ctx: StoryContext,
                envelope: PhaseEnvelope,
            ) -> None:
                pass

            def on_resume(
                self,
                ctx: StoryContext,
                envelope: PhaseEnvelope,
                trigger: str,
            ) -> HandlerResult:
                msg = "Boom!"
                raise RuntimeError(msg)

        registry = PhaseHandlerRegistry()
        registry.register("setup", NoOpHandler())
        registry.register("implementation", _ExplodingHandler())
        registry.register("closure", NoOpHandler())

        result = run_pipeline(ctx, s_dir, registry, workflow)

        assert result.final_status == "failed"
        assert result.final_phase == "implementation"
        assert any("Boom!" in e for e in result.errors)

    def test_pipeline_run_result_fields(self, tmp_path: Path) -> None:
        """PipelineRunResult contains all expected fields after completion."""
        project_dir = tmp_path / "proj"
        project_dir.mkdir()
        _install_project(project_dir)

        ctx, s_dir = _setup_story(
            project_dir,
            "ROBUST-007",
            StoryType.RESEARCH,
            None,
        )

        workflow = resolve_workflow(StoryType.RESEARCH)
        registry = _registry_for_workflow(workflow)

        result = run_pipeline(ctx, s_dir, registry, workflow)

        assert isinstance(result, PipelineRunResult)
        assert result.story_id == "ROBUST-007"
        assert isinstance(result.phases_executed, tuple)
        assert isinstance(result.errors, tuple)
        assert result.yielded is False
        assert result.yield_status is None
