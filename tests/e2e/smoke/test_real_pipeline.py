"""Real end-to-end pipeline tests.

These tests exercise the actual product path:
1. Install AgentKit into a target project (real install)
2. Setup phase builds the StoryContext from the AK3 Story-Service record
3. Middle phases use NoOpHandler (acceptable -- LLM phases are stubs)
4. Implementation runs as the canonical middle phase
5. Closure phase closes the story via the AK3 Story-Service

AG3-120: AK3 owns the user story via ``story_id``; GitHub is only the code
backend (FK-12 §12.1.1, FK-91 §91.2 rule 9). The pipeline is driven by
``story_id`` and the authoritative Story-Service record -- no GitHub issue is
read or closed. State arises from actual pipeline execution, not manual
construction.
"""

from __future__ import annotations

import subprocess
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest
from tests.e2e._helpers import seed_active_run_ownership, seed_approved_story

from agentkit.backend.bootstrap.composition_root import (
    build_closure_phase_handler,
    build_setup_phase_handler,
)
from agentkit.backend.closure.phase import ClosureConfig
from agentkit.backend.governance.setup_preflight_gate.phase import SetupConfig
from agentkit.backend.installer import InstallConfig, install_agentkit
from agentkit.backend.installer.paths import qa_story_dir, story_dir
from agentkit.backend.phase_state_store.models import FlowExecution
from agentkit.backend.pipeline_engine.lifecycle import NoOpHandler, PhaseHandlerRegistry
from agentkit.backend.pipeline_engine.runner import run_pipeline
from agentkit.backend.process.language.definitions import resolve_workflow
from agentkit.backend.state_backend.pipeline_runtime_store import save_flow_execution
from agentkit.backend.state_backend.story_lifecycle_store import (
    read_story_context_record,
    save_story_context,
)
from agentkit.backend.state_backend.telemetry_event_store import append_execution_event
from agentkit.backend.story_context_manager.models import StoryContext
from agentkit.backend.story_context_manager.story_model import WireStoryType
from agentkit.backend.story_context_manager.types import StoryType
from agentkit.backend.telemetry.contract.records import ExecutionEventRecord
from agentkit.backend.telemetry.events import EventType

if TYPE_CHECKING:
    from pathlib import Path

    from agentkit.backend.process.language.model import WorkflowDefinition

_AGENT_START_AT = datetime(2026, 7, 5, 9, 0, 0, tzinfo=UTC)


def _seed_pipeline_run_ownership(
    s_dir: Path,
    *,
    project_key: str,
    story_id: str,
    workflow: WorkflowDefinition,
    run_id: str,
) -> None:
    """Reproduce the real control-plane setup-start invariant (AG3-144).

    A real run's control-plane setup start atomically mints the story's active
    ``run_ownership_records`` row AND the flow execution (with its ``AGENT_START``
    lifecycle event), all sharing ONE run id. These smoke tests drive
    ``run_pipeline`` directly (no control-plane), so we pre-seed:

    * the flow execution -- pins the run id the engine reuses (see
      ``EngineRuntimeState.resolve_run_id``);
    * the ``AGENT_START`` execution event for that run id -- because a
      pre-existing matching-``flow_id`` flow makes the engine treat the flow as
      NOT new and skip emitting ``AGENT_START`` itself, which the closure
      story-metrics build requires (``build_story_metrics_record``);
    * the active ownership record -- so the closure projection write passes the
      no-lease-no-write fence (FK-91 §91.1a Rule 15) exactly as a real admitted
      run would.
    """
    save_flow_execution(
        s_dir,
        FlowExecution(
            project_key=project_key,
            story_id=story_id,
            run_id=run_id,
            flow_id=workflow.flow_id,
            level=workflow.level.value,
            owner=workflow.owner,
        ),
    )
    append_execution_event(
        s_dir,
        ExecutionEventRecord(
            project_key=project_key,
            story_id=story_id,
            run_id=run_id,
            event_id=f"evt-agent-start-{run_id}",
            event_type=EventType.AGENT_START.value,
            occurred_at=_AGENT_START_AT,
            source_component="e2e-seed",
            severity="info",
            payload={"agent_type": "pipeline_engine"},
        ),
    )
    seed_active_run_ownership(
        project_key=project_key,
        story_id=story_id,
        run_id=run_id,
    )


def _init_project_repo(project_dir: Path) -> None:
    """Init a real git repo so Preflight Check 7's ``git show-ref`` can run.

    AG3-034 Finding B: ``no_story_branch`` reads the real repo and fails closed
    on a non-repo dir; the real-pipeline smoke run therefore needs an actual
    git repository (with no ``story/*`` branch) under the project root.
    """
    subprocess.run(["git", "-C", str(project_dir), "init", "-q"], check=True)
    subprocess.run(
        ["git", "-C", str(project_dir), "config", "user.email", "t@example.com"],
        check=True,
    )
    subprocess.run(
        ["git", "-C", str(project_dir), "config", "user.name", "T"], check=True
    )


@pytest.mark.e2e
class TestRealPipelineE2E:
    """Real E2E tests that exercise actual production handlers.

    These tests run real handlers (setup, closure) against the real
    state-backend and Story-Service, and validate real outcomes. Only
    LLM-dependent middle phases use NoOpHandler -- that is acceptable because
    those phases require an actual LLM agent. AG3-120: the story is identified
    by ``story_id`` and closed via the AK3 Story-Service (no GitHub issue).
    """

    def test_concept_story_full_pipeline(self, tmp_path: Path) -> None:
        """Concept story through real pipeline handlers.

        Real setup -> NoOp implementation -> real closure.
        This is the simplest story type that exercises real handlers.
        """
        # 1. Install AgentKit
        project_dir = tmp_path / "project"
        project_dir.mkdir()
        _init_project_repo(project_dir)
        install_agentkit(
            InstallConfig(
                project_key="e2e-test",
                project_name="e2e-test",
                project_root=project_dir,
                github_owner="acme",  # AG3-039 R6: CP 7 coordinates are MANDATORY
                github_repo="demo",
                sonarqube_available=False,  # AG3-052: conscious opt-out, no live Sonar
                ci_available=False,  # AG3-056: conscious opt-out, no live Jenkins
            )
        )

        # 2. Prepare story directory and initial context (AK3 owns the story_id).
        story_id = "E2E-9001"
        s_dir = story_dir(project_dir, story_id)
        s_dir.mkdir(parents=True, exist_ok=True)

        # Minimal initial context -- Setup will ENRICH it from the Story-Service.
        initial_ctx = StoryContext(
            project_key="e2e-test",
            story_id=story_id,
            story_type=StoryType.CONCEPT,
            execution_route=None,
            project_root=project_dir,
        )
        save_story_context(s_dir, initial_ctx)

        # Seed the APPROVED Story the Setup preflight gate requires
        # (real StoryService persistence, no mock).
        seed_approved_story(
            project_key="e2e-test",
            story_display_id=story_id,
            story_number=9001,
            story_type=WireStoryType.CONCEPT,
            title="E2E-AUTO: real pipeline concept test",
        )

        # 3. Build registry with REAL handlers where possible
        setup_config = SetupConfig(
            project_root=project_dir,
            story_id=story_id,
            create_worktree=False,
        )

        workflow = resolve_workflow(StoryType.CONCEPT)
        registry = PhaseHandlerRegistry()
        registry.register("setup", build_setup_phase_handler(setup_config))
        registry.register("implementation", NoOpHandler())  # OK: LLM phase
        registry.register(
            "closure",
            build_closure_phase_handler(
                ClosureConfig(story_dir=s_dir),
                store_dir=s_dir,
                project_key="e2e-test",
            ),
        )

        # AG3-144: seed the setup-minted active ownership record (+ pinned flow
        # execution) a real control-plane run would have, so the closure
        # projection write passes the no-lease-no-write fence.
        _seed_pipeline_run_ownership(
            s_dir,
            project_key="e2e-test",
            story_id=story_id,
            workflow=workflow,
            run_id="5aaa4bd3-70f0-5132-9f94-9dbaf1a6b026",
        )

        # 4. Run the full pipeline
        result = run_pipeline(initial_ctx, s_dir, registry, workflow)

        # 5. Verify real outcomes
        assert result.final_status == "completed", (
            f"Pipeline failed: {result.errors}"
        )
        assert "setup" in result.phases_executed
        assert "closure" in result.phases_executed

        # Context was enriched by real setup (not manually built)
        loaded_ctx = read_story_context_record(s_dir)
        assert loaded_ctx is not None
        assert loaded_ctx.story_id == story_id

        # Closure report exists
        assert (qa_story_dir(project_dir, story_id) / "closure.json").exists()

    def test_research_story_full_pipeline(self, tmp_path: Path) -> None:
        """Research story: install -> real setup -> NoOp impl -> real closure.

        Research stories use the simplest
        full pipeline path with the real Story-Service.
        """
        project_dir = tmp_path / "project"
        project_dir.mkdir()
        _init_project_repo(project_dir)
        install_agentkit(
            InstallConfig(
                project_key="e2e-test",
                project_name="e2e-test",
                project_root=project_dir,
                github_owner="acme",  # AG3-039 R6: CP 7 coordinates are MANDATORY
                github_repo="demo",
                sonarqube_available=False,  # AG3-052: conscious opt-out, no live Sonar
                ci_available=False,  # AG3-056: conscious opt-out, no live Jenkins
            )
        )

        story_id = "E2E-9002"
        s_dir = story_dir(project_dir, story_id)
        s_dir.mkdir(parents=True, exist_ok=True)

        initial_ctx = StoryContext(
            project_key="e2e-test",
            story_id=story_id,
            story_type=StoryType.RESEARCH,
            execution_route=None,
            project_root=project_dir,
        )
        save_story_context(s_dir, initial_ctx)

        # Seed the APPROVED Story the Setup preflight gate requires
        # (real StoryService persistence, no mock).
        seed_approved_story(
            project_key="e2e-test",
            story_display_id=story_id,
            story_number=9002,
            story_type=WireStoryType.RESEARCH,
            title="E2E-AUTO: real pipeline research test",
        )

        setup_config = SetupConfig(
            project_root=project_dir,
            story_id=story_id,
            create_worktree=False,
        )

        workflow = resolve_workflow(StoryType.RESEARCH)
        registry = PhaseHandlerRegistry()
        registry.register("setup", build_setup_phase_handler(setup_config))
        registry.register("implementation", NoOpHandler())  # OK: LLM phase
        registry.register(
            "closure",
            build_closure_phase_handler(
                ClosureConfig(story_dir=s_dir),
                store_dir=s_dir,
                project_key="e2e-test",
            ),
        )

        # AG3-144: seed the setup-minted active ownership record (+ pinned flow
        # execution) a real control-plane run would have, so the closure
        # projection write passes the no-lease-no-write fence.
        _seed_pipeline_run_ownership(
            s_dir,
            project_key="e2e-test",
            story_id=story_id,
            workflow=workflow,
            run_id="767b4d32-0e1d-53ab-9d55-2dd36b3dafa8",
        )

        result = run_pipeline(initial_ctx, s_dir, registry, workflow)

        assert result.final_status == "completed", (
            f"Pipeline failed: {result.errors}"
        )
        assert result.phases_executed == (
            "setup",
            "implementation",
            "closure",
        )

        # Context was enriched by real setup
        loaded_ctx = read_story_context_record(s_dir)
        assert loaded_ctx is not None
        assert loaded_ctx.story_id == story_id

        # Closure report exists
        assert (qa_story_dir(project_dir, story_id) / "closure.json").exists()
