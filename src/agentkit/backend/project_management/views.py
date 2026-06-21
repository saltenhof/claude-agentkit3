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


# ---------------------------------------------------------------------------
# Flow snapshot entities (AG3-091 / FK-39 / frontend-contracts §91.1a)
# ---------------------------------------------------------------------------

_FLOW_STATE = Literal[
    "done", "active", "pending", "skipped",
    "optional-pending", "optional-skipped",
    "failed", "escalated", "paused",
]


class StoryFlowSubstep(BaseModel):
    """Wire model for ``frontend-contracts.entity.story_flow_substep``."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    substep: str
    state: _FLOW_STATE
    optional: bool
    loop_group: str | None = None
    loop_position: int | None = None
    loop_size: int | None = None


class StoryFlowPhase(BaseModel):
    """Wire model for ``frontend-contracts.entity.story_flow_phase``."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    phase: Literal["setup", "exploration", "implementation", "closure"]
    state: _FLOW_STATE
    state_reason: str | None = None
    iteration: int | None = None
    iteration_loop_group: str | None = None
    substeps: list[StoryFlowSubstep]


class StoryFlowSnapshot(BaseModel):
    """Wire model for ``frontend-contracts.entity.story_flow_snapshot``."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    story_id: str
    mode: Literal["standard", "fast"]
    phases: list[StoryFlowPhase]


# ---------------------------------------------------------------------------
# Execution limits (AG3-091 / FK-70 §70.6.2)
# ---------------------------------------------------------------------------


class ExecutionLimits(BaseModel):
    """Wire model for ``frontend-contracts.entity.execution_limits``.

    Active execution caps for a project (FK-70 §70.6.2). Zero means the
    cap blocks all work. Read-only; mutation is ``update_execution_limits``.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    project_key: str
    repo_parallel_cap: int
    merge_risk_cap: int
    max_parallel_agent_cap: int
    llm_pool_cap: int
    ci_capacity_cap: int


# ---------------------------------------------------------------------------
# Coverage read-model entities (AG3-091 / FK-40 §40.5b.6)
# ---------------------------------------------------------------------------


class StoryAreLinkView(BaseModel):
    """Wire view of a single StoryAreLink edge (FK-40 §40.5b.6).

    Attributes:
        are_item_id: ARE requirement identifier.
        kind: Link kind (addresses|partial|derives_from|recurring).
        coverage_status: Live coverage status (covered|uncovered|linked).
        evidence_paths: Concrete evidence references (test locator, commit SHA,
            artifact path) for this requirement, sourced from
            ``AreClient.list_evidence`` (FK-40 §40.5b.6 / story §2.1.2).
            Empty list when no evidence has been submitted or ARE is not
            queried (no links case).
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    are_item_id: str
    kind: str
    coverage_status: str
    evidence_paths: list[str] = []


class StoryAreEvidence(BaseModel):
    """Wire model for ``frontend-contracts.entity.story_are_evidence``.

    Ist-coverage: linked requirements and coverage status per ARE item.
    Source: StoryAreLink + ARE-live-status (FK-40 §40.5b.6). Read-only.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    story_id: str
    project_key: str
    linked_requirements: list[StoryAreLinkView]


class StoryCoverageAcceptance(BaseModel):
    """Wire model for ``frontend-contracts.entity.story_coverage_acceptance``.

    Soll-coverage: addressed acceptance criteria and linked ARE requirements.
    Source: StoryAreLink (ADDRESSES/PARTIAL kinds) + story spec (FK-40 §40.5b.6).
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    story_id: str
    project_key: str
    acceptance_criteria: list[str]
    linked_requirements: list[str]
