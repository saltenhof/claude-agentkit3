"""Task and TaskLink models for the task-management bounded context."""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, field_validator


class TaskKind(StrEnum):
    """Task shape: reminder or concrete actionable task."""

    REMINDER = "reminder"
    ACTIONABLE = "actionable"


class TaskPriority(StrEnum):
    """Task priority values."""

    LOW = "low"
    NORMAL = "normal"
    HIGH = "high"


class TaskStatus(StrEnum):
    """Task lifecycle states."""

    OPEN = "open"
    DONE = "done"
    DISMISSED = "dismissed"


class TaskOrigin(StrEnum):
    """Originating producer category."""

    CLOSURE = "closure"
    VERIFY = "verify"
    GOVERNANCE = "governance"
    HUMAN = "human"


class ResolvedBy(StrEnum):
    """Allowed task resolution actors."""

    HUMAN = "human"
    AGENT = "agent"


class TaskTargetKind(StrEnum):
    """Allowed task-link target kinds."""

    TASK = "task"
    STORY = "story"


class TaskRelationKind(StrEnum):
    """Typed task-link relation kinds."""

    RELATES_TO = "relates_to"
    SPAWNED_STORY = "spawned_story"
    DUPLICATE_OF = "duplicate_of"


class Task(BaseModel):
    """Task entity with identity ``(project_key, task_id)``."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    task_id: str = Field(pattern=r"^TM-\d{4}-\d{4,}$")
    project_key: str = Field(min_length=1)
    kind: TaskKind
    type: str = Field(min_length=1)
    title: str = Field(min_length=1)
    body: str = Field(min_length=1)
    priority: TaskPriority
    status: TaskStatus
    origin: TaskOrigin
    source_story_id: str | None = None
    execution_report_ref: str | None = None
    created_at: datetime
    resolved_at: datetime | None = None
    resolved_by: ResolvedBy | None = None

    @field_validator("created_at", "resolved_at")
    @classmethod
    def _require_aware_utc(cls, value: datetime | None) -> datetime | None:
        """Require timezone-aware timestamps and normalize them to UTC."""
        if value is None:
            return None
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("task timestamps must be timezone-aware UTC instants")
        return value.astimezone(UTC)


class TaskLink(BaseModel):
    """TaskLink entity with identity ``(project_key, task_id, target_kind, target_id, kind)``."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    project_key: str = Field(min_length=1)
    task_id: str = Field(pattern=r"^TM-\d{4}-\d{4,}$")
    target_kind: TaskTargetKind
    target_id: str = Field(min_length=1)
    kind: TaskRelationKind


class TaskListFilter(BaseModel):
    """Project-scoped task list filter."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    status: TaskStatus | None = None
    type: str | None = None
    kind: TaskKind | None = None
    origin: TaskOrigin | None = None
