"""Typed conformance-service models (FK-32, AG3-063)."""

from __future__ import annotations

from enum import StrEnum
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from agentkit.backend.verify_system.protocols import Finding


class FidelityLevel(StrEnum):
    """The four fidelity levels owned by the ConformanceService."""

    GOAL = "goal"
    DESIGN = "design"
    IMPL = "impl"
    FEEDBACK = "feedback"


class ConformanceVerdict(StrEnum):
    """Wire verdict for a conformance assessment."""

    PASS = "PASS"
    PASS_WITH_CONCERNS = "PASS_WITH_CONCERNS"
    FAIL = "FAIL"


class FidelityFailureAction(StrEnum):
    """Typed level-specific action attached to a failed fidelity result."""

    STORY_REVISION_REQUIRED = "story_revision_required"
    ESCALATED = "escalated"
    IMPLEMENTATION_BLOCKED = "implementation_blocked"
    FEEDBACK_WARNING = "feedback_warning"


class ReferenceDocument(BaseModel):
    """A validated manifest-index reference document used by an assessment."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    path: str
    scope: str
    content: str


class FidelityContext(BaseModel):
    """Input context for one ConformanceService fidelity assessment."""

    model_config = ConfigDict(
        frozen=True,
        extra="forbid",
        arbitrary_types_allowed=True,
    )

    story_id: str
    run_id: str
    project_root: Path
    story_type: str
    module: str
    subject: str
    story_description: str = ""
    tags: tuple[str, ...] = ()
    review_bundle: object | None = Field(default=None, exclude=True)
    previous_findings: tuple[Finding, ...] = ()
    qa_cycle_round: int = 1


class FidelityResult(BaseModel):
    """Result of one fidelity assessment.

    The JSON/wire field is the FK-32 glossary term ``conformance-verdict``.
    """

    model_config = ConfigDict(
        frozen=True,
        extra="forbid",
        populate_by_name=True,
        arbitrary_types_allowed=True,
    )

    level: FidelityLevel
    conformance_verdict: ConformanceVerdict = Field(alias="conformance-verdict")
    reason: str
    description: str
    references_used: tuple[str, ...]
    findings: tuple[Finding, ...] = ()
    failure_action: FidelityFailureAction | None = None
    evaluator_result: object | None = Field(default=None, exclude=True)


__all__ = [
    "ConformanceVerdict",
    "FidelityContext",
    "FidelityFailureAction",
    "FidelityLevel",
    "FidelityResult",
    "ReferenceDocument",
]
