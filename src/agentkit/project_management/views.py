"""Wire-level read-model views for the project-management bounded context.

These Pydantic models are the exact wire shapes consumed by the AK3
web frontend (``formal.frontend-contracts.entities``).  They are the
serialization contract of the project-management HTTP surface:

  - :class:`ProjectSummary` — ``frontend-contracts.entity.project_summary``
    (topbar project selector / ``GET /v1/projects`` list).
  - :class:`ProjectModeLock` — ``frontend-contracts.entity.project_mode_lock``
    (derived story-mode indicator).
  - :class:`StoryCounters` — ``frontend-contracts.entity.story_counters``
    (KpiBar aggregate counters).
  - :class:`ProjectDetailView` — ``frontend-contracts.entity.project_detail``
    (flat detail view for ``GET /v1/projects/{key}``).

The contract is fail-closed: every model is ``frozen`` and rejects
extra fields (``extra="forbid"``).  Field names and value enums match
the formal spec exactly; no additional fields are exposed.  The
aggregation that populates :class:`ProjectDetailView` lives in
``project_management.service`` (the views module is data-only).
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict


class ProjectSummary(BaseModel):
    """Wire summary for ``frontend-contracts.entity.project_summary``.

    Exactly the three canonical attributes — ``project_key``,
    ``display_name`` and ``status`` — and nothing else.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    project_key: str
    display_name: str
    status: Literal["active", "archived"]


class ProjectModeLock(BaseModel):
    """Wire model for ``frontend-contracts.entity.project_mode_lock``.

    The project-wide active story-mode, derived from running stories
    (FK-24 §24.3.3).  ``idle`` means there is no ``In Progress`` story
    in the project.  There is intentionally no ``holder_count`` — the
    formal spec carries only ``project_key`` and ``mode``.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    project_key: str
    mode: Literal["standard", "fast", "idle"]


class StoryCounters(BaseModel):
    """Wire model for ``frontend-contracts.entity.story_counters``.

    The six aggregate story counters for the KpiBar.  Classification is
    deterministic per
    ``frontend-contracts.invariant.counters_classification``.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    project_key: str
    total: int
    finished: int
    running: int
    ready: int
    queue: int
    blocked: int


class ProjectDetailView(BaseModel):
    """Wire model for ``frontend-contracts.entity.project_detail``.

    The detail shape is **flat**: ``project_key``, ``display_name`` and
    ``status`` are direct attributes (not nested under a project-summary
    reference), matching the formal spec exactly.  ``mode_lock`` and
    ``story_counters`` are nested wire references; ``concept_anchors`` is
    a (possibly empty) list of short normative references.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    project_key: str
    display_name: str
    status: Literal["active", "archived"]
    mode_lock: ProjectModeLock
    story_counters: StoryCounters
    concept_anchors: list[str]
