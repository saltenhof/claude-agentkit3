"""Tests for QaSubflowCycle -- orchestration of QA layers and policy engine."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest

from agentkit.implementation.qa_subflow import QaSubflowCycle
from agentkit.phase_state_store.models import FlowExecution
from agentkit.state_backend.config import ALLOW_SQLITE_ENV, STATE_BACKEND_ENV
from agentkit.state_backend.store import (
    reset_backend_cache_for_tests,
    save_flow_execution,
    save_phase_snapshot,
    save_story_context,
)
from agentkit.story_context_manager.models import (
    PhaseSnapshot,
    PhaseStatus,
    StoryContext,
)
from agentkit.story_context_manager.types import StoryMode, StoryType, get_profile
from agentkit.verify_system import VerifySystem
from agentkit.verify_system.llm_evaluator.reviewer import SemanticReviewer
from agentkit.verify_system.structural.checker import StructuralChecker

if TYPE_CHECKING:
    from collections.abc import Generator
    from pathlib import Path

    from agentkit.verify_system.protocols import QALayer


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
) -> StoryContext:
    """Build a minimal StoryContext for testing."""
    return StoryContext(
        project_key="test-project",
        story_id="TEST-001",
        story_type=story_type,
        execution_route=StoryMode.EXECUTION,
    )


def _setup_complete_story_dir(
    tmp_path: Path,
    story_type: StoryType = StoryType.BUGFIX,
) -> Path:
    """Set up a story dir with all required canonical records for a given type."""
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


class TestQaSubflowCycle:
    """QaSubflowCycle orchestration tests."""

    def test_all_layers_pass_returns_pass(self, tmp_path: Path) -> None:
        story_dir = _setup_complete_story_dir(tmp_path)
        ctx = _make_context()
        verify_system = make_test_verify_system()
        layers: list[QALayer] = [
            StructuralChecker(),
            SemanticReviewer(),
            verify_system.adversarial_layer(),
        ]
        cycle = QaSubflowCycle(layers=layers, verify_system=verify_system)

        result = cycle.run(ctx, story_dir)
        assert result.decision.passed is True
        assert result.feedback is None
        assert result.attempt_nr == 1

    def test_structural_fail_returns_fail_with_feedback(self, tmp_path: Path) -> None:
        # No artifacts at all -> structural fails
        ctx = _make_context()
        verify_system = make_test_verify_system()
        layers: list[QALayer] = [
            StructuralChecker(),
            SemanticReviewer(),
            verify_system.adversarial_layer(),
        ]
        cycle = QaSubflowCycle(layers=layers, verify_system=verify_system)

        result = cycle.run(ctx, tmp_path)
        assert result.decision.passed is False
        assert result.feedback is not None
        assert result.feedback.story_id == "TEST-001"

    def test_one_layer_fail_produces_correct_aggregation(self, tmp_path: Path) -> None:
        """When structural fails but semantic and adversarial pass,
        the overall result is FAIL because structural produces blockers."""
        ctx = _make_context()
        verify_system = make_test_verify_system()
        layers: list[QALayer] = [
            StructuralChecker(),
            SemanticReviewer(),
            verify_system.adversarial_layer(),
        ]
        cycle = QaSubflowCycle(layers=layers, verify_system=verify_system)

        result = cycle.run(ctx, tmp_path)
        assert result.decision.passed is False
        # All layers ran
        assert len(result.decision.layer_results) == 3
        # Structural failed, others passed
        structural_lr = next(
            lr for lr in result.decision.layer_results if lr.layer == "structural"
        )
        assert structural_lr.passed is False

    def test_feedback_prompt_text_contains_details(self, tmp_path: Path) -> None:
        ctx = _make_context()
        layers: list[QALayer] = [StructuralChecker()]
        verify_system = make_test_verify_system()
        cycle = QaSubflowCycle(layers=layers, verify_system=verify_system)

        result = cycle.run(ctx, tmp_path)
        assert result.feedback is not None
        text = result.feedback.to_prompt_text()
        assert "Remediation Feedback" in text
        assert "TEST-001" in text

    def test_attempt_nr_propagated(self, tmp_path: Path) -> None:
        story_dir = _setup_complete_story_dir(tmp_path)
        ctx = _make_context()
        layers: list[QALayer] = [StructuralChecker()]
        verify_system = make_test_verify_system()
        cycle = QaSubflowCycle(layers=layers, verify_system=verify_system)

        result = cycle.run(ctx, story_dir, attempt_nr=3)
        assert result.attempt_nr == 3


# ---------------------------------------------------------------------------
# Local test helpers (AG3-026 Re-Review: VerifySystem.create_default braucht
# einen ArtifactManager als Pflicht-Argument; Recording-Test-Double inline
# ohne Cross-Module-Helper, um pytest/mypy-Pfad-Konflikte zu vermeiden).
# ---------------------------------------------------------------------------

from agentkit.artifacts import ArtifactEnvelope as _AGAEnvelope  # noqa: E402
from agentkit.artifacts import ArtifactManager as _AGAManager  # noqa: E402
from agentkit.artifacts import ArtifactReference as _AGARef  # noqa: E402


class _RecordingArtifactManagerForTests(_AGAManager):
    """In-memory ArtifactManager for unit tests (no MagicMock)."""

    def __init__(self) -> None:
        self.written_envelopes: list[_AGAEnvelope] = []

    def write(self, envelope: _AGAEnvelope) -> _AGARef:
        self.written_envelopes.append(envelope)
        return _AGARef(
            artifact_class=envelope.artifact_class,
            story_id=envelope.story_id,
            run_id=envelope.run_id,
            record_key=f"rec/{envelope.stage}/{envelope.attempt}",
        )


def make_test_verify_system(*, max_major_findings: int = 0) -> VerifySystem:
    """Build a VerifySystem wired with a recording ArtifactManager."""
    return VerifySystem.create_default(
        max_major_findings=max_major_findings,
        artifact_manager=_RecordingArtifactManagerForTests(),
    )
