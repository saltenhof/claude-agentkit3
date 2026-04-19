"""Pydantic models for story data."""

from __future__ import annotations

import re
from datetime import datetime
from enum import StrEnum
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field, field_validator, model_validator

from agentkit.story_context_manager.types import (
    ImplementationContract,
    StoryMode,
    StoryType,
    get_profile,
)


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
    implementation_contract: ImplementationContract | None = None
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

    @model_validator(mode="before")
    @classmethod
    def _normalize_contract_defaults(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data

        story_type_raw = data.get("story_type")
        if story_type_raw is None:
            return data

        try:
            story_type = StoryType(story_type_raw)
        except ValueError:
            return data

        profile = get_profile(story_type)
        if (
            story_type is StoryType.IMPLEMENTATION
            and data.get("implementation_contract") is None
        ):
            data = dict(data)
            data["implementation_contract"] = profile.default_implementation_contract
        return data

    @model_validator(mode="after")
    def _validate_contract_shape(self) -> StoryContext:
        profile = get_profile(self.story_type)

        if self.mode not in profile.allowed_modes:
            raise ValueError(
                f"mode {self.mode!r} is not allowed for story_type {self.story_type!r}",
            )

        if (
            self.implementation_contract
            not in profile.allowed_implementation_contracts
        ):
            if (
                self.implementation_contract is None
                and not profile.allowed_implementation_contracts
            ):
                return self
            raise ValueError(
                "implementation_contract "
                f"{self.implementation_contract!r} is not allowed for story_type "
                f"{self.story_type!r}",
            )

        return self

    @property
    def execution_route(self) -> StoryMode:
        """Semantic alias for the historic ``mode`` wire field."""

        return self.mode

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
