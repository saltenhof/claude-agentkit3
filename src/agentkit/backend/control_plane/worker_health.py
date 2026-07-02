"""Control-plane service for canonical worker-health read/write.

AG3-129 (FK-10 §10.1.0 I1 / §10.3.2): the Dev-side hook is a REST requester;
the canonical worker-health state (FK-30 §30.10) is read and written ONLY here,
inside the core, through the owner ``WorkerHealthStateRepository``. Worker-health
is a fail-closed gate operation -- a persistence fault surfaces as an error, not
a silent empty result.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from agentkit.backend.control_plane.models import (
    WorkerHealthSaveAccepted,
    WorkerHealthStateResponse,
)

if TYPE_CHECKING:
    from collections.abc import Callable

    from agentkit.backend.state_backend.store.worker_health_repository import (
        WorkerHealthStateRepository,
    )


def _default_repository() -> WorkerHealthStateRepository:
    from agentkit.backend.state_backend.store.worker_health_repository import (
        StateBackendWorkerHealthRepository,
    )

    return StateBackendWorkerHealthRepository()


class ControlPlaneWorkerHealthService:
    """Read and write canonical worker-health state from the control plane."""

    def __init__(
        self,
        *,
        repository_factory: Callable[
            [], WorkerHealthStateRepository
        ] = _default_repository,
    ) -> None:
        """Bind the service to a worker-health repository factory.

        Args:
            repository_factory: Builds the persistence port per request (the
                default wires the canonical SQLite/Postgres adapter).
        """
        self._repository_factory = repository_factory

    def load(self, *, story_id: str, worker_id: str) -> WorkerHealthStateResponse:
        """Read the canonical worker-health state for one scope.

        Args:
            story_id: The story the health state belongs to.
            worker_id: The worker whose health state to read.

        Returns:
            The read result (``state`` is ``None`` when no row exists).
        """
        state = self._repository_factory().load(
            story_id=story_id, worker_id=worker_id
        )
        if state is None:
            return WorkerHealthStateResponse(state=None)
        return WorkerHealthStateResponse(state=state.model_dump(mode="json"))

    def save(self, payload: object) -> WorkerHealthSaveAccepted:
        """Validate and persist canonical worker-health state.

        Args:
            payload: The ``AgentHealthState`` wire object.

        Returns:
            The accepted result.
        """
        from agentkit.backend.implementation.worker_health.models import (
            AgentHealthState,
        )

        state = AgentHealthState.model_validate(payload)
        self._repository_factory().save(state)
        return WorkerHealthSaveAccepted(
            story_id=state.story_id, worker_id=state.worker_id
        )
