"""Unit tests for FK-51 §51.4 config migration (AG3-089 AC1 / AC2).

Covers:
* stepwise ``config_version`` migration on a major jump (3 -> 4);
* a ``.bak`` backup written BEFORE every migration whose content equals the old
  config (AC1);
* fail-closed behaviour on an unknown source/target version (AC2);
* idempotency (already at target -> no migration, no backup).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
import yaml

from agentkit.installer.upgrade.config_migration import (
    BACKUP_SUFFIX,
    ConfigMigrationError,
    MigrationStep,
    backup_config_file,
    migrate_3_to_4,
    migrate_config,
    migrate_config_file,
)

if TYPE_CHECKING:
    from pathlib import Path


def _cfg(version: object, **extra: object) -> dict[str, object]:
    """Build a config mapping with ``pipeline.config_version`` (AG3-070 SSOT)."""
    return {"pipeline": {"config_version": version}, **extra}


def test_migrate_config_step_3_to_4_renames_and_defaults() -> None:
    """``migrate_config`` performs the stepwise 3.0 -> 4.0 transform (AC1)."""
    result = migrate_config(_cfg("3.0", old_field=7), "4.0")

    assert result["pipeline"]["config_version"] == "4.0"  # type: ignore[index]
    assert result["new_field"] == 7
    assert "old_field" not in result
    assert result["new_required_field"] == "default_value"


def test_migrate_config_already_at_target_is_noop() -> None:
    """An existing config already at the target version is returned unchanged."""
    existing = _cfg("4.0", keep=1)
    result = migrate_config(existing, "4.0")

    assert result == existing
    assert result is not existing  # a copy, never the same object


def test_migrate_config_stepwise_no_jump_skip() -> None:
    """A 3 -> 5 migration runs 3 -> 4 -> 5 stepwise, never skipping a jump (AC1)."""
    steps = (
        MigrationStep("3.0", "4.0", lambda c: {**c, "via4": True}),
        MigrationStep("4.0", "5.0", lambda c: {**c, "via5": True}),
    )
    result = migrate_config(_cfg("3.0"), "5.0", steps=steps)

    assert result["pipeline"]["config_version"] == "5.0"  # type: ignore[index]
    assert result["via4"] is True
    assert result["via5"] is True


def test_migrate_config_fail_closed_unknown_source_version() -> None:
    """An unknown source version with no registered step fails closed (AC2)."""
    with pytest.raises(ConfigMigrationError) as exc:
        migrate_config(_cfg("9.9"), "4.0")

    assert "9.9" in str(exc.value)


def test_migrate_config_fail_closed_unreachable_target_version() -> None:
    """A target the step chain cannot reach fails closed (AC2)."""
    with pytest.raises(ConfigMigrationError):
        migrate_config(_cfg("3.0"), "99.0")


def test_migrate_config_fail_closed_empty_target_version() -> None:
    """An empty target version is rejected fail-closed (AC2)."""
    with pytest.raises(ConfigMigrationError):
        migrate_config(_cfg("3.0"), "  ")


def test_migrate_config_fail_closed_non_string_config_version() -> None:
    """A non-string config_version is rejected fail-closed (AC2)."""
    with pytest.raises(ConfigMigrationError):
        migrate_config(_cfg(3), "4.0")


def test_migrate_config_fail_closed_missing_pipeline_stanza() -> None:
    """A config with NO pipeline stanza fails closed (AG3-070 no-silent-default)."""
    with pytest.raises(ConfigMigrationError):
        migrate_config({"config_version": "3.0"}, "4.0")  # top-level is NOT the SSOT


def test_migrate_3_to_4_does_not_mutate_input() -> None:
    """The step transform operates on a copy; the caller's dict is untouched."""
    source = {"pipeline": {"config_version": "3.0"}, "old_field": 1}
    migrate_3_to_4(source)

    assert source == {"pipeline": {"config_version": "3.0"}, "old_field": 1}


def test_backup_config_file_writes_bak_with_old_content(tmp_path: Path) -> None:
    """``backup_config_file`` writes a byte-identical ``.bak`` (AC1)."""
    config = tmp_path / "project.yaml"
    config.write_text(
        "pipeline:\n  config_version: '3.0'\nold_field: 5\n", encoding="utf-8"
    )

    backup = backup_config_file(config)

    assert backup == config.with_name("project.yaml" + BACKUP_SUFFIX)
    assert backup.read_text(encoding="utf-8") == config.read_text(encoding="utf-8")


def test_backup_config_file_missing_source_fails_closed(tmp_path: Path) -> None:
    """Backing up a missing config fails closed (no migration without a backup)."""
    with pytest.raises(ConfigMigrationError):
        backup_config_file(tmp_path / "absent.yaml")


def test_migrate_config_file_3_to_4_creates_bak_and_rewrites(tmp_path: Path) -> None:
    """File migration 3 -> 4 writes a ``.bak`` = old config and the new on disk (AC1)."""
    config = tmp_path / "project.yaml"
    old_content = "pipeline:\n  config_version: '3.0'\nold_field: 42\n"
    config.write_text(old_content, encoding="utf-8")

    migrated = migrate_config_file(config, "4.0")

    assert migrated is True
    backup = config.with_name("project.yaml" + BACKUP_SUFFIX)
    # AC1: `.bak` content equals the OLD config.
    assert backup.read_text(encoding="utf-8") == old_content
    # AC1: the new config is on disk with the migrated shape (version at the
    # AG3-070 SSOT location pipeline.config_version).
    on_disk = yaml.safe_load(config.read_text(encoding="utf-8"))
    assert on_disk["pipeline"]["config_version"] == "4.0"
    assert on_disk["new_field"] == 42
    assert "old_field" not in on_disk


def test_migrate_config_file_already_current_no_backup(tmp_path: Path) -> None:
    """A file already at the target version is not migrated and writes no ``.bak``."""
    config = tmp_path / "project.yaml"
    config.write_text("pipeline:\n  config_version: '4.0'\n", encoding="utf-8")

    migrated = migrate_config_file(config, "4.0")

    assert migrated is False
    assert not config.with_name("project.yaml" + BACKUP_SUFFIX).exists()


def test_migrate_config_file_unknown_version_fails_closed(tmp_path: Path) -> None:
    """A file on an unknown version fails closed (AC2)."""
    config = tmp_path / "project.yaml"
    config.write_text("pipeline:\n  config_version: '9.9'\n", encoding="utf-8")

    with pytest.raises(ConfigMigrationError):
        migrate_config_file(config, "4.0")


def test_migrate_config_file_missing_fails_closed(tmp_path: Path) -> None:
    """Migrating a missing config file fails closed."""
    with pytest.raises(ConfigMigrationError):
        migrate_config_file(tmp_path / "absent.yaml", "4.0")


def test_migrate_config_file_malformed_yaml_fails_closed(tmp_path: Path) -> None:
    """A non-mapping YAML config fails closed."""
    config = tmp_path / "project.yaml"
    config.write_text("- just\n- a\n- list\n", encoding="utf-8")

    with pytest.raises(ConfigMigrationError):
        migrate_config_file(config, "4.0")
