"""Full-app reachability of the Execution-Input surface (AG3-100, FK-70 §70.8a).

Codex review seam: the unit route tests construct ``ExecutionPlanningRoutes``
directly. This integration test drives ``GET /execution-input/snapshot`` and
``GET /execution-input/next`` through the REAL productive HTTP entry
``ControlPlaneApplication`` / ``ControlPlaneApplicationRoutes`` -- i.e. through the
genuine registration + delegation path (``handle_request`` ->
``_handle_get_request`` -> ``self._planning_routes.handle_get``) plus the real
``TenantScopeMiddleware`` -- and asserts the wire payload. It proves the routes are
reachable end-to-end through the productive app, not just via a hand-constructed
route handler. The planning route itself is the REAL ``ExecutionPlanningRoutes``;
only the sanctioned repository test doubles are injected (no second selector,
no DB).
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from http import HTTPStatus

from agentkit.backend.control_plane_http.app import (
    ControlPlaneApplication,
    ControlPlaneApplicationRoutes,
    HttpResponse,
)
from agentkit.backend.control_plane_http.tenant_scope import TenantScopeMiddleware
from agentkit.backend.execution_planning.entities import (
    ParallelizationConfig,
    StoryDependency,
    StoryRefForPlanning,
)
from agentkit.backend.execution_planning.http.routes import ExecutionPlanningRoutes
from agentkit.backend.project_management.entities import Project, ProjectConfiguration
from agentkit.backend.project_management.lifecycle import create_project

_PROJECT = "tenant-a"
_SNAPSHOT = f"/v1/projects/{_PROJECT}/execution-input/snapshot"
_NEXT = f"/v1/projects/{_PROJECT}/execution-input/next"


@dataclass
class _ProjectRepo:
    """Sanctioned in-memory project repository double (project existence source)."""

    exists: bool = True

    def get(self, key: str) -> Project | None:
        if not self.exists or key != _PROJECT:
            return None
        return create_project(
            _PROJECT,
            "Tenant A",
            "AK3",
            ProjectConfiguration(
                repo_url="",
                default_branch="main",
                default_worker_count=1,
                repositories=["repo-a"],
            ),
            repositories=["repo-a"],
        )


@dataclass
class _StoryRepo:
    stories: dict[str, StoryRefForPlanning] = field(default_factory=dict)

    def get(self, project_key: str, story_id: str) -> StoryRefForPlanning | None:
        del project_key
        return self.stories.get(story_id)

    def list_for_project(self, project_key: str) -> list[StoryRefForPlanning]:
        del project_key
        return list(self.stories.values())


@dataclass
class _DepRepo:
    edges: list[StoryDependency] = field(default_factory=list)

    def list_for_project(self, project_key: str) -> list[StoryDependency]:
        del project_key
        return list(self.edges)

    def list_for_story(self, story_id: str) -> list[StoryDependency]:
        return [edge for edge in self.edges if edge.story_id == story_id]

    def add(self, edge: StoryDependency, *, project_key: str) -> None:  # pragma: no cover
        del project_key
        self.edges.append(edge)

    def remove(self, *args: object, **kwargs: object) -> None:  # pragma: no cover
        del args, kwargs


@dataclass
class _ConfigRepo:
    config: ParallelizationConfig | None = None

    def get(self, project_key: str) -> ParallelizationConfig | None:
        del project_key
        return self.config

    def upsert(self, config: ParallelizationConfig) -> None:  # pragma: no cover
        self.config = config


def _story(story_id: str, number: int, *, repo: str = "repo-a") -> StoryRefForPlanning:
    return StoryRefForPlanning(
        project_key=_PROJECT,
        story_id=story_id,
        story_number=number,
        title=f"Story {story_id}",
        lifecycle_status="defined",
        repo=repo,
    )


class _FakeRoute:
    """Passthrough BC-route stub: never claims a route (returns None for all verbs).

    Only the REAL ``ExecutionPlanningRoutes`` may claim the execution-input paths;
    every other BC route in the app must abstain so the test proves the productive
    delegation lands on the real planning route.
    """

    def handle_get(self, *args: object, **kwargs: object) -> None:
        del args, kwargs
        return None

    def handle_post(self, *args: object, **kwargs: object) -> None:
        del args, kwargs
        return None

    def handle_put(self, *args: object, **kwargs: object) -> None:
        del args, kwargs
        return None

    def handle_patch(self, *args: object, **kwargs: object) -> None:
        del args, kwargs
        return None

    def handle_delete(self, *args: object, **kwargs: object) -> None:
        del args, kwargs
        return None


def _build_app(
    *,
    stories: dict[str, StoryRefForPlanning] | None = None,
    edges: list[StoryDependency] | None = None,
    config: ParallelizationConfig | None = None,
) -> ControlPlaneApplication:
    """Wire the productive app with the REAL planning route + sanctioned doubles."""
    project_repo = _ProjectRepo()
    planning_routes = ExecutionPlanningRoutes(
        project_repository=project_repo,  # type: ignore[arg-type]
        story_repository=_StoryRepo(stories=stories or {}),
        dependency_repository=_DepRepo(edges=edges or []),
        config_repository=_ConfigRepo(config=config),
    )
    fake = _FakeRoute()
    return ControlPlaneApplication(
        routes=ControlPlaneApplicationRoutes(
            project_routes=fake,  # type: ignore[arg-type]
            story_routes=fake,  # type: ignore[arg-type]
            concept_routes=fake,  # type: ignore[arg-type]
            hub_routes=fake,  # type: ignore[arg-type]
            planning_routes=planning_routes,
            telemetry_routes=fake,  # type: ignore[arg-type]
            auth_routes=fake,  # type: ignore[arg-type]
            kpi_analytics_routes=fake,  # type: ignore[arg-type]
        ),
        tenant_scope_middleware=TenantScopeMiddleware(repository=project_repo),  # type: ignore[arg-type]
    )


def _json_body(response: HttpResponse) -> dict[str, object]:
    body: dict[str, object] = json.loads(response.body)
    return body


class TestExecutionInputThroughFullApp:
    def test_snapshot_reachable_through_productive_app(self) -> None:
        """GET snapshot through the full app returns the formal wire payload."""
        app = _build_app(
            stories={"S1": _story("S1", 1), "S2": _story("S2", 2, repo="repo-b")},
            config=ParallelizationConfig(project_key=_PROJECT, max_parallel_stories=5),
        )
        response = app.handle_request(method="GET", path=_SNAPSHOT, body=b"")
        assert response.status_code == int(HTTPStatus.OK)
        body = _json_body(response)
        assert set(body.keys()) == {
            "project_key",
            "running",
            "eligible_ready",
            "total_ready",
            "global_slots_left",
        }
        assert body["total_ready"] == 2
        eligible = body["eligible_ready"]
        assert isinstance(eligible, list)
        # Cards carry the formal execution_input_stack shape (nested story ref).
        first = eligible[0]
        assert set(first.keys()) == {"story", "predecessor", "successor"}
        ids = {card["story"]["story_id"] for card in eligible}
        assert ids == {"S1", "S2"}
        assert all(card["story"]["repo"] in {"repo-a", "repo-b"} for card in eligible)

    def test_next_reachable_through_productive_app(self) -> None:
        """GET next through the full app returns exactly one nested card + reason."""
        app = _build_app(
            stories={"S1": _story("S1", 1), "S2": _story("S2", 2)},
            config=ParallelizationConfig(project_key=_PROJECT, max_parallel_stories=5),
        )
        response = app.handle_request(method="GET", path=_NEXT, body=b"")
        assert response.status_code == int(HTTPStatus.OK)
        body = _json_body(response)
        assert set(body.keys()) == {"project_key", "story", "reason"}
        card = body["story"]
        assert isinstance(card, dict)
        assert set(card.keys()) == {"story", "predecessor", "successor"}
        story_ref = card["story"]
        assert isinstance(story_ref, dict)
        assert story_ref["story_id"] in {"S1", "S2"}
        reason = body["reason"]
        assert isinstance(reason, dict)
        assert reason["active_tiebreaker"] == (
            "critical_path_desc_then_story_number_asc"
        )

    def test_unknown_project_fails_closed_through_middleware(self) -> None:
        """The full app fails closed (404) for an unknown project via tenant scope."""
        app = _build_app(stories={"S1": _story("S1", 1)})
        response = app.handle_request(
            method="GET",
            path="/v1/projects/does-not-exist/execution-input/snapshot",
            body=b"",
        )
        assert response.status_code == int(HTTPStatus.NOT_FOUND)
