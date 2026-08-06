"""Config migration for project.yaml across config_version major jumps (FK-51 §51.4).

Implements the FK-51 §51.4 stepwise config migration:

* :func:`migrate_config` — the pure dict migration (FK-51 §51.4.2 reference): a
  stepwise chain over typed :class:`MigrationStep` entries; NO version jump is
  skipped (3 -> 5 runs 3 -> 4 -> 5). Fail-closed on an unknown source or target
  version (story AC2).
* :func:`migrate_3_to_4` — the concrete 3.0 -> 4.0 step (the only registered
  step today; the chain is extended by registering further steps).
* :func:`migrate_config_file` — the file-level wrapper that writes the ``.bak``
  backup BEFORE mutating (atomic, recoverable, FK-51 §51.4.3, story AC1) and
  then atomically rewrites ``project.yaml`` with the migrated content.

Ownership: the migration steps are owned HERE (BC ``installation-and-bootstrap``,
installer-upgrade layer). The migration consumes the ``config_version`` schema
of the config model (BC ``pipeline-framework``, FK-03 / AG3-070) as the version
source — it never redefines the config model (story §2.2).
"""

from __future__ import annotations

import hashlib
import os
import shutil
from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING, Final

import yaml

from agentkit.backend.boundary.filesystem.path_identity import is_filesystem_link
from agentkit.backend.exceptions import ConfigError, InstallationError
from agentkit.backend.utils.io import assert_atomic_write_target

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

#: Retired AG3-226 owner key.  The whole stanza configured the removed
#: permission-request procedure; upgrade removes this exact key while retaining
#: every sibling, including extension keys unknown to the current schema.
OBSOLETE_PERMISSIONS_KEY: Final = "permissions"

#: The feature keys targeted by the AG3-226 E4 repair.  AG3-176 made VectorDB
#: mandatory after earlier AK3 installers had explicitly written ``false``.
#: Upgrade changes only that exact historical value; all sibling feature keys
#: remain untouched, including keys unknown to the current schema.
FEATURES_KEY: Final = "features"
VECTORDB_KEY: Final = "vectordb"

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


class ConfigBehaviorChange(StrEnum):
    """User-visible behavior changes proven by a config migration witness."""

    MANDATORY_VECTORDB_ENABLED = "mandatory_vectordb_enabled"


@dataclass(frozen=True)
class CompletedConfigMigrationWitness:
    """Exact interrupted-migration witness and its behavior changes."""

    behavior_changes: frozenset[ConfigBehaviorChange]


@dataclass(frozen=True)
class ConfigFileBaseline:
    """One identity-bound byte baseline for an on-disk config migration."""

    path: Path
    content: bytes
    byte_digest: str
    stat: os.stat_result


@dataclass(frozen=True)
class ConfigMigrationPlan:
    """A config migration derived entirely from one validated byte baseline."""

    baseline: ConfigFileBaseline
    rendered_content: bytes
    migrated_config_digest: str
    mandatory_vectordb_enabled: bool

    @property
    def needs_migration(self) -> bool:
        """Return whether the deterministic result differs from the baseline."""
        return self.rendered_content != self.baseline.content

    @property
    def migrated_digest(self) -> str:
        """Return the canonical config digest of the planned mapping."""
        return self.migrated_config_digest


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


def remove_obsolete_permission_config(
    config: dict[str, object],
) -> dict[str, object]:
    """Remove only the retired ``pipeline.permissions`` stanza (AG3-226).

    The stanza exclusively parameterized the abolished permission-request
    procedure.  This targeted transform deliberately does not filter or
    validate any other key: known and unknown siblings remain byte-for-value
    equivalent in the returned mapping.  The input and its nested ``pipeline``
    mapping are not mutated.
    """
    pipeline = config.get(PIPELINE_KEY)
    if not isinstance(pipeline, dict) or OBSOLETE_PERMISSIONS_KEY not in pipeline:
        return dict(config)
    cleaned = dict(config)
    cleaned_pipeline = dict(pipeline)
    del cleaned_pipeline[OBSOLETE_PERMISSIONS_KEY]
    cleaned[PIPELINE_KEY] = cleaned_pipeline
    return cleaned


def enable_mandatory_vectordb_config(
    config: dict[str, object],
) -> dict[str, object]:
    """Replace only historical ``pipeline.features.vectordb=false`` with true.

    AG3-176 made VectorDB a mandatory base dependency and the current model
    rejects an explicit opt-out.  Earlier AK3 installers nevertheless emitted
    ``false``.  Keeping the key and setting the sole admissible value makes the
    mandatory activation explicit, matching the current installer output; it
    does not pretend that the field remains an operator choice.

    Values other than the exact YAML boolean ``false`` are not repaired here.
    They were not emitted by the historical writer and remain subject to strict
    model validation.  The input and all foreign sibling mappings are preserved.
    """
    legacy_mappings = _historical_disabled_vectordb_mappings(config)
    if legacy_mappings is None:
        return dict(config)

    pipeline, features = legacy_mappings
    migrated = dict(config)
    migrated_pipeline = dict(pipeline)
    migrated_features = dict(features)
    migrated_features[VECTORDB_KEY] = True
    migrated_pipeline[FEATURES_KEY] = migrated_features
    migrated[PIPELINE_KEY] = migrated_pipeline
    return migrated


def has_historical_disabled_vectordb(config: dict[str, object]) -> bool:
    """Return whether config carries the exact AK3-written E4 legacy value."""
    return _historical_disabled_vectordb_mappings(config) is not None


def _historical_disabled_vectordb_mappings(
    config: dict[str, object],
) -> tuple[dict[str, object], dict[str, object]] | None:
    """Return the owning mappings only for the exact historical false value."""
    pipeline = config.get(PIPELINE_KEY)
    if not isinstance(pipeline, dict):
        return None
    features = pipeline.get(FEATURES_KEY)
    if not isinstance(features, dict) or features.get(VECTORDB_KEY) is not False:
        return None
    return pipeline, features


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
    migrated = remove_obsolete_permission_config(existing)
    migrated = enable_mandatory_vectordb_config(migrated)
    if current == target_version:
        return migrated

    index = _step_index(steps)
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


def _read_config_baseline(
    config_path: Path,
) -> ConfigFileBaseline:
    """Read one stable, identity-bound byte baseline."""
    if is_filesystem_link(config_path) or not config_path.is_file():
        raise ConfigMigrationError(
            f"Cannot read a regular local config file for migration: {config_path} "
            "(FK-51 §51.4, fail-closed).",
            detail={"config_path": str(config_path)},
        )
    try:
        with config_path.open("rb") as source:
            stat_before = os.fstat(source.fileno())
            content = source.read()
            stat_after = os.fstat(source.fileno())
    except OSError as exc:
        raise ConfigMigrationError(
            f"Failed to read config migration baseline {config_path}: {exc}",
            detail={"config_path": str(config_path)},
        ) from exc
    if not os.path.samestat(stat_before, stat_after):
        raise ConfigMigrationError(
            f"Config identity changed while reading migration baseline: {config_path}.",
            detail={"config_path": str(config_path)},
        )
    return ConfigFileBaseline(
        path=config_path,
        content=content,
        byte_digest=hashlib.sha256(content).hexdigest(),
        stat=stat_after,
    )


def _assert_baseline_current(
    baseline: ConfigFileBaseline,
    *,
    mutation: str,
) -> None:
    """Compare file identity and digest with ``baseline`` before a mutation."""
    current = _read_config_baseline(baseline.path)
    if (
        not os.path.samestat(baseline.stat, current.stat)
        or current.byte_digest != baseline.byte_digest
    ):
        raise ConfigMigrationError(
            "project.yaml identity or content changed after the validated "
            f"migration read and before {mutation}; refusing mutation "
            "fail-closed.",
            detail={
                "baseline_byte_digest": baseline.byte_digest,
                "current_byte_digest": current.byte_digest,
                "config_path": str(baseline.path),
            },
        )


def prepare_config_migration(
    config_path: Path,
    target_version: str,
    *,
    expected_digest: str | None = None,
    steps: tuple[MigrationStep, ...] = _MIGRATION_STEPS,
) -> ConfigMigrationPlan:
    """Derive a migration plan from one digest-validated byte baseline.

    The returned baseline is the sole source for YAML parsing, migration and
    backup bytes. ``expected_digest`` binds the read to UP01 when the engine
    invokes this function; direct file-level callers may omit it.
    """
    baseline = _read_config_baseline(config_path)
    try:
        loaded = yaml.safe_load(baseline.content.decode("utf-8"))
    except (UnicodeError, yaml.YAMLError) as exc:
        raise ConfigMigrationError(
            f"Config file is not valid UTF-8 YAML; cannot migrate: "
            f"{config_path} ({exc}).",
            detail={"config_path": str(config_path)},
        ) from exc
    if not isinstance(loaded, dict):
        raise ConfigMigrationError(
            f"Config file must be a YAML mapping to migrate: {config_path}.",
            detail={"config_path": str(config_path)},
        )
    existing: dict[str, object] = dict(loaded)
    from agentkit.backend.installer.runner import _canonical_config_digest

    current_config_digest = _canonical_config_digest(existing)
    if expected_digest is not None and current_config_digest != expected_digest:
        raise ConfigMigrationError(
            "project.yaml changed after upgrade detection and before migration; "
            "refusing backup, rewrite, or digest persistence fail-closed.",
            detail={
                "detected_digest": expected_digest,
                "current_digest": current_config_digest,
                "current_byte_digest": baseline.byte_digest,
            },
        )
    migrated = migrate_config(existing, target_version, steps=steps)
    return ConfigMigrationPlan(
        baseline=baseline,
        rendered_content=(
            _render_config(migrated).encode("utf-8")
            if migrated != existing
            else baseline.content
        ),
        migrated_config_digest=_canonical_config_digest(migrated),
        mandatory_vectordb_enabled=has_historical_disabled_vectordb(existing),
    )


def backup_config_file(baseline: ConfigFileBaseline) -> Path:
    """Write ``baseline`` to ``.bak`` BEFORE a migration (FK-51 §51.4.3).

    The backup is created atomically (copy to a temp sibling, then ``os.replace``
    onto ``<config_path>.bak``) so a crash never leaves a truncated backup; the
    resulting ``.bak`` is byte-identical to the source, making the migration
    recoverable (story §6 — recoverable on migration failure).

    Args:
        baseline: The validated source identity and bytes to back up.

    Returns:
        The backup path (``<config_path>.bak``).

    Raises:
        ConfigMigrationError: When the source changed after the baseline read or
            the backup cannot be written.
    """
    config_path = baseline.path
    _assert_baseline_current(baseline, mutation="backup")
    backup_path = config_path.with_name(config_path.name + BACKUP_SUFFIX)
    tmp_path = _migration_temp_path(backup_path)
    try:
        if tmp_path.exists():
            tmp_path.unlink()
        with tmp_path.open("xb") as destination:
            destination.write(baseline.content)
            destination.flush()
            os.fsync(destination.fileno())
        shutil.copystat(config_path, tmp_path, follow_symlinks=False)
        os.replace(tmp_path, backup_path)
    except OSError as exc:
        if tmp_path.exists() and not is_filesystem_link(tmp_path):
            tmp_path.unlink()
        raise ConfigMigrationError(
            f"Failed to write config backup {backup_path}: {exc} (FK-51 §51.4.3, "
            "fail-closed: no migration without a recoverable backup).",
            detail={"config_path": str(config_path), "backup_path": str(backup_path)},
        ) from exc
    return backup_path


def _render_config(config: dict[str, object]) -> str:
    """Render a migrated config exactly as the file-level writer emits it."""
    return yaml.dump(
        config,
        default_flow_style=False,
        allow_unicode=True,
        sort_keys=False,
    )


def _migration_temp_path(path: Path) -> Path:
    """Return an unlink-safe staging path as an installer migration error."""
    try:
        return assert_atomic_write_target(path)
    except OSError as exc:
        raise ConfigMigrationError(
            f"Unsafe config migration staging path for {path}: {exc}",
            detail={"target_path": str(path)},
        ) from exc


def matches_completed_config_migration(
    config_path: Path,
    registered_digest: str,
    target_version: str,
) -> bool:
    """Return whether ``.bak`` proves an interrupted owned migration.

    The witness is accepted only when all three facts agree: the backup is a
    real local file, its canonical digest equals the registered pre-migration
    baseline, and the current config bytes exactly equal the deterministic
    result of migrating that backup to ``target_version``. Mere backup presence
    or a subsequently edited migration result therefore remains untrusted.

    Args:
        config_path: Current project config path.
        registered_digest: Digest persisted before the interrupted migration.
        target_version: Version requested by the resumed upgrade.

    Returns:
        ``True`` only for an exact completed-migration witness; otherwise
        ``False`` fail-closed.
    """
    return (
        completed_config_migration_witness(
            config_path,
            registered_digest,
            target_version,
        )
        is not None
    )


def completed_config_migration_witness(
    config_path: Path,
    registered_digest: str,
    target_version: str,
) -> CompletedConfigMigrationWitness | None:
    """Return the exact interrupted migration witness with behavior metadata."""
    from agentkit.backend.installer.upgrade._digest import config_file_digest

    if not registered_digest or is_filesystem_link(config_path):
        return None
    backup_path = config_path.with_name(config_path.name + BACKUP_SUFFIX)
    if is_filesystem_link(backup_path) or not backup_path.is_file():
        return None
    try:
        if config_file_digest(backup_path) != registered_digest:
            return None
        loaded = yaml.safe_load(backup_path.read_text(encoding="utf-8"))
        if not isinstance(loaded, dict):
            return None
        source = dict(loaded)
        expected = _render_config(migrate_config(source, target_version))
        if config_path.read_bytes() != expected.encode("utf-8"):
            return None
        behavior_changes: set[ConfigBehaviorChange] = set()
        if has_historical_disabled_vectordb(source):
            behavior_changes.add(ConfigBehaviorChange.MANDATORY_VECTORDB_ENABLED)
        return CompletedConfigMigrationWitness(
            behavior_changes=frozenset(behavior_changes),
        )
    except (ConfigError, ConfigMigrationError, OSError, UnicodeError, yaml.YAMLError):
        return None


def _replace_config_if_unchanged(
    plan: ConfigMigrationPlan,
    staged_path: Path,
) -> None:
    """CAS the staged migration result over the validated baseline."""
    _assert_baseline_current(plan.baseline, mutation="final replacement")
    os.replace(staged_path, plan.baseline.path)


def migrate_config_file(plan: ConfigMigrationPlan) -> bool:
    """Apply a prepared ``project.yaml`` migration plan (FK-51 §51.4).

    The file-level wrapper around :func:`migrate_config`:

    The plan already binds parsing, transforms and backup bytes to one baseline.
    If a foreign write changes either the file identity or digest before backup
    or before the final replace, the operation fails closed and leaves those
    foreign bytes untouched.

    On any migration failure AFTER the backup the original is recoverable from
    the ``.bak`` (story §6); the backup itself is written before any mutation.

    Args:
        plan: The prepared migration plan and its validated byte baseline.

    Returns:
        ``True`` when a migration was performed (backup + rewrite), ``False``
        when the config was already at the target version.

    Raises:
        ConfigMigrationError: On a changed baseline or any staging/backup error.
    """
    if not plan.needs_migration:
        return False

    # Prove both derived staging paths before the first on-disk mutation. The
    # individual writers repeat the same central check at their own boundary.
    config_path = plan.baseline.path
    backup_path = config_path.with_name(config_path.name + BACKUP_SUFFIX)
    _migration_temp_path(backup_path)
    tmp_path = _migration_temp_path(config_path)

    # FK-51 §51.4.3: backup BEFORE every on-disk mutation.
    backup_config_file(plan.baseline)
    try:
        if tmp_path.exists():
            tmp_path.unlink()
        with tmp_path.open("xb") as staged:
            staged.write(plan.rendered_content)
            staged.flush()
            os.fsync(staged.fileno())
        _replace_config_if_unchanged(plan, tmp_path)
    except BaseException:
        if tmp_path.exists() and not is_filesystem_link(tmp_path):
            tmp_path.unlink()
        raise
    return True


__all__ = [
    "BACKUP_SUFFIX",
    "CONFIG_VERSION_KEY",
    "FEATURES_KEY",
    "OBSOLETE_PERMISSIONS_KEY",
    "PIPELINE_KEY",
    "VECTORDB_KEY",
    "CompletedConfigMigrationWitness",
    "ConfigFileBaseline",
    "ConfigBehaviorChange",
    "ConfigMigrationError",
    "ConfigMigrationPlan",
    "MigrationStep",
    "backup_config_file",
    "completed_config_migration_witness",
    "enable_mandatory_vectordb_config",
    "has_historical_disabled_vectordb",
    "matches_completed_config_migration",
    "migrate_3_to_4",
    "migrate_config",
    "migrate_config_file",
    "prepare_config_migration",
    "read_config_version",
    "remove_obsolete_permission_config",
]
