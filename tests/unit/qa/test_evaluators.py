"""Tests for SemanticReviewer -- passthrough LLM layer."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

from agentkit.installer import InstallConfig, install_agentkit
from agentkit.installer.paths import PROMPT_BUNDLE_STORE_ENV
from agentkit.phase_state_store import FlowExecution, save_flow_execution
from agentkit.prompt_composer.pins import initialize_prompt_run_pin
from agentkit.qa.evaluators.reviewer import SemanticReviewer

if TYPE_CHECKING:
    from pathlib import Path

    import pytest
from agentkit.qa.protocols import QALayer
from agentkit.story_context_manager.models import StoryContext
from agentkit.story_context_manager.types import StoryMode, StoryType


class TestSemanticReviewer:
    """SemanticReviewer passthrough tests."""

    def test_evaluate_returns_passed(self, tmp_path: Path) -> None:
        reviewer = SemanticReviewer()
        ctx = StoryContext(
            story_id="TEST-001",
            story_type=StoryType.IMPLEMENTATION,
            mode=StoryMode.EXECUTION,
        )
        result = reviewer.evaluate(ctx, tmp_path)
        assert result.passed is True
        assert result.layer == "semantic"
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
                project_name="test-project",
                project_root=project_root,
            ),
        )
        story_dir = project_root / "stories" / "TEST-001"
        story_dir.mkdir(parents=True)
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
        initialize_prompt_run_pin(project_root, run_id="run-review-001")
        reviewer = SemanticReviewer()
        ctx = StoryContext(
            story_id="TEST-001",
            story_type=StoryType.IMPLEMENTATION,
            mode=StoryMode.EXECUTION,
            project_root=project_root,
        )

        result = reviewer.evaluate(ctx, story_dir)

        audit = result.metadata["prompt_audit"]
        assert audit["status"] == "materialized"
        assert audit["run_id"] == "run-review-001"
        assert audit["logical_prompt_id"] == "prompt.qa-semantic-review"
        assert audit["artifact_path"] == (
            ".agentkit/prompts/run-review-001/"
            "verify-semantic-attempt-001/semantic-prompt.md"
        )
        assert audit["manifest_path"] == (
            ".agentkit/prompts/run-review-001/"
            "verify-semantic-attempt-001/rendered-manifest.json"
        )
        assert (
            project_root / audit["artifact_path"]
        ).is_file()
        assert (
            project_root / audit["manifest_path"]
        ).is_file()

    def test_evaluate_skips_when_flow_story_does_not_match_context(
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
                project_name="test-project",
                project_root=project_root,
            ),
        )
        story_dir = project_root / "stories" / "TEST-001"
        story_dir.mkdir(parents=True)
        save_flow_execution(
            story_dir,
            FlowExecution(
                project_key="test-project",
                story_id="OTHER-999",
                run_id="run-review-001",
                flow_id="story-pipeline",
                level="story",
                owner="pipeline",
                attempt_no=1,
                started_at=datetime.now(tz=UTC),
            ),
        )
        initialize_prompt_run_pin(project_root, run_id="run-review-001")
        reviewer = SemanticReviewer()
        ctx = StoryContext(
            story_id="TEST-001",
            story_type=StoryType.IMPLEMENTATION,
            mode=StoryMode.EXECUTION,
            project_root=project_root,
        )

        result = reviewer.evaluate(ctx, story_dir)

        assert result.metadata["prompt_audit"] == {
            "status": "skipped",
            "reason": "story_identity_mismatch",
        }

    def test_implements_qa_layer_protocol(self) -> None:
        reviewer = SemanticReviewer()
        assert isinstance(reviewer, QALayer)

    def test_name_is_semantic(self) -> None:
        reviewer = SemanticReviewer()
        assert reviewer.name == "semantic"
