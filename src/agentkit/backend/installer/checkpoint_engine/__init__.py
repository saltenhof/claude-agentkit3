"""Installer CheckpointEngine (FK-50 §50.3.1).

The deterministic checkpoint-execution layer of BC ``installation-and-bootstrap``.
Models the installer as a ``FlowDefinition(level=COMPONENT, owner="Installer")``
over the existing process-DSL and walks it in one of the typed
:class:`ExecutionMode` values (register / dry_run / verify, FK-50 §50.2).

This package is the LOWEST intra-BC layer (architecture-conformance
``installer_checkpoint_engine``): it depends only on the process-DSL,
``installer.registration`` and ``installer.runner``'s config type. The concrete
checkpoint handlers live in the ``bootstrap_checkpoints`` layer above it.
"""

from __future__ import annotations

from agentkit.backend.installer.checkpoint_engine.context import (
    CheckpointContext,
    CheckpointRunState,
    ScopeInteractionMode,
)
from agentkit.backend.installer.checkpoint_engine.engine import (
    CheckpointEngine,
    CheckpointHandler,
)
from agentkit.backend.installer.checkpoint_engine.execution_mode import ExecutionMode
from agentkit.backend.installer.checkpoint_engine.flow import (
    INSTALLER_FLOW_ID,
    INSTALLER_FLOW_OWNER,
    build_installer_flow,
)

__all__ = [
    "INSTALLER_FLOW_ID",
    "INSTALLER_FLOW_OWNER",
    "CheckpointContext",
    "CheckpointEngine",
    "CheckpointHandler",
    "CheckpointRunState",
    "ExecutionMode",
    "ScopeInteractionMode",
    "build_installer_flow",
]
