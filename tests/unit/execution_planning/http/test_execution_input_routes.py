"""Unit tests for the Execution-Input snapshot/next HTTP routes (AG3-100, FK-70 §70.8a).

Pins the two living surface variants on the ONE deterministic selector: snapshot
returns the whole pick (empty lists -> 200, not 404), next returns exactly the first
card (or null) + triage reason, idempotently. The surfaces are exercised through the
real ``ExecutionPlanningRoutes`` handler with sanctioned repository test doubles only.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from http import HTTPStatus

from agentkit.backend.execution_planning.entities import (
    ParallelizationConfig,
    StoryDependency,
    StoryDependencyKind,
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


def _story(
    story_id: str,
    number: int,
    *,
    repo: str = "repo-a",
    status: str = "defined",
) -> StoryRefForPlanning:
    return StoryRefForPlanning(
        project_key=_PROJECT,
        story_id=story_id,
        story_number=number,
        title=f"Story {story_id}",
        lifecycle_status=status,
        repo=repo,
    )


def _routes(
    *,
    project_exists: bool = True,
    stories: dict[str, StoryRefForPlanning] | None = None,
    edges: list[StoryDependency] | None = None,
    config: ParallelizationConfig | None = None,
) -> ExecutionPlanningRoutes:
    return ExecutionPlanningRoutes(
        project_repository=_ProjectRepo(exists=project_exists),
        story_repository=_StoryRepo(stories=stories or {}),
        dependency_repository=_DepRepo(edges=edges or []),
        config_repository=_ConfigRepo(config=config),
    )


def _body(response: object) -> dict[str, object]:
    assert response is not None
    return json.loads(response.body)  # type: ignore[attr-defined]


class TestExecutionInputSnapshot:
    def test_snapshot_returns_pick_with_wire_fields(self) -> None:
        """Snapshot exposes running/eligible_ready/total_ready/global_slots_left."""
        routes = _routes(
            stories={"S1": _story("S1", 1), "S2": _story("S2", 2, repo="repo-b")},
            config=ParallelizationConfig(
                project_key=_PROJECT, max_parallel_stories=5,
            ),
        )
        response = routes.handle_get(_SNAPSHOT, "corr-1")
        assert response is not None
        assert response.status_code == int(HTTPStatus.OK)
        body = _body(response)
        assert set(body.keys()) == {
            "project_key",
            "running",
            "eligible_ready",
            "total_ready",
            "global_slots_left",
        }
        assert body["total_ready"] == 2
        # Cards are the nested execution_input_stack shape: story under ``story``.
        eligible_ids = {card["story"]["story_id"] for card in body["eligible_ready"]}
        assert eligible_ids == {"S1", "S2"}
        first_card = body["eligible_ready"][0]
        assert set(first_card.keys()) == {"story", "predecessor", "successor"}

    def test_empty_eligible_list_is_200_not_404(self) -> None:
        """FK-70 §70.8a.1: an empty eligible list is a valid 200, never a 404."""
        routes = _routes(stories={})
        response = routes.handle_get(_SNAPSHOT, "corr-2")
        assert response is not None
        assert response.status_code == int(HTTPStatus.OK)
        body = _body(response)
        assert body["running"] == []
        assert body["eligible_ready"] == []
        assert body["total_ready"] == 0

    def test_unknown_project_is_404(self) -> None:
        """An unknown project key fails closed with 404 (not an empty 200)."""
        routes = _routes(project_exists=False)
        response = routes.handle_get(_SNAPSHOT, "corr-3")
        assert response is not None
        assert response.status_code == int(HTTPStatus.NOT_FOUND)


class TestExecutionInputNext:
    def test_next_returns_one_story_and_reason(self) -> None:
        """FK-70 §70.8a.2: next returns exactly one story + triage reason."""
        routes = _routes(
            stories={"S1": _story("S1", 1), "S2": _story("S2", 2)},
            config=ParallelizationConfig(
                project_key=_PROJECT, max_parallel_stories=5,
            ),
        )
        response = routes.handle_get(_NEXT, "corr-4")
        body = _body(response)
        assert set(body.keys()) == {"project_key", "story", "reason"}
        assert body["story"] is not None
        # ``story`` is one execution_input_stack card: the story ref nests under ``story``.
        assert set(body["story"].keys()) == {"story", "predecessor", "successor"}
        # The single selector picks the critical-path story first per repo bucket.
        assert body["story"]["story"]["story_id"] in {"S1", "S2"}
        assert body["reason"]["active_tiebreaker"] == (
            "critical_path_desc_then_story_number_asc"
        )
        assert set(body["reason"].keys()) == {
            "repo_bucket",
            "on_critical_path",
            "global_slots_left",
            "repo_slots",
            "active_tiebreaker",
        }

    def test_next_is_null_when_nothing_delegable(self) -> None:
        """FK-70 §70.8a.2: no delegable card -> story=null, reason=null, still 200."""
        routes = _routes(
            stories={"S1": _story("S1", 1)},
            config=ParallelizationConfig(
                project_key=_PROJECT, max_parallel_stories=5,
            ),
            edges=[
                StoryDependency(
                    story_id="S1",
                    depends_on_story_id="S0",
                    kind=StoryDependencyKind.HARD_STORY_DEPENDENCY,
                    created_at=datetime(2024, 1, 1, tzinfo=UTC),
                ),
            ],
        )
        # S1 depends on missing/un-done S0 -> blocked -> nothing delegable.
        routes_with_blocker = routes
        response = routes_with_blocker.handle_get(_NEXT, "corr-5")
        body = _body(response)
        assert body["story"] is None
        assert body["reason"] is None

    def test_next_is_idempotent(self) -> None:
        """FK-70 §70.8a.2: repeated calls without backlog change return the same."""
        routes = _routes(
            stories={"S1": _story("S1", 1), "S2": _story("S2", 2)},
            config=ParallelizationConfig(
                project_key=_PROJECT, max_parallel_stories=5,
            ),
        )
        first = _body(routes.handle_get(_NEXT, "corr-6"))
        second = _body(routes.handle_get(_NEXT, "corr-7"))
        assert first["story"] == second["story"]
        assert first["reason"] == second["reason"]
