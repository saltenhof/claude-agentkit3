"""Tests for BranchGuard -- dangerous git operation prevention."""

from __future__ import annotations

import pytest

from agentkit.governance.guards.branch_guard import BranchGuard
from agentkit.governance.protocols import ViolationType


@pytest.fixture()
def guard() -> BranchGuard:
    return BranchGuard()


class TestBranchGuardDangerousPatterns:
    """Every DANGEROUS_PATTERNS entry must produce a BLOCK."""

    def test_force_push_long(self, guard: BranchGuard) -> None:
        ctx = {"command": "git push --force origin feature"}
        v = guard.evaluate("bash_command", ctx)
        assert v.allowed is False
        assert v.violation_type == ViolationType.BRANCH_VIOLATION

    def test_force_push_short(self, guard: BranchGuard) -> None:
        v = guard.evaluate("bash_command", {"command": "git push -f origin feature"})
        assert v.allowed is False
        assert v.violation_type == ViolationType.BRANCH_VIOLATION

    def test_hard_reset(self, guard: BranchGuard) -> None:
        v = guard.evaluate("bash_command", {"command": "git reset --hard HEAD~1"})
        assert v.allowed is False
        assert v.violation_type == ViolationType.BRANCH_VIOLATION

    def test_force_delete_branch_short(self, guard: BranchGuard) -> None:
        v = guard.evaluate("bash_command", {"command": "git branch -D feature"})
        assert v.allowed is False
        assert v.violation_type == ViolationType.BRANCH_VIOLATION

    def test_force_delete_branch_long(self, guard: BranchGuard) -> None:
        ctx = {"command": "git branch --delete --force feature"}
        v = guard.evaluate("bash_command", ctx)
        assert v.allowed is False
        assert v.violation_type == ViolationType.BRANCH_VIOLATION


class TestBranchGuardProtectedBranches:
    """Direct pushes to protected branch names must be blocked."""

    def test_push_to_main(self, guard: BranchGuard) -> None:
        v = guard.evaluate("bash_command", {"command": "git push origin main"})
        assert v.allowed is False
        assert v.violation_type == ViolationType.BRANCH_VIOLATION

    def test_push_to_master(self, guard: BranchGuard) -> None:
        v = guard.evaluate("bash_command", {"command": "git push origin master"})
        assert v.allowed is False
        assert v.violation_type == ViolationType.BRANCH_VIOLATION

    def test_push_to_develop(self, guard: BranchGuard) -> None:
        v = guard.evaluate("bash_command", {"command": "git push origin develop"})
        assert v.allowed is False
        assert v.violation_type == ViolationType.BRANCH_VIOLATION


class TestBranchGuardAllowed:
    """Safe operations must be allowed."""

    def test_normal_git_commit(self, guard: BranchGuard) -> None:
        v = guard.evaluate("bash_command", {"command": "git commit -m 'fix'"})
        assert v.allowed is True

    def test_non_git_command(self, guard: BranchGuard) -> None:
        v = guard.evaluate("bash_command", {"command": "ls -la"})
        assert v.allowed is True

    def test_non_bash_operation(self, guard: BranchGuard) -> None:
        v = guard.evaluate("file_write", {"file_path": "/some/file.py"})
        assert v.allowed is True

    def test_push_to_feature_branch(self, guard: BranchGuard) -> None:
        ctx = {"command": "git push origin feature/AG3-001"}
        v = guard.evaluate("bash_command", ctx)
        assert v.allowed is True

    def test_guard_name(self, guard: BranchGuard) -> None:
        assert guard.name == "branch_guard"

    def test_missing_command_in_context(self, guard: BranchGuard) -> None:
        v = guard.evaluate("bash_command", {})
        assert v.allowed is True
