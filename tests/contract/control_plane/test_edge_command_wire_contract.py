"""Contract pins for the Edge-Command-Queue wire vocabulary (FK-91 §91.1b, AG3-145 AC9).

Pins: the six command kinds, the three result types, the quarantine detail
shape and the named takeover error states -- the closed, contract-pinned wire
vocabulary every sibling story (AG3-147/151/152) builds against. Also pins the
``edge_command_records`` row shape (field-exact, no TTL/expiry column) mirroring
the AG3-137 ``test_ownership_record_formats.py`` precedent. Pure and DB-free.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from agentkit.backend.control_plane import edge_commands as ec
from agentkit.backend.control_plane.models import (
    BranchRefReport,
    CommandErrorResult,
    EdgeCommandResultRequest,
    PreflightProbeCommandPayload,
    PreflightProbeReport,
    ProvisionWorktreeCommandPayload,
    PushStatusReport,
    TakeoverErrorResult,
    TakeoverQuarantineDetail,
    TeardownWorktreeCommandPayload,
    WorktreeReport,
)
from agentkit.backend.control_plane.records import EdgeCommandRecord
from agentkit.backend.state_backend.store import mappers

_NOW = datetime(2026, 7, 4, 12, 0, tzinfo=UTC)

# ---------------------------------------------------------------------------
# Six command kinds (initial), FK-91 §91.1b
# ---------------------------------------------------------------------------


@pytest.mark.contract
def test_six_command_kinds_are_pinned() -> None:
    assert {
        "provision_worktree",
        "teardown_worktree",
        "preflight_probe",
        "sync_push",
        "takeover_reconcile",
        "merge_local",
    } == ec.ALL_COMMAND_KINDS


@pytest.mark.contract
def test_an_edge_unknown_command_kind_is_registered_but_not_executable() -> None:
    """Scope item 4: only 3 of the 6 registered kinds are EXECUTED this story."""
    for kind in ("sync_push", "takeover_reconcile", "merge_local"):
        assert ec.is_known_command_kind(kind) is True
        assert ec.is_executable_command_kind(kind) is False


# ---------------------------------------------------------------------------
# Three result types + quarantine detail + named takeover states
# ---------------------------------------------------------------------------


@pytest.mark.contract
def test_branch_ref_report_pins_its_field_shape() -> None:
    report = BranchRefReport(repo_id="repo-a", branch_class="branch_present", head_sha="deadbeef")
    assert report.result_type == "branch_ref_report"
    dumped = report.model_dump(mode="json")
    assert set(dumped) == {"result_type", "repo_id", "branch_class", "head_sha"}


@pytest.mark.contract
def test_push_status_report_pins_its_field_shape() -> None:
    report = PushStatusReport(repo_id="repo-a", push_outcome="pushed")
    assert report.result_type == "push_status_report"
    assert set(report.model_dump(mode="json")) == {"result_type", "repo_id", "push_outcome"}


@pytest.mark.contract
def test_worktree_report_pins_its_field_shape_incl_worktree_root() -> None:
    """FK-56 §56.8: the Edge-reported ``worktree_root`` IS the session's
    ``worktree_roots`` truth -- the backend never derives it itself."""
    report = WorktreeReport(
        repo_id="repo-a",
        outcome="provisioned",
        worktree_root="/wt/AG3-100",
        branch="story/AG3-100",
        head_sha="deadbeef",
        marker_present=True,
    )
    assert report.result_type == "worktree_report"
    assert set(report.model_dump(mode="json")) == {
        "result_type",
        "repo_id",
        "outcome",
        "worktree_root",
        "branch",
        "head_sha",
        "marker_present",
    }


@pytest.mark.contract
def test_result_types_constant_matches_the_three_pinned_models() -> None:
    assert {
        "branch_ref_report",
        "push_status_report",
        "worktree_report",
    } == ec.RESULT_TYPES


@pytest.mark.contract
def test_takeover_quarantine_detail_pins_its_field_shape() -> None:
    detail = TakeoverQuarantineDetail(
        repo_id="repo-a", quarantine_path="/wt/AG3-100/.agentkit-quarantine", reason="dirty_target",
    )
    assert detail.result_type == "takeover_quarantine_detail"
    assert set(detail.model_dump(mode="json")) == {
        "result_type", "repo_id", "quarantine_path", "reason",
    }


@pytest.mark.contract
@pytest.mark.parametrize(
    "result_type",
    [
        "remote_branch_diverged_after_takeover",
        "local_stale_or_dirty_takeover_target",
        "contested_local_writes",
    ],
)
def test_named_takeover_error_states_are_pinned(result_type: str) -> None:
    """FK-30 §30.6.3: benannte Result-Zustaende, kein Sammel-FAIL."""
    result = TakeoverErrorResult(result_type=result_type, repo_id="repo-a")
    assert result.result_type == result_type
    assert result_type in ec.TAKEOVER_ERROR_RESULT_TYPES


@pytest.mark.contract
def test_takeover_error_result_rejects_an_unregistered_state() -> None:
    with pytest.raises(ValidationError):
        TakeoverErrorResult(result_type="made_up_state", repo_id="repo-a")


@pytest.mark.contract
def test_command_error_result_pins_its_field_shape() -> None:
    """Scope item 4: an edge's deterministic error result for an unsupported command."""
    result = CommandErrorResult(error_code="unsupported_command_kind", message="sync_push is not executable by this edge")
    assert result.result_type == "command_error"


@pytest.mark.contract
def test_preflight_probe_report_pins_its_field_shape() -> None:
    """FK-22 §22.3.1: the pure per-repo probe collection (branch + worktree state)."""
    report = PreflightProbeReport(
        repo_id="api",
        branch_present=True,
        head_sha="deadbeef",
        worktree_present=True,
        worktree_path="/wt/AG3-100",
        marker_present=True,
        marker_story_id="AG3-100",
        marker_run_id="run-1",
    )
    assert report.result_type == "preflight_probe_report"
    assert set(report.model_dump(mode="json")) == {
        "result_type",
        "repo_id",
        "branch_present",
        "head_sha",
        "worktree_present",
        "worktree_path",
        "marker_present",
        "marker_story_id",
        "marker_run_id",
    }


@pytest.mark.contract
def test_command_payload_shapes_are_pinned() -> None:
    """FK-91 §91.1b: the typed backend->edge command payloads (per repo)."""
    provision = ProvisionWorktreeCommandPayload(
        story_id="AG3-100", project_key="tenant-a", run_id="run-1",
        repo_id="api", branch="story/AG3-100",
    )
    assert provision.base_ref == "main"  # default
    assert set(provision.model_dump(mode="json")) == {
        "story_id", "project_key", "run_id", "repo_id", "branch", "base_ref",
    }
    teardown = TeardownWorktreeCommandPayload(
        story_id="AG3-100", repo_id="api", branch="story/AG3-100"
    )
    assert set(teardown.model_dump(mode="json")) == {"story_id", "repo_id", "branch"}
    probe = PreflightProbeCommandPayload(
        story_id="AG3-100", repo_id="api", branch="story/AG3-100"
    )
    assert set(probe.model_dump(mode="json")) == {"story_id", "repo_id", "branch"}


# ---------------------------------------------------------------------------
# EdgeCommandResultRequest discriminated union dispatch
# ---------------------------------------------------------------------------


@pytest.mark.contract
@pytest.mark.parametrize(
    ("payload", "expected_type"),
    [
        (
            {"result_type": "branch_ref_report", "repo_id": "repo-a", "branch_class": "no_branch"},
            BranchRefReport,
        ),
        (
            {"result_type": "push_status_report", "repo_id": "repo-a", "push_outcome": "pushed"},
            PushStatusReport,
        ),
        (
            {"result_type": "worktree_report", "repo_id": "repo-a", "outcome": "no_op"},
            WorktreeReport,
        ),
        (
            {"result_type": "preflight_probe_report", "repo_id": "repo-a", "branch_present": False},
            PreflightProbeReport,
        ),
        (
            {
                "result_type": "takeover_quarantine_detail",
                "repo_id": "repo-a",
                "quarantine_path": "/wt/x",
                "reason": "dirty",
            },
            TakeoverQuarantineDetail,
        ),
        (
            {"result_type": "local_stale_or_dirty_takeover_target", "repo_id": "repo-a"},
            TakeoverErrorResult,
        ),
        (
            {"result_type": "command_error", "error_code": "x", "message": "y"},
            CommandErrorResult,
        ),
    ],
)
def test_request_result_discriminator_dispatches_to_the_pinned_model(
    payload: dict[str, object], expected_type: type,
) -> None:
    request = EdgeCommandResultRequest(
        project_key="tenant-a",
        story_id="AG3-100",
        session_id="sess-A",
        op_id="op-1",
        result=payload,
    )
    assert isinstance(request.result, expected_type)


@pytest.mark.contract
def test_op_id_is_mandatory_with_no_server_default() -> None:
    """FK-91 §91.1b / Rule 5: client op_id is mandatory, no default_factory minting."""
    with pytest.raises(ValidationError):
        EdgeCommandResultRequest.model_validate(
            {
                "project_key": "tenant-a",
                "story_id": "AG3-100",
                "session_id": "sess-A",
                "result": {"result_type": "worktree_report", "repo_id": "repo-a", "outcome": "no_op"},
            }
        )
    assert "default_factory" not in repr(EdgeCommandResultRequest.model_fields["op_id"])


# ---------------------------------------------------------------------------
# edge_command_records row shape (field-exact, no TTL column)
# ---------------------------------------------------------------------------

_EDGE_COMMAND_ROW_KEYS = {
    "command_id",
    "project_key",
    "story_id",
    "run_id",
    "session_id",
    "command_kind",
    "payload_json",
    "status",
    "ownership_epoch",
    "created_at",
    "delivered_at",
    "completed_at",
    "result_op_id",
    "result_type",
    "result_payload_json",
}


@pytest.mark.contract
def test_edge_command_row_is_field_exact_and_has_no_ttl() -> None:
    record = EdgeCommandRecord(
        command_id="cmd-1",
        project_key="tenant-a",
        story_id="AG3-100",
        run_id="run-1",
        session_id="sess-A",
        command_kind="provision_worktree",
        payload={"repo_id": "repo-a"},
        status="created",
        ownership_epoch=1,
        created_at=_NOW,
    )
    row = mappers.edge_command_record_to_row(record)
    assert set(row) == _EDGE_COMMAND_ROW_KEYS
    assert not (set(row) & {"ttl", "expiry", "expires_at", "lease_ttl"})
    assert mappers.edge_command_row_to_record(row) == record


@pytest.mark.contract
def test_edge_command_row_round_trips_a_terminal_result() -> None:
    record = EdgeCommandRecord(
        command_id="cmd-1",
        project_key="tenant-a",
        story_id="AG3-100",
        run_id="run-1",
        session_id="sess-A",
        command_kind="preflight_probe",
        payload={},
        status="failed",
        ownership_epoch=2,
        created_at=_NOW,
        delivered_at=_NOW,
        completed_at=_NOW,
        result_op_id="op-9",
        result_type="local_stale_or_dirty_takeover_target",
        result_payload={"repo_id": "repo-a"},
    )
    row = mappers.edge_command_record_to_row(record)
    assert mappers.edge_command_row_to_record(row) == record
