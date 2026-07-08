"""StateBackendStoryReadRepository — productive StoryReadPort adapter (AG3-126).

Productive implementation of the consumer-owned ``StoryReadPort`` Protocol
(``agentkit.backend.story.repository``), backing the Story-BC central list/detail
read surface (FK-07 §7.6/§7.7.5). Mirrors ``fact_repository``:

- This adapter is the ONLY place that knows the global story-read loaders
  (``load_*_global``); the Story-BC (``story.service`` / ``story.repository``)
  depends solely on the Protocol and never imports these loaders.
- Wired in the composition root (``build_story_read_service`` and the
  story-reset / control-plane / read-model wirings); ``story`` never imports
  this module.
- Fail-closed (FK-07 §7.7.5 / story §2.1.5): each read delegates to the
  state-backend loader unchanged — a missing table propagates the underlying
  backend error, a legitimately-absent row returns ``None``/an empty list. No
  silent empty-OK masks a missing backend here.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from agentkit.backend.state_backend.pipeline_runtime_store import (
    load_flow_execution_global,
    load_phase_state_global,
)
from agentkit.backend.state_backend.story_lifecycle_store import (
    load_story_context_global,
    load_story_contexts_global,
)
from agentkit.backend.state_backend.telemetry_event_store import (
    load_execution_events_global,
    load_latest_story_metrics_global,
)

if TYPE_CHECKING:
    from pathlib import Path

    from agentkit.backend.closure.post_merge_finalization.records import StoryMetricsRecord
    from agentkit.backend.phase_state_store.models import FlowExecution
    from agentkit.backend.pipeline_engine.phase_executor import PhaseState
    from agentkit.backend.story_context_manager.models import StoryContext
    from agentkit.backend.telemetry.contract.records import ExecutionEventRecord


@dataclass(frozen=True)
class StateBackendStoryReadRepository:
    """State-backend implementation of ``StoryReadPort`` (AG3-126).

    Each method delegates 1:1 to the corresponding global story-read loader,
    preserving the established fail-closed and ``None``/empty-list contract.

    Args:
        store_dir: Store root threaded into the store-scoped loaders (story
            context, phase state, latest story metrics). ``None`` defers
            resolution to the loader/backend default (SQLite ``Path.cwd()``).
            The composition root injects the same ``store_dir`` it threads into
            the sibling read repositories so every project-scoped read resolves
            against one store root.
    """

    store_dir: Path | None = None

    def list_story_contexts(self, project_key: str) -> list[StoryContext]:
        """Return all story contexts of ``project_key`` (empty list when none)."""
        return load_story_contexts_global(project_key, self.store_dir)

    def load_story_context(
        self, project_key: str, story_id: str
    ) -> StoryContext | None:
        """Return the story context for ``(project_key, story_id)`` or ``None``."""
        return load_story_context_global(project_key, story_id, self.store_dir)

    def load_phase_state(self, story_id: str) -> PhaseState | None:
        """Return the single current runtime phase state of ``story_id`` or ``None``."""
        return load_phase_state_global(story_id, self.store_dir)

    def load_flow_execution(
        self, project_key: str, story_id: str
    ) -> FlowExecution | None:
        """Return the current/last flow execution of the story, or ``None``."""
        # Global-only loader: no store_dir parameter (inherently global read).
        return load_flow_execution_global(project_key, story_id)

    def load_latest_story_metrics(
        self, project_key: str, story_id: str
    ) -> StoryMetricsRecord | None:
        """Return the latest closure story-metrics record, or ``None``."""
        return load_latest_story_metrics_global(project_key, story_id, self.store_dir)

    def load_recent_execution_events(
        self,
        project_key: str,
        story_id: str,
        run_id: str,
        limit: int,
    ) -> list[ExecutionEventRecord]:
        """Return up to ``limit`` recent execution events for the run scope."""
        # Global-only loader: no store_dir parameter (inherently global read).
        return load_execution_events_global(
            project_key,
            story_id,
            run_id=run_id,
            limit=limit,
        )

    def query_execution_events(
        self,
        project_key: str,
        story_id: str,
        *,
        event_type: str | None = None,
    ) -> list[ExecutionEventRecord]:
        """Return execution events for a scope, optionally filtered by type.

        Global-only loader (no store_dir). Backs the AG3-129 server-mediated
        telemetry read for the hook's REST event emitter — the loader stays
        inside this explicit story-read surface (architecture-conformance AC004).
        """
        return load_execution_events_global(
            project_key,
            story_id,
            event_type=event_type,
        )


__all__ = ["StateBackendStoryReadRepository"]
