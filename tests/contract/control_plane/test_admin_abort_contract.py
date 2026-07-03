"""Contract tests for the AG3-138 ``admin_abort_inflight_operation`` payloads.

Pins the stable request/response/error shapes of
``POST /v1/project-edge/operations/{op_id}/admin-abort`` (FK-91 §91.1a, FK-55
§55.5 ``admin_transition``): the audited request, the terminal
``aborted`` / ``repair`` / ``resolved`` result carrying the machine-readable
``admin_note``, and the ``edge_bundle``-optionality invariant that a
non-materializing terminal result never carries an edge bundle (``resolved`` is
the productive repair-lock exit, AC10). ARCH-55: all wire keys / status tokens /
error codes are English.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from agentkit.backend.control_plane.models import (
    AdminAbortRequest,
    ControlPlaneMutationResult,
    EdgeBundle,
    EdgePointer,
)


def _valid_edge_bundle() -> EdgeBundle:
    """A minimal, schema-valid edge bundle (to exercise the model invariant)."""
    now = datetime(2026, 7, 3, 10, 0, tzinfo=UTC)
    return EdgeBundle(
        current=EdgePointer(
            project_key="tenant-a",
            export_version="edge-1",
            operating_mode="ai_augmented",
            bundle_dir="_temp/governance/bundles/edge-1",
            sync_after=now,
            freshness_class="mutation",
            generated_at=now,
        ),
    )


@pytest.mark.contract
def test_admin_abort_request_is_frozen_extra_forbid_and_audited() -> None:
    """The request pins an audited actor + mandatory reason; unknown keys rejected."""
    request = AdminAbortRequest(
        session_id="admin-sess-1",
        principal_type="operator",
        reason="hung executor; operator decision",
    )
    assert request.source_component == "project_edge_client"
    payload = request.model_dump(mode="json")
    assert payload == {
        "session_id": "admin-sess-1",
        "principal_type": "operator",
        "reason": "hung executor; operator decision",
        "source_component": "project_edge_client",
    }
    # extra="forbid": an unknown wire key is rejected fail-closed.
    with pytest.raises(ValidationError):
        AdminAbortRequest.model_validate(
            {
                "session_id": "s",
                "principal_type": "operator",
                "reason": "r",
                "unexpected": "x",
            },
        )


@pytest.mark.contract
@pytest.mark.parametrize("field", ["session_id", "principal_type", "reason"])
def test_admin_abort_request_rejects_empty_mandatory_fields(field: str) -> None:
    """AC6: the audited actor and the justification are mandatory (min_length=1)."""
    base = {
        "session_id": "admin-sess-1",
        "principal_type": "operator",
        "reason": "hung executor",
    }
    base[field] = ""
    with pytest.raises(ValidationError):
        AdminAbortRequest.model_validate(base)


@pytest.mark.contract
@pytest.mark.parametrize("status", ["aborted", "repair", "failed", "resolved"])
def test_reconcile_terminal_result_carries_admin_note_and_no_edge_bundle(
    status: str,
) -> None:
    """The terminal abort/repair/failed result carries the audited note, no bundle."""
    result = ControlPlaneMutationResult(
        status=status,  # type: ignore[arg-type]
        op_id="op-1",
        operation_kind="phase_start",
        run_id="run-1",
        phase="implementation",
        edge_bundle=None,
        phase_dispatch=None,
        admin_note=f"admin_abort_inflight_operation: {status}",
    )
    dumped = result.model_dump(mode="json")
    assert dumped["status"] == status
    assert dumped["edge_bundle"] is None
    assert dumped["admin_note"].endswith(status)
    # Round-trips through validation (the model invariant re-checks on load).
    assert ControlPlaneMutationResult.model_validate(dumped).status == status


@pytest.mark.contract
@pytest.mark.parametrize("status", ["aborted", "repair", "failed", "resolved"])
def test_reconcile_terminal_result_must_not_carry_edge_bundle(status: str) -> None:
    """A non-materializing terminal result carrying an edge bundle is rejected."""
    with pytest.raises(ValidationError, match="must not"):
        ControlPlaneMutationResult(
            status=status,  # type: ignore[arg-type]
            op_id="op-1",
            operation_kind="phase_start",
            run_id="run-1",
            phase="implementation",
            edge_bundle=_valid_edge_bundle(),
        )
