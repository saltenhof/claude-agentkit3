"""Integration-level tests fuer die drei Layer-2 Reviewer (W1 / AG3-026).

Testet die Reviewer-Klassen in realistischen Szenarien (Prompt-Audit,
Protokoll-Konformitaet). Detaillierte PASS/FAIL-Dimension-Tests sind in
``tests/unit/verify_system/llm_evaluator/test_reviewers.py``.

AG3-026 Pass-3 ERROR-5: all evaluate() calls now pass review_input.
"""

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
from agentkit.story_context_manager.models import StoryContext
from agentkit.story_context_manager.types import StoryMode, StoryType
from agentkit.verify_system.llm_evaluator.inputs import Layer2ReviewInput
from agentkit.verify_system.llm_evaluator.reviewer import (
    DocFidelityReviewer,
    QaReviewReviewer,
    SemanticReviewer,
)
from agentkit.verify_system.protocols import QALayer

if TYPE_CHECKING:
    from pathlib import Path

    import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _minimal_ctx() -> StoryContext:
    return StoryContext(
        project_key="test-project",
        story_id="TEST-001",
        story_type=StoryType.IMPLEMENTATION,
        execution_route=StoryMode.EXECUTION,
    )


def _wired_audit_deps(store_dir: Path) -> dict[str, object]:
    """Build the injected prompt-audit deps the composition root wires.

    AG3-015 / FK-44 §44.4.2: the QA layers materialize prompts via
    ``PromptRuntime.materialize_prompt`` (audited through the
    ``ArtifactManager``) and resolve the run correlation through the
    state-backed ``StoryContextQueryPort`` -- no loose ``rendered-manifest``
    JSON and no direct ``state_backend.store`` import inside ``verify_system``.
    """
    return {
        "artifact_manager": build_artifact_manager(store_dir),
        "story_context_port": StateBackendVerifyStoryContextAdapter(),
    }


def _empty_ri() -> Layer2ReviewInput:
    """Empty Layer2ReviewInput (all fields empty strings)."""
    return Layer2ReviewInput()


# ---------------------------------------------------------------------------
# QaReviewReviewer
# ---------------------------------------------------------------------------


class TestQaReviewReviewer:
    """QaReviewReviewer integration tests (AG3-026 Pass-2)."""

    def test_evaluate_returns_layer_result_with_qa_review_layer(
        self, tmp_path: Path
    ) -> None:
        """evaluate() always returns LayerResult with layer='qa_review'."""
        reviewer = QaReviewReviewer()
        result = reviewer.evaluate(_minimal_ctx(), tmp_path, review_input=_empty_ri())
        assert result.layer == "qa_review"

    def test_evaluate_includes_prompt_audit_in_metadata(self, tmp_path: Path) -> None:
        """evaluate() includes 'prompt_audit' in metadata."""
        reviewer = QaReviewReviewer(**_wired_audit_deps(tmp_path))
        result = reviewer.evaluate(_minimal_ctx(), tmp_path, review_input=_empty_ri())
        assert result.metadata["prompt_audit"] == {
            "status": "skipped",
            "reason": "project_root_unavailable",
        }

    def test_name_is_qa_review(self) -> None:
        reviewer = QaReviewReviewer()
        assert reviewer.name == "qa_review"

    def test_implements_qa_layer_protocol(self) -> None:
        reviewer = QaReviewReviewer()
        assert isinstance(reviewer, QALayer)


# ---------------------------------------------------------------------------
# SemanticReviewer
# ---------------------------------------------------------------------------


class TestSemanticReviewer:
    """SemanticReviewer integration tests (AG3-026 Pass-2)."""

    def test_evaluate_returns_passed_on_empty_dir(self, tmp_path: Path) -> None:
        """PASS: empty story_dir has no .py files to check.

        With empty review_input, layer2_input.missing (MAJOR) is emitted,
        but no BLOCKING -> passed=True. findings is non-empty.
        """
        reviewer = SemanticReviewer(**_wired_audit_deps(tmp_path))
        result = reviewer.evaluate(_minimal_ctx(), tmp_path, review_input=_empty_ri())
        assert result.passed is True
        assert result.layer == "semantic_review"
        # layer2_input.missing is MAJOR; passed is still True (no BLOCKING)
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
            ),
        )
        story_dir = project_root / "stories" / "TEST-001"
        story_dir.mkdir(parents=True)
        save_story_context(
            story_dir,
            StoryContext(
                project_key="test-project",
                story_id="TEST-001",
                story_type=StoryType.IMPLEMENTATION,
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
        reviewer = SemanticReviewer(**_wired_audit_deps(project_root))
        ctx = StoryContext(
            project_key="test-project",
            story_id="TEST-001",
            story_type=StoryType.IMPLEMENTATION,
            execution_route=StoryMode.EXECUTION,
            project_root=project_root,
        )

        result = reviewer.evaluate(ctx, story_dir, review_input=_empty_ri())

        audit = cast("dict[str, object]", result.metadata["prompt_audit"])
        assert audit["status"] == "materialized"
        assert audit["run_id"] == "run-review-001"
        assert audit["render_mode"] == "rendered"
        # FK-44 §44.4.1 canonical run-scoped instance path (prompt.md), not a
        # loose layer-named file; audit persisted via ArtifactManager.
        assert audit["artifact_path"] == (
            ".agentkit/prompts/run-review-001/"
            "verify-semantic_review-attempt-001/prompt.md"
        )
        assert "manifest_path" not in audit
        assert isinstance(audit["audit_record_key"], str)
        assert len(str(audit["output_sha256"])) == 64
        assert (
            project_root / str(audit["artifact_path"])
        ).is_file()
        # No loose rendered-manifest.json is written as audit truth anymore.
        assert not (
            project_root
            / ".agentkit"
            / "prompts"
            / "run-review-001"
            / "verify-semantic_review-attempt-001"
            / "rendered-manifest.json"
        ).exists()

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
                project_key="test-project",
                project_name="test-project",
                project_root=project_root,
            ),
        )
        story_dir = project_root / "stories" / "OTHER-999"
        story_dir.mkdir(parents=True)
        save_story_context(
            story_dir,
            StoryContext(
                project_key="test-project",
                story_id="OTHER-999",
                story_type=StoryType.IMPLEMENTATION,
                execution_route=StoryMode.EXECUTION,
                project_root=project_root,
            ),
        )
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
        reviewer = SemanticReviewer(**_wired_audit_deps(project_root))
        ctx = StoryContext(
            project_key="test-project",
            story_id="TEST-001",
            story_type=StoryType.IMPLEMENTATION,
            execution_route=StoryMode.EXECUTION,
            project_root=project_root,
        )

        result = reviewer.evaluate(ctx, story_dir, review_input=_empty_ri())

        assert result.metadata["prompt_audit"] == {
            "status": "skipped",
            "reason": "story_identity_mismatch",
        }

    def test_implements_qa_layer_protocol(self) -> None:
        reviewer = SemanticReviewer()
        assert isinstance(reviewer, QALayer)

    def test_name_is_semantic_review(self) -> None:
        reviewer = SemanticReviewer()
        assert reviewer.name == "semantic_review"


# ---------------------------------------------------------------------------
# DocFidelityReviewer
# ---------------------------------------------------------------------------


class TestDocFidelityReviewer:
    """DocFidelityReviewer integration tests (AG3-026 Pass-2)."""

    def test_evaluate_returns_passed_on_empty_dir(self, tmp_path: Path) -> None:
        """PASS: empty story_dir has no .py files to check.

        With empty review_input, layer2_input.missing (MAJOR) is emitted,
        but no BLOCKING -> passed=True.
        """
        reviewer = DocFidelityReviewer(**_wired_audit_deps(tmp_path))
        result = reviewer.evaluate(_minimal_ctx(), tmp_path, review_input=_empty_ri())
        assert result.passed is True
        assert result.layer == "doc_fidelity"
        assert result.metadata["prompt_audit"] == {
            "status": "skipped",
            "reason": "project_root_unavailable",
        }

    def test_name_is_doc_fidelity(self) -> None:
        reviewer = DocFidelityReviewer()
        assert reviewer.name == "doc_fidelity"

    def test_implements_qa_layer_protocol(self) -> None:
        reviewer = DocFidelityReviewer()
        assert isinstance(reviewer, QALayer)
