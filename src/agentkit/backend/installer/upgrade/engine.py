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
    -> up_04_migrate_hooks   (§51.6 — Governance.register_hooks via migrate_hooks)
    -> up_05_migrate_git_hook (§51.6.1 — pre-commit dispatch migration, `.bak`)
    -> up_06_cleanup         (§51.7 — fail-closed obsolete cleanup; optional)

Read-only modes (``dry_run`` / ``verify``) detect + decide but mutate NOTHING
(FK-50 §50.2): the mutating handlers report the WOULD-execute plan. The engine
itself enforces the register-aborts-on-FAILED vs read-only-collects contract.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from agentkit.backend.installer.registration import CheckpointResult, CheckpointStatus
from agentkit.backend.installer.upgrade.cleanup import run_cleanup
from agentkit.backend.installer.upgrade.config_migration import migrate_config_file
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
    from pathlib import Path

    from agentkit.backend.governance.hook_registration import HookDefinition
    from agentkit.backend.governance.runner import Governance
    from agentkit.backend.installer.checkpoint_engine.engine import CheckpointHandler
    from agentkit.backend.installer.checkpoint_engine.execution_mode import ExecutionMode
    from agentkit.backend.installer.repository import ProjectRegistrationRepository
    from agentkit.backend.installer.upgrade.cleanup import CleanupOutcome, CleanupPlan
    from agentkit.backend.installer.upgrade.hook_migration import (
        GitHookMigrationOutcome,
        HookMigrationOutcome,
    )
    from agentkit.backend.installer.upgrade.scenarios import UpgradeScenarioDecision
    from agentkit.backend.skills import Skills

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
        is_subagent: Scope flag forwarded to the CCAG footprint source.
        skills: The agent-skills top surface for the skill-binding footprint
            source (DI; defaults to the productive surface).
        governance: The governance top surface for the §51.6 hook migration
            (``migrate_hooks`` -> ``Governance.register_hooks``). ``None`` skips
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
    is_subagent: bool = False
    skills: Skills | None = None
    governance: Governance | None = None
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
    config_target_version: str | None = None
    hook_outcome: HookMigrationOutcome | None = None
    claude_hook_settings_migrated: bool = False
    git_hook_outcome: GitHookMigrationOutcome | None = None
    cleanup_outcome: CleanupOutcome | None = None


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
    from agentkit.backend.installer.paths import project_config_path
    from agentkit.backend.installer.upgrade._digest import config_file_digest

    start = time.monotonic()
    req = context.request
    footprint = CustomizationFootprint.detect(
        req.project_root,
        registration_repo=req.registration_repo,
        project_key=req.project_key,
        is_subagent=req.is_subagent,
        skills=req.skills,
    )
    registration = req.registration_repo.get(req.project_key)
    registered_digest = registration.config_digest if registration is not None else ""
    config_path = project_config_path(req.project_root)
    on_disk_digest = (
        config_file_digest(config_path) if config_path.is_file() else registered_digest
    )
    decision = decide_upgrade_scenario(
        registered_config_digest=registered_digest,
        on_disk_config_digest=on_disk_digest,
        bundle_version_changed=req.bundle_version_changed,
        explicit_binding_switch=req.explicit_binding_switch,
    )
    context.run_state.footprint = footprint
    context.run_state.decision = decision
    return _result(
        UP_01_DETECT_FOOTPRINT,
        status=CheckpointStatus.PASS,
        detail=(
            f"Detected {len(footprint.points)} customization(s); scenario "
            f"{decision.scenario.value!r}."
        ),
        start=start,
    )


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
    from agentkit.backend.installer.paths import project_config_path
    from agentkit.backend.installer.upgrade.config_migration import read_config_version

    start = time.monotonic()
    req = context.request
    config_path = project_config_path(req.project_root)
    if not config_path.is_file():
        return _result(
            UP_03_MIGRATE_CONFIG,
            status=CheckpointStatus.SKIPPED,
            detail="No on-disk project.yaml; nothing to migrate.",
            reason="no_on_disk_config",
            start=start,
        )
    import yaml

    loaded = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    current = read_config_version(loaded) if isinstance(loaded, dict) else None
    needs_migration = current is not None and current != req.target_config_version
    if not needs_migration:
        return _result(
            UP_03_MIGRATE_CONFIG,
            status=CheckpointStatus.PASS,
            detail="config already at target version; no migration.",
            start=start,
        )
    if not context.mode.mutations_allowed:
        context.run_state.config_target_version = req.target_config_version
        return _result(
            UP_03_MIGRATE_CONFIG,
            status=CheckpointStatus.SKIPPED,
            detail=(
                f"[plan] Would write `.bak` and migrate config to "
                f"{req.target_config_version} (no mutation in read-only mode)."
            ),
            reason="planned_no_mutation",
            start=start,
        )
    migrated = migrate_config_file(config_path, req.target_config_version)
    context.run_state.config_migrated = migrated
    context.run_state.config_target_version = (
        req.target_config_version if migrated else None
    )
    return _result(
        UP_03_MIGRATE_CONFIG,
        status=CheckpointStatus.UPDATED if migrated else CheckpointStatus.PASS,
        detail=(
            f"Migrated config to {req.target_config_version} (.bak written)."
            if migrated
            else "config already current; no migration."
        ),
        start=start,
    )


def up_04_migrate_hooks(context: UpgradeRunContext) -> CheckpointResult:
    """Migrate project hooks via ``Governance.register_hooks`` (§51.6, AC4).

    Genuinely wires :func:`migrate_hooks` -> ``Governance.register_hooks`` into
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
                f"{len(desired)} hook definition(s) via Governance.register_hooks "
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
            f"Governance.register_hooks; removed {len(outcome.removed)} obsolete; "
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
    """Run the §51.7 cleanup mode fail-closed against the footprint (AC6/AC8).

    No-op when the request carries no cleanup plan. Read-only modes do not mutate
    (cleanup deletes files); register mode runs :func:`run_cleanup`, which raises
    :class:`CustomizationPreservationError` if a target is a detected
    customization (F-51-023, fail-closed — no partial deletion).
    """
    start = time.monotonic()
    req = context.request
    if req.cleanup_plan is None:
        return _result(
            UP_06_CLEANUP,
            status=CheckpointStatus.PASS,
            detail="No cleanup plan; nothing to clean up.",
            start=start,
        )
    footprint = context.run_state.footprint
    assert footprint is not None  # up_01 ran first (spine order)
    if not context.mode.mutations_allowed:
        return _result(
            UP_06_CLEANUP,
            status=CheckpointStatus.SKIPPED,
            detail="[plan] Would run cleanup fail-closed against the footprint.",
            reason="planned_no_mutation",
            start=start,
        )
    outcome = run_cleanup(req.cleanup_plan, footprint)
    context.run_state.cleanup_outcome = outcome
    return _result(
        UP_06_CLEANUP,
        status=(
            CheckpointStatus.UPDATED if outcome.removed else CheckpointStatus.PASS
        ),
        detail=f"Removed {len(outcome.removed)} obsolete target(s).",
        start=start,
    )


def _build_default_hook_definitions() -> list[HookDefinition]:
    """Return the productive default hook definitions (§51.6 desired set)."""
    from agentkit.backend.governance.default_hook_definitions import (
        build_default_hook_definitions,
    )

    return build_default_hook_definitions()


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
