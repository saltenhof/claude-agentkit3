"""Project operations: install, upgrade, checkpoint, merge-preservation.

Public API
----------
.. autofunction:: install_agentkit
.. autoclass:: InstallConfig
.. autoclass:: InstallResult
"""

from __future__ import annotations

from agentkit.project_ops.install import (
    InstallConfig,
    InstallResult,
    install_agentkit,
)

__all__ = [
    "InstallConfig",
    "InstallResult",
    "install_agentkit",
]
