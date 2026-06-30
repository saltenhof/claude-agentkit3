"""Published read port for the Story-BC central story queries (FK-07 §7.6).

This module defines :class:`StoryReadPort`, the consumer-owned read port for the
Story-BC's central list/detail surface (StoryContext, PhaseState, FlowExecution,
StoryMetrics and the global ``execution_events`` stream). It lives in the
``agentkit.backend.story`` package (the BC), so the Story-BC depends ONLY on this
Protocol and never imports the ``agentkit.backend.state_backend.store`` loader
facade — the FK-07 §7.6 architecture-conformance boundary ("Fachkomponenten
haengen nicht an ``state_backend.store`` als generischer Mega-Fassade").

The productive implementation lives in
``agentkit.backend.state_backend.store.story_read_repository`` and is wired in the
composition root, mirroring the proven ``FactRepository`` pattern
(``kpi_analytics.fact_store.repository`` Protocol + ``state_backend.store``
adapter).

Fail-closed contract: a read against a missing table/state propagates the
underlying backend error or returns ``None``/an empty list exactly as the
state-backend loaders define it — a missing backend is NEVER masked by a silent
empty-OK result.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from agentkit.backend.closure.post_merge_finalization.records import StoryMetricsRecord
    from agentkit.backend.phase_state_store.models import FlowExecution
    from agentkit.backend.pipeline_engine.phase_executor import PhaseState
    from agentkit.backend.story_context_manager.models import StoryContext
    from agentkit.backend.telemetry.contract.records import ExecutionEventRecord

__all__ = ["StoryReadPort"]


@runtime_checkable
class StoryReadPort(Protocol):
    """Read port for the Story-BC central list and detail endpoints.

    The single sanctioned story-read edge: every global story read (story
    context, phase state, flow execution, latest story metrics and recent
    execution events) flows through this published Protocol. Implementations
    are the only place that knows the ``state_backend.store`` story loaders.
    """

    def list_story_contexts(self, project_key: str) -> list[StoryContext]:
        """Return all story contexts of ``project_key`` (empty list when none)."""
        ...

    def load_story_context(
        self, project_key: str, story_id: str
    ) -> StoryContext | None:
        """Return the story context for ``(project_key, story_id)`` or ``None``."""
        ...

    def load_phase_state(self, story_id: str) -> PhaseState | None:
        """Return the single current runtime phase state of ``story_id`` or ``None``."""
        ...

    def load_flow_execution(
        self, project_key: str, story_id: str
    ) -> FlowExecution | None:
        """Return the current/last flow execution of the story, or ``None``."""
        ...

    def load_latest_story_metrics(
        self, project_key: str, story_id: str
    ) -> StoryMetricsRecord | None:
        """Return the latest closure story-metrics record, or ``None``."""
        ...

    def load_recent_execution_events(
        self,
        project_key: str,
        story_id: str,
        run_id: str,
        limit: int,
    ) -> list[ExecutionEventRecord]:
        """Return up to ``limit`` recent execution events for the run scope."""
        ...
