"""Pydantic models for story data."""

from __future__ import annotations

import re
from datetime import datetime
from enum import StrEnum
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field, field_validator

from agentkit.story_context_manager.types import StoryMode, StoryType


class PhaseStatus(StrEnum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    PAUSED = "paused"
    COMPLETED = "completed"
    FAILED = "failed"
    ESCALATED = "escalated"
    BLOCKED = "blocked"


class StoryContext(BaseModel):
    story_id: str
    story_type: StoryType
    mode: StoryMode
    issue_nr: int | None = None

    @field_validator("story_id")
    @classmethod
    def _validate_story_id_branch_safe(cls, v: str) -> str:
        if not re.match(r"^[a-zA-Z0-9][a-zA-Z0-9._-]*$", v):
            raise ValueError(
                f"story_id {v!r} must start with an alphanumeric character and "
                "contain only alphanumeric characters, dots, hyphens, or underscores"
            )
        return v

    title: str = ""
    project_root: Path | None = None
    worktree_path: Path | None = None
    participating_repos: list[str] = Field(default_factory=list)
    labels: list[str] = Field(default_factory=list)
    created_at: datetime | None = None

    model_config = {"frozen": True}


class PhaseState(BaseModel):
    story_id: str
    phase: str
    status: PhaseStatus
    paused_reason: str | None = None
    review_round: int = 0
    errors: list[str] = Field(default_factory=list)
    attempt_id: str | None = None


class PhaseSnapshot(BaseModel):
    story_id: str
    phase: str
    status: PhaseStatus
    completed_at: datetime
    artifacts: list[str] = Field(default_factory=list)
    evidence: dict[str, Any] = Field(default_factory=dict)

    model_config = {"frozen": True}

__all__ = [
    "PhaseSnapshot",
    "PhaseState",
    "PhaseStatus",
    "StoryContext",
]
