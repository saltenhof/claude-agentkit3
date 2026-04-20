"""Unit tests for agentkit.telemetry.emitters."""

from __future__ import annotations

from typing import runtime_checkable

from agentkit.telemetry.emitters import EventEmitter, MemoryEmitter, NullEmitter
from agentkit.telemetry.events import Event, EventType


class TestMemoryEmitter:
    """Tests for the MemoryEmitter."""

    def test_emit_and_query_roundtrip(self) -> None:
        emitter = MemoryEmitter()
        evt = Event(
            story_id="AG3-001",
            event_type=EventType.FLOW_START,
            phase="setup",
        )
        emitter.emit(evt)
        results = emitter.query("AG3-001")
        assert len(results) == 1
        assert results[0] is evt

    def test_query_filters_by_event_type(self) -> None:
        emitter = MemoryEmitter()
        evt1 = Event(story_id="AG3-001", event_type=EventType.FLOW_START)
        evt2 = Event(story_id="AG3-001", event_type=EventType.FLOW_END)
        emitter.emit(evt1)
        emitter.emit(evt2)
        results = emitter.query("AG3-001", event_type=EventType.FLOW_END)
        assert len(results) == 1
        assert results[0] is evt2

    def test_query_filters_by_story_id(self) -> None:
        emitter = MemoryEmitter()
        evt1 = Event(story_id="AG3-001", event_type=EventType.FLOW_START)
        evt2 = Event(story_id="AG3-002", event_type=EventType.FLOW_START)
        emitter.emit(evt1)
        emitter.emit(evt2)
        results = emitter.query("AG3-001")
        assert len(results) == 1
        assert results[0].story_id == "AG3-001"

    def test_clear_removes_all_events(self) -> None:
        emitter = MemoryEmitter()
        emitter.emit(Event(story_id="AG3-001", event_type=EventType.FLOW_START))
        emitter.emit(Event(story_id="AG3-002", event_type=EventType.ERROR))
        assert len(emitter.all_events) == 2
        emitter.clear()
        assert len(emitter.all_events) == 0

    def test_all_events_property(self) -> None:
        emitter = MemoryEmitter()
        evt1 = Event(story_id="AG3-001", event_type=EventType.FLOW_START)
        evt2 = Event(story_id="AG3-002", event_type=EventType.ERROR)
        emitter.emit(evt1)
        emitter.emit(evt2)
        all_evts = emitter.all_events
        assert len(all_evts) == 2
        assert evt1 in all_evts
        assert evt2 in all_evts

    def test_all_events_returns_copy(self) -> None:
        emitter = MemoryEmitter()
        emitter.emit(Event(story_id="AG3-001", event_type=EventType.FLOW_START))
        copy1 = emitter.all_events
        copy1.clear()
        assert len(emitter.all_events) == 1

    def test_implements_event_emitter_protocol(self) -> None:
        emitter = MemoryEmitter()
        assert isinstance(emitter, EventEmitter)


class TestNullEmitter:
    """Tests for the NullEmitter."""

    def test_emit_does_not_raise(self) -> None:
        emitter = NullEmitter()
        evt = Event(story_id="AG3-001", event_type=EventType.FLOW_START)
        emitter.emit(evt)  # Should not raise

    def test_query_returns_empty_list(self) -> None:
        emitter = NullEmitter()
        emitter.emit(Event(story_id="AG3-001", event_type=EventType.FLOW_START))
        results = emitter.query("AG3-001")
        assert results == []

    def test_query_with_event_type_returns_empty(self) -> None:
        emitter = NullEmitter()
        results = emitter.query("AG3-001", event_type=EventType.ERROR)
        assert results == []

    def test_implements_event_emitter_protocol(self) -> None:
        emitter = NullEmitter()
        assert isinstance(emitter, EventEmitter)


class TestEventEmitterProtocol:
    """Verify the EventEmitter Protocol is runtime-checkable."""

    def test_protocol_is_runtime_checkable(self) -> None:
        assert runtime_checkable(EventEmitter)

    def test_memory_emitter_satisfies_protocol(self) -> None:
        assert isinstance(MemoryEmitter(), EventEmitter)

    def test_null_emitter_satisfies_protocol(self) -> None:
        assert isinstance(NullEmitter(), EventEmitter)
