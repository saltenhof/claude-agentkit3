"""Thin Jenkins CI Web-API adapter (trigger + poll + artefact fetch).

This is a boundary adapter (``integrations`` = thin adapters, CLAUDE.md):
it speaks the Jenkins Remote-API over HTTP and returns transport-shaped
DTOs. It carries **no** binding/green/applicability business logic — that
lives in ``agentkit.backend.verify_system.pre_merge_runner`` (AG3-056, FK-29
§29.1a.3 / FK-33 §33.6.3).

Operations (AG3-056 §2.1.1):

* ``trigger_build`` -- ``POST job/<pipeline>/buildWithParameters`` for a
  concrete integrated-candidate ``branch``/``commit_sha``. Returns the
  queue item the build will be created from.
* ``queue_item`` -- ``GET queue/item/<id>/api/json`` to map a queue item
  to its executable build number once Jenkins has scheduled it.
* ``build_status`` -- ``GET job/<pipeline>/<number>/api/json`` for the
  build result (``SUCCESS``/``FAILURE``/...) and ``building`` flag.
* ``build_artifact`` -- ``GET job/<pipeline>/<number>/artifact/<path>``
  to fetch the run's archived ``report-task.txt`` (the Sonar analysis
  reference THIS build emitted — never a stale local ``.scannerwork/``).

Reachability, missing builds and non-2xx are surfaced as a typed
:class:`JenkinsApiError`; the *applicability* decision (declared-absent vs
configured-but-unreachable) is made by the capability, not here.
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
#: HTTP 201 Created — Jenkins returns this for an accepted build trigger.
_HTTP_CREATED = 201


class JenkinsApiError(IntegrationError):
    """Jenkins was configured but the Remote-API call could not complete.

    Raised on transport failure, non-2xx status, missing ``Location``
    header, or malformed JSON. The capability treats this as
    *configured-but-unreachable* -> fail-closed (AG3-056 §2.1.4); it is
    NEVER the deliberate-absence skip (``available == false``).
    """


@dataclass(frozen=True)
class JenkinsHttpResponse:
    """Transport-shaped result of one Jenkins Remote-API request.

    Attributes:
        status_code: HTTP status code.
        json_body: Parsed JSON body (``{}`` when the body was empty or the
            endpoint is not a JSON endpoint).
        text_body: Raw decoded text body (for non-JSON artefacts such as
            ``report-task.txt``).
        headers: Lower-cased response headers (e.g. ``location``).
    """

    status_code: int
    json_body: dict[str, Any] = field(default_factory=dict)
    text_body: str = ""
    headers: dict[str, str] = field(default_factory=dict)


class JenkinsClient:
    """Thin HTTP client over the Jenkins Remote-API.

    The token is supplied as a value (resolved by the caller from
    ``ci.token_env`` -- never inline). It is sent as HTTP Basic
    (``<user>:<token>``) per the Jenkins API-token convention.
    """

    def __init__(
        self,
        base_url: str,
        token: str,
        *,
        user: str = "",
        timeout_seconds: int = _DEFAULT_TIMEOUT_SECONDS,
    ) -> None:
        """Initialise the client.

        Args:
            base_url: Jenkins server base URL (e.g. ``http://host:8080``).
            token: Jenkins API token (resolved from the secret store/env).
            user: Optional Jenkins user the token belongs to (HTTP Basic
                username). Empty for token-only setups.
            timeout_seconds: Per-request timeout.
        """
        self._base_url = base_url.rstrip("/")
        self._token = token
        self._user = user
        self._timeout = timeout_seconds
        self._crumb_header: tuple[str, str] | None = None
        self._crumb_cookie: str | None = None
        self._crumb_checked = False

    def trigger_build(
        self, pipeline: str, *, parameters: Mapping[str, str]
    ) -> JenkinsHttpResponse:
        """Trigger a parameterised build (``buildWithParameters``).

        Args:
            pipeline: Jenkins job/pipeline name.
            parameters: Build parameters (e.g. ``branch``/``commit_sha``).

        Returns:
            The Web-API response; ``headers['location']`` carries the queue
            item URL Jenkins created for this trigger.

        Raises:
            JenkinsApiError: On any HTTP/transport failure (fail-closed).
        """
        path = f"job/{urllib.parse.quote(pipeline)}/buildWithParameters"
        response = self._post(path, dict(parameters))
        if response.status_code != _HTTP_CREATED:
            raise JenkinsApiError(
                f"buildWithParameters for {pipeline!r} returned HTTP "
                f"{response.status_code} (expected 201 Created)",
            )
        return response

    def queue_item(self, queue_id: int) -> JenkinsHttpResponse:
        """Read a queue item (``queue/item/<id>/api/json``)."""
        return self._get(f"queue/item/{queue_id}/api/json", {})

    def build_status(self, pipeline: str, build_number: int) -> JenkinsHttpResponse:
        """Read a build's status (``job/<pipeline>/<number>/api/json``)."""
        path = f"job/{urllib.parse.quote(pipeline)}/{build_number}/api/json"
        return self._get(path, {})

    def build_artifact(
        self, pipeline: str, build_number: int, artifact_path: str
    ) -> JenkinsHttpResponse:
        """Fetch a build's archived artefact as raw text.

        Args:
            pipeline: Jenkins job/pipeline name.
            build_number: The build number.
            artifact_path: Repo-relative archived artefact path (e.g.
                ``.scannerwork/report-task.txt``).

        Returns:
            The response with the artefact in ``text_body``.
        """
        quoted = "/".join(
            urllib.parse.quote(part) for part in artifact_path.split("/") if part
        )
        path = f"job/{urllib.parse.quote(pipeline)}/{build_number}/artifact/{quoted}"
        return self._get_text(path)

    def job_exists(self, pipeline: str) -> JenkinsHttpResponse:
        """Read a job's metadata (``job/<pipeline>/api/json``)."""
        return self._get(f"job/{urllib.parse.quote(pipeline)}/api/json", {})

    def whoami(self) -> JenkinsHttpResponse:
        """Read the authenticated user (``me/api/json``)."""
        return self._get("me/api/json", {})

    def _get(self, path: str, params: Mapping[str, str]) -> JenkinsHttpResponse:
        query = urllib.parse.urlencode(params)
        url = f"{self._base_url}/{path}"
        if query:
            url = f"{url}?{query}"
        return self._send(urllib.request.Request(url, method="GET"), parse_json=True)

    def _get_text(self, path: str) -> JenkinsHttpResponse:
        url = f"{self._base_url}/{path}"
        return self._send(urllib.request.Request(url, method="GET"), parse_json=False)

    def _post(self, path: str, params: Mapping[str, str]) -> JenkinsHttpResponse:
        data = urllib.parse.urlencode(params).encode("utf-8")
        url = f"{self._base_url}/{path}"
        request = urllib.request.Request(url, data=data, method="POST")
        request.add_header("Content-Type", "application/x-www-form-urlencoded")
        self._add_crumb_headers(request)
        return self._send(request, parse_json=False)

    def _add_crumb_headers(self, request: urllib.request.Request) -> None:
        """Attach Jenkins CSRF crumb evidence to POST requests when available."""
        self._ensure_crumb()
        if self._crumb_header is not None:
            name, value = self._crumb_header
            request.add_header(name, value)
        if self._crumb_cookie:
            request.add_header("Cookie", self._crumb_cookie)

    def _ensure_crumb(self) -> None:
        if self._crumb_checked:
            return
        self._crumb_checked = True
        try:
            response = self._get("crumbIssuer/api/json", {})
        except JenkinsApiError:
            return
        field = response.json_body.get("crumbRequestField")
        crumb = response.json_body.get("crumb")
        if isinstance(field, str) and field and isinstance(crumb, str) and crumb:
            self._crumb_header = (field, crumb)
        cookie = _first_cookie(response.headers.get("set-cookie", ""))
        if cookie:
            self._crumb_cookie = cookie

    def _send(
        self, request: urllib.request.Request, *, parse_json: bool
    ) -> JenkinsHttpResponse:
        credential = f"{self._user}:{self._token}"
        basic = base64.b64encode(credential.encode("utf-8")).decode()
        request.add_header("Authorization", f"Basic {basic}")
        try:
            with urllib.request.urlopen(request, timeout=self._timeout) as response:
                raw = response.read().decode("utf-8")
                status = int(response.status)
                headers = {k.lower(): v for k, v in response.headers.items()}
        except urllib.error.HTTPError as exc:  # non-2xx
            raise JenkinsApiError(
                f"Jenkins API returned HTTP {exc.code} for {request.full_url}",
                detail={"status_code": exc.code, "url": request.full_url},
            ) from exc
        except OSError as exc:
            # urllib.error.URLError and TimeoutError both derive from OSError;
            # HTTPError (a URLError subclass) is caught above so it never lands
            # here. Catching the base class keeps the fail-closed path airtight
            # without redundant subclass except-clauses.
            raise JenkinsApiError(
                f"Jenkins API unreachable for {request.full_url}: {exc}",
                detail={"url": request.full_url},
            ) from exc
        body = (
            _parse_json(raw, request.full_url) if parse_json else {}
        )
        return JenkinsHttpResponse(
            status_code=status,
            json_body=body,
            text_body=raw,
            headers=headers,
        )


def _parse_json(raw: str, url: str) -> dict[str, Any]:
    if not raw.strip():
        return {}
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise JenkinsApiError(
            f"Jenkins API returned malformed JSON for {url}",
            detail={"url": url},
        ) from exc
    if not isinstance(parsed, dict):
        raise JenkinsApiError(
            f"Jenkins API returned a non-object JSON body for {url}",
            detail={"url": url},
        )
    return parsed


def _first_cookie(raw: str) -> str:
    if not raw:
        return ""
    return raw.split(";", 1)[0].strip()


__all__ = ["JenkinsApiError", "JenkinsClient", "JenkinsHttpResponse"]
