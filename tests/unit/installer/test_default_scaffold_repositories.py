"""Unit coverage for default-scaffold repository materialisation."""

from __future__ import annotations

from pathlib import Path

import pytest

from agentkit.backend.exceptions import ProjectError
from agentkit.backend.installer.runner import (
    InstallConfig,
    _build_repo_entries,
    _materialize_scaffold_repo_dir,
)


def _config(**kwargs: object) -> InstallConfig:
    return InstallConfig(
        project_key="p",
        project_name="p",
        project_root=Path("."),
        github_owner="acme",
        github_repo="demo",
        sonarqube_available=False,
        ci_available=False,
        **kwargs,
    )


def test_multi_repo_without_explicit_repos_fails_closed() -> None:
    config = _config(default_project_structure=True, multi_repo=True)

    with pytest.raises(ProjectError, match="requires explicit code repositories"):
        _build_repo_entries(config)


def test_single_repo_default_uses_codebase_without_subdir() -> None:
    config = _config(default_project_structure=True)

    assert _build_repo_entries(config) == [{"name": "app", "path": "codebase"}]


def test_existing_git_repo_dir_is_skipped(tmp_path: Path) -> None:
    target = tmp_path / "codebase" / "frontend"
    target.mkdir(parents=True)
    (target / ".git").mkdir()

    result = _materialize_scaffold_repo_dir(
        tmp_path, {"name": "frontend", "path": "codebase/frontend"}
    )

    assert result is None


def test_non_empty_non_git_clone_target_fails_closed(tmp_path: Path) -> None:
    target = tmp_path / "codebase" / "frontend"
    target.mkdir(parents=True)
    (target / "notes.txt").write_text("not a repo\n", encoding="utf-8")

    with pytest.raises(ProjectError, match="non-empty and not a Git repo"):
        _materialize_scaffold_repo_dir(
            tmp_path,
            {
                "name": "frontend",
                "path": "codebase/frontend",
                "remote_url": "https://example.invalid/frontend.git",
            },
        )
