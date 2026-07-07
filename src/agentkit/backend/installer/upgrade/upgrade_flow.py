"""Upgrade flow — engine-driven FLOW/MODE on the AG3-088 walker (FK-51).

Upgrade is NOT a second installer (story §6 / §2.2): :func:`run_upgrade` builds
the upgrade :class:`~agentkit.backend.installer.upgrade.engine.UpgradeRequest`, constructs
the SHARED AG3-088 :class:`~agentkit.backend.installer.checkpoint_engine.engine.CheckpointEngine`
over the upgrade :func:`~agentkit.backend.installer.upgrade.engine.build_upgrade_flow`
(``level=COMPONENT``) + handler registry, runs it in the requested
``ExecutionMode`` and assembles the :class:`UpgradeResult` from the engine's
run-state. The FK-51 sequence (footprint/decision §51.8, the F-51-023 binding
guard §51.3.3, config migration §51.3.2/§51.4, hook migration §51.6, git-hook
migration §51.6.1, optional cleanup §51.7) is the engine flow's spine, NOT an
imperative helper.

Read-only modes (``dry_run`` / ``verify``) detect + decide but perform NO
mutation (FK-50 §50.2) — the engine's handlers report the WOULD-execute plan.
The never-silently-overwrite invariant F-51-023 guards the cleanup / binding /
git-hook write paths via the footprint; the config migration path uses ``.bak`` +
write (FK-prescribed, story §6).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from agentkit.backend.installer.checkpoint_engine.engine import CheckpointEngine
from agentkit.backend.installer.checkpoint_engine.execution_mode import ExecutionMode
from agentkit.backend.installer.upgrade.engine import (
    UpgradeRequest,
    UpgradeRunContext,
    build_upgrade_branch_predicate_registry,
    build_upgrade_flow,
    build_upgrade_handler_registry,
)

if TYPE_CHECKING:
    from pathlib import Path

    from agentkit.backend.governance.hook_registration import HookDefinition
    from agentkit.backend.governance.runner import Governance
    from agentkit.backend.installer.repository import ProjectRegistrationRepository
    from agentkit.backend.installer.upgrade.cleanup import CleanupOutcome, CleanupPlan
    from agentkit.backend.installer.upgrade.footprint import CustomizationFootprint
    from agentkit.backend.installer.upgrade.hook_migration import (
        GitHookMigrationOutcome,
        HookMigrationOutcome,
    )
    from agentkit.backend.installer.upgrade.scenarios import UpgradeScenarioDecision
    from agentkit.backend.skills import Skills


@dataclass(frozen=True)
class UpgradeResult:
    """The aggregate result of an :func:`run_upgrade` flow.

    Attributes:
        mode: The execution mode the flow ran in.
        scenario: The decided §51.3 :class:`UpgradeScenarioDecision`.
        footprint: The detected customization footprint.
        config_migrated: Whether the config file was migrated (``.bak`` + write).
        config_target_version: The config version migrated to (``None`` when no
            migration ran).
        hook_outcome: The §51.6 hook-migration outcome (``None`` in read-only
            modes or when no governance surface was provided).
        claude_hook_settings_migrated: Whether legacy flat Claude settings were
            rewritten to the canonical three-level shape.
        git_hook_outcome: The git-hook dispatch migration outcome (``None`` in
            read-only modes or when no migration ran).
        cleanup_outcome: The §51.7 cleanup outcome (``None`` when no cleanup ran).
        detail: Human-readable summary.
    """

    mode: ExecutionMode
    scenario: UpgradeScenarioDecision
    footprint: CustomizationFootprint
    config_migrated: bool = False
    config_target_version: str | None = None
    hook_outcome: HookMigrationOutcome | None = None
    claude_hook_settings_migrated: bool = False
    git_hook_outcome: GitHookMigrationOutcome | None = None
    cleanup_outcome: CleanupOutcome | None = None
    detail: str = ""

    @property
    def mutated(self) -> bool:
        """Return whether the flow performed any mutation."""
        return (
            self.config_migrated
            or self.claude_hook_settings_migrated
            or (self.hook_outcome is not None and self.hook_outcome.changed)
            or (self.git_hook_outcome is not None and self.git_hook_outcome.migrated)
            or (
                self.cleanup_outcome is not None
                and bool(self.cleanup_outcome.removed)
            )
        )


def run_upgrade(
    project_root: Path,
    *,
    project_key: str,
    target_config_version: str,
    registration_repo: ProjectRegistrationRepository,
    bundle_version_changed: bool = False,
    explicit_binding_switch: bool = False,
    mode: ExecutionMode = ExecutionMode.REGISTER,
    is_subagent: bool = False,
    skills: Skills | None = None,
    governance: Governance | None = None,
    desired_hook_definitions: list[HookDefinition] | None = None,
    current_hook_matchers: frozenset[str] = frozenset(),
    cleanup_plan: CleanupPlan | None = None,
) -> UpgradeResult:
    """Run the FK-51 upgrade flow THROUGH the AG3-088 engine (register/dry_run/verify).

    Builds the :class:`UpgradeRequest`, runs the upgrade flow on the shared
    :class:`CheckpointEngine`, and assembles the :class:`UpgradeResult` from the
    engine's run-state. In ``register`` mode the engine performs the prescribed
    config migration (``.bak`` + write, §51.3.2 / §51.4), the §51.6 hook
    migration via ``Governance.register_hooks`` (when a governance surface is
    given), the §51.6.1 git-hook dispatch migration and the optional §51.7
    cleanup. ``dry_run`` / ``verify`` are read-only (FK-50 §50.2).

    Args:
        project_root: The target-project root.
        project_key: The registered project key.
        target_config_version: The desired ``pipeline.config_version`` after
            migration (AG3-070 SSOT).
        registration_repo: The CP 7 registration read surface (digest source).
        bundle_version_changed: Whether the target bundle version differs from the
            currently bound version (§51.3 criterion).
        explicit_binding_switch: Whether the operator explicitly switched the
            project binding to the new bundle/profile (§51.3.3 — no auto pull).
        mode: The execution mode (defaults to ``register``).
        is_subagent: Scope flag forwarded to the CCAG footprint source.
        skills: The agent-skills top surface for the skill-binding footprint
            source (DI; defaults to the productive surface).
        governance: The governance top surface for the §51.6 hook migration.
            ``None`` skips the hook step (unit isolation without a backend).
        desired_hook_definitions: The desired hook definitions (§51.6). ``None``
            -> the productive default set is built.
        current_hook_matchers: Currently registered matchers (the obsolete split).
        cleanup_plan: The optional §51.7 cleanup plan. ``None`` -> no cleanup.

    Returns:
        The :class:`UpgradeResult` assembled from the engine run-state.

    Raises:
        CustomizationPreservationError: When an explicit binding switch or a
            cleanup target would overwrite a detected customization (F-51-023).
    """
    request = UpgradeRequest(
        project_root=project_root,
        project_key=project_key,
        target_config_version=target_config_version,
        registration_repo=registration_repo,
        bundle_version_changed=bundle_version_changed,
        explicit_binding_switch=explicit_binding_switch,
        is_subagent=is_subagent,
        skills=skills,
        governance=governance,
        desired_hook_definitions=desired_hook_definitions,
        current_hook_matchers=current_hook_matchers,
        cleanup_plan=cleanup_plan,
    )
    context = UpgradeRunContext(mode=mode, request=request)
    engine: CheckpointEngine[UpgradeRunContext] = CheckpointEngine(
        flow=build_upgrade_flow(),
        handlers=build_upgrade_handler_registry(),
        branch_predicates=build_upgrade_branch_predicate_registry(),
    )
    results = engine.run(context)

    state = context.run_state
    assert state.footprint is not None  # up_01 always runs first
    assert state.decision is not None
    detail = "; ".join(r.detail for r in results if r.detail)
    return UpgradeResult(
        mode=mode,
        scenario=state.decision,
        footprint=state.footprint,
        config_migrated=state.config_migrated,
        config_target_version=state.config_target_version,
        hook_outcome=state.hook_outcome,
        claude_hook_settings_migrated=state.claude_hook_settings_migrated,
        git_hook_outcome=state.git_hook_outcome,
        cleanup_outcome=state.cleanup_outcome,
        detail=detail,
    )


__all__ = ["UpgradeResult", "run_upgrade"]
