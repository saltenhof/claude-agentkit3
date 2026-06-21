"""Project rulebook model + compiled canonical form (FK-70 §70.7d).

A project-specific ``orchestrator-rulebook.dsl`` is an INPUT artifact for the
execution-planning domain, never direct runtime truth. Every rulebook is
translated through an official compile step into the canonical model
(``RulebookCompileResult`` carrying a ``CompiledRulebook``); the raw syntax is
never runtime truth. Rulebook changes are versioned (``rulebook_revision``) and
trigger an official re-plan, not a silent hot-reload, and may only be updated via
the official admin/control-plane path (the compile step), not by free agent
mutation in the project.

DSL boundary (FK-70 §70.7d -- NORMATIVE, do not confuse): the execution-planning
rulebook DSL is NOT the FK-20 ``FlowDefinition`` DSL. FK-20 describes the
checkpoint-engine step sequence and the PipelineEngine phase lifecycle. This
rulebook DSL describes scheduling hints, parallelization rules, priority orders
and conflict indicators for the ``ExecutionPlanningService``. Both DSLs coexist;
neither replaces the other. Confusing them produces wrong BC boundaries. This
module lives in the execution-planning (BC14) package and imports NOTHING from
the FK-20 pipeline-framework DSL.

Sources:
- FK-70 §70.7d -- rulebook as input artifact, compile step, ``rulebook_revision``,
  re-plan-not-hot-reload, admin/control-plane-only mutation, FlowDefinition
  distinction
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

__all__ = [
    "CompiledRulebook",
    "RulebookCompileResult",
    "RulebookCompileStatus",
    "RulebookRevision",
    "RulebookSchedulingRule",
]


class RulebookCompileStatus(StrEnum):
    """Result status of a rulebook compile step (FK-70 §70.7d #4)."""

    COMPILED = "compiled"
    REJECTED = "rejected"


class RulebookRevision(BaseModel):
    """One versioned revision of a project rulebook (FK-70 §70.7d #5).

    Holds the RAW rulebook syntax plus its monotonic ``revision``. The raw
    syntax is never direct runtime truth -- it must be compiled (see
    ``RulebookCompileResult``) into the canonical model before it influences
    planning. A new revision triggers a re-plan, not a hot-reload.

    Attributes:
        project_key: Tenant/project scope key.
        rulebook_id: Stable rulebook identity within the project.
        revision: Monotonic rulebook revision (>= 1).
        raw_syntax: The raw ``orchestrator-rulebook.dsl`` source text (input
            artifact, never runtime truth).
        updated_by_principal: The admin/control-plane principal that produced
            this revision (FK-70 §70.7d #6: admin/control-plane only).
        created_at: Revision creation timestamp.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    project_key: str
    rulebook_id: str
    revision: int = Field(ge=1)
    raw_syntax: str
    updated_by_principal: str
    created_at: datetime


class RulebookSchedulingRule(BaseModel):
    """One canonical scheduling rule compiled from rulebook syntax (FK-70 §70.7d).

    The rulebook DSL only maps onto the canonical FK-70 primitives; it never
    replaces them (§70.7d #3). A rule expresses a scheduling hint /
    parallelization / priority / conflict indicator in canonical typed form.

    Attributes:
        rule_kind: Closed canonical rule class (e.g. ``parallelize``,
            ``serialize``, ``priority``, ``conflict``).
        story_ids: Stories the rule applies to.
        detail: Optional canonical detail.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    rule_kind: str
    story_ids: tuple[str, ...] = Field(default_factory=tuple)
    detail: str | None = None


class CompiledRulebook(BaseModel):
    """Canonical compiled form of a rulebook revision (FK-70 §70.7d #2/#4).

    The canonical truth is the central AK3 planning model; this is the typed
    projection of a rulebook revision onto canonical scheduling rules.

    Attributes:
        project_key: Tenant/project scope key.
        rulebook_id: Stable rulebook identity.
        revision: Source rulebook revision this compiled form belongs to.
        rules: Canonical scheduling rules.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    project_key: str
    rulebook_id: str
    revision: int = Field(ge=1)
    rules: tuple[RulebookSchedulingRule, ...] = Field(default_factory=tuple)


class RulebookCompileResult(BaseModel):
    """Result of the official rulebook compile step (FK-70 §70.7d #4).

    Records the outcome of translating a ``RulebookRevision`` raw syntax into the
    canonical ``CompiledRulebook``. On ``REJECTED`` the compiled form is absent
    and ``errors`` is non-empty (FAIL-CLOSED: a rejected rulebook never becomes
    runtime truth). A successful compile also signals that an official re-plan
    must be triggered (``triggers_replan``), never a hot-reload.

    Attributes:
        project_key: Tenant/project scope key.
        rulebook_id: Stable rulebook identity.
        revision: Source rulebook revision.
        status: Compile status.
        compiled: Canonical compiled rulebook on success, else ``None``.
        errors: Compile errors on rejection (empty on success).
        triggers_replan: Whether the compile mandates an official re-plan.
        compiled_at: Compile timestamp.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    project_key: str
    rulebook_id: str
    revision: int = Field(ge=1)
    status: RulebookCompileStatus
    compiled: CompiledRulebook | None = None
    errors: tuple[str, ...] = Field(default_factory=tuple)
    triggers_replan: bool = False
    compiled_at: datetime
