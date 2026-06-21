"""SonarQube installer preconditions — FK-50 CP 10d (applicability-conditional).

In scope (AG3-052 §2.1.6): the CP10d PRECONDITION checks.

* ``sonarqube.available == false`` -> CP SKIPPED (``reason="not_applicable"``),
  NOT FAILED.
* ``sonarqube.available == true`` -> fail-closed:
  (a) reachability + ``min_version``;
  (b) token role incl. ``Administer Issues`` (for the reconciler);
  (c) Community Branch Plugin present + a Branch-Plugin-Conformance
      self-test on a throwaway mini-project (plugin actually functional,
      not merely installed);
  plus the default quality-gate profile artefact path exists.

Out of scope (AG3-052 §2.2): the CP10d config-drift-against-CP7 handling
(owner Installer/AG3-039). This story only builds/binds the derived
``config_hash`` (see ``sonarqube_gate.attestation``).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Protocol

from agentkit.integration_clients.sonar import SonarApiError

if TYPE_CHECKING:
    from pathlib import Path

    from agentkit.backend.config.models import SonarQubeConfig
    from agentkit.integration_clients.sonar import SonarClient

#: Token permission the reconciler needs (FK-33 §33.6.4).
ADMINISTER_ISSUES = "Administer Issues"


class CheckpointStatus:
    """Checkpoint status string constants (FK-50)."""

    PASS = "PASS"
    FAILED = "FAILED"
    SKIPPED = "SKIPPED"


@dataclass(frozen=True)
class SonarPreflightResult:
    """Result of the CP 10d SonarQube preconditions.

    Attributes:
        status: ``PASS`` / ``FAILED`` / ``SKIPPED``.
        reason: Machine reason (``"not_applicable"`` when skipped; the
            failing precondition id when failed).
        details: Per-check evidence.
    """

    status: str
    reason: str | None = None
    details: tuple[str, ...] = field(default_factory=tuple)


class BranchPluginSelfTest(Protocol):
    """Branch-Plugin-Conformance self-test on a throwaway mini-project.

    The plugin is inofficial and only Trust-A-capable when this passes
    (FK-50 §50.3 CP 10d.2). Provisioning a scanner run is operational, so
    the runner is injected; tests supply a stub.
    """

    def __call__(self, client: SonarClient) -> bool:
        """Run the self-test; return ``True`` iff every step conformed."""
        ...


def check_sonarqube_preconditions(
    config: SonarQubeConfig,
    *,
    client: SonarClient | None,
    repo_root: Path,
    token_permissions: frozenset[str],
    branch_plugin_self_test: BranchPluginSelfTest | None,
) -> SonarPreflightResult:
    """Run the FK-50 CP 10d SonarQube preconditions (fail-closed).

    Args:
        config: The ``sonarqube`` config stanza.
        client: A connected ``SonarClient`` (required when applicable).
        repo_root: Repo root used to resolve the default-profile path.
        token_permissions: The token's effective global permissions.
        branch_plugin_self_test: Injected conformance self-test runner
            (required when applicable).

    Returns:
        A :class:`SonarPreflightResult` (SKIPPED when not applicable).
    """
    if not config.available:
        return SonarPreflightResult(status=CheckpointStatus.SKIPPED, reason="not_applicable")
    return _run_applicable_checks(
        config,
        client=client,
        repo_root=repo_root,
        token_permissions=token_permissions,
        branch_plugin_self_test=branch_plugin_self_test,
    )


def _run_applicable_checks(
    config: SonarQubeConfig,
    *,
    client: SonarClient | None,
    repo_root: Path,
    token_permissions: frozenset[str],
    branch_plugin_self_test: BranchPluginSelfTest | None,
) -> SonarPreflightResult:
    if client is None or branch_plugin_self_test is None:
        return SonarPreflightResult(
            status=CheckpointStatus.FAILED,
            reason="missing_dependency",
            details=("client and branch_plugin_self_test are required when available",),
        )
    profile_failure = _check_default_profile(config, repo_root)
    if profile_failure is not None:
        return profile_failure
    try:
        return _probe_server(config, client, token_permissions, branch_plugin_self_test)
    except SonarApiError as exc:
        return SonarPreflightResult(
            status=CheckpointStatus.FAILED,
            reason="unreachable",
            details=(str(exc),),
        )


def _check_default_profile(
    config: SonarQubeConfig, repo_root: Path
) -> SonarPreflightResult | None:
    profile_path = repo_root / config.quality_gate.default_profile
    if not profile_path.is_file():
        return SonarPreflightResult(
            status=CheckpointStatus.FAILED,
            reason="default_profile_missing",
            details=(f"default quality-gate profile not found: {profile_path}",),
        )
    return None


def _probe_server(
    config: SonarQubeConfig,
    client: SonarClient,
    token_permissions: frozenset[str],
    branch_plugin_self_test: BranchPluginSelfTest,
) -> SonarPreflightResult:
    from agentkit.backend.installer.integration_checkpoints.sonar_probes import (
        verify_branch_plugin,
        verify_reachable_version,
        verify_token_role,
    )

    details: list[str] = []
    for failure in (
        verify_reachable_version(client, config.min_version),
        verify_token_role(token_permissions),
        verify_branch_plugin(client, config, branch_plugin_self_test),
    ):
        if failure is not None:
            return failure
    details.append("reachable; version OK; token role OK; branch plugin conformant")
    return SonarPreflightResult(status=CheckpointStatus.PASS, details=tuple(details))


__all__ = [
    "ADMINISTER_ISSUES",
    "BranchPluginSelfTest",
    "CheckpointStatus",
    "SonarPreflightResult",
    "check_sonarqube_preconditions",
]
