"""Shared no-op ``StoryReadPort`` stub for tests (AG3-126).

Used by test doubles that subclass ``agentkit.backend.story.service.StoryService``
and override its public read methods: the service now requires a
``StoryReadPort`` (no default), so these fakes pass this trivial stub to
``super().__init__`` even though they never consult it.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from agentkit.backend.closure.post_merge_finalization.records import StoryMetricsRecord
    from agentkit.backend.phase_state_store.models import FlowExecution
    from agentkit.backend.pipeline_engine.phase_executor import PhaseState
    from agentkit.backend.story_context_manager.models import StoryContext
    from agentkit.backend.telemetry.contract.records import ExecutionEventRecord


class StubStoryReadPort:
    """Empty ``StoryReadPort`` implementation (no state backend, no rows)."""

    def list_story_contexts(self, project_key: str) -> list[StoryContext]:
        return []

    def load_story_context(
        self, project_key: str, story_id: str
    ) -> StoryContext | None:
        return None

    def load_phase_state(self, story_id: str) -> PhaseState | None:
        return None

    def load_flow_execution(
        self, project_key: str, story_id: str
    ) -> FlowExecution | None:
        return None

    def load_latest_story_metrics(
        self, project_key: str, story_id: str
    ) -> StoryMetricsRecord | None:
        return None

    def load_recent_execution_events(
        self, project_key: str, story_id: str, run_id: str, limit: int
    ) -> list[ExecutionEventRecord]:
        return []
