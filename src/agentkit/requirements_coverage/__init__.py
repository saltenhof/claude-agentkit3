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
    EvidenceProducer,
    EvidenceSubmitResult,
    EvidenceType,
    LinkResult,
)
from agentkit.requirements_coverage.errors import (
    AreCapabilityNotImplementedError,
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
    # AreClient skeleton
    "AreClient",
    # Contract enums
    "AreDockpointStatus",
    "AreRequirementType",
    "EvidenceType",
    "EvidenceProducer",
    # Contract models
    "AreRequirement",
    "AreContext",
    "AreEvidence",
    "LinkResult",
    "ContextLoadResult",
    "EvidenceSubmitResult",
    "CoverageVerdict",
    # Errors
    "AreConfigurationError",
    "AreCapabilityNotImplementedError",
    # Legacy StoryAreLink surface (unchanged)
    "StoryAreLink",
    "StoryAreLinkKind",
    "StoryAreLinkConflictError",
    "StoryAreLinkError",
    "StoryAreLinkNotFoundError",
    "StoryAreLinkRepository",
]
