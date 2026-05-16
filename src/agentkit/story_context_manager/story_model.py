"""Wire-level Story stammdaten model.

This module owns the fachlich authoritative Story entity for the
story_context_manager BC. It is the Single Source of Truth for
the FK-91 / formal.frontend-contracts wire contract.

Distinction from ``models.py`` (StoryContext):
  - ``StoryContext`` is the pipeline-runtime model (frozen, story_uuid,
    execution_route, phase machinery).
  - ``Story`` here is the Stammdaten (admin/frontend contract) model:
    it carries the Wire-level enums (StoryStatus, wire StorySize, etc.)
    and is what the StoryService persists and exposes.

The Wire-Adapter (``wire_adapter.py``) converts between this model and
the HTTP wire format (``repos`` <-> ``participating_repos``,
``"In Progress"`` <-> ``StoryStatus.IN_PROGRESS``).
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator

# ---------------------------------------------------------------------------
# Wire-level enums (formal.frontend-contracts.entity.story_summary)
# ---------------------------------------------------------------------------


class StoryStatus(StrEnum):
    """Story lifecycle status values with exact Wire encoding.

    The values contain spaces where the Wire contract mandates them.
    Python enum names use underscores (IN_PROGRESS) while values carry
    the exact wire string ("In Progress").
    """

    BACKLOG = "Backlog"
    APPROVED = "Approved"
    IN_PROGRESS = "In Progress"
    DONE = "Done"
    CANCELLED = "Cancelled"


class WireStoryType(StrEnum):
    """Wire-level story type values (formal.frontend-contracts)."""

    IMPLEMENTATION = "implementation"
    BUGFIX = "bugfix"
    CONCEPT = "concept"
    RESEARCH = "research"


class WireStorySize(StrEnum):
    """Wire-level story size values per DK-10 §10.4 (XS/S/M/L/XL).

    Seit AG3-021 deckungsgleich mit ``agentkit.core_types.StorySize`` —
    der frueher hier gefuehrte ``XXL``-Wert war kein Konzept-Wert und ist
    entfallen.
    """

    XS = "XS"
    S = "S"
    M = "M"
    L = "L"
    XL = "XL"


class WireStoryMode(StrEnum):
    """Wire-level story mode (standard/fast)."""

    STANDARD = "standard"
    FAST = "fast"


class ChangeImpact(StrEnum):
    """Change-impact classification with exact Wire encoding.

    The value ``"Architecture Impact"`` contains a space.
    """

    LOCAL = "Local"
    COMPONENT = "Component"
    CROSS_COMPONENT = "Cross-Component"
    ARCHITECTURE_IMPACT = "Architecture Impact"


class ConceptQuality(StrEnum):
    """Concept quality classification."""

    HIGH = "High"
    MEDIUM = "Medium"
    LOW = "Low"


class RiskLevel(StrEnum):
    """Risk level classification."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


# ---------------------------------------------------------------------------
# StorySpecification (sub-entity, 1:1 to Story)
# ---------------------------------------------------------------------------


class StorySpecification(BaseModel):
    """Story specification sub-entity.

    Corresponds to ``formal.frontend-contracts.entity.story_specification``.
    Stored in ``story_specifications`` table, FK on ``story_uuid``.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    need: str | None = None
    solution: str | None = None
    acceptance: list[str] = Field(default_factory=list)
    definition_of_done: list[str] | None = None
    concept_refs: list[str] | None = None
    guardrail_refs: list[str] | None = None
    external_sources: list[str] | None = None


# ---------------------------------------------------------------------------
# Story stammdaten (main entity)
# ---------------------------------------------------------------------------


class Story(BaseModel):
    """Wire-level story stammdaten entity.

    Owner-BC: story_context_manager (FK-02 §2.11.2).

    Identifiers:
      - ``story_uuid``: technical PK, global unique.
      - ``(project_key, story_number)``: fachlich unique per project;
        story_number is project-local monotone, atomically allocated.
      - ``story_display_id``: materialized once from
        ``Project.story_id_prefix + "-" + story_number``.

    Internal vs Wire:
      - ``participating_repos`` is the INTERNAL name (FK-21 language).
      - Wire name is ``repos``. The wire_adapter handles the conversion.

    Timestamps:
      - ``created_at``: system-managed at creation.
      - ``completed_at``: system-managed when status becomes Done.
    """

    model_config = ConfigDict(extra="forbid", frozen=False)

    # -- Identity -----------------------------------------------------------
    story_uuid: UUID = Field(default_factory=uuid4)
    project_key: str
    story_number: int = Field(ge=1)
    story_display_id: str  # e.g. "AK3-042"

    # -- Stammdaten ---------------------------------------------------------
    title: str
    story_type: WireStoryType
    status: StoryStatus = StoryStatus.BACKLOG
    size: WireStorySize = WireStorySize.M
    mode: WireStoryMode | None = None
    epic: str = ""
    module: str = ""

    # Wire: "repos" -> internal: "participating_repos" (FK-21 language)
    participating_repos: list[str] = Field(default_factory=list, min_length=1)

    change_impact: ChangeImpact = ChangeImpact.LOCAL
    concept_quality: ConceptQuality = ConceptQuality.MEDIUM
    owner: str = ""
    risk: RiskLevel = RiskLevel.LOW
    blocker: str | None = None
    labels: list[str] = Field(default_factory=list)

    # -- Read-model joins (not stored in stories table, joined from others) --
    dependencies: list[str] = Field(default_factory=list)  # list of story_display_id
    qa_rounds: int = 0
    qa_rounds_exploration: int | None = None
    qa_rounds_implementation: int | None = None
    wave: int = 0
    critical_path: bool = False
    processing_time: str | None = None

    # -- Timestamps ---------------------------------------------------------
    created_at: datetime | None = None
    completed_at: datetime | None = None


# ---------------------------------------------------------------------------
# CreateStoryInput (input DTO for StoryService.create_story)
# ---------------------------------------------------------------------------


class CreateStoryInput(BaseModel):
    """Input DTO for ``StoryService.create_story`` (FK-91 §91.1a).

    Carries all stammdaten that are accepted from the wire / pipeline
    callers.  Pydantic v2 validators coerce the wire enum strings to the
    typed ``WireStory*`` / ``ChangeImpact`` / ``ConceptQuality`` /
    ``RiskLevel`` values, so callers can pass either strings or enums.

    The wire field name ``type`` is accepted as an alias for
    ``story_type`` so that HTTP payloads validate without renaming.

    ``op_id`` and ``correlation_id`` are intentionally *not* part of this
    DTO: they belong to the transport layer (idempotency / telemetry),
    not to the story content.
    """

    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        populate_by_name=True,
    )

    project_key: str
    title: str
    story_type: WireStoryType = Field(alias="type")
    repos: list[str] = Field(min_length=1)
    epic: str = ""
    module: str = ""
    size: WireStorySize = WireStorySize.M
    mode: WireStoryMode | None = None
    change_impact: ChangeImpact = ChangeImpact.LOCAL
    concept_quality: ConceptQuality = ConceptQuality.MEDIUM
    owner: str = ""
    risk: RiskLevel = RiskLevel.LOW
    labels: list[str] = Field(default_factory=list)

    @field_validator("title")
    @classmethod
    def _title_not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("title must not be empty")
        return value

    @field_validator("repos")
    @classmethod
    def _repos_no_blanks(cls, value: list[str]) -> list[str]:
        for entry in value:
            if not entry.strip():
                raise ValueError("repos entries must not be empty")
        return value
