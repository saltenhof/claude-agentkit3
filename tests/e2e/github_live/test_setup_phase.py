"""E2E tests for the setup phase against the live GitHub testbed.

Testbed: saltenhof/agentkit3-testbed
Pre-existing issues: #1 (implementation), #2 (bugfix), #3 (concept).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from agentkit.pipeline.phases.setup.phase import SetupConfig, SetupPhaseHandler
from agentkit.pipeline.state import load_story_context
from agentkit.installer import InstallConfig, install_agentkit
from agentkit.installer.paths import story_dir
from agentkit.story_context_manager.models import PhaseState, PhaseStatus, StoryContext
from agentkit.story_context_manager.types import StoryMode, StoryType

if TYPE_CHECKING:
    from pathlib import Path


OWNER = "saltenhof"
REPO = "agentkit3-testbed"


@pytest.mark.e2e
@pytest.mark.requires_gh
class TestSetupPhaseE2E:
    """End-to-end tests for the setup phase against real GitHub."""

    def test_setup_reads_real_issue(self, tmp_path: Path) -> None:
        """Setup phase reads testbed issue #1 and builds StoryContext."""
        # 1. Install AgentKit
        install_agentkit(InstallConfig(
            project_name="test", project_root=tmp_path,
        ))

        # 2. Run setup with real issue
        config = SetupConfig(
            owner=OWNER,
            repo=REPO,
            issue_nr=1,
            project_root=tmp_path,
            create_worktree=False,  # No git repo in tmp_path
        )
        handler = SetupPhaseHandler(config)

        # Minimal initial context
        ctx = StoryContext(
            story_id="TEST-001",
            story_type=StoryType.IMPLEMENTATION,
            mode=StoryMode.EXECUTION,
        )
        state = PhaseState(
            story_id="TEST-001",
            phase="setup",
            status=PhaseStatus.IN_PROGRESS,
        )

        result = handler.on_enter(ctx, state)

        assert result.status == PhaseStatus.COMPLETED

        # 3. Verify context.json was written
        s_dir = story_dir(tmp_path, "TEST-001")
        loaded = load_story_context(s_dir)
        assert loaded is not None
        assert loaded.issue_nr == 1
        assert loaded.story_id == "TEST-001"

    def test_setup_preflight_fails_on_nonexistent_issue(
        self, tmp_path: Path,
    ) -> None:
        """Setup fails cleanly when issue doesn't exist."""
        install_agentkit(InstallConfig(
            project_name="test", project_root=tmp_path,
        ))

        config = SetupConfig(
            owner=OWNER,
            repo=REPO,
            issue_nr=99999,
            project_root=tmp_path,
        )
        handler = SetupPhaseHandler(config)
        ctx = StoryContext(
            story_id="FAIL-001",
            story_type=StoryType.IMPLEMENTATION,
            mode=StoryMode.EXECUTION,
        )
        state = PhaseState(
            story_id="FAIL-001",
            phase="setup",
            status=PhaseStatus.IN_PROGRESS,
        )

        result = handler.on_enter(ctx, state)
        assert result.status == PhaseStatus.FAILED
        assert len(result.errors) > 0
