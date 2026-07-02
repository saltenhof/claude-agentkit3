"""Ports for worker-health gate operations (AG3-129).

The PostToolUse update and the PreToolUse intervention gate need only to
*load* and *save* one worker-health state. Segregating that narrow surface from
the full 4-method reader repository lets the hook use a REST-backed store
(FK-10 §10.1.0 I1) that mediates exactly those two canonical operations without
carrying unused reader methods.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from agentkit.backend.implementation.worker_health.models import AgentHealthState


@runtime_checkable
class WorkerHealthGateStore(Protocol):
    """Load/save port for the worker-health gate (subset of the repository)."""

    def load(
        self, *, story_id: str, worker_id: str
    ) -> AgentHealthState | None:
        """Load the health state for one ``(story_id, worker_id)`` scope."""
        ...

    def save(self, state: AgentHealthState) -> None:
        """Persist the health state (upsert on the scope key)."""
        ...


__all__ = ["WorkerHealthGateStore"]
