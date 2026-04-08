"""Tests for ScopeGuard -- write-scope enforcement."""

from __future__ import annotations

import os

from agentkit.governance.guards.scope_guard import ScopeGuard
from agentkit.governance.protocols import ViolationType


class TestScopeGuardAllowed:
    """Writes inside allowed_paths must be permitted."""

    def test_write_inside_allowed_path(self) -> None:
        guard = ScopeGuard(allowed_paths=["/project/worktree"])
        v = guard.evaluate("file_write", {"file_path": "/project/worktree/src/main.py"})
        assert v.allowed is True

    def test_edit_inside_allowed_path(self) -> None:
        guard = ScopeGuard(allowed_paths=["/project/worktree"])
        v = guard.evaluate("file_edit", {"file_path": "/project/worktree/src/main.py"})
        assert v.allowed is True

    def test_write_to_exact_allowed_path(self) -> None:
        # Edge case: file_path IS the allowed path itself.
        guard = ScopeGuard(allowed_paths=["/project/worktree"])
        v = guard.evaluate("file_write", {"file_path": "/project/worktree"})
        assert v.allowed is True

    def test_multiple_allowed_paths(self) -> None:
        guard = ScopeGuard(allowed_paths=["/a", "/b/c"])
        v = guard.evaluate("file_write", {"file_path": "/b/c/file.txt"})
        assert v.allowed is True


class TestScopeGuardBlocked:
    """Writes outside allowed_paths must be blocked."""

    def test_write_outside_allowed_path(self) -> None:
        guard = ScopeGuard(allowed_paths=["/project/worktree"])
        v = guard.evaluate("file_write", {"file_path": "/etc/passwd"})
        assert v.allowed is False
        assert v.violation_type == ViolationType.SCOPE_VIOLATION

    def test_empty_allowed_paths_blocks_all(self) -> None:
        guard = ScopeGuard(allowed_paths=[])
        v = guard.evaluate("file_write", {"file_path": "/any/path.py"})
        assert v.allowed is False
        assert v.violation_type == ViolationType.SCOPE_VIOLATION

    def test_none_allowed_paths_blocks_all(self) -> None:
        guard = ScopeGuard()
        v = guard.evaluate("file_write", {"file_path": "/any/path.py"})
        assert v.allowed is False
        assert v.violation_type == ViolationType.SCOPE_VIOLATION

    def test_partial_prefix_not_allowed(self) -> None:
        # /project/worktree-other is NOT inside /project/worktree.
        guard = ScopeGuard(allowed_paths=["/project/worktree"])
        v = guard.evaluate(
            "file_write",
            {"file_path": f"/project/worktree-other{os.sep}file.py"},
        )
        assert v.allowed is False


class TestScopeGuardNonWriteOps:
    """Non-write operations are always allowed."""

    def test_bash_command_allowed(self) -> None:
        guard = ScopeGuard()  # No allowed paths.
        v = guard.evaluate("bash_command", {"command": "ls"})
        assert v.allowed is True

    def test_read_operation_allowed(self) -> None:
        guard = ScopeGuard()
        v = guard.evaluate("file_read", {"file_path": "/etc/passwd"})
        assert v.allowed is True

    def test_guard_name(self) -> None:
        guard = ScopeGuard()
        assert guard.name == "scope_guard"
