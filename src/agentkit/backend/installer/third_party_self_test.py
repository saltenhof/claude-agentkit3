"""Execution of the explicit heavy branch-plugin self-test."""

from __future__ import annotations

from typing import TYPE_CHECKING

from agentkit.backend.control_plane.third_party_models import (
    BranchPluginSelfTestOperation,
    BranchPluginSelfTestRequest,
)
from agentkit.backend.installer.third_party_redaction import redact_detail

if TYPE_CHECKING:
    from agentkit.backend.installer.third_party_clients import (
        SecretResolver,
        ThirdPartyClientFactory,
    )


def execute_branch_plugin_self_test(
    request: BranchPluginSelfTestRequest,
    resolver: SecretResolver,
    clients: ThirdPartyClientFactory,
) -> BranchPluginSelfTestOperation:
    """Run the existing conformance logic through backend-owned clients."""
    sonar_token = resolver.resolve(request.sonar.token_env or "")
    ci_token = resolver.resolve(request.ci.token_env or "")
    if not sonar_token or not ci_token:
        return _failed(request.op_id, "self_test_secret_unavailable", "required token_env was not resolved")
    try:
        from agentkit.backend.installer.integration_checkpoints.branch_plugin_self_test import (
            run_branch_plugin_conformance_self_test,
        )
        from agentkit.backend.installer.integration_checkpoints.jenkins_selftest_harness import (
            JenkinsBranchPluginSelfTestHarness,
        )

        sonar = clients.sonar(request.sonar, sonar_token)
        jenkins = clients.jenkins(request.ci, ci_token)
        harness = JenkinsBranchPluginSelfTestHarness(
            sonar_client=sonar,
            jenkins_client=jenkins,
            pipeline=request.ci.pipeline or "",
        )
        passed = run_branch_plugin_conformance_self_test(sonar, harness)
    except Exception as exc:
        detail = redact_detail(exc, (sonar_token, ci_token))
        return _failed(request.op_id, "branch_plugin_self_test_failed", detail)
    if not passed:
        return _failed(
            request.op_id,
            "branch_plugin_self_test_failed",
            "branch-plugin conformance self-test did not pass",
        )
    return BranchPluginSelfTestOperation(
        op_id=request.op_id,
        status="succeeded",
        detail="branch-plugin conformance self-test passed",
    )


def _failed(op_id: str, error_code: str, detail: str) -> BranchPluginSelfTestOperation:
    return BranchPluginSelfTestOperation(
        op_id=op_id,
        status="failed",
        error_code=error_code,
        detail=detail,
    )


__all__ = ["execute_branch_plugin_self_test"]
