"""Task-management model contract tests."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from agentkit.task_management import (
    Task,
    TaskKind,
    TaskLink,
    TaskOrigin,
    TaskPriority,
    TaskRelationKind,
    TaskStatus,
    TaskTargetKind,
)


def _task_payload() -> dict[str, object]:
    return {
        "project_key": "proj-a",
        "task_id": "TM-2026-0001",
        "kind": "actionable",
        "type": "concept_update",
        "title": "Clarify boundary",
        "body": "Adjust the prose.",
        "priority": "normal",
        "status": "open",
        "origin": "human",
        "source_story_id": None,
        "execution_report_ref": None,
        "created_at": datetime(2026, 6, 9, 10, 0, tzinfo=UTC),
        "resolved_at": None,
        "resolved_by": None,
    }


def test_task_accepts_exact_formal_spec_fields() -> None:
    task = Task.model_validate(_task_payload())

    assert set(Task.model_fields) == {
        "task_id",
        "project_key",
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
    assert task.kind is TaskKind.ACTIONABLE
    assert task.priority is TaskPriority.NORMAL
    assert task.status is TaskStatus.OPEN
    assert task.origin is TaskOrigin.HUMAN


def test_task_rejects_unknown_and_missing_required_fields() -> None:
    payload = _task_payload()
    payload["owner"] = "agent"
    with pytest.raises(ValidationError):
        Task.model_validate(payload)

    missing = _task_payload()
    del missing["title"]
    with pytest.raises(ValidationError):
        Task.model_validate(missing)


def test_task_rejects_invalid_enum_and_task_id() -> None:
    payload = _task_payload()
    payload["status"] = "reopened"
    with pytest.raises(ValidationError):
        Task.model_validate(payload)

    payload = _task_payload()
    payload["task_id"] = "TASK-1"
    with pytest.raises(ValidationError):
        Task.model_validate(payload)


def test_task_link_accepts_exact_formal_spec_fields() -> None:
    link = TaskLink.model_validate(
        {
            "project_key": "proj-a",
            "task_id": "TM-2026-0001",
            "target_kind": "story",
            "target_id": "AG3-096",
            "kind": "relates_to",
        },
    )

    assert set(TaskLink.model_fields) == {
        "project_key",
        "task_id",
        "target_kind",
        "target_id",
        "kind",
    }
    assert link.target_kind is TaskTargetKind.STORY
    assert link.kind is TaskRelationKind.RELATES_TO


def test_task_link_rejects_artifacts_and_unknown_fields() -> None:
    with pytest.raises(ValidationError):
        TaskLink.model_validate(
            {
                "project_key": "proj-a",
                "task_id": "TM-2026-0001",
                "target_kind": "artifact",
                "target_id": "report.json",
                "kind": "relates_to",
            },
        )

    with pytest.raises(ValidationError):
        TaskLink.model_validate(
            {
                "project_key": "proj-a",
                "task_id": "TM-2026-0001",
                "target_kind": "story",
                "target_id": "AG3-096",
                "kind": "relates_to",
                "status": "open",
            },
        )
