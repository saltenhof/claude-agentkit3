"""Fail-closed / edge-branch coverage for the upgrade package (AG3-089 §5).

Exercises the guardrail branches the happy-path tests do not reach: the digest
helper's missing/malformed-config errors, the footprint's "no on-disk config /
unreadable config" tolerance, and the upgrade flow's no-registration path.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from tests.unit.installer.upgrade.conftest import (
    InMemoryRegistrationRepo,
    register_project,
    write_valid_project_yaml,
)

from agentkit.backend.exceptions import ConfigError
from agentkit.backend.installer.checkpoint_engine.execution_mode import ExecutionMode
from agentkit.backend.installer.upgrade._digest import config_file_digest
from agentkit.backend.installer.upgrade.footprint import (
    CustomizationFootprint,
    CustomizationKind,
)
from agentkit.backend.installer.upgrade.upgrade_flow import run_upgrade

if TYPE_CHECKING:
    from pathlib import Path


def test_config_file_digest_missing_file_fails_closed(tmp_path: Path) -> None:
    """The digest helper rejects a missing config file fail-closed."""
    with pytest.raises(ConfigError):
        config_file_digest(tmp_path / "absent.yaml")


def test_config_file_digest_non_mapping_fails_closed(tmp_path: Path) -> None:
    """The digest helper rejects a non-mapping YAML config fail-closed."""
    bad = tmp_path / "project.yaml"
    bad.write_text("- a\n- b\n", encoding="utf-8")

    with pytest.raises(ConfigError):
        config_file_digest(bad)


def test_config_file_digest_invalid_yaml_fails_closed(tmp_path: Path) -> None:
    """The digest helper rejects invalid YAML fail-closed."""
    bad = tmp_path / "project.yaml"
    bad.write_text("key: [unterminated\n", encoding="utf-8")

    with pytest.raises(ConfigError):
        config_file_digest(bad)


def test_footprint_pipeline_config_absent_on_disk_no_point(
    tmp_path: Path, registration_repo: InMemoryRegistrationRepo
) -> None:
    """A registration with NO on-disk config yields no pipeline-config point."""
    project_root = tmp_path / "proj"
    project_root.mkdir()
    register_project(
        registration_repo,
        project_root=project_root,
        project_key=project_root.stem,
        config_digest="some-digest",
    )

    footprint = CustomizationFootprint.detect(
        project_root,
        registration_repo=registration_repo,  # type: ignore[arg-type]
        project_key=project_root.stem,
    )

    assert footprint.points_of(CustomizationKind.PIPELINE_CONFIG) == ()


def test_footprint_pipeline_config_unreadable_config_no_point(
    tmp_path: Path, registration_repo: InMemoryRegistrationRepo
) -> None:
    """An unreadable (non-mapping) on-disk config yields no pipeline-config point."""
    from agentkit.backend.installer.paths import project_config_path

    project_root = tmp_path / "proj"
    project_root.mkdir()
    config_path = project_config_path(project_root)
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text("- not\n- a\n- mapping\n", encoding="utf-8")
    register_project(
        registration_repo,
        project_root=project_root,
        project_key=project_root.stem,
        config_digest="some-digest",
    )

    footprint = CustomizationFootprint.detect(
        project_root,
        registration_repo=registration_repo,  # type: ignore[arg-type]
        project_key=project_root.stem,
    )

    assert footprint.points_of(CustomizationKind.PIPELINE_CONFIG) == ()


def test_backup_config_file_oserror_fails_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A backup write failure fails closed (no migration without a recoverable bak)."""
    import shutil

    from agentkit.backend.installer.upgrade.config_migration import (
        ConfigMigrationError,
        backup_config_file,
    )

    config = tmp_path / "project.yaml"
    config.write_text("config_version: '3.0'\n", encoding="utf-8")

    def _boom(*_args: object, **_kwargs: object) -> None:
        raise OSError("disk full")

    monkeypatch.setattr(shutil, "copy2", _boom)
    with pytest.raises(ConfigMigrationError):
        backup_config_file(config)


def test_build_skills_surface_returns_none_on_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A skills surface that cannot be built degrades to ``None`` (read-only)."""
    import agentkit.backend.state_backend.store.skill_binding_repository as repo_mod
    from agentkit.backend.installer.upgrade._skills_surface import build_skills_surface

    def _boom(*_args: object, **_kwargs: object) -> object:
        raise RuntimeError("no state backend")

    monkeypatch.setattr(
        repo_mod, "StateBackendSkillBindingRepository", _boom
    )
    assert build_skills_surface(tmp_path) is None


def test_run_upgrade_no_registration_uses_empty_digest(
    tmp_path: Path, registration_repo: InMemoryRegistrationRepo
) -> None:
    """An unregistered project upgrades against an empty registered digest.

    With no registration the on-disk digest != "" -> CONFIG_EDITED is decided,
    but the read-only verify mode performs no mutation.
    """
    project_root = tmp_path / "proj"
    project_root.mkdir()
    write_valid_project_yaml(project_root)

    result = run_upgrade(
        project_root,
        project_key=project_root.stem,
        target_config_version="3.0",
        registration_repo=registration_repo,  # type: ignore[arg-type]
        mode=ExecutionMode.VERIFY,
    )

    assert result.mutated is False
    assert result.footprint.is_empty  # no registration -> no pipeline-config point
