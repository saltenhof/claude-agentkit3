"""Tests for structural checks against canonical backend records."""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime

from agentkit.qa.protocols import LayerResult, Severity, TrustClass
from agentkit.qa.structural.checks import (
    check_artifacts_present,
    check_context_exists,
    check_context_valid,
    check_no_corrupt_state,
    check_phase_snapshots,
)
from agentkit.state_backend import (
    record_layer_artifacts,
    save_phase_snapshot,
    save_phase_state,
    save_story_context,
    state_db_path,
)
from agentkit.story_context_manager.models import (
    PhaseSnapshot,
    PhaseState,
    PhaseStatus,
    StoryContext,
)
from agentkit.story_context_manager.types import StoryMode, StoryType


def _story_dir(root: object, story_id: str = "TEST-001"):
    from pathlib import Path

    story_dir = Path(str(root)) / "stories" / story_id
    story_dir.mkdir(parents=True, exist_ok=True)
    return story_dir


def _save_context(story_dir) -> None:
    save_story_context(
        story_dir,
        StoryContext(
            project_key="test-project",
            story_id="TEST-001",
            story_type=StoryType.IMPLEMENTATION,
            execution_route=StoryMode.EXECUTION,
            title="Structural Test",
        ),
    )


def _save_snapshot(story_dir, phase: str) -> None:
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


class TestCheckContextExists:
    def test_context_present_returns_none(self, tmp_path: object) -> None:
        story_dir = _story_dir(tmp_path)
        _save_context(story_dir)
        assert check_context_exists(story_dir) is None

    def test_context_missing_returns_critical_finding(self, tmp_path: object) -> None:
        story_dir = _story_dir(tmp_path)
        finding = check_context_exists(story_dir)
        assert finding is not None
        assert finding.severity == Severity.CRITICAL
        assert finding.trust_class == TrustClass.SYSTEM
        assert finding.check == "context_exists"


class TestCheckContextValid:
    def test_valid_context_returns_none(self, tmp_path: object) -> None:
        story_dir = _story_dir(tmp_path)
        _save_context(story_dir)
        assert check_context_valid(story_dir) is None

    def test_corrupt_context_returns_finding(self, tmp_path: object) -> None:
        story_dir = _story_dir(tmp_path)
        _save_context(story_dir)
        with sqlite3.connect(state_db_path(story_dir)) as conn:
            conn.execute("UPDATE story_contexts SET payload_json = 'not json'")
            conn.commit()
        finding = check_context_valid(story_dir)
        assert finding is not None
        assert finding.severity == Severity.CRITICAL
        assert finding.check == "context_valid"

    def test_missing_context_returns_none(self, tmp_path: object) -> None:
        story_dir = _story_dir(tmp_path)
        assert check_context_valid(story_dir) is None


class TestCheckPhaseSnapshots:
    def test_all_present_returns_empty(self, tmp_path: object) -> None:
        story_dir = _story_dir(tmp_path)
        _save_context(story_dir)
        for phase in ["setup", "implementation"]:
            _save_snapshot(story_dir, phase)
        result = check_phase_snapshots(story_dir, ["setup", "implementation"])
        assert result == []

    def test_one_missing_returns_one_finding(self, tmp_path: object) -> None:
        story_dir = _story_dir(tmp_path)
        _save_context(story_dir)
        _save_snapshot(story_dir, "setup")
        result = check_phase_snapshots(story_dir, ["setup", "implementation"])
        assert len(result) == 1
        assert result[0].severity == Severity.HIGH
        assert "implementation" in result[0].message

    def test_all_missing_returns_finding_per_phase(self, tmp_path: object) -> None:
        story_dir = _story_dir(tmp_path)
        _save_context(story_dir)
        result = check_phase_snapshots(
            story_dir,
            ["setup", "exploration", "implementation"],
        )
        assert len(result) == 3


class TestCheckArtifactsPresent:
    def test_all_present_returns_empty(self, tmp_path: object) -> None:
        story_dir = _story_dir(tmp_path)
        (story_dir / "protocol.md").write_text("protocol")
        (story_dir / "manifest.json").write_text("{}")
        result = check_artifacts_present(story_dir, ["protocol.md", "manifest.json"])
        assert result == []

    def test_canonical_runtime_artifact_uses_record_presence(
        self,
        tmp_path: object,
    ) -> None:
        story_dir = _story_dir(tmp_path)
        _save_context(story_dir)
        record_layer_artifacts(
            story_dir,
            layer_results=(LayerResult(layer="structural", passed=True),),
            attempt_nr=1,
        )
        (story_dir / "structural.json").unlink()

        result = check_artifacts_present(story_dir, ["structural.json"])
        assert result == []

    def test_missing_artifact_returns_finding(self, tmp_path: object) -> None:
        story_dir = _story_dir(tmp_path)
        result = check_artifacts_present(story_dir, ["protocol.md"])
        assert len(result) == 1
        assert result[0].severity == Severity.HIGH
        assert "protocol.md" in result[0].message


class TestCheckNoCorruptState:
    def test_no_state_file_returns_none(self, tmp_path: object) -> None:
        story_dir = _story_dir(tmp_path)
        assert check_no_corrupt_state(story_dir) is None

    def test_valid_state_returns_none(self, tmp_path: object) -> None:
        story_dir = _story_dir(tmp_path)
        _save_context(story_dir)
        save_phase_state(
            story_dir,
            PhaseState(
                story_id="TEST-001",
                phase="verify",
                status=PhaseStatus.IN_PROGRESS,
            ),
        )
        assert check_no_corrupt_state(story_dir) is None

    def test_corrupt_state_returns_finding(self, tmp_path: object) -> None:
        story_dir = _story_dir(tmp_path)
        _save_context(story_dir)
        save_phase_state(
            story_dir,
            PhaseState(
                story_id="TEST-001",
                phase="verify",
                status=PhaseStatus.IN_PROGRESS,
            ),
        )
        with sqlite3.connect(state_db_path(story_dir)) as conn:
            conn.execute("UPDATE phase_states SET payload_json = 'not json'")
            conn.commit()
        finding = check_no_corrupt_state(story_dir)
        assert finding is not None
        assert finding.severity == Severity.HIGH
        assert finding.check == "no_corrupt_state"
