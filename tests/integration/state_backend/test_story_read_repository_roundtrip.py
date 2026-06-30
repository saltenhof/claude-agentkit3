"""AG3-126 AC2: StateBackendStoryReadRepository over a REAL SQLite round-trip.

Persists a story via the canonical global write owners into a real SQLite store,
then reads it back through the productive ``StoryReadPort`` adapter — the
strongest "really persisted" evidence for the read edge. FlowExecution global
reads are Postgres-only at the backend (no ``load_flow_execution_global_row`` on
SQLite); they are covered by ``tests/unit/state_backend/test_story_read_repository``.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest

from agentkit.backend.closure.post_merge_finalization.records import StoryMetricsRecord
from agentkit.backend.pipeline_engine.phase_executor import PhaseStatus
from agentkit.backend.state_backend.config import (
    ALLOW_SQLITE_ENV,
    STATE_BACKEND_ENV,
    STORE_DIR_ENV,
)
from agentkit.backend.state_backend.store import facade
from agentkit.backend.state_backend.store.story_read_repository import (
    StateBackendStoryReadRepository,
)
from agentkit.backend.story.repository import StoryReadPort
from agentkit.backend.story_context_manager.models import StoryContext
from agentkit.backend.story_context_manager.types import (
    ImplementationContract,
    StoryMode,
    StoryType,
)
from agentkit.backend.telemetry.contract.records import ExecutionEventRecord

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

from tests.phase_state_factory import make_phase_state

_PROJECT = "tenant-a"
_STORY = "AG3-126"
_RUN = "run-126"
_NOW = datetime(2026, 6, 12, 10, 0, tzinfo=UTC)


@pytest.fixture
def store_dir(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Iterator[Path]:
    monkeypatch.setenv(STATE_BACKEND_ENV, "sqlite")
    monkeypatch.setenv(ALLOW_SQLITE_ENV, "1")
    monkeypatch.setenv(STORE_DIR_ENV, str(tmp_path))
    # The non-event global reads resolve store_dir=None to CWD; chdir so the
    # adapter (which passes no store_dir, mirroring production) hits the seeded DB.
    monkeypatch.chdir(tmp_path)
    facade.reset_backend_cache_for_tests()
    yield tmp_path
    facade.reset_backend_cache_for_tests()


def _seed(store_dir: Path) -> None:
    facade.save_story_context_global(
        store_dir,
        StoryContext(
            project_key=_PROJECT,
            story_id=_STORY,
            story_type=StoryType.IMPLEMENTATION,
            execution_route=StoryMode.EXECUTION,
            implementation_contract=ImplementationContract.STANDARD,
            title="Round-trip story",
            labels=["size:medium"],
            participating_repos=["app"],
            created_at=_NOW,
        ),
    )
    facade.save_phase_state(
        store_dir,
        make_phase_state(
            story_id=_STORY,
            phase="implementation",
            status=PhaseStatus.IN_PROGRESS,
        ),
    )
    facade.upsert_story_metrics(
        store_dir,
        StoryMetricsRecord(
            project_key=_PROJECT,
            story_id=_STORY,
            run_id=_RUN,
            story_type="implementation",
            story_size="medium",
            mode="standard",
            processing_time_min=18.5,
            qa_rounds=2,
            increments=3,
            final_status="DONE",
            completed_at="2026-06-12T11:30:00+00:00",
        ),
    )
    facade.append_execution_event_global(
        ExecutionEventRecord(
            project_key=_PROJECT,
            story_id=_STORY,
            run_id=_RUN,
            event_id="evt-001",
            event_type="node_result",
            occurred_at=_NOW,
            source_component="pipeline-engine",
            severity="info",
            phase="implementation",
            flow_id="implementation",
            node_id="node-1",
            payload={"order": 1},
        ),
    )


def test_adapter_reads_persisted_story_on_sqlite(store_dir: Path) -> None:
    _seed(store_dir)
    adapter = StateBackendStoryReadRepository()

    # Structural runtime_checkable conformance (additionally, not as a replacement).
    assert isinstance(adapter, StoryReadPort)

    contexts = adapter.list_story_contexts(_PROJECT)
    assert [c.story_id for c in contexts] == [_STORY]

    context = adapter.load_story_context(_PROJECT, _STORY)
    assert context is not None
    assert context.title == "Round-trip story"

    phase_state = adapter.load_phase_state(_STORY)
    assert phase_state is not None
    assert phase_state.phase == "implementation"
    assert phase_state.status is PhaseStatus.IN_PROGRESS

    metrics = adapter.load_latest_story_metrics(_PROJECT, _STORY)
    assert metrics is not None
    assert metrics.final_status == "DONE"
    assert metrics.run_id == _RUN

    events = adapter.load_recent_execution_events(_PROJECT, _STORY, _RUN, 25)
    assert [e.event_id for e in events] == ["evt-001"]
    assert events[0].payload == {"order": 1}


def test_adapter_returns_empty_and_none_for_absent_story(store_dir: Path) -> None:
    # AC5 fail-closed (legit absence, not a masked backend failure): a fresh
    # store yields an empty list / None, never an error.
    adapter = StateBackendStoryReadRepository()
    assert adapter.list_story_contexts(_PROJECT) == []
    assert adapter.load_story_context(_PROJECT, _STORY) is None
    assert adapter.load_phase_state(_STORY) is None
    assert adapter.load_latest_story_metrics(_PROJECT, _STORY) is None
