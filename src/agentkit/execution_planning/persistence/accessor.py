"""PlanningProjectionAccessor: the single BC-9-hosted planning write boundary.

This is the BC14/BC9 pendant to the FK-69 ``ProjectionAccessor``. It is the ONLY
write boundary for the ten planning schema families (FK-70 §70.10.2). It follows
the SAME BC-9 DI pattern as the FK-69 accessor (typed kind enum, typed record
union, fail-closed type mismatch, injected repository bundle) but is
OWNER-DISTINCT: it does not touch, widen or reuse the FK-69 ``ProjectionKind`` /
``ProjectionRecord`` / ``ProjectionRepositories`` contract (which stays pinned to
its seven read-models). The conceptual ``Telemetry.write_projection`` name from
FK-70 §70.10.2 is realized HERE, for planning.

FIX THE MODEL: all planning writes flow through ``write_projection``; there is no
direct state_backend repo write for planning anymore (the legacy
``dependency_edge`` write is migrated onto this path via a planning-backed
``StoryDependencyRepository``).

Sources:
- FK-70 §70.10.2 -- single planning write path, schema owner BC14, DB owner BC9
- FK-70 §70.11 #8 -- idempotency / revision binding
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from agentkit.execution_planning.persistence.errors import (
    PlanningProjectionDeleteNotSupportedError,
    PlanningProjectionRecordTypeMismatchError,
    PlanningSchemaKindUnknownError,
)
from agentkit.execution_planning.persistence.records import (
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
    planning_kind_to_record_type,
)
from agentkit.execution_planning.persistence.schema_kind import PlanningSchemaKind

if TYPE_CHECKING:
    from agentkit.execution_planning.persistence.filter import (
        DependencyEdgeDeleteKey,
        PlanningProjectionFilter,
    )
    from agentkit.execution_planning.persistence.records import PlanningProjectionRecord
    from agentkit.execution_planning.persistence.repositories import (
        PlanningProjectionRepositories,
    )

__all__ = ["PlanningProjectionAccessor"]


class PlanningProjectionAccessor:
    """DB-owner-distinct write/read boundary for the ten planning families.

    Pendant to FK-69 ``ProjectionAccessor`` for BC14 planning. Dependency
    injection via ``PlanningProjectionRepositories``; the accessor imports no
    concrete repository implementation (BC-9 write-boundary rule).

    Args:
        repositories: Bundle of all ten planning repository adapters.
    """

    def __init__(self, repositories: PlanningProjectionRepositories) -> None:
        self._repos = repositories

    def write_projection(
        self,
        schema_kind: PlanningSchemaKind,
        record: PlanningProjectionRecord,
    ) -> None:
        """Persist one planning record via the owning repository adapter.

        FAIL-CLOSED: the record type must match ``schema_kind`` (pendant to
        ``ProjectionRecordTypeMismatchError``); an unmapped kind raises
        ``PlanningSchemaKindUnknownError``.

        Args:
            schema_kind: The planning schema family.
            record: The record to persist; type must match ``schema_kind``.

        Raises:
            PlanningProjectionRecordTypeMismatchError: On a record/kind mismatch.
            PlanningSchemaKindUnknownError: On an unmapped planning kind.
        """
        expected_type = planning_kind_to_record_type().get(schema_kind)
        if expected_type is None:
            raise PlanningSchemaKindUnknownError(kind=schema_kind)
        if not isinstance(record, expected_type):
            raise PlanningProjectionRecordTypeMismatchError(
                kind=schema_kind,
                expected=expected_type,
                received=type(record),
            )

        if schema_kind is PlanningSchemaKind.PLANNED_STORY:
            assert isinstance(record, PlannedStoryRecord)
            self._repos.planned_story.write(record)
        elif schema_kind is PlanningSchemaKind.DEPENDENCY_EDGE:
            assert isinstance(record, DependencyEdgeRecord)
            self._repos.dependency_edge.write(record)
        elif schema_kind is PlanningSchemaKind.BLOCKING_CONDITION:
            assert isinstance(record, BlockingConditionRecord)
            self._repos.blocking_condition.write(record)
        elif schema_kind is PlanningSchemaKind.GATE:
            assert isinstance(record, GateRecord)
            self._repos.gate.write(record)
        elif schema_kind is PlanningSchemaKind.SCHEDULING_BUDGET:
            assert isinstance(record, SchedulingBudgetRecord)
            self._repos.scheduling_budget.write(record)
        elif schema_kind is PlanningSchemaKind.SCHEDULING_POLICY:
            assert isinstance(record, SchedulingPolicyRecord)
            self._repos.scheduling_policy.write(record)
        elif schema_kind is PlanningSchemaKind.RULEBOOK_REVISION:
            assert isinstance(record, RulebookRevisionRecord)
            self._repos.rulebook_revision.write(record)
        elif schema_kind is PlanningSchemaKind.RULEBOOK_COMPILE_RESULT:
            assert isinstance(record, RulebookCompileResultRecord)
            self._repos.rulebook_compile_result.write(record)
        elif schema_kind is PlanningSchemaKind.EXECUTION_PLAN:
            assert isinstance(record, ExecutionPlanRecord)
            self._repos.execution_plan.write(record)
        elif schema_kind is PlanningSchemaKind.EXECUTION_WAVE:
            assert isinstance(record, ExecutionWaveRecord)
            self._repos.execution_wave.write(record)
        else:  # pragma: no cover - exhaustively covered above
            raise PlanningSchemaKindUnknownError(kind=schema_kind)

    def delete_projection(
        self,
        schema_kind: PlanningSchemaKind,
        key: DependencyEdgeDeleteKey,
    ) -> int:
        """Delete one planning record via the owning repository adapter.

        This is the delete leg of the SINGLE planning write boundary (FK-70
        §70.10.2): ALL dependency-edge mutations -- add AND remove -- flow
        through this accessor, never directly through a concrete repository
        adapter. Only families whose adapter exposes a delete operation are
        deletable; an unsupported family fails closed.

        Args:
            schema_kind: The planning schema family (currently only
                ``DEPENDENCY_EDGE`` supports delete).
            key: The composite delete key for the record to remove.

        Returns:
            The number of rows removed (0 if no matching record).

        Raises:
            PlanningProjectionDeleteNotSupportedError: For a family without
                delete semantics.
        """
        if schema_kind is PlanningSchemaKind.DEPENDENCY_EDGE:
            return self._repos.dependency_edge.delete(
                project_key=key.project_key,
                story_id=key.story_id,
                depends_on_story_id=key.depends_on_story_id,
                kind=key.kind,
            )
        raise PlanningProjectionDeleteNotSupportedError(kind=schema_kind)

    def read_projection(
        self,
        schema_kind: PlanningSchemaKind,
        filter: PlanningProjectionFilter,  # noqa: A002
    ) -> list[PlanningProjectionRecord]:
        """Read planning records for one schema family, mandant-scoped.

        Args:
            schema_kind: The planning schema family.
            filter: Read filter (``project_key`` mandatory for isolation).

        Returns:
            The matching records (possibly empty).

        Raises:
            PlanningSchemaKindUnknownError: On an unmapped planning kind.
        """
        if schema_kind is PlanningSchemaKind.PLANNED_STORY:
            return list(self._repos.planned_story.read(filter))
        if schema_kind is PlanningSchemaKind.DEPENDENCY_EDGE:
            return list(self._repos.dependency_edge.read(filter))
        if schema_kind is PlanningSchemaKind.BLOCKING_CONDITION:
            return list(self._repos.blocking_condition.read(filter))
        if schema_kind is PlanningSchemaKind.GATE:
            return list(self._repos.gate.read(filter))
        if schema_kind is PlanningSchemaKind.SCHEDULING_BUDGET:
            return list(self._repos.scheduling_budget.read(filter))
        if schema_kind is PlanningSchemaKind.SCHEDULING_POLICY:
            return list(self._repos.scheduling_policy.read(filter))
        if schema_kind is PlanningSchemaKind.RULEBOOK_REVISION:
            return list(self._repos.rulebook_revision.read(filter))
        if schema_kind is PlanningSchemaKind.RULEBOOK_COMPILE_RESULT:
            return list(self._repos.rulebook_compile_result.read(filter))
        if schema_kind is PlanningSchemaKind.EXECUTION_PLAN:
            return list(self._repos.execution_plan.read(filter))
        if schema_kind is PlanningSchemaKind.EXECUTION_WAVE:
            return list(self._repos.execution_wave.read(filter))
        raise PlanningSchemaKindUnknownError(kind=schema_kind)  # pragma: no cover
