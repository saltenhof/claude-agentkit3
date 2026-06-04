"""Tests for AdversarialChallenger -- passthrough adversarial layer."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING, cast

from agentkit.bootstrap.composition_root import build_artifact_manager
from agentkit.installer import InstallConfig, install_agentkit
from agentkit.installer.paths import PROMPT_BUNDLE_STORE_ENV
from agentkit.phase_state_store import FlowExecution, save_flow_execution
from agentkit.state_backend.store import save_story_context
from agentkit.state_backend.store.verify_story_context_repository import (
    StateBackendVerifyStoryContextAdapter,
)
from agentkit.verify_system.adversarial_orchestrator.challenger import AdversarialChallenger

if TYPE_CHECKING:
    from pathlib import Path

    import pytest
from agentkit.story_context_manager.models import StoryContext
from agentkit.story_context_manager.types import StoryMode, StoryType
from agentkit.verify_system.protocols import QALayer


def _wired_audit_deps(store_dir: Path) -> dict[str, object]:
    """Prompt-audit deps as wired by the composition root (AG3-015)."""
    return {
        "artifact_manager": build_artifact_manager(store_dir),
        "story_context_port": StateBackendVerifyStoryContextAdapter(),
    }


class TestAdversarialChallenger:
    """AdversarialChallenger passthrough tests."""

    def test_evaluate_returns_passed(self, tmp_path: Path) -> None:
        challenger = AdversarialChallenger(**_wired_audit_deps(tmp_path))
        ctx = StoryContext(
            project_key="test-project",
            story_id="TEST-001",
            story_type=StoryType.BUGFIX,
            execution_route=StoryMode.EXECUTION,
        )
        result = challenger.evaluate(ctx, tmp_path)
        assert result.passed is True
        assert result.layer == "adversarial"
        assert result.findings == ()
        assert result.metadata["prompt_audit"] == {
            "status": "skipped",
            "reason": "project_root_unavailable",
        }

    def test_evaluate_materializes_prompt_audit_for_project_runs(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        project_root = tmp_path / "project"
        project_root.mkdir()
        monkeypatch.setenv(
            PROMPT_BUNDLE_STORE_ENV,
            str(tmp_path / ".prompt-bundle-store"),
        )
        install_agentkit(
            InstallConfig(
                project_key="test-project",
                project_name="test-project",
                project_root=project_root,
                github_owner="acme",  # AG3-039 R6: CP 7 coordinates are MANDATORY
                github_repo="demo",
                sonarqube_available=False,  # AG3-052: conscious opt-out, no live Sonar
            ),
        )
        story_dir = project_root / "stories" / "TEST-001"
        story_dir.mkdir(parents=True)
        save_story_context(
            story_dir,
            StoryContext(
                project_key="test-project",
                story_id="TEST-001",
                story_type=StoryType.BUGFIX,
                execution_route=StoryMode.EXECUTION,
                project_root=project_root,
            ),
        )
        save_flow_execution(
            story_dir,
            FlowExecution(
                project_key="test-project",
                story_id="TEST-001",
                run_id="run-review-001",
                flow_id="story-pipeline",
                level="story",
                owner="pipeline",
                attempt_no=1,
                started_at=datetime.now(tz=UTC),
            ),
        )
        challenger = AdversarialChallenger(**_wired_audit_deps(project_root))
        ctx = StoryContext(
            project_key="test-project",
            story_id="TEST-001",
            story_type=StoryType.BUGFIX,
            execution_route=StoryMode.EXECUTION,
            project_root=project_root,
        )

        result = challenger.evaluate(ctx, story_dir)

        audit = cast("dict[str, object]", result.metadata["prompt_audit"])
        assert audit["status"] == "materialized"
        assert audit["run_id"] == "run-review-001"
        assert audit["render_mode"] == "rendered"
        assert audit["artifact_path"] == (
            ".agentkit/prompts/run-review-001/"
            "verify-adversarial-attempt-001/prompt.md"
        )
        assert "manifest_path" not in audit
        assert isinstance(audit["audit_record_key"], str)
        assert (
            project_root / str(audit["artifact_path"])
        ).is_file()
        assert not (
            project_root
            / ".agentkit"
            / "prompts"
            / "run-review-001"
            / "verify-adversarial-attempt-001"
            / "rendered-manifest.json"
        ).exists()

    def test_implements_qa_layer_protocol(self) -> None:
        challenger = AdversarialChallenger()
        assert isinstance(challenger, QALayer)

    def test_name_is_adversarial(self) -> None:
        challenger = AdversarialChallenger()
        assert challenger.name == "adversarial"
