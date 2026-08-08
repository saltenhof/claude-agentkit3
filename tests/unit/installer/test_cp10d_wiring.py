"""Installer CP10d mediation tests for AG3-132."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, cast

import pytest

from agentkit.backend.control_plane.third_party_models import (
    ThirdPartyValidationRequest,
    ThirdPartyValidationResponse,
)
from agentkit.backend.exceptions import ControlPlaneApiError, InstallationError
from agentkit.backend.installer.bootstrap_checkpoints.cp10d_sonarqube import cp10d_sonarqube
from agentkit.backend.installer.bootstrap_checkpoints.orchestrator import (
    build_checkpoint_context,
)
from agentkit.backend.installer.checkpoint_engine.execution_mode import ExecutionMode
from agentkit.backend.installer.integration_checkpoints.sonar_preflight import (
    CheckpointStatus,
)
from agentkit.backend.installer.registration import CheckpointStatus as RecordedStatus
from agentkit.backend.installer.runner import InstallConfig, _run_cp10d_sonarqube

if TYPE_CHECKING:
    from pathlib import Path

    from agentkit.harness_client.projectedge.client import ProjectEdgeClient


@dataclass
class _ProjectEdgeBoundary:
    verdict: ThirdPartyValidationResponse | None = None
    failure: Exception | None = None
    requests: list[ThirdPartyValidationRequest] = field(default_factory=list)

    def validate_third_party(
        self, *, project_key: str, request: ThirdPartyValidationRequest
    ) -> ThirdPartyValidationResponse:
        assert project_key == "acme"
        self.requests.append(request)
        if self.failure is not None:
            raise self.failure
        assert self.verdict is not None
        return self.verdict


def _verdict(*, sonar_status: str = "PASS") -> ThirdPartyValidationResponse:
    sonar_code = "sonar_unreachable" if sonar_status == "FAILED" else None
    return ThirdPartyValidationResponse.model_validate(
        {
            "op_id": "validation-1",
            "status": "FAILED" if sonar_status == "FAILED" else "PASS",
            "error_code": "third_party_validation_failed"
            if sonar_status == "FAILED"
            else None,
            "systems": [
                {
                    "system": "sonar",
                    "status": sonar_status,
                    "error_code": sonar_code,
                    "detail": "probe verdict",
                },
                {"system": "jenkins", "status": "PASS", "detail": "probe verdict"},
                {"system": "are", "status": "SKIPPED", "detail": "not applicable"},
            ],
        }
    )


def _profile(root: Path) -> None:
    path = root / "bundles" / "target_project" / "sonar" / "ak3-default-gate.json"
    path.parent.mkdir(parents=True)
    path.write_text("{}", encoding="utf-8")


def _yaml(
    *,
    sonar_available: bool = True,
    ci_available: bool = True,
    are_enabled: bool = False,
) -> dict[str, object]:
    """Build a project stanza; the three applicability switches are independent.

    They are separate arguments because the three conditions are separate in the
    source: Sonar and Jenkins are applicable on ``available``, ARE on the
    ``features.are`` gate (``ThirdPartyValidationRequest.applicable_systems``).
    """
    return {
        "pipeline": {
            "features": {"are": are_enabled},
            "sonarqube": {
                "available": sonar_available,
                "enabled": True,
                "base_url": "https://sonar.example",
                "token_env": "SONAR_BACKEND_TOKEN",
                "scanner_version": "5.0.1",
            },
            "ci": {
                "available": ci_available,
                "enabled": True,
                "base_url": "https://jenkins.example",
                "token_env": "JENKINS_BACKEND_TOKEN",
                "pipeline": "pre-merge",
            },
        }
    }


def _config(
    root: Path, edge: _ProjectEdgeBoundary | _WireValidatingBoundary
) -> InstallConfig:
    return InstallConfig(
        project_key="acme",
        project_name="Acme",
        project_root=root,
        project_edge_client=cast("ProjectEdgeClient", edge),
    )


def test_cp10d_sends_only_secret_references_and_consumes_pass(
    tmp_path: Path,
) -> None:
    _profile(tmp_path)
    edge = _ProjectEdgeBoundary(verdict=_verdict())

    result = _run_cp10d_sonarqube(_config(tmp_path, edge), tmp_path, _yaml())

    assert result.status == CheckpointStatus.PASS
    assert len(edge.requests) == 1
    request = edge.requests[0]
    assert request.sonar.token_env == "SONAR_BACKEND_TOKEN"
    assert request.ci.token_env == "JENKINS_BACKEND_TOKEN"
    assert "secret" not in request.model_dump_json().lower()


def test_cp10d_preserves_local_default_profile_validation(tmp_path: Path) -> None:
    edge = _ProjectEdgeBoundary(verdict=_verdict())

    with pytest.raises(InstallationError) as caught:
        _run_cp10d_sonarqube(_config(tmp_path, edge), tmp_path, _yaml())

    assert caught.value.detail["error_code"] == "default_profile_missing"
    assert edge.requests == []


def test_cp10d_fails_closed_when_backend_is_unreachable(tmp_path: Path) -> None:
    _profile(tmp_path)
    edge = _ProjectEdgeBoundary(failure=OSError("control plane refused connection"))

    with pytest.raises(InstallationError) as caught:
        _run_cp10d_sonarqube(_config(tmp_path, edge), tmp_path, _yaml())

    assert caught.value.detail["error_code"] == "third_party_backend_unreachable"


def test_cp10d_distinguishes_backend_http_rejection_from_transport_failure(
    tmp_path: Path,
) -> None:
    """A reachable backend's HTTP error retains its structured taxonomy."""
    _profile(tmp_path)
    edge = _ProjectEdgeBoundary(
        failure=ControlPlaneApiError(
            "project token is invalid",
            error_code="unauthorized",
            correlation_id="corr-http",
            http_status=401,
        )
    )

    with pytest.raises(InstallationError) as caught:
        _run_cp10d_sonarqube(_config(tmp_path, edge), tmp_path, _yaml())

    assert caught.value.detail == {
        "cause": "ThirdPartyValidationBackendHttpError",
        "error_code": "unauthorized",
        "http_status": 401,
    }


@dataclass
class _WireValidatingBoundary:
    """Boundary that parses a raw wire payload exactly as the real client does.

    ``ProjectEdgeClient.validate_third_party`` ends in
    ``ThirdPartyValidationResponse.model_validate(data)`` (client.py:723). Handing
    this fake a pre-built response object would test nothing about a hostile
    payload, because the model refuses to build one. It therefore takes the dict.
    """

    payload: dict[str, object]
    requests: list[ThirdPartyValidationRequest] = field(default_factory=list)

    def validate_third_party(
        self, *, project_key: str, request: ThirdPartyValidationRequest
    ) -> ThirdPartyValidationResponse:
        assert project_key == "acme"
        # The request is KEPT. Applicability is stated here and nowhere else, so
        # a test that discards it cannot show which systems the verdict owed an
        # answer for -- it could only assume it.
        self.requests.append(request)
        return ThirdPartyValidationResponse.model_validate(self.payload)


def test_cp10d_fails_closed_on_a_contradictory_backend_verdict(tmp_path: Path) -> None:
    """A wire verdict claiming PASS while Sonar FAILED must not pass CP10d.

    This is the defect the contract now forbids: the installer reads only the
    aggregate, so before the model enforced the invariant this payload produced
    ``CheckpointStatus.PASS`` for a Sonar that had failed.
    """
    _profile(tmp_path)
    edge = _WireValidatingBoundary(
        payload={
            "op_id": "validation-1",
            "status": "PASS",
            "systems": [
                {"system": "sonar", "status": "FAILED", "error_code": "sonar_unreachable"},
                {"system": "jenkins", "status": "PASS"},
                {"system": "are", "status": "SKIPPED"},
            ],
        }
    )

    with pytest.raises(InstallationError) as caught:
        _run_cp10d_sonarqube(_config(tmp_path, edge), tmp_path, _yaml())

    assert caught.value.detail["cause"] == "ThirdPartyValidationBackendUnavailable"


def test_cp10d_fails_closed_on_a_verdict_that_omits_a_system(tmp_path: Path) -> None:
    """A verdict silent about Jenkins is a silent skip, not a pass."""
    _profile(tmp_path)
    edge = _WireValidatingBoundary(
        payload={
            "op_id": "validation-1",
            "status": "PASS",
            "systems": [
                {"system": "sonar", "status": "PASS"},
                {"system": "are", "status": "SKIPPED"},
            ],
        }
    )

    with pytest.raises(InstallationError) as caught:
        _run_cp10d_sonarqube(_config(tmp_path, edge), tmp_path, _yaml())

    assert caught.value.detail["cause"] == "ThirdPartyValidationBackendUnavailable"


def _wire_verdict(**statuses: str) -> dict[str, object]:
    """Build a raw wire payload, defaulting to the fully unremarkable verdict."""
    merged = {"sonar": "PASS", "jenkins": "PASS", "are": "SKIPPED", **statuses}
    return {
        "op_id": "validation-1",
        "status": "PASS",
        "systems": [
            {"system": name, "status": status} for name, status in merged.items()
        ],
    }


@pytest.mark.parametrize(
    ("skipped_system", "sonar_available", "ci_available", "are_enabled"),
    [
        ("sonar", True, True, False),
        ("jenkins", True, True, False),
        ("are", True, True, True),
    ],
)
def test_cp10d_fails_closed_when_an_applicable_system_reports_skipped(
    tmp_path: Path,
    skipped_system: str,
    sonar_available: bool,
    ci_available: bool,
    are_enabled: bool,
) -> None:
    """An applicable system that was never probed must not yield a green CP10d.

    This is the fail-open path the aggregate cannot catch: every per-system
    status is unremarkable, so `status: PASS` is internally consistent, and the
    installer reads only the aggregate. What makes it illegal is the REQUEST --
    the system is applicable there, and
    `installer.invariant.third_party_validation_fails_closed` (invariants.md:72)
    rules out a silent skip for an applicable system.
    """
    _profile(tmp_path)
    yaml_data = _yaml(
        sonar_available=sonar_available,
        ci_available=ci_available,
        are_enabled=are_enabled,
    )
    edge = _WireValidatingBoundary(payload=_wire_verdict(**{skipped_system: "SKIPPED"}))

    with pytest.raises(InstallationError) as caught:
        _run_cp10d_sonarqube(_config(tmp_path, edge), tmp_path, yaml_data)

    # The request is the evidence that the skip was illegal, not an assumption.
    assert skipped_system in edge.requests[0].applicable_systems()
    assert caught.value.detail["cause"] == "ThirdPartyValidationIncomplete"
    assert caught.value.detail["error_code"] == "third_party_applicable_system_skipped"
    assert caught.value.detail["systems"] == [skipped_system]


def test_cp10d_accepts_skipped_verdicts_for_systems_the_request_excluded(
    tmp_path: Path,
) -> None:
    """The legal skip stays legal: a declared absence is not a silent skip.

    Sonar and Jenkins are switched off via `available`, ARE via the `features.are`
    gate -- three systems, two different conditions. All three answer SKIPPED and
    CP10d passes, because the request never asked for them.
    """
    yaml_data = _yaml(sonar_available=False, ci_available=False, are_enabled=False)
    edge = _WireValidatingBoundary(
        payload=_wire_verdict(sonar="SKIPPED", jenkins="SKIPPED", are="SKIPPED")
    )

    result = _run_cp10d_sonarqube(_config(tmp_path, edge), tmp_path, yaml_data)

    assert edge.requests[0].applicable_systems() == frozenset()
    assert result.status == CheckpointStatus.SKIPPED
    assert result.reason == "not_applicable"


def test_cp10d_fails_closed_on_structured_system_failure(tmp_path: Path) -> None:
    _profile(tmp_path)
    edge = _ProjectEdgeBoundary(verdict=_verdict(sonar_status="FAILED"))

    with pytest.raises(InstallationError) as caught:
        _run_cp10d_sonarqube(_config(tmp_path, edge), tmp_path, _yaml())

    assert caught.value.detail["error_code"] == "third_party_validation_failed"
    assert "sonar_unreachable" in str(caught.value.detail["details"])


def test_register_light_validation_does_not_start_heavy_self_test(tmp_path: Path) -> None:
    _profile(tmp_path)
    edge = _ProjectEdgeBoundary(verdict=_verdict())

    _run_cp10d_sonarqube(_config(tmp_path, edge), tmp_path, _yaml())

    assert len(edge.requests) == 1
    assert not hasattr(edge, "start_branch_plugin_self_test")


def test_verify_runs_live_read_only_probes_but_dry_run_is_plan_only(
    tmp_path: Path,
) -> None:
    _profile(tmp_path)
    edge = _ProjectEdgeBoundary(verdict=_verdict())
    config = _config(tmp_path, edge)
    verify = build_checkpoint_context(config, ExecutionMode.VERIFY)
    verify.run_state.project_yaml = _yaml()

    verified = cp10d_sonarqube(verify)

    assert verified.status is RecordedStatus.PASS
    assert len(edge.requests) == 1

    planned_edge = _ProjectEdgeBoundary(verdict=_verdict())
    planned = build_checkpoint_context(
        _config(tmp_path, planned_edge), ExecutionMode.DRY_RUN
    )
    planned.run_state.project_yaml = _yaml()
    assert cp10d_sonarqube(planned).status is RecordedStatus.PASS
    assert planned_edge.requests == []
