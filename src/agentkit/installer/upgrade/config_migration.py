"""Config migration for project.yaml across config_version major jumps (FK-51 §51.4).

Implements the FK-51 §51.4 stepwise config migration:

* :func:`migrate_config` — the pure dict migration (FK-51 §51.4.2 reference): a
  stepwise chain over typed :class:`MigrationStep` entries; NO version jump is
  skipped (3 -> 5 runs 3 -> 4 -> 5). Fail-closed on an unknown source or target
  version (story AC2).
* :func:`migrate_3_to_4` — the concrete 3.0 -> 4.0 step (the only registered
  step today; the chain is extended by registering further steps).
* :func:`migrate_config_file` — the file-level wrapper that writes the ``.bak``
  backup BEFORE migrating (atomic, recoverable, FK-51 §51.4.3, story AC1) and
  then atomically rewrites ``project.yaml`` with the migrated content.

Ownership: the migration steps are owned HERE (BC ``installation-and-bootstrap``,
installer-upgrade layer). The migration consumes the ``config_version`` schema
of the config model (BC ``pipeline-framework``, FK-03 / AG3-070) as the version
source — it never redefines the config model (story §2.2).
"""

from __future__ import annotations

import shutil
from dataclasses import dataclass
from typing import TYPE_CHECKING, Final

import yaml

from agentkit.exceptions import InstallationError
from agentkit.utils.io import atomic_write_text

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

#: The ``pipeline`` stanza key in ``project.yaml`` that OWNS ``config_version``
#: (AG3-070 SSOT: ``ProjectConfig.pipeline.config_version``, FK-03 §3.2.1). The
#: migration reads/writes the version at this nested owner location, NOT a
#: top-level key (no second source of truth, story §2.2 / FIX-THE-MODEL).
PIPELINE_KEY: Final = "pipeline"

#: The ``config_version`` key WITHIN the ``pipeline`` stanza (AG3-070 SSOT).
CONFIG_VERSION_KEY: Final = "config_version"

#: Suffix appended to a file path to form its backup (FK-51 §51.4.3 ``.bak``).
#: English, dot-prefixed convention (ARCH-55, story §5).
BACKUP_SUFFIX: Final = ".bak"


class ConfigMigrationError(InstallationError):
    """A config migration could not be carried out fail-closed (FK-51 §51.4).

    Raised for an unknown source/target ``config_version`` (no registered step
    chain reaches the target — story AC2) or when the on-disk backup target
    cannot be written before a migration (FK-51 §51.4.3 — no migration without a
    recoverable backup). It is an :class:`InstallationError` so the upgrade flow
    treats it as a hard, fail-closed install failure (no partial migration).
    """


def read_config_version(config: dict[str, object]) -> str:
    """Read ``pipeline.config_version`` fail-closed (AG3-070 SSOT, FK-03 §3.2.1).

    The version lives ONLY at the AG3-070 owner location
    ``pipeline.config_version`` — there is NO top-level key and NO silent default
    (AG3-070 is fail-closed on a missing version). A missing ``pipeline`` stanza,
    a non-mapping ``pipeline``, an absent / non-string / empty ``config_version``
    raises :class:`ConfigMigrationError` rather than fabricating a baseline.

    Args:
        config: The raw ``project.yaml`` mapping.

    Returns:
        The on-disk ``pipeline.config_version`` string.

    Raises:
        ConfigMigrationError: When the version is absent/malformed (fail-closed,
            consistent with AG3-070's no-silent-default contract).
    """
    pipeline = config.get(PIPELINE_KEY)
    if not isinstance(pipeline, dict):
        raise ConfigMigrationError(
            "project.yaml has no 'pipeline' stanza; cannot read "
            "pipeline.config_version fail-closed (AG3-070 SSOT, FK-03 §3.2.1).",
            detail={"missing": f"{PIPELINE_KEY}.{CONFIG_VERSION_KEY}"},
        )
    raw = pipeline.get(CONFIG_VERSION_KEY)
    if not isinstance(raw, str) or not raw.strip():
        raise ConfigMigrationError(
            "pipeline.config_version is absent / non-string / empty; cannot "
            "migrate fail-closed (AG3-070 no-silent-default, FK-51 §51.4).",
            detail={"config_version": repr(raw)},
        )
    return raw


def _write_config_version(config: dict[str, object], version: str) -> dict[str, object]:
    """Return ``config`` with ``pipeline.config_version`` set to ``version``.

    Writes the version at the AG3-070 SSOT location (a fresh nested copy of the
    ``pipeline`` stanza, so the input is not mutated). Fail-closed when the
    ``pipeline`` stanza is absent/non-mapping (a migration target must carry the
    owner stanza).
    """
    pipeline = config.get(PIPELINE_KEY)
    if not isinstance(pipeline, dict):
        raise ConfigMigrationError(
            "project.yaml has no 'pipeline' stanza; cannot write "
            "pipeline.config_version fail-closed (AG3-070 SSOT).",
            detail={"missing": f"{PIPELINE_KEY}.{CONFIG_VERSION_KEY}"},
        )
    updated = dict(config)
    updated_pipeline = dict(pipeline)
    updated_pipeline[CONFIG_VERSION_KEY] = version
    updated[PIPELINE_KEY] = updated_pipeline
    return updated


@dataclass(frozen=True)
class MigrationStep:
    """A single typed config-migration step (FK-51 §51.4.2).

    A step converts the config dict from ``source_version`` to ``target_version``
    via a pure ``apply`` transform. Steps are chained: the migration walks from
    the existing version to the requested target one major step at a time, never
    skipping a jump (story §2.1.1). The step set is the single source of truth
    for which version transitions exist — an unreachable target fails closed.

    Attributes:
        source_version: The ``config_version`` this step migrates FROM.
        target_version: The ``config_version`` this step migrates TO.
        apply: Pure transform ``dict -> dict`` for the step body. It receives a
            shallow copy and returns the migrated mapping; it must NOT mutate its
            argument in place (the caller owns copy semantics).
    """

    source_version: str
    target_version: str
    apply: Callable[[dict[str, object]], dict[str, object]]


def migrate_3_to_4(config: dict[str, object]) -> dict[str, object]:
    """Migrate a ``config_version`` 3.0 config dict to the 4.0 shape (FK-51 §51.4.2).

    The FK-51 §51.4.2 reference body: a representative field rename plus a new
    required field with a default. Operates on a shallow copy and returns the
    migrated mapping (the ``config_version`` itself is set by the chain driver,
    not here, so a step never disagrees with the requested target).

    Args:
        config: The 3.0 config mapping (already copied by the chain driver).

    Returns:
        The migrated 4.0 config mapping.
    """
    migrated = dict(config)
    # FK-51 §51.4.2: example field rename (old_field -> new_field).
    if "old_field" in migrated:
        migrated["new_field"] = migrated.pop("old_field")
    # FK-51 §51.4.2: new required field gets a default when absent.
    migrated.setdefault("new_required_field", "default_value")
    return migrated


#: The registered migration steps (FK-51 §51.4.2). The single source of truth
#: for which ``config_version`` transitions exist. Extend by appending a step;
#: the chain driver composes them and fails closed on a gap (story AC2).
_MIGRATION_STEPS: Final[tuple[MigrationStep, ...]] = (
    MigrationStep(source_version="3.0", target_version="4.0", apply=migrate_3_to_4),
)


def _step_index(steps: tuple[MigrationStep, ...]) -> dict[str, MigrationStep]:
    """Index steps by their source version (one outgoing step per version)."""
    index: dict[str, MigrationStep] = {}
    for step in steps:
        if step.source_version in index:  # pragma: no cover - registry is unique
            raise ConfigMigrationError(
                "Ambiguous config migration: two steps share source version "
                f"{step.source_version!r}.",
                detail={"source_version": step.source_version},
            )
        index[step.source_version] = step
    return index


def migrate_config(
    existing: dict[str, object],
    target_version: str,
    *,
    steps: tuple[MigrationStep, ...] = _MIGRATION_STEPS,
) -> dict[str, object]:
    """Migrate a config dict to ``target_version`` stepwise (FK-51 §51.4.2).

    Walks the registered :class:`MigrationStep` chain from the existing
    ``config_version`` (or :data:`DEFAULT_SOURCE_VERSION` when absent) to
    ``target_version`` one major step at a time — NO jump is skipped (story
    §2.1.1). When the existing version already equals the target, the config is
    returned unchanged (no migration needed).

    Fail-closed (story AC2): if the chain cannot reach ``target_version`` from
    the existing version (an unknown source or target, or a gap in the step set),
    a :class:`ConfigMigrationError` is raised — the migration never fabricates a
    transition or silently leaves the config on a stale version.

    Args:
        existing: The existing config mapping (read from project.yaml).
        target_version: The desired ``config_version`` after migration.
        steps: The migration step set (defaults to the registered steps; an
            override is for tests only).

    Returns:
        A NEW migrated config mapping with ``pipeline.config_version ==
        target_version`` (the AG3-070 SSOT). The input mapping is not mutated.

    Raises:
        ConfigMigrationError: When the existing version is absent/malformed
            (AG3-070 no-silent-default), the target is empty, or the step chain
            cannot reach the target (fail-closed).
    """
    raw_current = read_config_version(existing)
    if not target_version.strip():
        raise ConfigMigrationError(
            "Empty target config_version; cannot migrate fail-closed (FK-51 §51.4).",
            detail={"target_version": repr(target_version)},
        )

    current = raw_current
    if current == target_version:
        return dict(existing)  # No migration needed (FK-51 §51.4.2).

    index = _step_index(steps)
    migrated = dict(existing)
    # Walk the chain. The loop is bounded by the step count: each iteration
    # advances ``current`` to a STRICTLY later source, so it cannot cycle.
    for _ in range(len(steps) + 1):
        if current == target_version:
            return _write_config_version(migrated, target_version)
        step = index.get(current)
        if step is None:
            raise ConfigMigrationError(
                f"No config migration step from version {current!r} toward "
                f"{target_version!r} (FK-51 §51.4, fail-closed: unknown source/"
                "target version, no fabricated transition).",
                detail={
                    "current_version": current,
                    "target_version": target_version,
                },
            )
        migrated = step.apply(migrated)
        migrated = _write_config_version(migrated, step.target_version)
        current = step.target_version

    # Loop exhausted without reaching the target -> the target is unreachable
    # through the registered chain (fail-closed). pragma: defensive — the bound
    # above is len(steps)+1 so a reachable target always returns inside the loop.
    raise ConfigMigrationError(  # pragma: no cover - defensive unreachable bound
        f"Config migration chain did not reach target {target_version!r} from "
        f"{raw_current!r} (FK-51 §51.4, fail-closed).",
        detail={"source_version": raw_current, "target_version": target_version},
    )


def backup_config_file(config_path: Path) -> Path:
    """Write the ``.bak`` backup of ``config_path`` BEFORE a migration (FK-51 §51.4.3).

    The backup is created atomically (copy to a temp sibling, then ``os.replace``
    onto ``<config_path>.bak``) so a crash never leaves a truncated backup; the
    resulting ``.bak`` is byte-identical to the source, making the migration
    recoverable (story §6 — recoverable on migration failure).

    Args:
        config_path: The existing config file to back up.

    Returns:
        The backup path (``<config_path>.bak``).

    Raises:
        ConfigMigrationError: When the source file is absent (no migration
            without an existing config to back up) or the backup write fails.
    """
    if not config_path.is_file():
        raise ConfigMigrationError(
            f"Cannot back up a missing config file before migration: {config_path} "
            "(FK-51 §51.4.3, fail-closed).",
            detail={"config_path": str(config_path)},
        )
    backup_path = config_path.with_name(config_path.name + BACKUP_SUFFIX)
    tmp_path = backup_path.with_name(backup_path.name + ".tmp")
    try:
        shutil.copy2(config_path, tmp_path)
        tmp_path.replace(backup_path)
    except OSError as exc:
        if tmp_path.exists():
            tmp_path.unlink()
        raise ConfigMigrationError(
            f"Failed to write config backup {backup_path}: {exc} (FK-51 §51.4.3, "
            "fail-closed: no migration without a recoverable backup).",
            detail={"config_path": str(config_path), "backup_path": str(backup_path)},
        ) from exc
    return backup_path


def migrate_config_file(
    config_path: Path,
    target_version: str,
    *,
    steps: tuple[MigrationStep, ...] = _MIGRATION_STEPS,
) -> bool:
    """Migrate ``project.yaml`` on disk to ``target_version`` (FK-51 §51.4).

    The file-level wrapper around :func:`migrate_config`:

    1. Reads the existing YAML mapping.
    2. If already at ``target_version`` -> returns ``False`` (no backup, no
       write — nothing to migrate).
    3. Otherwise writes the ``.bak`` backup FIRST (FK-51 §51.4.3 — before every
       migration), then computes the migrated mapping and atomically rewrites the
       config file. Returns ``True``.

    On any migration failure AFTER the backup the original is recoverable from
    the ``.bak`` (story §6); the backup itself is written before any mutation.

    Args:
        config_path: Path to the existing ``project.yaml``.
        target_version: The desired ``config_version`` after migration.
        steps: The migration step set (tests may override).

    Returns:
        ``True`` when a migration was performed (backup + rewrite), ``False``
        when the config was already at the target version.

    Raises:
        ConfigMigrationError: On a missing/malformed config, an unknown version
            (fail-closed) or a backup write failure.
    """
    if not config_path.is_file():
        raise ConfigMigrationError(
            f"Cannot migrate a missing config file: {config_path} (FK-51 §51.4, "
            "fail-closed).",
            detail={"config_path": str(config_path)},
        )
    raw_text = config_path.read_text(encoding="utf-8")
    try:
        loaded = yaml.safe_load(raw_text)
    except yaml.YAMLError as exc:
        raise ConfigMigrationError(
            f"Config file is not valid YAML; cannot migrate: {config_path} ({exc}).",
            detail={"config_path": str(config_path)},
        ) from exc
    if not isinstance(loaded, dict):
        raise ConfigMigrationError(
            f"Config file must be a YAML mapping to migrate: {config_path}.",
            detail={"config_path": str(config_path)},
        )
    existing: dict[str, object] = dict(loaded)

    current = read_config_version(existing)
    if current == target_version:
        return False

    # FK-51 §51.4.3: backup BEFORE the migration (and before any rewrite).
    backup_config_file(config_path)
    migrated = migrate_config(existing, target_version, steps=steps)
    atomic_write_text(
        config_path,
        yaml.dump(migrated, default_flow_style=False, allow_unicode=True, sort_keys=False),
    )
    return True


__all__ = [
    "BACKUP_SUFFIX",
    "CONFIG_VERSION_KEY",
    "PIPELINE_KEY",
    "ConfigMigrationError",
    "MigrationStep",
    "backup_config_file",
    "migrate_3_to_4",
    "migrate_config",
    "migrate_config_file",
    "read_config_version",
]
