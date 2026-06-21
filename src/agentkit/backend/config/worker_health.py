"""Worker-health monitor configuration model."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class WorkerHealthThresholdsConfig(BaseModel):
    """Score thresholds for health-monitor actions."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    warning: int = 50
    intervention: int = 70
    hard_stop: int = 85

    @model_validator(mode="after")
    def _validate_order(self) -> WorkerHealthThresholdsConfig:
        if not (0 <= self.warning < self.intervention < self.hard_stop <= 100):
            raise ValueError(
                "worker_health.scoring.thresholds must satisfy "
                "0 <= warning < intervention < hard_stop <= 100"
            )
        return self


class WorkerHealthRuntimeConfig(BaseModel):
    """Runtime scoring thresholds in minutes per story size."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    S: tuple[int, int, int] = (30, 45, 75)
    M: tuple[int, int, int] = (60, 90, 120)
    L: tuple[int, int, int] = (90, 135, 180)
    max_points: int = 30

    @field_validator("S", "M", "L")
    @classmethod
    def _validate_percentiles(cls, value: tuple[int, int, int]) -> tuple[int, int, int]:
        if not (0 < value[0] < value[1] < value[2]):
            raise ValueError("runtime percentiles must be positive and strictly ascending")
        return value


class WorkerHealthRepetitionConfig(BaseModel):
    """Repetition-pattern scoring configuration."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    window_size: int = 15
    same_file_threshold: int = 5
    max_points: int = 25


class WorkerHealthHookConflictConfig(BaseModel):
    """Hook/commit conflict scoring configuration."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    same_reason_threshold: int = 2
    max_points: int = 25


class WorkerHealthStagnationConfig(BaseModel):
    """Progress-stagnation scoring configuration."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    no_commit_warning_minutes: int = 30
    no_commit_critical_minutes: int = 60
    max_points: int = 20


class WorkerHealthToolCallsConfig(BaseModel):
    """Tool-call volume scoring configuration."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    soft_limit: int = 80
    hard_limit: int = 120
    max_points: int = 10


class WorkerHealthScoringConfig(BaseModel):
    """All deterministic worker-health scoring parameters."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    thresholds: WorkerHealthThresholdsConfig = WorkerHealthThresholdsConfig()
    runtime: WorkerHealthRuntimeConfig = WorkerHealthRuntimeConfig()
    repetition: WorkerHealthRepetitionConfig = WorkerHealthRepetitionConfig()
    hook_conflict: WorkerHealthHookConflictConfig = WorkerHealthHookConflictConfig()
    stagnation: WorkerHealthStagnationConfig = WorkerHealthStagnationConfig()
    tool_calls: WorkerHealthToolCallsConfig = WorkerHealthToolCallsConfig()


class WorkerHealthLlmAssessmentConfig(BaseModel):
    """Asynchronous LLM assessment configuration."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    trigger_score: int = 50
    throttle_seconds: int = 600
    timeout_seconds: int = 45
    max_delta: int = 10
    score_rise_threshold: int = 10
    models: list[str] = Field(default_factory=lambda: ["gemini", "grok", "qwen"])


class WorkerHealthSidecarConfig(BaseModel):
    """Worker-health sidecar lifecycle configuration."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    poll_interval_seconds: int = 60
    idle_shutdown_seconds: int = 300


class WorkerHealthToolCallLogConfig(BaseModel):
    """Tool-call-log artifact configuration."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    max_entries: int = 500


class WorkerHealthConfig(BaseModel):
    """Mandatory worker-health monitor configuration.

    The model intentionally has no ``enabled`` or ``disabled`` field. The monitor
    is mandatory; only thresholds and sidecar timing are configurable.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    scoring: WorkerHealthScoringConfig = WorkerHealthScoringConfig()
    llm_assessment: WorkerHealthLlmAssessmentConfig = WorkerHealthLlmAssessmentConfig()
    sidecar: WorkerHealthSidecarConfig = WorkerHealthSidecarConfig()
    tool_call_log: WorkerHealthToolCallLogConfig = WorkerHealthToolCallLogConfig()


__all__ = [
    "WorkerHealthConfig",
    "WorkerHealthHookConflictConfig",
    "WorkerHealthLlmAssessmentConfig",
    "WorkerHealthRepetitionConfig",
    "WorkerHealthRuntimeConfig",
    "WorkerHealthScoringConfig",
    "WorkerHealthSidecarConfig",
    "WorkerHealthStagnationConfig",
    "WorkerHealthThresholdsConfig",
    "WorkerHealthToolCallLogConfig",
    "WorkerHealthToolCallsConfig",
]
