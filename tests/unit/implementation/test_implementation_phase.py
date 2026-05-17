"""Tests for ImplementationPhaseHandler against canonical backend records."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest

from agentkit.implementation.phase import (
    ImplementationConfig,
    ImplementationPhaseHandler,
)
from agentkit.installer.paths import qa_story_dir
from agentkit.phase_state_store.models import FlowExecution
from agentkit.pipeline_engine.lifecycle import PhaseHandler
from agentkit.pipeline_engine.phase_envelope.store import PhaseEnvelopeStore
from agentkit.state_backend.config import ALLOW_SQLITE_ENV, STATE_BACKEND_ENV
from agentkit.state_backend.store import (
    reset_backend_cache_for_tests,
    save_flow_execution,
    save_phase_snapshot,
    save_story_context,
)
from agentkit.story_context_manager.models import (
    PhaseSnapshot,
    PhaseState,
    PhaseStatus,
    StoryContext,
)
from agentkit.story_context_manager.types import StoryMode, StoryType, get_profile
from agentkit.verify_system.structural.checker import StructuralChecker

if TYPE_CHECKING:
    from collections.abc import Generator
    from pathlib import Path

    from agentkit.pipeline_engine.phase_envelope.envelope import PhaseEnvelope


@pytest.fixture(autouse=True)
def sqlite_backend_env(monkeypatch: pytest.MonkeyPatch) -> Generator[None, None, None]:
    monkeypatch.setenv(STATE_BACKEND_ENV, "sqlite")
    monkeypatch.setenv(ALLOW_SQLITE_ENV, "1")
    reset_backend_cache_for_tests()
    yield
    reset_backend_cache_for_tests()


def _story_dir(root: Path, story_id: str = "TEST-001") -> Path:
    story_dir = root / "stories" / story_id
    story_dir.mkdir(parents=True, exist_ok=True)
    return story_dir


def _make_context(
    story_type: StoryType = StoryType.BUGFIX,
    *,
    project_root: Path | None = None,
) -> StoryContext:
    """Build a minimal StoryContext for testing."""
    return StoryContext(
        project_key="test-project",
        story_id="TEST-001",
        story_type=story_type,
        execution_route=StoryMode.EXECUTION,
        project_root=project_root,
    )


def _make_state(review_round: int = 0) -> PhaseState:
    """Build a minimal PhaseState for the implementation phase."""
    return PhaseState(
        story_id="TEST-001",
        phase="implementation",
        status=PhaseStatus.IN_PROGRESS,
        review_round=review_round,
    )


def _make_envelope(state: PhaseState) -> PhaseEnvelope:
    """Wrap a PhaseState in a PhaseEnvelope for handler calls."""
    return PhaseEnvelopeStore.make_fresh_envelope(state)


def _setup_complete_story_dir(
    tmp_path: Path,
    story_type: StoryType = StoryType.BUGFIX,
) -> Path:
    """Set up a story dir with all required artifacts for a given type."""
    story_dir = _story_dir(tmp_path)

    save_story_context(story_dir, _make_context(story_type))
    save_flow_execution(
        story_dir,
        FlowExecution(
            project_key="test-project",
            story_id="TEST-001",
            run_id="run-implementation-001",
            flow_id="implementation",
            level="story",
            owner="pipeline_engine",
            status="IN_PROGRESS",
        ),
    )

    profile = get_profile(story_type)
    for phase in profile.phases:
        if phase == "implementation":
            break
        save_phase_snapshot(
            story_dir,
            PhaseSnapshot(
                story_id="TEST-001",
                phase=phase,
                status=PhaseStatus.COMPLETED,
                completed_at=datetime.now(tz=UTC),
                artifacts=[],
                evidence={},
            ),
        )

    return story_dir


class TestImplementationPhaseHandler:
    """ImplementationPhaseHandler tests."""

    def test_complete_setup_returns_completed(self, tmp_path: Path) -> None:
        story_dir = _setup_complete_story_dir(tmp_path)
        config = ImplementationConfig(story_dir=story_dir)
        handler = ImplementationPhaseHandler(config)
        ctx = _make_context()
        state = _make_state()

        result = handler.on_enter(ctx, _make_envelope(state))
        assert result.status == PhaseStatus.COMPLETED
        assert result.artifacts_produced == (
            "structural.json",
            "semantic-review.json",
            "adversarial.json",
            "verify-decision.json",
        )

    def test_missing_artifacts_returns_escalated(self, tmp_path: Path) -> None:
        # Empty story dir -> structural checks fail
        story_dir = _story_dir(tmp_path)
        save_story_context(story_dir, _make_context())
        save_flow_execution(
            story_dir,
            FlowExecution(
                project_key="test-project",
                story_id="TEST-001",
                run_id="run-implementation-001",
                flow_id="implementation",
                level="story",
                owner="pipeline_engine",
                status="IN_PROGRESS",
            ),
        )
        config = ImplementationConfig(story_dir=story_dir, max_feedback_rounds=0)
        handler = ImplementationPhaseHandler(config)
        ctx = _make_context()
        state = _make_state()

        result = handler.on_enter(ctx, _make_envelope(state))
        assert result.status == PhaseStatus.ESCALATED
        assert len(result.errors) > 0
        assert result.artifacts_produced == (
            "structural.json",
            "semantic-review.json",
            "adversarial.json",
            "verify-decision.json",
        )

    def test_on_resume_reruns_qa_subflow(self, tmp_path: Path) -> None:
        story_dir = _setup_complete_story_dir(tmp_path)
        config = ImplementationConfig(story_dir=story_dir)
        handler = ImplementationPhaseHandler(config)
        ctx = _make_context()
        state = _make_state(review_round=1)

        result = handler.on_resume(ctx, _make_envelope(state), trigger="remediation_complete")
        assert result.status == PhaseStatus.COMPLETED

    def test_no_story_dir_returns_failed(self) -> None:
        config = ImplementationConfig(story_dir=None)
        handler = ImplementationPhaseHandler(config)
        ctx = _make_context()
        state = _make_state()

        result = handler.on_enter(ctx, _make_envelope(state))
        assert result.status == PhaseStatus.FAILED
        assert "story_dir" in result.errors[0]

    def test_custom_layers_structural_only(self, tmp_path: Path) -> None:
        story_dir = _setup_complete_story_dir(tmp_path)
        config = ImplementationConfig(
            story_dir=story_dir,
            layers=[StructuralChecker()],
        )
        handler = ImplementationPhaseHandler(config)
        ctx = _make_context()
        state = _make_state()

        result = handler.on_enter(ctx, _make_envelope(state))
        assert result.status == PhaseStatus.COMPLETED
        assert result.artifacts_produced == (
            "structural.json",
            "verify-decision.json",
        )

    def test_on_exit_is_noop(self, tmp_path: Path) -> None:
        config = ImplementationConfig(story_dir=_story_dir(tmp_path))
        handler = ImplementationPhaseHandler(config)
        ctx = _make_context(project_root=tmp_path)
        state = _make_state()
        # on_exit should not raise
        handler.on_exit(ctx, _make_envelope(state))

    def test_implements_phase_handler_protocol(self, tmp_path: Path) -> None:
        config = ImplementationConfig(story_dir=_story_dir(tmp_path))
        handler = ImplementationPhaseHandler(config)
        assert isinstance(handler, PhaseHandler)

    def test_failed_result_contains_feedback_text(self, tmp_path: Path) -> None:
        story_dir = _story_dir(tmp_path)
        save_story_context(story_dir, _make_context())
        save_flow_execution(
            story_dir,
            FlowExecution(
                project_key="test-project",
                story_id="TEST-001",
                run_id="run-implementation-001",
                flow_id="implementation",
                level="story",
                owner="pipeline_engine",
                status="IN_PROGRESS",
            ),
        )
        config = ImplementationConfig(story_dir=story_dir, max_feedback_rounds=0)
        handler = ImplementationPhaseHandler(config)
        ctx = _make_context()
        state = _make_state()

        result = handler.on_enter(ctx, _make_envelope(state))
        assert result.status == PhaseStatus.ESCALATED
        # Should contain structured feedback
        full_errors = "\n".join(result.errors)
        assert "Remediation Feedback" in full_errors or "FAIL" in full_errors

    def test_verify_decision_json_written_on_pass(self, tmp_path: Path) -> None:
        story_dir = _setup_complete_story_dir(tmp_path)
        config = ImplementationConfig(story_dir=story_dir)
        handler = ImplementationPhaseHandler(config)
        ctx = _make_context()
        state = _make_state()

        result = handler.on_enter(ctx, _make_envelope(state))
        assert result.status == PhaseStatus.COMPLETED

        qa_dir = qa_story_dir(tmp_path, "TEST-001")
        decision_path = qa_dir / "verify-decision.json"
        assert decision_path.exists(), "verify-decision.json must be written"
        semantic_path = qa_dir / "semantic-review.json"
        adversarial_path = qa_dir / "adversarial.json"
        structural_path = qa_dir / "structural.json"
        assert structural_path.exists()
        assert semantic_path.exists()
        assert adversarial_path.exists()
        data = json.loads(decision_path.read_text(encoding="utf-8"))
        structural_data = json.loads(structural_path.read_text(encoding="utf-8"))
        assert data["passed"] is True
        assert data["status"] == "PASS"
        assert "summary" in data
        assert isinstance(data["layers"], list)
        assert isinstance(data["blocking_findings"], list)
        assert isinstance(data["all_findings_count"], int)
        assert structural_data["layer"] == "structural"
        assert structural_data["passed"] is True
        semantic = next(
            layer for layer in data["layers"] if layer["layer"] == "semantic"
        )
        adversarial = next(
            layer for layer in data["layers"] if layer["layer"] == "adversarial"
        )
        assert semantic["metadata"]["prompt_audit"] == {
            "status": "skipped",
            "reason": "project_root_unavailable",
        }
        assert adversarial["metadata"]["prompt_audit"] == {
            "status": "skipped",
            "reason": "project_root_unavailable",
        }
        semantic_data = json.loads(semantic_path.read_text(encoding="utf-8"))
        adversarial_data = json.loads(adversarial_path.read_text(encoding="utf-8"))
        assert semantic_data["layer"] == "semantic"
        assert semantic_data["passed"] is True
        assert semantic_data["metadata"]["prompt_audit"] == {
            "status": "skipped",
            "reason": "project_root_unavailable",
        }
        assert adversarial_data["layer"] == "adversarial"
        assert adversarial_data["passed"] is True
        assert adversarial_data["metadata"]["prompt_audit"] == {
            "status": "skipped",
            "reason": "project_root_unavailable",
        }

    def test_verify_decision_json_written_on_fail(self, tmp_path: Path) -> None:
        story_dir = _story_dir(tmp_path)
        save_story_context(story_dir, _make_context())
        save_flow_execution(
            story_dir,
            FlowExecution(
                project_key="test-project",
                story_id="TEST-001",
                run_id="run-implementation-001",
                flow_id="implementation",
                level="story",
                owner="pipeline_engine",
                status="IN_PROGRESS",
            ),
        )
        config = ImplementationConfig(story_dir=story_dir, max_feedback_rounds=0)
        handler = ImplementationPhaseHandler(config)
        ctx = _make_context()
        state = _make_state()

        result = handler.on_enter(ctx, _make_envelope(state))
        assert result.status == PhaseStatus.ESCALATED

        qa_dir = qa_story_dir(tmp_path, "TEST-001")
        decision_path = qa_dir / "verify-decision.json"
        assert decision_path.exists(), (
            "verify-decision.json must be written even on FAIL"
        )
        assert (qa_dir / "structural.json").exists()
        assert (qa_dir / "semantic-review.json").exists()
        assert (qa_dir / "adversarial.json").exists()
        data = json.loads(decision_path.read_text(encoding="utf-8"))
        assert data["passed"] is False
        assert data["status"] == "FAIL"
        assert isinstance(data["layers"], list)
        assert len(data["blocking_findings"]) > 0
