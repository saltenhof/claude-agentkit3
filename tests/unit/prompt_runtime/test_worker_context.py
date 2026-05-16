"""Tests for worker worktree context composition."""

from __future__ import annotations

from pathlib import Path

import pytest

from agentkit.prompt_runtime import (
    ComposeConfig,
    build_worker_worktree_context,
    compose_prompt,
)
from agentkit.story_context_manager.models import StoryContext
from agentkit.story_context_manager.types import StoryMode, StoryType


def _context(
    *,
    participating_repos: list[str],
    worktree_map: dict[str, Path],
    worktree_path: Path | None = None,
    project_root: Path | None = Path("T:/target"),
) -> StoryContext:
    return StoryContext(
        project_key="test-project",
        story_id="AG3-011",
        story_type=StoryType.IMPLEMENTATION,
        execution_route=StoryMode.EXECUTION,
        title="Worker spawn",
        project_root=project_root,
        worktree_path=worktree_path,
        worktree_map=worktree_map,
        participating_repos=participating_repos,
    )


def test_single_repo_worker_context_renders_one_worktree_path() -> None:
    ctx = _context(
        participating_repos=["api"],
        worktree_path=Path("T:/target/api/worktrees/AG3-011"),
        worktree_map={"api": Path("T:/target/api/worktrees/AG3-011")},
    )

    worktree_context = build_worker_worktree_context(ctx)

    assert worktree_context.spawn_cwd == "T:/target/api/worktrees/AG3-011"
    assert worktree_context.worktree_map == {
        "api": "T:/target/api/worktrees/AG3-011",
    }
    assert "Worktree-Pfad: T:/target/api/worktrees/AG3-011" in (
        worktree_context.prompt_markdown
    )
    assert "Multi-Repo-Worktree-Map" not in worktree_context.prompt_markdown


def test_multi_repo_worker_context_renders_worktree_map() -> None:
    ctx = _context(
        participating_repos=["api", "web", "docs"],
        worktree_map={
            "api": Path("T:/target/api/worktrees/AG3-011"),
            "web": Path("T:/target/web/worktrees/AG3-011"),
            "docs": Path("T:/target/docs/worktrees/AG3-011"),
        },
    )

    worktree_context = build_worker_worktree_context(ctx)

    assert worktree_context.worktree_map == {
        "api": "T:/target/api/worktrees/AG3-011",
        "web": "T:/target/web/worktrees/AG3-011",
        "docs": "T:/target/docs/worktrees/AG3-011",
    }
    assert "| api | T:/target/api/worktrees/AG3-011 |" in (
        worktree_context.prompt_markdown
    )
    assert "| web | T:/target/web/worktrees/AG3-011 |" in (
        worktree_context.prompt_markdown
    )
    assert "| docs | T:/target/docs/worktrees/AG3-011 |" in (
        worktree_context.prompt_markdown
    )


def test_multi_repo_spawn_cwd_is_first_participating_repo() -> None:
    ctx = _context(
        participating_repos=["web", "api"],
        worktree_map={
            "api": Path("T:/target/api/worktrees/AG3-011"),
            "web": Path("T:/target/web/worktrees/AG3-011"),
        },
    )

    worktree_context = build_worker_worktree_context(ctx)

    assert worktree_context.spawn_cwd == "T:/target/web/worktrees/AG3-011"
    assert "Spawn-CWD: T:/target/web/worktrees/AG3-011" in (
        worktree_context.prompt_markdown
    )


def test_worker_prompt_contains_write_boundary_notice() -> None:
    ctx = _context(
        participating_repos=["api", "web"],
        project_root=None,
        worktree_map={
            "api": Path("T:/target/api/worktrees/AG3-011"),
            "web": Path("T:/target/web/worktrees/AG3-011"),
        },
    )

    prompt = compose_prompt(ctx, ComposeConfig(story_type=StoryType.IMPLEMENTATION))

    assert "Schreiben in nicht-teilnehmende Repos ist verboten" in prompt.content
    assert "| api | T:/target/api/worktrees/AG3-011 |" in prompt.content
    assert "Spawn-CWD: T:/target/api/worktrees/AG3-011" in prompt.content


@pytest.mark.parametrize(
    "repo_names",
    [["api"], ["api", "web"], ["api", "web", "docs"]],
)
def test_worker_prompt_renders_for_one_two_and_three_repos(
    repo_names: list[str],
) -> None:
    worktree_map = {
        repo_name: Path(f"T:/target/{repo_name}/worktrees/AG3-011")
        for repo_name in repo_names
    }
    ctx = _context(
        participating_repos=repo_names,
        project_root=None,
        worktree_path=worktree_map[repo_names[0]],
        worktree_map=worktree_map,
    )

    prompt = compose_prompt(ctx, ComposeConfig(story_type=StoryType.IMPLEMENTATION))

    assert "[SENTINEL:worker-implementation-v1:AG3-011]" in prompt.content
    assert f"Spawn-CWD: T:/target/{repo_names[0]}/worktrees/AG3-011" in (
        prompt.content
    )
