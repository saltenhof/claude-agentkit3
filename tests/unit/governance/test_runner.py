"""Tests for GuardRunner -- orchestration of governance guards."""

from __future__ import annotations

from agentkit.governance.guards.artifact_guard import ArtifactGuard
from agentkit.governance.guards.branch_guard import BranchGuard
from agentkit.governance.guards.scope_guard import ScopeGuard
from agentkit.governance.protocols import GuardVerdict, ViolationType
from agentkit.governance.runner import GuardRunner


class _AlwaysAllowGuard:
    """Test guard that always allows."""

    @property
    def name(self) -> str:
        return "always_allow"

    def evaluate(self, operation: str, context: dict[str, object]) -> GuardVerdict:
        return GuardVerdict.ALLOW(self.name)


class _AlwaysBlockGuard:
    """Test guard that always blocks."""

    @property
    def name(self) -> str:
        return "always_block"

    def evaluate(self, operation: str, context: dict[str, object]) -> GuardVerdict:
        return GuardVerdict.BLOCK(
            self.name, ViolationType.POLICY_VIOLATION, "blocked",
        )


class TestGuardRunnerAllAllow:
    """All guards allow -- operation is allowed."""

    def test_all_allow(self) -> None:
        runner = GuardRunner(guards=[_AlwaysAllowGuard(), _AlwaysAllowGuard()])
        allowed, verdicts = runner.is_allowed("any_op", {})
        assert allowed is True
        assert len(verdicts) == 2
        assert all(v.allowed for v in verdicts)


class TestGuardRunnerOneBlocks:
    """One guard blocks -- operation is blocked."""

    def test_one_block(self) -> None:
        runner = GuardRunner(guards=[_AlwaysAllowGuard(), _AlwaysBlockGuard()])
        allowed, verdicts = runner.is_allowed("any_op", {})
        assert allowed is False
        assert len(verdicts) == 2

    def test_block_first_still_runs_all(self) -> None:
        """All guards must run even when the first one blocks."""
        runner = GuardRunner(guards=[_AlwaysBlockGuard(), _AlwaysAllowGuard()])
        allowed, verdicts = runner.is_allowed("any_op", {})
        assert allowed is False
        assert len(verdicts) == 2
        # Second guard must have run and produced an ALLOW.
        assert verdicts[1].allowed is True


class TestGuardRunnerCollectAll:
    """Multiple blocking guards -- all violations collected."""

    def test_two_blocks(self) -> None:
        runner = GuardRunner(guards=[_AlwaysBlockGuard(), _AlwaysBlockGuard()])
        allowed, verdicts = runner.is_allowed("any_op", {})
        assert allowed is False
        assert len(verdicts) == 2
        assert all(not v.allowed for v in verdicts)


class TestGuardRunnerEmpty:
    """Empty runner -- no guards, everything allowed."""

    def test_empty_runner(self) -> None:
        runner = GuardRunner()
        allowed, verdicts = runner.is_allowed("any_op", {})
        assert allowed is True
        assert len(verdicts) == 0

    def test_empty_runner_evaluate(self) -> None:
        runner = GuardRunner()
        verdicts = runner.evaluate("any_op", {})
        assert verdicts == []


class TestGuardRunnerRegister:
    """Dynamic guard registration."""

    def test_register_adds_guard(self) -> None:
        runner = GuardRunner()
        runner.register(_AlwaysBlockGuard())
        allowed, verdicts = runner.is_allowed("any_op", {})
        assert allowed is False
        assert len(verdicts) == 1


class TestGuardRunnerWithRealGuards:
    """Integration-like test with real guard implementations."""

    def test_branch_and_artifact_guards(self) -> None:
        runner = GuardRunner(guards=[BranchGuard(), ArtifactGuard()])
        # Force push: BranchGuard blocks, ArtifactGuard allows.
        allowed, verdicts = runner.is_allowed(
            "bash_command", {"command": "git push --force"},
        )
        assert allowed is False
        assert verdicts[0].allowed is False
        assert verdicts[1].allowed is True

    def test_scope_guard_integration(self) -> None:
        runner = GuardRunner(guards=[ScopeGuard(allowed_paths=["/project"])])
        allowed, verdicts = runner.is_allowed(
            "file_write", {"file_path": "/etc/passwd"},
        )
        assert allowed is False
