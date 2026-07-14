"""Thin read-only ARE reachability adapter."""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Protocol


class ArePreflightError(RuntimeError):
    """The configured ARE health endpoint could not be validated."""


@dataclass(frozen=True)
class ArePreflightResponse:
    """Transport-shaped ARE health response."""

    status_code: int
    json_body: dict[str, object]


class ArePreflightTransport(Protocol):
    """Transport port at the ARE external-system boundary."""

    def send(self, request: urllib.request.Request) -> ArePreflightResponse:
        """Send one read-only health request."""
        ...


class UrlLibArePreflightTransport:
    """Production urllib transport for the ARE health endpoint."""

    def send(self, request: urllib.request.Request) -> ArePreflightResponse:
        """Send the request without exposing authorization data in errors."""
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                raw = response.read().decode("utf-8")
                body = json.loads(raw) if raw else {}
                return ArePreflightResponse(int(response.status), body)
        except urllib.error.HTTPError as exc:
            raise ArePreflightError(f"ARE health returned HTTP {exc.code}") from exc
        except (OSError, ValueError) as exc:
            raise ArePreflightError("ARE health endpoint is unreachable or invalid") from exc


class ArePreflightClient:
    """Read-only ARE reachability and token-validity client."""

    def __init__(
        self,
        base_url: str,
        token: str,
        *,
        transport: ArePreflightTransport | None = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._token = token
        self._transport = transport or UrlLibArePreflightTransport()

    def health(self) -> ArePreflightResponse:
        """Read the authenticated ARE health endpoint."""
        request = urllib.request.Request(f"{self._base_url}/health", method="GET")
        request.add_header("Authorization", f"Bearer {self._token}")
        return self._transport.send(request)
