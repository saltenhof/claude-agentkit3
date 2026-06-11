"""Installer component namespace for project registration and bootstrap."""

from __future__ import annotations

from agentkit.installer.bootstrap_checkpoints import run_checkpoint_install
from agentkit.installer.checkpoint_engine import (
    CheckpointEngine,
    ExecutionMode,
    build_installer_flow,
)
from agentkit.installer.registration import (
    CheckpointResult,
    CheckpointStatus,
    ProjectRegistration,
    RuntimeProfile,
)
from agentkit.installer.repo_probe import (
    GhCliRepoExistenceProbe,
    RepoExistenceProbe,
    RepoProbeResult,
)
from agentkit.installer.repository import ProjectRegistrationRepository
from agentkit.installer.runner import (
    InstallConfig,
    InstallResult,
    UninstallResult,
    install_agentkit,
    uninstall_agentkit,
)
from agentkit.installer.upgrade import (
    CustomizationFootprint,
    UpgradeResult,
    UpgradeScenario,
    migrate_config,
    run_cleanup,
    run_upgrade,
)

__all__ = [
    "CheckpointEngine",
    "CheckpointResult",
    "CheckpointStatus",
    "CustomizationFootprint",
    "ExecutionMode",
    "GhCliRepoExistenceProbe",
    "InstallConfig",
    "InstallResult",
    "ProjectRegistration",
    "ProjectRegistrationRepository",
    "RepoExistenceProbe",
    "RepoProbeResult",
    "RuntimeProfile",
    "UninstallResult",
    "UpgradeResult",
    "UpgradeScenario",
    "build_installer_flow",
    "install_agentkit",
    "migrate_config",
    "run_checkpoint_install",
    "run_cleanup",
    "run_upgrade",
    "uninstall_agentkit",
]
