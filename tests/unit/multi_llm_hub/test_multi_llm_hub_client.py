from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from agentkit.multi_llm_hub.client import HubClient
from agentkit.multi_llm_hub.errors import HubSessionNotFoundError, HubUnavailableError

if TYPE_CHECKING:
    from collections.abc import Mapping


class _FakeTransport:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, dict[str, object] | None]] = []
        self.timeout_calls: list[float | None] = []
        self.responses: dict[tuple[str, str], dict[str, object] | Exception] = {}

    def request(
        self,
        method: str,
        path: str,
        payload: Mapping[str, object] | None = None,
        *,
        timeout: float | None = None,
    ) -> dict[str, object]:
        payload_dict = dict(payload) if payload is not None else None
        self.calls.append((method, path, payload_dict))
        self.timeout_calls.append(timeout)
        response = self.responses[(method, path)]
        if isinstance(response, Exception):
            raise response
        return response


def test_acquire_returns_session_lease() -> None:
    transport = _FakeTransport()
    transport.responses[("POST", "/api/session/acquire")] = {
        "session_id": "s-1",
        "token": "tok",
        "llms": ["chatgpt", "gemini"],
        "slots": {"chatgpt": 0, "gemini": 1},
    }
    client = HubClient("http://hub.test", transport=transport)

    lease = client.acquire(
        owner="main-agent",
        description="Review session",
        llms=["chatgpt", "gemini"],
    )

    assert lease.session_id == "s-1"
    assert lease.llms == ["chatgpt", "gemini"]
    assert transport.calls == [
        (
            "POST",
            "/api/session/acquire",
            {
                "owner": "main-agent",
                "description": "Review session",
                "llms": ["chatgpt", "gemini"],
            },
        ),
    ]


def test_send_broadcast_returns_message_per_backend() -> None:
    transport = _FakeTransport()
    transport.responses[("POST", "/api/session/send")] = {
        "mode": "broadcast",
        "responses": {
            "chatgpt": {"response": "A", "duration_ms": 12, "status": "ok"},
            "gemini": {"response": "B", "duration_ms": 15, "status": "ok"},
        },
    }
    client = HubClient("http://hub.test", transport=transport)

    messages = client.send(session_id="s-1", token="tok", message="Hello")

    assert sorted(messages) == ["chatgpt", "gemini"]
    assert messages["chatgpt"].text == "A"
    assert messages["gemini"].status == "ok"


def test_send_single_target_forwards_target() -> None:
    transport = _FakeTransport()
    transport.responses[("POST", "/api/session/send")] = {
        "mode": "single",
        "responses": {
            "qwen": {"response": "Q", "duration_ms": 10, "status": "ok"},
        },
    }
    client = HubClient("http://hub.test", transport=transport)

    messages = client.send(
        session_id="s-1",
        token="tok",
        message="Hello",
        target="qwen",
    )

    assert list(messages) == ["qwen"]
    assert transport.calls[0][2] == {
        "session_id": "s-1",
        "token": "tok",
        "message": "Hello",
        "target": "qwen",
    }


def test_release_posts_session_token() -> None:
    transport = _FakeTransport()
    transport.responses[("POST", "/api/session/release")] = {
        "status": "released",
        "session_id": "s-1",
    }
    client = HubClient("http://hub.test", transport=transport)

    client.release(session_id="s-1", token="tok")

    assert transport.calls == [
        ("POST", "/api/session/release", {"session_id": "s-1", "token": "tok"}),
    ]


def test_pool_status_maps_backend_metrics() -> None:
    transport = _FakeTransport()
    transport.responses[("GET", "/api/status")] = {
        "version": "0.3.0",
        "backends": {
            "chatgpt": {
                "name": "chatgpt",
                "status": "healthy",
                "slots_total": 3,
                "slots_in_use": 1,
                "holders": [
                    {
                        "session_id": "s-1",
                        "owner": "main",
                        "description": "Main session",
                    },
                ],
            },
        },
        "active_sessions": 1,
        "total_slots": 3,
        "available_slots": 2,
    }
    client = HubClient("http://hub.test", transport=transport)

    metrics = client.pool_status()

    assert metrics[0].name == "chatgpt"
    assert metrics[0].label == "ChatGPT"
    assert metrics[0].holders[0].owner == "main"


def test_hub_unavailable_is_propagated() -> None:
    transport = _FakeTransport()
    transport.responses[("GET", "/api/health")] = HubUnavailableError("down")
    client = HubClient("http://hub.test", transport=transport)

    with pytest.raises(HubUnavailableError):
        client.health()


def test_unknown_session_is_propagated() -> None:
    transport = _FakeTransport()
    transport.responses[("POST", "/api/session/send")] = HubSessionNotFoundError("missing")
    client = HubClient("http://hub.test", transport=transport)

    with pytest.raises(HubSessionNotFoundError):
        client.send(session_id="missing", token="tok", message="Hello")
