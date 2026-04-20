"""Unit tests for canonical telemetry storage."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest

from agentkit.phase_state_store.models import FlowExecution
from agentkit.state_backend import save_flow_execution, save_story_context
from agentkit.state_backend.config import ALLOW_SQLITE_ENV, STATE_BACKEND_ENV
from agentkit.state_backend.store import reset_backend_cache_for_tests
from agentkit.story_context_manager.models import StoryContext
from agentkit.story_context_manager.types import StoryMode, StoryType
from agentkit.telemetry.emitters import EventEmitter
from agentkit.telemetry.events import Event, EventType
from agentkit.telemetry.storage import StateBackendEmitter

if TYPE_CHECKING:
    from pathlib import Path


@pytest.fixture(autouse=True)
def sqlite_backend_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(STATE_BACKEND_ENV, "sqlite")
    monkeypatch.setenv(ALLOW_SQLITE_ENV, "1")
    reset_backend_cache_for_tests()
    yield
    reset_backend_cache_for_tests()


def _story_dir(tmp_path: Path, story_id: str = "AG3-001") -> Path:
    story_dir = tmp_path / "stories" / story_id
    story_dir.mkdir(parents=True, exist_ok=True)
    return story_dir


class TestStateBackendEmitter:
    def test_emit_and_query_roundtrip(self, tmp_path: Path) -> None:
        story_dir = _story_dir(tmp_path)
        emitter = StateBackendEmitter(
            story_dir,
            default_project_key="demo-project",
            default_source_component="test-hook",
        )
        ts = datetime(2026, 1, 15, 10, 30, 0, tzinfo=UTC)

        emitter.emit(
            Event(
                story_id="AG3-001",
                event_type=EventType.FLOW_START,
                timestamp=ts,
                phase="setup",
                flow_id="implementation",
                node_id="setup",
                payload={"key": "value"},
                run_id="run-1",
            )
        )

        results = emitter.query("AG3-001")
        assert len(results) == 1
        event = results[0]
        assert event.story_id == "AG3-001"
        assert event.project_key == "demo-project"
        assert event.event_type == EventType.FLOW_START
        assert event.source_component == "test-hook"
        assert event.phase == "setup"
        assert event.flow_id == "implementation"
        assert event.node_id == "setup"
        assert event.payload == {"key": "value"}
        assert event.run_id == "run-1"
        assert event.event_id is not None

    def test_query_filters_by_event_type(self, tmp_path: Path) -> None:
        story_dir = _story_dir(tmp_path)
        emitter = StateBackendEmitter(
            story_dir,
            default_project_key="demo-project",
        )
        emitter.emit(
            Event(
                story_id="AG3-001",
                event_type=EventType.FLOW_START,
                run_id="run-1",
            )
        )
        emitter.emit(
            Event(
                story_id="AG3-001",
                event_type=EventType.FLOW_END,
                run_id="run-1",
            )
        )

        results = emitter.query("AG3-001", event_type=EventType.FLOW_END)
        assert len(results) == 1
        assert results[0].event_type == EventType.FLOW_END

    def test_query_filters_by_story_id(self, tmp_path: Path) -> None:
        emitter_one = StateBackendEmitter(
            _story_dir(tmp_path, "AG3-001"),
            default_project_key="demo-project",
        )
        emitter_two = StateBackendEmitter(
            _story_dir(tmp_path, "AG3-002"),
            default_project_key="demo-project",
        )
        emitter_one.emit(
            Event(
                story_id="AG3-001",
                event_type=EventType.FLOW_START,
                run_id="run-1",
            )
        )
        emitter_two.emit(
            Event(
                story_id="AG3-002",
                event_type=EventType.FLOW_START,
                run_id="run-2",
            )
        )

        results = emitter_one.query("AG3-001")
        assert len(results) == 1
        assert results[0].story_id == "AG3-001"

    def test_emitter_derives_project_key_and_run_id_from_runtime_state(
        self,
        tmp_path: Path,
    ) -> None:
        story_dir = _story_dir(tmp_path)
        save_story_context(
            story_dir,
            StoryContext(
                project_key="demo-project",
                story_id="AG3-001",
                story_type=StoryType.IMPLEMENTATION,
                execution_route=StoryMode.EXECUTION,
                title="Telemetry derivation",
                project_root=tmp_path / "demo-project",
            ),
        )
        save_flow_execution(
            story_dir,
            FlowExecution(
                project_key="demo-project",
                story_id="AG3-001",
                run_id="run-derived-001",
                flow_id="implementation",
                level="story",
                owner="pipeline_engine",
                status="IN_PROGRESS",
            ),
        )
        emitter = StateBackendEmitter(story_dir)

        emitter.emit(
            Event(
                story_id="AG3-001",
                event_type=EventType.NODE_RESULT,
                payload={"outcome": "PASS"},
            )
        )

        results = emitter.query("AG3-001")
        assert len(results) == 1
        assert results[0].project_key == "demo-project"
        assert results[0].run_id == "run-derived-001"

    def test_missing_runtime_scope_degrades_without_raise(
        self,
        tmp_path: Path,
    ) -> None:
        story_dir = _story_dir(tmp_path)
        emitter = StateBackendEmitter(story_dir)

        emitter.emit(
            Event(
                story_id="AG3-001",
                event_type=EventType.ERROR,
            )
        )

        assert emitter.query("AG3-001") == []

    def test_implements_event_emitter_protocol(self, tmp_path: Path) -> None:
        emitter = StateBackendEmitter(
            _story_dir(tmp_path),
            default_project_key="demo-project",
        )
        assert isinstance(emitter, EventEmitter)
