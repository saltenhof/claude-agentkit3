"""Contract pin for the AG3-142 ex-owner ``ownership_transferred`` rejection.

FK-91 §91.1a Rule 18 (ex-owner error picture) / Rule 8 (stable error contract) /
FK-56 §56.13c: a mutating call whose run-ownership no longer matches the
story's active record is deterministically rejected with a structured
``ownership_transferred`` payload -- at minimum reason, new owner and transfer
instant -- embedded on the SAME ``ControlPlaneMutationResult`` body the K4
busy-object rejection already uses this pattern for (``error_code`` +
structured detail extending, never replacing, the Rule-8 contract). Pins:

* AC6 -- the ex-owner rejection maps to HTTP 403 FORBIDDEN (distinct from the
  generic 409 CONFLICT every other rejection cause gets) and carries the
  ``ownership_conflict`` detail with all three mandatory fields.
* The plain (non-ex-owner) rejection shapes are UNCHANGED: still 409, still no
  ``ownership_conflict``/``Retry-After``.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from http import HTTPStatus
from typing import TYPE_CHECKING

import pytest

from agentkit.backend.control_plane.models import OwnershipTransferredDetail
from agentkit.backend.control_plane.ownership_fence import ERROR_CODE_OWNERSHIP_TRANSFERRED
from agentkit.backend.control_plane.runtime import (
    _ownership_transferred_rejection,
    _rejection_result,
)
from agentkit.backend.control_plane_http.app import _mutation_result_response

if TYPE_CHECKING:
    from agentkit.backend.control_plane.models import ControlPlaneMutationResult

pytestmark = pytest.mark.contract


def _ex_owner_rejection() -> ControlPlaneMutationResult:
    """The productive ex-owner rejection (the exact runtime helper output)."""
    return _ownership_transferred_rejection(
        op_id="op-1",
        operation_kind="phase_complete",
        run_id="run-1",
        phase="implementation",
        new_owner_session_id="sess-new-owner",
        new_ownership_epoch=2,
        transferred_at=datetime(2026, 7, 4, 12, 0, tzinfo=UTC),
    )


def test_error_code_is_the_stable_ownership_transferred_constant() -> None:
    assert ERROR_CODE_OWNERSHIP_TRANSFERRED == "ownership_transferred"
    assert _ex_owner_rejection().error_code == ERROR_CODE_OWNERSHIP_TRANSFERRED


def test_ex_owner_rejection_maps_to_403_forbidden() -> None:
    """AC6 (FK-91 §91.1a Rule 18): the ex-owner rejection is 403, not the
    generic 409 every other control-plane rejection maps to -- the caller is
    not merely conflicting with concurrent state, it no longer holds
    run-ownership at all.
    """
    response = _mutation_result_response(_ex_owner_rejection(), correlation_id="corr-1")

    assert response.status_code == int(HTTPStatus.FORBIDDEN)
    body = json.loads(response.body)
    assert body["status"] == "rejected"
    assert body["error_code"] == "ownership_transferred"


def test_ownership_conflict_detail_carries_the_rule_18_mandatory_fields() -> None:
    """FK-91 §91.1a Rule 18: at least reason, new owner and transfer instant."""
    response = _mutation_result_response(_ex_owner_rejection(), correlation_id="corr-2")
    body = json.loads(response.body)

    conflict = body["ownership_conflict"]
    assert conflict is not None
    assert conflict["reason"] == "ownership_transferred"
    assert conflict["new_owner_session_id"] == "sess-new-owner"
    assert conflict["new_ownership_epoch"] == 2
    assert conflict["transferred_at"] == "2026-07-04T12:00:00Z"


def test_correlation_id_travels_on_the_response_header_regel_7() -> None:
    """FK-91 §91.1a Rule 7: every response carries a stable correlation_id --
    here via the ``X-Correlation-Id`` header (the SAME transport-level carrier
    every other control-plane mutation response uses).
    """
    response = _mutation_result_response(_ex_owner_rejection(), correlation_id="corr-3")

    assert ("X-Correlation-Id", "corr-3") in response.headers


def test_ownership_transferred_detail_model_requires_all_three_fields() -> None:
    """Schema pin: ``OwnershipTransferredDetail`` cannot be built with a field
    missing -- the Rule-18 payload can never silently degrade to fewer than
    reason/new-owner/epoch/instant.
    """
    with pytest.raises(Exception):  # noqa: B017, PT011 -- pydantic ValidationError, any missing field
        OwnershipTransferredDetail.model_validate({"reason": "ownership_transferred"})

    full = OwnershipTransferredDetail(
        reason="ownership_transferred",
        new_owner_session_id="sess-x",
        new_ownership_epoch=3,
        transferred_at=datetime(2026, 7, 4, 12, 0, tzinfo=UTC),
    )
    assert full.reason == "ownership_transferred"


def test_ex_owner_rejection_carries_no_retry_after_header() -> None:
    """The K4 ``Retry-After`` header stays exclusive to the busy-object wait
    contract -- an ex-owner rejection never grows one.
    """
    response = _mutation_result_response(_ex_owner_rejection(), correlation_id="corr-4")

    assert all(name != "Retry-After" for name, _ in response.headers)


def test_plain_rejection_is_unaffected_still_409_no_ownership_conflict() -> None:
    """Every OTHER rejection cause (e.g. "not admitted", no active record) is
    UNCHANGED by AG3-142's new 403 branch: still 409, still no
    ``ownership_conflict`` detail.
    """
    plain = _rejection_result(
        op_id="op-2",
        operation_kind="phase_complete",
        run_id="run-2",
        phase="implementation",
        reason="phase_complete rejected: the run has no active run-ownership record",
    )

    response = _mutation_result_response(plain, correlation_id="corr-5")

    assert response.status_code == int(HTTPStatus.CONFLICT)
    body = json.loads(response.body)
    assert body["error_code"] is None
    assert body["ownership_conflict"] is None
