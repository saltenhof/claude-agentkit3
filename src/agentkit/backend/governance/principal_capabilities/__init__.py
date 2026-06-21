"""Principal-Capability-Modell (FK-55): principals, path/operation classes,
hard capability matrix, conflict-freeze overlay and the enforcement pipeline.

Public surface (AG3-032 AK1). See FK-55 §55.3-55.10 and the formal spec
``formal.principal-capabilities.*`` for the authoritative definitions.
"""

from __future__ import annotations

from agentkit.backend.governance.principal_capabilities.enforcement import (
    CapabilityEnforcement,
    CapabilityHull,
    CapabilityResult,
    EnforcementOutcome,
)
from agentkit.backend.governance.principal_capabilities.freeze import (
    ConflictFreezeOverlay,
    LocalFreezeExport,
)
from agentkit.backend.governance.principal_capabilities.matrix import (
    CapabilityDecision,
    CapabilityMatrix,
    CapabilityVerdict,
)
from agentkit.backend.governance.principal_capabilities.operations import (
    OperationClass,
    OperationClassifier,
)
from agentkit.backend.governance.principal_capabilities.paths import (
    PathClass,
    PathClassifier,
)
from agentkit.backend.governance.principal_capabilities.principals import (
    Principal,
    PrincipalResolver,
)
from agentkit.backend.governance.principal_capabilities.service_paths import (
    is_official_service_path,
)

__all__ = [
    "CapabilityDecision",
    "CapabilityEnforcement",
    "CapabilityHull",
    "CapabilityMatrix",
    "CapabilityResult",
    "CapabilityVerdict",
    "ConflictFreezeOverlay",
    "EnforcementOutcome",
    "LocalFreezeExport",
    "OperationClass",
    "OperationClassifier",
    "PathClass",
    "PathClassifier",
    "Principal",
    "PrincipalResolver",
    "is_official_service_path",
]
