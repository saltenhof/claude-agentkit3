"""Typed story-exit artifact models."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from agentkit.backend.governance.principal_capabilities.principals import Principal

STORY_EXIT_PRODUCER_ID: Literal["story_exit_service"] = "story_exit_service"


class ExitReason(StrEnum):
    """The exact FK-58 §58.3 reason-code set."""

    SOLUTION_VIABILITY_REQUIRES_HUMAN_DESIGN = (
        "solution_viability_requires_human_design"
    )
    INTEGRATION_STRATEGY_NOT_SCOPE_QUESTION = (
        "integration_strategy_not_scope_question"
    )
    INTEGRATION_BUDGET_EXHAUSTED = "integration_budget_exhausted"
    APPROVED_MANIFEST_NO_LONGER_SUFFICIENT = (
        "approved_manifest_no_longer_sufficient"
    )
    BOUND_STORY_CONTRACT_NO_LONGER_FIT_FOR_DECISION_SPACE = (
        "bound_story_contract_no_longer_fit_for_decision_space"
    )


class TerminalState(StrEnum):
    """Local consumer of the consolidated story terminal-state axis."""

    CANCELLED = "Cancelled"


class ExitClass(StrEnum):
    """Official administrative exit subclasses owned by exit records."""

    VIABILITY_HANDOFF = "viability_handoff"


class AdmissibilityAssessment(BaseModel):
    """Typed FK-58 §58.3 exclusion predicates derived by the service."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    normal_difficulty_excluded: bool
    mere_agent_uncertainty_excluded: bool
    usual_remediation_excluded: bool
    split_or_replan_excluded: bool

    @property
    def passed(self) -> bool:
        """Whether all four typed prohibitions were excluded."""

        return (
            self.normal_difficulty_excluded
            and self.mere_agent_uncertainty_excluded
            and self.usual_remediation_excluded
            and self.split_or_replan_excluded
        )

    def blocking_predicates(self) -> tuple[str, ...]:
        """Return the predicate names that still block the exit."""

        blocked: list[str] = []
        if not self.normal_difficulty_excluded:
            blocked.append("normal_difficulty_excluded")
        if not self.mere_agent_uncertainty_excluded:
            blocked.append("mere_agent_uncertainty_excluded")
        if not self.usual_remediation_excluded:
            blocked.append("usual_remediation_excluded")
        if not self.split_or_replan_excluded:
            blocked.append("split_or_replan_excluded")
        return tuple(blocked)


class AlternativeReview(BaseModel):
    """Typed FK-58 §58.7 alternative review produced by story_exit_service."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    standard_contract_checked: bool
    standard_contract_rejection_reason: str = ""
    reclassification_checked: bool
    reclassification_rejection_reason: str = ""
    split_checked: bool
    split_rejection_reason: str = ""

    @field_validator(
        "standard_contract_rejection_reason",
        "reclassification_rejection_reason",
        "split_rejection_reason",
    )
    @classmethod
    def _strip_reason(cls, value: str) -> str:
        return value.strip()

    @property
    def passed(self) -> bool:
        """Whether every alternative was checked and rejected with a reason."""

        return (
            self.standard_contract_checked
            and bool(self.standard_contract_rejection_reason)
            and self.reclassification_checked
            and bool(self.reclassification_rejection_reason)
            and self.split_checked
            and bool(self.split_rejection_reason)
        )

    def blocking_checks(self) -> tuple[str, ...]:
        """Return the alternative-review fields that still block the exit."""

        blocked: list[str] = []
        if not self.standard_contract_checked:
            blocked.append("standard_contract_checked")
        if not self.standard_contract_rejection_reason:
            blocked.append("standard_contract_rejection_reason")
        if not self.reclassification_checked:
            blocked.append("reclassification_checked")
        if not self.reclassification_rejection_reason:
            blocked.append("reclassification_rejection_reason")
        if not self.split_checked:
            blocked.append("split_checked")
        if not self.split_rejection_reason:
            blocked.append("split_rejection_reason")
        return tuple(blocked)


class ExitManifestSnapshot(BaseModel):
    """Snapshot of bound run and manifest-relevant exit evidence."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    producer_id: Literal["story_exit_service"] = STORY_EXIT_PRODUCER_ID
    project_key: str
    story_id: str
    run_id: str
    session_id: str
    reason: ExitReason
    integration_budget_exhausted: bool = False
    approved_manifest_no_longer_sufficient: bool = False
    human_design_required: bool = False
    integration_strategy_blocked: bool = False
    story_contract_not_fit: bool = False
    remediation_exhausted: bool = False
    split_or_replan_available: bool = False
    reclassification_available: bool = False
    standard_contract_viable: bool = False
    architecture_blockers: tuple[str, ...] = ()
    open_questions: tuple[str, ...] = ()
    recommendation: str = ""
    out_of_contract_deltas: tuple[str, ...] = ()
    captured_at: datetime

    @field_validator(
        "architecture_blockers",
        "open_questions",
        "out_of_contract_deltas",
        mode="before",
    )
    @classmethod
    def _tuple_of_strings(cls, value: object) -> tuple[str, ...]:
        if value is None:
            return ()
        if isinstance(value, str):
            return (value.strip(),) if value.strip() else ()
        if isinstance(value, list | tuple):
            return tuple(str(item).strip() for item in value if str(item).strip())
        return ()


class DeltaQuarantine(BaseModel):
    """Optional quarantine for out-of-contract deltas."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    producer_id: Literal["story_exit_service"] = STORY_EXIT_PRODUCER_ID
    exit_id: str
    story_id: str
    deltas: tuple[str, ...]
    created_at: datetime

    @model_validator(mode="after")
    def _require_deltas(self) -> DeltaQuarantine:
        if not self.deltas:
            raise ValueError("delta quarantine requires at least one delta")
        return self


class StoryExitRecord(BaseModel):
    """Canonical audit record for an approved story exit."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    producer_id: Literal["story_exit_service"] = STORY_EXIT_PRODUCER_ID
    exit_id: str
    project_key: str
    story_id: str
    run_id: str
    session_id: str
    reason: ExitReason
    note: str | None = None
    principal: Principal
    terminal_state: TerminalState
    exit_class: ExitClass
    admissibility_assessment: AdmissibilityAssessment
    alternative_review: AlternativeReview
    artifact_paths: dict[str, str] = Field(default_factory=dict)
    created_at: datetime

    @field_validator("note")
    @classmethod
    def _strip_note(cls, value: str | None) -> str | None:
        if value is None:
            return None
        stripped = value.strip()
        return stripped or None

    @model_validator(mode="after")
    def _exit_class_only_under_cancelled(self) -> StoryExitRecord:
        if (
            self.exit_class is ExitClass.VIABILITY_HANDOFF
            and self.terminal_state is not TerminalState.CANCELLED
        ):
            raise ValueError("exit_class=viability_handoff requires Cancelled")
        if self.principal is not Principal.HUMAN_CLI:
            raise ValueError("story exit record requires principal=human_cli")
        return self

    @property
    def is_gate_admissible(self) -> bool:
        """Whether the record carries the full pre-mutation approval evidence."""

        return self.admissibility_assessment.passed and self.alternative_review.passed
