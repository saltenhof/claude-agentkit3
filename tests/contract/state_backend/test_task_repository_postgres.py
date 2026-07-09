"""Postgres contract tests for task-management persistence."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest

from agentkit.backend.state_backend.store.telemetry_projection_repository_misc import (
    build_projection_repositories,
)
from agentkit.backend.task_management import (
    ResolvedBy,
    Task,
    TaskKind,
    TaskLink,
    TaskManagement,
    TaskOrigin,
    TaskPriority,
    TaskRelationKind,
    TaskStatus,
    TaskTargetKind,
)
from agentkit.backend.telemetry.projection_accessor import ProjectionAccessor

if TYPE_CHECKING:
    from pathlib import Path

pytest_plugins = ("tests.fixtures.postgres_backend",)

_NOW = datetime(2026, 6, 9, 10, 0, tzinfo=UTC)


def _task(task_id: str, *, project_key: str = "proj-pg") -> Task:
    return Task(
        project_key=project_key,
        task_id=task_id,
        kind=TaskKind.ACTIONABLE,
        type="concept_update",
        title=task_id,
        body="Body",
        priority=TaskPriority.HIGH,
        status=TaskStatus.OPEN,
        origin=TaskOrigin.VERIFY,
        source_story_id=None,
        execution_report_ref=None,
        created_at=_NOW,
        resolved_at=None,
        resolved_by=None,
    )


@pytest.mark.contract
def test_postgres_task_tables_exist(postgres_backend_env: object) -> None:
    from agentkit.backend.state_backend.store.telemetry_projection_repository_common import _postgres_connect

    with _postgres_connect() as conn:
        tables = {
            row["table_name"]
            for row in conn.execute(
                """
                SELECT table_name
                FROM information_schema.tables
                WHERE table_name IN ('tm_tasks', 'tm_task_links')
                """,
            ).fetchall()
        }
        link_columns = {
            row["column_name"]
            for row in conn.execute(
                """
                SELECT column_name
                FROM information_schema.columns
                WHERE table_name = 'tm_task_links'
                """,
            ).fetchall()
        }

    assert tables == {"tm_tasks", "tm_task_links"}
    assert "status" not in link_columns


@pytest.mark.contract
def test_postgres_dedicated_task_port_roundtrip(
    tmp_path: Path,
    postgres_backend_env: object,
) -> None:
    service = TaskManagement(ProjectionAccessor(build_projection_repositories(tmp_path)))
    service.create_task(_task("TM-2026-0001"))
    service.create_task(_task("TM-2026-0002"))
    link = service.link_task(
        TaskLink(
            project_key="proj-pg",
            task_id="TM-2026-0001",
            target_kind=TaskTargetKind.TASK,
            target_id="TM-2026-0002",
            kind=TaskRelationKind.RELATES_TO,
        ),
    )
    closed = service.resolve_task(
        "proj-pg",
        "TM-2026-0001",
        ResolvedBy.AGENT,
        resolved_at=datetime(2026, 6, 9, 11, 0, tzinfo=UTC),
    )

    assert service.get_task("proj-pg", "TM-2026-0001") == closed
    assert [
        task.task_id
        for task in service.list_tasks_for_target(
            "proj-pg",
            TaskTargetKind.TASK,
            "TM-2026-0002",
        )
    ] == ["TM-2026-0001"]
    service.unlink_task(link)
    assert service.list_tasks_for_target("proj-pg", TaskTargetKind.TASK, "TM-2026-0002") == []


@pytest.mark.contract
def test_postgres_list_task_links_parity(
    tmp_path: Path,
    postgres_backend_env: object,
) -> None:
    """AG3-105/AC4 parity: project-wide link read on Postgres matches the SQLite
    contract (deterministic order, project partition, row->model mapping)."""
    service = TaskManagement(ProjectionAccessor(build_projection_repositories(tmp_path)))
    for task_id in ("TM-2026-0010", "TM-2026-0011", "TM-2026-0012"):
        service.create_task(_task(task_id))
    service.link_task(
        TaskLink(
            project_key="proj-pg",
            task_id="TM-2026-0010",
            target_kind=TaskTargetKind.TASK,
            target_id="TM-2026-0011",
            kind=TaskRelationKind.RELATES_TO,
        ),
    )
    service.link_task(
        TaskLink(
            project_key="proj-pg",
            task_id="TM-2026-0010",
            target_kind=TaskTargetKind.TASK,
            target_id="TM-2026-0012",
            kind=TaskRelationKind.DUPLICATE_OF,
        ),
    )
    service.link_task(
        TaskLink(
            project_key="proj-pg",
            task_id="TM-2026-0011",
            target_kind=TaskTargetKind.TASK,
            target_id="TM-2026-0012",
            kind=TaskRelationKind.RELATES_TO,
        ),
    )
    # Tenant isolation across project partitions.
    service.create_task(_task("TM-2026-0010", project_key="proj-pg-other"))
    service.create_task(_task("TM-2026-0011", project_key="proj-pg-other"))
    service.link_task(
        TaskLink(
            project_key="proj-pg-other",
            task_id="TM-2026-0010",
            target_kind=TaskTargetKind.TASK,
            target_id="TM-2026-0011",
            kind=TaskRelationKind.RELATES_TO,
        ),
    )

    links = service.list_task_links("proj-pg")
    assert [(link.task_id, link.target_id, link.kind.value) for link in links] == [
        ("TM-2026-0010", "TM-2026-0011", "relates_to"),
        ("TM-2026-0010", "TM-2026-0012", "duplicate_of"),
        ("TM-2026-0011", "TM-2026-0012", "relates_to"),
    ]
    assert all(link.project_key == "proj-pg" for link in links)
    assert [link.task_id for link in service.list_task_links("proj-pg-other")] == ["TM-2026-0010"]
