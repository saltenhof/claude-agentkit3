"""Requirements-coverage domain surface."""

from __future__ import annotations

from agentkit.requirements_coverage.are_client import AreClient
from agentkit.requirements_coverage.contract import (
    AreContext,
    AreDockpointStatus,
    AreEvidence,
    AreRequirement,
    AreRequirementType,
    ContextLoadResult,
    CoverageVerdict,
    EvidenceCoverage,
    EvidenceProducer,
    EvidenceSubmitResult,
    EvidenceType,
    LinkResult,
)
from agentkit.requirements_coverage.errors import (
    AreClientDecodeError,
    AreClientError,
    AreClientHttpError,
    AreClientResponseError,
    AreConfigurationError,
    StoryAreLinkConflictError,
    StoryAreLinkError,
    StoryAreLinkNotFoundError,
)
from agentkit.requirements_coverage.models import StoryAreLink, StoryAreLinkKind
from agentkit.requirements_coverage.repository import StoryAreLinkRepository
from agentkit.requirements_coverage.top import RequirementsCoverage

__all__ = [
    # Top-surface
    "RequirementsCoverage",
    # AreClient
    "AreClient",
    # Contract enums
    "AreDockpointStatus",
    "AreRequirementType",
    "EvidenceType",
    "EvidenceProducer",
    "EvidenceCoverage",
    # Contract models
    "AreRequirement",
    "AreContext",
    "AreEvidence",
    "LinkResult",
    "ContextLoadResult",
    "EvidenceSubmitResult",
    "CoverageVerdict",
    # Errors
    "AreClientDecodeError",
    "AreClientError",
    "AreClientHttpError",
    "AreClientResponseError",
    "AreConfigurationError",
    # Legacy StoryAreLink surface (unchanged)
    "StoryAreLink",
    "StoryAreLinkKind",
    "StoryAreLinkConflictError",
    "StoryAreLinkError",
    "StoryAreLinkNotFoundError",
    "StoryAreLinkRepository",
]
