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


def _verdict(status: str, systems: list[dict[str, object]]) -> dict[str, object]:
    return {"op_id": "validation-contract-1", "status": status, "systems": systems}


def _system(name: str, status: str) -> dict[str, object]:
    return {"system": name, "status": status, "detail": "probe verdict"}


class TestTheAggregateIsNotFreelyChosen:
    """AG3-242: the verdict was fail-open at the contract, not at a call site.

    `installer.invariant.third_party_validation_fails_closed` forbids a silent
    skip or a green outcome for a failed system, and FK-91 section 91.1 says the
    response carries a typed single result PER SYSTEM. Neither was enforced: the
    model accepted `PASS` next to a failed system and accepted a verdict that
    omitted a system entirely. The installer reads only the aggregate, so both
    turned a failed precondition into a passing checkpoint.
    """

    def test_pass_next_to_a_failed_system_is_rejected(self) -> None:
        with pytest.raises(ValidationError) as caught:
            ThirdPartyValidationResponse.model_validate(
                _verdict(
                    "PASS",
                    [
                        _system("sonar", "FAILED"),
                        _system("jenkins", "PASS"),
                        _system("are", "SKIPPED"),
                    ],
                )
            )

        assert "always makes the aggregate FAILED" in str(caught.value)

    def test_failed_without_any_failed_system_is_accepted(self) -> None:
        """The converse is NOT a rule, and enforcing it discarded a valid answer.

        `installer.invariant.third_party_validation_fails_closed`
        (`concept/formal-spec/installer/invariants.md:72`) names TWO independent
        causes of a failed outcome: "an unreachable backend OR any applicable
        unreachable or invalid third system". The decision record
        `concept/_meta/decisions/2026-07-14-third-party-backend-mediation.md`
        section 2 says the same: "Bei Backend- oder Dritt-System-Ausfall bricht
        der Installer sichtbar fail-closed ab". The first cause has no per-system
        FAILED to point at. Nothing anchors the converse, and rejecting this
        verdict would throw away a backend-level failure the concept provides
        for -- re-labelling it as a transport fault at `runner.py`.
        """
        accepted = ThirdPartyValidationResponse.model_validate(
            {
                **_verdict(
                    "FAILED",
                    [
                        _system("sonar", "PASS"),
                        _system("jenkins", "PASS"),
                        _system("are", "SKIPPED"),
                    ],
                ),
                "error_code": "backend_probe_environment_unavailable",
            }
        )

        assert accepted.status == "FAILED"
        assert accepted.error_code == "backend_probe_environment_unavailable"

    @pytest.mark.parametrize("omitted", ["sonar", "jenkins", "are"])
    def test_a_verdict_that_omits_a_system_is_rejected(self, omitted: str) -> None:
        systems = [
            _system(name, "PASS")
            for name in ("sonar", "jenkins", "are")
            if name != omitted
        ]

        with pytest.raises(ValidationError) as caught:
            ThirdPartyValidationResponse.model_validate(_verdict("PASS", systems))

        assert "incomplete" in str(caught.value)
        assert omitted in str(caught.value)

    def test_a_system_reported_twice_is_rejected(self) -> None:
        """Two verdicts for one system make the aggregate ambiguous."""
        with pytest.raises(ValidationError) as caught:
            ThirdPartyValidationResponse.model_validate(
                _verdict(
                    "PASS",
                    [
                        _system("sonar", "PASS"),
                        _system("sonar", "SKIPPED"),
                        _system("jenkins", "PASS"),
                        _system("are", "SKIPPED"),
                    ],
                )
            )

        assert "more than once" in str(caught.value)

    def test_the_consistent_verdict_the_producer_builds_is_accepted(self) -> None:
        """The invariant must not reject what `run_light_validation` emits."""
        accepted = ThirdPartyValidationResponse.model_validate(
            _verdict(
                "PASS",
                [
                    _system("sonar", "PASS"),
                    _system("jenkins", "PASS"),
                    _system("are", "SKIPPED"),
                ],
            )
        )

        assert accepted.status == "PASS"


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
