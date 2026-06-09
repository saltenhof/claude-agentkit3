"""Typed models for worker-health scoring and interventions."""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)

StorySize = Literal["S", "M", "L"]


def utc_now() -> datetime:
    """Return the current UTC timestamp."""

    return datetime.now(UTC)


class CommitFailureCategory(StrEnum):
    """Classified git-commit failure categories."""

    FIXABLE_LOCAL = "FIXABLE_LOCAL"
    FIXABLE_CODE = "FIXABLE_CODE"
    POLICY_CONFLICT = "POLICY_CONFLICT"
    ENVIRONMENTAL = "ENVIRONMENTAL"


class LlmAssessmentStatus(StrEnum):
    """Lifecycle states for the asynchronous LLM assessment."""

    IDLE = "idle"
    PENDING = "pending"
    COMPLETED = "completed"
    FAILED = "failed"


class InterventionKind(StrEnum):
    """Worker-health intervention kinds."""

    SOFT = "soft"
    HARD_STOP = "hard_stop"
    FINAL_CALL = "final_call"
    PERMANENT_BLOCK = "permanent_block"


class PostToolOutcome(BaseModel):
    """Harness-neutral PostToolUse outcome contract."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    exit_code: int | None = None
    stdout: str = ""
    stderr: str = ""
    tool_result: dict[str, object] | list[object] | None = None


class CommitFailureClassification(BaseModel):
    """Commit failure classification result."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    category: CommitFailureCategory
    reason: str
    base_score: int
    max_score: int


class ScoreComponents(BaseModel):
    """Weighted worker-health score components."""

    model_config = ConfigDict(extra="forbid")

    runtime: int = 0
    repetition: int = 0
    hook_conflict: int = 0
    stagnation: int = 0
    tool_calls: int = 0
    llm_assessment: int = 0

    def total(self) -> int:
        """Return the bounded sum of all components."""

        return max(
            0,
            min(
                100,
                self.runtime
                + self.repetition
                + self.hook_conflict
                + self.stagnation
                + self.tool_calls
                + self.llm_assessment,
            ),
        )


class ToolCallRecord(BaseModel):
    """Harness-neutral tool-call summary used by scoring and sidecar prompts."""

    model_config = ConfigDict(extra="forbid")

    at: datetime = Field(default_factory=utc_now)
    operation: str
    target: str = ""
    args_hash: str = ""
    command: str = ""


class HookFailure(BaseModel):
    """Recorded failed hook-sensitive operation."""

    model_config = ConfigDict(extra="forbid")

    at: datetime = Field(default_factory=utc_now)
    reason: str
    category: CommitFailureCategory
    count: int = Field(default=1, ge=1)
    contribution: int = Field(default=0, ge=0)
    stderr_excerpt: str = ""


class InterventionRecord(BaseModel):
    """Persisted worker-health intervention event."""

    model_config = ConfigDict(extra="forbid")

    at: datetime = Field(default_factory=utc_now)
    kind: InterventionKind
    score: int
    message: str


class LlmAssessmentState(BaseModel):
    """Persisted LLM assessment state."""

    model_config = ConfigDict(extra="forbid")

    status: LlmAssessmentStatus = LlmAssessmentStatus.IDLE
    result: int | None = None
    requested_at: datetime | None = None
    completed_at: datetime | None = None
    expires_at: datetime | None = None
    requested_score: int | None = None
    last_completed_score: int | None = None
    delta: int = 0
    error: str | None = None

    @field_validator("delta")
    @classmethod
    def _check_delta(cls, value: int) -> int:
        if value < -10 or value > 10:
            raise ValueError("llm assessment delta must be between -10 and 10")
        return value


class AgentHealthState(BaseModel):
    """Authoritative worker-health state stored in the state backend."""

    model_config = ConfigDict(extra="forbid")

    worker_id: str
    story_id: str
    project_key: str = ""
    run_id: str = ""
    story_size: StorySize = "M"
    started_at: datetime = Field(default_factory=utc_now)
    score_components: ScoreComponents = Field(default_factory=ScoreComponents)
    total_score: int = 0
    tool_call_count: int = 0
    tool_call_log_path: str = ""
    recent_tool_calls: list[ToolCallRecord] = Field(default_factory=list)
    hook_failures: list[HookFailure] = Field(default_factory=list)
    last_commit_at: datetime | None = None
    tests_green_since: datetime | None = None
    interventions: list[InterventionRecord] = Field(default_factory=list)
    llm_assessment: LlmAssessmentState = Field(default_factory=LlmAssessmentState)
    soft_intervention_issued: bool = False
    hard_stop_issued: bool = False
    final_call_used: bool = False
    observation_calls_remaining: int = Field(default=0, ge=0)
    last_updated: datetime = Field(default_factory=utc_now)

    @field_validator("total_score")
    @classmethod
    def _check_total_score(cls, value: int) -> int:
        if value < 0 or value > 100:
            raise ValueError("total_score must be between 0 and 100")
        return value

    @model_validator(mode="after")
    def _sync_llm_component(self) -> AgentHealthState:
        self.score_components.llm_assessment = self.llm_assessment.delta
        return self
