"""Contract pin for the Spec-Freeze error shape (AG3-143, AC10, FK-59 §59.9a).

Freezes the wire contract of the Spec-Freeze rejection so a later change to
the error class, its HTTP status or its machine-readable ``error_code`` is a
deliberate, visible break rather than a silent drift:

- ``SpecFrozenDuringActiveRunError`` maps to HTTP ``409`` with the stable
  ``error_code`` ``"spec_frozen_during_active_run"`` (ARCH-55 english wire
  key);
- the rendered error body carries ``error_code`` / ``error`` /
  ``correlation_id`` (FK-91 §91.1a Rule 7+8) plus the structured ``detail``
  the domain error attaches.
"""

from __future__ import annotations

import json
from http import HTTPStatus

from agentkit.backend.story_context_manager.errors import (
    SpecFrozenDuringActiveRunError,
)
from agentkit.backend.story_context_manager.http.routes import (
    _ERROR_CODE_MAP,
    _service_error_response,
)

_EXPECTED_ERROR_CODE = "spec_frozen_during_active_run"


def test_error_code_map_pins_freeze_error_to_409_and_stable_code() -> None:
    assert _ERROR_CODE_MAP[SpecFrozenDuringActiveRunError] == (
        HTTPStatus.CONFLICT,
        _EXPECTED_ERROR_CODE,
    )


def test_freeze_error_response_body_shape() -> None:
    exc = SpecFrozenDuringActiveRunError(
        "frozen",
        detail={"project_key": "ak3", "story_id": "AK3-001"},
    )

    resp = _service_error_response(exc, correlation_id="corr-1")

    assert resp.status_code == int(HTTPStatus.CONFLICT)
    body = json.loads(resp.body)
    assert body["error_code"] == _EXPECTED_ERROR_CODE
    assert body["error"] == "frozen"
    assert body["correlation_id"] == "corr-1"
    assert body["detail"] == {"project_key": "ak3", "story_id": "AK3-001"}


def test_freeze_error_carries_correlation_header() -> None:
    exc = SpecFrozenDuringActiveRunError("frozen", detail={})
    resp = _service_error_response(exc, correlation_id="corr-42")
    assert ("X-Correlation-Id", "corr-42") in resp.headers
