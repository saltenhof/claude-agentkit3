from __future__ import annotations

from datetime import UTC, datetime

import pytest

from agentkit.integration_clients.multi_llm_hub.entities import HubBackendMetric, HubHealth, HubSession
from agentkit.integration_clients.multi_llm_hub.sse_stream import (
    parse_hub_topics,
    render_hub_heartbeat,
    render_hub_snapshot,
)


class _HubSnapshotSource:
    def backend_status(self) -> tuple[HubHealth, list[HubBackendMetric]]:
        return (
            HubHealth(
                status="ok",
                version="0.3.0",
                backends={"chatgpt": "ok"},
                persistence="ok",
                uptime_ms=100,
            ),
            [
                HubBackendMetric(
                    name="chatgpt",
                    label="ChatGPT",
                    status="healthy",
                    slots_total=2,
                    slots_in_use=1,
                    sends=1,
                    responses=1,
                    errors=0,
                    avg_response_ms=None,
                    holders=[],
                ),
            ],
        )

    def sessions(self) -> list[HubSession]:
        return [
            HubSession(
                session_id="s-1",
                owner="main",
                description="Main",
                llms=["chatgpt"],
                status="active",
                created_at=datetime(2026, 5, 4, tzinfo=UTC),
                last_activity=datetime(2026, 5, 4, tzinfo=UTC),
                resumable=False,
            ),
        ]


def test_render_hub_snapshot_filters_topics_and_adds_heartbeat() -> None:
    payload = render_hub_snapshot(
        source=_HubSnapshotSource(),
        topics={"sessions"},
    ).decode("utf-8")

    assert "event: sessions" in payload
    assert "s-1" in payload
    assert "event: backend_status" not in payload
    assert "event: heartbeat" in payload


def test_render_hub_heartbeat_is_sse_event() -> None:
    assert render_hub_heartbeat().decode("utf-8").startswith("event: heartbeat\n")


def test_parse_hub_topics_defaults_and_rejects_unknown() -> None:
    assert "backend_status" in parse_hub_topics(None)
    assert parse_hub_topics("backend_status,sessions") == frozenset({"backend_status", "sessions"})

    with pytest.raises(ValueError, match="Unknown SSE topic"):
        parse_hub_topics("backend_status,unknown")
