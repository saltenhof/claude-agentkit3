"""SQLite task-management persistence tests."""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest

from agentkit.backend.state_backend.persistence_test_support import reset_backend_cache_for_tests
from agentkit.backend.state_backend.sqlite_store import _connect
from agentkit.backend.state_backend.store.projection_repositories import (
    build_projection_repositories,
)
from agentkit.backend.task_management import (
    ResolvedBy,
    Task,
    TaskKind,
    TaskLink,
    TaskListFilter,
    TaskManagement,
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


@pytest.fixture(autouse=True)
def sqlite_env(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.setenv("AGENTKIT_STATE_BACKEND", "sqlite")
    monkeypatch.setenv("AGENTKIT_ALLOW_SQLITE", "1")
    reset_backend_cache_for_tests()
    yield
    reset_backend_cache_for_tests()


def _task(task_id: str, *, project_key: str = "proj-a") -> Task:
    return Task(
        project_key=project_key,
        task_id=task_id,
        kind=TaskKind.ACTIONABLE,
        type="concept_update",
        title=task_id,
        body="Body",
        priority=TaskPriority.NORMAL,
        status=TaskStatus.OPEN,
        origin=TaskOrigin.HUMAN,
        source_story_id="AG3-096",
        execution_report_ref="reports/AG3-096.json",
        created_at=_NOW,
        resolved_at=None,
        resolved_by=None,
    )


def test_sqlite_schema_contains_tm_tasks_and_links(tmp_path: Path) -> None:
    with _connect(tmp_path) as conn:
        task_columns = {
            row[1]: {"notnull": bool(row[3]), "pk": int(row[5])}
            for row in conn.execute("PRAGMA table_info(tm_tasks)").fetchall()
        }
        link_columns = {
            row[1]: {"notnull": bool(row[3]), "pk": int(row[5])}
            for row in conn.execute("PRAGMA table_info(tm_task_links)").fetchall()
        }
        link_fks = [
            tuple(row)
            for row in conn.execute("PRAGMA foreign_key_list(tm_task_links)").fetchall()
        ]

    assert set(task_columns) == {
        "project_key",
        "task_id",
        "kind",
        "type",
        "title",
        "body",
        "priority",
        "status",
        "origin",
        "source_story_id",
        "execution_report_ref",
        "created_at",
        "resolved_at",
        "resolved_by",
    }
    assert task_columns["project_key"]["pk"] == 1
    assert task_columns["task_id"]["pk"] == 2
    assert set(link_columns) == {
        "project_key",
        "task_id",
        "target_kind",
        "target_id",
        "kind",
    }
    assert link_columns["project_key"]["pk"] == 1
    assert link_columns["task_id"]["pk"] == 2
    assert link_columns["target_kind"]["pk"] == 3
    assert link_columns["target_id"]["pk"] == 4
    assert link_columns["kind"]["pk"] == 5
    assert "status" not in link_columns
    assert any(fk[2] == "tm_tasks" and fk[3] == "project_key" for fk in link_fks)
    assert any(fk[2] == "tm_tasks" and fk[3] == "task_id" for fk in link_fks)


def test_sqlite_schema_rejects_bad_task_and_link_rows(tmp_path: Path) -> None:
    with _connect(tmp_path) as conn:
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                """
                INSERT INTO tm_tasks (
                    project_key, task_id, kind, type, title, body, priority,
                    status, origin, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    "proj-a",
                    "BAD-1",
                    "actionable",
                    "concept_update",
                    "t",
                    "b",
                    "normal",
                    "open",
                    "human",
                    _NOW.isoformat(),
                ),
            )
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                """
                INSERT INTO tm_task_links (
                    project_key, task_id, target_kind, target_id, kind
                ) VALUES (?, ?, ?, ?, ?)
                """,
                ("proj-a", "TM-2026-9999", "story", "AG3-096", "relates_to"),
            )


def test_dedicated_task_port_roundtrip_sqlite(tmp_path: Path) -> None:
    service = TaskManagement(ProjectionAccessor(build_projection_repositories(tmp_path)))
    task = service.create_task(_task("TM-2026-0001"))
    resolved = service.resolve_task(
        "proj-a",
        "TM-2026-0001",
        ResolvedBy.AGENT,
        resolved_at=datetime(2026, 6, 9, 11, 0, tzinfo=UTC),
    )

    assert service.get_task("proj-a", "TM-2026-0001") == resolved
    assert service.list_tasks("proj-a", TaskListFilter(status=TaskStatus.DONE)) == [
        resolved,
    ]
    assert task.status is TaskStatus.OPEN


def test_task_link_roundtrip_sqlite(tmp_path: Path) -> None:
    service = TaskManagement(ProjectionAccessor(build_projection_repositories(tmp_path)))
    service.create_task(_task("TM-2026-0002"))
    service.create_task(_task("TM-2026-0003"))
    link = service.link_task(
        TaskLink(
            project_key="proj-a",
            task_id="TM-2026-0002",
            target_kind=TaskTargetKind.TASK,
            target_id="TM-2026-0003",
            kind=TaskRelationKind.DUPLICATE_OF,
        ),
    )

    assert [
        task.task_id
        for task in service.list_tasks_for_target(
            "proj-a",
            TaskTargetKind.TASK,
            "TM-2026-0003",
        )
    ] == ["TM-2026-0002"]
    service.unlink_task(link)
    assert service.list_tasks_for_target("proj-a", TaskTargetKind.TASK, "TM-2026-0003") == []


def test_list_task_links_project_wide_sqlite(tmp_path: Path) -> None:
    """AG3-105/AC4: project-wide link read hydrates outgoing links per task."""
    service = TaskManagement(ProjectionAccessor(build_projection_repositories(tmp_path)))
    for task_id in ("TM-2026-0020", "TM-2026-0021", "TM-2026-0022"):
        service.create_task(_task(task_id))
    # Two outgoing links on TM-2026-0020, one on TM-2026-0021, none on TM-2026-0022.
    service.link_task(
        TaskLink(
            project_key="proj-a",
            task_id="TM-2026-0020",
            target_kind=TaskTargetKind.TASK,
            target_id="TM-2026-0021",
            kind=TaskRelationKind.RELATES_TO,
        ),
    )
    service.link_task(
        TaskLink(
            project_key="proj-a",
            task_id="TM-2026-0020",
            target_kind=TaskTargetKind.TASK,
            target_id="TM-2026-0022",
            kind=TaskRelationKind.DUPLICATE_OF,
        ),
    )
    service.link_task(
        TaskLink(
            project_key="proj-a",
            task_id="TM-2026-0021",
            target_kind=TaskTargetKind.TASK,
            target_id="TM-2026-0022",
            kind=TaskRelationKind.RELATES_TO,
        ),
    )
    # Tenant isolation: an identically keyed task in another project must not leak.
    service.create_task(_task("TM-2026-0020", project_key="proj-b"))
    service.create_task(_task("TM-2026-0021", project_key="proj-b"))
    service.link_task(
        TaskLink(
            project_key="proj-b",
            task_id="TM-2026-0020",
            target_kind=TaskTargetKind.TASK,
            target_id="TM-2026-0021",
            kind=TaskRelationKind.RELATES_TO,
        ),
    )

    links = service.list_task_links("proj-a")
    # Deterministic ordering: (task_id, target_kind, target_id, kind).
    assert [(link.task_id, link.target_id, link.kind.value) for link in links] == [
        ("TM-2026-0020", "TM-2026-0021", "relates_to"),
        ("TM-2026-0020", "TM-2026-0022", "duplicate_of"),
        ("TM-2026-0021", "TM-2026-0022", "relates_to"),
    ]
    assert all(link.project_key == "proj-a" for link in links)
    # Other project is strictly partitioned.
    assert [link.task_id for link in service.list_task_links("proj-b")] == ["TM-2026-0020"]


def test_list_task_links_requires_project_key(tmp_path: Path) -> None:
    service = TaskManagement(ProjectionAccessor(build_projection_repositories(tmp_path)))
    with pytest.raises(ValueError, match="project_key"):
        service.list_task_links("")
