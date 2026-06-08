"""Stage-registry boundary module.

Re-exports the typed stage profile (:class:`StageDefinition`,
:class:`ExecutionPolicy`), the canonical Layer-1 stage catalogue
(``LAYER_1_STAGES``) and the planner (:class:`StageRegistry`). The
queryable telemetry projections (``QAStageResultRecord``,
``QAFindingRecord``) remain re-exported for the projection accessor.

Source of truth: FK-33 §33.2 (Stage-Registry) + FK-27 §27.4 (Layer-1
stage catalogue).
"""

from __future__ import annotations

from agentkit.verify_system.stage_registry.data import LAYER_1_STAGES, STANDARD_STAGES
from agentkit.verify_system.stage_registry.records import (
    QAFindingRecord,
    QAStageResultRecord,
)
from agentkit.verify_system.stage_registry.registry import StageRegistry
from agentkit.verify_system.stage_registry.stages import (
    ExecutionPolicy,
    StageDefinition,
    StageKind,
    StageOverridePolicy,
)

__all__ = [
    "LAYER_1_STAGES",
    "STANDARD_STAGES",
    "ExecutionPolicy",
    "QAFindingRecord",
    "QAStageResultRecord",
    "StageKind",
    "StageDefinition",
    "StageOverridePolicy",
    "StageRegistry",
]
