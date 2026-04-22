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
                "is_subagent": True,
                "active_story_id": "AG3-001",
            },
        )
        assert v.allowed is False
        assert v.violation_type == ViolationType.ARTIFACT_TAMPERING

    def test_subagent_edit_to_active_story_qa_path(self, guard: ArtifactGuard) -> None:
        v = guard.evaluate(
            "file_edit",
            {
                "file_path": "/repo/_temp/qa/AG3-001/verify-decision.json",
                "operating_mode": "story_execution",
                "qa_artifact_lock_active": True,
                "is_subagent": True,
                "active_story_id": "AG3-001",
            },
        )
        assert v.allowed is False
        assert v.violation_type == ViolationType.ARTIFACT_TAMPERING


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
                "is_subagent": False,
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
                "is_subagent": True,
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
                "is_subagent": True,
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
                "is_subagent": True,
                "active_story_id": "AG3-001",
            },
        )
        assert v.allowed is True

    def test_non_write_operation(self, guard: ArtifactGuard) -> None:
        v = guard.evaluate("bash_command", {"command": "cat decision.json"})
        assert v.allowed is True

    def test_file_read_operation(self, guard: ArtifactGuard) -> None:
        ctx = {"file_path": "/repo/_temp/qa/AG3-001/structural.json"}
        v = guard.evaluate("file_read", ctx)
        assert v.allowed is True

    def test_guard_name(self, guard: ArtifactGuard) -> None:
        assert guard.name == "artifact_guard"
