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
    HubBackendSessionStats,
    HubBackendStatus,
    HubHealth,
    HubHolder,
    HubMessage,
    HubMessageStatus,
    HubSession,
    HubSessionLease,
    HubSessionStats,
    HubSessionStatus,
)
from agentkit.multi_llm_hub.errors import (
    HubAcquireQueuedError,
    HubLoginRequiredError,
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
        *,
        timeout: float | None = None,
    ) -> dict[str, object]:
        """Make a JSON request.

        Args:
            method: HTTP method (GET/POST/...).
            path: Request path relative to the base URL.
            payload: Optional request body as a mapping.
            timeout: Per-request timeout in seconds. ``None`` => use the
                transport's constructor default (backward-compatible; no
                existing caller breaks).

        Returns:
            Parsed JSON response as a dict.
        """
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
        *,
        timeout: float | None = None,
    ) -> dict[str, object]:
        """Make a JSON HTTP request.

        Args:
            method: HTTP method.
            path: Request path relative to the base URL.
            payload: Optional JSON body.
            timeout: Per-request timeout in seconds. ``None`` => constructor
                default (FK-11 §11.6.1 additive, backward-compatible).

        Returns:
            Parsed JSON response.
        """
        effective_timeout = timeout if timeout is not None else self._timeout
        body = json.dumps(payload, sort_keys=True).encode("utf-8") if payload is not None else None
        request = urllib.request.Request(
            url=f"{self._base_url}{path}",
            method=method,
            data=body,
            headers={"Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(request, timeout=effective_timeout) as response:
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


class HubClientProtocol(Protocol):
    """Structural protocol for HubClient — allows test-doubles without inheritance."""

    def health(self) -> HubHealth: ...
    def pool_status(self) -> list[HubBackendMetric]: ...
    def list_sessions(self, *, include_inactive: bool = ...) -> list[HubSession]: ...
    def acquire(
        self,
        *,
        owner: str,
        description: str,
        llms: list[HubBackendName],
        timeout: float | None = ...,
    ) -> HubSessionLease:
        """Acquire a Hub session lease.

        Args:
            owner: Owner identifier.
            description: Human-readable description of the session purpose.
            llms: Requested LLM backends.
            timeout: Per-request timeout in seconds. ``None`` => transport default.

        Returns:
            Granted :class:`HubSessionLease`.

        Raises:
            HubAcquireQueuedError: When the Hub signals ``status == "queued"``
                (no slot granted yet); the caller must retry.
            HubUnavailableError: On transient Hub unavailability.
            MultiLlmHubError: On other Hub errors.
        """
        ...

    def send(
        self,
        *,
        session_id: str,
        token: str,
        message: str | None = ...,
        target: HubBackendName | None = ...,
        targets: dict[HubBackendName, str] | None = ...,
        timeout: float | None = ...,
    ) -> dict[HubBackendName, HubMessage]:
        """Send a message through the Hub.

        Args:
            session_id: Active session identifier.
            token: Session authentication token.
            message: Optional broadcast message.
            target: Optional single-backend target.
            targets: Optional per-backend messages.
            timeout: Per-request timeout in seconds. ``None`` => transport default.

        Returns:
            Per-backend :class:`HubMessage` map.
        """
        ...

    def release(self, *, session_id: str, token: str, timeout: float | None = ...) -> None:
        """Release a Hub session lease.

        Args:
            session_id: Active session identifier.
            token: Session authentication token.
            timeout: Per-request timeout in seconds. ``None`` => transport default.
        """
        ...

    def resume(self, *, session_id: str) -> HubSessionLease: ...

    def session_stats(self, *, session_id: str, timeout: float | None = ...) -> HubSessionStats:
        """Return post-hoc per-LLM session statistics (FK-25 §25.5.4).

        Read-only ``llm_session_stats`` consume surface: per-LLM message count +
        whether the LLM answered, plus the session/release status. No token is
        required (the external tool works for active and released sessions).

        Args:
            session_id: Session identifier to read stats for.
            timeout: Per-request timeout in seconds. ``None`` => transport default.

        Returns:
            The typed :class:`HubSessionStats`.
        """
        ...


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
        timeout: float | None = None,
    ) -> HubSessionLease:
        """Acquire a Hub session lease.

        Detects a ``status == "queued"`` wire response (no slot granted) and
        raises :class:`HubAcquireQueuedError` BEFORE attempting to parse a lease
        (FK-11 §11.2.3 Zeile 187 / §11.6.1). The return type is always
        :class:`HubSessionLease` (no Union) — a queued state is an exception,
        keeping the AG3-079-stable port surface.

        Args:
            owner: Owner identifier.
            description: Human-readable description.
            llms: Requested LLM backends.
            timeout: Per-request timeout (``None`` => transport default).

        Returns:
            Granted :class:`HubSessionLease`.

        Raises:
            HubAcquireQueuedError: When the Hub signals ``status == "queued"``.
            HubUnavailableError: On transient Hub unavailability.
            MultiLlmHubError: On other Hub errors.
        """
        payload: dict[str, object] = {
            "owner": owner,
            "description": description,
        }
        if llms:
            payload["llms"] = list(llms)
        raw = self._request("POST", "/api/session/acquire", payload, timeout=timeout)
        # FK-11 §11.2.3 Zeile 187: detect queued response BEFORE _lease_payload,
        # which would KeyError on a missing session_id/token.
        if raw.get("status") == "queued":
            wait_seconds = raw.get("estimated_wait_seconds")
            estimated: float | None = float(wait_seconds) if isinstance(wait_seconds, (int, float)) else None
            raise HubAcquireQueuedError(
                "Hub acquire returned queued status — no slot granted yet",
                estimated_wait_seconds=estimated,
            )
        return HubSessionLease.model_validate(_lease_payload(raw))

    def send(
        self,
        *,
        session_id: str,
        token: str,
        message: str | None = None,
        target: HubBackendName | None = None,
        targets: dict[HubBackendName, str] | None = None,
        timeout: float | None = None,
    ) -> dict[HubBackendName, HubMessage]:
        """Send a message through the Hub and return per-backend messages.

        Args:
            session_id: Active session identifier.
            token: Session authentication token.
            message: Optional broadcast message.
            target: Optional single-backend target.
            targets: Optional per-backend messages.
            timeout: Per-request timeout (``None`` => transport default).

        Returns:
            Per-backend :class:`HubMessage` map.
        """
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

        data = self._request("POST", "/api/session/send", payload, timeout=timeout)
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

    def release(self, *, session_id: str, token: str, timeout: float | None = None) -> None:
        """Release a Hub session lease.

        Args:
            session_id: Active session identifier.
            token: Session authentication token.
            timeout: Per-request timeout (``None`` => transport default).
        """
        self._request(
            "POST",
            "/api/session/release",
            {"session_id": session_id, "token": token},
            timeout=timeout,
        )

    def resume(self, *, session_id: str) -> HubSessionLease:
        """Resume a previously released Hub session.

        Args:
            session_id: Session identifier to resume.

        Returns:
            Renewed :class:`HubSessionLease`.
        """
        return HubSessionLease.model_validate(
            _lease_payload(
                self._request("POST", "/api/session/resume", {"session_id": session_id}),
            ),
        )

    def session_stats(
        self, *, session_id: str, timeout: float | None = None
    ) -> HubSessionStats:
        """Return post-hoc per-LLM session statistics (FK-25 §25.5.4).

        Read-only ``llm_session_stats`` consume surface for the AK3 fine-design
        adapter's post-hoc verification: per-LLM message count + whether the LLM
        answered, plus the session/release status. No token is required.

        Args:
            session_id: Session identifier to read stats for.
            timeout: Per-request timeout (``None`` => transport default).

        Returns:
            The typed :class:`HubSessionStats`.
        """
        encoded = urllib.parse.quote(session_id, safe="")
        raw = self._request(
            "GET", f"/api/session/stats?session_id={encoded}", timeout=timeout
        )
        return _session_stats_payload(raw)

    def _request(
        self,
        method: str,
        path: str,
        payload: Mapping[str, object] | None = None,
        timeout: float | None = None,
    ) -> dict[str, object]:
        try:
            return self._transport.request(method, path, payload, timeout=timeout)
        except MultiLlmHubError:
            raise
        except (OSError, json.JSONDecodeError, ValidationError) as exc:
            raise HubUnavailableError(f"Multi-LLM Hub request failed: {exc}") from exc


def _hub_error_from_http_error(exc: urllib.error.HTTPError) -> MultiLlmHubError:
    """Map an HTTP error to a typed MultiLlmHubError subclass.

    Reads the typed ``error_code`` field from the response payload
    (routes.py:364-366) — NOT the ``error`` message — so canonical route codes
    (``hub_session_not_found``, ``hub_login_required``, ``hub_unavailable``,
    ``hub_error``) are dispatched to distinct exception types. This fixes the
    wire-key mismatch where the old code read ``payload.get("error")`` (the
    human-readable message) instead of the typed ``error_code`` field.

    Backward-compatible: unknown/missing ``error_code`` falls back to the
    prior behaviour (5xx → HubUnavailableError, 4xx → MultiLlmHubError).

    Args:
        exc: The HTTP error from urllib.

    Returns:
        A typed :class:`MultiLlmHubError` subclass.
    """
    detail = exc.read().decode("utf-8", errors="replace")
    try:
        payload = json.loads(detail)
    except json.JSONDecodeError:
        payload = {}
    if isinstance(payload, dict):
        # Read the TYPED error_code (routes.py:364-366), not the human message.
        error_code = payload.get("error_code")
        message = payload.get("error") or payload.get("detail") or detail or f"Hub HTTP {exc.code}"
        if error_code == "hub_session_not_found":
            return HubSessionNotFoundError(str(message))
        if error_code == "hub_login_required":
            return HubLoginRequiredError(str(message))
        if error_code in ("hub_unavailable", "hub_error") or exc.code >= 500:
            return HubUnavailableError(str(message))
        return MultiLlmHubError(str(message))
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


def _session_stats_payload(raw_stats: dict[str, object]) -> HubSessionStats:
    """Map a raw ``llm_session_stats`` response into the typed read model.

    Faithful to the external Hub contract (FK-25 §25.5.4): per-LLM message count
    + answered flag, plus the session status. ``released`` is DERIVED from the
    session status (``status == "released"``) rather than trusting a separate
    boolean the Hub may not send -- a still-``active`` or ``expired`` session
    after the discussion is NOT a correct release (drives the WARNING upstream).
    """
    status = _session_status(raw_stats.get("status"))
    backends_raw = _object_map(raw_stats.get("backends"))
    backends: list[HubBackendSessionStats] = []
    for backend_name in sorted(backends_raw):
        backend = _backend_name(backend_name)
        row = _object_map(backends_raw[backend_name])
        message_count = _int_value(row.get("message_count"))
        # ``answered`` is reported by the Hub; fall back to a response-count /
        # message-count signal so a faithful client never reads a non-answering
        # LLM as answered (fail-closed for the upstream 0-answer abort).
        answered = _answered_flag(row)
        backends.append(
            HubBackendSessionStats(
                backend=backend,
                message_count=message_count,
                answered=answered,
            )
        )
    return HubSessionStats(
        session_id=str(raw_stats.get("session_id", "")),
        status=status,
        released=status == "released",
        backends=backends,
    )


def _answered_flag(row: dict[str, object]) -> bool:
    raw_answered = row.get("answered")
    if isinstance(raw_answered, bool):
        return raw_answered
    # No explicit flag: derive ONLY from a response count (a real answer fact the
    # hub contract reports). NEVER from ``message_count`` -- per FK-25 §25.5.4
    # that is the count of SENT messages, so deriving an answer from it would
    # invent one for a silent backend and defeat the upstream 0-answer abort
    # (NO ERROR BYPASSING: no silent fallback to weaker data quality). Missing
    # both facts is fail-closed False (never invent an answer).
    if "response_count" in row:
        return _int_value(row.get("response_count")) > 0
    return False


def _session_status(value: object) -> HubSessionStatus:
    allowed: tuple[HubSessionStatus, ...] = ("active", "released", "expired")
    if value in allowed:
        return value
    # Unknown / missing status is NOT silently a correct release: treat it as the
    # most conservative non-released state so the release WARNING fires.
    return "active"


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
