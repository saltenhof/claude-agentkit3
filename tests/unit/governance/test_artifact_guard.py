"""Tests for ArtifactGuard -- QA directory tampering prevention."""

from __future__ import annotations

import pytest

from agentkit.governance.guards.artifact_guard import ArtifactGuard
from agentkit.governance.protocols import ViolationType


@pytest.fixture()
def guard() -> ArtifactGuard:
    return ArtifactGuard()


class TestArtifactGuardBlocked:
    """Sub-agent writes into the active QA directory must be blocked."""

    def test_subagent_write_to_active_story_qa_path(
        self,
        guard: ArtifactGuard,
    ) -> None:
        v = guard.evaluate(
            "file_write",
            {
                "file_path": "/repo/_temp/qa/AG3-001/structural.json",
                "operating_mode": "story_execution",
                "qa_artifact_lock_active": True,
                "principal_kind": "subagent",
                "active_story_id": "AG3-001",
            },
        )
        assert v.allowed is False
        assert v.violation_type == ViolationType.ARTIFACT_TAMPERING

    def test_subagent_edit_to_active_story_qa_path(self, guard: ArtifactGuard) -> None:
        v = guard.evaluate(
            "file_edit",
            {
                "file_path": "/repo/_temp/qa/AG3-001/decision.json",
                "operating_mode": "story_execution",
                "qa_artifact_lock_active": True,
                "principal_kind": "subagent",
                "active_story_id": "AG3-001",
            },
        )
        assert v.allowed is False
        assert v.violation_type == ViolationType.ARTIFACT_TAMPERING


class TestArtifactGuardFrozenChangeFrame:
    """The exploration change-frame is write-protected once frozen (AG3-045 AC8)."""

    def test_subagent_write_to_frozen_change_frame_blocked(
        self, guard: ArtifactGuard
    ) -> None:
        """A frozen change_frame.json is real write-protected (FIX 1)."""
        v = guard.evaluate(
            "file_write",
            {
                "file_path": "/repo/_temp/qa/AG3-045/change_frame.json",
                "operating_mode": "story_execution",
                "principal_kind": "subagent",
                "active_story_id": "AG3-045",
                "change_frame_frozen": True,
            },
        )
        assert v.allowed is False
        assert v.violation_type == ViolationType.ARTIFACT_TAMPERING
        assert v.detail["protected_filename"] == "change_frame.json"

    def test_subagent_edit_to_frozen_change_frame_blocked(
        self, guard: ArtifactGuard
    ) -> None:
        v = guard.evaluate(
            "file_edit",
            {
                "file_path": "/repo/_temp/qa/AG3-045/change_frame.json",
                "operating_mode": "story_execution",
                "principal_kind": "subagent",
                "active_story_id": "AG3-045",
                "change_frame_frozen": True,
            },
        )
        assert v.allowed is False
        assert v.violation_type == ViolationType.ARTIFACT_TAMPERING

    def test_subagent_write_to_unfrozen_change_frame_allowed(
        self, guard: ArtifactGuard
    ) -> None:
        """Before freeze the change-frame is still editable (FK-25 §25.4.2).

        Allowed ONLY when the freeze state is explicitly KNOWN to be not-frozen.
        """
        v = guard.evaluate(
            "file_write",
            {
                "file_path": "/repo/_temp/qa/AG3-045/change_frame.json",
                "operating_mode": "story_execution",
                "principal_kind": "subagent",
                "active_story_id": "AG3-045",
                "change_frame_frozen": False,
                "change_frame_freeze_known": True,
            },
        )
        assert v.allowed is True

    def test_change_frame_freeze_state_unknown_blocks_fail_closed(
        self, guard: ArtifactGuard
    ) -> None:
        """An unknown / missing freeze state blocks fail-closed (deep-review #5).

        Previously this pinned "no signal => allowed" -- the fail-open hole. An
        absent / unreadable freeze state is now treated as deny (ARCH-48).
        """
        v = guard.evaluate(
            "file_write",
            {
                "file_path": "/repo/_temp/qa/AG3-045/change_frame.json",
                "operating_mode": "story_execution",
                "principal_kind": "subagent",
                "active_story_id": "AG3-045",
            },
        )
        assert v.allowed is False
        assert v.violation_type == ViolationType.ARTIFACT_TAMPERING

    def test_change_frame_freeze_known_false_blocks_fail_closed(
        self, guard: ArtifactGuard
    ) -> None:
        """An explicitly-unknown freeze state (``known`` False) blocks too."""
        v = guard.evaluate(
            "file_write",
            {
                "file_path": "/repo/_temp/qa/AG3-045/change_frame.json",
                "operating_mode": "story_execution",
                "principal_kind": "subagent",
                "active_story_id": "AG3-045",
                "change_frame_frozen": False,
                "change_frame_freeze_known": False,
            },
        )
        assert v.allowed is False
        assert v.violation_type == ViolationType.ARTIFACT_TAMPERING

    def test_main_agent_may_write_frozen_change_frame(
        self, guard: ArtifactGuard
    ) -> None:
        """The freeze protection only targets sub-agents (same as QA artifacts)."""
        v = guard.evaluate(
            "file_write",
            {
                "file_path": "/repo/_temp/qa/AG3-045/change_frame.json",
                "operating_mode": "story_execution",
                "principal_kind": "main",
                "active_story_id": "AG3-045",
                "change_frame_frozen": True,
            },
        )
        assert v.allowed is True

    def test_other_story_frozen_change_frame_allows(
        self, guard: ArtifactGuard
    ) -> None:
        v = guard.evaluate(
            "file_write",
            {
                "file_path": "/repo/_temp/qa/AG3-099/change_frame.json",
                "operating_mode": "story_execution",
                "principal_kind": "subagent",
                "active_story_id": "AG3-045",
                "change_frame_frozen": True,
            },
        )
        assert v.allowed is True


class TestArtifactGuardAllowed:
    """Non-scoped or non-subagent writes must be allowed."""

    def test_write_normal_code(self, guard: ArtifactGuard) -> None:
        v = guard.evaluate("file_write", {"file_path": "/src/agentkit/main.py"})
        assert v.allowed is True

    def test_write_protocol_md(self, guard: ArtifactGuard) -> None:
        v = guard.evaluate("file_write", {"file_path": "/stories/AG3-001/protocol.md"})
        assert v.allowed is True

    def test_main_agent_may_write_qa_path(self, guard: ArtifactGuard) -> None:
        v = guard.evaluate(
            "file_write",
            {
                "file_path": "/repo/_temp/qa/AG3-001/structural.json",
                "operating_mode": "story_execution",
                "qa_artifact_lock_active": True,
                "principal_kind": "main",
                "active_story_id": "AG3-001",
            },
        )
        assert v.allowed is True

    def test_missing_qa_lock_blocks_fail_closed(self, guard: ArtifactGuard) -> None:
        v = guard.evaluate(
            "file_write",
            {
                "file_path": "/repo/_temp/qa/AG3-001/structural.json",
                "operating_mode": "story_execution",
                "qa_artifact_lock_active": False,
                "qa_artifact_lock_known": False,
                "principal_kind": "subagent",
                "active_story_id": "AG3-001",
            },
        )
        assert v.allowed is False
        assert v.violation_type == ViolationType.ARTIFACT_TAMPERING

    def test_inactive_known_qa_lock_allows(self, guard: ArtifactGuard) -> None:
        v = guard.evaluate(
            "file_write",
            {
                "file_path": "/repo/_temp/qa/AG3-001/structural.json",
                "operating_mode": "story_execution",
                "qa_artifact_lock_active": False,
                "qa_artifact_lock_known": True,
                "principal_kind": "subagent",
                "active_story_id": "AG3-001",
            },
        )
        assert v.allowed is True

    def test_other_story_qa_path_allows(self, guard: ArtifactGuard) -> None:
        v = guard.evaluate(
            "file_write",
            {
                "file_path": "/repo/_temp/qa/AG3-002/structural.json",
                "operating_mode": "story_execution",
                "qa_artifact_lock_active": True,
                "principal_kind": "subagent",
                "active_story_id": "AG3-001",
            },
        )
        assert v.allowed is True

    def test_non_write_operation(self, guard: ArtifactGuard) -> None:
        v = guard.evaluate("bash_command", {"command": "cat decision.json"})
        assert v.allowed is True

    def test_file_read_operation(self, guard: ArtifactGuard) -> None:
        ctx: dict[str, object] = {"file_path": "/repo/_temp/qa/AG3-001/structural.json"}
        v = guard.evaluate("file_read", ctx)
        assert v.allowed is True

    def test_guard_name(self, guard: ArtifactGuard) -> None:
        assert guard.name == "artifact_guard"
