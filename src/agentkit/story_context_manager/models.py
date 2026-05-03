"""Pydantic models for story data."""

from __future__ import annotations

import re
from datetime import datetime
from enum import StrEnum
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)

from agentkit.story_context_manager.sizing import StorySize, estimate_size
from agentkit.story_context_manager.types import (
    ImplementationContract,
    StoryMode,
    StoryType,
    get_profile,
)

_STORY_ID_PATTERN = re.compile(r"^[A-Z][A-Z0-9]{1,9}-\d+$")


class PhaseStatus(StrEnum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    PAUSED = "paused"
    COMPLETED = "completed"
    FAILED = "failed"
    ESCALATED = "escalated"
    BLOCKED = "blocked"


class StoryContext(BaseModel):
    story_uuid: UUID = Field(default_factory=uuid4)
    project_key: str
    story_number: int = Field(ge=1)
    story_id: str
    story_type: StoryType
    execution_route: StoryMode
    implementation_contract: ImplementationContract | None = None
    issue_nr: int | None = None

    @field_validator("project_key")
    @classmethod
    def _validate_project_key_non_empty(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("project_key must not be empty")
        return value

    @field_validator("story_id")
    @classmethod
    def _validate_story_id_branch_safe(cls, v: str) -> str:
        if _STORY_ID_PATTERN.fullmatch(v) is None:
            raise ValueError(
                f"story_id {v!r} must match "
                r"^[A-Z][A-Z0-9]{1,9}-\d+$"
            )
        return v

    title: str = ""
    story_size: StorySize = StorySize.SMALL
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

        data = dict(data)
        if data.get("story_number") is None and isinstance(data.get("story_id"), str):
            data["story_number"] = _story_number_from_id(data["story_id"])

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
            data["implementation_contract"] = profile.default_implementation_contract
        if data.get("story_size") is None:
            labels = data.get("labels")
            title = data.get("title")
            data["story_size"] = estimate_size(
                list(labels) if isinstance(labels, list) else [],
                title if isinstance(title, str) else "",
            )
        return data

    @model_validator(mode="after")
    def _validate_contract_shape(self) -> StoryContext:
        profile = get_profile(self.story_type)

        if self.execution_route not in profile.allowed_modes:
            raise ValueError(
                "execution_route "
                f"{self.execution_route!r} is not allowed for story_type "
                f"{self.story_type!r}",
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
    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        populate_by_name=True,
    )


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


def _story_number_from_id(story_id: str) -> int | None:
    suffix = story_id.rsplit("-", maxsplit=1)[-1]
    if not suffix.isdigit():
        return None
    return int(suffix)
