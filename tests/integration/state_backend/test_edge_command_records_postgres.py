"""Integration: AG3-145 Edge-Command-Queue row functions against REAL Postgres.

Exercises the transactional AT/T mechanics that only a real Postgres can prove:

* AC1 -- ``list_and_ack_open_edge_command_records_global`` acks delivery
  (``created`` -> ``delivered``) as part of the SAME read, and a foreign
  ``session_id`` (or a mismatched ``project_key``) matches zero rows.
* AC2 -- ``commit_edge_command_result_global`` atomically commits the
  op-ledger row AND the command-result CAS; an unknown/already-terminal
  ``command_id`` raises :class:`EdgeCommandNotOpenError` and rolls back the
  WHOLE transaction (no orphan op-ledger entry).
* AC3 (no TOCTOU) -- the commit-time Rule-15 fence
  (``_enforce_ownership_fence_row``, reused verbatim from AG3-142) rejects a
  stale/ex-owner snapshot with NOTHING committed -- neither the op row nor the
  command-result CAS.

The ``postgres_isolated_schema`` fixture is auto-attached to every
``/integration/state_backend/`` item (``tests/integration/conftest.py``).
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from agentkit.backend.control_plane.ownership import OwnershipAcquisition, OwnershipStatus
from agentkit.backend.control_plane.records import ControlPlaneOperationRecord, EdgeCommandRecord, RunOwnershipRecord
from agentkit.backend.exceptions import EdgeCommandNotOpenError, OwnershipFenceViolationError
from agentkit.backend.state_backend.store import (
    commit_edge_command_result_global,
    insert_edge_command_record_global,
    insert_run_ownership_record_global,
    list_and_ack_open_edge_command_records_global,
    load_control_plane_operation_global,
    load_edge_command_record_global,
)

pytestmark = pytest.mark.integration

_NOW = datetime(2026, 7, 4, 10, 0, tzinfo=UTC)


def _command(
    command_id: str,
    *,
    project_key: str = "tenant-a",
    story_id: str = "AG3-700",
    run_id: str = "run-700",
    session_id: str = "sess-A",
    status: str = "created",
    command_kind: str = "provision_worktree",
) -> EdgeCommandRecord:
    return EdgeCommandRecord(
        command_id=command_id,
        project_key=project_key,
        story_id=story_id,
        run_id=run_id,
        session_id=session_id,
        command_kind=command_kind,
        payload={"repo_id": "repo-a"},
        status=status,
        ownership_epoch=1,
        created_at=_NOW,
    )


def _ownership_record(
    *,
    story_id: str = "AG3-700",
    run_id: str = "run-700",
    owner_session_id: str = "sess-A",
    epoch: int = 1,
) -> RunOwnershipRecord:
    return RunOwnershipRecord(
        project_key="tenant-a",
        story_id=story_id,
        run_id=run_id,
        owner_session_id=owner_session_id,
        ownership_epoch=epoch,
        status=OwnershipStatus.ACTIVE,
        acquired_via=OwnershipAcquisition.SETUP,
        acquired_at=_NOW,
        audit_ref="audit:x",
    )


def _op_record(
    op_id: str,
    *,
    project_key: str = "tenant-a",
    story_id: str = "AG3-700",
    run_id: str = "run-700",
    session_id: str = "sess-A",
) -> ControlPlaneOperationRecord:
    return ControlPlaneOperationRecord(
        op_id=op_id,
        project_key=project_key,
        story_id=story_id,
        run_id=run_id,
        session_id=session_id,
        operation_kind="edge_command_result",
        phase=None,
        status="committed",
        response_payload={"status": "completed", "command_id": "cmd-x"},
        created_at=_NOW,
        updated_at=_NOW,
    )


# ---------------------------------------------------------------------------
# Insert / load round trip
# ---------------------------------------------------------------------------


def test_insert_and_load_round_trips_a_command_record() -> None:
    insert_edge_command_record_global(_command("cmd-pg-1"))

    loaded = load_edge_command_record_global("cmd-pg-1")

    assert loaded is not None
    assert loaded.command_kind == "provision_worktree"
    assert loaded.status == "created"
    assert loaded.delivered_at is None
    assert loaded.completed_at is None


# ---------------------------------------------------------------------------
# AC1: GET ack semantics + fail-closed session scoping
# ---------------------------------------------------------------------------


def test_list_and_ack_flips_created_to_delivered_and_stamps_once() -> None:
    insert_edge_command_record_global(_command("cmd-pg-2"))

    first = list_and_ack_open_edge_command_records_global(
        project_key="tenant-a", run_id="run-700", session_id="sess-A", delivered_at=_NOW,
    )
    assert len(first) == 1
    assert first[0].status == "delivered"
    first_delivered_at = first[0].delivered_at
    assert first_delivered_at is not None

    later = datetime(2026, 7, 4, 11, 0, tzinfo=UTC)
    second = list_and_ack_open_edge_command_records_global(
        project_key="tenant-a", run_id="run-700", session_id="sess-A", delivered_at=later,
    )
    assert len(second) == 1
    #: The FIRST delivered_at is preserved -- a re-fetch never overwrites it.
    assert second[0].delivered_at == first_delivered_at


def test_list_and_ack_foreign_session_matches_zero_rows() -> None:
    insert_edge_command_record_global(_command("cmd-pg-3", session_id="sess-A"))

    foreign = list_and_ack_open_edge_command_records_global(
        project_key="tenant-a", run_id="run-700", session_id="sess-FOREIGN", delivered_at=_NOW,
    )

    assert foreign == ()
    #: The foreign query never touched the row.
    stored = load_edge_command_record_global("cmd-pg-3")
    assert stored is not None
    assert stored.status == "created"


def test_list_and_ack_terminal_commands_are_excluded() -> None:
    command = _command("cmd-pg-4", status="completed")
    insert_edge_command_record_global(command)

    open_commands = list_and_ack_open_edge_command_records_global(
        project_key="tenant-a", run_id="run-700", session_id="sess-A", delivered_at=_NOW,
    )

    assert open_commands == ()


# ---------------------------------------------------------------------------
# AC2: commit_edge_command_result_global -- atomic op-ledger + command CAS
# ---------------------------------------------------------------------------


def test_commit_result_atomically_writes_op_row_and_command_row() -> None:
    insert_run_ownership_record_global(_ownership_record(story_id="AG3-701", run_id="run-701"))
    insert_edge_command_record_global(
        _command("cmd-pg-5", story_id="AG3-701", run_id="run-701", status="delivered")
    )

    commit_edge_command_result_global(
        _op_record("op-pg-1", story_id="AG3-701", run_id="run-701"),
        command_id="cmd-pg-5",
        result_status="completed",
        completed_at=_NOW,
        result_op_id="op-pg-1",
        result_type="worktree_report",
        result_payload={"repo_id": "repo-a", "outcome": "provisioned"},
        expected_ownership_epoch=1,
    )

    stored_op = load_control_plane_operation_global("op-pg-1")
    assert stored_op is not None
    assert stored_op.status == "committed"
    stored_command = load_edge_command_record_global("cmd-pg-5")
    assert stored_command is not None
    assert stored_command.status == "completed"
    assert stored_command.result_op_id == "op-pg-1"
    assert stored_command.result_payload == {"repo_id": "repo-a", "outcome": "provisioned"}


def test_commit_result_unknown_command_id_raises_and_writes_nothing() -> None:
    insert_run_ownership_record_global(_ownership_record(story_id="AG3-702", run_id="run-702"))

    with pytest.raises(EdgeCommandNotOpenError):
        commit_edge_command_result_global(
            _op_record("op-pg-2", story_id="AG3-702", run_id="run-702"),
            command_id="cmd-missing",
            result_status="completed",
            completed_at=_NOW,
            result_op_id="op-pg-2",
            result_type="worktree_report",
            result_payload={},
            expected_ownership_epoch=1,
        )

    #: The WHOLE transaction rolled back -- no orphan op-ledger row.
    assert load_control_plane_operation_global("op-pg-2") is None


def test_commit_result_double_completion_raises_and_writes_nothing() -> None:
    insert_run_ownership_record_global(_ownership_record(story_id="AG3-703", run_id="run-703"))
    insert_edge_command_record_global(
        _command("cmd-pg-6", story_id="AG3-703", run_id="run-703", status="delivered")
    )
    commit_edge_command_result_global(
        _op_record("op-pg-3", story_id="AG3-703", run_id="run-703"),
        command_id="cmd-pg-6",
        result_status="completed",
        completed_at=_NOW,
        result_op_id="op-pg-3",
        result_type="worktree_report",
        result_payload={},
        expected_ownership_epoch=1,
    )

    with pytest.raises(EdgeCommandNotOpenError):
        commit_edge_command_result_global(
            _op_record("op-pg-4", story_id="AG3-703", run_id="run-703"),
            command_id="cmd-pg-6",
            result_status="completed",
            completed_at=_NOW,
            result_op_id="op-pg-4",
            result_type="worktree_report",
            result_payload={},
            expected_ownership_epoch=1,
        )

    #: The second (rejected) attempt's op-ledger row was never committed.
    assert load_control_plane_operation_global("op-pg-4") is None
    stored_command = load_edge_command_record_global("cmd-pg-6")
    assert stored_command is not None
    assert stored_command.result_op_id == "op-pg-3"  # unchanged by the rejected attempt


# ---------------------------------------------------------------------------
# AC3 (no TOCTOU): the Rule-15 fence rejects a stale/ex-owner snapshot
# ---------------------------------------------------------------------------


def test_commit_result_wrong_owner_fence_violation_writes_nothing() -> None:
    insert_run_ownership_record_global(
        _ownership_record(story_id="AG3-704", run_id="run-704", owner_session_id="sess-REAL-OWNER")
    )
    insert_edge_command_record_global(
        _command(
            "cmd-pg-7", story_id="AG3-704", run_id="run-704", session_id="sess-REAL-OWNER", status="delivered",
        )
    )

    with pytest.raises(OwnershipFenceViolationError) as excinfo:
        commit_edge_command_result_global(
            _op_record(
                "op-pg-5", story_id="AG3-704", run_id="run-704", session_id="sess-IMPOSTOR",
            ),
            command_id="cmd-pg-7",
            result_status="completed",
            completed_at=_NOW,
            result_op_id="op-pg-5",
            result_type="worktree_report",
            result_payload={},
            expected_ownership_epoch=1,
        )

    assert excinfo.value.detail["current_owner_session_id"] == "sess-REAL-OWNER"
    #: NOTHING committed: no op row, and the command stays open/untouched.
    assert load_control_plane_operation_global("op-pg-5") is None
    stored_command = load_edge_command_record_global("cmd-pg-7")
    assert stored_command is not None
    assert stored_command.status == "delivered"
    assert stored_command.result_op_id is None


def test_commit_result_stale_epoch_fence_violation_writes_nothing() -> None:
    """AC3 (no TOCTOU): a takeover landed between admission and commit."""
    insert_run_ownership_record_global(
        _ownership_record(story_id="AG3-705", run_id="run-705", owner_session_id="sess-A", epoch=1)
    )
    insert_edge_command_record_global(
        _command("cmd-pg-8", story_id="AG3-705", run_id="run-705", status="delivered")
    )

    with pytest.raises(OwnershipFenceViolationError) as excinfo:
        commit_edge_command_result_global(
            _op_record("op-pg-6", story_id="AG3-705", run_id="run-705"),
            command_id="cmd-pg-8",
            result_status="completed",
            completed_at=_NOW,
            result_op_id="op-pg-6",
            result_type="worktree_report",
            result_payload={},
            # The caller observed epoch=1 at admission, but the row moved on.
            expected_ownership_epoch=2,
        )

    assert excinfo.value.detail["current_ownership_epoch"] == 1
    assert load_control_plane_operation_global("op-pg-6") is None
    stored_command = load_edge_command_record_global("cmd-pg-8")
    assert stored_command is not None
    assert stored_command.status == "delivered"
