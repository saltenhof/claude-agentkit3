"""Integration tests for fresh AgentKit installation.

Tests the full install flow using real filesystem operations via
``tmp_path``.  Validates that the generated ``project.yaml`` is
loadable by :func:`agentkit.config.load_project_config`.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from agentkit.config import load_project_config
from agentkit.exceptions import ProjectError
from agentkit.installer import InstallConfig, InstallResult, install_agentkit
from agentkit.installer.paths import (
    PROMPT_BUNDLE_STORE_ENV,
    prompt_bundle_store_dir,
)


@pytest.mark.integration
class TestInstallFresh:
    """Test suite for fresh AgentKit installation into a target project."""

    def test_install_creates_agentkit_dir(self, tmp_path: object) -> None:
        """Install creates ``.agentkit/`` directory."""
        root = _as_path(tmp_path)
        config = _make_install_config(root, project_name="test-project")
        result = install_agentkit(config)
        assert result.success
        assert (root / ".agentkit").is_dir()

    def test_install_creates_project_yaml(self, tmp_path: object) -> None:
        """Install creates a ``project.yaml`` loadable by the config loader."""
        root = _as_path(tmp_path)
        config = _make_install_config(root, project_name="test-project")
        install_agentkit(config)
        # Must be loadable by our config loader
        project_config = load_project_config(root)
        assert project_config.project_name == "test-project"
        assert project_config.project_key == "test-project"

    def test_install_creates_directory_structure(self, tmp_path: object) -> None:
        """Install creates prompt/runtime/story directories."""
        root = _as_path(tmp_path)
        config = _make_install_config(root, project_name="test-project")
        install_agentkit(config)
        assert (root / "prompts").is_dir()
        assert (root / "prompts" / "manifest.json").is_file()
        assert (root / "prompts" / "worker-implementation.md").is_file()
        assert (root / ".agentkit" / "config" / "prompt-bundle.lock.json").is_file()
        assert (root / ".agentkit" / "config" / "control-plane.json").is_file()
        assert (root / ".agentkit" / "prompts").is_dir()
        assert (root / ".agentkit" / "hooks").is_dir()
        assert (root / "stories").is_dir()
        assert (root / "tools" / "agentkit" / "projectedge.py").is_file()

    def test_install_creates_prompt_hardlink_binding(self, tmp_path: object) -> None:
        """Install binds project prompt files to bundled prompt resources."""

        root = _as_path(tmp_path)
        config = _make_install_config(root, project_name="test-project")
        install_agentkit(config)

        installed = root / "prompts" / "worker-implementation.md"
        bundled = (
            prompt_bundle_store_dir(
                "internal-bootstrap-prompts",
                "1",
                store_root=_prompt_bundle_store_root(root),
            )
            / "internal"
            / "prompts"
            / "worker-implementation.md"
        )
        assert installed.exists()
        assert bundled.exists()
        assert installed.samefile(bundled)

    def test_install_writes_prompt_bundle_lock(self, tmp_path: object) -> None:
        """Install persists a prompt-bundle lock for resolver preflight."""

        root = _as_path(tmp_path)
        install_agentkit(_make_install_config(root, project_name="test-project"))

        lock_path = root / ".agentkit" / "config" / "prompt-bundle.lock.json"
        lock = json.loads(lock_path.read_text(encoding="utf-8"))
        assert lock["bundle_id"] == "internal-bootstrap-prompts"
        assert lock["bundle_version"] == "1"
        assert lock["binding_root"] == "prompts"
        assert lock["manifest_file"] == "manifest.json"
        assert "manifest_sha256" in lock

    def test_install_fails_if_already_installed(self, tmp_path: object) -> None:
        """Double install raises :class:`ProjectError`."""
        root = _as_path(tmp_path)
        config = _make_install_config(root, project_name="test")
        install_agentkit(config)
        with pytest.raises(ProjectError):
            install_agentkit(config)

    def test_install_fails_if_root_missing(self, tmp_path: object) -> None:
        """Install into non-existent directory raises :class:`ProjectError`."""
        root = _as_path(tmp_path)
        config = InstallConfig(
            project_name="test",
            project_key="test",
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
        config = _make_install_config(
            root,
            project_name="test",
            repositories=repos,
        )
        install_agentkit(config)
        project_config = load_project_config(root)
        assert len(project_config.repositories) == 1
        assert project_config.repositories[0].name == "backend"

    def test_install_result_lists_created_files(self, tmp_path: object) -> None:
        """:class:`InstallResult` ``created_files`` lists all created entries."""
        root = _as_path(tmp_path)
        config = _make_install_config(root, project_name="test")
        result = install_agentkit(config)
        assert isinstance(result, InstallResult)
        assert len(result.created_files) > 0
        assert any("project.yaml" in f for f in result.created_files)

    def test_install_default_repositories(self, tmp_path: object) -> None:
        """Install without repositories defaults to a single ``app`` repo at ``.``."""
        root = _as_path(tmp_path)
        config = _make_install_config(root, project_name="test")
        install_agentkit(config)
        project_config = load_project_config(root)
        assert len(project_config.repositories) == 1
        assert project_config.repositories[0].name == "app"

    def test_install_default_story_types(self, tmp_path: object) -> None:
        """Install includes all four default story types."""
        root = _as_path(tmp_path)
        config = _make_install_config(root, project_name="test")
        install_agentkit(config)
        project_config = load_project_config(root)
        assert "implementation" in project_config.story_types
        assert "bugfix" in project_config.story_types
        assert "concept" in project_config.story_types
        assert "research" in project_config.story_types

    def test_install_default_pipeline_config(self, tmp_path: object) -> None:
        """Install sets correct pipeline defaults."""
        root = _as_path(tmp_path)
        config = _make_install_config(root, project_name="test")
        install_agentkit(config)
        project_config = load_project_config(root)
        assert project_config.pipeline.max_feedback_rounds == 3
        assert project_config.pipeline.max_remediation_rounds == 2
        assert project_config.pipeline.exploration_mode is True
        assert "structural" in project_config.pipeline.verify_layers

    def test_install_with_github_fields(self, tmp_path: object) -> None:
        """Install with GitHub owner/repo persists them in config."""
        root = _as_path(tmp_path)
        config = _make_install_config(
            root,
            project_name="test",
            github_owner="myorg",
            github_repo="myrepo",
        )
        install_agentkit(config)
        project_config = load_project_config(root)
        assert project_config.github_owner == "myorg"
        assert project_config.github_repo == "myrepo"

    def test_install_with_custom_prompt_bundle_root(self, tmp_path: object) -> None:
        """Install can bind prompts from an explicit external bundle root."""

        root = _as_path(tmp_path)
        bundle_root = root / "bundle-source"
        bundle_root.mkdir()
        (bundle_root / "manifest.json").write_text(
            json.dumps(
                {
                    "bundle_id": "external-prompts",
                    "bundle_version": "7",
                    "templates": {
                        "worker-implementation": {
                            "relpath": "internal/prompts/worker-implementation.md",
                            "sha256": (
                                "c547072c5eb412c5efc3da135fd02bd9"
                                "e3a0fcd3fef2df856653fbcb21f7ffdd"
                            ),
                        },
                    },
                },
            ),
            encoding="utf-8",
        )
        (bundle_root / "worker-implementation.md").write_text(
            "# External Prompt {story_id}\n"
            "[SENTINEL:worker-implementation-v1:{story_id}]\n",
            encoding="utf-8",
        )

        config = _make_install_config(
            root,
            project_name="test",
            prompt_bundle_root=bundle_root,
        )
        install_agentkit(config)

        lock_path = root / ".agentkit" / "config" / "prompt-bundle.lock.json"
        lock = json.loads(lock_path.read_text(encoding="utf-8"))
        assert lock["bundle_id"] == "external-prompts"
        assert lock["bundle_version"] == "7"
        canonical_root = prompt_bundle_store_dir(
            "external-prompts",
            "7",
            store_root=_prompt_bundle_store_root(root),
        )
        assert (canonical_root / "manifest.json").is_file()
        assert (root / "prompts" / "worker-implementation.md").samefile(
            canonical_root / "internal" / "prompts" / "worker-implementation.md",
        )


def _as_path(tmp_path: object) -> Path:
    """Cast pytest tmp_path fixture to Path for type safety."""
    if not isinstance(tmp_path, Path):  # pragma: no cover
        msg = f"Expected Path, got {type(tmp_path).__name__}"
        raise TypeError(msg)
    return tmp_path


def _make_install_config(project_root: Path, **kwargs: object) -> InstallConfig:
    kwargs.setdefault("project_key", kwargs.get("project_name", "test-project"))
    return InstallConfig(
        project_root=project_root,
        **kwargs,
    )


def _prompt_bundle_store_root(project_root: Path) -> Path:
    return project_root / ".prompt-bundle-store"


@pytest.fixture(autouse=True)
def _set_prompt_bundle_store_env(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(
        PROMPT_BUNDLE_STORE_ENV,
        str(_prompt_bundle_store_root(tmp_path)),
    )
