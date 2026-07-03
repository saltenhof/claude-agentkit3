"""Unit tests for StoryContextRoutes (story_context_manager HTTP adapter).

Tests HTTP routing, error contract, and service dispatch for all story
endpoints (FK-91 §91.1a).
"""

from __future__ import annotations

import json
from http import HTTPStatus

from agentkit.backend.project_management.entities import Project, ProjectConfiguration
from agentkit.backend.story_context_manager.http.routes import StoryContextRoutes, StoryRouteResponse
from agentkit.backend.story_context_manager.idempotency import InMemoryIdempotencyKeyRepository
from agentkit.backend.story_context_manager.service import StoryService
from agentkit.backend.story_context_manager.story_repository import InMemoryStoryRepository

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class _InMemoryProjectRepository:
    def __init__(self) -> None:
        self._projects: dict[str, Project] = {
            "ak3": Project(
                key="ak3",
                name="AgentKit 3",
                story_id_prefix="AK3",
                configuration=ProjectConfiguration(
                    repo_url="",
                    default_branch="main",
                    default_worker_count=2,
                    repositories=["ak3", "r"],
                ),
            ),
        }

    def get(self, key: str) -> Project | None:
        return self._projects.get(key)

    def list(self, *, include_archived: bool = False) -> list[Project]:
        return list(self._projects.values())

    def save(self, project: Project) -> None:
        self._projects[project.key] = project


def _make_routes() -> StoryContextRoutes:
    svc = StoryService(
        story_repository=InMemoryStoryRepository(),
        project_repository=_InMemoryProjectRepository(),
        idempotency_repository=InMemoryIdempotencyKeyRepository(),
    )
    return StoryContextRoutes(story_service=svc)


def _body(resp: StoryRouteResponse) -> dict[str, object]:
    result = json.loads(resp.body)
    assert isinstance(result, dict)
    return result


def _correlation_header(resp: StoryRouteResponse) -> str:
    for key, val in resp.headers:
        if key == "X-Correlation-Id":
            return val
    raise AssertionError("Missing X-Correlation-Id header")


CORR = "test-corr-001"

# AG3-068 (FK-21 §21.4/§21.12/§21.13): the agent-facing POST /v1/stories is
# fail-closed and requires typed reconciliation evidence — there is NO in-body
# escape hatch (the Zone-2/admin exemption of §21.13.2 calls the StoryService
# in-process, not this route). These routing/error-contract tests are not about
# the gate itself, so they carry a minimal VALID evidence block to get past it;
# the dedicated reconciliation-gate tests (incl. the no-magic-string regression)
# live in tests/integration/story_creation/test_create_route_reconciliation.py.
_RECON: dict[str, object] = {
    "weaviate_ready": True,
    "total_hits": 0,
    "hits_above_threshold": 0,
    "hits_classified_conflict": 0,
    "threshold_value": 0.7,
    "verdict": "PASS",
}

# ---------------------------------------------------------------------------
# GET /v1/stories (list)
# ---------------------------------------------------------------------------


def test_get_stories_returns_empty_list_for_new_project() -> None:
    routes = _make_routes()
    resp = routes.handle_get(
        "/v1/stories",
        CORR,
        query={"project_key": ["ak3"]},
    )
    assert resp is not None
    assert resp.status_code == HTTPStatus.OK
    body = _body(resp)
    assert body["project_key"] == "ak3"
    assert body["stories"] == []


def test_get_stories_missing_project_key_returns_400() -> None:
    routes = _make_routes()
    resp = routes.handle_get("/v1/stories", CORR)
    assert resp is not None
    assert resp.status_code == HTTPStatus.BAD_REQUEST
    assert _body(resp)["error_code"] == "missing_project_key"


def test_get_stories_returns_correlation_id_header() -> None:
    routes = _make_routes()
    resp = routes.handle_get(
        "/v1/stories",
        "my-corr-42",
        query={"project_key": ["ak3"]},
    )
    assert resp is not None
    assert _correlation_header(resp) == "my-corr-42"


# ---------------------------------------------------------------------------
# POST /v1/stories (create)
# ---------------------------------------------------------------------------


def test_post_stories_creates_story() -> None:
    routes = _make_routes()
    resp = routes.handle_post(
        "/v1/stories",
        {
            "op_id": "op-001",
            "project_key": "ak3",
            "title": "New story",
            "type": "implementation",
            "repos": ["ak3"],
            "reconciliation": _RECON,
        },
        CORR,
    )
    assert resp is not None
    assert resp.status_code == HTTPStatus.CREATED
    body = _body(resp)
    assert body["story_id"] == "AK3-001"
    assert body["status"] == "Backlog"


def test_post_stories_missing_op_id_returns_422() -> None:
    """AG3-140 (FK-91 §91.1a Regel 5, AC1): missing op_id fails closed with 422."""
    routes = _make_routes()
    resp = routes.handle_post(
        "/v1/stories",
        {"project_key": "ak3", "title": "T"},
        CORR,
    )
    assert resp is not None
    assert resp.status_code == HTTPStatus.UNPROCESSABLE_ENTITY
    assert _body(resp)["error_code"] == "missing_op_id"


def test_post_stories_unknown_project_returns_400() -> None:
    routes = _make_routes()
    resp = routes.handle_post(
        "/v1/stories",
        {
            "op_id": "op-001",
            "project_key": "UNKNOWN",
            "title": "T",
            "type": "implementation",
            "repos": ["r"],
            "reconciliation": _RECON,
        },
        CORR,
    )
    assert resp is not None
    assert resp.status_code == HTTPStatus.BAD_REQUEST


def test_post_stories_invalid_story_type_returns_400() -> None:
    routes = _make_routes()
    resp = routes.handle_post(
        "/v1/stories",
        {
            "op_id": "op-001",
            "project_key": "ak3",
            "title": "T",
            "type": "invalid_type",
            "repos": ["r"],
            "reconciliation": _RECON,
        },
        CORR,
    )
    assert resp is not None
    assert resp.status_code == HTTPStatus.BAD_REQUEST


def test_post_stories_non_dict_body_returns_400() -> None:
    routes = _make_routes()
    resp = routes.handle_post("/v1/stories", "not a dict", CORR)
    assert resp is not None
    assert resp.status_code == HTTPStatus.BAD_REQUEST


# ---------------------------------------------------------------------------
# GET /v1/stories/{id}
# ---------------------------------------------------------------------------


def test_get_story_detail_returns_200() -> None:
    routes = _make_routes()
    routes.handle_post(
        "/v1/stories",
        {
            "op_id": "op-001",
            "project_key": "ak3",
            "title": "Detail story",
            "type": "implementation",
            "repos": ["ak3"],
            "reconciliation": _RECON,
        },
        CORR,
    )
    resp = routes.handle_get("/v1/stories/AK3-001", CORR)
    assert resp is not None
    assert resp.status_code == HTTPStatus.OK
    body = _body(resp)
    assert body["summary"]["story_id"] == "AK3-001"  # type: ignore[index]
    # Befund 2: create_story always persists a default StorySpecification.
    assert body["spec"] is not None


def test_get_story_detail_not_found_returns_404() -> None:
    routes = _make_routes()
    resp = routes.handle_get("/v1/stories/AK3-999", CORR)
    assert resp is not None
    assert resp.status_code == HTTPStatus.NOT_FOUND
    assert _body(resp)["error_code"] == "story_not_found"


# ---------------------------------------------------------------------------
# GET /v1/stories/{id}/fields
# ---------------------------------------------------------------------------


def test_get_story_fields_returns_wire_dict() -> None:
    routes = _make_routes()
    routes.handle_post(
        "/v1/stories",
        {
            "op_id": "op-001",
            "project_key": "ak3",
            "title": "Fields test",
            "type": "implementation",
            "repos": ["ak3"],
            "reconciliation": _RECON,
        },
        CORR,
    )
    resp = routes.handle_get("/v1/stories/AK3-001/fields", CORR)
    assert resp is not None
    assert resp.status_code == HTTPStatus.OK
    body = _body(resp)
    assert "fields" in body
    fields = body["fields"]
    assert isinstance(fields, dict)
    assert isinstance(fields, dict) and fields["status"] == "Backlog"


def test_get_story_fields_not_found_returns_404() -> None:
    routes = _make_routes()
    resp = routes.handle_get("/v1/stories/AK3-999/fields", CORR)
    assert resp is not None
    assert resp.status_code == HTTPStatus.NOT_FOUND


# ---------------------------------------------------------------------------
# GET /v1/projects/{key}/stories/search
# ---------------------------------------------------------------------------


def test_search_stories_missing_q_returns_400() -> None:
    routes = _make_routes()
    resp = routes.handle_get("/v1/projects/ak3/stories/search", CORR, query={})
    assert resp is not None
    assert resp.status_code == HTTPStatus.BAD_REQUEST
    assert _body(resp)["error_code"] == "missing_query"


def test_search_stories_returns_matching_stories() -> None:
    routes = _make_routes()
    routes.handle_post(
        "/v1/stories",
        {
            "op_id": "op-001",
            "project_key": "ak3",
            "title": "Implement service backend",
            "type": "implementation",
            "repos": ["ak3"],
            "reconciliation": _RECON,
        },
        CORR,
    )
    routes.handle_post(
        "/v1/stories",
        {
            "op_id": "op-002",
            "project_key": "ak3",
            "title": "Fix preflight logic",
            "type": "bugfix",
            "repos": ["ak3"],
            "reconciliation": _RECON,
        },
        CORR,
    )

    resp = routes.handle_get(
        "/v1/projects/ak3/stories/search",
        CORR,
        query={"q": ["service"]},
    )
    assert resp is not None
    assert resp.status_code == HTTPStatus.OK
    body = _body(resp)
    assert len(body["stories"]) == 1  # type: ignore[arg-type]
    assert "service" in str(body["stories"][0]).lower()  # type: ignore[index]


# ---------------------------------------------------------------------------
# POST /v1/stories/{id}/approve|reject|cancel
# ---------------------------------------------------------------------------


def _setup_story(routes: StoryContextRoutes) -> str:
    """Create a story and return its display_id."""
    routes.handle_post(
        "/v1/stories",
        {
            "op_id": "op-setup",
            "project_key": "ak3",
            "title": "Setup story",
            "type": "implementation",
            "repos": ["ak3"],
            "reconciliation": _RECON,
        },
        CORR,
    )
    return "AK3-001"


def test_post_approve_transitions_to_approved() -> None:
    routes = _make_routes()
    story_id = _setup_story(routes)

    resp = routes.handle_post(
        f"/v1/stories/{story_id}/approve",
        {"op_id": "op-approve"},
        CORR,
    )
    assert resp is not None
    assert resp.status_code == HTTPStatus.OK
    assert _body(resp)["status"] == "Approved"


def test_post_reject_transitions_to_backlog() -> None:
    routes = _make_routes()
    story_id = _setup_story(routes)
    routes.handle_post(f"/v1/stories/{story_id}/approve", {"op_id": "op-approve"}, CORR)

    resp = routes.handle_post(
        f"/v1/stories/{story_id}/reject",
        {"op_id": "op-reject"},
        CORR,
    )
    assert resp is not None
    assert resp.status_code == HTTPStatus.OK
    assert _body(resp)["status"] == "Backlog"


def test_post_cancel_transitions_to_cancelled() -> None:
    routes = _make_routes()
    story_id = _setup_story(routes)

    resp = routes.handle_post(
        f"/v1/stories/{story_id}/cancel",
        {"op_id": "op-cancel", "reason": "No longer needed"},
        CORR,
    )
    assert resp is not None
    assert resp.status_code == HTTPStatus.OK
    assert _body(resp)["status"] == "Cancelled"


def test_post_approve_invalid_transition_returns_422() -> None:
    routes = _make_routes()
    story_id = _setup_story(routes)
    # Already in Backlog; try to approve and then approve again:
    routes.handle_post(f"/v1/stories/{story_id}/approve", {"op_id": "op-a"}, CORR)
    # Story is now Approved. Approve again from Approved would still be invalid
    # Actually approved->approved is same-status (idempotent), so:
    # Try cancel -> approved (invalid)
    routes.handle_post(f"/v1/stories/{story_id}/cancel", {"op_id": "op-c"}, CORR)
    resp = routes.handle_post(
        f"/v1/stories/{story_id}/approve",
        {"op_id": "op-a2"},
        CORR,
    )
    assert resp is not None
    assert resp.status_code == HTTPStatus.UNPROCESSABLE_ENTITY
    assert _body(resp)["error_code"] == "invalid_transition"


# ---------------------------------------------------------------------------
# PATCH /v1/stories/{id}
# ---------------------------------------------------------------------------


def test_patch_story_updates_title() -> None:
    routes = _make_routes()
    story_id = _setup_story(routes)

    resp = routes.handle_patch(
        f"/v1/stories/{story_id}",
        {"op_id": "op-patch", "title": "Updated title"},
        CORR,
    )
    assert resp is not None
    assert resp.status_code == HTTPStatus.OK
    assert _body(resp)["title"] == "Updated title"


def test_patch_story_forbidden_field_returns_422() -> None:
    routes = _make_routes()
    story_id = _setup_story(routes)

    resp = routes.handle_patch(
        f"/v1/stories/{story_id}",
        {"op_id": "op-patch", "status": "Approved"},
        CORR,
    )
    assert resp is not None
    assert resp.status_code == HTTPStatus.UNPROCESSABLE_ENTITY
    assert _body(resp)["error_code"] == "forbidden_field"


def test_patch_non_story_path_returns_none() -> None:
    routes = _make_routes()
    resp = routes.handle_patch("/v1/projects/AK3", {}, CORR)
    assert resp is None


# ---------------------------------------------------------------------------
# PUT /v1/stories/{id}/fields/{key}
# ---------------------------------------------------------------------------


def test_put_story_field_updates_title() -> None:
    routes = _make_routes()
    story_id = _setup_story(routes)

    resp = routes.handle_put(
        f"/v1/stories/{story_id}/fields/title",
        {"op_id": "op-put", "value": "PUT title"},
        CORR,
    )
    assert resp is not None
    assert resp.status_code == HTTPStatus.OK
    assert _body(resp)["title"] == "PUT title"


def test_put_story_field_status_returns_422() -> None:
    routes = _make_routes()
    story_id = _setup_story(routes)

    resp = routes.handle_put(
        f"/v1/stories/{story_id}/fields/status",
        {"op_id": "op-put-status", "value": "Approved"},
        CORR,
    )
    assert resp is not None
    assert resp.status_code == HTTPStatus.UNPROCESSABLE_ENTITY
    assert _body(resp)["error_code"] == "forbidden_field"


def test_put_non_field_path_returns_none() -> None:
    routes = _make_routes()
    resp = routes.handle_put("/v1/stories/AK3-1", {}, CORR)
    assert resp is None


# ---------------------------------------------------------------------------
# Error contract
# ---------------------------------------------------------------------------


def test_error_response_includes_correlation_id() -> None:
    routes = _make_routes()
    resp = routes.handle_get("/v1/stories/AK3-999", "my-corr-id")
    assert resp is not None
    body = _body(resp)
    assert body["correlation_id"] == "my-corr-id"
    assert _correlation_header(resp) == "my-corr-id"


def test_unknown_path_returns_none_not_404() -> None:
    """Routes return None for paths they don't own; caller decides 404."""
    routes = _make_routes()
    assert routes.handle_get("/v1/other/path", CORR) is None
    assert routes.handle_post("/v1/other/path", {}, CORR) is None
    assert routes.handle_patch("/v1/other/path", {}, CORR) is None
    assert routes.handle_put("/v1/other/path", {}, CORR) is None
