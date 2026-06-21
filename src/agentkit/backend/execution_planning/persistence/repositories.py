"""Planning projection repository protocols + DI bundle (FK-70 §70.10.2, FIX THE MODEL).

The BC14 pendant to FK-69 ``ProjectionRepositories``. One thin write/read/bootstrap
adapter protocol per planning schema family, bundled in
``PlanningProjectionRepositories`` for dependency injection into the planning
write top-surface (``PlanningProjectionAccessor``). The accessor depends only on
these protocols (no direct state_backend facade import at the BC-9 write
boundary), exactly like the FK-69 accessor.

Sources:
- FK-70 §70.10.2 -- schema owner BC14, DB access BC9, single planning write path
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from agentkit.backend.execution_planning.persistence.filter import PlanningProjectionFilter
    from agentkit.backend.execution_planning.persistence.records import (
        BlockingConditionRecord,
        DependencyEdgeRecord,
        ExecutionPlanRecord,
        ExecutionWaveRecord,
        GateRecord,
        PlannedStoryRecord,
        RulebookCompileResultRecord,
        RulebookRevisionRecord,
        SchedulingBudgetRecord,
        SchedulingPolicyRecord,
    )

__all__ = [
    "BlockingConditionProjectionRepository",
    "DependencyEdgeProjectionRepository",
    "ExecutionPlanProjectionRepository",
    "ExecutionWaveProjectionRepository",
    "GateProjectionRepository",
    "PlannedStoryProjectionRepository",
    "PlanningProjectionRepositories",
    "RulebookCompileResultProjectionRepository",
    "RulebookRevisionProjectionRepository",
    "SchedulingBudgetProjectionRepository",
    "SchedulingPolicyProjectionRepository",
]


@runtime_checkable
class PlannedStoryProjectionRepository(Protocol):
    """Write/read/bootstrap adapter for ``planned_story`` (FK-70 §70.10.2)."""

    def write(self, record: PlannedStoryRecord) -> None: ...

    def read(self, filter: PlanningProjectionFilter) -> list[PlannedStoryRecord]:  # noqa: A002
        ...


@runtime_checkable
class DependencyEdgeProjectionRepository(Protocol):
    """Write/read/delete adapter for ``dependency_edge`` (FK-70 §70.10.2).

    Carries ``delete`` so the migrated ``dependency_edge`` write path (the
    planning-backed ``StoryDependencyRepository``) can remove edges through the
    planning projection path rather than a direct state_backend repo write.
    """

    def write(self, record: DependencyEdgeRecord) -> None: ...

    def read(self, filter: PlanningProjectionFilter) -> list[DependencyEdgeRecord]:  # noqa: A002
        ...

    def delete(
        self,
        *,
        project_key: str,
        story_id: str,
        depends_on_story_id: str,
        kind: str,
    ) -> int:
        """Delete one edge by composite identity; return rows removed."""
        ...


@runtime_checkable
class BlockingConditionProjectionRepository(Protocol):
    """Write/read adapter for ``blocking_condition`` (FK-70 §70.10.2)."""

    def write(self, record: BlockingConditionRecord) -> None: ...

    def read(self, filter: PlanningProjectionFilter) -> list[BlockingConditionRecord]:  # noqa: A002
        ...


@runtime_checkable
class GateProjectionRepository(Protocol):
    """Write/read adapter for ``gate`` (FK-70 §70.10.2)."""

    def write(self, record: GateRecord) -> None: ...

    def read(self, filter: PlanningProjectionFilter) -> list[GateRecord]:  # noqa: A002
        ...


@runtime_checkable
class SchedulingBudgetProjectionRepository(Protocol):
    """Write/read adapter for ``scheduling_budget`` (FK-70 §70.10.2)."""

    def write(self, record: SchedulingBudgetRecord) -> None: ...

    def read(self, filter: PlanningProjectionFilter) -> list[SchedulingBudgetRecord]:  # noqa: A002
        ...


@runtime_checkable
class SchedulingPolicyProjectionRepository(Protocol):
    """Write/read adapter for ``scheduling_policy`` (FK-70 §70.10.2)."""

    def write(self, record: SchedulingPolicyRecord) -> None: ...

    def read(self, filter: PlanningProjectionFilter) -> list[SchedulingPolicyRecord]:  # noqa: A002
        ...


@runtime_checkable
class RulebookRevisionProjectionRepository(Protocol):
    """Write/read adapter for ``rulebook_revision`` (FK-70 §70.10.2)."""

    def write(self, record: RulebookRevisionRecord) -> None: ...

    def read(self, filter: PlanningProjectionFilter) -> list[RulebookRevisionRecord]:  # noqa: A002
        ...


@runtime_checkable
class RulebookCompileResultProjectionRepository(Protocol):
    """Write/read adapter for ``rulebook_compile_result`` (FK-70 §70.10.2)."""

    def write(self, record: RulebookCompileResultRecord) -> None: ...

    def read(
        self,
        filter: PlanningProjectionFilter,  # noqa: A002
    ) -> list[RulebookCompileResultRecord]: ...


@runtime_checkable
class ExecutionPlanProjectionRepository(Protocol):
    """Write/read adapter for ``execution_plan`` (FK-70 §70.10.2)."""

    def write(self, record: ExecutionPlanRecord) -> None: ...

    def read(self, filter: PlanningProjectionFilter) -> list[ExecutionPlanRecord]:  # noqa: A002
        ...


@runtime_checkable
class ExecutionWaveProjectionRepository(Protocol):
    """Write/read adapter for ``execution_wave`` (FK-70 §70.10.2)."""

    def write(self, record: ExecutionWaveRecord) -> None: ...

    def read(self, filter: PlanningProjectionFilter) -> list[ExecutionWaveRecord]:  # noqa: A002
        ...


@dataclass(frozen=True)
class PlanningProjectionRepositories:
    """Bundle of all ten planning projection repository adapters (FK-70 §70.10.2).

    The BC14 pendant to FK-69 ``ProjectionRepositories``. Instantiated in the
    composition root and injected into ``PlanningProjectionAccessor``; the
    accessor never instantiates a concrete adapter itself.

    Attributes:
        planned_story: Adapter for ``planned_story``.
        dependency_edge: Adapter for ``dependency_edge``.
        blocking_condition: Adapter for ``blocking_condition``.
        gate: Adapter for ``gate``.
        scheduling_budget: Adapter for ``scheduling_budget``.
        scheduling_policy: Adapter for ``scheduling_policy``.
        rulebook_revision: Adapter for ``rulebook_revision``.
        rulebook_compile_result: Adapter for ``rulebook_compile_result``.
        execution_plan: Adapter for ``execution_plan``.
        execution_wave: Adapter for ``execution_wave``.
    """

    planned_story: PlannedStoryProjectionRepository
    dependency_edge: DependencyEdgeProjectionRepository
    blocking_condition: BlockingConditionProjectionRepository
    gate: GateProjectionRepository
    scheduling_budget: SchedulingBudgetProjectionRepository
    scheduling_policy: SchedulingPolicyProjectionRepository
    rulebook_revision: RulebookRevisionProjectionRepository
    rulebook_compile_result: RulebookCompileResultProjectionRepository
    execution_plan: ExecutionPlanProjectionRepository
    execution_wave: ExecutionWaveProjectionRepository
