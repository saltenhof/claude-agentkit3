"""Installer upgrade / migration / customization-preservation (FK-51).

The HIGHEST intra-BC layer of ``installation-and-bootstrap``
(architecture-conformance ``installer_upgrade``): it builds ON the AG3-088
checkpoint engine + execution modes (it is a FLOW/MODE of that engine, not a
second installer) and CONSUMES the four owner-BC top/read surfaces lent to the
:class:`CustomizationFootprint`. Nothing in the lower installer layers imports
from this package. The public surface (re-exported below, see ``__all__``)
covers config migration (§51.4), the typed scenario decision (§51.3), the
customization read-aggregate + invariant F-51-023 (§51.8), hook/git-hook
migration (§51.6), the fail-closed cleanup mode (§51.7) and the engine-driven
:func:`run_upgrade` entry point.
"""

from __future__ import annotations

from agentkit.installer.upgrade.cleanup import (
    CleanupAction,
    CleanupOutcome,
    CleanupPlan,
    run_cleanup,
)
from agentkit.installer.upgrade.config_migration import (
    BACKUP_SUFFIX,
    CONFIG_VERSION_KEY,
    PIPELINE_KEY,
    ConfigMigrationError,
    MigrationStep,
    backup_config_file,
    migrate_3_to_4,
    migrate_config,
    migrate_config_file,
    read_config_version,
)
from agentkit.installer.upgrade.engine import (
    UpgradeRequest,
    UpgradeRunContext,
    UpgradeRunState,
    build_upgrade_flow,
    build_upgrade_handler_registry,
)
from agentkit.installer.upgrade.entry import run_checkpoint_upgrade
from agentkit.installer.upgrade.footprint import (
    CustomizationFootprint,
    CustomizationKind,
    CustomizationPoint,
    CustomizationPreservationError,
)
from agentkit.installer.upgrade.hook_migration import (
    GIT_HOOK_DISPATCH_MARKERS,
    GitHookMigrationOutcome,
    HookMigrationOutcome,
    migrate_git_hook_dispatch,
    migrate_hooks,
)
from agentkit.installer.upgrade.scenarios import (
    UpgradeScenario,
    UpgradeScenarioDecision,
    decide_upgrade_scenario,
)
from agentkit.installer.upgrade.upgrade_flow import (
    UpgradeResult,
    run_upgrade,
)

__all__ = [
    "BACKUP_SUFFIX",
    "CONFIG_VERSION_KEY",
    "GIT_HOOK_DISPATCH_MARKERS",
    "PIPELINE_KEY",
    "CleanupAction",
    "CleanupOutcome",
    "CleanupPlan",
    "ConfigMigrationError",
    "CustomizationFootprint",
    "CustomizationKind",
    "CustomizationPoint",
    "CustomizationPreservationError",
    "GitHookMigrationOutcome",
    "HookMigrationOutcome",
    "MigrationStep",
    "UpgradeRequest",
    "UpgradeResult",
    "UpgradeRunContext",
    "UpgradeRunState",
    "UpgradeScenario",
    "UpgradeScenarioDecision",
    "backup_config_file",
    "build_upgrade_flow",
    "build_upgrade_handler_registry",
    "decide_upgrade_scenario",
    "migrate_3_to_4",
    "migrate_config",
    "migrate_config_file",
    "migrate_git_hook_dispatch",
    "migrate_hooks",
    "read_config_version",
    "run_checkpoint_upgrade",
    "run_cleanup",
    "run_upgrade",
]
