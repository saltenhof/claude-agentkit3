"""Unit tests for multi-repository setup worktree handling."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING
from unittest.mock import call, patch

import pytest

from agentkit.config.models import (
    SUPPORTED_CONFIG_VERSION,
    Features,
    JenkinsConfig,
    PipelineConfig,
    ProjectConfig,
    RepositoryConfig,
    SonarQubeConfig,
)
from agentkit.exceptions import WorktreeError
from agentkit.governance.setup_preflight_gate.worktree import (
    RepoNotFoundError,
    setup_worktree,
    setup_worktrees,
)
from agentkit.story_context_manager.models import StoryContext
from agentkit.story_context_manager.types import StoryMode, StoryType

if TYPE_CHECKING:
    from pathlib import Path


def _project_config(tmp_path: Path, repo_names: list[str]) -> ProjectConfig:
    return ProjectConfig(
        project_key="test-project",
        project_name="Test Project",
        repositories=[
            RepositoryConfig(name=repo_name, path=tmp_path / repo_name)
            for repo_name in repo_names
        ],
        # AG3-052 E6 / AG3-056: code-producing default story_types => declare
        # the sonarqube + ci stanzas explicitly (opt-outs here).
        pipeline=PipelineConfig(  # type: ignore[call-arg]
            config_version=SUPPORTED_CONFIG_VERSION,
            features=Features(multi_llm=False),
            sonarqube=SonarQubeConfig(available=False, enabled=False),
            ci=JenkinsConfig(available=False, enabled=False),
        ),
    )


def _story_context(repo_names: list[str]) -> StoryContext:
    return StoryContext(
        project_key="test-project",
        story_id="AG3-010",
        story_type=StoryType.IMPLEMENTATION,
        execution_route=StoryMode.EXPLORATION,
        title="Multi repo setup",
        participating_repos=repo_names,
    )


@pytest.mark.parametrize("repo_names", [["api"], ["api", "web"], ["api", "web", "docs"]])
def test_setup_worktrees_creates_one_worktree_per_participating_repo(
    tmp_path: Path,
    repo_names: list[str],
) -> None:
    project = _project_config(tmp_path, repo_names)
    context = _story_context(repo_names)

    with (
        patch(
            "agentkit.governance.setup_preflight_gate.worktree.branch_exists",
            return_value=False,
        ),
        patch("agentkit.governance.setup_preflight_gate.worktree.create_worktree") as create,
    ):
        results = setup_worktrees(
            "AG3-010",
            context,
            project,
            project_root=tmp_path,
        )

    assert [result.repo_name for result in results] == repo_names
    assert [result.branch for result in results] == ["story/AG3-010"] * len(repo_names)
    assert create.call_count == len(repo_names)
    for repo_name in repo_names:
        create.assert_any_call(
            repo_root=tmp_path / repo_name,
            worktree_path=tmp_path / repo_name / "worktrees" / "AG3-010",
            branch="story/AG3-010",
            base_ref="main",
        )
        marker = tmp_path / repo_name / "worktrees" / "AG3-010" / ".agentkit-story.json"
        payload = json.loads(marker.read_text(encoding="utf-8"))
        assert payload["story_id"] == "AG3-010"
        assert payload["project_key"] == "test-project"
        assert payload["run_id"] == "AG3-010"
        assert "created_at" in payload


def test_setup_worktrees_fails_for_unknown_participating_repo(
    tmp_path: Path,
) -> None:
    project = _project_config(tmp_path, ["api"])
    context = _story_context(["api", "missing"])

    with (
        patch(
            "agentkit.governance.setup_preflight_gate.worktree.branch_exists",
            return_value=False,
        ),
        patch("agentkit.governance.setup_preflight_gate.worktree.create_worktree"),
        patch("agentkit.governance.setup_preflight_gate.worktree.remove_worktree") as remove,
        pytest.raises(RepoNotFoundError, match="missing"),
    ):
        setup_worktrees("AG3-010", context, project, project_root=tmp_path)

    remove.assert_called_once_with(
        tmp_path / "api",
        tmp_path / "api" / "worktrees" / "AG3-010",
    )


def test_setup_worktree_fails_when_story_branch_already_exists(
    tmp_path: Path,
) -> None:
    repo = RepositoryConfig(name="api", path=tmp_path / "api")

    with (
        patch(
            "agentkit.governance.setup_preflight_gate.worktree.branch_exists",
            return_value=True,
        ),
        patch("agentkit.governance.setup_preflight_gate.worktree.create_worktree") as create,
        pytest.raises(WorktreeError, match="Story branch already exists"),
    ):
        setup_worktree(
            "AG3-010",
            repo,
            repo_root=tmp_path / "api",
        )

    create.assert_not_called()


def test_setup_worktrees_cleans_up_previous_repos_on_later_failure(
    tmp_path: Path,
) -> None:
    project = _project_config(tmp_path, ["api", "web", "docs"])
    context = _story_context(["api", "web", "docs"])

    def _create_side_effect(
        *,
        repo_root: Path,
        worktree_path: Path,
        branch: str,
        base_ref: str | None,
    ) -> None:
        _ = worktree_path, branch, base_ref
        if repo_root == tmp_path / "docs":
            raise WorktreeError("boom")

    with (
        patch(
            "agentkit.governance.setup_preflight_gate.worktree.branch_exists",
            return_value=False,
        ),
        patch(
            "agentkit.governance.setup_preflight_gate.worktree.create_worktree",
            side_effect=_create_side_effect,
        ),
        patch("agentkit.governance.setup_preflight_gate.worktree.remove_worktree") as remove,
        pytest.raises(WorktreeError, match="boom"),
    ):
        setup_worktrees("AG3-010", context, project, project_root=tmp_path)

    assert remove.call_args_list == [
        call(tmp_path / "web", tmp_path / "web" / "worktrees" / "AG3-010"),
        call(tmp_path / "api", tmp_path / "api" / "worktrees" / "AG3-010"),
    ]
