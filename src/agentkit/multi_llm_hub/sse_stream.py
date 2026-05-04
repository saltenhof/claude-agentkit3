"""SSE stream composition for the project-neutral Multi-LLM-Hub stream."""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal, Protocol

if TYPE_CHECKING:
    from collections.abc import Iterable, Iterator

    from agentkit.multi_llm_hub.entities import HubBackendMetric, HubHealth, HubSession

HubSseTopic = Literal["backend_status", "sessions", "session_messages"]
HUB_SSE_TOPICS: frozenset[HubSseTopic] = frozenset(
    {"backend_status", "sessions", "session_messages"},
)


class HubSseSnapshotSource(Protocol):
    """Read-side source for Hub live-event snapshots."""

    def backend_status(self) -> tuple[HubHealth, list[HubBackendMetric]]:
        """Return current Hub health and backend metrics."""
        ...

    def sessions(self) -> list[HubSession]:
        """Return current Hub sessions."""
        ...


@dataclass(frozen=True)
class HubSseEnvelope:
    """One typed Hub SSE event envelope."""

    event: HubSseTopic | Literal["heartbeat"]
    data: dict[str, object]


def parse_hub_topics(raw_topics: str | None) -> frozenset[HubSseTopic]:
    """Parse a comma-separated Hub SSE topic filter."""
    if raw_topics is None or not raw_topics.strip():
        return HUB_SSE_TOPICS
    topics: set[HubSseTopic] = set()
    invalid: list[str] = []
    for raw_topic in raw_topics.split(","):
        topic = raw_topic.strip()
        if not topic:
            continue
        if topic not in HUB_SSE_TOPICS:
            invalid.append(topic)
            continue
        topics.add(topic)
    if invalid:
        raise ValueError(f"Unknown SSE topic: {', '.join(sorted(invalid))}")
    return frozenset(topics or HUB_SSE_TOPICS)


def render_hub_sse_event(envelope: HubSseEnvelope) -> bytes:
    """Render one Hub SSE envelope as bytes."""
    payload = json.dumps(envelope.data, sort_keys=True, default=str)
    lines = [f"event: {envelope.event}", f"data: {payload}", ""]
    return ("\n".join(lines) + "\n").encode("utf-8")


def render_hub_heartbeat() -> bytes:
    """Render one Hub SSE heartbeat event."""
    return render_hub_sse_event(
        HubSseEnvelope(event="heartbeat", data={"type": "heartbeat"}),
    )


def render_hub_snapshot(
    *,
    source: HubSseSnapshotSource,
    topics: Iterable[HubSseTopic],
) -> bytes:
    """Render current matching Hub state as SSE bytes."""
    allowed = set(topics)
    chunks: list[bytes] = []
    if "backend_status" in allowed:
        health, metrics = source.backend_status()
        chunks.append(
            render_hub_sse_event(
                HubSseEnvelope(
                    event="backend_status",
                    data={
                        "health": health.model_dump(mode="json"),
                        "backends": [metric.model_dump(mode="json") for metric in metrics],
                    },
                ),
            ),
        )
    if "sessions" in allowed:
        chunks.append(
            render_hub_sse_event(
                HubSseEnvelope(
                    event="sessions",
                    data={
                        "sessions": [
                            session.model_dump(mode="json")
                            for session in source.sessions()
                        ],
                    },
                ),
            ),
        )
    chunks.append(render_hub_heartbeat())
    return b"".join(chunks)


def iter_hub_sse_stream(
    *,
    source: HubSseSnapshotSource,
    topics: Iterable[HubSseTopic],
    heartbeat_interval_seconds: float = 30.0,
) -> Iterator[bytes]:
    """Yield a lossy Hub SSE stream without cursor or buffering."""
    while True:
        yield render_hub_snapshot(source=source, topics=topics)
        time.sleep(heartbeat_interval_seconds)


__all__ = [
    "HUB_SSE_TOPICS",
    "HubSseEnvelope",
    "HubSseSnapshotSource",
    "HubSseTopic",
    "iter_hub_sse_stream",
    "parse_hub_topics",
    "render_hub_heartbeat",
    "render_hub_snapshot",
    "render_hub_sse_event",
]
