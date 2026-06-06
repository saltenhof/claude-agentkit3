"""Closure metrics mode-tag tests (AG3-018 DELTA-D / AC6, FK-24 §24.3.298).

The closure ``StoryMetricsRecord`` is tagged with the standard/fast ``mode`` axis
(``StoryContext.mode``) so fast runs are separately aggregable. A fast story's
record carries ``mode="fast"``; a standard story carries ``mode="standard"``.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest

from agentkit.closure.post_merge_finalization.metrics import (
    build_story_metrics_record,
)
from agentkit.phase_state_store.models import FlowExecution
from agentkit.state_backend.store import (
    append_execution_event,
    save_flow_execution,
)
from agentkit.story_context_manager.models import StoryContext
from agentkit.story_context_manager.story_model import WireStoryMode
from agentkit.story_context_manager.types import StoryMode, StoryType
from agentkit.telemetry.contract.records import ExecutionEventRecord
from agentkit.telemetry.events import EventType

if TYPE_CHECKING:
    from collections.abc import Generator
    from pathlib import Path


@pytest.fixture(autouse=True)
def _sqlite_backend(monkeypatch: pytest.MonkeyPatch) -> Generator[None, None, None]:
    from agentkit.state_backend.store import reset_backend_cache_for_tests

    monkeypatch.setenv("AGENTKIT_STATE_BACKEND", "sqlite")
    monkeypatch.setenv("AGENTKIT_ALLOW_SQLITE", "1")
    monkeypatch.delenv("AGENTKIT_STATE_DATABASE_URL", raising=False)
    reset_backend_cache_for_tests()
    yield
    reset_backend_cache_for_tests()


def _prepare(tmp_path: Path, story_id: str) -> Path:
    s_dir = tmp_path / "stories" / story_id
    s_dir.mkdir(parents=True)
    save_flow_execution(
        s_dir,
        FlowExecution(
            project_key="proj",
            story_id=story_id,
            run_id=f"run-{story_id.lower()}",
            flow_id="implementation",
            level="story",
            owner="pipeline_engine",
            status="COMPLETED",
            started_at=datetime(2026, 1, 1, 10, 0, 0, tzinfo=UTC),
        ),
    )
    append_execution_event(
        s_dir,
        ExecutionEventRecord(
            project_key="proj",
            story_id=story_id,
            run_id=f"run-{story_id.lower()}",
            event_id=f"evt-start-{story_id.lower()}",
            event_type=EventType.AGENT_START.value,
            occurred_at=datetime(2026, 1, 1, 9, 45, 0, tzinfo=UTC),
            source_component="test",
            severity="info",
            payload={},
        ),
    )
    return s_dir


def _ctx(story_id: str, mode: WireStoryMode) -> StoryContext:
    return StoryContext(
        project_key="proj",
        story_id=story_id,
        story_type=StoryType.IMPLEMENTATION,
        execution_route=StoryMode.EXECUTION,
        mode=mode,
    )


def test_fast_story_metrics_record_tagged_fast(tmp_path: Path) -> None:
    s_dir = _prepare(tmp_path, "AG3-100")
    record = build_story_metrics_record(
        s_dir,
        _ctx("AG3-100", WireStoryMode.FAST),
        completed_at=datetime(2026, 1, 1, 11, 0, 0, tzinfo=UTC),
        final_status="completed",
    )
    assert record.mode == "fast"
    assert record.to_metrics_payload()["mode"] == "fast"


def test_standard_story_metrics_record_tagged_standard(tmp_path: Path) -> None:
    s_dir = _prepare(tmp_path, "AG3-101")
    record = build_story_metrics_record(
        s_dir,
        _ctx("AG3-101", WireStoryMode.STANDARD),
        completed_at=datetime(2026, 1, 1, 11, 0, 0, tzinfo=UTC),
        final_status="completed",
    )
    assert record.mode == "standard"
    assert record.to_metrics_payload()["mode"] == "standard"
