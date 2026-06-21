"""Individual SonarQube CP 10d probe steps (FK-50 §50.3).

Each probe returns ``None`` on success or a ``SonarPreflightResult``
carrying the fail-closed FAILED outcome. Kept separate from the
orchestrator to keep module-level LOC small and each probe unit-testable.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from agentkit.backend.installer.integration_checkpoints.sonar_preflight import (
    ADMINISTER_ISSUES,
    CheckpointStatus,
    SonarPreflightResult,
)

if TYPE_CHECKING:
    from agentkit.backend.config.models import SonarQubeConfig
    from agentkit.backend.installer.integration_checkpoints.sonar_preflight import (
        BranchPluginSelfTest,
    )
    from agentkit.integration_clients.sonar import SonarClient

_COMMUNITY_BRANCH_PLUGIN_KEY = "communityBranchSupport"


def _parse_version(value: str) -> tuple[int, ...]:
    return tuple(int(part) for part in value.split(".") if part.isdigit())


def verify_reachable_version(
    client: SonarClient, min_version: str
) -> SonarPreflightResult | None:
    """Verify the server is reachable and at least ``min_version``."""
    response = client.system_status()
    version = str(response.json_body.get("version", ""))
    if not version:
        return SonarPreflightResult(
            status=CheckpointStatus.FAILED,
            reason="version_unknown",
            details=("api/system/status returned no version",),
        )
    if _parse_version(version) < _parse_version(min_version):
        return SonarPreflightResult(
            status=CheckpointStatus.FAILED,
            reason="version_too_low",
            details=(f"server version {version} < min_version {min_version}",),
        )
    return None


def verify_token_role(token_permissions: frozenset[str]) -> SonarPreflightResult | None:
    """Verify the token grants ``Administer Issues`` (for the reconciler)."""
    if ADMINISTER_ISSUES not in token_permissions:
        return SonarPreflightResult(
            status=CheckpointStatus.FAILED,
            reason="token_role_insufficient",
            details=(f"token is missing the {ADMINISTER_ISSUES!r} permission",),
        )
    return None


def verify_branch_plugin(
    client: SonarClient,
    config: SonarQubeConfig,
    branch_plugin_self_test: BranchPluginSelfTest,
) -> SonarPreflightResult | None:
    """Verify the Community Branch Plugin is present, recent, and conformant."""
    response = client.installed_plugins()
    plugins = response.json_body.get("plugins", [])
    plugin = _find_branch_plugin(plugins)
    if plugin is None:
        return SonarPreflightResult(
            status=CheckpointStatus.FAILED,
            reason="branch_plugin_missing",
            details=("Community Branch Plugin not installed",),
        )
    installed = str(plugin.get("version", ""))
    required = config.plugins.community_branch.min_version
    if _parse_version(installed) < _parse_version(required):
        return SonarPreflightResult(
            status=CheckpointStatus.FAILED,
            reason="branch_plugin_too_low",
            details=(f"branch plugin {installed} < min_version {required}",),
        )
    if not branch_plugin_self_test(client):
        return SonarPreflightResult(
            status=CheckpointStatus.FAILED,
            reason="branch_plugin_self_test_failed",
            details=("branch-plugin conformance self-test did not pass",),
        )
    return None


def _find_branch_plugin(plugins: object) -> dict[str, object] | None:
    if not isinstance(plugins, list):
        return None
    for entry in plugins:
        if isinstance(entry, dict) and entry.get("key") == _COMMUNITY_BRANCH_PLUGIN_KEY:
            return entry
    return None


__all__ = [
    "verify_branch_plugin",
    "verify_reachable_version",
    "verify_token_role",
]
