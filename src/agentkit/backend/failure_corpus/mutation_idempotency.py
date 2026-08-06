"""Failure-corpus ownership of the unified mutation claim contract."""

from __future__ import annotations

from contextlib import nullcontext
from typing import TYPE_CHECKING, Protocol

from agentkit.backend.state_backend.store.inflight_idempotency_guard import (
    IdempotencyRequest,
    InflightIdempotencyGuard,
    StateBackendInflightIdempotencyGuard,
    compute_body_hash,
    run_route_idempotent,
    state_backend_atomic_writer_mutation,
)

if TYPE_CHECKING:
    from collections.abc import Callable


class FailureCorpusMutationResponse(Protocol):
    """Minimal response shape persisted by the unified route guard."""

    @property
    def status_code(self) -> int:
        """HTTP status persisted with the replay body."""
        ...

    @property
    def body(self) -> bytes:
        """Serialized JSON body persisted for replay."""
        ...


_OPERATIONS = frozenset(
    {
        "add_incident",
        "review_pattern",
        "review_check",
        "effectiveness",
    },
)


class FailureCorpusMutationCoordinator:
    """Claim and finalize one failure-corpus mutation before/after dispatch."""

    def __init__(self, guard: InflightIdempotencyGuard | None = None) -> None:
        self._guard = guard

    def run[ResponseT: FailureCorpusMutationResponse](
        self,
        *,
        operation: str,
        op_id: str,
        project_key: str,
        target_id: str | None,
        request_body: dict[str, object],
        session_id: str,
        correlation_id: str,
        mutate: Callable[[], ResponseT],
        replay: Callable[[dict[str, object]], ResponseT],
        conflict: Callable[[str, str, dict[str, object]], ResponseT],
    ) -> ResponseT:
        """Run the owner mutation under the shared op-id/claim mechanism."""

        if operation not in _OPERATIONS:
            raise ValueError(f"unknown failure-corpus mutation operation: {operation!r}")
        hash_body = {**request_body, "project_key": project_key}
        if target_id is not None:
            hash_body["target_id"] = target_id
        request = IdempotencyRequest(
            op_id=op_id,
            operation_kind=f"failure_corpus_{operation}",
            body_hash=compute_body_hash(hash_body),
            project_key=project_key,
            session_id=session_id,
            correlation_id=correlation_id,
        )
        guard = self._guard or StateBackendInflightIdempotencyGuard()
        return run_route_idempotent(
            guard,
            request,
            mutate=mutate,
            replay=replay,
            conflict=conflict,
            mutation_scope=(
                state_backend_atomic_writer_mutation
                if isinstance(guard, StateBackendInflightIdempotencyGuard)
                else nullcontext
            ),
        )


__all__ = ["FailureCorpusMutationCoordinator", "FailureCorpusMutationResponse"]
