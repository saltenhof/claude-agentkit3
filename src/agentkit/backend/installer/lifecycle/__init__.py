"""Level-specific lifecycle operations (FK-10 §10.2.8/§10.2.9, AG3-122).

The install trinity (FK-10 §10.2.0) has three levels, each with its own typed
lifecycle verb set:

* level 2 (dev machine) — :mod:`update` (hybrid update driver) and the machine
  half of :mod:`decommission`.
* level 3 (project) — :mod:`detach` (project-detach).
* level 1 (core) — the core half of :mod:`decommission`.

A LOWER level never deletes a HIGHER level's canonical state (FK-10 §10.2.0
base rule); the modules here enforce that fail-closed.
"""

from __future__ import annotations

from agentkit.backend.installer.lifecycle.decommission import (
    CoreDecommissionError,
    CoreDecommissionRequest,
    CoreDecommissionResult,
    DecommissionLevel,
    MachineDecommissionResult,
    PinnedProject,
    ServiceController,
    StateBackendExporter,
    decommission_core,
    decommission_machine,
)
from agentkit.backend.installer.lifecycle.detach import DetachResult, detach_project
from agentkit.backend.installer.lifecycle.update import (
    REINSTALL_HINT,
    UpdateCompatError,
    UpdateDecision,
    UpdateStatus,
    evaluate_update,
)

__all__ = [
    "REINSTALL_HINT",
    "CoreDecommissionError",
    "CoreDecommissionRequest",
    "CoreDecommissionResult",
    "DecommissionLevel",
    "DetachResult",
    "MachineDecommissionResult",
    "PinnedProject",
    "ServiceController",
    "StateBackendExporter",
    "UpdateCompatError",
    "UpdateDecision",
    "UpdateStatus",
    "decommission_core",
    "decommission_machine",
    "detach_project",
    "evaluate_update",
]
