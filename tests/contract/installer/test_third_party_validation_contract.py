"""Wire-contract pins for AG3-132 third-party mediation."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, cast

import pytest
from pydantic import ValidationError

from agentkit.backend.control_plane.third_party_models import (
    ThirdPartyValidationRequest,
    ThirdPartyValidationResponse,
)
from agentkit.backend.control_plane_http.third_party_validation_routes import (
    ThirdPartyValidationRoutes,
)

if TYPE_CHECKING:
    from agentkit.backend.installer.third_party_preflight import ThirdPartyPreflightService


class _Service:
    def validate_idempotent(
        self,
        project_key: str,
        request: ThirdPartyValidationRequest,
        correlation_id: str,
    ) -> ThirdPartyValidationResponse:
        assert project_key == "tenant-a"
        assert correlation_id == "corr-1"
        return ThirdPartyValidationResponse.model_validate(
            {
                "op_id": request.op_id,
                "status": "FAILED",
                "error_code": "third_party_validation_failed",
                "systems": [
                    {
                        "system": "sonar",
                        "status": "FAILED",
                        "error_code": "sonar_unreachable",
                        "detail": "connection refused",
                    },
                    {
                        "system": "jenkins",
                        "status": "SKIPPED",
                        "detail": "not applicable",
                    },
                    {
                        "system": "are",
                        "status": "SKIPPED",
                        "detail": "not applicable",
                    },
                ],
            }
        )


def _payload() -> dict[str, object]:
    return {
        "op_id": "validation-contract-1",
        "sonar": {
            "available": True,
            "enabled": True,
            "base_url": "https://sonar.example",
            "token_env": "SONAR_BACKEND_TOKEN",
            "scanner_version": "5.0.1",
        },
        "ci": {"available": False, "enabled": False},
        "are": {"enabled": False},
    }


def _routes() -> ThirdPartyValidationRoutes:
    return ThirdPartyValidationRoutes(
        cast("ThirdPartyPreflightService", _Service()),
    )


def test_only_frozen_project_scoped_route_is_exposed() -> None:
    routes = _routes()

    assert routes.handle_post(
        "/v1/installation/third-party-validation", _payload(), "corr-1"
    ) is None
    response = routes.handle_post(
        "/v1/projects/tenant-a/installation/third-party-validation",
        _payload(),
        "corr-1",
    )

    assert response is not None
    assert response.status_code == 200
    assert ("X-Correlation-Id", "corr-1") in response.headers
    body = json.loads(response.body)
    assert body["op_id"] == "validation-contract-1"
    assert body["error_code"] == "third_party_validation_failed"
    assert body["systems"][0]["error_code"] == "sonar_unreachable"


def test_secret_values_are_forbidden_and_never_echoed_by_validation_errors() -> None:
    payload = _payload()
    sonar = payload["sonar"]
    assert isinstance(sonar, dict)
    sonar["token"] = "wire-secret-must-not-echo"

    with pytest.raises(ValidationError):
        ThirdPartyValidationRequest.model_validate(payload)
    response = _routes().handle_post(
        "/v1/projects/tenant-a/installation/third-party-validation",
        payload,
        "corr-secret",
    )

    assert response is not None
    assert response.status_code == 400
    assert b"wire-secret-must-not-echo" not in response.body
    assert b"invalid_third_party_validation_request" in response.body
