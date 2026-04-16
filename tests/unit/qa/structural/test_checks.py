"""Tests for individual structural check functions."""

from __future__ import annotations

import json

from agentkit.qa.protocols import Severity, TrustClass
from agentkit.qa.structural.checks import (
    check_artifacts_present,
    check_context_exists,
    check_context_valid,
    check_no_corrupt_state,
    check_phase_snapshots,
)
from agentkit.story_context_manager.models import PhaseStatus
from agentkit.story_context_manager.types import StoryMode, StoryType


class TestCheckContextExists:
    """check_context_exists: present -> None, missing -> Finding(CRITICAL)."""

    def test_context_present_returns_none(self, tmp_path: object) -> None:
        from pathlib import Path

        story_dir = Path(str(tmp_path))
        (story_dir / "context.json").write_text("{}")
        assert check_context_exists(story_dir) is None

    def test_context_missing_returns_critical_finding(self, tmp_path: object) -> None:
        from pathlib import Path

        story_dir = Path(str(tmp_path))
        finding = check_context_exists(story_dir)
        assert finding is not None
        assert finding.severity == Severity.CRITICAL
        assert finding.trust_class == TrustClass.SYSTEM
        assert finding.check == "context_exists"


class TestCheckContextValid:
    """check_context_valid: valid -> None, corrupt -> Finding."""

    def test_valid_context_returns_none(self, tmp_path: object) -> None:
        from pathlib import Path

        story_dir = Path(str(tmp_path))
        ctx_data = {
            "story_id": "TEST-001",
            "story_type": StoryType.IMPLEMENTATION.value,
            "mode": StoryMode.EXECUTION.value,
        }
        (story_dir / "context.json").write_text(json.dumps(ctx_data))
        assert check_context_valid(story_dir) is None

    def test_corrupt_context_returns_finding(self, tmp_path: object) -> None:
        from pathlib import Path

        story_dir = Path(str(tmp_path))
        (story_dir / "context.json").write_text("not valid json {{{")
        finding = check_context_valid(story_dir)
        assert finding is not None
        assert finding.severity == Severity.CRITICAL
        assert finding.check == "context_valid"

    def test_missing_context_returns_none(self, tmp_path: object) -> None:
        """When file doesn't exist, skip (existence checked elsewhere)."""
        from pathlib import Path

        story_dir = Path(str(tmp_path))
        assert check_context_valid(story_dir) is None


class TestCheckPhaseSnapshots:
    """check_phase_snapshots: all present -> empty, missing -> Finding per missing."""

    def test_all_present_returns_empty(self, tmp_path: object) -> None:
        from pathlib import Path

        story_dir = Path(str(tmp_path))
        for phase in ["setup", "implementation"]:
            (story_dir / f"phase-state-{phase}.json").write_text("{}")
        result = check_phase_snapshots(story_dir, ["setup", "implementation"])
        assert result == []

    def test_one_missing_returns_one_finding(self, tmp_path: object) -> None:
        from pathlib import Path

        story_dir = Path(str(tmp_path))
        (story_dir / "phase-state-setup.json").write_text("{}")
        result = check_phase_snapshots(story_dir, ["setup", "implementation"])
        assert len(result) == 1
        assert result[0].severity == Severity.HIGH
        assert "implementation" in result[0].message

    def test_all_missing_returns_finding_per_phase(self, tmp_path: object) -> None:
        from pathlib import Path

        story_dir = Path(str(tmp_path))
        result = check_phase_snapshots(
            story_dir, ["setup", "exploration", "implementation"],
        )
        assert len(result) == 3


class TestCheckArtifactsPresent:
    """check_artifacts_present: all present -> empty, missing -> Finding."""

    def test_all_present_returns_empty(self, tmp_path: object) -> None:
        from pathlib import Path

        story_dir = Path(str(tmp_path))
        (story_dir / "protocol.md").write_text("protocol")
        (story_dir / "manifest.json").write_text("{}")
        result = check_artifacts_present(
            story_dir, ["protocol.md", "manifest.json"],
        )
        assert result == []

    def test_missing_artifact_returns_finding(self, tmp_path: object) -> None:
        from pathlib import Path

        story_dir = Path(str(tmp_path))
        result = check_artifacts_present(story_dir, ["protocol.md"])
        assert len(result) == 1
        assert result[0].severity == Severity.HIGH
        assert "protocol.md" in result[0].message


class TestCheckNoCorruptState:
    """check_no_corrupt_state: valid -> None, corrupt -> Finding."""

    def test_no_state_file_returns_none(self, tmp_path: object) -> None:
        from pathlib import Path

        story_dir = Path(str(tmp_path))
        assert check_no_corrupt_state(story_dir) is None

    def test_valid_state_returns_none(self, tmp_path: object) -> None:
        from pathlib import Path

        story_dir = Path(str(tmp_path))
        state_data = {
            "story_id": "TEST-001",
            "phase": "verify",
            "status": PhaseStatus.IN_PROGRESS.value,
        }
        (story_dir / "phase-state.json").write_text(json.dumps(state_data))
        assert check_no_corrupt_state(story_dir) is None

    def test_corrupt_state_returns_finding(self, tmp_path: object) -> None:
        from pathlib import Path

        story_dir = Path(str(tmp_path))
        (story_dir / "phase-state.json").write_text("corrupt json {{{")
        finding = check_no_corrupt_state(story_dir)
        assert finding is not None
        assert finding.severity == Severity.HIGH
        assert finding.check == "no_corrupt_state"
