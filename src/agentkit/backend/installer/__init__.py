"""Installer component namespace for project registration and bootstrap."""

from __future__ import annotations

from agentkit.backend.installer.bootstrap_checkpoints import run_checkpoint_install
from agentkit.backend.installer.checkpoint_engine import (
    CheckpointEngine,
    ExecutionMode,
    build_installer_flow,
)
from agentkit.backend.installer.registration import (
    CheckpointResult,
    CheckpointStatus,
    ProjectRegistration,
    RuntimeProfile,
)
from agentkit.backend.installer.repo_probe import (
    GhCliRepoExistenceProbe,
    RepoExistenceProbe,
    RepoProbeResult,
)
from agentkit.backend.installer.repository import ProjectRegistrationRepository
from agentkit.backend.installer.runner import (
    InstallConfig,
    InstallResult,
    UninstallResult,
    install_agentkit,
    uninstall_agentkit,
)
from agentkit.backend.installer.upgrade import (
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
