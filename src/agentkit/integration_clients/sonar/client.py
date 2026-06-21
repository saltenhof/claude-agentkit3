"""Thin SonarQube Web-API adapter (read + reconcile-transition).

This is a boundary adapter (``integrations`` = thin adapters, CLAUDE.md):
it speaks the SonarQube Web-API over HTTP and returns transport-shaped
DTOs. It contains **no** gate/applicability/green business logic — that
lives in ``agentkit.backend.verify_system.sonarqube_gate`` (FK-33 §33.6).

Operations (FK-33 §33.6, AG3-052 §2.1.1):

* ``project_status`` -- ``GET api/qualitygates/project_status`` by
  ``analysisId``/``ceTaskId`` (never a bare ``projectKey`` live-read,
  FK-33 §33.6.3).
* ``ce_task`` -- ``GET api/ce/task`` (Compute-Engine analysis status).
* ``project_analyses_search`` -- ``GET api/project_analyses/search`` to map a
  concrete ``analysisId`` to the git ``revision`` it measured (FK-33 §33.6.3
  commit binding, authoritative source — never a project-version string).
* ``search_issues`` -- ``GET api/issues/search`` (open, non-accepted
  issues for the Overall-Code invariant).
* ``transition_issue`` / ``set_issue_tags`` -- ``Administer Issues``
  write operations used by the deterministic reconciler (scoped token).

Reachability, version and branch-plugin presence are reported as raw
HTTP outcomes; the *applicability* decision (absent vs broken) is made
by the capability, not here (AG3-052 §2.1.1).
"""

from __future__ import annotations

import base64
import json
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from agentkit.backend.exceptions import IntegrationError

if TYPE_CHECKING:
    from collections.abc import Mapping

_DEFAULT_TIMEOUT_SECONDS = 30


class SonarApiError(IntegrationError):
    """SonarQube was configured but the Web-API call could not complete.

    Raised on transport failure, non-2xx status, or malformed JSON. The
    capability treats this as *configured-but-unreachable* -> fail-closed
    (FK-33 §33.6.5); it is NEVER the deliberate-absence skip.
    """


@dataclass(frozen=True)
class SonarHttpResponse:
    """Transport-shaped result of one SonarQube Web-API GET.

    Attributes:
        status_code: HTTP status code.
        json_body: Parsed JSON body (``{}`` when the body was empty).
    """

    status_code: int
    json_body: dict[str, Any] = field(default_factory=dict)


class SonarClient:
    """Thin HTTP client over the SonarQube Web-API.

    The token is supplied as a value (resolved by the caller from
    ``sonarqube.token_env`` -- never inline). It is sent as HTTP Basic
    (``<token>:``) per the SonarQube token convention.
    """

    def __init__(
        self,
        base_url: str,
        token: str,
        *,
        timeout_seconds: int = _DEFAULT_TIMEOUT_SECONDS,
    ) -> None:
        """Initialise the client.

        Args:
            base_url: SonarQube server base URL (e.g. ``http://host:9901``).
            token: Sonar auth token (resolved from the secret store/env).
            timeout_seconds: Per-request timeout.
        """
        self._base_url = base_url.rstrip("/")
        self._token = token
        self._timeout = timeout_seconds

    def project_status(
        self,
        *,
        analysis_id: str | None = None,
        ce_task_id: str | None = None,
    ) -> SonarHttpResponse:
        """Read the quality-gate status by ``analysisId`` or ``ceTaskId``.

        Args:
            analysis_id: Analysis identifier (preferred binding key).
            ce_task_id: Compute-Engine task identifier (alternative key).

        Returns:
            The Web-API response.

        Raises:
            SonarApiError: When neither key is provided, or on any HTTP/JSON
                failure (configured-but-unreachable, fail-closed).
        """
        if not analysis_id and not ce_task_id:
            raise SonarApiError(
                "project_status requires analysis_id or ce_task_id "
                "(no bare projectKey live-read, FK-33 §33.6.3)",
            )
        params: dict[str, str] = (
            {"analysisId": analysis_id}
            if analysis_id
            else {"ceTaskId": ce_task_id or ""}
        )
        return self._get("api/qualitygates/project_status", params)

    def ce_task(self, ce_task_id: str) -> SonarHttpResponse:
        """Read a Compute-Engine task status (``api/ce/task``).

        The real response is ``{"task": {"id", "type", "componentKey",
        "status", "analysisId", ...}}``; ``status`` is one of ``PENDING`` /
        ``IN_PROGRESS`` / ``SUCCESS`` / ``FAILED`` / ``CANCELED`` and
        ``analysisId`` is present only once the task terminated successfully.
        The capability resolves the analysisId from this terminal task — the
        scanner ``report-task.txt`` carries only ``ceTaskId`` (FK-33 §33.6.3).
        """
        return self._get("api/ce/task", {"id": ce_task_id})

    def qualitygates_get_by_project(self, project: str) -> SonarHttpResponse:
        """Read the quality gate a project is bound to.

        ``GET api/qualitygates/get_by_project`` -> ``{"qualityGate": {"id",
        "name", "default"}}``. Used (with :meth:`qualitygates_show`) to compute
        the deterministic quality-gate integrity hash (FK-33 §33.6.3).
        """
        return self._get("api/qualitygates/get_by_project", {"project": project})

    def qualitygates_show(self, name: str) -> SonarHttpResponse:
        """Read a quality gate's definition by name.

        ``GET api/qualitygates/show`` -> ``{"id", "name", "conditions":
        [{"id", "metric", "op", "error"}], ...}``. The conditions are the
        authoritative material for the quality-gate integrity hash.
        """
        return self._get("api/qualitygates/show", {"name": name})

    def qualityprofiles_search(self, project: str) -> SonarHttpResponse:
        """List the quality profiles a project actively uses.

        ``GET api/qualityprofiles/search?project=<key>`` -> ``{"profiles":
        [{"key", "name", "language", "rulesUpdatedAt", "lastUsed", ...}]}``.
        Authoritative material for the quality-profile integrity hash.
        """
        return self._get("api/qualityprofiles/search", {"project": project})

    def settings_values(
        self, *, component: str, keys: tuple[str, ...] = ()
    ) -> SonarHttpResponse:
        """Read a component's settings values.

        ``GET api/settings/values?component=<key>[&keys=...]`` -> ``{"settings":
        [{"key", "value" | "values" | "fieldValues", "inherited", ...}]}``.
        Authoritative material for the analysis-scope integrity hash.

        Args:
            component: The Sonar component/project key.
            keys: Optional explicit setting keys to scope the read to.
        """
        params: dict[str, str] = {"component": component}
        if keys:
            params["keys"] = ",".join(keys)
        return self._get("api/settings/values", params)

    def project_analyses_search(
        self, project: str, *, branch: str | None = None
    ) -> SonarHttpResponse:
        """List a project's analyses (``GET api/project_analyses/search``).

        Each entry carries the analysis ``key`` and the git ``revision`` the
        analysis was computed on. This is the authoritative source for the
        commit a concrete ``analysisId`` measured (FK-33 §33.6.3): the caller
        matches the triggered run's ``analysisId`` against an entry and reads
        its ``revision`` — never a project-version string or a local
        ``git rev-parse HEAD``.

        Args:
            project: The Sonar project/component key.
            branch: The Community-Branch-Plugin branch to scope to.

        Returns:
            The Web-API response (``analyses`` array of ``{key, revision, ...}``).
        """
        params: dict[str, str] = {"project": project}
        if branch:
            params["branch"] = branch
        return self._get("api/project_analyses/search", params)

    def search_issues(self, params: Mapping[str, str]) -> SonarHttpResponse:
        """Search issues (``api/issues/search``) with the given query params."""
        return self._get("api/issues/search", dict(params))

    def installed_plugins(self) -> SonarHttpResponse:
        """List installed plugins (``api/plugins/installed``)."""
        return self._get("api/plugins/installed", {})

    def system_status(self) -> SonarHttpResponse:
        """Read server reachability/version (``api/system/status``)."""
        return self._get("api/system/status", {})

    def transition_issue(self, issue_key: str, transition: str) -> SonarHttpResponse:
        """Apply an issue transition (``Administer Issues``, scoped token)."""
        return self._post(
            "api/issues/do_transition",
            {"issue": issue_key, "transition": transition},
        )

    def set_issue_tags(self, issue_key: str, tags: str) -> SonarHttpResponse:
        """Set issue tags (``Administer Issues``, scoped token)."""
        return self._post("api/issues/set_tags", {"issue": issue_key, "tags": tags})

    def create_project(self, project_key: str, name: str) -> SonarHttpResponse:
        """Create a project (``POST api/projects/create``, scoped token).

        Used by the CP 10d branch-plugin conformance self-test to provision
        the throwaway mini-project (FK-50 §50.3 CP 10d.2).
        """
        return self._post(
            "api/projects/create", {"project": project_key, "name": name}
        )

    def delete_project(self, project_key: str) -> SonarHttpResponse:
        """Delete a project (``POST api/projects/delete``, scoped token)."""
        return self._post("api/projects/delete", {"project": project_key})

    def project_branches(self, project_key: str) -> SonarHttpResponse:
        """List a project's analysed branches (``GET api/project_branches/list``)."""
        return self._get("api/project_branches/list", {"project": project_key})

    def _get(self, path: str, params: Mapping[str, str]) -> SonarHttpResponse:
        query = urllib.parse.urlencode(params)
        url = f"{self._base_url}/{path}"
        if query:
            url = f"{url}?{query}"
        return self._send(urllib.request.Request(url, method="GET"))

    def _post(self, path: str, params: Mapping[str, str]) -> SonarHttpResponse:
        data = urllib.parse.urlencode(params).encode("utf-8")
        url = f"{self._base_url}/{path}"
        request = urllib.request.Request(url, data=data, method="POST")
        request.add_header("Content-Type", "application/x-www-form-urlencoded")
        return self._send(request)

    def _send(self, request: urllib.request.Request) -> SonarHttpResponse:
        basic = base64.b64encode(f"{self._token}:".encode()).decode()
        request.add_header("Authorization", f"Basic {basic}")
        try:
            with urllib.request.urlopen(request, timeout=self._timeout) as response:
                raw = response.read().decode("utf-8")
                status = int(response.status)
        except urllib.error.HTTPError as exc:  # non-2xx
            raise SonarApiError(
                f"SonarQube API returned HTTP {exc.code} for {request.full_url}",
                detail={"status_code": exc.code, "url": request.full_url},
            ) from exc
        except OSError as exc:
            # urllib.error.URLError and TimeoutError both derive from OSError
            # (verified hierarchy); catching the base class is identical in
            # behaviour and avoids S5713 redundant-subclass except clauses.
            # HTTPError (a URLError subclass) is caught by the prior block, so
            # it never reaches here — the fail-closed path is unchanged.
            raise SonarApiError(
                f"SonarQube API unreachable for {request.full_url}: {exc}",
                detail={"url": request.full_url},
            ) from exc
        return SonarHttpResponse(status_code=status, json_body=_parse_json(raw, request.full_url))


def _parse_json(raw: str, url: str) -> dict[str, Any]:
    if not raw.strip():
        return {}
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise SonarApiError(
            f"SonarQube API returned malformed JSON for {url}",
            detail={"url": url},
        ) from exc
    if not isinstance(parsed, dict):
        raise SonarApiError(
            f"SonarQube API returned a non-object JSON body for {url}",
            detail={"url": url},
        )
    return parsed


__all__ = ["SonarApiError", "SonarClient", "SonarHttpResponse"]
