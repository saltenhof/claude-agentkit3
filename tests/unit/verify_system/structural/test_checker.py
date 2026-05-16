"""Tests for StructuralChecker against canonical backend records."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from agentkit.state_backend.store import save_phase_snapshot, save_story_context
from agentkit.story_context_manager.models import (
    PhaseSnapshot,
    PhaseStatus,
    StoryContext,
)
from agentkit.story_context_manager.types import StoryMode, StoryType, get_profile
from agentkit.verify_system.protocols import QALayer, Severity
from agentkit.verify_system.structural.checker import StructuralChecker


def _story_dir(root: object, story_id: str = "TEST-001") -> Path:
    story_dir = Path(str(root)) / "stories" / story_id
    story_dir.mkdir(parents=True, exist_ok=True)
    return story_dir


def _make_context(story_type: StoryType = StoryType.BUGFIX) -> StoryContext:
    return StoryContext(
        project_key="test-project",
        story_id="TEST-001",
        story_type=story_type,
        execution_route=StoryMode.EXECUTION,
    )


def _save_snapshot(story_dir: Path, phase: str, story_id: str = "TEST-001") -> None:
    save_phase_snapshot(
        story_dir,
        PhaseSnapshot(
            story_id=story_id,
            phase=phase,
            status=PhaseStatus.COMPLETED,
            completed_at=datetime.now(tz=UTC),
            artifacts=[],
            evidence={},
        ),
    )


def _setup_complete_story_dir(
    tmp_path: object,
    story_type: StoryType = StoryType.BUGFIX,
) -> Path:
    story_dir = _story_dir(tmp_path)
    save_story_context(story_dir, _make_context(story_type))
    profile = get_profile(story_type)
    for phase in profile.phases:
        if phase == "implementation":
            break
        _save_snapshot(story_dir, phase)
    return story_dir


class TestStructuralChecker:
    def test_complete_setup_passes(self, tmp_path: Path) -> None:
        story_dir = _setup_complete_story_dir(tmp_path)
        checker = StructuralChecker()
        ctx = _make_context()
        result = checker.evaluate(ctx, story_dir)
        assert result.passed is True
        assert result.layer == "structural"

    def test_missing_context_fails(self, tmp_path: Path) -> None:
        story_dir = _story_dir(tmp_path)
        checker = StructuralChecker()
        ctx = _make_context()
        result = checker.evaluate(ctx, story_dir)
        assert result.passed is False
        assert any(
            finding.severity == Severity.BLOCKING and finding.check == "context_exists"
            for finding in result.findings
        )

    def test_collects_all_findings_no_early_return(self, tmp_path: Path) -> None:
        story_dir = _story_dir(tmp_path)
        checker = StructuralChecker()
        ctx = _make_context()
        result = checker.evaluate(ctx, story_dir)
        assert result.passed is False
        checks_found = {finding.check for finding in result.findings}
        assert "context_exists" in checks_found
        assert "phase_snapshots" in checks_found

    def test_implements_qa_layer_protocol(self) -> None:
        assert isinstance(StructuralChecker(), QALayer)

    def test_name_is_structural(self) -> None:
        assert StructuralChecker().name == "structural"

    def test_implementation_story_checks_more_phases(self, tmp_path: Path) -> None:
        story_dir = _story_dir(tmp_path)
        ctx = StoryContext(
            project_key="test-project",
            story_id="TEST-001",
            story_type=StoryType.IMPLEMENTATION,
            execution_route=StoryMode.EXPLORATION,
        )
        save_story_context(story_dir, ctx)
        _save_snapshot(story_dir, "setup")

        checker = StructuralChecker()
        result = checker.evaluate(ctx, story_dir)
        assert result.passed is False
        snapshot_findings = [
            finding
            for finding in result.findings
            if finding.check == "phase_snapshots"
        ]
        assert len(snapshot_findings) >= 1
