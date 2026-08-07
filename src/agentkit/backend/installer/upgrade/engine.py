"""The FK-51 upgrade flow as an engine-driven flow on the AG3-088 walker.

Upgrade is NOT a second installer (story §6 / §2.2): it is a flow/mode DRIVEN BY
the AG3-088 :class:`~agentkit.backend.installer.checkpoint_engine.engine.CheckpointEngine`
— the SAME deterministic walker the installer flow uses (the engine is generic
over its run-context type). This module supplies:

* :class:`UpgradeRequest` — the immutable upgrade inputs.
* :class:`UpgradeRunState` — the mutable per-run state the handlers fill (the
  footprint, the §51.3 decision, the migration outcomes), exactly mirroring the
  installer :class:`~agentkit.backend.installer.checkpoint_engine.context.CheckpointRunState`
  pattern (one explicit owner for cross-checkpoint data).
* :class:`UpgradeRunContext` — the per-run context handed to every handler;
  exposes the typed ``mode`` the engine reads.
* :func:`build_upgrade_flow` — the upgrade :class:`FlowDefinition`
  (``level=COMPONENT, owner="UpgradeFlow"``).
* the upgrade checkpoint handlers + :func:`build_upgrade_handler_registry`.

The flow spine (FK-51 §51.3-§51.7):

    up_01_detect_footprint   (§51.8 — read the four-source footprint, decide §51.3)
    -> up_02_guard_binding   (§51.3.3 / F-51-023 — block a rebind over a customization)
    -> up_03_migrate_config  (§51.3.2 / §51.4 — `.bak` + write across a version jump)
    -> up_04_migrate_hooks   (§51.6 — InstallerHookGovernance.register_hooks via migrate_hooks)
    -> up_05_migrate_git_hook (§51.6.1 — pre-commit dispatch migration, `.bak`)
    -> up_06_cleanup         (§51.7 — fail-closed obsolete cleanup; optional)

Read-only modes (``dry_run`` / ``verify``) detect + decide but mutate NOTHING
(FK-50 §50.2): the mutating handlers report the WOULD-execute plan. The engine
itself enforces the register-aborts-on-FAILED vs read-only-collects contract.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

from agentkit.backend.boundary.filesystem import assert_project_local_file_path
from agentkit.backend.installer.registration import CheckpointResult, CheckpointStatus
from agentkit.backend.installer.upgrade.cleanup import run_cleanup
from agentkit.backend.installer.upgrade.config_migration import (
    ConfigBehaviorChange,
    ConfigMigrationError,
    completed_config_migration_witness,
    migrate_config_file,
    prepare_config_migration,
)
from agentkit.backend.installer.upgrade.footprint import (
    CustomizationFootprint,
    CustomizationKind,
)
from agentkit.backend.installer.upgrade.hook_migration import (
    migrate_git_hook_dispatch,
    migrate_hooks,
    migrate_legacy_claude_hook_settings,
)
from agentkit.backend.installer.upgrade.scenarios import decide_upgrade_scenario
from agentkit.backend.process.language.model import (
    EdgeRule,
    FlowDefinition,
    FlowLevel,
    NodeDefinition,
    NodeKind,
)

if TYPE_CHECKING:
    from collections.abc import Callable

    from agentkit.backend.installer.checkpoint_engine.engine import CheckpointHandler
    from agentkit.backend.installer.checkpoint_engine.execution_mode import ExecutionMode
    from agentkit.backend.installer.repository import ProjectRegistrationRepository
    from agentkit.backend.installer.upgrade.cleanup import CleanupOutcome, CleanupPlan
    from agentkit.backend.installer.upgrade.config_migration import ConfigMigrationPlan
    from agentkit.backend.installer.upgrade.hook_migration import (
        GitHookMigrationOutcome,
        HookMigrationOutcome,
        HookRegistrationSurface,
    )
    from agentkit.backend.installer.upgrade.scenarios import UpgradeScenarioDecision
    from agentkit.backend.skills import Skills
    from agentkit_wire.governance_registration import HookDefinition

#: Upgrade flow id / owner (its own ``level=COMPONENT`` flow on the shared walker).
UPGRADE_FLOW_ID = "upgrade_flow"
UPGRADE_FLOW_OWNER = "UpgradeFlow"

#: Upgrade checkpoint node ids (English, ARCH-55; centralised — no scattered
#: string literals; typed ids, not strings, story §5).
UP_01_DETECT_FOOTPRINT = "up_01_detect_footprint"
UP_02_GUARD_BINDING = "up_02_guard_binding"
UP_03_MIGRATE_CONFIG = "up_03_migrate_config"
UP_04_MIGRATE_HOOKS = "up_04_migrate_hooks"
UP_05_MIGRATE_GIT_HOOK = "up_05_migrate_git_hook"
UP_06_CLEANUP = "up_06_cleanup"
REASON_NORM_VIOLATING_SKILL_PIN = "norm_violating_skill_pin"


@dataclass(frozen=True)
class UpgradeRequest:
    """Immutable inputs of one upgrade run (FK-51 §51.3-§51.8).

    Attributes:
        project_root: The target-project root.
        project_key: The registered project key.
        target_config_version: The desired ``pipeline.config_version`` after
            migration (AG3-070 SSOT).
        registration_repo: The CP 7 registration read surface (digest source).
        bundle_version_changed: Whether the target bundle version differs from the
            currently bound version (§51.3 criterion).
        explicit_binding_switch: Whether the operator explicitly switched the
            project binding to the new bundle/profile (§51.3.3 — no auto pull).
        skills: The agent-skills top surface for the skill-binding footprint
            source (DI; defaults to the productive surface).
        governance: The governance top surface for the §51.6 hook migration
            (``migrate_hooks`` -> ``InstallerHookGovernance.register_hooks``). ``None`` skips
            the hook step (e.g. unit isolation without a state backend).
        desired_hook_definitions: The desired hook definitions for the current
            version (§51.6). ``None`` -> the productive default set is built.
        current_hook_matchers: Currently registered matchers (the obsolete split).
        cleanup_plan: The optional §51.7 cleanup plan. ``None`` -> no cleanup.
    """

    project_root: Path
    project_key: str
    target_config_version: str
    registration_repo: ProjectRegistrationRepository
    bundle_version_changed: bool = False
    explicit_binding_switch: bool = False
    skills: Skills | None = None
    governance: HookRegistrationSurface | None = None
    desired_hook_definitions: list[HookDefinition] | None = None
    current_hook_matchers: frozenset[str] = frozenset()
    cleanup_plan: CleanupPlan | None = None


@dataclass
class UpgradeRunState:
    """Mutable per-run state the upgrade handlers fill (cross-checkpoint data).

    Mirrors the installer ``CheckpointRunState`` pattern: one explicit, typed
    owner for the data a checkpoint produces for a later one to consume, instead
    of recomputing or stashing it in hidden globals (FIX-THE-MODEL).
    """

    footprint: CustomizationFootprint | None = None
    decision: UpgradeScenarioDecision | None = None
    config_migrated: bool = False
    config_migration_resume_detected: bool = False
    config_migration_behavior_changes: frozenset[ConfigBehaviorChange] = frozenset()
    registered_config_digest_at_detection: str | None = None
    config_digest_at_detection: str | None = None
    config_digest_to_persist: str | None = None
    config_target_version: str | None = None
    hook_outcome: HookMigrationOutcome | None = None
    claude_hook_settings_migrated: bool = False
    git_hook_outcome: GitHookMigrationOutcome | None = None
    cleanup_outcome: CleanupOutcome | None = None
    obsolete_permission_rule_files_removed: tuple[str, ...] = ()


@dataclass(frozen=True)
class UpgradeRunContext:
    """Immutable per-run context handed to every upgrade handler.

    Attributes:
        mode: The typed :class:`ExecutionMode` (register / dry_run / verify); the
            engine reads this to honour the read-only / register contract.
        request: The immutable :class:`UpgradeRequest`.
        run_state: The mutable :class:`UpgradeRunState` for cross-checkpoint data.
    """

    mode: ExecutionMode
    request: UpgradeRequest
    run_state: UpgradeRunState = field(default_factory=UpgradeRunState)


def _result(
    checkpoint: str,
    *,
    status: CheckpointStatus,
    detail: str,
    start: float,
    reason: str | None = None,
) -> CheckpointResult:
    """Build a :class:`CheckpointResult` with a measured duration."""
    return CheckpointResult(
        checkpoint=checkpoint,
        status=status,
        detail=detail,
        reason=reason,
        duration_ms=max(0, int((time.monotonic() - start) * 1000)),
    )


def up_01_detect_footprint(context: UpgradeRunContext) -> CheckpointResult:
    """Detect the four-source footprint and decide the §51.3 scenario (§51.8).

    Read-only in every mode (a read aggregate, never a mutation). Records the
    footprint and the decision on the run state for the later write paths.
    """
    from agentkit.backend.installer.paths import CONFIG_DIR, PROJECT_CONFIG_FILE
    from agentkit.backend.installer.upgrade._digest import config_file_digest

    start = time.monotonic()
    req = context.request
    footprint = CustomizationFootprint.detect(
        req.project_root,
        registration_repo=req.registration_repo,
        project_key=req.project_key,
        skills=req.skills,
    )
    registration = req.registration_repo.get(req.project_key)
    registered_digest = registration.config_digest if registration is not None else ""
    config_path = assert_project_local_file_path(
        req.project_root,
        Path(CONFIG_DIR) / PROJECT_CONFIG_FILE,
    )
    on_disk_digest = (
        config_file_digest(config_path) if config_path.is_file() else registered_digest
    )
    migration_witness = (
        completed_config_migration_witness(
            config_path,
            registered_digest,
            req.target_config_version,
        )
        if registration is not None and registered_digest != on_disk_digest
        else None
    )
    migration_resumed = migration_witness is not None
    decision = decide_upgrade_scenario(
        registered_config_digest=registered_digest,
        on_disk_config_digest=(
            registered_digest if migration_resumed else on_disk_digest
        ),
        bundle_version_changed=req.bundle_version_changed,
        explicit_binding_switch=req.explicit_binding_switch,
    )
    context.run_state.footprint = footprint
    context.run_state.decision = decision
    context.run_state.config_migration_resume_detected = migration_resumed
    context.run_state.config_migration_behavior_changes = (
        migration_witness.behavior_changes
        if migration_witness is not None
        else frozenset()
    )
    context.run_state.registered_config_digest_at_detection = (
        registered_digest if registration is not None else None
    )
    context.run_state.config_digest_at_detection = (
        on_disk_digest if config_path.is_file() else None
    )
    context.run_state.config_digest_to_persist = (
        on_disk_digest if migration_resumed else None
    )
    return _result(
        UP_01_DETECT_FOOTPRINT,
        status=CheckpointStatus.PASS,
        detail=(
            f"Detected {len(footprint.points)} customization(s); scenario "
            f"{decision.scenario.value!r}."
            + (
                " Exact backup witness identifies an interrupted config "
                "migration; digest persistence will resume."
                if migration_resumed
                else ""
            )
        ),
        start=start,
    )


def _norm_violating_pins(req: UpgradeRequest) -> list[str]:
    """Report every persisted skill pinned below its bundle's conform floor.

    Read-only. Bundles without a policy floor are outside this check. A pin for
    a floored bundle that is not a comparable version fails closed because it
    cannot prove conformance.
    """
    from agentkit.backend.skills import assess_bundle_version  # noqa: PLC0415

    if req.skills is None:
        return []  # no skills surface in this run: nothing to inspect, not a finding
    violating: list[str] = []
    for binding in req.skills.list_bound_skills(req.project_root):
        # Keyed on the ACTUALLY bound bundle, not on the expected default id:
        # a project may legitimately run a different bundle, and that one has
        # its own floor (or none at all).
        assessment = assess_bundle_version(binding.bundle_id, binding.bundle_version)
        floor = assessment.minimum_version
        if floor is None:
            continue
        if not assessment.is_comparable:
            # Fail-closed: this bundle HAS a floor, and a pin that cannot be
            # compared against it cannot be shown to satisfy it. Skipping here
            # would wave through exactly the case the floor exists for.
            violating.append(f"{binding.bundle_id}@{binding.bundle_version} (not comparable to {floor})")
            continue
        if not assessment.is_conform:
            violating.append(f"{binding.bundle_id}@{binding.bundle_version} < {floor}")
    return violating


def up_02_guard_binding(context: UpgradeRunContext) -> CheckpointResult:
    """Block an explicit binding switch over a detected customization (F-51-023).

    The binding write path is non-migrating, so F-51-023 applies: a register-mode
    explicit rebind first consults the footprint and is blocked fail-closed
    (``CustomizationPreservationError``) when it would overwrite a detected
    prompt/skill binding. Read-only modes and a run without an explicit switch
    pass through.

    Raises:
        CustomizationPreservationError: When the rebind would overwrite a
            detected binding customization (F-51-023).
    """
    start = time.monotonic()
    req = context.request
    # Runs in EVERY mode and independently of the F-51-023 guard below: an
    # upgrade must not finish while the project still carries a pin whose bundle
    # executes a path the norm abolished. Otherwise the upgrade reports success
    # for a project that keeps doing the forbidden thing until someone happens
    # to run a verify.
    violating = _norm_violating_pins(req)
    if violating:
        return _result(
            UP_02_GUARD_BINDING,
            status=CheckpointStatus.FAILED,
            detail="Norm-violating skill pin(s): " + "; ".join(violating) + ". Rebind before upgrading.",
            reason=REASON_NORM_VIOLATING_SKILL_PIN,
            start=start,
        )
    if not (context.mode.mutations_allowed and req.explicit_binding_switch):
        return _result(
            UP_02_GUARD_BINDING,
            status=CheckpointStatus.PASS,
            detail="No mutating explicit binding switch; F-51-023 guard not engaged.",
            start=start,
        )
    footprint = context.run_state.footprint
    assert footprint is not None  # up_01 ran first (spine order)
    for kind in (CustomizationKind.PROMPT_BINDING, CustomizationKind.SKILL_BINDING):
        for point in footprint.points_of(kind):
            # Raises CustomizationPreservationError -> the engine surfaces it
            # fail-closed; NOTHING downstream mutates (no config write yet).
            footprint.guard_write(point.identifier, write_path="binding")
    return _result(
        UP_02_GUARD_BINDING,
        status=CheckpointStatus.PASS,
        detail="Explicit binding switch cleared the F-51-023 footprint guard.",
        start=start,
    )


def up_03_migrate_config(context: UpgradeRunContext) -> CheckpointResult:
    """Migrate the config across a version jump (§51.3.2 / §51.4, `.bak` + write).

    The §51.3.2 path is EXEMPT from F-51-023 (story §6) — ``.bak`` + write is the
    FK-prescribed path and the human re-applies edits. Read-only modes report the
    planned migration without writing (FK-50 §50.2).
    """
    from agentkit.backend.installer.paths import CONFIG_DIR, PROJECT_CONFIG_FILE
    start = time.monotonic()
    req = context.request
    # Repeat containment at the side-effect checkpoint: an ancestor could have
    # been swapped after UP 01's read-only inspection (TOCTOU fail-closed).
    config_path = assert_project_local_file_path(
        req.project_root,
        Path(CONFIG_DIR) / PROJECT_CONFIG_FILE,
    )
    if context.run_state.config_migration_resume_detected:
        _assert_resume_witness_unchanged(context, config_path)
    if not config_path.is_file():
        return _absent_config_result(context, config_path, start=start)
    migration_plan = prepare_config_migration(
        config_path,
        req.target_config_version,
        expected_digest=context.run_state.config_digest_at_detection,
    )
    vectordb_migration_planned = migration_plan.mandatory_vectordb_enabled
    if not migration_plan.needs_migration:
        return _unmigrated_config_result(context, start=start)
    if not context.mode.mutations_allowed:
        context.run_state.config_target_version = req.target_config_version
        return _planned_migration_result(
            context,
            vectordb_migration_planned=vectordb_migration_planned,
            start=start,
        )
    return _apply_config_migration(
        context,
        migration_plan,
        vectordb_migration_planned=vectordb_migration_planned,
        start=start,
    )


def _assert_resume_witness_unchanged(
    context: UpgradeRunContext,
    config_path: Path,
) -> None:
    """Fail closed unless the interrupted migration's backup witness still matches."""
    current_witness = completed_config_migration_witness(
        config_path,
        context.run_state.registered_config_digest_at_detection or "",
        context.request.target_config_version,
    )
    if (
        current_witness is None
        or current_witness.behavior_changes
        != context.run_state.config_migration_behavior_changes
    ):
        raise ConfigMigrationError(
            "Interrupted config-migration witness changed after upgrade "
            "detection; refusing backup, rewrite, or digest persistence "
            "fail-closed.",
            detail={"config_path": str(config_path)},
        )


def _absent_config_result(
    context: UpgradeRunContext,
    config_path: Path,
    *,
    start: float,
) -> CheckpointResult:
    """Report a missing project.yaml -- unless detection had already digested one."""
    if context.run_state.config_digest_at_detection is not None:
        raise ConfigMigrationError(
            "project.yaml disappeared or became a non-file after upgrade "
            "detection; refusing digest persistence fail-closed.",
            detail={
                "detected_digest": context.run_state.config_digest_at_detection,
                "config_path": str(config_path),
            },
        )
    return _result(
        UP_03_MIGRATE_CONFIG,
        status=CheckpointStatus.SKIPPED,
        detail="No on-disk project.yaml; nothing to migrate.",
        reason="no_on_disk_config",
        start=start,
    )


def _unmigrated_config_result(
    context: UpgradeRunContext,
    *,
    start: float,
) -> CheckpointResult:
    """Report a config already at the target shape, resumed VectorDB switch included."""
    req = context.request
    vectordb_migration_resumed = (
        ConfigBehaviorChange.MANDATORY_VECTORDB_ENABLED
        in context.run_state.config_migration_behavior_changes
    )
    if not vectordb_migration_resumed:
        return _result(
            UP_03_MIGRATE_CONFIG,
            status=CheckpointStatus.PASS,
            detail="config already at target shape and version; no migration.",
            start=start,
        )
    resume_action = (
        "digest persistence resumes"
        if context.mode.mutations_allowed
        else "digest persistence requires register mode"
    )
    return _result(
        UP_03_MIGRATE_CONFIG,
        status=CheckpointStatus.PASS,
        detail=(
            f"Project {req.project_key!r} at {req.project_root}: "
            "pipeline.features.vectordb changed from false to true; "
            "VectorDB is mandatory, so the interrupted upgrade changed "
            "project behavior from disabled to enabled. Exact backup "
            f"witness verified; {resume_action}."
        ),
        start=start,
    )


def _planned_migration_result(
    context: UpgradeRunContext,
    *,
    vectordb_migration_planned: bool,
    start: float,
) -> CheckpointResult:
    """Report the read-only migration plan without touching the config."""
    req = context.request
    behavior_change_note = ""
    if vectordb_migration_planned:
        behavior_change_note = (
            f"Project {req.project_key!r} at {req.project_root}: would "
            "change pipeline.features.vectordb from false to true; "
            "VectorDB is mandatory, so this upgrade would change "
            "project behavior from disabled to enabled. "
        )
    return _result(
        UP_03_MIGRATE_CONFIG,
        status=CheckpointStatus.SKIPPED,
        detail=behavior_change_note
        + "[plan] Would write `.bak`, repair retired config values, "
        f"and migrate config to {req.target_config_version} (no "
        "mutation in read-only mode).",
        reason="planned_no_mutation",
        start=start,
    )


def _apply_config_migration(
    context: UpgradeRunContext,
    migration_plan: ConfigMigrationPlan,
    *,
    vectordb_migration_planned: bool,
    start: float,
) -> CheckpointResult:
    """Write the `.bak`, migrate the config, and record what the upgrade changed."""
    req = context.request
    migrated = migrate_config_file(migration_plan)
    context.run_state.config_migrated = migrated
    if migrated:
        context.run_state.config_digest_to_persist = migration_plan.migrated_digest
    context.run_state.config_target_version = (
        req.target_config_version if migrated else None
    )
    return _result(
        UP_03_MIGRATE_CONFIG,
        status=CheckpointStatus.UPDATED if migrated else CheckpointStatus.PASS,
        detail=_migration_detail(
            req.project_key,
            str(req.project_root),
            req.target_config_version,
            migrated=migrated,
            vectordb_migration_planned=vectordb_migration_planned,
        ),
        start=start,
    )


def _migration_detail(
    project_key: str,
    project_root: str,
    target_config_version: str,
    *,
    migrated: bool,
    vectordb_migration_planned: bool,
) -> str:
    """Describe what the migration did, naming a VectorDB behavior change first."""
    if not migrated:
        return "config already current; no migration."
    if vectordb_migration_planned:
        return (
            f"Project {project_key!r} at {project_root}: changed "
            "pipeline.features.vectordb from false to true; VectorDB is "
            "mandatory, so this upgrade changed project behavior from "
            "disabled to enabled. Migrated config shape and version to "
            f"{target_config_version} (.bak written)."
        )
    return (
        "Migrated config shape and version to "
        f"{target_config_version} (.bak written)."
    )


def up_04_migrate_hooks(context: UpgradeRunContext) -> CheckpointResult:
    """Migrate project hooks via ``InstallerHookGovernance.register_hooks`` (§51.6, AC4).

    Genuinely wires :func:`migrate_hooks` -> ``InstallerHookGovernance.register_hooks`` into
    the engine-driven upgrade flow (no longer a built-but-unwired helper). When
    no governance surface is provided the step is skipped (unit isolation).
    Read-only modes report the planned registration without registering.
    """
    start = time.monotonic()
    req = context.request
    if context.mode.mutations_allowed:
        context.run_state.claude_hook_settings_migrated = (
            migrate_legacy_claude_hook_settings(req.project_root)
        )
    if req.governance is None:
        detail = "No governance surface provided; hook migration not wired here."
        if context.run_state.claude_hook_settings_migrated:
            detail = (
                "Migrated legacy Claude hook settings to the three-level shape. "
                + detail
            )
        return _result(
            UP_04_MIGRATE_HOOKS,
            status=CheckpointStatus.SKIPPED,
            detail=detail,
            reason="no_governance_surface",
            start=start,
        )
    desired = (
        req.desired_hook_definitions
        if req.desired_hook_definitions is not None
        else _build_default_hook_definitions()
    )
    if not context.mode.mutations_allowed:
        return _result(
            UP_04_MIGRATE_HOOKS,
            status=CheckpointStatus.SKIPPED,
            detail=(
                "[plan] Would register "
                f"{len(desired)} hook definition(s) via InstallerHookGovernance.register_hooks "
                "(no mutation in read-only mode)."
            ),
            reason="planned_no_mutation",
            start=start,
        )
    outcome = migrate_hooks(
        req.governance, desired, current_matchers=req.current_hook_matchers
    )
    context.run_state.hook_outcome = outcome
    changed = outcome.changed or context.run_state.claude_hook_settings_migrated
    return _result(
        UP_04_MIGRATE_HOOKS,
        status=CheckpointStatus.UPDATED if changed else CheckpointStatus.PASS,
        detail=(
            f"Registered {len(outcome.registered)} hook(s) via "
            f"InstallerHookGovernance.register_hooks; removed {len(outcome.removed)} obsolete; "
            "migrated legacy Claude settings="
            f"{context.run_state.claude_hook_settings_migrated}."
        ),
        start=start,
    )


def up_05_migrate_git_hook(context: UpgradeRunContext) -> CheckpointResult:
    """Migrate the pre-commit dispatch hook (§51.6.1, AC5).

    Read-only modes report the planned migration without writing; register mode
    runs :func:`migrate_git_hook_dispatch` (which preserves an unrecognised
    pre-commit as ``.bak`` before writing).
    """
    start = time.monotonic()
    req = context.request
    if not context.mode.mutations_allowed:
        return _result(
            UP_05_MIGRATE_GIT_HOOK,
            status=CheckpointStatus.SKIPPED,
            detail="[plan] Would migrate the pre-commit dispatch hook (no mutation).",
            reason="planned_no_mutation",
            start=start,
        )
    outcome = migrate_git_hook_dispatch(req.project_root)
    context.run_state.git_hook_outcome = outcome
    return _result(
        UP_05_MIGRATE_GIT_HOOK,
        status=CheckpointStatus.UPDATED if outcome.migrated else CheckpointStatus.PASS,
        detail=outcome.detail,
        start=start,
    )


def up_06_cleanup(context: UpgradeRunContext) -> CheckpointResult:
    """Run §51.7 cleanup and remove obsolete CCAG permission-rule files.

    Read-only modes do not mutate. Register mode first runs an optional typed
    cleanup plan, which remains protected by F-51-023, and then unconditionally
    removes the three permission-rule files retired by AG3-226. Those files are
    not customizations anymore because the productive permission authority and
    every reader have been removed.
    """
    start = time.monotonic()
    req = context.request
    if not context.mode.mutations_allowed:
        return _result(
            UP_06_CLEANUP,
            status=CheckpointStatus.SKIPPED,
            detail=(
                "[plan] Would run optional cleanup fail-closed against the "
                "footprint and remove obsolete CCAG permission-rule files."
            ),
            reason="planned_no_mutation",
            start=start,
        )
    outcome = None
    if req.cleanup_plan is not None:
        footprint = context.run_state.footprint
        assert footprint is not None  # up_01 ran first (spine order)
        outcome = run_cleanup(req.cleanup_plan, footprint)
        context.run_state.cleanup_outcome = outcome

    from agentkit.backend.installer.ccag_settings import (
        remove_obsolete_permission_rule_files,
    )

    obsolete_removed = tuple(remove_obsolete_permission_rule_files(req.project_root))
    context.run_state.obsolete_permission_rule_files_removed = obsolete_removed
    cleanup_removed_count = len(outcome.removed) if outcome is not None else 0
    changed = cleanup_removed_count > 0 or bool(obsolete_removed)
    return _result(
        UP_06_CLEANUP,
        status=CheckpointStatus.UPDATED if changed else CheckpointStatus.PASS,
        detail=(
            f"Removed {cleanup_removed_count} planned obsolete target(s) and "
            f"{len(obsolete_removed)} obsolete CCAG permission-rule file(s)."
        ),
        start=start,
    )


def _build_default_hook_definitions() -> list[HookDefinition]:
    """Return the productive default hook definitions (§51.6 desired set)."""
    from agentkit.backend.installer.ccag_settings import (
        build_installed_hook_definitions,
    )

    return build_installed_hook_definitions()


def build_upgrade_flow() -> FlowDefinition:
    """Build the upgrade :class:`FlowDefinition` (``level=COMPONENT``).

    A linear spine of upgrade checkpoints (no branches): detect/decide, the
    F-51-023 binding guard, config migration, hook migration, git-hook migration
    and the optional cleanup. The ORDER is the flow contract — the binding guard
    precedes every write path so a blocked customization aborts BEFORE any
    mutation (FK-50 §50.4 register-aborts-on-FAILED + the guard raising).
    """
    nodes: tuple[NodeDefinition, ...] = (
        NodeDefinition(
            name=UP_01_DETECT_FOOTPRINT,
            kind=NodeKind.STEP,
            handler_ref=UP_01_DETECT_FOOTPRINT,
        ),
        NodeDefinition(
            name=UP_02_GUARD_BINDING,
            kind=NodeKind.STEP,
            handler_ref=UP_02_GUARD_BINDING,
        ),
        NodeDefinition(
            name=UP_03_MIGRATE_CONFIG,
            kind=NodeKind.STEP,
            handler_ref=UP_03_MIGRATE_CONFIG,
        ),
        NodeDefinition(
            name=UP_04_MIGRATE_HOOKS,
            kind=NodeKind.STEP,
            handler_ref=UP_04_MIGRATE_HOOKS,
        ),
        NodeDefinition(
            name=UP_05_MIGRATE_GIT_HOOK,
            kind=NodeKind.STEP,
            handler_ref=UP_05_MIGRATE_GIT_HOOK,
        ),
        NodeDefinition(
            name=UP_06_CLEANUP, kind=NodeKind.STEP, handler_ref=UP_06_CLEANUP
        ),
    )
    edges: tuple[EdgeRule, ...] = (
        EdgeRule(source=UP_01_DETECT_FOOTPRINT, target=UP_02_GUARD_BINDING),
        EdgeRule(source=UP_02_GUARD_BINDING, target=UP_03_MIGRATE_CONFIG),
        EdgeRule(source=UP_03_MIGRATE_CONFIG, target=UP_04_MIGRATE_HOOKS),
        EdgeRule(source=UP_04_MIGRATE_HOOKS, target=UP_05_MIGRATE_GIT_HOOK),
        EdgeRule(source=UP_05_MIGRATE_GIT_HOOK, target=UP_06_CLEANUP),
    )
    return FlowDefinition(
        flow_id=UPGRADE_FLOW_ID,
        level=FlowLevel.COMPONENT,
        owner=UPGRADE_FLOW_OWNER,
        nodes=nodes,
        edges=edges,
    )


def build_upgrade_handler_registry() -> dict[
    str, CheckpointHandler[UpgradeRunContext]
]:
    """Return the upgrade node-id -> handler registry (every step covered)."""
    return {
        UP_01_DETECT_FOOTPRINT: up_01_detect_footprint,
        UP_02_GUARD_BINDING: up_02_guard_binding,
        UP_03_MIGRATE_CONFIG: up_03_migrate_config,
        UP_04_MIGRATE_HOOKS: up_04_migrate_hooks,
        UP_05_MIGRATE_GIT_HOOK: up_05_migrate_git_hook,
        UP_06_CLEANUP: up_06_cleanup,
    }


def build_upgrade_branch_predicate_registry() -> dict[
    str, Callable[[UpgradeRunContext], bool]
]:
    """Return the (empty) upgrade branch-predicate registry (the spine is linear)."""
    return {}


__all__ = [
    "UP_01_DETECT_FOOTPRINT",
    "UP_02_GUARD_BINDING",
    "UP_03_MIGRATE_CONFIG",
    "UP_04_MIGRATE_HOOKS",
    "UP_05_MIGRATE_GIT_HOOK",
    "UP_06_CLEANUP",
    "REASON_NORM_VIOLATING_SKILL_PIN",
    "UPGRADE_FLOW_ID",
    "UPGRADE_FLOW_OWNER",
    "UpgradeRequest",
    "UpgradeRunContext",
    "UpgradeRunState",
    "build_upgrade_branch_predicate_registry",
    "build_upgrade_flow",
    "build_upgrade_handler_registry",
    "up_01_detect_footprint",
    "up_02_guard_binding",
    "up_03_migrate_config",
    "up_04_migrate_hooks",
    "up_05_migrate_git_hook",
    "up_06_cleanup",
]
