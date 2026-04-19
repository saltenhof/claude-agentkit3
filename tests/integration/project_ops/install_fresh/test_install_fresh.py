"""Integration tests for fresh AgentKit installation.

Tests the full install flow using real filesystem operations via
``tmp_path``.  Validates that the generated ``project.yaml`` is
loadable by :func:`agentkit.config.load_project_config`.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from agentkit.config import load_project_config
from agentkit.exceptions import ProjectError
from agentkit.installer import InstallConfig, InstallResult, install_agentkit


@pytest.mark.integration
class TestInstallFresh:
    """Test suite for fresh AgentKit installation into a target project."""

    def test_install_creates_agentkit_dir(self, tmp_path: object) -> None:
        """Install creates ``.agentkit/`` directory."""
        root = _as_path(tmp_path)
        config = InstallConfig(project_name="test-project", project_root=root)
        result = install_agentkit(config)
        assert result.success
        assert (root / ".agentkit").is_dir()

    def test_install_creates_project_yaml(self, tmp_path: object) -> None:
        """Install creates a ``project.yaml`` loadable by the config loader."""
        root = _as_path(tmp_path)
        config = InstallConfig(project_name="test-project", project_root=root)
        install_agentkit(config)
        # Must be loadable by our config loader
        project_config = load_project_config(root)
        assert project_config.project_name == "test-project"

    def test_install_creates_directory_structure(self, tmp_path: object) -> None:
        """Install creates prompt/runtime/story directories."""
        root = _as_path(tmp_path)
        config = InstallConfig(project_name="test-project", project_root=root)
        install_agentkit(config)
        assert (root / "prompts").is_dir()
        assert (root / ".agentkit" / "prompts").is_dir()
        assert (root / ".agentkit" / "hooks").is_dir()
        assert (root / "stories").is_dir()

    def test_install_fails_if_already_installed(self, tmp_path: object) -> None:
        """Double install raises :class:`ProjectError`."""
        root = _as_path(tmp_path)
        config = InstallConfig(project_name="test", project_root=root)
        install_agentkit(config)
        with pytest.raises(ProjectError):
            install_agentkit(config)

    def test_install_fails_if_root_missing(self, tmp_path: object) -> None:
        """Install into non-existent directory raises :class:`ProjectError`."""
        root = _as_path(tmp_path)
        config = InstallConfig(
            project_name="test",
            project_root=root / "nope",
        )
        with pytest.raises(ProjectError):
            install_agentkit(config)

    def test_install_with_repositories(self, tmp_path: object) -> None:
        """Install with custom repositories includes them in config."""
        root = _as_path(tmp_path)
        repos = [
            {"name": "backend", "path": "src/backend", "language": "python"},
        ]
        config = InstallConfig(
            project_name="test",
            project_root=root,
            repositories=repos,
        )
        install_agentkit(config)
        project_config = load_project_config(root)
        assert len(project_config.repositories) == 1
        assert project_config.repositories[0].name == "backend"

    def test_install_result_lists_created_files(self, tmp_path: object) -> None:
        """:class:`InstallResult` ``created_files`` lists all created entries."""
        root = _as_path(tmp_path)
        config = InstallConfig(project_name="test", project_root=root)
        result = install_agentkit(config)
        assert isinstance(result, InstallResult)
        assert len(result.created_files) > 0
        assert any("project.yaml" in f for f in result.created_files)

    def test_install_default_repositories(self, tmp_path: object) -> None:
        """Install without repositories defaults to a single ``app`` repo at ``.``."""
        root = _as_path(tmp_path)
        config = InstallConfig(project_name="test", project_root=root)
        install_agentkit(config)
        project_config = load_project_config(root)
        assert len(project_config.repositories) == 1
        assert project_config.repositories[0].name == "app"

    def test_install_default_story_types(self, tmp_path: object) -> None:
        """Install includes all four default story types."""
        root = _as_path(tmp_path)
        config = InstallConfig(project_name="test", project_root=root)
        install_agentkit(config)
        project_config = load_project_config(root)
        assert "implementation" in project_config.story_types
        assert "bugfix" in project_config.story_types
        assert "concept" in project_config.story_types
        assert "research" in project_config.story_types

    def test_install_default_pipeline_config(self, tmp_path: object) -> None:
        """Install sets correct pipeline defaults."""
        root = _as_path(tmp_path)
        config = InstallConfig(project_name="test", project_root=root)
        install_agentkit(config)
        project_config = load_project_config(root)
        assert project_config.pipeline.max_feedback_rounds == 3
        assert project_config.pipeline.max_remediation_rounds == 2
        assert project_config.pipeline.exploration_mode is True
        assert "structural" in project_config.pipeline.verify_layers

    def test_install_with_github_fields(self, tmp_path: object) -> None:
        """Install with GitHub owner/repo persists them in config."""
        root = _as_path(tmp_path)
        config = InstallConfig(
            project_name="test",
            project_root=root,
            github_owner="myorg",
            github_repo="myrepo",
        )
        install_agentkit(config)
        project_config = load_project_config(root)
        assert project_config.github_owner == "myorg"
        assert project_config.github_repo == "myrepo"


def _as_path(tmp_path: object) -> Path:
    """Cast pytest tmp_path fixture to Path for type safety."""
    if not isinstance(tmp_path, Path):  # pragma: no cover
        msg = f"Expected Path, got {type(tmp_path).__name__}"
        raise TypeError(msg)
    return tmp_path
