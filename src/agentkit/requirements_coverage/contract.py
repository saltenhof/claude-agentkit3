"""Pydantic data models for the requirements-coverage BC top-surface.

These models represent the contract between ``RequirementsCoverage``
and its callers. All models are frozen and reject extra fields.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict


class AreDockpointStatus(StrEnum):
    """Status of an ARE dock-point invocation."""

    SKIPPED = "SKIPPED"
    PASS = "PASS"
    FAIL = "FAIL"
    ERROR = "ERROR"


class AreRequirementType(StrEnum):
    """Typed classification of an ARE requirement (FK-40 §40.4.2)."""

    REGULATORY = "regulatory"
    BUSINESS_RULE = "business_rule"
    REPORT_MAPPING = "report_mapping"
    SYSTEM = "system"
    QUALITY = "quality"


class EvidenceType(StrEnum):
    """Classification of a submitted evidence reference (FK-40 §40.5.3)."""

    TEST_REPORT = "test_report"
    COMMIT_REF = "commit_ref"
    ARTIFACT_REF = "artifact_ref"
    MANUAL_NOTE = "manual_note"


class EvidenceProducer(StrEnum):
    """Who submitted the evidence — worker or QA agent."""

    WORKER = "WORKER"
    QA = "QA"


class AreRequirement(BaseModel):
    """A single requirement fetched from ARE.

    Attributes:
        requirement_id: Opaque ARE-side identifier.
        requirement_type: Typed classification (FK-40 §40.4.2).
        summary: Short human-readable title.
        description: Optional longer description.
        must_cover: Whether evidence is mandatory before story closure.
        acceptance_criteria: List of acceptance criteria strings.
        recurring: Whether this is a recurring requirement for the
            scope/story-type (auto-linked by dock-point 1).
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    requirement_id: str
    requirement_type: AreRequirementType
    summary: str
    description: str | None = None
    must_cover: bool
    acceptance_criteria: list[str]
    recurring: bool


class AreContext(BaseModel):
    """ARE context loaded for a story (dock-point 2 result).

    Attributes:
        requirements: List of requirements fetched from ARE.
        loaded_at: Timestamp when the context was fetched.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    requirements: list[AreRequirement]
    loaded_at: datetime


class AreEvidence(BaseModel):
    """A piece of evidence submitted for one requirement (dock-point 3).

    Attributes:
        requirement_id: The ARE requirement this evidence covers.
        evidence_type: Classification of the evidence.
        evidence_ref: Concrete reference (test locator, commit SHA,
            artifact path, or free text).
        produced_by: Which agent role submitted this evidence.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    requirement_id: str
    evidence_type: EvidenceType
    evidence_ref: str
    produced_by: EvidenceProducer


class LinkResult(BaseModel):
    """Result of dock-point 1: link_requirements.

    Attributes:
        status: Dock-point execution status.
        reason: Optional explanation (e.g. ``"feature_disabled"``).
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    status: AreDockpointStatus
    reason: str | None = None


class ContextLoadResult(BaseModel):
    """Result of dock-point 2: load_context.

    Attributes:
        status: Dock-point execution status.
        are_bundle_ref: Path or identifier of the persisted ARE bundle
            artefact, or ``None`` when skipped/unavailable.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    status: AreDockpointStatus
    are_bundle_ref: str | None = None


class EvidenceSubmitResult(BaseModel):
    """Result of dock-point 3: submit_evidence.

    Attributes:
        status: Dock-point execution status.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    status: AreDockpointStatus


class CoverageVerdict(BaseModel):
    """Result of dock-point 4: check_gate (FK-40 §40.5.4).

    Attributes:
        status: Dock-point execution status.
        verdict: ``"PASS"`` or ``"FAIL"`` when gate ran; ``None`` when
            skipped.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    status: AreDockpointStatus
    verdict: str | None = None
