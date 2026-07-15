"""Backend-owned light third-system validation tests."""

from __future__ import annotations

import threading
from dataclasses import dataclass
from typing import TYPE_CHECKING, cast

import pytest

from agentkit.backend.control_plane.third_party_models import ThirdPartyValidationRequest
from agentkit.backend.installer.third_party_errors import ThirdPartyOperationConflictError
from agentkit.backend.installer.third_party_light import run_light_validation
from agentkit.backend.installer.third_party_preflight import ThirdPartyPreflightService
from agentkit.backend.installer.third_party_redaction import redact_detail
from agentkit.backend.state_backend.store.inflight_idempotency_guard import (
    FreshClaim,
    IdempotencyRequest,
    InMemoryInflightIdempotencyGuard,
    compute_body_hash,
)
from agentkit.integration_clients.are.preflight import ArePreflightResponse
from agentkit.integration_clients.jenkins import JenkinsApiError, JenkinsHttpResponse
from agentkit.integration_clients.sonar import SonarApiError, SonarHttpResponse

if TYPE_CHECKING:
    from collections.abc import Callable
    from concurrent.futures import Future

    from agentkit.backend.control_plane.records import ControlPlaneOperationRecord
    from agentkit.backend.control_plane.third_party_models import (
        AreValidationConfig,
        CiValidationConfig,
        SonarValidationConfig,
    )
    from agentkit.backend.installer.third_party_clients import (
        SecretResolver,
        ThirdPartyClientFactory,
    )
    from agentkit.backend.installer.third_party_preflight import AsyncExecutor
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
    entered: threading.Event | None = None
    proceed: threading.Event | None = None
    status_calls: int = 0

    def system_status(self) -> SonarHttpResponse:
        self.status_calls += 1
        if self.entered is not None:
            self.entered.set()
        if self.proceed is not None and not self.proceed.wait(timeout=5):
            raise AssertionError("timed out waiting to release the Sonar probe")
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


class _UnusedExecutor:
    """Executor seam that proves light validation never schedules heavy work."""

    def submit(self, fn: Callable[[], None]) -> Future[None]:
        del fn
        raise AssertionError("light validation submitted heavy work")


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


def _service(
    resolver: SecretResolver,
    clients: ThirdPartyClientFactory,
    guard: InMemoryInflightIdempotencyGuard,
) -> ThirdPartyPreflightService:
    def _load(_op_id: str) -> ControlPlaneOperationRecord | None:
        return None

    return ThirdPartyPreflightService(
        resolver=resolver,
        clients=clients,
        guard=guard,
        operation_loader=_load,
        executor=cast("AsyncExecutor", _UnusedExecutor()),
    )


def _identity(request: ThirdPartyValidationRequest) -> IdempotencyRequest:
    body = request.model_dump(mode="json")
    body["project_key"] = "tenant-a"
    return IdempotencyRequest(
        op_id=request.op_id,
        operation_kind="third_party_validation",
        body_hash=compute_body_hash(body),
        project_key="tenant-a",
    )


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


def test_legacy_committed_light_verdict_is_never_replayed() -> None:
    """A terminal PASS left by the old implementation cannot fail open."""
    resolver, clients = _dependencies()
    request = _request()
    guard = InMemoryInflightIdempotencyGuard()
    identity = _identity(request)
    claim = guard.claim(identity)
    assert isinstance(claim, FreshClaim)
    stale = run_light_validation(request, resolver, clients)
    assert stale.status == "PASS"
    assert guard.finalize(identity, claim, stale.model_dump(mode="json"))
    factory = cast("_ClientFactory", clients)
    factory.sonar_boundary.fail = True

    live = _service(resolver, clients, guard).validate_idempotent(
        "tenant-a", request, "corr-live"
    )

    assert live.status == "FAILED"
    assert live.systems[0].error_code == "sonar_unreachable"
    assert factory.sonar_boundary.status_calls == 2


def test_concurrent_identical_light_requests_do_not_double_probe() -> None:
    """The released light claim remains an in-flight concurrency fence."""
    resolver, clients = _dependencies()
    factory = cast("_ClientFactory", clients)
    entered = threading.Event()
    proceed = threading.Event()
    factory.sonar_boundary.entered = entered
    factory.sonar_boundary.proceed = proceed
    service = _service(resolver, clients, InMemoryInflightIdempotencyGuard())
    request = _request()
    first_results: list[str] = []

    def _first_request() -> None:
        result = service.validate_idempotent("tenant-a", request, "corr-first")
        first_results.append(result.status)

    thread = threading.Thread(target=_first_request)
    thread.start()
    assert entered.wait(timeout=5)

    with pytest.raises(ThirdPartyOperationConflictError, match="already running"):
        service.validate_idempotent("tenant-a", request, "corr-second")

    proceed.set()
    thread.join(timeout=5)
    assert not thread.is_alive()
    assert first_results == ["PASS"]
    assert factory.sonar_boundary.status_calls == 1
