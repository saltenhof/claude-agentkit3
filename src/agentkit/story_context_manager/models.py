"""Pydantic models for story runtime context."""

from __future__ import annotations

import re
from datetime import datetime
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
from agentkit.story_context_manager.story_model import (
    ChangeImpact,
    ConceptQuality,
    WireStoryMode,
)
from agentkit.story_context_manager.types import (
    ImplementationContract,
    StoryMode,
    StoryType,
    get_profile,
)

_STORY_ID_PATTERN = re.compile(r"^[A-Z][A-Z0-9]{1,9}-\d+$")


class StoryContext(BaseModel):
    story_uuid: UUID = Field(default_factory=uuid4)
    project_key: str
    story_number: int = Field(default=0)  # derived from story_id by model_validator if not given
    story_id: str
    story_type: StoryType
    execution_route: StoryMode | None = None
    #: Fast/Standard mode (FK-24 §24.3.3) — a SEPARATE axis from
    #: ``execution_route`` (which is the intra-run path EXECUTION/EXPLORATION/
    #: None). ``fast`` (AG3-018) disables story-scoped guards and is only
    #: legal for code-producing stories (implementation/bugfix). Defaults to
    #: ``standard``. This is NOT conflated into ``execution_route``.
    mode: WireStoryMode = WireStoryMode.STANDARD
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
    story_size: StorySize = StorySize.S
    project_root: Path | None = None
    worktree_path: Path | None = None
    worktree_map: dict[str, Path] = Field(default_factory=dict)
    participating_repos: list[str] = Field(default_factory=list)
    labels: list[str] = Field(default_factory=list)
    created_at: datetime | None = None

    # AG3-057: 4-trigger mode-determination inputs (FK-22 §22.8.1).
    # Projected from the authoritative Story stammdaten at context-build time.
    # Re-uses existing Story fields (change_impact / concept_quality), adds the
    # two still-missing run-time fields (new_structures / vectordb_conflict_resolved).

    #: Projected from ``Story.change_impact`` (authoritative owner: story_model).
    #: ``None`` when the field could not be resolved (fail-closed -> Exploration).
    change_impact: ChangeImpact | None = None

    #: Projected from ``Story.concept_quality`` (authoritative owner: story_model).
    #: ``None`` when the field could not be resolved (fail-closed -> Exploration).
    concept_quality: ConceptQuality | None = None

    #: Whether the story introduces new code / module structures.
    #: Projected from ``Story.new_structures`` (AG3-057, FK-22 §22.8.1 Trigger 3).
    #: Fail-closed default ``False``: absence of the field does NOT trigger
    #: Exploration (no new structures assumed), but also does not mask a real True.
    new_structures: bool = False

    #: Whether a VektorDB conflict has been detected and acknowledged for this story.
    #: Consumed from ``Story.vectordb_conflict_resolved`` (authoritative producer:
    #: AG3-068, FK-21 §21.12). This story only READS the value — no persistence
    #: here. Fail-closed default ``False``/absent (AG3-068 not yet merged).
    vectordb_conflict_resolved: bool = False

    #: Runtime projection of ``StorySpecification.concept_refs`` as a tuple of
    #: path strings. Used by ``_has_valid_concept_paths`` (FK-22 §22.8.1 Trigger 1).
    #: ``concept_refs`` in the StorySpec remains the persistence owner; this field
    #: is the typed run-time view for the sandbox guard (no second persistence truth).
    concept_paths: tuple[str, ...] = ()

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
        if self.story_number < 1:
            raise ValueError(
                f"story_number must be >= 1, got {self.story_number!r}"
            )

        profile = get_profile(self.story_type)

        if self.execution_route not in profile.allowed_modes:
            raise ValueError(
                "execution_route "
                f"{self.execution_route!r} is not allowed for story_type "
                f"{self.story_type!r}",
            )

        if (
            self.mode is WireStoryMode.FAST
            and self.story_type
            not in (StoryType.IMPLEMENTATION, StoryType.BUGFIX)
        ):
            raise ValueError(
                "mode=fast (FK-24 §24.3.3/§24.3.4) is only allowed for "
                "code-producing story_types (implementation/bugfix); "
                f"got story_type {self.story_type!r}",
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


__all__ = [
    "StoryContext",
]


def _story_number_from_id(story_id: str) -> int | None:
    suffix = story_id.rsplit("-", maxsplit=1)[-1]
    if not suffix.isdigit():
        return None
    return int(suffix)
