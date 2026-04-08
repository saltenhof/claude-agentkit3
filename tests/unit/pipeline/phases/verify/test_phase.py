"""Tests for VerifyPhaseHandler -- phase handler for the verify phase."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from agentkit.pipeline.lifecycle import PhaseHandler

if TYPE_CHECKING:
    from pathlib import Path
from agentkit.pipeline.phases.verify.phase import VerifyConfig, VerifyPhaseHandler
from agentkit.qa.structural.checker import StructuralChecker
from agentkit.story.models import PhaseState, PhaseStatus, StoryContext
from agentkit.story.types import StoryMode, StoryType, get_profile


def _make_context(
    story_type: StoryType = StoryType.BUGFIX,
) -> StoryContext:
    """Build a minimal StoryContext for testing."""
    return StoryContext(
        story_id="TEST-001",
        story_type=story_type,
        mode=StoryMode.EXECUTION,
    )


def _make_state(review_round: int = 0) -> PhaseState:
    """Build a minimal PhaseState for the verify phase."""
    return PhaseState(
        story_id="TEST-001",
        phase="verify",
        status=PhaseStatus.IN_PROGRESS,
        review_round=review_round,
    )


def _setup_complete_story_dir(
    tmp_path: Path,
    story_type: StoryType = StoryType.BUGFIX,
) -> Path:
    """Set up a story dir with all required artifacts for a given type."""
    story_dir = tmp_path

    # context.json
    ctx_data = {
        "story_id": "TEST-001",
        "story_type": story_type.value,
        "mode": StoryMode.EXECUTION.value,
    }
    (story_dir / "context.json").write_text(json.dumps(ctx_data))

    # Phase snapshots for all phases before verify
    profile = get_profile(story_type)
    for phase in profile.phases:
        if phase == "verify":
            break
        (story_dir / f"phase-state-{phase}.json").write_text(
            json.dumps({
                "story_id": "TEST-001",
                "phase": phase,
                "status": "completed",
            }),
        )

    return story_dir


class TestVerifyPhaseHandler:
    """VerifyPhaseHandler tests."""

    def test_complete_setup_returns_completed(self, tmp_path: Path) -> None:
        story_dir = _setup_complete_story_dir(tmp_path)
        config = VerifyConfig(story_dir=story_dir)
        handler = VerifyPhaseHandler(config)
        ctx = _make_context()
        state = _make_state()

        result = handler.on_enter(ctx, state)
        assert result.status == PhaseStatus.COMPLETED

    def test_missing_artifacts_returns_failed(self, tmp_path: Path) -> None:
        # Empty story dir -> structural checks fail
        config = VerifyConfig(story_dir=tmp_path)
        handler = VerifyPhaseHandler(config)
        ctx = _make_context()
        state = _make_state()

        result = handler.on_enter(ctx, state)
        assert result.status == PhaseStatus.FAILED
        assert len(result.errors) > 0

    def test_on_resume_reruns_verify(self, tmp_path: Path) -> None:
        story_dir = _setup_complete_story_dir(tmp_path)
        config = VerifyConfig(story_dir=story_dir)
        handler = VerifyPhaseHandler(config)
        ctx = _make_context()
        state = _make_state(review_round=1)

        result = handler.on_resume(ctx, state, trigger="remediation_complete")
        assert result.status == PhaseStatus.COMPLETED

    def test_no_story_dir_returns_failed(self) -> None:
        config = VerifyConfig(story_dir=None)
        handler = VerifyPhaseHandler(config)
        ctx = _make_context()
        state = _make_state()

        result = handler.on_enter(ctx, state)
        assert result.status == PhaseStatus.FAILED
        assert "story_dir" in result.errors[0]

    def test_custom_layers_structural_only(self, tmp_path: Path) -> None:
        story_dir = _setup_complete_story_dir(tmp_path)
        config = VerifyConfig(
            story_dir=story_dir,
            layers=[StructuralChecker()],
        )
        handler = VerifyPhaseHandler(config)
        ctx = _make_context()
        state = _make_state()

        result = handler.on_enter(ctx, state)
        assert result.status == PhaseStatus.COMPLETED

    def test_on_exit_is_noop(self, tmp_path: Path) -> None:
        config = VerifyConfig(story_dir=tmp_path)
        handler = VerifyPhaseHandler(config)
        ctx = _make_context()
        state = _make_state()
        # on_exit should not raise
        handler.on_exit(ctx, state)

    def test_implements_phase_handler_protocol(self, tmp_path: Path) -> None:
        config = VerifyConfig(story_dir=tmp_path)
        handler = VerifyPhaseHandler(config)
        assert isinstance(handler, PhaseHandler)

    def test_failed_result_contains_feedback_text(self, tmp_path: Path) -> None:
        config = VerifyConfig(story_dir=tmp_path)
        handler = VerifyPhaseHandler(config)
        ctx = _make_context()
        state = _make_state()

        result = handler.on_enter(ctx, state)
        assert result.status == PhaseStatus.FAILED
        # Should contain structured feedback
        full_errors = "\n".join(result.errors)
        assert "Remediation Feedback" in full_errors or "FAIL" in full_errors

    def test_verify_decision_json_written_on_pass(self, tmp_path: Path) -> None:
        story_dir = _setup_complete_story_dir(tmp_path)
        config = VerifyConfig(story_dir=story_dir)
        handler = VerifyPhaseHandler(config)
        ctx = _make_context()
        state = _make_state()

        result = handler.on_enter(ctx, state)
        assert result.status == PhaseStatus.COMPLETED

        decision_path = story_dir / "verify-decision.json"
        assert decision_path.exists(), "verify-decision.json must be written"
        data = json.loads(decision_path.read_text(encoding="utf-8"))
        assert data["passed"] is True
        assert data["status"] == "PASS"
        assert "summary" in data
        assert isinstance(data["blocking_findings"], list)
        assert isinstance(data["all_findings_count"], int)

    def test_verify_decision_json_written_on_fail(self, tmp_path: Path) -> None:
        config = VerifyConfig(story_dir=tmp_path)
        handler = VerifyPhaseHandler(config)
        ctx = _make_context()
        state = _make_state()

        result = handler.on_enter(ctx, state)
        assert result.status == PhaseStatus.FAILED

        decision_path = tmp_path / "verify-decision.json"
        assert decision_path.exists(), (
            "verify-decision.json must be written even on FAIL"
        )
        data = json.loads(decision_path.read_text(encoding="utf-8"))
        assert data["passed"] is False
        assert data["status"] == "FAIL"
        assert len(data["blocking_findings"]) > 0
