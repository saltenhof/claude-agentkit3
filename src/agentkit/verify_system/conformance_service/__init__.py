"""ConformanceService public surface (FK-32, AG3-063)."""

from __future__ import annotations

from agentkit.verify_system.conformance_service.models import (
    ConformanceVerdict,
    FidelityContext,
    FidelityFailureAction,
    FidelityLevel,
    FidelityResult,
    ReferenceDocument,
)
from agentkit.verify_system.conformance_service.service import (
    FILE_UPLOAD_THRESHOLD_BYTES,
    HARD_LIMIT_BYTES,
    ConformanceEvaluation,
    ConformanceEvaluationPort,
    ConformanceManifestError,
    ConformanceService,
    StructuredEvaluatorConformanceAdapter,
    identify_references,
)

__all__ = [
    "ConformanceEvaluation",
    "ConformanceEvaluationPort",
    "ConformanceManifestError",
    "ConformanceService",
    "ConformanceVerdict",
    "FidelityContext",
    "FidelityFailureAction",
    "FidelityLevel",
    "FidelityResult",
    "HARD_LIMIT_BYTES",
    "FILE_UPLOAD_THRESHOLD_BYTES",
    "ReferenceDocument",
    "StructuredEvaluatorConformanceAdapter",
    "identify_references",
]
