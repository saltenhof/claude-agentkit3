"""Tests for ArtifactGuard -- QA artifact tampering prevention."""

from __future__ import annotations

import pytest

from agentkit.governance.guards.artifact_guard import ArtifactGuard
from agentkit.governance.protocols import ViolationType


@pytest.fixture()
def guard() -> ArtifactGuard:
    return ArtifactGuard()


class TestArtifactGuardBlocked:
    """Writes to protected QA artifacts must be blocked."""

    @pytest.mark.parametrize("artifact", [
        "structural.json",
        "semantic-review.json",
        "guardrail.json",
        "verify-decision.json",
        "adversarial.json",
    ])
    def test_write_to_protected_artifact(
        self, guard: ArtifactGuard, artifact: str,
    ) -> None:
        v = guard.evaluate("file_write", {"file_path": f"/stories/AG3-001/{artifact}"})
        assert v.allowed is False
        assert v.violation_type == ViolationType.ARTIFACT_TAMPERING

    def test_edit_to_protected_artifact(self, guard: ArtifactGuard) -> None:
        v = guard.evaluate(
            "file_edit",
            {"file_path": "/stories/AG3-001/verify-decision.json"},
        )
        assert v.allowed is False
        assert v.violation_type == ViolationType.ARTIFACT_TAMPERING


class TestArtifactGuardAllowed:
    """Writes to non-protected files must be allowed."""

    def test_write_normal_code(self, guard: ArtifactGuard) -> None:
        v = guard.evaluate("file_write", {"file_path": "/src/agentkit/main.py"})
        assert v.allowed is True

    def test_write_protocol_md(self, guard: ArtifactGuard) -> None:
        v = guard.evaluate("file_write", {"file_path": "/stories/AG3-001/protocol.md"})
        assert v.allowed is True

    def test_non_write_operation(self, guard: ArtifactGuard) -> None:
        v = guard.evaluate("bash_command", {"command": "cat decision.json"})
        assert v.allowed is True

    def test_file_read_operation(self, guard: ArtifactGuard) -> None:
        ctx = {"file_path": "/stories/AG3-001/structural.json"}
        v = guard.evaluate("file_read", ctx)
        assert v.allowed is True

    def test_guard_name(self, guard: ArtifactGuard) -> None:
        assert guard.name == "artifact_guard"
