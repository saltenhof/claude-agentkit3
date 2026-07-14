"""SonarQube installer preconditions — FK-50 CP 10d (applicability-conditional).

In scope (AG3-052 §2.1.6): the CP10d PRECONDITION checks.

* ``sonarqube.available == false`` -> CP SKIPPED (``reason="not_applicable"``),
  NOT FAILED.
* ``sonarqube.available == true`` -> server-side fail-closed:
  (a) reachability + ``min_version``;
  (b) token role incl. ``Administer Issues`` (for the reconciler);
  (c) Community Branch Plugin present and recent;
* The default quality-gate profile artefact remains a separate dev-local
  pre-send configuration check; no project root crosses into the backend.

Out of scope (AG3-052 §2.2): the CP10d config-drift-against-CP7 handling
(owner Installer/AG3-039). This story only builds/binds the derived
``config_hash`` (see ``sonarqube_gate.attestation``).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

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


def check_sonarqube_preconditions(
    config: SonarQubeConfig,
    *,
    client: SonarClient | None,
    token_permissions: frozenset[str],
) -> SonarPreflightResult:
    """Run only the light server-side SonarQube probes (fail-closed).

    Args:
        config: The ``sonarqube`` config stanza.
        client: A connected ``SonarClient`` (required when applicable).
        token_permissions: The token's effective global permissions.

    Returns:
        A :class:`SonarPreflightResult` (SKIPPED when not applicable).
    """
    if not config.available:
        return SonarPreflightResult(status=CheckpointStatus.SKIPPED, reason="not_applicable")
    return _run_applicable_checks(
        config,
        client=client,
        token_permissions=token_permissions,
    )


def _run_applicable_checks(
    config: SonarQubeConfig,
    *,
    client: SonarClient | None,
    token_permissions: frozenset[str],
) -> SonarPreflightResult:
    if client is None:
        return SonarPreflightResult(
            status=CheckpointStatus.FAILED,
            reason="missing_dependency",
            details=("a SonarClient is required when available",),
        )
    try:
        return _probe_server(config, client, token_permissions)
    except SonarApiError as exc:
        return SonarPreflightResult(
            status=CheckpointStatus.FAILED,
            reason="unreachable",
            details=(str(exc),),
        )


def check_default_profile(
    config: SonarQubeConfig, repo_root: Path
) -> SonarPreflightResult | None:
    """Validate the dev-local profile artifact before contacting the backend."""
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
) -> SonarPreflightResult:
    from agentkit.backend.installer.integration_checkpoints.sonar_probes import (
        verify_branch_plugin_presence,
        verify_reachable_version,
        verify_token_role,
    )

    details: list[str] = []
    for failure in (
        verify_reachable_version(client, config.min_version),
        verify_token_role(token_permissions),
        verify_branch_plugin_presence(client, config),
    ):
        if failure is not None:
            return failure
    details.append("reachable; version OK; token role OK; branch plugin present")
    return SonarPreflightResult(status=CheckpointStatus.PASS, details=tuple(details))


__all__ = [
    "ADMINISTER_ISSUES",
    "CheckpointStatus",
    "SonarPreflightResult",
    "check_default_profile",
    "check_sonarqube_preconditions",
]
