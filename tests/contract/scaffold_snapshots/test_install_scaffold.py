"""Contract tests for installed project scaffolding.

These tests verify that ``install_agentkit()`` produces a stable,
expected directory structure. Changes to the scaffold break these
tests -- forcing conscious review.

The expected structure is derived from
``src/agentkit/resources/target_project/`` (single source of truth)
plus the generated ``project.yaml``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from agentkit.config.loader import load_project_config
from agentkit.installer import InstallConfig, install_agentkit
from agentkit.installer.paths import PROMPT_BUNDLE_STORE_ENV

if TYPE_CHECKING:
    from pathlib import Path


@pytest.mark.contract
class TestInstallScaffoldContract:
    """Contract tests for the installed project scaffold structure."""

    def test_install_creates_expected_directories(
        self, tmp_path: Path,
    ) -> None:
        """Installed project has all expected directories."""
        install_agentkit(_make_install_config(
            tmp_path,
            project_name="contract-test",
        ))

        expected_dirs = [
            ".agentkit",
            ".agentkit/config",
            ".agentkit/prompts",
            ".agentkit/hooks",
            ".agentkit/manifests",
            ".claude",
            ".claude/context",
            ".claude/skills",
            "prompts",
            "stories",
        ]
        for d in expected_dirs:
            assert (tmp_path / d).is_dir(), (
                f"Missing expected directory: {d}"
            )
        assert (
            tmp_path / ".agentkit" / "config" / "prompt-bundle.lock.json"
        ).is_file()
        assert (tmp_path / "prompts" / "manifest.json").is_file()
        assert (tmp_path / "prompts" / "worker-implementation.md").is_file()

    def test_install_creates_project_yaml(self, tmp_path: Path) -> None:
        """Installed project has a valid, loadable project.yaml."""
        install_agentkit(_make_install_config(
            tmp_path,
            project_name="contract-test",
        ))
        config_file = tmp_path / ".agentkit" / "config" / "project.yaml"
        assert config_file.exists(), "project.yaml not created"

        # Must be loadable by the config loader
        config = load_project_config(tmp_path)
        assert config.project_name == "contract-test"
        assert config.project_key == "contract-test"

    def test_install_scaffold_is_deterministic(
        self, tmp_path: Path,
    ) -> None:
        """Install produces deterministic output -- same input, same output."""
        dir1 = tmp_path / "a"
        dir1.mkdir()
        dir2 = tmp_path / "b"
        dir2.mkdir()

        install_agentkit(_make_install_config(
            dir1,
            project_name="stable",
        ))
        install_agentkit(_make_install_config(
            dir2,
            project_name="stable",
        ))

        # Same directory structure
        dirs1 = sorted(
            str(p.relative_to(dir1))
            for p in dir1.rglob("*") if p.is_dir()
        )
        dirs2 = sorted(
            str(p.relative_to(dir2))
            for p in dir2.rglob("*") if p.is_dir()
        )
        assert dirs1 == dirs2, (
            f"Directory structures differ:\n"
            f"  dir1: {dirs1}\n"
            f"  dir2: {dirs2}"
        )

        # Same file set (by relative path)
        files1 = sorted(
            str(p.relative_to(dir1))
            for p in dir1.rglob("*") if p.is_file()
        )
        files2 = sorted(
            str(p.relative_to(dir2))
            for p in dir2.rglob("*") if p.is_file()
        )
        assert files1 == files2, (
            f"File sets differ:\n"
            f"  dir1: {files1}\n"
            f"  dir2: {files2}"
        )

    def test_install_project_yaml_has_required_fields(
        self, tmp_path: Path,
    ) -> None:
        """project.yaml must contain all fields needed by the pipeline."""
        install_agentkit(_make_install_config(
            tmp_path,
            project_name="contract-test",
        ))

        config = load_project_config(tmp_path)

        # Required fields for pipeline operation
        assert config.project_name == "contract-test"
        assert config.project_key == "contract-test"
        assert hasattr(config, "repositories")
        assert len(config.repositories) >= 1

    def test_double_install_is_rejected(self, tmp_path: Path) -> None:
        """Installing into an already-installed project raises ProjectError."""
        from agentkit.exceptions import ProjectError

        install_agentkit(_make_install_config(
            tmp_path,
            project_name="first",
        ))

        with pytest.raises(ProjectError, match="already installed"):
            install_agentkit(_make_install_config(
                tmp_path,
                project_name="second",
            ))

    def test_scaffold_matches_resource_directories(
        self, tmp_path: Path,
    ) -> None:
        """Installed directories must correspond to resources/target_project/.

        This test ensures the installer deploys from the single source
        of truth (resources/target_project/) and not from hardcoded paths.
        """
        from agentkit.installer.runner import (
            _resources_target_project_dir,
        )

        install_agentkit(_make_install_config(
            tmp_path,
            project_name="contract-test",
        ))

        resources_dir = _resources_target_project_dir()

        # Every non-template directory in resources must exist in the install
        for item in sorted(resources_dir.rglob("*")):
            rel = item.relative_to(resources_dir)
            # Skip templates -- they are rendered, not copied
            if rel.parts[0] == "templates":
                continue
            if item.is_dir():
                installed = tmp_path / rel
                assert installed.is_dir(), (
                    f"Resource directory '{rel}' not deployed to install"
                )


def _make_install_config(project_root: Path, **kwargs: object) -> InstallConfig:
    kwargs.setdefault("project_key", kwargs.get("project_name", "test-project"))
    return InstallConfig(
        project_root=project_root,
        **kwargs,
    )


@pytest.fixture(autouse=True)
def _set_prompt_bundle_store_env(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(
        PROMPT_BUNDLE_STORE_ENV,
        str(tmp_path.parent / ".prompt-bundle-store"),
    )
