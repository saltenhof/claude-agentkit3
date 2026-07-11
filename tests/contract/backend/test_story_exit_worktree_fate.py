"""SOLL-079 contract: story exit preserves worktrees and branches."""

from __future__ import annotations

import ast
from pathlib import Path

from agentkit.backend.story_exit import service as story_exit_service


def test_story_exit_has_no_teardown_worktree_command_or_physical_cleanup() -> None:
    source = Path(story_exit_service.__file__).read_text(encoding="utf-8")

    assert "teardown_worktree" not in source
    assert "worktree remove" not in source
    assert "shutil.rmtree" not in source


def test_deployed_projectedge_reuses_shared_takeover_executor_without_copy() -> None:
    repo_root = Path(__file__).resolve().parents[3]
    deployed = (
        repo_root
        / "src"
        / "agentkit"
        / "bundles"
        / "target_project"
        / "tools"
        / "agentkit"
        / "projectedge.py"
    ).read_text(encoding="utf-8")

    assert "process_open_commands" in deployed
    assert "takeover_reconcile" in deployed
    assert "def execute_takeover_reconcile" not in deployed
    assert "quarantine_worktree" not in deployed


def test_takeover_executor_has_no_stash_or_salvage_command_path() -> None:
    repo_root = Path(__file__).resolve().parents[3]
    source = (
        repo_root
        / "src"
        / "agentkit"
        / "harness_client"
        / "projectedge"
        / "reconcile.py"
    ).read_text(encoding="utf-8")
    string_literals = {
        node.value
        for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.Constant) and isinstance(node.value, str)
    }

    assert "stash" not in string_literals
    assert "salvage" not in string_literals
