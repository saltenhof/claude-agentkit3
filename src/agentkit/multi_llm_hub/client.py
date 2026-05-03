"""Synchronous REST client for the external Multi-LLM Hub."""

from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Protocol, cast

from pydantic import ValidationError

from agentkit.multi_llm_hub.entities import (
    HubBackendMetric,
    HubBackendName,
    HubBackendStatus,
    HubHealth,
    HubHolder,
    HubMessage,
    HubMessageStatus,
    HubSession,
    HubSessionLease,
)
from agentkit.multi_llm_hub.errors import (
    HubSessionNotFoundError,
    HubUnavailableError,
    MultiLlmHubError,
)

if TYPE_CHECKING:
    from collections.abc import Mapping

_BACKEND_LABELS: dict[HubBackendName, str] = {
    "chatgpt": "ChatGPT",
    "gemini": "Gemini",
    "grok": "Grok",
    "qwen": "Qwen",
    "kimi": "Kimi",
}
_KNOWN_BACKENDS = frozenset(_BACKEND_LABELS)


class JsonTransport(Protocol):
    """Minimal JSON transport abstraction for Hub REST calls."""

    def request(
        self,
        method: str,
        path: str,
        payload: Mapping[str, object] | None = None,
    ) -> dict[str, object]:
        ...


class UrllibJsonTransport:
    """HTTP JSON transport backed by the Python standard library."""

    def __init__(self, base_url: str, *, timeout: float = 30.0) -> None:
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout

    def request(
        self,
        method: str,
        path: str,
        payload: Mapping[str, object] | None = None,
    ) -> dict[str, object]:
        body = json.dumps(payload, sort_keys=True).encode("utf-8") if payload is not None else None
        request = urllib.request.Request(
            url=f"{self._base_url}{path}",
            method=method,
            data=body,
            headers={"Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(request, timeout=self._timeout) as response:
                response_body = response.read()
        except urllib.error.HTTPError as exc:
            raise _hub_error_from_http_error(exc) from exc
        except urllib.error.URLError as exc:
            raise HubUnavailableError(f"Multi-LLM Hub unavailable: {exc}") from exc
        except TimeoutError as exc:
            raise HubUnavailableError("Multi-LLM Hub request timed out") from exc

        data = json.loads(response_body.decode("utf-8"))
        if not isinstance(data, dict):
            raise MultiLlmHubError("Multi-LLM Hub response must be a JSON object")
        return cast("dict[str, object]", data)


class HubClient:
    """Adapter client for the external Multi-LLM Hub REST API."""

    def __init__(
        self,
        base_url: str,
        *,
        timeout: float = 30.0,
        transport: JsonTransport | None = None,
    ) -> None:
        self._transport = transport or UrllibJsonTransport(base_url, timeout=timeout)

    def health(self) -> HubHealth:
        """Return Hub health information."""

        return HubHealth.model_validate(self._request("GET", "/api/health"))

    def pool_status(self) -> list[HubBackendMetric]:
        """Return backend pool status as cockpit metrics."""

        data = self._request("GET", "/api/status")
        raw_backends = _object_map(data.get("backends"))
        metrics: list[HubBackendMetric] = []
        for backend_name in sorted(raw_backends):
            backend = _backend_name(backend_name)
            raw_metric = _object_map(raw_backends[backend_name])
            metrics.append(_backend_metric(backend, raw_metric))
        return metrics

    def list_sessions(self, *, include_inactive: bool = False) -> list[HubSession]:
        """Return active sessions, optionally including released/expired sessions."""

        path = "/api/sessions?limit=200" if include_inactive else "/api/sessions?status=active&limit=200"
        data = self._request("GET", path)
        raw_sessions = _object_list(data.get("sessions"))
        return [HubSession.model_validate(_session_payload(raw_session)) for raw_session in raw_sessions]

    def acquire(
        self,
        *,
        owner: str,
        description: str,
        llms: list[HubBackendName],
    ) -> HubSessionLease:
        """Acquire a Hub session lease."""

        payload: dict[str, object] = {
            "owner": owner,
            "description": description,
        }
        if llms:
            payload["llms"] = list(llms)
        return HubSessionLease.model_validate(
            _lease_payload(self._request("POST", "/api/session/acquire", payload)),
        )

    def send(
        self,
        *,
        session_id: str,
        token: str,
        message: str | None = None,
        target: HubBackendName | None = None,
        targets: dict[HubBackendName, str] | None = None,
    ) -> dict[HubBackendName, HubMessage]:
        """Send a message through the Hub and return per-backend messages."""

        payload: dict[str, object] = {
            "session_id": session_id,
            "token": token,
        }
        if message is not None:
            payload["message"] = message
        if target is not None:
            payload["target"] = target
        if targets is not None:
            payload["targets"] = {
                backend: {"message": backend_message}
                for backend, backend_message in targets.items()
            }

        data = self._request("POST", "/api/session/send", payload)
        responses = _object_map(data.get("responses"))
        sent_at = datetime.now(UTC)
        return {
            _backend_name(backend): _message_from_response(
                session_id=session_id,
                backend=_backend_name(backend),
                raw_response=_object_map(raw_response),
                sent_at=sent_at,
            )
            for backend, raw_response in responses.items()
        }

    def release(self, *, session_id: str, token: str) -> None:
        """Release a Hub session lease."""

        self._request(
            "POST",
            "/api/session/release",
            {"session_id": session_id, "token": token},
        )

    def resume(self, *, session_id: str) -> HubSessionLease:
        """Resume a previously released Hub session."""

        return HubSessionLease.model_validate(
            _lease_payload(
                self._request("POST", "/api/session/resume", {"session_id": session_id}),
            ),
        )

    def _request(
        self,
        method: str,
        path: str,
        payload: Mapping[str, object] | None = None,
    ) -> dict[str, object]:
        try:
            return self._transport.request(method, path, payload)
        except MultiLlmHubError:
            raise
        except (OSError, json.JSONDecodeError, ValidationError) as exc:
            raise HubUnavailableError(f"Multi-LLM Hub request failed: {exc}") from exc


def _hub_error_from_http_error(exc: urllib.error.HTTPError) -> MultiLlmHubError:
    detail = exc.read().decode("utf-8", errors="replace")
    try:
        payload = json.loads(detail)
    except json.JSONDecodeError:
        payload = {}
    if isinstance(payload, dict):
        code = payload.get("error")
        message = payload.get("detail")
        if code == "unknown_session":
            return HubSessionNotFoundError(str(message or "Hub session not found"))
        if exc.code >= 500:
            return HubUnavailableError(str(message or detail or f"Hub HTTP {exc.code}"))
        return MultiLlmHubError(str(message or detail or f"Hub HTTP {exc.code}"))
    if exc.code >= 500:
        return HubUnavailableError(detail or f"Hub HTTP {exc.code}")
    return MultiLlmHubError(detail or f"Hub HTTP {exc.code}")


def _backend_metric(
    backend: HubBackendName,
    raw_metric: dict[str, object],
) -> HubBackendMetric:
    return HubBackendMetric(
        name=backend,
        label=_BACKEND_LABELS[backend],
        status=_backend_status(raw_metric.get("status")),
        slots_total=_int_value(raw_metric.get("slots_total")),
        slots_in_use=_int_value(raw_metric.get("slots_in_use")),
        sends=0,
        responses=0,
        errors=0,
        avg_response_ms=None,
        holders=[
            HubHolder.model_validate(_holder_payload(raw_holder))
            for raw_holder in _object_list(raw_metric.get("holders"))
        ],
    )


def _holder_payload(raw_holder: dict[str, object]) -> dict[str, object]:
    return {
        "session_id": str(raw_holder.get("session_id", "")),
        "owner": str(raw_holder.get("owner", "")),
        "description": str(raw_holder.get("description", "")),
    }


def _session_payload(raw_session: dict[str, object]) -> dict[str, object]:
    return {
        "session_id": raw_session["session_id"],
        "owner": raw_session["owner"],
        "description": raw_session.get("description", ""),
        "llms": [_backend_name(str(raw_backend)) for raw_backend in _raw_list(raw_session.get("llms"))],
        "status": raw_session["status"],
        "created_at": raw_session["created_at"],
        "last_activity": raw_session["last_activity"],
        "resumable": bool(raw_session.get("resumable", False)),
    }


def _lease_payload(raw_lease: dict[str, object]) -> dict[str, object]:
    return {
        "session_id": raw_lease["session_id"],
        "token": raw_lease["token"],
        "llms": [_backend_name(str(raw_backend)) for raw_backend in _raw_list(raw_lease.get("llms"))],
        "slots": {
            _backend_name(backend): _int_value(slot_id)
            for backend, slot_id in _object_map(raw_lease.get("slots")).items()
        },
    }


def _message_from_response(
    *,
    session_id: str,
    backend: HubBackendName,
    raw_response: dict[str, object],
    sent_at: datetime,
) -> HubMessage:
    raw_status = str(raw_response.get("status", "error"))
    status: HubMessageStatus = "ok" if raw_status == "ok" else "error"
    text = str(raw_response.get("response", ""))
    if status == "error" and text == "":
        text = str(raw_response.get("error", ""))
    return HubMessage(
        id=f"{session_id}:{backend}:assistant",
        session_id=session_id,
        backend=backend,
        role="assistant",
        text=text,
        at=sent_at,
        status=status,
    )


def _backend_name(value: str) -> HubBackendName:
    if value not in _KNOWN_BACKENDS:
        raise MultiLlmHubError(f"Unsupported Hub backend: {value}")
    return value


def _backend_status(value: object) -> HubBackendStatus:
    allowed: tuple[HubBackendStatus, ...] = ("healthy", "degraded", "unavailable")
    if value in allowed:
        return value
    return "unavailable"


def _int_value(value: object) -> int:
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        return int(value)
    return 0


def _object_map(value: object) -> dict[str, object]:
    if not isinstance(value, dict):
        return {}
    return cast("dict[str, object]", value)


def _object_list(value: object) -> list[dict[str, object]]:
    if not isinstance(value, list):
        return []
    return [_object_map(item) for item in value if isinstance(item, dict)]


def _raw_list(value: object) -> list[object]:
    if not isinstance(value, list):
        return []
    return cast("list[object]", value)
