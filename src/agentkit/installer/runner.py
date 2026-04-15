"""Installer runner facade.

The implementation still lives under ``agentkit.project_ops.install`` during
the migration. New code should import from ``agentkit.installer``.
"""

from __future__ import annotations

from agentkit.project_ops.install.runner import (
    InstallConfig,
    InstallResult,
    install_agentkit,
)

__all__ = [
    "InstallConfig",
    "InstallResult",
    "install_agentkit",
]
