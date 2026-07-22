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
from tests.e2e._helpers import seed_active_run_ownership
from tests.fixtures.git_repo import ensure_git_repo

from agentkit.backend.bootstrap.composition_root import build_exploration_phase_handler
from agentkit.backend.config.loader import load_project_config
from agentkit.backend.exceptions import PipelineError
from agentkit.backend.installer import InstallConfig, install_agentkit
from agentkit.backend.installer.paths import story_dir
from agentkit.backend.pipeline_engine.lifecycle import (
    HandlerResult,
    NoOpHandler,
    PhaseHandlerRegistry,
)
from agentkit.backend.pipeline_engine.phase_executor import PhaseStatus
from agentkit.backend.pipeline_engine.runner import PipelineRunResult, run_pipeline
from agentkit.backend.process.language.definitions import (
    BUGFIX_WORKFLOW,
    IMPLEMENTATION_WORKFLOW,
    RESEARCH_WORKFLOW,
    resolve_workflow,
)
from agentkit.backend.state_backend.pipeline_runtime_store import (
    load_attempts,
    read_phase_snapshot_record,
    read_phase_state_record,
)
from agentkit.backend.state_backend.story_lifecycle_store import (
    read_story_context_record,
    save_story_context,
)
from agentkit.backend.story_context_manager.models import StoryContext
from agentkit.backend.story_context_manager.types import StoryMode, StoryType

if TYPE_CHECKING:
    from pathlib import Path

    from agentkit.backend.pipeline_engine.phase_envelope.envelope import PhaseEnvelope


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
    #
    # AG3-088 CI regression (Jenkins #314): this drives a COMPLETING install
    # whose CP 11 (cp11_to_12.py, FK-50 §50.3) runs ``git config
    # core.hooksPath`` and hard-aborts (reason ``git_config_failed``) when the
    # target is not a git repo. Real AgentKit targets ARE git repos, and a clean
    # Linux CI agent puts ``tmp_path`` under ``/tmp`` (no ambient parent repo),
    # so the project root must be ``git init``-ed first — exactly as the unit
    # installer tests do via the same shared helper.
    ensure_git_repo(project_dir)
    install_result = install_agentkit(
        InstallConfig(
        weaviate_host="weaviate.test.local",
        weaviate_http_port=19903,
        weaviate_grpc_port=50051,
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
    from agentkit.backend.process.language.model import WorkflowDefinition

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
    ordering (AG3-144: see ``_seed_exploration_run_ownership`` for why the run
    id itself must now be PINNED via a pre-seeded ``FlowExecution``, not left
    to the engine's own fresh ``uuid4()`` fallback).
    """
    registry = _registry_for_workflow(workflow_def)
    registry.register(
        "exploration", build_exploration_phase_handler(story_dir_path)
    )
    return registry


def _seed_exploration_run_ownership(
    s_dir: Path,
    *,
    project_key: str,
    story_id: str,
    workflow_def: object,
    run_id: str,
) -> None:
    """Pin the run id + seed the active ownership lease (AG3-144 Codex round-3).

    These smoke tests use ``NoOpHandler`` for setup (see ``_registry_for_workflow``),
    so the real control-plane setup start that -- in production -- atomically
    mints the story's active ``run_ownership_records`` row (AG3-142) never runs.
    ``ExplorationPhaseHandler.on_enter`` (7b68f2fc) now binds an
    ``OwnershipFenceScope`` for its whole mutating execution and requires that
    active lease to exist (no-lease-no-write, FK-91 §91.1a Rule 15), so it
    would otherwise fail closed with ``CorruptStateError``.

    ``EngineRuntimeState.resolve_run_id`` REUSES an existing ``FlowExecution``
    row that matches ``(flow_id, story_id, project_key)`` instead of generating
    a fresh ``uuid4()`` (see ``runtime_state.py``); pre-seeding one here PINS
    the run id the engine (and therefore the exploration handler's fence bind)
    will use, so the ownership record seeded with the SAME run id is the one
    the fence actually re-verifies at commit time. Mirrors
    ``tests/e2e/smoke/test_real_pipeline.py``'s ``_seed_pipeline_run_ownership``.
    """
    from agentkit.backend.phase_state_store.models import FlowExecution
    from agentkit.backend.process.language.model import WorkflowDefinition
    from agentkit.backend.state_backend.pipeline_runtime_store import save_flow_execution

    assert isinstance(workflow_def, WorkflowDefinition)
    save_flow_execution(
        s_dir,
        FlowExecution(
            project_key=project_key,
            story_id=story_id,
            run_id=run_id,
            flow_id=workflow_def.flow_id,
            level=workflow_def.level.value,
            owner=workflow_def.owner,
        ),
    )
    seed_active_run_ownership(
        project_key=project_key,
        story_id=story_id,
        run_id=run_id,
    )


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

    AG3-045 delivers the deterministic plumbing; the content drafting is AG3-055
    and the gate review is AG3-046. With no worker-produced change-frame AND no
    worker draft yet, the productive handler drives the AG3-055 produce->consume
    loop: it EMITS a typed exploration-worker ``SpawnRequest`` and YIELDS (the
    orchestrator spawns the worker and resumes) instead of fake-completing to
    closure or dead-ending. No pseudo-draft is fabricated (NO ERROR BYPASSING).
    """

    def test_exploration_mode_yields_for_worker_spawn_without_change_frame(
        self,
        tmp_path: Path,
    ) -> None:
        """EXPLORATION mode yields at exploration to spawn the worker (AG3-055)."""
        from agentkit.backend.core_types import SpawnKind
        from agentkit.backend.state_backend.pipeline_runtime_store import load_phase_state

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
        # AG3-144 (Codex round-3): pin the run id + seed the active ownership
        # lease that a real control-plane setup start would have minted
        # (NoOpHandler drives setup here, so nothing else does). The engine
        # reuses this seeded FlowExecution's run id verbatim for the fresh
        # PhaseState it builds (``EngineRuntimeState.resolve_run_id``), and
        # ``PhaseState.run_id`` is pydantic-validated as a UUID string, so
        # this must be UUID-shaped.
        _seed_exploration_run_ownership(
            s_dir,
            project_key=ctx.project_key,
            story_id="EXPL-001",
            workflow_def=workflow,
            run_id="11111111-1111-4111-8111-000000000001",
        )

        result = run_pipeline(ctx, s_dir, registry, workflow)

        # Spawn-and-await: no fake-approve, no silent completion to closure.
        assert result.final_status == "yielded"
        assert result.final_phase == "exploration"
        assert result.phases_executed == ("setup", "exploration")
        assert "closure" not in result.phases_executed
        # The typed spawn order was persisted for the orchestrator to execute.
        persisted = load_phase_state(s_dir)
        assert persisted is not None
        assert persisted.phase == "exploration"
        assert [o.kind for o in persisted.agents_to_spawn] == [SpawnKind.WORKER]

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
        # AG3-144 (Codex round-3): pin the run id + seed the active ownership
        # lease that a real control-plane setup start would have minted
        # (NoOpHandler drives setup here, so nothing else does). The engine
        # reuses this seeded FlowExecution's run id verbatim for the fresh
        # PhaseState it builds (``EngineRuntimeState.resolve_run_id``), and
        # ``PhaseState.run_id`` is pydantic-validated as a UUID string, so
        # this must be UUID-shaped.
        _seed_exploration_run_ownership(
            s_dir,
            project_key=ctx.project_key,
            story_id="EXPL-002",
            workflow_def=workflow,
            run_id="11111111-1111-4111-8111-000000000002",
        )
        result = run_pipeline(ctx, s_dir, registry, workflow)

        assert result.final_status == "yielded"
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

    def test_bugfix_workflow_includes_exploration_phase(self) -> None:
        """BUGFIX_WORKFLOW includes exploration (AG3-057, FK-23 §23.1).

        An EXECUTION-route bugfix still runs setup->implementation->closure
        (routing_rules removes the exploration phase for EXECUTION mode).
        The workflow DEFINITION includes it so that an EXPLORATION-route
        bugfix (trigger-fired) can run exploration as well.
        """
        assert "exploration" in BUGFIX_WORKFLOW.phase_names


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
