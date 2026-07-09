"""Integration: AG3-147 push-freshness WRITE path against REAL Postgres.

The load-bearing wiring proof (In-Scope #3): a ``sync_push`` result submitted
through the PUBLIC :class:`ControlPlaneRuntimeService.submit_command_result`
API projects a ``push_status_report`` into the Postgres-only push-freshness read
model (``_commit_command_result`` -> ``project_push_freshness`` ->
``upsert_push_freshness_record_global``), behind the K5 Postgres guard and
inside the Rule-15 ownership fence. Covers the ``pushed`` advance and the
``behind_remote`` visible-backlog projection (AC3/AC4).

``tests/integration/control_plane/`` is NOT in the conftest Postgres
auto-attach allow-list, so this module requests the isolation fixture explicitly.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from agentkit.backend.control_plane.models import (
    CommandErrorResult,
    EdgeCommandResultRequest,
    PushStatusReport,
)
from agentkit.backend.control_plane.ownership import (
    OwnershipAcquisition,
    OwnershipStatus,
)
from agentkit.backend.control_plane.records import (
    EdgeCommandRecord,
    RunOwnershipRecord,
)
from agentkit.backend.control_plane.runtime import ControlPlaneRuntimeService
from agentkit.backend.state_backend.harness_edge_command_store import insert_edge_command_record_global
from agentkit.backend.state_backend.story_closure_store import list_push_freshness_records_global
from agentkit.backend.state_backend.story_lifecycle_store import insert_run_ownership_record_global

pytestmark = pytest.mark.integration

_NOW = datetime(2026, 7, 6, 10, 0, tzinfo=UTC)
_PROJECT = "tenant-a"
_STORY = "AG3-147"
_RUN = "run-1"
_SESSION = "sess-A"
_SHA_A = "a" * 40
_SHA_B = "b" * 40


@pytest.fixture(autouse=True)
def _isolated_postgres(postgres_isolated_schema: object) -> None:
    del postgres_isolated_schema


def _seed_owner_and_command(command_id: str) -> None:
    insert_run_ownership_record_global(
        RunOwnershipRecord(
            project_key=_PROJECT,
            story_id=_STORY,
            run_id=_RUN,
            owner_session_id=_SESSION,
            ownership_epoch=1,
            status=OwnershipStatus.ACTIVE,
            acquired_via=OwnershipAcquisition.SETUP,
            acquired_at=_NOW,
            audit_ref="audit:x",
        )
    )
    insert_edge_command_record_global(
        EdgeCommandRecord(
            command_id=command_id,
            project_key=_PROJECT,
            story_id=_STORY,
            run_id=_RUN,
            session_id=_SESSION,
            command_kind="sync_push",
            payload={"repo_id": "repo-a"},
            status="created",
            ownership_epoch=1,
            created_at=_NOW,
        )
    )


def _result_request(*, op_id: str, outcome: str, head_sha: str | None) -> EdgeCommandResultRequest:
    return EdgeCommandResultRequest(
        project_key=_PROJECT,
        story_id=_STORY,
        session_id=_SESSION,
        op_id=op_id,
        result=PushStatusReport(repo_id="repo-a", push_outcome=outcome, head_sha=head_sha),  # type: ignore[arg-type]
    )


def test_sync_push_pushed_result_writes_push_freshness() -> None:
    """AC3: a ``pushed`` sync_push result advances the freshness pushed head."""
    _seed_owner_and_command("run-1::sync_push::phase_completion:op-1::repo-a")
    service = ControlPlaneRuntimeService()

    outcome = service.submit_command_result(
        "run-1::sync_push::phase_completion:op-1::repo-a",
        _result_request(op_id="op-1", outcome="pushed", head_sha=_SHA_A),
    )

    assert outcome.status == "completed"
    rows = list_push_freshness_records_global(_PROJECT, _STORY, _RUN)
    assert len(rows) == 1
    row = rows[0]
    assert row.repo_id == "repo-a"
    assert row.last_reported_head_sha == _SHA_A
    assert row.last_pushed_head_sha == _SHA_A
    assert row.last_sync_point_id == "phase_completion:op-1"
    assert row.last_command_id == "run-1::sync_push::phase_completion:op-1::repo-a"
    assert row.backlog is False


def test_sync_push_behind_remote_result_writes_visible_backlog() -> None:
    """AC4: a ``behind_remote`` result raises a visible backlog, preserving the
    last known pushed head."""
    _seed_owner_and_command("run-1::sync_push::phase_completion:op-1::repo-a")
    service = ControlPlaneRuntimeService()
    service.submit_command_result(
        "run-1::sync_push::phase_completion:op-1::repo-a",
        _result_request(op_id="op-1", outcome="pushed", head_sha=_SHA_A),
    )
    # A second sync_push command reports a backlog for the same repo.
    insert_edge_command_record_global(
        EdgeCommandRecord(
            command_id="run-1::sync_push::phase_completion:op-2::repo-a",
            project_key=_PROJECT,
            story_id=_STORY,
            run_id=_RUN,
            session_id=_SESSION,
            command_kind="sync_push",
            payload={"repo_id": "repo-a"},
            status="created",
            ownership_epoch=1,
            created_at=_NOW,
        )
    )

    service.submit_command_result(
        "run-1::sync_push::phase_completion:op-2::repo-a",
        _result_request(op_id="op-2", outcome="behind_remote", head_sha=_SHA_B),
    )

    rows = list_push_freshness_records_global(_PROJECT, _STORY, _RUN)
    assert len(rows) == 1
    row = rows[0]
    assert row.backlog is True
    assert row.backlog_detail is not None
    assert row.last_reported_head_sha == _SHA_B
    assert row.last_sync_point_id == "phase_completion:op-2"
    # The last known pushed head is preserved across the backlog report.
    assert row.last_pushed_head_sha == _SHA_A


def test_sync_push_command_error_writes_visible_backlog() -> None:
    """A post-gate git failure must not leave a stale successful freshness row."""
    _seed_owner_and_command("run-1::sync_push::phase_completion:op-1::repo-a")
    service = ControlPlaneRuntimeService()
    service.submit_command_result(
        "run-1::sync_push::phase_completion:op-1::repo-a",
        _result_request(op_id="op-1", outcome="pushed", head_sha=_SHA_A),
    )
    insert_edge_command_record_global(
        EdgeCommandRecord(
            command_id="run-1::sync_push::phase_completion:op-2::repo-a",
            project_key=_PROJECT,
            story_id=_STORY,
            run_id=_RUN,
            session_id=_SESSION,
            command_kind="sync_push",
            payload={"repo_id": "repo-a"},
            status="created",
            ownership_epoch=1,
            created_at=_NOW,
        )
    )

    service.submit_command_result(
        "run-1::sync_push::phase_completion:op-2::repo-a",
        EdgeCommandResultRequest(
            project_key=_PROJECT,
            story_id=_STORY,
            session_id=_SESSION,
            op_id="op-2",
            result=CommandErrorResult(
                error_code="command_execution_failed",
                message="sync_push failed: rev-parse HEAD failed",
            ),
        ),
    )

    row = list_push_freshness_records_global(_PROJECT, _STORY, _RUN)[0]
    assert row.backlog is True
    assert row.last_reported_head_sha is None
    assert row.last_pushed_head_sha == _SHA_A
    assert row.last_sync_point_id == "phase_completion:op-2"
    assert row.last_command_id == "run-1::sync_push::phase_completion:op-2::repo-a"
