"""REST adapter for the Agent Requirements Engine (ARE)."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from pydantic import ValidationError

from agentkit.backend.requirements_coverage.contract import (
    AreContext,
    AreDockpointStatus,
    AreEvidence,
    AreRequirement,
    CoverageVerdict,
    EvidenceSubmitResult,
    EvidenceType,
)
from agentkit.backend.requirements_coverage.errors import (
    AreClientDecodeError,
    AreClientError,
    AreClientHttpError,
    AreClientResponseError,
)


@dataclass(frozen=True)
class AreHttpResponse:
    """HTTP response returned by the injected ARE transport."""

    status_code: int
    body: bytes


class AreHttpTransport(Protocol):
    """Transport port used by :class:`AreClient`."""

    def request(
        self,
        method: str,
        url: str,
        *,
        headers: dict[str, str],
        body: bytes | None = None,
    ) -> AreHttpResponse:
        """Execute one HTTP request."""


class UrlLibAreHttpTransport:
    """urllib-based ARE transport used in production wiring."""

    def request(
        self,
        method: str,
        url: str,
        *,
        headers: dict[str, str],
        body: bytes | None = None,
    ) -> AreHttpResponse:
        """Execute one HTTP request via :mod:`urllib.request`."""

        request = Request(url, data=body, headers=headers, method=method)
        try:
            with urlopen(request, timeout=30) as response:  # noqa: S310 - configured URL
                return AreHttpResponse(
                    status_code=int(response.status),
                    body=response.read(),
                )
        except HTTPError as exc:
            raise AreClientHttpError(
                f"ARE HTTP {exc.code} for {method} {url}"
            ) from exc
        except URLError as exc:
            raise AreClientHttpError(f"ARE HTTP request failed for {method} {url}: {exc}") from exc


class AreClient:
    """REST client for the ARE API (FK-40 §40.4).

    Args:
        base_url: Base URL of the ARE REST API.
        auth_token: Optional bearer token for authenticated requests.
        transport: Optional HTTP transport port for tests and alternate runtimes.
    """

    def __init__(
        self,
        base_url: str,
        auth_token: str | None = None,
        *,
        transport: AreHttpTransport | None = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._auth_token = auth_token
        self._transport = transport or UrlLibAreHttpTransport()

    @property
    def base_url(self) -> str:
        """Return the configured ARE base URL."""

        return self._base_url

    @property
    def auth_token(self) -> str | None:
        """Return the configured bearer token."""

        return self._auth_token

    def list_requirements(self, story_id: str, scope: str) -> list[AreRequirement]:
        """List requirements for a story in a given scope."""

        data = self._request_json(
            "GET",
            "/requirements",
            query={"story_id": story_id, "scope": scope},
        )
        return _parse_requirement_list(data, field="requirements")

    def get_recurring(self, scope: str, story_type: str) -> list[AreRequirement]:
        """Get recurring mandatory requirements for a scope and story type."""

        data = self._request_json(
            "GET",
            "/requirements/recurring",
            query={"scope": scope, "story_type": story_type},
        )
        return _parse_requirement_list(data, field="requirements")

    def load_context(self, story_id: str) -> AreContext:
        """Load must-cover requirements context for a story."""

        data = self._request_json("GET", f"/stories/{story_id}/context")
        try:
            if isinstance(data, list):
                return AreContext(
                    requirements=[AreRequirement.model_validate(item) for item in data],
                    loaded_at=datetime.now(UTC),
                )
            if not isinstance(data, dict):
                raise TypeError("ARE context response must be an object or list")
            if "loaded_at" not in data:
                data = {**data, "loaded_at": datetime.now(UTC).isoformat()}
            return AreContext.model_validate(data)
        except (TypeError, ValidationError) as exc:
            raise AreClientResponseError("Invalid ARE context response") from exc

    def submit_evidence(
        self,
        story_id: str,
        requirement_id: str,
        evidence_type: EvidenceType,
        evidence_ref: str,
    ) -> EvidenceSubmitResult:
        """Submit evidence for a requirement."""

        data = self._request_json(
            "POST",
            f"/stories/{story_id}/evidence",
            payload={
                "requirement_id": requirement_id,
                "evidence_type": evidence_type.value,
                "evidence_ref": evidence_ref,
            },
        )
        try:
            if data is None:
                return EvidenceSubmitResult(status=AreDockpointStatus.PASS)
            if not isinstance(data, dict):
                raise TypeError("ARE evidence response must be an object")
            return EvidenceSubmitResult.model_validate(data)
        except (TypeError, ValidationError) as exc:
            raise AreClientResponseError("Invalid ARE evidence response") from exc

    def check_gate(self, story_id: str) -> CoverageVerdict:
        """Check the ARE gate for a story."""

        data = self._request_json("GET", f"/stories/{story_id}/gate")
        try:
            if not isinstance(data, dict):
                raise TypeError("ARE gate response must be an object")
            return CoverageVerdict.model_validate(data)
        except (TypeError, ValidationError) as exc:
            raise AreClientResponseError("Invalid ARE gate response") from exc

    def list_evidence(self, story_id: str) -> list[AreEvidence]:
        """List submitted evidence for all requirements of a story.

        Calls ``GET /stories/{story_id}/evidence`` and returns all evidence
        items persisted for the story (FK-40 §40.5b.6).  Used to populate
        per-requirement ``evidence_paths`` in the are-evidence read-model.

        Args:
            story_id: Story identifier.

        Returns:
            List of :class:`AreEvidence` items (empty when none submitted).
        """
        data = self._request_json("GET", f"/stories/{story_id}/evidence")
        try:
            items = data
            if isinstance(data, dict):
                items = data.get("evidence") or data.get("items") or []
            if items is None:
                items = []
            if not isinstance(items, list):
                raise TypeError("ARE evidence list response must be a list")
            return [AreEvidence.model_validate(item) for item in items]
        except (TypeError, ValidationError) as exc:
            raise AreClientResponseError("Invalid ARE evidence list response") from exc

    def _request_json(
        self,
        method: str,
        path: str,
        *,
        query: dict[str, str] | None = None,
        payload: dict[str, object] | None = None,
    ) -> object:
        url = f"{self._base_url}{path}"
        if query:
            url = f"{url}?{urlencode(query)}"
        headers = {"Accept": "application/json"}
        body: bytes | None = None
        if payload is not None:
            headers["Content-Type"] = "application/json"
            body = json.dumps(payload, sort_keys=True).encode("utf-8")
        if self._auth_token:
            headers["Authorization"] = f"Bearer {self._auth_token}"

        try:
            response = self._transport.request(method, url, headers=headers, body=body)
        except AreClientError:
            raise
        except Exception as exc:  # noqa: BLE001 - transport boundary
            raise AreClientHttpError(f"ARE transport failed for {method} {url}: {exc}") from exc

        if response.status_code < 200 or response.status_code >= 300:
            raise AreClientHttpError(
                f"ARE HTTP {response.status_code} for {method} {url}"
            )
        if not response.body:
            return None
        try:
            return json.loads(response.body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise AreClientDecodeError(f"ARE response is not valid JSON for {method} {url}") from exc


def _parse_requirement_list(data: object, *, field: str) -> list[AreRequirement]:
    try:
        items = data
        if isinstance(data, dict):
            items = data.get(field)
        if not isinstance(items, list):
            raise TypeError("ARE requirement list response must be a list")
        return [AreRequirement.model_validate(item) for item in items]
    except (TypeError, ValidationError) as exc:
        raise AreClientResponseError("Invalid ARE requirement list response") from exc


__all__ = [
    "AreClient",
    "AreHttpResponse",
    "AreHttpTransport",
    "UrlLibAreHttpTransport",
]
