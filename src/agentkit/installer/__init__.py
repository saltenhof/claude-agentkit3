"""Installer component namespace for project registration and bootstrap."""

from __future__ import annotations

from agentkit.installer.registration import (
    CheckpointResult,
    CheckpointStatus,
    ProjectRegistration,
    RuntimeProfile,
)
from agentkit.installer.repository import ProjectRegistrationRepository
from agentkit.installer.runner import (
    InstallConfig,
    InstallResult,
    UninstallResult,
    install_agentkit,
    uninstall_agentkit,
)

__all__ = [
    "CheckpointResult",
    "CheckpointStatus",
    "InstallConfig",
    "InstallResult",
    "ProjectRegistration",
    "ProjectRegistrationRepository",
    "RuntimeProfile",
    "UninstallResult",
    "install_agentkit",
    "uninstall_agentkit",
]
