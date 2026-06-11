"""Planning-write-path ``StoryDependencyRepository`` (FK-70 §70.10.2 migration).

FIX THE MODEL / SINGLE SOURCE OF TRUTH: the legacy ``dependency_edge`` write went
``routes.py -> lifecycle.add_dependency -> StoryDependencyRepository.add ->
state_backend.story_dependency_repository (direct facade write)``. FK-70 §70.10.2
requires all planning writes to flow through the BC-9-hosted planning projection
write path. This repository implements the same ``StoryDependencyRepository`` port
but routes ``add``/``remove``/``list`` through ``PlanningProjectionAccessor`` and
the ``dependency_edge`` planning family -- so there is no direct state_backend
planning write anymore and no double write-truth.

The legacy ``StateBackendStoryDependencyRepository`` is replaced at the
composition root by this planning-backed repository for the
execution-planning HTTP write path.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from agentkit.execution_planning.entities import StoryDependency, StoryDependencyKind
from agentkit.execution_planning.errors import (
    StoryDependencyConflictError,
    StoryDependencyNotFoundError,
)
from agentkit.execution_planning.persistence.filter import (
    DependencyEdgeDeleteKey,
    PlanningProjectionFilter,
)
from agentkit.execution_planning.persistence.records import DependencyEdgeRecord
from agentkit.execution_planning.persistence.schema_kind import PlanningSchemaKind

if TYPE_CHECKING:
    from datetime import datetime

    from agentkit.execution_planning.persistence.accessor import (
        PlanningProjectionAccessor,
    )
    from agentkit.state_backend.store.planning_projection_repository import (
        StateBackendDependencyEdgeProjectionRepository,
    )

__all__ = ["PlanningWritePathStoryDependencyRepository"]


def _parse_dt(value: str) -> datetime:
    from datetime import datetime

    return datetime.fromisoformat(value)


class PlanningWritePathStoryDependencyRepository:
    """``StoryDependencyRepository`` backed by the planning projection write path.

    Args:
        accessor: The single planning write boundary (``write_projection`` /
            ``delete_projection``); ALL edge mutations (add AND remove) cross it.
        edge_repo: The concrete ``dependency_edge`` adapter, used only for the
            project-less ``read_for_story`` lookup the port's story-only
            ``list_for_story`` / project-key resolution require; the delete
            itself routes through ``accessor.delete_projection``.
    """

    def __init__(
        self,
        *,
        accessor: PlanningProjectionAccessor,
        edge_repo: StateBackendDependencyEdgeProjectionRepository,
    ) -> None:
        self._accessor = accessor
        self._edge_repo = edge_repo

    def list_for_project(self, project_key: str) -> list[StoryDependency]:
        """Load all dependency edges for one project from the planning path."""
        records = self._accessor.read_projection(
            PlanningSchemaKind.DEPENDENCY_EDGE,
            PlanningProjectionFilter(project_key=project_key),
        )
        return [
            self._record_to_entity(record)
            for record in records
            if isinstance(record, DependencyEdgeRecord)
        ]

    def list_for_story(self, story_id: str) -> list[StoryDependency]:
        """Load direct predecessor edges for one story from the planning path."""
        return [
            self._record_to_entity(record)
            for record in self._edge_repo.read_for_story(story_id)
        ]

    def add(self, edge: StoryDependency, *, project_key: str) -> None:
        """Persist one dependency edge through the planning write path.

        FAIL-CLOSED on a duplicate edge (same as the legacy repository's
        conflict semantics) so the HTTP layer keeps its 409 behaviour.
        """
        existing = [
            candidate
            for candidate in self.list_for_project(project_key)
            if candidate.story_id == edge.story_id
            and candidate.depends_on_story_id == edge.depends_on_story_id
            and candidate.kind == edge.kind
        ]
        if existing:
            raise StoryDependencyConflictError("Story dependency already exists")
        self._accessor.write_projection(
            PlanningSchemaKind.DEPENDENCY_EDGE,
            DependencyEdgeRecord(
                project_key=project_key,
                story_id=edge.story_id,
                depends_on_story_id=edge.depends_on_story_id,
                kind=edge.kind.value,
                rationale=None,
                is_hard_truth=True,
                created_at=edge.created_at.isoformat(),
                revision=1,
            ),
        )

    def remove(
        self,
        story_id: str,
        depends_on_story_id: str,
        kind: StoryDependencyKind,
    ) -> None:
        """Remove one dependency edge through the single planning write boundary.

        FIX THE MODEL: the delete is routed through
        ``PlanningProjectionAccessor.delete_projection`` (the single planning
        write top-surface), NOT directly through the concrete edge adapter -- so
        ALL dependency-edge mutations (add AND remove) cross the same boundary.
        """
        removed = self._accessor.delete_projection(
            PlanningSchemaKind.DEPENDENCY_EDGE,
            DependencyEdgeDeleteKey(
                project_key=self._resolve_project_key(
                    story_id, depends_on_story_id, kind
                ),
                story_id=story_id,
                depends_on_story_id=depends_on_story_id,
                kind=kind.value,
            ),
        )
        if removed == 0:
            raise StoryDependencyNotFoundError("Story dependency not found")

    def _resolve_project_key(
        self,
        story_id: str,
        depends_on_story_id: str,
        kind: StoryDependencyKind,
    ) -> str:
        for record in self._edge_repo.read_for_story(story_id):
            if (
                record.story_id == story_id
                and record.depends_on_story_id == depends_on_story_id
                and record.kind == kind.value
            ):
                return record.project_key
        raise StoryDependencyNotFoundError("Story dependency not found")

    @staticmethod
    def _record_to_entity(record: DependencyEdgeRecord) -> StoryDependency:
        return StoryDependency(
            story_id=record.story_id,
            depends_on_story_id=record.depends_on_story_id,
            kind=StoryDependencyKind(record.kind),
            created_at=_parse_dt(record.created_at),
        )
