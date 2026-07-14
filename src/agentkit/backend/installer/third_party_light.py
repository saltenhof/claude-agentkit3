"""Synchronous backend-owned third-system probes."""

from __future__ import annotations

from typing import TYPE_CHECKING

from agentkit.backend.control_plane.third_party_models import (
    ThirdPartySystemResult,
    ThirdPartyValidationRequest,
    ThirdPartyValidationResponse,
)
from agentkit.backend.installer.third_party_redaction import redact_detail

if TYPE_CHECKING:
    from agentkit.backend.installer.third_party_clients import (
        SecretResolver,
        ThirdPartyClientFactory,
    )


def run_light_validation(
    request: ThirdPartyValidationRequest,
    resolver: SecretResolver,
    clients: ThirdPartyClientFactory,
) -> ThirdPartyValidationResponse:
    """Run Sonar, Jenkins, and feature-gated ARE reads in the backend."""
    systems = (
        _sonar_result(request, resolver, clients),
        _jenkins_result(request, resolver, clients),
        _are_result(request, resolver, clients),
    )
    failed = any(result.status == "FAILED" for result in systems)
    return ThirdPartyValidationResponse(
        op_id=request.op_id,
        status="FAILED" if failed else "PASS",
        error_code="third_party_validation_failed" if failed else None,
        systems=systems,
    )


def _sonar_result(
    request: ThirdPartyValidationRequest,
    resolver: SecretResolver,
    clients: ThirdPartyClientFactory,
) -> ThirdPartySystemResult:
    cfg = request.sonar
    if not cfg.available:
        return _skipped("sonar")
    token = resolver.resolve(cfg.token_env or "")
    if not token:
        return _failed("sonar", "secret_unavailable", "token_env was not resolved")
    try:
        from agentkit.backend.config.models import SonarQubeConfig
        from agentkit.backend.installer.integration_checkpoints.sonar_preflight import (
            check_sonarqube_preconditions,
        )

        model = SonarQubeConfig.model_validate(
            {
                **cfg.model_dump(exclude={"user", "branch_plugin_min_version"}),
                "plugins": {"community_branch": {"min_version": cfg.branch_plugin_min_version}},
            }
        )
        result = check_sonarqube_preconditions(
            model,
            client=clients.sonar(cfg, token),
            token_permissions=clients.sonar_permissions(cfg),
        )
        return _mapped("sonar", result.status, result.reason, result.details, token)
    except Exception as exc:
        return _failed("sonar", "probe_failed", redact_detail(exc, (token,)))


def _jenkins_result(
    request: ThirdPartyValidationRequest,
    resolver: SecretResolver,
    clients: ThirdPartyClientFactory,
) -> ThirdPartySystemResult:
    cfg = request.ci
    if not cfg.available:
        return _skipped("jenkins")
    token = resolver.resolve(cfg.token_env or "")
    if not token:
        return _failed("jenkins", "secret_unavailable", "token_env was not resolved")
    try:
        from agentkit.backend.config.models import JenkinsConfig
        from agentkit.backend.installer.integration_checkpoints.ci_preflight import (
            check_ci_preconditions,
        )

        model = JenkinsConfig.model_validate(cfg.model_dump(exclude={"user"}))
        result = check_ci_preconditions(model, client=clients.jenkins(cfg, token))
        return _mapped("jenkins", result.status, result.reason, result.details, token)
    except Exception as exc:
        return _failed("jenkins", "probe_failed", redact_detail(exc, (token,)))


def _are_result(
    request: ThirdPartyValidationRequest,
    resolver: SecretResolver,
    clients: ThirdPartyClientFactory,
) -> ThirdPartySystemResult:
    cfg = request.are
    if not cfg.enabled:
        return _skipped("are")
    token = resolver.resolve(cfg.token_env or "")
    if not token or not cfg.base_url:
        return _failed("are", "configuration_invalid", "base_url and token_env are required")
    try:
        response = clients.are(cfg, token).health()
        if response.status_code < 200 or response.status_code >= 300:
            return _failed("are", "unreachable", f"health returned HTTP {response.status_code}")
        return ThirdPartySystemResult(system="are", status="PASS", detail="reachable; token authenticated")
    except Exception as exc:
        return _failed("are", "unreachable", redact_detail(exc, (token,)))


def _mapped(
    system: str,
    status: str,
    reason: str | None,
    details: tuple[str, ...],
    token: str,
) -> ThirdPartySystemResult:
    code = f"{system}_{reason}" if reason else None
    return ThirdPartySystemResult(
        system=system,
        status=status,
        error_code=code,
        detail=redact_detail("; ".join(details), (token,)),
    )


def _failed(system: str, reason: str, detail: str) -> ThirdPartySystemResult:
    return ThirdPartySystemResult(system=system, status="FAILED", error_code=f"{system}_{reason}", detail=detail)


def _skipped(system: str) -> ThirdPartySystemResult:
    return ThirdPartySystemResult(system=system, status="SKIPPED", error_code=None, detail="not applicable")
