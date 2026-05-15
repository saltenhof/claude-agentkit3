"""Domain entities for the project-management bounded context."""

from __future__ import annotations

import logging
import re
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

_PROJECT_KEY_PATTERN = re.compile(r"^[a-z0-9][a-z0-9-]*$")
_STORY_ID_PREFIX_PATTERN = re.compile(r"^[A-Z][A-Z0-9]{1,9}$")

_log = logging.getLogger(__name__)


class ProjectConfiguration(BaseModel):
    """Project-level configuration owned by project_management.

    ``repositories`` is the authoritative list of repos that belong to this
    project. Every story created for this project must reference only repos
    from this list (validated in story_context_manager §2.1.7).

    ``repositories[0]`` is the conventional primary repo (UI convention,
    analogous to formal.frontend-contracts.entity.story_summary.repos[0]).

    Forward-compatibility: old DB records that pre-date this field are
    accepted by the ``model_validator(mode="before")`` below, which derives a
    default from ``repo_url`` when ``repositories`` is absent.  This ensures
    that existing test databases and local sandboxes continue to load without
    crashing.  New records written after this change will always contain the
    field explicitly.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    repo_url: str
    default_branch: str
    are_url: str | None = None
    default_worker_count: int = Field(ge=1)
    repositories: list[str] = Field(default_factory=list)

    @model_validator(mode="before")
    @classmethod
    def _backfill_repositories(cls, data: Any) -> Any:
        """Derive ``repositories`` from ``repo_url`` for old records.

        When a DB record predates the ``repositories`` field the incoming dict
        will not contain the key.  To avoid breaking bootstrap of existing
        databases we derive a sensible default here and emit a WARNING so the
        operator knows about the degraded state.

        When ``repo_url`` is also absent or empty we cannot derive a default,
        so ``repositories`` is set to ``[]``.  This will produce a valid
        ``ProjectConfiguration`` entity (empty list is allowed at the schema
        level) but the application layer (lifecycle.py, routes.py) enforces
        ``min 1`` entry at write time.  Reading a legacy record with no repos
        must NOT crash — that is the forward-compat contract.

        Args:
            data: Raw input dict (or object) before Pydantic field coercion.

        Returns:
            The (possibly mutated) input data with ``repositories`` populated.
        """
        if not isinstance(data, dict):
            return data
        if "repositories" not in data:
            repo_url = data.get("repo_url", "")
            if repo_url:
                data = {**data, "repositories": [repo_url]}
                _log.warning(
                    "ProjectConfiguration loaded from an old record without "
                    "'repositories' field; defaulting to [%r].  "
                    "Update the project record to set 'repositories' explicitly.",
                    repo_url,
                )
            else:
                data = {**data, "repositories": []}
                _log.warning(
                    "ProjectConfiguration loaded from an old record without "
                    "'repositories' field and without a 'repo_url' to fall back to.  "
                    "Setting repositories=[] — operator must update this project record.",
                )
        return data

    @field_validator("repositories")
    @classmethod
    def _validate_repositories(cls, value: list[str]) -> list[str]:
        """Validate the repositories list.

        Note: minimum length (min 1) is enforced at the application layer
        (lifecycle.py ``create_project``, routes.py ``handle_patch``), NOT
        here.  This allows legacy DB records with ``repositories=[]`` to be
        loaded without crashing (forward-compatibility contract from AG3-020).

        Args:
            value: Candidate list of repository identifiers.

        Returns:
            The validated list.

        Raises:
            ``ValueError`` if any non-empty entry contains only whitespace,
            or if entries are not unique.
        """
        for entry in value:
            if not entry.strip():
                raise ValueError(
                    "repositories must not contain empty or whitespace-only strings"
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
