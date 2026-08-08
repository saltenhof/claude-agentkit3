"""AG3-126 AC4: BFF story list/detail route through the injected StoryReadPort.

Proves the through-port wiring (FK-72 §72.8): the REAL
``agentkit.backend.story.service.StoryService`` is injected into the BFF with a
fake :class:`StoryReadPort` (NO state backend). The unchanged ``StorySummary`` /
``StoryDetail`` wire models must come back, sourced exclusively through the port
— a fake StoryService would bypass the port and prove nothing.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from http import HTTPStatus
from typing import TYPE_CHECKING

from agentkit.backend.control_plane_http.app import ControlPlaneApplication
from agentkit.backend.control_plane_http.responses import HttpResponse, _error_response
from agentkit.backend.phase_state_store.models import FlowExecution
from agentkit.backend.story.service import StoryService
from agentkit.backend.story_context_manager.models import StoryContext
from agentkit.backend.story_context_manager.story_model import StorySpecification
from agentkit.backend.story_context_manager.types import (
    ImplementationContract,
    StoryMode,
    StoryType,
)

if TYPE_CHECKING:
    from agentkit.backend.closure.post_merge_finalization.records import StoryMetricsRecord
    from agentkit.backend.pipeline_engine.phase_executor import PhaseState
    from agentkit.backend.telemetry.contract.records import ExecutionEventRecord

_PROJECT = "tenant-a"
_STORY = "AG3-100"


def _context() -> StoryContext:
    return StoryContext(
        project_key=_PROJECT,
        story_id=_STORY,
        story_type=StoryType.IMPLEMENTATION,
        execution_route=StoryMode.EXECUTION,
        implementation_contract=ImplementationContract.STANDARD,
        title="Through-port story",
        labels=["size:medium"],
        participating_repos=["app"],
        created_at=datetime(2026, 6, 12, 10, 0, tzinfo=UTC),
    )


def _flow(project_key: str, story_id: str) -> FlowExecution:
    return FlowExecution(
        project_key=project_key,
        story_id=story_id,
        run_id="run-100",
        flow_id="implementation",
        level="story",
        owner="pipeline_engine",
        status="RUNNING",
        attempt_no=1,
        started_at=datetime(2026, 6, 12, 10, 5, tzinfo=UTC),
    )


def _specification() -> StorySpecification:
    return StorySpecification(
        need="The edge must reach a story and its specification over /v1.",
        solution="The project-scoped detail read resolves both in one call.",
        acceptance=["specification travels with the detail payload"],
    )


@dataclass
class _FakeStoryReadPort:
    """StoryReadPort fake with NO state backend (drives the real StoryService)."""

    def list_story_contexts(self, project_key: str) -> list[StoryContext]:
        return [_context()]

    def load_story_context(self, project_key: str, story_id: str) -> StoryContext | None:
        return _context() if story_id == _STORY else None

    def load_story_specification(
        self, project_key: str, story_id: str
    ) -> StorySpecification | None:
        return _specification() if story_id == _STORY else None

    def load_phase_state(self, story_id: str) -> PhaseState | None:
        return None

    def load_flow_execution(self, project_key: str, story_id: str) -> FlowExecution | None:
        return _flow(project_key, story_id)

    def load_latest_story_metrics(self, project_key: str, story_id: str) -> StoryMetricsRecord | None:
        return None

    def load_recent_execution_events(
        self, project_key: str, story_id: str, run_id: str, limit: int
    ) -> list[ExecutionEventRecord]:
        return []


class _NoopTenantScope:
    def validate(self, *, method: str, route_path: str, correlation_id: str) -> None:
        return None


def _make_app() -> ControlPlaneApplication:
    return ControlPlaneApplication(
        writer_lease_required=False,
        story_service=StoryService(repository=_FakeStoryReadPort()),
        tenant_scope_middleware=_NoopTenantScope(),  # type: ignore[arg-type]
    )


def _body(response: object) -> dict[str, object]:
    return json.loads(response.body)  # type: ignore[attr-defined]


def test_get_stories_collection_routes_through_port() -> None:
    app = _make_app()

    response = app.handle_request(
        method="GET",
        path=f"/v1/projects/{_PROJECT}/stories",
        body=b"",
    )

    assert response.status_code == 200
    body = _body(response)
    assert body["project_key"] == _PROJECT
    stories = body["stories"]
    assert isinstance(stories, list)
    assert stories[0]["story_id"] == _STORY
    assert stories[0]["title"] == "Through-port story"
    # The summary is sourced through the port's FlowExecution read.
    assert stories[0]["current_run"]["run_id"] == "run-100"
    assert stories[0]["lifecycle_status"] == "active"


def test_get_story_detail_routes_through_port() -> None:
    app = _make_app()

    response = app.handle_request(
        method="GET",
        path=f"/v1/projects/{_PROJECT}/stories/{_STORY}",
        body=b"",
    )

    assert response.status_code == 200
    body = _body(response)
    assert body["story_id"] == _STORY
    assert body["labels"] == ["size:medium"]
    assert body["participating_repos"] == ["app"]


def test_get_missing_story_detail_returns_not_found() -> None:
    app = _make_app()

    response = app.handle_request(
        method="GET",
        path=f"/v1/projects/{_PROJECT}/stories/AG3-404",
        body=b"",
    )

    assert response.status_code == 404


# ---------------------------------------------------------------------------
# AG3-240: the extended project-scoped detail read
# ---------------------------------------------------------------------------


class _RejectingTenantScope:
    """Tenant scope that refuses the request, as it does for a foreign project.

    The productive middleware answers with a response rather than raising, so
    the double does too -- a raising double would prove a path the application
    never takes.
    """

    def validate(
        self, *, method: str, route_path: str, correlation_id: str
    ) -> HttpResponse:
        return _error_response(
            HTTPStatus.FORBIDDEN,
            error_code="project_scope_forbidden",
            message="project scope is not authorised for this session",
            correlation_id=correlation_id,
        )


class _UnreachableCorePort(_FakeStoryReadPort):
    """A read port whose state backend cannot be reached."""

    def load_story_context(self, project_key: str, story_id: str) -> StoryContext | None:
        raise RuntimeError("state backend is not reachable")


def test_the_exposed_detail_route_carries_the_specification() -> None:
    """AG3-240: the ONLY exposed story-detail surface answers the specification.

    Bare ``/v1/stories/{id}`` is deliberately not delegated by the application,
    so before this change the specification was unreachable from off the core and
    every consumer had to build the core story service locally.
    """
    app = _make_app()

    response = app.handle_request(
        method="GET",
        path=f"/v1/projects/{_PROJECT}/stories/{_STORY}",
        body=b"",
    )

    assert response.status_code == 200
    specification = _body(response)["specification"]
    assert isinstance(specification, dict)
    assert specification["need"] == _specification().need
    assert specification["acceptance"] == list(_specification().acceptance)


def test_the_bare_story_detail_route_stays_undelegated() -> None:
    """The project-scoped convention is unchanged (FK-72 §72.8.1).

    Carrying the specification on the project-scoped route must not quietly open
    the bare path as a second way in.
    """
    app = _make_app()

    response = app.handle_request(method="GET", path=f"/v1/stories/{_STORY}", body=b"")

    assert response.status_code == 404


def test_an_unauthorised_project_scope_is_refused() -> None:
    app = ControlPlaneApplication(
        writer_lease_required=False,
        story_service=StoryService(repository=_FakeStoryReadPort()),
        tenant_scope_middleware=_RejectingTenantScope(),  # type: ignore[arg-type]
    )

    response = app.handle_request(
        method="GET",
        path=f"/v1/projects/{_PROJECT}/stories/{_STORY}",
        body=b"",
    )

    assert response.status_code in {401, 403}
    assert b"specification" not in response.body


def test_an_unknown_story_is_not_answered_with_a_specification() -> None:
    app = _make_app()

    response = app.handle_request(
        method="GET",
        path=f"/v1/projects/{_PROJECT}/stories/AG3-404",
        body=b"",
    )

    assert response.status_code == 404
    assert "specification" not in _body(response)


def test_an_unreachable_core_fails_closed() -> None:
    app = ControlPlaneApplication(
        writer_lease_required=False,
        story_service=StoryService(repository=_UnreachableCorePort()),
        tenant_scope_middleware=_NoopTenantScope(),  # type: ignore[arg-type]
    )

    response = app.handle_request(
        method="GET",
        path=f"/v1/projects/{_PROJECT}/stories/{_STORY}",
        body=b"",
    )

    assert response.status_code == 503
    assert _body(response)["error_code"] == "story_detail_unavailable"
