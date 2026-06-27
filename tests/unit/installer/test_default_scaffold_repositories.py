"""Unit coverage for default-scaffold repository materialisation."""

from __future__ import annotations

from pathlib import Path

import pytest

from agentkit.backend.exceptions import ProjectError
from agentkit.backend.installer.runner import (
    InstallConfig,
    _build_repo_entries,
    _ensure_default_scaffold_gitkeep,
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


def test_single_repo_default_scaffold_tracks_empty_persistent_dirs(
    tmp_path: Path,
) -> None:
    config = _config(default_project_structure=True)

    changed = _ensure_default_scaffold_gitkeep(config, tmp_path)

    normalized = sorted(path.replace("\\", "/") for path in changed)
    assert normalized == [
        "codebase/.gitkeep",
        "concepts/.gitkeep",
        "guardrails/.gitkeep",
        "input/.gitkeep",
        "input/_meetings/.gitkeep",
        "stories/.gitkeep",
    ]
    assert not (tmp_path / "temp" / ".gitkeep").exists()


def test_multi_repo_default_scaffold_does_not_track_codebase_root(
    tmp_path: Path,
) -> None:
    config = _config(
        default_project_structure=True,
        multi_repo=True,
        repositories=[{"name": "frontend", "path": "codebase/frontend"}],
    )

    changed = _ensure_default_scaffold_gitkeep(config, tmp_path)

    assert "codebase/.gitkeep" not in {path.replace("\\", "/") for path in changed}
    assert (tmp_path / "concepts" / ".gitkeep").is_file()


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
