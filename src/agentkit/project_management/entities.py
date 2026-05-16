"""Domain entities for the project-management bounded context."""

from __future__ import annotations

import re
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

_PROJECT_KEY_PATTERN = re.compile(r"^[a-z0-9][a-z0-9-]*$")
_STORY_ID_PREFIX_PATTERN = re.compile(r"^[A-Z][A-Z0-9]{1,9}$")


class ProjectConfiguration(BaseModel):
    """Project-level configuration owned by project_management.

    ``repositories`` is the authoritative list of repos that belong to this
    project (AG3-020).  Every story created for this project must reference
    only repos from this list (validated in story_context_manager §2.1.7).
    The field is mandatory and must hold at least one entry — empty lists
    are rejected at the schema level (no application-layer escape hatch).

    ``repositories[0]`` is the conventional primary repo (UI convention,
    analogous to formal.frontend-contracts.entity.story_summary.repos[0]).

    Forward-compatibility for legacy DB rows without a ``repositories`` key
    is the responsibility of the read-path adapter (state_backend mappers),
    NOT of this schema.  See ``backfill_legacy_configuration_payload`` in
    ``state_backend/store/mappers.py``.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    repo_url: str
    default_branch: str
    are_url: str | None = None
    default_worker_count: int = Field(ge=1)
    repositories: list[str] = Field(min_length=1)

    @field_validator("repositories")
    @classmethod
    def _validate_repositories(cls, value: list[str]) -> list[str]:
        """Reject empty/whitespace entries and duplicates.

        ``min_length=1`` is enforced by the Pydantic ``Field`` directly; this
        validator only handles per-entry quality.
        """
        for entry in value:
            if not entry.strip():
                raise ValueError(
                    "repositories must not contain empty or whitespace-only strings",
                )
        if len(value) != len(set(value)):
            raise ValueError("repositories must not contain duplicate entries")
        return value


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
