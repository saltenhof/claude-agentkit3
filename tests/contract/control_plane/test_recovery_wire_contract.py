"""Contract pins for the AG3-154 recovery endpoint wire form."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from agentkit.backend.control_plane.models import RecoveryRequest

pytestmark = pytest.mark.contract


def test_recovery_request_wire_keys_are_exact_and_client_op_id_reason_are_required() -> None:
    request = RecoveryRequest(
        project_key="project-a",
        story_id="AG3-154",
        op_id="op-recovery-contract",
        reason="operator confirmed orphaned claim",
    )

    assert request.model_dump(mode="json") == {
        "project_key": "project-a",
        "story_id": "AG3-154",
        "op_id": "op-recovery-contract",
        "reason": "operator confirmed orphaned claim",
        "worktree_disposition": "adopt",
        "source_component": "project_edge_client",
    }
    assert RecoveryRequest.model_validate(
        {
            **request.model_dump(mode="json"),
            "worktree_disposition": "reset",
        }
    ).worktree_disposition == "reset"
    with pytest.raises(ValidationError):
        RecoveryRequest.model_validate(
            {
                **request.model_dump(mode="json"),
                "worktree_disposition": "discard",
            }
        )
    with pytest.raises(ValidationError):
        RecoveryRequest.model_validate(
            {
                "project_key": "project-a",
                "story_id": "AG3-154",
                "reason": "operator confirmed orphaned claim",
            }
        )
    with pytest.raises(ValidationError):
        RecoveryRequest.model_validate(
            {
                "project_key": "project-a",
                "story_id": "AG3-154",
                "op_id": "op-recovery-contract",
            }
        )
