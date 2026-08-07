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

from agentkit.backend.config.models import ProjectConfig
from agentkit.backend.governance.hook_registration import RegistrationResult
from agentkit.backend.installer.checkpoint_engine.execution_mode import ExecutionMode
from agentkit.backend.installer.upgrade._digest import config_file_digest
from agentkit.backend.installer.upgrade.config_migration import (
    BACKUP_SUFFIX,
    ConfigMigrationError,
)
from agentkit.backend.installer.upgrade.footprint import CustomizationPreservationError
from agentkit.backend.installer.upgrade.scenarios import UpgradeScenario
from agentkit.backend.installer.upgrade.upgrade_flow import run_upgrade

if TYPE_CHECKING:
    from datetime import datetime
    from pathlib import Path

    from agentkit.backend.skills.binding import SkillBinding
    from agentkit_wire.governance_registration import HookDefinition


class _CrashOnceRegistrationRepo(InMemoryRegistrationRepo):
    """Simulate process loss immediately before digest persistence once."""

    def __init__(self) -> None:
        super().__init__()
        self.crash_next_upgrade = True

    def update_upgraded(
        self,
        project_key: str,
        upgraded_at: datetime,
        new_digest: str,
    ) -> None:
        if self.crash_next_upgrade:
            self.crash_next_upgrade = False
            raise RuntimeError("simulated process crash before digest persistence")
        super().update_upgraded(project_key, upgraded_at, new_digest)


class _ConfigEditingGovernance:
    """Edit project.yaml after UP01 while the later hook checkpoint runs."""

    def __init__(self, config_path: Path) -> None:
        self.config_path = config_path

    def register_hooks(
        self,
        hook_definitions: list[HookDefinition],
    ) -> RegistrationResult:
        config = yaml.safe_load(self.config_path.read_text(encoding="utf-8"))
        config["user_change_after_witness"] = True
        self.config_path.write_text(
            yaml.dump(config, sort_keys=False),
            encoding="utf-8",
        )
        return RegistrationResult(
            registered=[definition.matcher for definition in hook_definitions],
            skipped=[],
        )


class _ConfigEditingSkills:
    """Edit project.yaml in UP02, after UP01 captured its witness digest."""

    def __init__(self, config_path: Path) -> None:
        self.config_path = config_path

    def resolve_binding(
        self,
        project_root: Path,
        skill_name: str,
    ) -> SkillBinding | None:
        return None

    def list_bound_skills(self, project_root: Path) -> list[SkillBinding]:
        config = yaml.safe_load(self.config_path.read_text(encoding="utf-8"))
        pipeline = config["pipeline"]
        pipeline["permissions"] = {"request_ttl_s": 1800}
        pipeline["user_change_between_checkpoints"] = "preserve"
        self.config_path.write_text(
            yaml.dump(config, sort_keys=False),
            encoding="utf-8",
        )
        return []


class _ConfigDeletingSkills:
    """Remove project.yaml in UP02, after UP01 captured its witness."""

    def __init__(self, config_path: Path) -> None:
        self.config_path = config_path

    def resolve_binding(
        self,
        project_root: Path,
        skill_name: str,
    ) -> SkillBinding | None:
        return None

    def list_bound_skills(self, project_root: Path) -> list[SkillBinding]:
        self.config_path.unlink()
        return []


class _ConfigFormattingSkills:
    """Change only project.yaml bytes in UP02 after witness detection."""

    def __init__(self, config_path: Path) -> None:
        self.config_path = config_path

    def resolve_binding(
        self,
        project_root: Path,
        skill_name: str,
    ) -> SkillBinding | None:
        return None

    def list_bound_skills(self, project_root: Path) -> list[SkillBinding]:
        self.config_path.write_bytes(
            self.config_path.read_bytes() + b"# user formatting change\n",
        )
        return []


def _symlink_file_or_skip(link: Path, target: Path) -> None:
    """Create a real file symlink or skip where the host forbids it."""
    try:
        link.symlink_to(target)
    except OSError as exc:
        pytest.skip(f"file symlinks unavailable: {exc}")


def test_run_upgrade_register_migrates_config_with_bak(tmp_path: Path, registration_repo: InMemoryRegistrationRepo) -> None:
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
    stored = registration_repo.get(project_root.stem)
    assert stored is not None
    assert registration_repo.upgrade_calls == 1
    assert stored.config_digest == config_file_digest(config_path)


def test_run_upgrade_enables_historical_vectordb_and_reports_behavior_change(
    tmp_path: Path,
    registration_repo: InMemoryRegistrationRepo,
) -> None:
    """The productive flow repairs E4 and names project, field, and behavior."""
    project_root = tmp_path / "vectordb-history"
    project_root.mkdir()
    config_path = write_valid_project_yaml(
        project_root,
        extra_pipeline={
            "features": {
                "multi_llm": False,
                "vectordb": False,
                "telemetry": False,
            },
            "review": {"required_roles": []},
        },
    )
    before = config_path.read_bytes()
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
        mode=ExecutionMode.REGISTER,
    )

    assert result.config_migrated is True
    assert repr(project_root.stem) in result.detail
    assert str(project_root) in result.detail
    assert "pipeline.features.vectordb from false to true" in result.detail
    assert "changed project behavior from disabled to enabled" in result.detail
    backup = config_path.with_name("project.yaml" + BACKUP_SUFFIX)
    assert backup.read_bytes() == before
    on_disk = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    assert on_disk["pipeline"]["features"] == {
        "multi_llm": False,
        "vectordb": True,
        "telemetry": False,
    }
    assert on_disk["pipeline"]["review"] == {"required_roles": []}
    ProjectConfig.model_validate(on_disk)
    stored = registration_repo.get(project_root.stem)
    assert stored is not None
    assert stored.config_digest == config_file_digest(config_path)


def test_vectordb_migration_rejects_linked_staging_path(
    tmp_path: Path,
    registration_repo: InMemoryRegistrationRepo,
) -> None:
    """E4 uses the same project-local symlink-safe atomic-write boundary."""
    project_root = tmp_path / "vectordb-symlink"
    project_root.mkdir()
    config_path = write_valid_project_yaml(
        project_root,
        extra_pipeline={"features": {"multi_llm": False, "vectordb": False}},
    )
    before = config_path.read_bytes()
    register_project(
        registration_repo,
        project_root=project_root,
        project_key=project_root.stem,
        config_digest=config_file_digest(config_path),
    )
    external = tmp_path / "external-vectordb-rewrite"
    external.write_bytes(b"external bytes\n")
    external_before = external.read_bytes()
    _symlink_file_or_skip(config_path.with_name("project.yaml.tmp"), external)

    with pytest.raises(ConfigMigrationError):
        run_upgrade(
            project_root,
            project_key=project_root.stem,
            target_config_version="3.0",
            registration_repo=registration_repo,  # type: ignore[arg-type]
        )

    assert config_path.read_bytes() == before
    assert external.read_bytes() == external_before
    assert not config_path.with_name("project.yaml.bak").exists()


def test_vectordb_migration_resumes_digest_persistence_from_exact_witness(
    tmp_path: Path,
) -> None:
    """E4 inherits the R8 crash witness and persists the migrated digest."""
    project_root = tmp_path / "vectordb-resume"
    project_root.mkdir()
    config_path = write_valid_project_yaml(
        project_root,
        extra_pipeline={"features": {"multi_llm": False, "vectordb": False}},
    )
    original_digest = config_file_digest(config_path)
    registration_repo = _CrashOnceRegistrationRepo()
    register_project(
        registration_repo,
        project_root=project_root,
        project_key=project_root.stem,
        config_digest=original_digest,
    )

    with pytest.raises(RuntimeError, match="simulated process crash"):
        run_upgrade(
            project_root,
            project_key=project_root.stem,
            target_config_version="3.0",
            registration_repo=registration_repo,  # type: ignore[arg-type]
        )

    migrated_digest = config_file_digest(config_path)
    assert migrated_digest != original_digest
    assert yaml.safe_load(config_path.read_text(encoding="utf-8"))["pipeline"][
        "features"
    ]["vectordb"] is True

    resumed = run_upgrade(
        project_root,
        project_key=project_root.stem,
        target_config_version="3.0",
        registration_repo=registration_repo,  # type: ignore[arg-type]
    )

    assert resumed.config_migration_resumed is True
    assert "Project 'vectordb-resume'" in resumed.detail
    assert str(project_root) in resumed.detail
    assert "pipeline.features.vectordb changed from false to true" in resumed.detail
    assert "interrupted upgrade changed project behavior" in resumed.detail
    assert "disabled to enabled" in resumed.detail
    assert "Exact backup witness verified; digest persistence resumes" in resumed.detail
    assert registration_repo.upgrade_calls == 1
    stored = registration_repo.get(project_root.stem)
    assert stored is not None
    assert stored.config_digest == migrated_digest


def test_upgrade_rejects_project_yaml_tmp_symlink_without_external_write(
    tmp_path: Path,
    registration_repo: InMemoryRegistrationRepo,
) -> None:
    """A linked rewrite staging path blocks before backup and external writes."""
    project_root = tmp_path / "proj"
    project_root.mkdir()
    config_path = write_valid_project_yaml(project_root, old_field=5)
    before = config_path.read_bytes()
    register_project(
        registration_repo,
        project_root=project_root,
        project_key=project_root.stem,
        config_digest=config_file_digest(config_path),
    )
    external = tmp_path / "external-rewrite-target"
    external.write_bytes(b"external rewrite bytes\n")
    external_before = external.read_bytes()
    _symlink_file_or_skip(config_path.with_name("project.yaml.tmp"), external)

    with pytest.raises(ConfigMigrationError):
        run_upgrade(
            project_root,
            project_key=project_root.stem,
            target_config_version="4.0",
            registration_repo=registration_repo,  # type: ignore[arg-type]
        )

    assert external.read_bytes() == external_before
    assert config_path.read_bytes() == before
    assert not config_path.with_name("project.yaml.bak").exists()


def test_upgrade_rejects_project_yaml_bak_tmp_symlink_without_external_write(
    tmp_path: Path,
    registration_repo: InMemoryRegistrationRepo,
) -> None:
    """A linked backup staging path blocks before backup and external writes."""
    project_root = tmp_path / "proj"
    project_root.mkdir()
    config_path = write_valid_project_yaml(project_root, old_field=5)
    before = config_path.read_bytes()
    register_project(
        registration_repo,
        project_root=project_root,
        project_key=project_root.stem,
        config_digest=config_file_digest(config_path),
    )
    external = tmp_path / "external-backup-target"
    external.write_bytes(b"external backup bytes\n")
    external_before = external.read_bytes()
    _symlink_file_or_skip(config_path.with_name("project.yaml.bak.tmp"), external)

    with pytest.raises(ConfigMigrationError):
        run_upgrade(
            project_root,
            project_key=project_root.stem,
            target_config_version="4.0",
            registration_repo=registration_repo,  # type: ignore[arg-type]
        )

    assert external.read_bytes() == external_before
    assert config_path.read_bytes() == before
    assert not config_path.with_name("project.yaml.bak").exists()


def test_run_upgrade_resumes_digest_after_post_migration_crash(tmp_path: Path) -> None:
    """An exact backup witness resumes digest persistence after process loss."""
    project_root = tmp_path / "proj"
    project_root.mkdir()
    config_path = write_valid_project_yaml(project_root, old_field=5)
    original_digest = config_file_digest(config_path)
    registration_repo = _CrashOnceRegistrationRepo()
    register_project(
        registration_repo,
        project_root=project_root,
        project_key=project_root.stem,
        config_digest=original_digest,
    )

    with pytest.raises(RuntimeError, match="simulated process crash"):
        run_upgrade(
            project_root,
            project_key=project_root.stem,
            target_config_version="4.0",
            registration_repo=registration_repo,  # type: ignore[arg-type]
        )

    migrated_digest = config_file_digest(config_path)
    assert migrated_digest != original_digest
    assert registration_repo.rows[project_root.stem].config_digest == original_digest

    for read_only_mode in (ExecutionMode.DRY_RUN, ExecutionMode.VERIFY):
        planned = run_upgrade(
            project_root,
            project_key=project_root.stem,
            target_config_version="4.0",
            registration_repo=registration_repo,  # type: ignore[arg-type]
            mode=read_only_mode,
        )
        assert planned.config_migration_resumed is False
        assert planned.mutated is False
        assert (
            registration_repo.rows[project_root.stem].config_digest
            == original_digest
        )

    resumed = run_upgrade(
        project_root,
        project_key=project_root.stem,
        target_config_version="4.0",
        registration_repo=registration_repo,  # type: ignore[arg-type]
    )

    assert resumed.scenario.scenario is UpgradeScenario.UNCHANGED
    assert resumed.config_migrated is False
    assert resumed.config_migration_resumed is True
    assert resumed.mutated is True
    assert registration_repo.upgrade_calls == 1
    assert registration_repo.rows[project_root.stem].config_digest == migrated_digest


def test_resume_never_rebases_user_edit_after_witness(tmp_path: Path) -> None:
    """The resumed digest is immutable when a later checkpoint edits config."""
    project_root = tmp_path / "proj"
    project_root.mkdir()
    config_path = write_valid_project_yaml(project_root, old_field=5)
    original_digest = config_file_digest(config_path)
    registration_repo = _CrashOnceRegistrationRepo()
    register_project(
        registration_repo,
        project_root=project_root,
        project_key=project_root.stem,
        config_digest=original_digest,
    )
    with pytest.raises(RuntimeError, match="simulated process crash"):
        run_upgrade(
            project_root,
            project_key=project_root.stem,
            target_config_version="4.0",
            registration_repo=registration_repo,  # type: ignore[arg-type]
        )
    witnessed_digest = config_file_digest(config_path)

    resumed = run_upgrade(
        project_root,
        project_key=project_root.stem,
        target_config_version="4.0",
        registration_repo=registration_repo,  # type: ignore[arg-type]
        governance=_ConfigEditingGovernance(config_path),
    )

    edited_digest = config_file_digest(config_path)
    assert resumed.config_migration_resumed is True
    assert edited_digest != witnessed_digest
    assert registration_repo.rows[project_root.stem].config_digest == witnessed_digest

    next_run = run_upgrade(
        project_root,
        project_key=project_root.stem,
        target_config_version="4.0",
        registration_repo=registration_repo,  # type: ignore[arg-type]
    )
    assert next_run.scenario.scenario is UpgradeScenario.CONFIG_EDITED


def test_resume_blocks_user_edit_between_detection_and_migration(
    tmp_path: Path,
) -> None:
    """UP03 rejects bytes changed after UP01 before backup or rewrite."""
    project_root = tmp_path / "proj"
    project_root.mkdir()
    config_path = write_valid_project_yaml(project_root, old_field=5)
    original_digest = config_file_digest(config_path)
    registration_repo = _CrashOnceRegistrationRepo()
    register_project(
        registration_repo,
        project_root=project_root,
        project_key=project_root.stem,
        config_digest=original_digest,
    )
    with pytest.raises(RuntimeError, match="simulated process crash"):
        run_upgrade(
            project_root,
            project_key=project_root.stem,
            target_config_version="4.0",
            registration_repo=registration_repo,  # type: ignore[arg-type]
        )
    backup_path = config_path.with_name("project.yaml.bak")
    backup_before = backup_path.read_bytes()

    with pytest.raises(ConfigMigrationError, match="changed after upgrade detection"):
        run_upgrade(
            project_root,
            project_key=project_root.stem,
            target_config_version="4.0",
            registration_repo=registration_repo,  # type: ignore[arg-type]
            skills=_ConfigEditingSkills(config_path),  # type: ignore[arg-type]
        )

    on_disk = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    assert on_disk["pipeline"]["permissions"] == {"request_ttl_s": 1800}
    assert on_disk["pipeline"]["user_change_between_checkpoints"] == "preserve"
    assert backup_path.read_bytes() == backup_before
    assert registration_repo.upgrade_calls == 0
    assert registration_repo.rows[project_root.stem].config_digest == original_digest


def test_resume_blocks_config_removal_between_detection_and_migration(
    tmp_path: Path,
) -> None:
    """UP03 rejects removal after UP01 instead of treating config as absent."""
    project_root = tmp_path / "proj"
    project_root.mkdir()
    config_path = write_valid_project_yaml(project_root, old_field=5)
    original_digest = config_file_digest(config_path)
    registration_repo = _CrashOnceRegistrationRepo()
    register_project(
        registration_repo,
        project_root=project_root,
        project_key=project_root.stem,
        config_digest=original_digest,
    )
    with pytest.raises(RuntimeError, match="simulated process crash"):
        run_upgrade(
            project_root,
            project_key=project_root.stem,
            target_config_version="4.0",
            registration_repo=registration_repo,  # type: ignore[arg-type]
        )
    backup_path = config_path.with_name("project.yaml.bak")
    backup_before = backup_path.read_bytes()

    with pytest.raises(ConfigMigrationError, match="witness changed"):
        run_upgrade(
            project_root,
            project_key=project_root.stem,
            target_config_version="4.0",
            registration_repo=registration_repo,  # type: ignore[arg-type]
            skills=_ConfigDeletingSkills(config_path),  # type: ignore[arg-type]
        )

    assert not config_path.exists()
    assert backup_path.read_bytes() == backup_before
    assert registration_repo.upgrade_calls == 0
    assert registration_repo.rows[project_root.stem].config_digest == original_digest


def test_resume_blocks_formatting_edit_between_detection_and_migration(
    tmp_path: Path,
) -> None:
    """UP03 revalidates the exact witnessed bytes, not only YAML meaning."""
    project_root = tmp_path / "proj"
    project_root.mkdir()
    config_path = write_valid_project_yaml(project_root, old_field=5)
    original_digest = config_file_digest(config_path)
    registration_repo = _CrashOnceRegistrationRepo()
    register_project(
        registration_repo,
        project_root=project_root,
        project_key=project_root.stem,
        config_digest=original_digest,
    )
    with pytest.raises(RuntimeError, match="simulated process crash"):
        run_upgrade(
            project_root,
            project_key=project_root.stem,
            target_config_version="4.0",
            registration_repo=registration_repo,  # type: ignore[arg-type]
        )
    backup_path = config_path.with_name("project.yaml.bak")
    backup_before = backup_path.read_bytes()

    with pytest.raises(ConfigMigrationError, match="witness changed"):
        run_upgrade(
            project_root,
            project_key=project_root.stem,
            target_config_version="4.0",
            registration_repo=registration_repo,  # type: ignore[arg-type]
            skills=_ConfigFormattingSkills(config_path),  # type: ignore[arg-type]
        )

    assert config_path.read_bytes().endswith(b"# user formatting change\n")
    assert backup_path.read_bytes() == backup_before
    assert registration_repo.upgrade_calls == 0
    assert registration_repo.rows[project_root.stem].config_digest == original_digest


def test_run_upgrade_keeps_config_edited_after_post_crash_user_edit(
    tmp_path: Path,
) -> None:
    """Editing the migrated file invalidates the backup witness fail-closed."""
    project_root = tmp_path / "proj"
    project_root.mkdir()
    config_path = write_valid_project_yaml(project_root, old_field=5)
    original_digest = config_file_digest(config_path)
    registration_repo = _CrashOnceRegistrationRepo()
    register_project(
        registration_repo,
        project_root=project_root,
        project_key=project_root.stem,
        config_digest=original_digest,
    )
    with pytest.raises(RuntimeError, match="simulated process crash"):
        run_upgrade(
            project_root,
            project_key=project_root.stem,
            target_config_version="4.0",
            registration_repo=registration_repo,  # type: ignore[arg-type]
        )
    migrated = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    migrated["user_change"] = True
    config_path.write_text(yaml.dump(migrated, sort_keys=False), encoding="utf-8")

    result = run_upgrade(
        project_root,
        project_key=project_root.stem,
        target_config_version="4.0",
        registration_repo=registration_repo,  # type: ignore[arg-type]
    )

    assert result.scenario.scenario is UpgradeScenario.CONFIG_EDITED
    assert registration_repo.upgrade_calls == 0
    assert registration_repo.rows[project_root.stem].config_digest == original_digest


def test_run_upgrade_keeps_config_edited_with_manually_created_backup(
    tmp_path: Path,
    registration_repo: InMemoryRegistrationRepo,
) -> None:
    """Mere presence of a user-created backup is not a migration witness."""
    project_root = tmp_path / "proj"
    project_root.mkdir()
    config_path = write_valid_project_yaml(project_root)
    original_digest = config_file_digest(config_path)
    register_project(
        registration_repo,
        project_root=project_root,
        project_key=project_root.stem,
        config_digest=original_digest,
    )
    manual = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    manual["pipeline"]["config_version"] = "4.0"
    config_path.write_text(yaml.dump(manual, sort_keys=False), encoding="utf-8")
    config_path.with_name("project.yaml.bak").write_bytes(config_path.read_bytes())

    result = run_upgrade(
        project_root,
        project_key=project_root.stem,
        target_config_version="4.0",
        registration_repo=registration_repo,  # type: ignore[arg-type]
    )

    assert result.scenario.scenario is UpgradeScenario.CONFIG_EDITED
    assert registration_repo.upgrade_calls == 0
    assert registration_repo.rows[project_root.stem].config_digest == original_digest


def test_run_upgrade_scenario_3b_config_edited(tmp_path: Path, registration_repo: InMemoryRegistrationRepo) -> None:
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


def test_run_upgrade_scenario_3a_unchanged_skip(tmp_path: Path, registration_repo: InMemoryRegistrationRepo) -> None:
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
    # AG3-176: mandatory pre/post VectorDB dispatch is a convergence repair
    # even when the config/bundle scenario itself is unchanged.
    assert result.mutated is True


def test_run_upgrade_scenario_3c_explicit_binding_switch(tmp_path: Path, registration_repo: InMemoryRegistrationRepo) -> None:
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


def test_run_upgrade_dry_run_does_not_mutate(tmp_path: Path, registration_repo: InMemoryRegistrationRepo) -> None:
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

    def resolve_binding(
        self,
        project_root: Path,
        skill_name: str,
    ) -> SkillBinding | None:
        from datetime import UTC, datetime

        from agentkit.backend.skills.binding import (
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
            content_digest="0" * 64,
            target_path=project_root / ".claude" / "skills" / skill_name,
            binding_mode=SkillBindingMode.SYMLINK,
            status=SkillLifecycleStatus.BOUND,
            pinned_at=datetime.now(tz=UTC),
        )

    def list_bound_skills(self, project_root: Path) -> list[SkillBinding]:
        """Return the same persisted binding through the expanded skills port."""
        binding = self.resolve_binding(project_root, "execute-userstory")
        assert binding is not None  # noqa: S101 -- fixed test-double contract
        return [binding]


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
