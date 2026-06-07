"""Runtime ports the TelemetryContract depends on (telemetry-internal).

FK-68 §68.4 evaluates telemetry *proofs* over the canonical ``execution_events``
stream (NOT an FK-69 read-model). The ``TelemetryContract`` therefore depends on
a run-scoped execution-event reader, injected as a Protocol so the contract
module imports no state-backend implementation (AC8 import boundary).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from agentkit.telemetry.contract.records import ExecutionEventRecord


@runtime_checkable
class ExecutionEventReader(Protocol):
    """Run-scoped read boundary over the canonical ``execution_events`` stream.

    The canonical adapter wraps ``state_backend.store.load_execution_events``
    (see :class:`StateBackendExecutionEventReader`). Injected as a Protocol so
    ``telemetry.contract`` stays free of facade imports.
    """

    def read_run_events(self, run_id: str) -> list[ExecutionEventRecord]:
        """Return all execution events for ``run_id``, ordered by occurrence.

        Args:
            run_id: The run whose events to load.

        Returns:
            All ``ExecutionEventRecord``s for that run (possibly empty).
        """
        ...


__all__ = ["ExecutionEventReader"]
