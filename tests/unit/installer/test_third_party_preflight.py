"""Backend-owned light third-system validation tests."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, cast

from agentkit.backend.control_plane.third_party_models import ThirdPartyValidationRequest
from agentkit.backend.installer.third_party_light import run_light_validation
from agentkit.backend.installer.third_party_redaction import redact_detail
from agentkit.integration_clients.are.preflight import ArePreflightResponse
from agentkit.integration_clients.jenkins import JenkinsApiError, JenkinsHttpResponse
from agentkit.integration_clients.sonar import SonarApiError, SonarHttpResponse

if TYPE_CHECKING:
    from agentkit.backend.control_plane.third_party_models import (
        AreValidationConfig,
        CiValidationConfig,
        SonarValidationConfig,
    )
    from agentkit.backend.installer.third_party_clients import (
        SecretResolver,
        ThirdPartyClientFactory,
    )
    from agentkit.integration_clients.are import ArePreflightClient
    from agentkit.integration_clients.jenkins import JenkinsClient
    from agentkit.integration_clients.sonar import SonarClient


@dataclass(frozen=True)
class _Secrets:
    values: dict[str, str]

    def resolve(self, reference: str) -> str | None:
        return self.values.get(reference)


@dataclass
class _SonarBoundary:
    token: str
    fail: bool = False

    def system_status(self) -> SonarHttpResponse:
        if self.fail:
            raise SonarApiError(
                f"Authorization: Basic encoded-secret; Bearer {self.token}"
            )
        return SonarHttpResponse(status_code=200, json_body={"version": "26.4"})

    def installed_plugins(self) -> SonarHttpResponse:
        return SonarHttpResponse(
            status_code=200,
            json_body={
                "plugins": [
                    {"key": "communityBranchSupport", "version": "1.23.0"}
                ]
            },
        )


@dataclass
class _JenkinsBoundary:
    fail: bool = False

    def whoami(self) -> JenkinsHttpResponse:
        if self.fail:
            raise JenkinsApiError("jenkins unreachable")
        return JenkinsHttpResponse(status_code=200, json_body={"id": "agentkit"})

    def job_exists(self, pipeline: str) -> JenkinsHttpResponse:
        return JenkinsHttpResponse(status_code=200, json_body={"name": pipeline})


class _AreBoundary:
    def health(self) -> ArePreflightResponse:
        return ArePreflightResponse(status_code=200, json_body={"status": "ok"})


@dataclass
class _ClientFactory:
    sonar_boundary: _SonarBoundary
    jenkins_boundary: _JenkinsBoundary

    def sonar(self, config: SonarValidationConfig, token: str) -> SonarClient:
        del config
        assert token == self.sonar_boundary.token
        return cast("SonarClient", self.sonar_boundary)

    def sonar_permissions(
        self, config: SonarValidationConfig
    ) -> frozenset[str]:
        del config
        return frozenset({"Administer Issues"})

    def jenkins(self, config: CiValidationConfig, token: str) -> JenkinsClient:
        del config
        assert token == "jenkins-token"
        return cast("JenkinsClient", self.jenkins_boundary)

    def are(self, config: AreValidationConfig, token: str) -> ArePreflightClient:
        del config
        assert token == "are-token"
        return cast("ArePreflightClient", _AreBoundary())


def _request() -> ThirdPartyValidationRequest:
    return ThirdPartyValidationRequest.model_validate(
        {
            "op_id": "light-1",
            "sonar": {
                "available": True,
                "enabled": True,
                "base_url": "https://sonar.example",
                "token_env": "SONAR_REF",
                "scanner_version": "5.0.1",
            },
            "ci": {
                "available": True,
                "enabled": True,
                "base_url": "https://jenkins.example",
                "token_env": "JENKINS_REF",
                "pipeline": "pre-merge",
            },
            "are": {
                "enabled": True,
                "base_url": "https://are.example",
                "token_env": "ARE_REF",
            },
        }
    )


def _dependencies(
    *, sonar_fail: bool = False
) -> tuple[SecretResolver, ThirdPartyClientFactory]:
    sonar_token = "sonar-super-secret"
    secrets = _Secrets(
        {
            "SONAR_REF": sonar_token,
            "JENKINS_REF": "jenkins-token",
            "ARE_REF": "are-token",
        }
    )
    clients = _ClientFactory(
        _SonarBoundary(sonar_token, fail=sonar_fail), _JenkinsBoundary()
    )
    return cast("SecretResolver", secrets), cast("ThirdPartyClientFactory", clients)


def test_light_validation_runs_real_preflight_logic_for_all_enabled_systems() -> None:
    resolver, clients = _dependencies()

    verdict = run_light_validation(_request(), resolver, clients)

    assert verdict.status == "PASS"
    assert [(item.system, item.status) for item in verdict.systems] == [
        ("sonar", "PASS"),
        ("jenkins", "PASS"),
        ("are", "PASS"),
    ]


def test_system_unreachable_is_a_structured_fail_closed_verdict() -> None:
    resolver, clients = _dependencies(sonar_fail=True)

    verdict = run_light_validation(_request(), resolver, clients)

    sonar = verdict.systems[0]
    assert verdict.status == "FAILED"
    assert verdict.error_code == "third_party_validation_failed"
    assert sonar.status == "FAILED"
    assert sonar.error_code == "sonar_unreachable"


def test_service_boundary_redacts_resolved_tokens_and_auth_headers() -> None:
    resolver, clients = _dependencies(sonar_fail=True)

    payload = run_light_validation(_request(), resolver, clients).model_dump_json()

    assert "sonar-super-secret" not in payload
    assert "encoded-secret" not in payload
    assert "Basic" not in payload
    assert "Bearer" not in payload
    assert "[REDACTED]" in payload
    assert redact_detail("password=hunter2 Authorization: Bearer abc") == (
        "password=[REDACTED] Authorization=[REDACTED]"
    )
