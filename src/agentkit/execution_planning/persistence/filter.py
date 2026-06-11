"""Read filter for the planning projection path (FK-70 §70.10.2)."""

from __future__ import annotations

from dataclasses import dataclass

__all__ = ["DependencyEdgeDeleteKey", "PlanningProjectionFilter"]


@dataclass(frozen=True)
class DependencyEdgeDeleteKey:
    """Composite identity for deleting one ``dependency_edge`` planning record.

    The single planning write boundary (``PlanningProjectionAccessor.
    delete_projection``) takes a typed key per family rather than free kwargs.
    ``dependency_edge`` is keyed by its full composite primary key.

    Attributes:
        project_key: Tenant/project scope key (mandant isolation).
        story_id: Dependent story.
        depends_on_story_id: Story it depends on.
        kind: Dependency kind (wire string).
    """

    project_key: str
    story_id: str
    depends_on_story_id: str
    kind: str


@dataclass(frozen=True)
class PlanningProjectionFilter:
    """Optional filter parameters for ``read_projection`` on the planning path.

    ``project_key`` is the mandant-isolation key and is mandatory for any sane
    planning read (FAIL-CLOSED at the repository read). The remaining fields are
    optional per-family narrowing predicates.

    Attributes:
        project_key: Tenant/project scope key (mandatory at read time).
        story_id: Optional story narrowing.
        plan_id: Optional plan narrowing (execution_plan/execution_wave).
        rulebook_id: Optional rulebook narrowing (rulebook_* families).
        revision: Optional revision narrowing.
    """

    project_key: str
    story_id: str | None = None
    plan_id: str | None = None
    rulebook_id: str | None = None
    revision: int | None = None
