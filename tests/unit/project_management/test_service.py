"""Unit tests for project-management read-aggregation (AG3-040 sub-block a).

Covers ``compute_story_counters`` (per
``frontend-contracts.invariant.counters_classification``),
``derive_mode_lock`` (per
``frontend-contracts.invariant.mode_lock_derived``) and the
``ProjectDetailService.build_project_detail_view`` aggregation.

Uses real ``Story`` SSOT models and real ``Project`` entities; the only
test doubles are narrow read-only ports (a project repository and a
story-list port), which carry real domain objects — no mocked core
logic.
"""

from __future__ import annotations

import pytest

from agentkit.core_types import StorySize
from agentkit.project_management.entities import Project, ProjectConfiguration
from agentkit.project_management.errors import ProjectNotFoundError
from agentkit.project_management.service import (
    ProjectDetailService,
    compute_story_counters,
    derive_mode_lock,
)
from agentkit.story_context_manager.story_model import (
    Story,
    StoryStatus,
    WireStoryMode,
    WireStoryType,
)

_PROJECT_KEY = "tenant-a"


def _story(
    display_id: str,
    status: StoryStatus,
    *,
    mode: WireStoryMode | None = None,
    blocker: str | None = None,
    dependencies: list[str] | None = None,
) -> Story:
    return Story(
        project_key=_PROJECT_KEY,
        story_number=int(display_id.split("-")[-1]),
        story_display_id=display_id,
        title=f"Story {display_id}",
        story_type=WireStoryType.IMPLEMENTATION,
        status=status,
        size=StorySize.M,
        mode=mode,
        participating_repos=["repo-a"],
        blocker=blocker,
        dependencies=dependencies or [],
    )


class _StoryListStub:
    def __init__(self, stories: list[Story]) -> None:
        self._stories = stories

    def list_stories(self, project_key: str) -> list[Story]:
        assert project_key == _PROJECT_KEY
        return list(self._stories)


class _ProjectRepoStub:
    def __init__(self, project: Project | None) -> None:
        self._project = project

    def get(self, key: str) -> Project | None:
        if self._project is not None and self._project.key == key:
            return self._project
        return None

    def list(self, *, include_archived: bool = False) -> list[Project]:
        _ = include_archived
        return [self._project] if self._project is not None else []

    def save(self, project: Project) -> None:  # pragma: no cover - unused
        self._project = project


def _project(*, archived: bool = False) -> Project:
    from datetime import UTC, datetime

    return Project(
        key=_PROJECT_KEY,
        name="Tenant A",
        story_id_prefix="AG3",
        configuration=ProjectConfiguration(
            repo_url="",
            default_branch="main",
            default_worker_count=2,
            repositories=["repo-a"],
        ),
        archived_at=datetime.now(UTC) if archived else None,
    )


# ---------------------------------------------------------------------------
# counters_classification
# ---------------------------------------------------------------------------


def test_counters_total_and_simple_status_buckets() -> None:
    stories = [
        _story("AG3-1", StoryStatus.IN_PROGRESS),
        _story("AG3-2", StoryStatus.IN_PROGRESS),
        _story("AG3-3", StoryStatus.DONE),
        _story("AG3-4", StoryStatus.APPROVED),
        _story("AG3-5", StoryStatus.BACKLOG),
    ]
    counters = compute_story_counters(_PROJECT_KEY, stories)
    assert counters.total == 5
    assert counters.running == 2
    assert counters.finished == 1
    assert counters.queue == 1  # all Approved
    # Backlog always blocked.
    assert counters.blocked >= 1


def test_backlog_is_blocked() -> None:
    counters = compute_story_counters(
        _PROJECT_KEY, [_story("AG3-1", StoryStatus.BACKLOG)],
    )
    assert counters.blocked == 1
    assert counters.ready == 0
    assert counters.queue == 0


def test_approved_no_blocker_no_deps_is_ready() -> None:
    counters = compute_story_counters(
        _PROJECT_KEY, [_story("AG3-1", StoryStatus.APPROVED)],
    )
    assert counters.queue == 1
    assert counters.ready == 1
    assert counters.blocked == 0


def test_approved_with_blocker_is_blocked_not_ready() -> None:
    counters = compute_story_counters(
        _PROJECT_KEY,
        [_story("AG3-1", StoryStatus.APPROVED, blocker="waiting on infra")],
    )
    assert counters.queue == 1
    assert counters.ready == 0
    assert counters.blocked == 1


def test_approved_with_open_dependency_is_blocked() -> None:
    stories = [
        _story("AG3-1", StoryStatus.APPROVED),  # dependency, not Done
        _story("AG3-2", StoryStatus.APPROVED, dependencies=["AG3-1"]),
    ]
    counters = compute_story_counters(_PROJECT_KEY, stories)
    assert counters.queue == 2
    assert counters.ready == 1  # AG3-1 itself is ready
    assert counters.blocked == 1  # AG3-2 blocked by open dep


def test_approved_with_done_dependency_is_ready() -> None:
    stories = [
        _story("AG3-1", StoryStatus.DONE),
        _story("AG3-2", StoryStatus.APPROVED, dependencies=["AG3-1"]),
    ]
    counters = compute_story_counters(_PROJECT_KEY, stories)
    assert counters.finished == 1
    assert counters.ready == 1
    assert counters.blocked == 0


def test_approved_with_unresolved_dependency_is_blocked() -> None:
    # Dependency not present in the corpus -> treated as "not Done" (fail-closed).
    stories = [
        _story("AG3-2", StoryStatus.APPROVED, dependencies=["AG3-99"]),
    ]
    counters = compute_story_counters(_PROJECT_KEY, stories)
    assert counters.ready == 0
    assert counters.blocked == 1


def test_counters_empty_corpus() -> None:
    counters = compute_story_counters(_PROJECT_KEY, [])
    assert counters.model_dump() == {
        "project_key": _PROJECT_KEY,
        "total": 0,
        "finished": 0,
        "running": 0,
        "ready": 0,
        "queue": 0,
        "blocked": 0,
    }


# ---------------------------------------------------------------------------
# mode_lock_derived
# ---------------------------------------------------------------------------


def test_mode_lock_idle_when_no_in_progress() -> None:
    stories = [
        _story("AG3-1", StoryStatus.APPROVED),
        _story("AG3-2", StoryStatus.DONE),
        _story("AG3-3", StoryStatus.BACKLOG),
    ]
    assert derive_mode_lock(_PROJECT_KEY, stories).mode == "idle"


def test_mode_lock_fast_when_any_in_progress_fast() -> None:
    stories = [
        _story("AG3-1", StoryStatus.IN_PROGRESS, mode=WireStoryMode.STANDARD),
        _story("AG3-2", StoryStatus.IN_PROGRESS, mode=WireStoryMode.FAST),
    ]
    assert derive_mode_lock(_PROJECT_KEY, stories).mode == "fast"


def test_mode_lock_standard_when_in_progress_without_fast() -> None:
    stories = [
        _story("AG3-1", StoryStatus.IN_PROGRESS, mode=WireStoryMode.STANDARD),
        _story("AG3-2", StoryStatus.IN_PROGRESS, mode=None),
    ]
    assert derive_mode_lock(_PROJECT_KEY, stories).mode == "standard"


def test_mode_lock_empty_corpus_is_idle() -> None:
    assert derive_mode_lock(_PROJECT_KEY, []).mode == "idle"


# ---------------------------------------------------------------------------
# build_project_detail_view
# ---------------------------------------------------------------------------


def test_build_project_detail_view_aggregates() -> None:
    stories = [
        _story("AG3-1", StoryStatus.IN_PROGRESS, mode=WireStoryMode.FAST),
        _story("AG3-2", StoryStatus.APPROVED),
        _story("AG3-3", StoryStatus.DONE),
    ]
    service = ProjectDetailService(
        project_repository=_ProjectRepoStub(_project()),
        story_service=_StoryListStub(stories),
    )
    view = service.build_project_detail_view(_PROJECT_KEY)
    assert view.project_key == _PROJECT_KEY
    assert view.display_name == "Tenant A"
    assert view.status == "active"
    assert view.mode_lock.mode == "fast"
    assert view.story_counters.total == 3
    assert view.story_counters.running == 1
    assert view.story_counters.finished == 1
    assert view.story_counters.ready == 1
    assert view.concept_anchors == []


def test_build_project_detail_view_archived_status() -> None:
    service = ProjectDetailService(
        project_repository=_ProjectRepoStub(_project(archived=True)),
        story_service=_StoryListStub([]),
    )
    view = service.build_project_detail_view(_PROJECT_KEY)
    assert view.status == "archived"
    assert view.mode_lock.mode == "idle"


def test_build_project_detail_view_unknown_project_fails_closed() -> None:
    service = ProjectDetailService(
        project_repository=_ProjectRepoStub(None),
        story_service=_StoryListStub([]),
    )
    with pytest.raises(ProjectNotFoundError):
        service.build_project_detail_view("does-not-exist")
