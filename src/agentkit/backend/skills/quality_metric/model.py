"""Typed result models for skill quality metrics."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, model_validator


class AttributionState(StrEnum):
    """Whether source records can be attributed to a concrete skill version."""

    ATTRIBUTED = "ATTRIBUTED"
    UNATTRIBUTABLE = "UNATTRIBUTABLE"


class SourceWindow(BaseModel):
    """Typed inclusive/exclusive time window for metric source records."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    start_at: datetime | None = None
    end_at: datetime | None = None

    @model_validator(mode="after")
    def _validate_order(self) -> SourceWindow:
        if (
            self.start_at is not None
            and self.end_at is not None
            and self.start_at >= self.end_at
        ):
            msg = "source_window.start_at must be earlier than source_window.end_at"
            raise ValueError(msg)
        return self


class SkillQualityMetric(BaseModel):
    """Aggregated quality signals for one skill in one project/window."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    skill_name: str
    project_key: str
    source_window: SourceWindow
    bundle_version: str | None
    usage_count: int
    successful_runs: int
    failed_runs: int
    unknown_status_runs: int
    avg_qa_rounds: float | None
    remediation_count: int
    incident_count: int
    incident_ids: tuple[str, ...]
    attribution: AttributionState
