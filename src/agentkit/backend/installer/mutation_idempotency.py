"""Shared claim/replay coordinator for installer writer mutations."""

from __future__ import annotations

from contextlib import nullcontext
from typing import TYPE_CHECKING, Protocol, TypeVar

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


class _InstallerMutationResponse(Protocol):
    """Minimum response contract required by the shared idempotency owner."""

    @property
    def status_code(self) -> int: ...

    @property
    def body(self) -> bytes: ...


_T = TypeVar("_T", bound=_InstallerMutationResponse)


class InstallerMutationCoordinator:
    """Apply the unified claim/replay contract around one installer mutation."""

    def __init__(self, guard: InflightIdempotencyGuard) -> None:
        self._guard = guard

    def run(
        self,
        *,
        operation: str,
        op_id: str,
        project_key: str,
        request_body: dict[str, object],
        session_id: str,
        correlation_id: str,
        mutate: Callable[[], _T],
        replay: Callable[[dict[str, object]], _T],
        conflict: Callable[[str, str, dict[str, object]], _T],
    ) -> _T:
        """Claim, execute, and finalize one replayable installer mutation."""
        identity_body = {**request_body, "project_key": project_key}
        request = IdempotencyRequest(
            op_id=op_id,
            operation_kind=f"installer_{operation}",
            body_hash=compute_body_hash(identity_body),
            project_key=project_key,
            session_id=session_id,
            correlation_id=correlation_id,
        )
        return run_route_idempotent(
            self._guard,
            request,
            mutate=mutate,
            replay=replay,
            conflict=conflict,
            mutation_scope=(
                state_backend_atomic_writer_mutation
                if isinstance(self._guard, StateBackendInflightIdempotencyGuard)
                else nullcontext
            ),
        )


__all__ = ["InstallerMutationCoordinator"]
