"""Control-plane service for canonical guard-invocation counter mutations.

AG3-129 (FK-10 §10.1.0 I1/I3): the Dev-side hook is a REST requester; the
canonical ``guard_invocation_counters`` scratchpad (FK-61 §61.4.3) is written
ONLY here, inside the core. The core process may open its database directly (I1
constrains the Dev side, not the backend); the hook never does.

Idempotency (FK-91 §91.1a Rule 5): the ``record`` mutation carries an ``op_id``.
The counter increment AND the ``op_id`` idempotency key are written in ONE
transaction (``StateBackendGuardCounterRepository.record_invocation_idempotent``),
so a replayed ``op_id`` never double-counts and a crash between the two writes
rolls both back (no lost increment, no orphan count). A replay with a DIFFERENT
body hash is a fail-closed ``idempotency_mismatch`` conflict. The ``housekeeping``
sweep is naturally idempotent (it drains stale rows; a replay drains nothing), so
it needs no ``op_id`` dedup.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING, Protocol

from agentkit.backend.control_plane.models import (
    GuardCounterMutationAccepted,
    GuardCounterMutationRequest,
)
from agentkit.backend.kpi_analytics.fact_store.repository import GuardCounterRepository

if TYPE_CHECKING:
    from collections.abc import Callable

    from agentkit.backend.state_backend.store.guard_counter_repository import (
        GuardCounterRecordOutcome,
    )


class AtomicGuardCounterStore(GuardCounterRepository, Protocol):
    """A guard-counter store that also records exactly-once per ``op_id``.

    Extends the counter ``GuardCounterRepository`` port with the atomic
    counter-increment + idempotency-key write (one transaction).
    """

    def record_invocation_idempotent(
        self,
        *,
        op_id: str,
        body_hash: str,
        result_payload: dict[str, object],
        project_key: str,
        story_id: str,
        guard_key: str,
        week_start: str,
        blocked: bool,
        updated_at: datetime,
        created_at: datetime,
    ) -> GuardCounterRecordOutcome:
        """Record one invocation exactly once per ``op_id`` in one transaction."""
        ...


def _default_store() -> AtomicGuardCounterStore:
    from agentkit.backend.state_backend.store.guard_counter_repository import (
        StateBackendGuardCounterRepository,
    )

    return StateBackendGuardCounterRepository()


class ControlPlaneGuardCounterService:
    """Apply guard-counter mutations from the control plane (FK-61 §61.4.3)."""

    def __init__(
        self,
        *,
        store_factory: Callable[[], AtomicGuardCounterStore] = _default_store,
    ) -> None:
        """Bind the service to an atomic guard-counter store factory.

        Args:
            store_factory: Builds the counter+idempotency store per request (the
                default wires the canonical SQLite/Postgres adapter).
        """
        self._store_factory = store_factory

    def apply(
        self, request: GuardCounterMutationRequest
    ) -> GuardCounterMutationAccepted:
        """Apply one guard-counter mutation.

        Args:
            request: The typed guard-counter mutation.

        Returns:
            The accepted result. A ``record`` is exactly-once per ``op_id``; a
            replay returns the ORIGINAL result without re-counting.

        Raises:
            IdempotencyMismatchError: When ``op_id`` was reused with a different
                request body (FK-91 §91.1a Rule 5).
        """
        if request.operation == "housekeeping":
            return self._apply_housekeeping(request)
        return self._apply_record(request)

    def _apply_record(
        self, request: GuardCounterMutationRequest
    ) -> GuardCounterMutationAccepted:
        from agentkit.backend.kpi_analytics.fact_store.guard_counter import (
            week_start_for,
        )
        from agentkit.backend.state_backend.store.inflight_idempotency_guard import (
            compute_body_hash,
        )

        project_key = request.project_key
        story_id = request.story_id
        guard_key = request.guard_key
        blocked = request.blocked
        # The request validator guarantees these are present for ``record``;
        # narrow defensively so a malformed internal call fails closed.
        if (
            project_key is None
            or story_id is None
            or guard_key is None
            or blocked is None
        ):
            raise ValueError(
                "guard-counter record requires project_key, story_id, "
                "guard_key and blocked",
            )

        # Resolve idempotency FIRST (FUND 2): the atomic record claims the op_id,
        # and ONLY on a genuinely new claim drains older-week buckets + counts --
        # all in one transaction. A replay / mismatch has ZERO counter side effect
        # (no drain, no count); the drain never runs before the idempotency
        # resolution. The stored placeholder response carries ``drained: 0`` and is
        # overwritten with the real drained count on a successful claim.
        placeholder = GuardCounterMutationAccepted(
            operation="record", drained=0
        ).model_dump(mode="json")
        outcome = self._store_factory().record_invocation_idempotent(
            op_id=request.op_id,
            body_hash=compute_body_hash(request.model_dump(mode="json")),
            result_payload=placeholder,
            project_key=project_key,
            story_id=story_id,
            guard_key=guard_key,
            week_start=week_start_for(request.occurred_at),
            blocked=blocked,
            updated_at=request.occurred_at,
            created_at=datetime.now(UTC),
        )
        if outcome.status == "mismatch":
            from agentkit.backend.story_context_manager.errors import (
                IdempotencyMismatchError,
            )

            raise IdempotencyMismatchError(
                f"op_id {request.op_id!r} was previously used with a different "
                "request body; use a new op_id for a different mutation",
                detail={"op_id": request.op_id, "conflict": "body_hash_mismatch"},
            )
        if outcome.status == "replayed" and outcome.cached_result is not None:
            return GuardCounterMutationAccepted.model_validate(outcome.cached_result)
        return GuardCounterMutationAccepted(
            operation="record", drained=outcome.drained
        )

    def _apply_housekeeping(
        self, request: GuardCounterMutationRequest
    ) -> GuardCounterMutationAccepted:
        from agentkit.backend.kpi_analytics import GuardCounterService

        drained = GuardCounterService(self._store_factory()).flush_housekeeping(
            now=request.occurred_at
        )
        return GuardCounterMutationAccepted(
            operation="housekeeping", drained=len(drained)
        )
