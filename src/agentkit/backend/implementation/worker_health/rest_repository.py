"""REST-backed worker-health gate store for the hook process (AG3-129).

FK-10 §10.1.0 I1 / §10.3.2: the Dev-side hook reads and writes canonical
worker-health state via the core's REST API, never by opening the database
directly. Worker-health is a fail-closed gate operation (FK-30 §30.10): a
core-unreachable / rejected call propagates as an exception so the runner edge
can translate it into a fail-closed BLOCK -- there is NO silent empty result and
NO direct-DB fallback.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from agentkit.backend.implementation.worker_health.models import AgentHealthState

if TYPE_CHECKING:
    from agentkit.harness_client.projectedge.governance_client import (
        GovernanceEdgeClient,
    )


class RestWorkerHealthRepository:
    """``WorkerHealthGateStore`` implemented over the governance REST client."""

    def __init__(self, client: GovernanceEdgeClient) -> None:
        """Bind the store to a governance edge client.

        Args:
            client: The hook-side REST client (single shared transport).
        """
        self._client = client

    def load(
        self, *, story_id: str, worker_id: str
    ) -> AgentHealthState | None:
        """Read the canonical worker-health state via REST.

        Args:
            story_id: The story the health state belongs to.
            worker_id: The worker whose health state to read.

        Returns:
            The reconstructed state, or ``None`` when the core reports no row.

        Raises:
            Exception: On a core-unreachable / rejected read (fail-closed).
        """
        response = self._client.load_worker_health(
            story_id=story_id, worker_id=worker_id
        )
        if response.state is None:
            return None
        return AgentHealthState.model_validate(response.state)

    def save(self, state: AgentHealthState) -> None:
        """Write the canonical worker-health state via REST.

        Args:
            state: The health state to persist.

        Raises:
            Exception: On a core-unreachable / rejected write (fail-closed).
        """
        self._client.save_worker_health(state.model_dump(mode="json"))


__all__ = ["RestWorkerHealthRepository"]
