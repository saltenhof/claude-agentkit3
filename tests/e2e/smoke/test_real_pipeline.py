"""Real end-to-end pipeline tests.

These tests exercise the actual product path:
1. Install AgentKit into a target project (real install)
2. Setup phase reads a real GitHub issue (real setup handler)
3. Middle phases use NoOpHandler (acceptable -- LLM phases are stubs)
4. Verify phase runs real structural checks
5. Closure phase closes a real GitHub issue

State arises from actual pipeline execution, not manual construction.
"""

from __future__ import annotations

import contextlib
from typing import TYPE_CHECKING

import pytest

from agentkit.installer import InstallConfig, install_agentkit
from agentkit.installer.paths import story_dir
from agentkit.integrations.github.client import run_gh, run_gh_json
from agentkit.integrations.github.issues import (
    create_issue,
    get_issue,
    reopen_issue,
)
from agentkit.pipeline.lifecycle import NoOpHandler, PhaseHandlerRegistry
from agentkit.pipeline.phases.closure.phase import (
    ClosureConfig,
    ClosurePhaseHandler,
)
from agentkit.pipeline.phases.setup.phase import SetupConfig, SetupPhaseHandler
from agentkit.pipeline.phases.verify.phase import VerifyConfig, VerifyPhaseHandler
from agentkit.pipeline.runner import run_pipeline
from agentkit.pipeline.state import load_story_context, save_story_context
from agentkit.process.language.definitions import resolve_workflow
from agentkit.story_context_manager.models import StoryContext
from agentkit.story_context_manager.types import StoryMode, StoryType

if TYPE_CHECKING:
    from pathlib import Path

OWNER = "saltenhof"
REPO = "agentkit3-testbed"


def _ensure_label(name: str, *, color: str, description: str) -> None:
    """Ensure a required test label exists in the GitHub testbed repo."""

    raw = run_gh_json(
        "label",
        "list",
        "--repo",
        f"{OWNER}/{REPO}",
        "--json",
        "name",
        owner=OWNER,
    )
    if not isinstance(raw, list):
        return
    if any(isinstance(item, dict) and item.get("name") == name for item in raw):
        return
    run_gh(
        "label",
        "create",
        name,
        "--repo",
        f"{OWNER}/{REPO}",
        "--color",
        color,
        "--description",
        description,
        owner=OWNER,
    )


@pytest.mark.e2e
@pytest.mark.requires_gh
class TestRealPipelineE2E:
    """Real E2E tests that exercise actual production handlers.

    These tests create real GitHub issues, run real handlers (setup,
    verify, closure), and validate real outcomes. Only LLM-dependent
    phases (implementation, exploration) use NoOpHandler -- that is
    acceptable because those phases require an actual LLM agent.
    """

    def test_concept_story_full_pipeline(self, tmp_path: Path) -> None:
        """Concept story through real pipeline handlers.

        Real setup -> NoOp impl -> real verify -> real closure.
        This is the simplest story type that exercises real handlers.
        """
        _ensure_label(
            "concept",
            color="1d76db",
            description="Concept story test label",
        )

        # 1. Create a real GitHub issue for this test
        issue = create_issue(
            OWNER,
            REPO,
            title="E2E-AUTO: real pipeline concept test",
            body="Automated E2E test. Type: concept.",
            labels=["concept"],
        )

        try:
            # 2. Install AgentKit
            project_dir = tmp_path / "project"
            project_dir.mkdir()
            install_agentkit(
                InstallConfig(
                    project_name="e2e-test",
                    project_root=project_dir,
                )
            )

            # 3. Prepare story directory and initial context
            story_id = f"E2E-{issue.number}"
            s_dir = story_dir(project_dir, story_id)
            s_dir.mkdir(parents=True, exist_ok=True)

            # Minimal initial context -- Setup will ENRICH it from the issue
            initial_ctx = StoryContext(
                story_id=story_id,
                story_type=StoryType.CONCEPT,
                mode=StoryMode.NOT_APPLICABLE,
                project_root=project_dir,
            )
            save_story_context(s_dir, initial_ctx)

            # 4. Build registry with REAL handlers where possible
            setup_config = SetupConfig(
                owner=OWNER,
                repo=REPO,
                issue_nr=issue.number,
                project_root=project_dir,
                story_id=story_id,
                create_worktree=False,
            )

            workflow = resolve_workflow(StoryType.CONCEPT)
            registry = PhaseHandlerRegistry()
            registry.register("setup", SetupPhaseHandler(setup_config))
            registry.register("implementation", NoOpHandler())  # OK: LLM phase
            registry.register(
                "verify",
                VerifyPhaseHandler(VerifyConfig(story_dir=s_dir)),
            )
            registry.register(
                "closure",
                ClosurePhaseHandler(
                    ClosureConfig(
                        owner=OWNER,
                        repo=REPO,
                        issue_nr=issue.number,
                        story_dir=s_dir,
                        close_issue=True,
                    )
                ),
            )

            # 5. Run the full pipeline
            result = run_pipeline(initial_ctx, s_dir, registry, workflow)

            # 6. Verify real outcomes
            assert result.final_status == "completed", (
                f"Pipeline failed: {result.errors}"
            )
            assert "setup" in result.phases_executed
            assert "closure" in result.phases_executed

            # Context was enriched by real setup (not manually built)
            loaded_ctx = load_story_context(s_dir)
            assert loaded_ctx is not None
            assert loaded_ctx.issue_nr == issue.number

            # Issue was really closed
            closed_issue = get_issue(OWNER, REPO, issue.number)
            assert closed_issue.state == "CLOSED"

            # Closure report exists
            assert (s_dir / "closure.json").exists()

        finally:
            # Cleanup: reopen issue so test is repeatable
            with contextlib.suppress(Exception):
                reopen_issue(OWNER, REPO, issue.number)

    def test_research_story_full_pipeline(self, tmp_path: Path) -> None:
        """Research story: install -> real setup -> NoOp impl -> real closure.

        Research stories skip verify entirely -- tests the simplest
        full pipeline path with real GitHub integration.
        """
        _ensure_label(
            "research",
            color="5319e7",
            description="Research story test label",
        )

        issue = create_issue(
            OWNER,
            REPO,
            title="E2E-AUTO: real pipeline research test",
            body="Automated E2E test. Type: research.",
            labels=["research"],
        )

        try:
            project_dir = tmp_path / "project"
            project_dir.mkdir()
            install_agentkit(
                InstallConfig(
                    project_name="e2e-test",
                    project_root=project_dir,
                )
            )

            story_id = f"E2E-{issue.number}"
            s_dir = story_dir(project_dir, story_id)
            s_dir.mkdir(parents=True, exist_ok=True)

            initial_ctx = StoryContext(
                story_id=story_id,
                story_type=StoryType.RESEARCH,
                mode=StoryMode.NOT_APPLICABLE,
                project_root=project_dir,
            )
            save_story_context(s_dir, initial_ctx)

            setup_config = SetupConfig(
                owner=OWNER,
                repo=REPO,
                issue_nr=issue.number,
                project_root=project_dir,
                story_id=story_id,
                create_worktree=False,
            )

            workflow = resolve_workflow(StoryType.RESEARCH)
            registry = PhaseHandlerRegistry()
            registry.register("setup", SetupPhaseHandler(setup_config))
            registry.register("implementation", NoOpHandler())  # OK: LLM phase
            registry.register(
                "closure",
                ClosurePhaseHandler(
                    ClosureConfig(
                        owner=OWNER,
                        repo=REPO,
                        issue_nr=issue.number,
                        story_dir=s_dir,
                        close_issue=True,
                    )
                ),
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
            loaded_ctx = load_story_context(s_dir)
            assert loaded_ctx is not None
            assert loaded_ctx.issue_nr == issue.number

            # Issue was really closed
            closed_issue = get_issue(OWNER, REPO, issue.number)
            assert closed_issue.state == "CLOSED"

        finally:
            with contextlib.suppress(Exception):
                reopen_issue(OWNER, REPO, issue.number)
