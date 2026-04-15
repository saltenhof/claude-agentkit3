"""Installer component namespace for project registration and bootstrap."""

from __future__ import annotations

from agentkit.installer.runner import InstallConfig, InstallResult, install_agentkit

__all__ = [
    "InstallConfig",
    "InstallResult",
    "install_agentkit",
]
