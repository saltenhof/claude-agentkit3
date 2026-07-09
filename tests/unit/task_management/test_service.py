"""Task-management top-surface tests against real SQLite-backed components."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest

from agentkit.backend.core_types import StorySize
from agentkit.backend.state_backend.persistence_test_support import reset_backend_cache_for_tests
from agentkit.backend.state_backend.store.story_repository import StateBackendStoryRepository
from agentkit.backend.state_backend.store.telemetry_projection_repository_misc import (
    build_projection_repositories,
)
from agentkit.backend.story_context_manager.story_model import (
    ChangeImpact,
    ConceptQuality,
    RiskLevel,
    Story,
    StoryStatus,
    WireStoryType,
)
from agentkit.backend.task_management import (
    InvalidTaskLinkTargetError,
    InvalidTaskTransitionError,
    ResolvedBy,
    Task,
    TaskAlreadyExistsError,
    TaskKind,
    TaskLink,
    TaskLinkNotFoundError,
    TaskListFilter,
    TaskManagement,
    TaskNotFoundError,
    TaskOrigin,
    TaskPriority,
    TaskRelationKind,
    TaskStatus,
    TaskTargetKind,
)
from agentkit.backend.telemetry.projection_accessor import ProjectionAccessor

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

_NOW = datetime(2026, 6, 9, 10, 0, tzinfo=UTC)
_DONE_AT = datetime(2026, 6, 9, 11, 0, tzinfo=UTC)


@pytest.fixture()
def service(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[TaskManagement]:
    monkeypatch.setenv("AGENTKIT_STATE_BACKEND", "sqlite")
    monkeypatch.setenv("AGENTKIT_ALLOW_SQLITE", "1")
    reset_backend_cache_for_tests()
    yield TaskManagement(ProjectionAccessor(build_projection_repositories(tmp_path)))
    reset_backend_cache_for_tests()


@pytest.fixture()
def store_dir(tmp_path: Path) -> Path:
    return tmp_path


def _task(
    task_id: str,
    *,
    project_key: str = "proj-a",
    kind: TaskKind = TaskKind.ACTIONABLE,
    type: str = "concept_update",  # noqa: A002
    origin: TaskOrigin = TaskOrigin.HUMAN,
    priority: TaskPriority = TaskPriority.NORMAL,
) -> Task:
    return Task(
        project_key=project_key,
        task_id=task_id,
        kind=kind,
        type=type,
        title=f"Task {task_id}",
        body="Body",
        priority=priority,
        status=TaskStatus.OPEN,
        origin=origin,
        source_story_id=None,
        execution_report_ref=None,
        created_at=_NOW,
        resolved_at=None,
        resolved_by=None,
    )


def _link(
    task_id: str,
    target_kind: TaskTargetKind,
    target_id: str,
    *,
    project_key: str = "proj-a",
    kind: TaskRelationKind = TaskRelationKind.RELATES_TO,
) -> TaskLink:
    return TaskLink(
        project_key=project_key,
        task_id=task_id,
        target_kind=target_kind,
        target_id=target_id,
        kind=kind,
    )


def _save_story(store_dir: Path, project_key: str, story_id: str) -> None:
    story_number = int(story_id.rsplit("-", maxsplit=1)[1])
    StateBackendStoryRepository(store_dir).save(
        Story(
            project_key=project_key,
            story_number=story_number,
            story_display_id=story_id,
            title=story_id,
            story_type=WireStoryType.IMPLEMENTATION,
            status=StoryStatus.APPROVED,
            size=StorySize.M,
            epic="task-management",
            module="task_management",
            participating_repos=["repo"],
            change_impact=ChangeImpact.LOCAL,
            concept_quality=ConceptQuality.HIGH,
            owner="owner",
            risk=RiskLevel.LOW,
            wave=1,
            critical_path=False,
            created_at=_NOW,
        ),
    )


def test_create_get_and_list_tasks_surface(service: TaskManagement) -> None:
    created = service.create_task(_task("TM-2026-0001"))
    assert created.status is TaskStatus.OPEN
    assert service.create_task(created) == created
    assert service.get_task("proj-a", "TM-2026-0001") == created
    assert service.list_tasks("proj-a") == [created]
    assert service.list_tasks("proj-a", TaskListFilter(status=TaskStatus.OPEN)) == [created]
    assert service.list_tasks("proj-a", TaskListFilter(type="concept_update")) == [created]
    assert service.list_tasks("proj-a", TaskListFilter(kind=TaskKind.ACTIONABLE)) == [created]
    assert service.list_tasks("proj-a", TaskListFilter(origin=TaskOrigin.HUMAN)) == [created]


def test_create_task_rejects_non_initial_state(service: TaskManagement) -> None:
    task = _task("TM-2026-0002").model_copy(update={"status": TaskStatus.DONE})
    with pytest.raises(InvalidTaskTransitionError):
        service.create_task(task)


def test_create_task_rejects_conflicting_duplicate(service: TaskManagement) -> None:
    service.create_task(_task("TM-2026-0003"))
    changed = _task("TM-2026-0003").model_copy(update={"title": "Changed"})
    with pytest.raises(TaskAlreadyExistsError):
        service.create_task(changed)


def test_resolve_and_dismiss_valid_transitions(service: TaskManagement) -> None:
    service.create_task(_task("TM-2026-0004"))
    resolved = service.resolve_task(
        "proj-a",
        "TM-2026-0004",
        ResolvedBy.AGENT,
        resolved_at=_DONE_AT,
    )
    assert resolved.status is TaskStatus.DONE
    assert resolved.resolved_by is ResolvedBy.AGENT
    assert resolved.resolved_at == _DONE_AT

    service.create_task(_task("TM-2026-0005"))
    dismissed = service.dismiss_task(
        "proj-a",
        "TM-2026-0005",
        ResolvedBy.HUMAN,
        resolved_at=_DONE_AT,
    )
    assert dismissed.status is TaskStatus.DISMISSED
    assert dismissed.resolved_by is ResolvedBy.HUMAN
    assert dismissed.resolved_at == _DONE_AT


def test_invalid_transitions_and_terminality_fail_closed(service: TaskManagement) -> None:
    service.create_task(_task("TM-2026-0006"))
    service.resolve_task("proj-a", "TM-2026-0006", ResolvedBy.AGENT, resolved_at=_DONE_AT)
    with pytest.raises(InvalidTaskTransitionError):
        service.resolve_task("proj-a", "TM-2026-0006", ResolvedBy.AGENT)
    with pytest.raises(InvalidTaskTransitionError):
        service.dismiss_task("proj-a", "TM-2026-0006", ResolvedBy.AGENT)

    with pytest.raises(TaskNotFoundError):
        service.resolve_task("proj-a", "TM-2026-9999", ResolvedBy.AGENT)


def test_nm_linking_against_stories_and_tasks(
    service: TaskManagement,
    store_dir: Path,
) -> None:
    _save_story(store_dir, "proj-a", "AG3-096")
    _save_story(store_dir, "proj-a", "AG3-097")
    for task_id in ("TM-2026-0007", "TM-2026-0008", "TM-2026-0009"):
        service.create_task(_task(task_id))

    service.link_task(_link("TM-2026-0007", TaskTargetKind.STORY, "AG3-096"))
    service.link_task(
        _link(
            "TM-2026-0007",
            TaskTargetKind.STORY,
            "AG3-097",
            kind=TaskRelationKind.SPAWNED_STORY,
        ),
    )
    service.link_task(_link("TM-2026-0007", TaskTargetKind.TASK, "TM-2026-0008"))
    service.link_task(_link("TM-2026-0008", TaskTargetKind.STORY, "AG3-096"))
    service.link_task(_link("TM-2026-0009", TaskTargetKind.STORY, "AG3-096"))

    linked_to_story = service.list_tasks_for_target("proj-a", TaskTargetKind.STORY, "AG3-096")
    assert [task.task_id for task in linked_to_story] == [
        "TM-2026-0007",
        "TM-2026-0008",
        "TM-2026-0009",
    ]
    linked_to_task = service.list_tasks_for_target("proj-a", TaskTargetKind.TASK, "TM-2026-0008")
    assert [task.task_id for task in linked_to_task] == ["TM-2026-0007"]


def test_link_validation_and_unlink_negative_paths(
    service: TaskManagement,
    store_dir: Path,
) -> None:
    _save_story(store_dir, "proj-a", "AG3-096")
    service.create_task(_task("TM-2026-0010"))

    with pytest.raises(InvalidTaskLinkTargetError):
        service.link_task(_link("TM-2026-0010", TaskTargetKind.STORY, "AG3-404"))
    with pytest.raises(InvalidTaskLinkTargetError):
        service.link_task(_link("TM-2026-0010", TaskTargetKind.TASK, "TM-2026-0404"))
    with pytest.raises(TaskNotFoundError):
        service.link_task(_link("TM-2026-0404", TaskTargetKind.STORY, "AG3-096"))

    link = service.link_task(_link("TM-2026-0010", TaskTargetKind.STORY, "AG3-096"))
    service.unlink_task(link)
    assert service.list_tasks_for_target("proj-a", TaskTargetKind.STORY, "AG3-096") == []
    with pytest.raises(TaskLinkNotFoundError):
        service.unlink_task(link)


def test_link_and_unlink_do_not_change_terminal_status(
    service: TaskManagement,
    store_dir: Path,
) -> None:
    _save_story(store_dir, "proj-a", "AG3-096")
    service.create_task(_task("TM-2026-0011"))
    service.resolve_task("proj-a", "TM-2026-0011", ResolvedBy.AGENT, resolved_at=_DONE_AT)
    link = service.link_task(_link("TM-2026-0011", TaskTargetKind.STORY, "AG3-096"))
    assert service.get_task("proj-a", "TM-2026-0011").status is TaskStatus.DONE
    service.unlink_task(link)
    assert service.get_task("proj-a", "TM-2026-0011").status is TaskStatus.DONE


def test_read_surface_is_project_scoped(
    service: TaskManagement,
) -> None:
    service.create_task(_task("TM-2026-0012", project_key="proj-a"))
    service.create_task(_task("TM-2026-0012", project_key="proj-b"))
    service.create_task(_task("TM-2026-0013", project_key="proj-a"))
    service.create_task(_task("TM-2026-0013", project_key="proj-b"))
    service.link_task(
        _link("TM-2026-0012", TaskTargetKind.TASK, "TM-2026-0013", project_key="proj-a"),
    )
    service.link_task(
        _link("TM-2026-0012", TaskTargetKind.TASK, "TM-2026-0013", project_key="proj-b"),
    )

    assert service.get_task("proj-a", "TM-2026-0012").project_key == "proj-a"
    assert service.get_task("proj-b", "TM-2026-0012").project_key == "proj-b"
    assert [
        task.project_key
        for task in service.list_tasks_for_target(
            "proj-a",
            TaskTargetKind.TASK,
            "TM-2026-0013",
        )
    ] == ["proj-a"]
    assert [
        task.project_key
        for task in service.list_tasks_for_target(
            "proj-b",
            TaskTargetKind.TASK,
            "TM-2026-0013",
        )
    ] == ["proj-b"]


def test_read_methods_require_project_key(service: TaskManagement) -> None:
    with pytest.raises(ValueError, match="project_key"):
        service.get_task("", "TM-2026-0013")
    with pytest.raises(ValueError, match="project_key"):
        service.list_tasks("")
    with pytest.raises(ValueError, match="project_key"):
        service.list_tasks_for_target("", TaskTargetKind.STORY, "AG3-096")
