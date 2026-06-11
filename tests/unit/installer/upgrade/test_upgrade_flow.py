"""Unit tests for the engine-driven upgrade flow (AG3-089 — AC3 / dry-run / idempotency).

Exercises ``run_upgrade`` as a FLOW/MODE on the AG3-088 ``ExecutionMode``:
* register mode performs the §51.3.2 ``.bak`` + write config migration;
* the three §51.3 scenarios are decided end-to-end against the registration;
* dry_run / verify are read-only (no mutation) — they return the WOULD-execute
  plan (FK-50 §50.2);
* an already-current config is idempotent (no migration, no ``.bak``).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
import yaml
from tests.unit.installer.upgrade.conftest import (
    InMemoryRegistrationRepo,
    register_project,
    write_valid_project_yaml,
)

from agentkit.installer.checkpoint_engine.execution_mode import ExecutionMode
from agentkit.installer.upgrade._digest import config_file_digest
from agentkit.installer.upgrade.config_migration import BACKUP_SUFFIX
from agentkit.installer.upgrade.footprint import CustomizationPreservationError
from agentkit.installer.upgrade.scenarios import UpgradeScenario
from agentkit.installer.upgrade.upgrade_flow import run_upgrade

if TYPE_CHECKING:
    from pathlib import Path


def test_run_upgrade_register_migrates_config_with_bak(
    tmp_path: Path, registration_repo: InMemoryRegistrationRepo
) -> None:
    """register mode migrates 3->4 and writes a ``.bak`` (§51.4, scenario 3b path)."""
    project_root = tmp_path / "proj"
    project_root.mkdir()
    config_path = write_valid_project_yaml(project_root, old_field=5)
    # Registered digest matches the on-disk config -> not a 3b "edited" case, but
    # the config_version still jumped, so the migration runs.
    register_project(
        registration_repo,
        project_root=project_root,
        project_key=project_root.stem,
        config_digest=config_file_digest(config_path),
    )

    result = run_upgrade(
        project_root,
        project_key=project_root.stem,
        target_config_version="4.0",
        registration_repo=registration_repo,  # type: ignore[arg-type]
        mode=ExecutionMode.REGISTER,
    )

    assert result.config_migrated is True
    assert result.config_target_version == "4.0"
    backup = config_path.with_name("project.yaml" + BACKUP_SUFFIX)
    assert backup.is_file()
    on_disk = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    assert on_disk["pipeline"]["config_version"] == "4.0"


def test_run_upgrade_scenario_3b_config_edited(
    tmp_path: Path, registration_repo: InMemoryRegistrationRepo
) -> None:
    """AC3b: a registered digest != on-disk hash -> CONFIG_EDITED scenario."""
    project_root = tmp_path / "proj"
    project_root.mkdir()
    write_valid_project_yaml(project_root)
    register_project(
        registration_repo,
        project_root=project_root,
        project_key=project_root.stem,
        config_digest="stale-registered-digest",
    )

    result = run_upgrade(
        project_root,
        project_key=project_root.stem,
        target_config_version="3.0",  # no version jump; only the digest changed
        registration_repo=registration_repo,  # type: ignore[arg-type]
        mode=ExecutionMode.VERIFY,  # read-only: decide only
    )

    assert result.scenario.scenario is UpgradeScenario.CONFIG_EDITED


def test_run_upgrade_scenario_3a_unchanged_skip(
    tmp_path: Path, registration_repo: InMemoryRegistrationRepo
) -> None:
    """AC3a: equal digest + unchanged bundle -> UNCHANGED, no mutation."""
    project_root = tmp_path / "proj"
    project_root.mkdir()
    config_path = write_valid_project_yaml(project_root)
    register_project(
        registration_repo,
        project_root=project_root,
        project_key=project_root.stem,
        config_digest=config_file_digest(config_path),
    )

    result = run_upgrade(
        project_root,
        project_key=project_root.stem,
        target_config_version="3.0",
        registration_repo=registration_repo,  # type: ignore[arg-type]
        bundle_version_changed=False,
        mode=ExecutionMode.REGISTER,
    )

    assert result.scenario.scenario is UpgradeScenario.UNCHANGED
    assert result.config_migrated is False
    assert result.mutated is False


def test_run_upgrade_scenario_3c_explicit_binding_switch(
    tmp_path: Path, registration_repo: InMemoryRegistrationRepo
) -> None:
    """AC3c: a new variant is adopted only on an explicit binding switch."""
    project_root = tmp_path / "proj"
    project_root.mkdir()
    config_path = write_valid_project_yaml(project_root)
    register_project(
        registration_repo,
        project_root=project_root,
        project_key=project_root.stem,
        config_digest=config_file_digest(config_path),
    )

    pulled = run_upgrade(
        project_root,
        project_key=project_root.stem,
        target_config_version="3.0",
        registration_repo=registration_repo,  # type: ignore[arg-type]
        bundle_version_changed=True,
        explicit_binding_switch=True,
        mode=ExecutionMode.VERIFY,
    )
    not_pulled = run_upgrade(
        project_root,
        project_key=project_root.stem,
        target_config_version="3.0",
        registration_repo=registration_repo,  # type: ignore[arg-type]
        bundle_version_changed=True,
        explicit_binding_switch=False,
        mode=ExecutionMode.VERIFY,
    )

    assert pulled.scenario.scenario is UpgradeScenario.NEW_VARIANT
    # AC3c negative: without the explicit switch a new variant is NOT pulled.
    assert not_pulled.scenario.scenario is not UpgradeScenario.NEW_VARIANT


def test_run_upgrade_dry_run_does_not_mutate(
    tmp_path: Path, registration_repo: InMemoryRegistrationRepo
) -> None:
    """dry_run plans the migration but writes NOTHING (FK-50 §50.2)."""
    project_root = tmp_path / "proj"
    project_root.mkdir()
    config_path = write_valid_project_yaml(project_root, old_field=1)
    before = config_path.read_text(encoding="utf-8")
    register_project(
        registration_repo,
        project_root=project_root,
        project_key=project_root.stem,
        config_digest=config_file_digest(config_path),
    )

    result = run_upgrade(
        project_root,
        project_key=project_root.stem,
        target_config_version="4.0",
        registration_repo=registration_repo,  # type: ignore[arg-type]
        mode=ExecutionMode.DRY_RUN,
    )

    assert result.config_migrated is False
    assert result.mutated is False
    assert "[plan]" in result.detail
    # No mutation: the config is byte-identical and no `.bak` was written.
    assert config_path.read_text(encoding="utf-8") == before
    assert not config_path.with_name("project.yaml" + BACKUP_SUFFIX).exists()


def test_run_upgrade_register_idempotent_when_already_current(
    tmp_path: Path, registration_repo: InMemoryRegistrationRepo
) -> None:
    """An already-current config is not migrated and writes no ``.bak`` (idempotency)."""
    project_root = tmp_path / "proj"
    project_root.mkdir()
    config_path = write_valid_project_yaml(project_root, config_version="4.0")
    register_project(
        registration_repo,
        project_root=project_root,
        project_key=project_root.stem,
        config_digest=config_file_digest(config_path),
    )

    result = run_upgrade(
        project_root,
        project_key=project_root.stem,
        target_config_version="4.0",
        registration_repo=registration_repo,  # type: ignore[arg-type]
        mode=ExecutionMode.REGISTER,
    )

    assert result.config_migrated is False
    assert not config_path.with_name("project.yaml" + BACKUP_SUFFIX).exists()


class _SkillsWithBinding:
    """Agent-skills surface double returning a binding for one skill (footprint src)."""

    def resolve_binding(self, project_root: Path, skill_name: str) -> object | None:
        from datetime import UTC, datetime

        from agentkit.skills.binding import (
            SkillBinding,
            SkillBindingMode,
            SkillLifecycleStatus,
        )

        if skill_name != "execute-userstory":
            return None
        return SkillBinding(
            binding_id="b1",
            project_key=project_root.stem,
            skill_name=skill_name,
            bundle_id="execute-userstory-custom",
            bundle_version="9.9.9",
            target_path=project_root / ".claude" / "skills" / skill_name,
            binding_mode=SkillBindingMode.SYMLINK,
            status=SkillLifecycleStatus.BOUND,
            pinned_at=datetime.now(tz=UTC),
        )


def test_run_upgrade_explicit_binding_switch_blocks_detected_customization(
    tmp_path: Path, registration_repo: InMemoryRegistrationRepo
) -> None:
    """AC8: a register-mode binding switch over a detected skill binding blocks.

    F-51-023 — the non-migrating binding write path consults the footprint and
    blocks fail-closed (no mutation) when it would overwrite a detected
    customization.
    """
    project_root = tmp_path / "proj"
    project_root.mkdir()
    config_path = write_valid_project_yaml(project_root)
    before = config_path.read_text(encoding="utf-8")
    register_project(
        registration_repo,
        project_root=project_root,
        project_key=project_root.stem,
        config_digest=config_file_digest(config_path),
    )

    with pytest.raises(CustomizationPreservationError):
        run_upgrade(
            project_root,
            project_key=project_root.stem,
            target_config_version="3.0",
            registration_repo=registration_repo,  # type: ignore[arg-type]
            bundle_version_changed=True,
            explicit_binding_switch=True,
            mode=ExecutionMode.REGISTER,
            skills=_SkillsWithBinding(),  # type: ignore[arg-type]
        )

    # F-51-023: nothing mutated — config untouched, no `.bak`.
    assert config_path.read_text(encoding="utf-8") == before
    assert not config_path.with_name("project.yaml" + BACKUP_SUFFIX).exists()
