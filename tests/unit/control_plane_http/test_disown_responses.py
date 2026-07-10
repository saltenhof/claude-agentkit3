"""HTTP mapping contracts for AG3-149 disown and ping-pong denials."""

from __future__ import annotations

from http import HTTPStatus

import pytest

from agentkit.backend.control_plane.models import ControlPlaneMutationResult
from agentkit.backend.control_plane_http.responses import (
    _mutation_result_response,
    _takeover_result_response,
)


@pytest.mark.parametrize(
    "reason",
    ("ownership_transferred", "story_ended", "story_reset", "story_split"),
)
def test_disowned_phase_mutation_maps_reason_to_forbidden(reason: str) -> None:
    result = ControlPlaneMutationResult(
        status="rejected",
        op_id="op-disowned",
        operation_kind="phase_complete",
        run_id="run-a",
        phase="implementation",
        error_code=reason,
    )
    response = _mutation_result_response(result, correlation_id="corr-a")
    assert response.status_code == HTTPStatus.FORBIDDEN
    assert reason in response.body.decode("utf-8")


@pytest.mark.parametrize(
    "reason",
    (
        "disowned_session_cannot_immediately_reclaim",
        "repeat_transfer_requires_privileged_principal_and_reason",
    ),
)
def test_ping_pong_denial_maps_to_forbidden(reason: str) -> None:
    result = ControlPlaneMutationResult(
        status="rejected",
        op_id="op-ping",
        operation_kind="ownership_takeover_confirm",
        run_id="run-a",
        error_code=reason,
    )
    response = _takeover_result_response(result, correlation_id="corr-a")
    assert response.status_code == HTTPStatus.FORBIDDEN
    assert reason in response.body.decode("utf-8")
