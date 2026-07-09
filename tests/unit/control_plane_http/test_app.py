"""Unit tests for control_plane_http.app (AG3-090).

Covers:
  - AC1: compat re-export resolves to same class as new namespace owner
  - AC2: project-scoped URL routing for stories, dashboard, story-runs, closure
  - AC2: legacy /v1/stories... bare paths return 404 (no implicit bypass)
  - AC3: tenant-scope middleware integration (unknown project -> 404, archived -> 403)
  - AC3: story mutations through project-scoped path blocked by archived-project scope
  - AC7: X-Correlation-Id and typed ApiErrorResponse on errors
  - AC8: SSE path (/v1/projects/{key}/events) passes through unmodified
"""

from __future__ import annotations

import json
import re
from http import HTTPStatus
from typing import TYPE_CHECKING

import pytest

from agentkit.backend.auth.middleware import AuthMiddleware
from agentkit.backend.auth.tokens import issue_project_api_token

# AC1: compat re-export must resolve to the SAME class
from agentkit.backend.control_plane.http import ControlPlaneApplication as CompatCPA
from agentkit.backend.control_plane.http import HttpResponse as CompatHttpResponse

# AC1: canonical namespace is owner
from agentkit.backend.control_plane_http.app import (
    ControlPlaneApplication,
    ControlPlaneApplicationRoutes,
    HttpResponse,
)
from agentkit.backend.telemetry.http.routes import TelemetryRouteResponse

if TYPE_CHECKING:
    from agentkit.backend.auth.entities import ProjectApiToken
    from agentkit.backend.control_plane.models import TakeoverChallengeEchoRequest

# ---------------------------------------------------------------------------
# AC1 — compat re-export identity
# ---------------------------------------------------------------------------


def test_compat_reexport_is_same_class() -> None:
    """control_plane.http is a compat re-export; the class must be identical."""
    assert ControlPlaneApplication is CompatCPA
    assert HttpResponse is CompatHttpResponse


# ---------------------------------------------------------------------------
# Fakes / stubs
# ---------------------------------------------------------------------------


class _NoopTenantScope:
    """Passthrough stub: every project is valid, no project archived."""

    def validate(self, *, method: str, route_path: str, correlation_id: str) -> None:
        return None


class _RejectingTenantScope:
    """Always rejects as unknown project (404)."""

    def validate(
        self, *, method: str, route_path: str, correlation_id: str
    ) -> HttpResponse:
        body = json.dumps({
            "error_code": "project_not_found",
            "error": "Project not found",
            "correlation_id": correlation_id,
        }).encode()
        return HttpResponse(
            status_code=int(HTTPStatus.NOT_FOUND),
            body=body,
            headers=(("X-Correlation-Id", correlation_id),),
        )


class _ArchivedTenantScope:
    """Rejects mutations (archived project -> 403); passes GET."""

    def validate(
        self, *, method: str, route_path: str, correlation_id: str
    ) -> HttpResponse | None:
        mutation_methods = {"POST", "PUT", "PATCH", "DELETE"}
        if method in mutation_methods:
            body = json.dumps({
                "error_code": "forbidden",
                "error": "Project is archived; mutations are not allowed",
                "correlation_id": correlation_id,
            }).encode()
            return HttpResponse(
                status_code=int(HTTPStatus.FORBIDDEN),
                body=body,
                headers=(("X-Correlation-Id", correlation_id),),
            )
        return None


class _FakeStoryContextRoutes:
    """Minimal stub for StoryContextRoutes used in routing tests."""

    def handle_get(
        self,
        route_path: str,
        correlation_id: str,
        query: dict[str, list[str]] | None = None,
    ) -> None:
        return None

    def handle_post(
        self, route_path: str, payload: object, correlation_id: str
    ) -> None:
        return None

    def handle_patch(
        self, route_path: str, payload: object, correlation_id: str
    ) -> None:
        return None

    def handle_put(
        self, route_path: str, payload: object, correlation_id: str
    ) -> None:
        return None


class _FakeProjectRoutes:
    """Minimal stub for ProjectManagementRoutes."""

    def handle_get(
        self,
        route_path: str,
        query: dict[str, list[str]],
        correlation_id: str,
    ) -> None:
        return None

    def handle_post(
        self, route_path: str, payload: object, correlation_id: str
    ) -> None:
        return None

    def handle_patch(
        self, route_path: str, payload: object, correlation_id: str
    ) -> None:
        return None

    def handle_put(
        self, route_path: str, payload: object, correlation_id: str
    ) -> None:
        return None


class _FakeConceptRoutes:
    def handle_get(
        self,
        route_path: str,
        query: dict[str, list[str]],
        correlation_id: str,
    ) -> None:
        return None


class _FakeHubRoutes:
    def handle_get(
        self, route_path: str, query: dict[str, list[str]], correlation_id: str
    ) -> None:
        return None

    def handle_post(
        self, route_path: str, payload: object, correlation_id: str
    ) -> None:
        return None


class _FakePlanningRoutes:
    def handle_get(self, route_path: str, correlation_id: str) -> None:
        return None

    def handle_post(
        self, route_path: str, payload: object, correlation_id: str
    ) -> None:
        return None

    def handle_put(
        self, route_path: str, payload: object, correlation_id: str
    ) -> None:
        return None

    def handle_delete(self, route_path: str, correlation_id: str) -> None:
        return None


class _FakeTelemetryRoutes:
    """Stub that claims /v1/projects/{key}/events but returns nothing else."""

    def handle_get(
        self,
        route_path: str,
        query: dict[str, list[str]],
        correlation_id: str,
    ) -> TelemetryRouteResponse | None:
        import re

        m = re.match(r"^/v1/projects/(?P<project_key>[^/]+)/events$", route_path)
        if m is None:
            return None
        return TelemetryRouteResponse(
            status_code=200,
            body=b"",
            headers=(("Content-Type", "text/event-stream"),),
        )


class _FakeAuthRoutes:
    def handle_get(self, route_path: str, correlation_id: str) -> None:
        return None

    def handle_post(
        self,
        route_path: str,
        payload: object,
        correlation_id: str,
        request_headers: object = None,
    ) -> None:
        return None

    def handle_delete(
        self, route_path: str, query: dict[str, list[str]], correlation_id: str
    ) -> None:
        return None


class _FakeReadModelRoutes:
    """Stub for ReadModelRoutes used in unit routing tests.

    Returns a minimal 200 response for every AG3-091 read-model path,
    using the same JSON shape the real routes produce so that assertions
    on ``body["story_id"]`` work without needing a real project repo.
    """

    _ARE_EVIDENCE_PATH = re.compile(
        r"^/v1/projects/(?P<project_key>[^/]+)/coverage/stories/(?P<story_id>[^/]+)/are-evidence$"
    )
    _ACCEPTANCE_PATH = re.compile(
        r"^/v1/projects/(?P<project_key>[^/]+)/coverage/stories/(?P<story_id>[^/]+)/acceptance$"
    )
    _FLOW_PATH = re.compile(
        r"^/v1/projects/(?P<project_key>[^/]+)/stories/(?P<story_id>[^/]+)/flow$"
    )
    _COUNTERS_PATH = re.compile(
        r"^/v1/projects/(?P<project_key>[^/]+)/stories/counters$"
    )
    _MODE_LOCK_PATH = re.compile(
        r"^/v1/projects/(?P<project_key>[^/]+)/mode-lock$"
    )
    _LIMITS_PATH = re.compile(
        r"^/v1/projects/(?P<project_key>[^/]+)/execution-input/limits$"
    )

    def handle_get(
        self,
        route_path: str,
        _query: dict[str, list[str]],
        correlation_id: str,
    ) -> object:
        from agentkit.backend.control_plane.models import bc_json_response

        m = self._ARE_EVIDENCE_PATH.match(route_path)
        if m:
            return bc_json_response(
                HTTPStatus.OK,
                {
                    "story_are_evidence": {
                        "story_id": m.group("story_id"),
                        "project_key": m.group("project_key"),
                        "linked_requirements": [],
                    },
                },
                correlation_id=correlation_id,
            )
        m = self._ACCEPTANCE_PATH.match(route_path)
        if m:
            return bc_json_response(
                HTTPStatus.OK,
                {
                    "story_coverage_acceptance": {
                        "story_id": m.group("story_id"),
                        "project_key": m.group("project_key"),
                        "acceptance_criteria": [],
                        "linked_requirements": [],
                    },
                },
                correlation_id=correlation_id,
            )
        m = self._FLOW_PATH.match(route_path)
        if m:
            return bc_json_response(
                HTTPStatus.OK,
                {"story_flow_snapshot": {"story_id": m.group("story_id"), "mode": "standard", "phases": []}},
                correlation_id=correlation_id,
            )
        m = self._COUNTERS_PATH.match(route_path)
        if m:
            return bc_json_response(
                HTTPStatus.OK,
                {"story_counters": {"project_key": m.group("project_key")}},
                correlation_id=correlation_id,
            )
        m = self._MODE_LOCK_PATH.match(route_path)
        if m:
            return bc_json_response(
                HTTPStatus.OK,
                {"mode_lock": {"project_key": m.group("project_key")}},
                correlation_id=correlation_id,
            )
        m = self._LIMITS_PATH.match(route_path)
        if m:
            return bc_json_response(
                HTTPStatus.OK,
                {"execution_limits": {"project_key": m.group("project_key")}},
                correlation_id=correlation_id,
            )
        return None

    def handle_post(
        self,
        route_path: str,
        _payload: object,
        correlation_id: str,
    ) -> None:
        return None

    def handle_put(
        self,
        route_path: str,
        _payload: object,
        correlation_id: str,
    ) -> None:
        return None

    def handle_patch(
        self,
        route_path: str,
        _payload: object,
        correlation_id: str,
    ) -> None:
        return None

    def handle_delete(
        self,
        route_path: str,
        correlation_id: str,
    ) -> None:
        return None


class _InMemoryTokenRepository:
    def __init__(self) -> None:
        self.tokens: dict[str, ProjectApiToken] = {}

    def get(self, token_id: str) -> ProjectApiToken | None:
        return self.tokens.get(token_id)

    def get_by_hash(self, token_hash: str) -> ProjectApiToken | None:
        for token in self.tokens.values():
            if token.token_hash == token_hash:
                return token
        return None

    def list_for_project(self, project_key: str) -> list[ProjectApiToken]:
        return [token for token in self.tokens.values() if token.project_key == project_key]

    def save(self, token: ProjectApiToken) -> None:
        self.tokens[token.token_id] = token

    def revoke(self, project_key: str, token_id: str) -> None:
        del project_key
        del self.tokens[token_id]


class _FakeTakeoverRuntime:
    def __init__(self) -> None:
        self.confirm_calls: list[TakeoverChallengeEchoRequest] = []

    def confirm_ownership_takeover(self, *, request: TakeoverChallengeEchoRequest) -> object:
        self.confirm_calls.append(request)
        raise AssertionError("forged takeover confirm reached runtime")


def _make_app(
    *,
    tenant_scope: object | None = None,
    telemetry_routes: object | None = None,
    read_model_routes: object | None = None,
) -> ControlPlaneApplication:
    """Build a minimal ControlPlaneApplication wired with all fakes."""
    from agentkit.backend.kpi_analytics.http.routes import KpiAnalyticsRoutes

    return ControlPlaneApplication(
        routes=ControlPlaneApplicationRoutes(
            project_routes=_FakeProjectRoutes(),  # type: ignore[arg-type]
            story_routes=_FakeStoryContextRoutes(),  # type: ignore[arg-type]
            concept_routes=_FakeConceptRoutes(),  # type: ignore[arg-type]
            hub_routes=_FakeHubRoutes(),  # type: ignore[arg-type]
            planning_routes=_FakePlanningRoutes(),  # type: ignore[arg-type]
            telemetry_routes=telemetry_routes or _FakeTelemetryRoutes(),  # type: ignore[arg-type]
            auth_routes=_FakeAuthRoutes(),  # type: ignore[arg-type]
            kpi_analytics_routes=KpiAnalyticsRoutes(),  # no kpi_analytics → 503 on dim routes
            read_model_routes=read_model_routes or _FakeReadModelRoutes(),  # type: ignore[arg-type]
        ),
        tenant_scope_middleware=tenant_scope or _NoopTenantScope(),  # type: ignore[arg-type]
    )


def _json_body(response: HttpResponse) -> object:
    return json.loads(response.body)


def _header(response: HttpResponse, name: str) -> str | None:
    for k, v in response.headers:
        if k.lower() == name.lower():
            return v
    return None


def test_token_agent_cannot_forge_human_takeover_confirm_and_writes_nothing() -> None:
    tokens = _InMemoryTokenRepository()
    issued = issue_project_api_token(
        project_key="tenant-a",
        label="agent",
        repository=tokens,
    )
    runtime = _FakeTakeoverRuntime()
    app = ControlPlaneApplication(
        routes=ControlPlaneApplicationRoutes(
            project_routes=_FakeProjectRoutes(),  # type: ignore[arg-type]
            story_routes=_FakeStoryContextRoutes(),  # type: ignore[arg-type]
            concept_routes=_FakeConceptRoutes(),  # type: ignore[arg-type]
            hub_routes=_FakeHubRoutes(),  # type: ignore[arg-type]
            planning_routes=_FakePlanningRoutes(),  # type: ignore[arg-type]
            telemetry_routes=_FakeTelemetryRoutes(),  # type: ignore[arg-type]
            auth_routes=_FakeAuthRoutes(),  # type: ignore[arg-type]
            read_model_routes=_FakeReadModelRoutes(),  # type: ignore[arg-type]
        ),
        runtime_service=runtime,  # type: ignore[arg-type]
        auth_middleware=AuthMiddleware(token_repository=tokens),
        tenant_scope_middleware=_NoopTenantScope(),  # type: ignore[arg-type]
    )
    response = app.handle_request(
        method="POST",
        path="/v1/project-edge/story-runs/run-100/ownership/takeover-confirm",
        body=json.dumps(
            {
                "project_key": "tenant-a",
                "story_id": "AG3-100",
                "session_id": "sess-agent",
                "principal_type": "human_cli",
                "op_id": "op-forged-confirm",
                "reason": "forged",
                "worktree_roots": ["T:/worktrees/ag3-100"],
                "challenge_echo": {
                    "challenge_id": "takeover-op",
                    "owner_session_id": "sess-001",
                    "ownership_epoch": 1,
                    "binding_version": "1",
                },
            }
        ).encode(),
        request_headers={
            "Authorization": f"Bearer {issued.plaintext_token}",
            "X-Project-Key": "tenant-a",
            "X-Correlation-Id": "req-forged-confirm",
        },
    )

    assert response.status_code == HTTPStatus.FORBIDDEN
    assert _json_body(response)["error_code"] == "agent_confirm_forbidden"  # type: ignore[index]
    assert runtime.confirm_calls == []


# ---------------------------------------------------------------------------
# AC7 — X-Correlation-Id and error_code on errors
# ---------------------------------------------------------------------------


def test_404_carries_correlation_id_and_error_code() -> None:
    app = _make_app()
    response = app.handle_request(
        method="GET",
        path="/v1/projects/myproj/unknown-endpoint-xyz",
        body=b"",
    )
    assert response.status_code == HTTPStatus.NOT_FOUND
    body = _json_body(response)
    assert isinstance(body, dict)
    assert body["error_code"] == "not_found"
    assert "correlation_id" in body
    assert _header(response, "X-Correlation-Id") is not None


def test_correlation_id_reflected_from_request_header() -> None:
    app = _make_app()
    response = app.handle_request(
        method="GET",
        path="/v1/projects/myproj/kpi/design-tokens",
        body=b"",
        request_headers={"X-Correlation-Id": "custom-corr-99"},
    )
    assert _header(response, "X-Correlation-Id") == "custom-corr-99"


def test_correlation_id_adopted_case_insensitively_on_success_and_error() -> None:
    """Codex R2 #2: the server adopts the client's id regardless of header casing.

    The official client sends ``X-Correlation-Id`` but ``urllib`` (and proxies)
    may normalize the casing on the wire (e.g. ``x-correlation-id``). HTTP header
    names are case-insensitive (RFC 9110 §5.1), so the server's lookup must adopt
    the client's id — not mint a divergent ``req-<uuid>`` — on BOTH a success and
    an error response.
    """
    app = _make_app()
    # Lower-cased header name, as it can arrive after urllib normalization.
    success = app.handle_request(
        method="GET",
        path="/v1/projects/myproj/kpi/design-tokens",
        body=b"",
        request_headers={"x-correlation-id": "corr-ci-1"},
    )
    assert _header(success, "X-Correlation-Id") == "corr-ci-1"

    error = app.handle_request(
        method="GET",
        path="/v1/projects/myproj/unknown-endpoint-xyz",
        body=b"",
        request_headers={"x-correlation-id": "corr-ci-1"},
    )
    assert error.status_code == HTTPStatus.NOT_FOUND
    # The SAME id is echoed on the error response (header AND body), not a req-*.
    assert _header(error, "X-Correlation-Id") == "corr-ci-1"
    body = _json_body(error)
    assert isinstance(body, dict)
    assert body["correlation_id"] == "corr-ci-1"


# ---------------------------------------------------------------------------
# AC2 — project-scoped URL routing
# ---------------------------------------------------------------------------


def test_get_project_scoped_kpi_returns_503_without_analytics() -> None:
    """KPI dimension routes return 503 when kpi_analytics is not configured (fail-closed)."""
    app = _make_app()
    response = app.handle_request(
        method="GET",
        path="/v1/projects/myproj/kpi",
        body=b"",
    )
    # Without kpi_analytics wired, the dimension endpoint returns 503 (fail-closed).
    assert response.status_code == HTTPStatus.SERVICE_UNAVAILABLE


def test_get_project_scoped_kpi_dimension_returns_503_without_analytics() -> None:
    """KPI dimension routes return 503 when kpi_analytics is not configured (fail-closed)."""
    app = _make_app()
    response = app.handle_request(
        method="GET",
        path="/v1/projects/myproj/kpi/stories",
        body=b"",
    )
    # Without kpi_analytics wired, the dimension endpoint returns 503 (fail-closed).
    assert response.status_code == HTTPStatus.SERVICE_UNAVAILABLE


def test_get_project_scoped_kpi_design_tokens_returns_200() -> None:
    """Design-token route always available regardless of kpi_analytics wiring."""
    app = _make_app()
    response = app.handle_request(
        method="GET",
        path="/v1/projects/myproj/kpi/design-tokens",
        body=b"",
    )
    assert response.status_code == HTTPStatus.OK


def test_get_project_scoped_coverage_are_evidence_returns_200() -> None:
    """GET /v1/projects/{key}/coverage/stories/{story_id}/are-evidence (FK-40)."""
    app = _make_app()
    response = app.handle_request(
        method="GET",
        path="/v1/projects/myproj/coverage/stories/AG3-001/are-evidence",
        body=b"",
    )
    assert response.status_code == HTTPStatus.OK
    body = _json_body(response)
    assert isinstance(body, dict)
    assert isinstance(body["story_are_evidence"], dict)
    assert body["story_are_evidence"]["story_id"] == "AG3-001"


# ---------------------------------------------------------------------------
# ERROR 1 (R5) — read-only 405 fires BEFORE JSON body decode (dispatch order)
# ---------------------------------------------------------------------------


class _Real405ReadModelRoutes:
    """Real-matcher read-model stub: returns 405 for read-only mutation verbs.

    Reuses the genuine ``ReadModelRoutes`` 405-matcher
    (``_method_not_allowed_if_matches``) so the unit test proves the productive
    dispatch reorder (405 BEFORE ``_decode_json_body``) without a real repo.
    Non-read-only paths return ``None`` (the dispatcher proceeds to decode).
    """

    def __init__(self) -> None:
        from agentkit.backend.project_management.read_model_routes import ReadModelRoutes

        # Build a bare instance only to access the real 405 matcher; the
        # repo fields are never touched on the 405 path (it runs before any
        # repo access).
        self._matcher = ReadModelRoutes.__new__(ReadModelRoutes)

    def _match(self, route_path: str, correlation_id: str) -> object:
        from agentkit.backend.project_management.read_model_routes import ReadModelRoutes

        return ReadModelRoutes._method_not_allowed_if_matches(
            self._matcher, route_path, correlation_id
        )

    def handle_get(
        self, route_path: str, _query: dict[str, list[str]], correlation_id: str
    ) -> None:
        return None

    def handle_post(
        self, route_path: str, _payload: object, correlation_id: str
    ) -> object:
        return self._match(route_path, correlation_id)

    def handle_put(
        self, route_path: str, _payload: object, correlation_id: str
    ) -> object:
        return self._match(route_path, correlation_id)

    def handle_patch(
        self, route_path: str, _payload: object, correlation_id: str
    ) -> object:
        return self._match(route_path, correlation_id)

    def handle_delete(self, route_path: str, correlation_id: str) -> object:
        return self._match(route_path, correlation_id)


def _assert_read_only_405(response: HttpResponse, *, method: str) -> None:
    assert response.status_code == HTTPStatus.METHOD_NOT_ALLOWED, (
        f"{method} on a read-only path must be 405 regardless of body, "
        f"got {response.status_code}"
    )
    body = _json_body(response)
    assert isinstance(body, dict)
    assert body["error_code"] == "method_not_allowed", (
        f"{method} must NOT degrade to invalid_json for an empty/non-JSON "
        f"body; got error_code={body.get('error_code')!r}"
    )
    allow = _header(response, "Allow")
    assert allow is not None and "GET" in allow


@pytest.mark.parametrize("method", ["POST", "PUT", "PATCH"])
@pytest.mark.parametrize("body", [b"", b"not json"])
def test_read_only_mutation_returns_405_for_empty_or_non_json_body(
    method: str, body: bytes
) -> None:
    """ERROR 1: read-only 405 fires before body decode (empty AND non-JSON body).

    The previous dispatch decoded the body first, so an empty/non-JSON body on
    a read-only path degraded to ``400 invalid_json`` instead of ``405``.  The
    fix runs the read-only 405 matcher BEFORE ``_decode_json_body``.
    """
    app = _make_app(read_model_routes=_Real405ReadModelRoutes())
    response = app.handle_request(
        method=method,
        path="/v1/projects/myproj/execution-input/limits",
        body=body,
    )
    _assert_read_only_405(response, method=method)


@pytest.mark.parametrize("method", ["POST", "PUT", "PATCH"])
@pytest.mark.parametrize("body", [b"", b"not json"])
def test_read_only_coverage_mutation_returns_405_for_empty_or_non_json_body(
    method: str, body: bytes
) -> None:
    """ERROR 1: same guarantee on a coverage read-only endpoint."""
    app = _make_app(read_model_routes=_Real405ReadModelRoutes())
    response = app.handle_request(
        method=method,
        path="/v1/projects/myproj/coverage/stories/AG3-001/acceptance",
        body=body,
    )
    _assert_read_only_405(response, method=method)


def test_read_only_delete_returns_405_before_any_handler() -> None:
    """DELETE on a read-only path -> 405 (no body decode; DELETE has no body)."""
    app = _make_app(read_model_routes=_Real405ReadModelRoutes())
    response = app.handle_request(
        method="DELETE",
        path="/v1/projects/myproj/execution-input/limits",
        body=b"",
    )
    _assert_read_only_405(response, method="DELETE")


@pytest.mark.parametrize("body", [b"", b"not json"])
def test_non_read_only_mutation_still_decodes_body(body: bytes) -> None:
    """Other BCs' mutation endpoints are unaffected: empty/non-JSON body -> 400.

    A NON-read-only mutation path must still decode the body and surface
    ``400 invalid_json`` for an empty/non-JSON body (no read-only short-circuit).
    """
    app = _make_app(read_model_routes=_Real405ReadModelRoutes())
    response = app.handle_request(
        method="POST",
        path="/v1/telemetry/events",
        body=body,
    )
    assert response.status_code == HTTPStatus.BAD_REQUEST, (
        "non-read-only mutation must still decode the body and 400 on bad JSON"
    )
    decoded = _json_body(response)
    assert isinstance(decoded, dict)
    assert decoded["error_code"] == "invalid_json"


# ---------------------------------------------------------------------------
# AC3 — tenant-scope middleware: unknown project -> 404
# ---------------------------------------------------------------------------


def test_unknown_project_returns_404() -> None:
    """AC3: unknown project_key on a project-scoped path -> 404."""
    app = _make_app(tenant_scope=_RejectingTenantScope())
    response = app.handle_request(
        method="GET",
        path="/v1/projects/no-such-project/stories",
        body=b"",
    )
    assert response.status_code == HTTPStatus.NOT_FOUND
    body = _json_body(response)
    assert isinstance(body, dict)
    assert body["error_code"] == "project_not_found"


def test_archived_project_mutation_returns_403() -> None:
    """AC3: archived project + mutation method -> 403/forbidden."""
    app = _make_app(tenant_scope=_ArchivedTenantScope())
    response = app.handle_request(
        method="POST",
        path="/v1/projects/archived-proj/stories",
        body=json.dumps({}).encode(),
    )
    assert response.status_code == HTTPStatus.FORBIDDEN
    body = _json_body(response)
    assert isinstance(body, dict)
    assert body["error_code"] == "forbidden"


def test_archived_project_get_passes_through() -> None:
    """AC3: archived project + GET -> middleware passes; route handles it."""
    app = _make_app(tenant_scope=_ArchivedTenantScope())
    response = app.handle_request(
        method="GET",
        path="/v1/projects/archived-proj/kpi/design-tokens",
        body=b"",
    )
    # Middleware passes (GET), route returns 200 (kpi design-tokens always available)
    assert response.status_code == HTTPStatus.OK


# ---------------------------------------------------------------------------
# AC3 — non-project-scoped paths bypass tenant-scope
# ---------------------------------------------------------------------------


def test_healthz_bypasses_tenant_scope() -> None:
    """Non-project path /healthz is not subject to tenant-scope."""
    app = _make_app(tenant_scope=_RejectingTenantScope())
    response = app.handle_request(method="GET", path="/healthz", body=b"")
    assert response.status_code == HTTPStatus.OK


# ---------------------------------------------------------------------------
# AC8 — SSE compat: /v1/projects/{key}/events must pass unchanged
# ---------------------------------------------------------------------------


def test_sse_path_passes_tenant_scope_and_reaches_telemetry_routes() -> None:
    """AC8: SSE /v1/projects/{key}/events goes through tenant-scope and hits TelemetryRoutes."""
    app = _make_app(tenant_scope=_NoopTenantScope())
    response = app.handle_request(
        method="GET",
        path="/v1/projects/myproj/events",
        body=b"",
    )
    # TelemetryRoutes stub returns 200 with Content-Type: text/event-stream
    assert response.status_code == HTTPStatus.OK
    assert _header(response, "Content-Type") == "text/event-stream"


def test_sse_path_with_unknown_project_returns_404() -> None:
    """AC8: unknown project_key for SSE path -> 404 from tenant-scope."""
    app = _make_app(tenant_scope=_RejectingTenantScope())
    response = app.handle_request(
        method="GET",
        path="/v1/projects/no-such/events",
        body=b"",
    )
    assert response.status_code == HTTPStatus.NOT_FOUND
    body = _json_body(response)
    assert isinstance(body, dict)
    assert body["error_code"] == "project_not_found"


# ---------------------------------------------------------------------------
# Helpers for story-routing tests that need a real StoryContextRoutes
# ---------------------------------------------------------------------------


def _make_story_routes() -> object:
    """Build a real StoryContextRoutes backed by in-memory repos."""
    from agentkit.backend.project_management.entities import Project, ProjectConfiguration
    from agentkit.backend.state_backend.store.inflight_idempotency_guard import (
        InMemoryInflightIdempotencyGuard,
    )
    from agentkit.backend.story_context_manager.http.routes import StoryContextRoutes
    from agentkit.backend.story_context_manager.service import StoryService
    from agentkit.backend.story_context_manager.story_repository import InMemoryStoryRepository

    class _InMemProjectRepo:
        def __init__(self) -> None:
            self._p: dict[str, Project] = {
                "proj-a": Project(
                    key="proj-a",
                    name="Proj A",
                    story_id_prefix="PA",
                    configuration=ProjectConfiguration(
                        repo_url="",
                        default_branch="main",
                        default_worker_count=1,
                        repositories=["proj-a"],
                    ),
                ),
            }

        def get(self, key: str) -> Project | None:
            return self._p.get(key)

        def list(self, *, include_archived: bool = False) -> list[Project]:
            return list(self._p.values())

        def save(self, project: Project) -> None:
            self._p[project.key] = project

    svc = StoryService(
        story_repository=InMemoryStoryRepository(),
        project_repository=_InMemProjectRepo(),  # type: ignore[arg-type]
        idempotency_guard=InMemoryInflightIdempotencyGuard(),
    )
    return StoryContextRoutes(story_service=svc)


def _make_app_with_real_story_routes(
    *,
    tenant_scope: object | None = None,
) -> ControlPlaneApplication:
    """ControlPlaneApplication with real StoryContextRoutes for integration checks."""
    from agentkit.backend.kpi_analytics.http.routes import KpiAnalyticsRoutes

    return ControlPlaneApplication(
        routes=ControlPlaneApplicationRoutes(
            project_routes=_FakeProjectRoutes(),  # type: ignore[arg-type]
            story_routes=_make_story_routes(),  # type: ignore[arg-type]
            concept_routes=_FakeConceptRoutes(),  # type: ignore[arg-type]
            hub_routes=_FakeHubRoutes(),  # type: ignore[arg-type]
            planning_routes=_FakePlanningRoutes(),  # type: ignore[arg-type]
            telemetry_routes=_FakeTelemetryRoutes(),  # type: ignore[arg-type]
            auth_routes=_FakeAuthRoutes(),  # type: ignore[arg-type]
            kpi_analytics_routes=KpiAnalyticsRoutes(),  # no kpi_analytics → 503 on dim routes
            read_model_routes=_FakeReadModelRoutes(),  # type: ignore[arg-type]
        ),
        tenant_scope_middleware=tenant_scope or _NoopTenantScope(),  # type: ignore[arg-type]
    )


def _create_story_via_app(app: ControlPlaneApplication, project_key: str = "proj-a") -> str:
    """Create a story via the project-scoped POST and return its story_id."""
    resp = app.handle_request(
        method="POST",
        path=f"/v1/projects/{project_key}/stories",
        body=json.dumps({
            "op_id": "op-setup-001",
            "project_key": project_key,
            "title": "Test story",
            "type": "implementation",
            "repos": [project_key],
            # AG3-068 (FK-21 §21.4/§21.12): the agent-facing create path is
            # fail-closed without typed reconciliation evidence. This setup helper
            # carries a minimal VALID evidence block to get past the gate (there
            # is no in-body escape hatch; §21.13.2 Zone-2/admin direct creation
            # uses the StoryService in-process, not this route).
            "reconciliation": {
                "weaviate_ready": True,
                "total_hits": 0,
                "hits_above_threshold": 0,
                "hits_classified_conflict": 0,
                "threshold_value": 0.7,
                "verdict": "PASS",
            },
        }).encode(),
    )
    assert resp.status_code == 201, f"Story creation failed: {resp.status_code} {resp.body}"
    return str(json.loads(resp.body)["story_id"])


# ---------------------------------------------------------------------------
# AC2 — legacy /v1/stories bare paths must return 404
# ---------------------------------------------------------------------------


def test_legacy_get_stories_collection_returns_404() -> None:
    """GET /v1/stories?project_key=... (legacy) is no longer routed; must 404 (AC2)."""
    app = _make_app()
    response = app.handle_request(
        method="GET",
        path="/v1/stories?project_key=proj-a",
        body=b"",
    )
    assert response.status_code == HTTPStatus.NOT_FOUND
    assert _json_body(response)["error_code"] == "not_found"  # type: ignore[index]


def test_legacy_get_story_detail_returns_404() -> None:
    """GET /v1/stories/{id} (legacy bare path) must 404 (AC2)."""
    app = _make_app()
    response = app.handle_request(
        method="GET",
        path="/v1/stories/AG3-100",
        body=b"",
    )
    assert response.status_code == HTTPStatus.NOT_FOUND
    assert _json_body(response)["error_code"] == "not_found"  # type: ignore[index]


def test_legacy_post_story_approve_returns_404() -> None:
    """POST /v1/stories/{id}/approve (legacy) is no longer routed; must 404 (AC2/AC3)."""
    app = _make_app()
    response = app.handle_request(
        method="POST",
        path="/v1/stories/AG3-100/approve",
        body=json.dumps({"op_id": "op-1"}).encode(),
    )
    assert response.status_code == HTTPStatus.NOT_FOUND
    assert _json_body(response)["error_code"] == "not_found"  # type: ignore[index]


def test_legacy_post_story_reject_returns_404() -> None:
    """POST /v1/stories/{id}/reject (legacy) is no longer routed; must 404 (AC2/AC3)."""
    app = _make_app()
    response = app.handle_request(
        method="POST",
        path="/v1/stories/AG3-100/reject",
        body=json.dumps({"op_id": "op-1"}).encode(),
    )
    assert response.status_code == HTTPStatus.NOT_FOUND
    assert _json_body(response)["error_code"] == "not_found"  # type: ignore[index]


def test_legacy_post_story_cancel_returns_404() -> None:
    """POST /v1/stories/{id}/cancel (legacy) is no longer routed; must 404 (AC2/AC3)."""
    app = _make_app()
    response = app.handle_request(
        method="POST",
        path="/v1/stories/AG3-100/cancel",
        body=json.dumps({"op_id": "op-1"}).encode(),
    )
    assert response.status_code == HTTPStatus.NOT_FOUND
    assert _json_body(response)["error_code"] == "not_found"  # type: ignore[index]


def test_legacy_patch_story_returns_404() -> None:
    """PATCH /v1/stories/{id} (legacy) is no longer routed; must 404 (AC2/AC3)."""
    app = _make_app()
    response = app.handle_request(
        method="PATCH",
        path="/v1/stories/AG3-100",
        body=json.dumps({"op_id": "op-1", "title": "New"}).encode(),
    )
    assert response.status_code == HTTPStatus.NOT_FOUND
    assert _json_body(response)["error_code"] == "not_found"  # type: ignore[index]


def test_legacy_put_story_field_returns_404() -> None:
    """PUT /v1/stories/{id}/fields/{key} (legacy) is no longer routed; must 404 (AC2/AC3)."""
    app = _make_app()
    response = app.handle_request(
        method="PUT",
        path="/v1/stories/AG3-100/fields/title",
        body=json.dumps({"op_id": "op-1", "value": "New"}).encode(),
    )
    assert response.status_code == HTTPStatus.NOT_FOUND
    assert _json_body(response)["error_code"] == "not_found"  # type: ignore[index]


# ---------------------------------------------------------------------------
# AC2 — project-scoped story paths cover all operations
# ---------------------------------------------------------------------------


def test_project_scoped_story_collection_get_resolves() -> None:
    """GET /v1/projects/{key}/stories resolves (tenant-scoped path, no legacy bypass) (AC2)."""
    app = _make_app_with_real_story_routes()

    get_resp = app.handle_request(
        method="GET",
        path="/v1/projects/proj-a/stories",
        body=b"",
    )
    # Route resolves (200 OK with empty list - no stories in the test read-model).
    # Key: this is NOT 404 (route missing) and goes through tenant-scope.
    assert get_resp.status_code == HTTPStatus.OK
    body = _json_body(get_resp)
    assert isinstance(body, dict)
    assert "stories" in body


def test_project_scoped_story_collection_post() -> None:
    """POST /v1/projects/{key}/stories creates a story (AC2)."""
    app = _make_app_with_real_story_routes()
    story_id = _create_story_via_app(app)
    assert story_id.startswith("PA-")


def test_project_scoped_story_detail_get_unknown_returns_404() -> None:
    """GET /v1/projects/{key}/stories/{id} resolves to a story-not-found 404 (AC2).

    The route IS reachable (project-scoped path resolves via tenant-scope) but
    the story itself doesn't exist, so the service returns 404.  This is
    different from a routing-404 (error_code='not_found') — it proves the
    project-scoped path dispatches correctly.
    """
    app = _make_app_with_real_story_routes()

    resp = app.handle_request(
        method="GET",
        path="/v1/projects/proj-a/stories/PA-999",
        body=b"",
    )
    # Story not found in read-model -> story service returns None -> 404 story_not_found.
    # This error_code proves the story route handler ran (not a routing 404).
    assert resp.status_code == HTTPStatus.NOT_FOUND
    assert _json_body(resp)["error_code"] == "story_not_found"  # type: ignore[index]


def test_project_scoped_story_approve_post() -> None:
    """POST /v1/projects/{key}/stories/{id}/approve works through tenant-scope (AC2)."""
    app = _make_app_with_real_story_routes()
    story_id = _create_story_via_app(app)

    resp = app.handle_request(
        method="POST",
        path=f"/v1/projects/proj-a/stories/{story_id}/approve",
        body=json.dumps({"op_id": "op-approve-1"}).encode(),
    )
    assert resp.status_code == HTTPStatus.OK
    assert _json_body(resp)["status"] == "Approved"  # type: ignore[index]


def test_project_scoped_story_reject_post() -> None:
    """POST /v1/projects/{key}/stories/{id}/reject works through tenant-scope (AC2)."""
    app = _make_app_with_real_story_routes()
    story_id = _create_story_via_app(app)
    # First approve, then reject
    app.handle_request(
        method="POST",
        path=f"/v1/projects/proj-a/stories/{story_id}/approve",
        body=json.dumps({"op_id": "op-approve-1"}).encode(),
    )
    resp = app.handle_request(
        method="POST",
        path=f"/v1/projects/proj-a/stories/{story_id}/reject",
        body=json.dumps({"op_id": "op-reject-1"}).encode(),
    )
    assert resp.status_code == HTTPStatus.OK
    assert _json_body(resp)["status"] == "Backlog"  # type: ignore[index]


def test_project_scoped_story_cancel_post() -> None:
    """POST /v1/projects/{key}/stories/{id}/cancel works through tenant-scope (AC2)."""
    app = _make_app_with_real_story_routes()
    story_id = _create_story_via_app(app)

    resp = app.handle_request(
        method="POST",
        path=f"/v1/projects/proj-a/stories/{story_id}/cancel",
        body=json.dumps({"op_id": "op-cancel-1", "reason": "Not needed"}).encode(),
    )
    assert resp.status_code == HTTPStatus.OK
    assert _json_body(resp)["status"] == "Cancelled"  # type: ignore[index]


def test_project_scoped_story_fields_get() -> None:
    """GET /v1/projects/{key}/stories/{id}/fields works through tenant-scope (AC2)."""
    app = _make_app_with_real_story_routes()
    story_id = _create_story_via_app(app)

    resp = app.handle_request(
        method="GET",
        path=f"/v1/projects/proj-a/stories/{story_id}/fields",
        body=b"",
    )
    assert resp.status_code == HTTPStatus.OK
    body = _json_body(resp)
    assert isinstance(body, dict)
    assert "fields" in body


def test_project_scoped_story_field_key_put() -> None:
    """PUT /v1/projects/{key}/stories/{id}/fields/{fkey} works through tenant-scope (AC2)."""
    app = _make_app_with_real_story_routes()
    story_id = _create_story_via_app(app)

    resp = app.handle_request(
        method="PUT",
        path=f"/v1/projects/proj-a/stories/{story_id}/fields/title",
        body=json.dumps({"op_id": "op-put-1", "value": "Updated title"}).encode(),
    )
    assert resp.status_code == HTTPStatus.OK
    assert _json_body(resp)["title"] == "Updated title"  # type: ignore[index]


def test_project_scoped_story_patch() -> None:
    """PATCH /v1/projects/{key}/stories/{id} works through tenant-scope (AC2)."""
    app = _make_app_with_real_story_routes()
    story_id = _create_story_via_app(app)

    resp = app.handle_request(
        method="PATCH",
        path=f"/v1/projects/proj-a/stories/{story_id}",
        body=json.dumps({"op_id": "op-patch-1", "title": "Patched title"}).encode(),
    )
    assert resp.status_code == HTTPStatus.OK
    assert _json_body(resp)["title"] == "Patched title"  # type: ignore[index]


def test_project_scoped_story_search() -> None:
    """GET /v1/projects/{key}/stories/search?q=... works through tenant-scope (AC2)."""
    app = _make_app_with_real_story_routes()
    _create_story_via_app(app)

    resp = app.handle_request(
        method="GET",
        path="/v1/projects/proj-a/stories/search?q=Test",
        body=b"",
    )
    assert resp.status_code == HTTPStatus.OK
    body = _json_body(resp)
    assert isinstance(body, dict)
    stories = body["stories"]
    assert isinstance(stories, list)
    assert len(stories) >= 1


# ---------------------------------------------------------------------------
# AC3 — fail-open hole closed: mutations on archived/unknown project blocked
# ---------------------------------------------------------------------------


def test_story_mutation_on_archived_project_returns_403() -> None:
    """Story POST on archived project is blocked by tenant-scope (AC3 fail-open hole closed)."""
    app = _make_app_with_real_story_routes(tenant_scope=_ArchivedTenantScope())

    response = app.handle_request(
        method="POST",
        path="/v1/projects/archived-proj/stories",
        body=json.dumps({
            "op_id": "op-1",
            "project_key": "archived-proj",
            "title": "Forbidden story",
            "type": "implementation",
            "repos": ["r"],
        }).encode(),
    )
    # Archived project -> tenant-scope blocks mutation -> 403
    assert response.status_code == HTTPStatus.FORBIDDEN
    body = _json_body(response)
    assert isinstance(body, dict)
    assert body["error_code"] == "forbidden"
    assert _header(response, "X-Correlation-Id") is not None


def test_story_approve_on_archived_project_returns_403() -> None:
    """POST approve on archived project is blocked by tenant-scope (AC3 fail-open hole closed)."""
    app = _make_app_with_real_story_routes(tenant_scope=_ArchivedTenantScope())

    response = app.handle_request(
        method="POST",
        path="/v1/projects/archived-proj/stories/PA-001/approve",
        body=json.dumps({"op_id": "op-1"}).encode(),
    )
    assert response.status_code == HTTPStatus.FORBIDDEN
    assert _json_body(response)["error_code"] == "forbidden"  # type: ignore[index]


def test_story_mutation_on_unknown_project_returns_404() -> None:
    """Story mutation on unknown project is blocked by tenant-scope (AC3 fail-open hole closed)."""
    app = _make_app_with_real_story_routes(tenant_scope=_RejectingTenantScope())

    response = app.handle_request(
        method="POST",
        path="/v1/projects/no-such-project/stories/PA-001/cancel",
        body=json.dumps({"op_id": "op-1"}).encode(),
    )
    assert response.status_code == HTTPStatus.NOT_FOUND
    body = _json_body(response)
    assert isinstance(body, dict)
    assert body["error_code"] == "project_not_found"
