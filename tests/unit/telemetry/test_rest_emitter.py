"""Unit tests for the hook-side REST telemetry emitter (AG3-129).

Covers the non-blocking / fail-soft contract without a live server:

* ``emit`` never raises and never falls back to a direct DB when the client
  fails (FK-30 "blockieren nie");
* ``query`` returns ``[]`` on a read fault (the pre-existing fail-soft behaviour,
  unchanged blocking effect);
* the happy path maps ``Event`` -> wire -> ``Event`` faithfully.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest

from agentkit.backend.control_plane.models import (
    TelemetryEventAccepted,
    TelemetryEventQueryResponse,
)
from agentkit.backend.control_plane.telemetry import execution_event_to_wire
from agentkit.backend.telemetry.contract.records import ExecutionEventRecord
from agentkit.backend.telemetry.events import Event, EventType
from agentkit.backend.telemetry.rest_emitter import RestEventEmitter

if TYPE_CHECKING:
    from agentkit.backend.control_plane.models import TelemetryEventIngestRequest

_PROJECT = "tenant-a"
_STORY = "AG3-129"
_RUN = "run-129"


class _RecordingClient:
    """A minimal in-memory stand-in for GovernanceEdgeClient (not a mock).

    Stores emitted events and serves them back via ``query`` -- a first-class
    fake used only to exercise the emitter's mapping/branching in isolation.
    """

    def __init__(self) -> None:
        self.emitted: list[TelemetryEventIngestRequest] = []

    def emit_telemetry_event(
        self, request: TelemetryEventIngestRequest
    ) -> TelemetryEventAccepted:
        self.emitted.append(request)
        return TelemetryEventAccepted(event_id=request.event_id or "evt-1")

    def query_telemetry_events(
        self, *, project_key: str, story_id: str, event_type: str | None = None
    ) -> TelemetryEventQueryResponse:
        events = [
            execution_event_to_wire(
                ExecutionEventRecord(
                    project_key=project_key,
                    story_id=story_id,
                    run_id=_RUN,
                    event_id=req.event_id or "evt-1",
                    event_type=req.event_type.value,
                    occurred_at=req.occurred_at,
                    source_component=req.source_component,
                    severity=req.severity,
                    payload=dict(req.payload),
                )
            )
            for req in self.emitted
            if req.story_id == story_id
            and (event_type is None or req.event_type.value == event_type)
        ]
        return TelemetryEventQueryResponse(events=events)


class _FailingClient:
    """A client whose calls always raise (core unreachable)."""

    def emit_telemetry_event(
        self, request: TelemetryEventIngestRequest
    ) -> TelemetryEventAccepted:
        raise ConnectionError("core unreachable")

    def query_telemetry_events(
        self, *, project_key: str, story_id: str, event_type: str | None = None
    ) -> TelemetryEventQueryResponse:
        raise ConnectionError("core unreachable")


def _event() -> Event:
    return Event(
        story_id=_STORY,
        event_type=EventType.INCREMENT_COMMIT,
        timestamp=datetime(2026, 6, 2, 12, 0, tzinfo=UTC),
        project_key=_PROJECT,
        run_id=_RUN,
        payload={"marker": "x"},
    )


def test_emit_and_query_round_trip() -> None:
    client = _RecordingClient()
    emitter = RestEventEmitter(client, project_key=_PROJECT, run_id=_RUN)  # type: ignore[arg-type]

    emitter.emit(_event())

    assert len(client.emitted) == 1
    events = emitter.query(_STORY, EventType.INCREMENT_COMMIT)
    assert len(events) == 1
    assert events[0].event_type == EventType.INCREMENT_COMMIT
    assert events[0].payload == {"marker": "x"}
    assert events[0].project_key == _PROJECT


def test_emit_is_non_blocking_on_client_failure() -> None:
    emitter = RestEventEmitter(_FailingClient(), project_key=_PROJECT, run_id=_RUN)  # type: ignore[arg-type]
    # Must not raise (non-blocking; dropped, no direct-DB fallback).
    emitter.emit(_event())


def test_query_is_fail_soft_on_client_failure() -> None:
    emitter = RestEventEmitter(_FailingClient(), project_key=_PROJECT, run_id=_RUN)  # type: ignore[arg-type]
    assert emitter.query(_STORY, EventType.INCREMENT_COMMIT) == []


def test_strict_query_raises_on_client_failure() -> None:
    # AG3-129 FUND 3: an enforcement reader (strict_query) must NOT read a
    # core-unreachable counter as ``[]`` -- it re-raises so the guard fails closed.
    emitter = RestEventEmitter(
        _FailingClient(),  # type: ignore[arg-type]
        project_key=_PROJECT,
        run_id=_RUN,
        strict_query=True,
    )
    with pytest.raises(ConnectionError):
        emitter.query(_STORY, EventType.INCREMENT_COMMIT)


def test_emit_degrades_when_scope_missing() -> None:
    client = _RecordingClient()
    emitter = RestEventEmitter(client, project_key="", run_id="")  # type: ignore[arg-type]
    # An event without project_key/run_id and no emitter defaults is dropped.
    emitter.emit(
        Event(story_id=_STORY, event_type=EventType.INCREMENT_COMMIT)
    )
    assert client.emitted == []
