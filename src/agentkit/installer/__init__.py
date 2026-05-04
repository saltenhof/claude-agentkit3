"""Installer component namespace for project registration and bootstrap."""

from __future__ import annotations

from agentkit.installer.runner import (
    InstallConfig,
    InstallResult,
    UninstallResult,
    install_agentkit,
    uninstall_agentkit,
)

__all__ = [
    "InstallConfig",
    "InstallResult",
    "UninstallResult",
    "install_agentkit",
    "uninstall_agentkit",
]
