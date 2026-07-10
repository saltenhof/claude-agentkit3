"""Contract pins for AG3-150 freeze records and Rule-8 rejection shapes."""

from __future__ import annotations

import json
from http import HTTPStatus

import pytest

from agentkit.backend.control_plane.models import (
    ControlPlaneMutationResult,
    FreezeConflictDetail,
)
from agentkit.backend.control_plane.runtime._ownership_transfer_support import (
    _takeover_rejection,
)
from agentkit.backend.control_plane_http.app import _mutation_result_response
from agentkit.backend.core_types.freeze import FreezeKind
from agentkit.backend.state_backend.store.freeze_repository import FreezeRecord

pytestmark = pytest.mark.contract


def test_freeze_record_contract_pins_kind_epoch_reason_and_audit_fields() -> None:
    record = FreezeRecord(
        story_id="AG3-150",
        frozen_at="2026-07-11T12:00:00+00:00",
        freeze_reason="normative conflict",
        freeze_version=9,
        kind=FreezeKind.CONFLICT_FREEZE,
        freeze_epoch="14",
    )

    assert tuple(record.__dataclass_fields__) == (
        "story_id",
        "frozen_at",
        "freeze_reason",
        "freeze_version",
        "kind",
        "freeze_epoch",
    )
    assert record.kind is FreezeKind.CONFLICT_FREEZE
    assert record.frozen_at == "2026-07-11T12:00:00+00:00"


def test_admission_freeze_rejection_contract_is_structured_rule_8_conflict() -> None:
    result = ControlPlaneMutationResult(
        status="rejected",
        op_id="op-freeze",
        operation_kind="phase_complete",
        run_id="run-150",
        phase="implementation",
        error_code="story_frozen",
        freeze_conflict=FreezeConflictDetail(
            kind="conflict_freeze",
            freeze_reason="normative conflict",
            freeze_epoch="14",
            state_readable=True,
        ),
    )

    response = _mutation_result_response(result, correlation_id="corr-freeze")
    body = json.loads(response.body)
    assert response.status_code == int(HTTPStatus.CONFLICT)
    assert body["error_code"] == "story_frozen"
    assert body["freeze_conflict"] == {
        "kind": "conflict_freeze",
        "freeze_reason": "normative conflict",
        "freeze_epoch": "14",
        "state_readable": True,
    }


def test_takeover_admissibility_rejection_contract_pins_rule_8_error_code() -> None:
    result = _takeover_rejection(
        op_id="op-confirm",
        operation_kind="ownership_takeover_confirm",
        reason="story_not_takeover_admissible",
        error_code="story_not_takeover_admissible",
        run_id="run-150",
    )

    response = _mutation_result_response(result, correlation_id="corr-takeover")
    body = json.loads(response.body)
    assert response.status_code == int(HTTPStatus.CONFLICT)
    assert body["error_code"] == "story_not_takeover_admissible"
