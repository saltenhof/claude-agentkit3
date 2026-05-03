"""Domain entities for the project-management bounded context."""

from __future__ import annotations

import re
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

_PROJECT_KEY_PATTERN = re.compile(r"^[a-z0-9][a-z0-9-]*$")
_STORY_ID_PREFIX_PATTERN = re.compile(r"^[A-Z][A-Z0-9]{1,9}$")


class ProjectConfiguration(BaseModel):
    """Project-level configuration owned by project_management."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    repo_url: str
    default_branch: str
    are_url: str | None = None
    default_worker_count: int = Field(ge=1)


class Project(BaseModel):
    """Canonical project entity."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    key: str
    name: str
    story_id_prefix: str
    configuration: ProjectConfiguration
    archived_at: datetime | None = None

    @field_validator("key")
    @classmethod
    def _validate_key(cls, value: str) -> str:
        if _PROJECT_KEY_PATTERN.fullmatch(value) is None:
            raise ValueError("key must match ^[a-z0-9][a-z0-9-]*$")
        return value

    @field_validator("story_id_prefix")
    @classmethod
    def _validate_story_id_prefix(cls, value: str) -> str:
        if _STORY_ID_PREFIX_PATTERN.fullmatch(value) is None:
            raise ValueError("story_id_prefix must match ^[A-Z][A-Z0-9]{1,9}$")
        return value
