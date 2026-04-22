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
    """Protected branch operations are blocked in story execution."""

    def test_push_to_main(self, guard: BranchGuard) -> None:
        v = guard.evaluate(
            "bash_command",
            {"command": "git push origin main", "operating_mode": "story_execution"},
        )
        assert v.allowed is False
        assert v.violation_type == ViolationType.BRANCH_VIOLATION

    def test_push_to_master(self, guard: BranchGuard) -> None:
        v = guard.evaluate(
            "bash_command",
            {"command": "git push origin master", "operating_mode": "story_execution"},
        )
        assert v.allowed is False
        assert v.violation_type == ViolationType.BRANCH_VIOLATION

    def test_checkout_to_main(self, guard: BranchGuard) -> None:
        v = guard.evaluate(
            "bash_command",
            {
                "command": "git checkout main",
                "operating_mode": "story_execution",
                "active_story_id": "AG3-001",
            },
        )
        assert v.allowed is False
        assert v.violation_type == ViolationType.BRANCH_VIOLATION

    def test_rebase_on_origin_main(self, guard: BranchGuard) -> None:
        v = guard.evaluate(
            "bash_command",
            {
                "command": "git rebase origin/main",
                "operating_mode": "story_execution",
                "active_story_id": "AG3-001",
            },
        )
        assert v.allowed is False
        assert v.violation_type == ViolationType.BRANCH_VIOLATION

    def test_push_to_non_story_branch_is_blocked_in_story_execution(
        self,
        guard: BranchGuard,
    ) -> None:
        v = guard.evaluate(
            "bash_command",
            {
                "command": "git push origin feature/AG3-001",
                "operating_mode": "story_execution",
                "active_story_id": "AG3-001",
            },
        )
        assert v.allowed is False
        assert v.violation_type == ViolationType.BRANCH_VIOLATION

    def test_switch_to_non_story_branch_is_blocked_in_story_execution(
        self,
        guard: BranchGuard,
    ) -> None:
        v = guard.evaluate(
            "bash_command",
            {
                "command": "git switch feature/AG3-001",
                "operating_mode": "story_execution",
                "active_story_id": "AG3-001",
            },
        )
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

    def test_push_to_story_branch_allowed_in_story_execution(
        self,
        guard: BranchGuard,
    ) -> None:
        v = guard.evaluate(
            "bash_command",
            {
                "command": "git push origin story/AG3-001",
                "operating_mode": "story_execution",
                "active_story_id": "AG3-001",
            },
        )
        assert v.allowed is True

    def test_push_to_main_allowed_outside_story_execution(
        self,
        guard: BranchGuard,
    ) -> None:
        v = guard.evaluate(
            "bash_command",
            {"command": "git push origin main", "operating_mode": "ai_augmented"},
        )
        assert v.allowed is True

    def test_official_control_plane_command_allowed(self, guard: BranchGuard) -> None:
        v = guard.evaluate(
            "bash_command",
            {
                "command": "agentkit run-phase closure --story AG3-001 --no-ff",
                "operating_mode": "story_execution",
            },
        )
        assert v.allowed is True

    def test_git_internal_file_mutation_is_blocked(self, guard: BranchGuard) -> None:
        v = guard.evaluate("file_write", {"file_path": "/repo/.git/index"})
        assert v.allowed is False
        assert v.violation_type == ViolationType.BRANCH_VIOLATION

    def test_git_checkout_file_restore_is_allowed(self, guard: BranchGuard) -> None:
        v = guard.evaluate(
            "bash_command",
            {
                "command": "git checkout -- src/main.py",
                "operating_mode": "story_execution",
            },
        )
        assert v.allowed is True

    def test_bash_git_internal_mutation_is_blocked(self, guard: BranchGuard) -> None:
        v = guard.evaluate(
            "bash_command",
            {"command": "Remove-Item .git/refs/heads/main"},
        )
        assert v.allowed is False
        assert v.violation_type == ViolationType.BRANCH_VIOLATION

    def test_guard_name(self, guard: BranchGuard) -> None:
        assert guard.name == "branch_guard"

    def test_missing_command_in_context(self, guard: BranchGuard) -> None:
        v = guard.evaluate("bash_command", {})
        assert v.allowed is True
