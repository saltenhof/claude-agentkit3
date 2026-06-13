"""ProjectionAccessor dedicated task-port tests."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest

from agentkit.state_backend.store import reset_backend_cache_for_tests
from agentkit.state_backend.store.projection_repositories import (
    build_projection_repositories,
)
from agentkit.task_management import (
    Task,
    TaskKind,
    TaskOrigin,
    TaskPriority,
    TaskStatus,
)
from agentkit.telemetry.errors import ProjectionRecordTypeMismatchError
from agentkit.telemetry.projection_accessor import ProjectionAccessor, ProjectionKind

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path


@pytest.fixture(autouse=True)
def sqlite_env(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.setenv("AGENTKIT_STATE_BACKEND", "sqlite")
    monkeypatch.setenv("AGENTKIT_ALLOW_SQLITE", "1")
    reset_backend_cache_for_tests()
    yield
    reset_backend_cache_for_tests()


def _task() -> Task:
    return Task(
        project_key="proj-a",
        task_id="TM-2026-0001",
        kind=TaskKind.REMINDER,
        type="concept_update",
        title="Title",
        body="Body",
        priority=TaskPriority.LOW,
        status=TaskStatus.OPEN,
        origin=TaskOrigin.GOVERNANCE,
        created_at=datetime(2026, 6, 9, 10, 0, tzinfo=UTC),
    )


def test_task_port_does_not_extend_projection_kind() -> None:
    # AG3-108 (FK-69 §69.15 Codex-approved): qa_check_outcomes is the 8th
    # FK-69 table. The task port (tm_tasks) must NOT appear in ProjectionKind.
    assert {kind.value for kind in ProjectionKind} == {
        "qa_stage_results",
        "qa_findings",
        "qa_check_outcomes",
        "story_metrics",
        "phase_state_projection",
        "fc_incidents",
        "fc_patterns",
        "fc_check_proposals",
    }


def test_record_task_rejects_wrong_record_type(tmp_path: Path) -> None:
    accessor = ProjectionAccessor(build_projection_repositories(tmp_path))
    with pytest.raises(ProjectionRecordTypeMismatchError) as exc_info:
        accessor.record_task(object())  # type: ignore[arg-type]

    assert exc_info.value.kind == "tm_tasks"
    assert exc_info.value.expected is Task
    assert exc_info.value.received is object


def test_record_task_link_rejects_wrong_record_type(tmp_path: Path) -> None:
    accessor = ProjectionAccessor(build_projection_repositories(tmp_path))
    with pytest.raises(ProjectionRecordTypeMismatchError) as exc_info:
        accessor.record_task_link(_task())  # type: ignore[arg-type]

    assert exc_info.value.kind == "tm_task_links"


def test_dedicated_accessor_task_roundtrip(tmp_path: Path) -> None:
    accessor = ProjectionAccessor(build_projection_repositories(tmp_path))
    task = _task()
    accessor.record_task(task)

    assert accessor.get_task("proj-a", "TM-2026-0001") == task
    assert accessor.list_tasks("proj-a") == [task]
