"""CI (Jenkins) installer preconditions — applicability-conditional (AG3-056).

Mirrors the SonarQube CP 10d discipline for the pre-merge verification
runner's CI dependency (AG3-056 §2.1.6 / §4.2):

* ``ci.available == false`` -> CP SKIPPED (``reason="not_applicable"``), NOT
  FAILED (a deliberate, declared absence).
* ``ci.available == true`` -> fail-closed:
  (a) reachability (``api/json`` responds);
  (b) the configured token authenticates (``me/api/json``);
  (c) the configured pipeline/job exists (``job/<pipeline>/api/json``).

A configured-but-unreachable Jenkins (``available == true`` + unreachable)
FAILS closed — never a silent skip (AG3-056 §2.1.4).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from agentkit.integrations.jenkins import JenkinsApiError

if TYPE_CHECKING:
    from agentkit.config.models import JenkinsConfig
    from agentkit.integrations.jenkins import JenkinsClient


class CheckpointStatus:
    """Checkpoint status string constants (FK-50)."""

    PASS = "PASS"
    FAILED = "FAILED"
    SKIPPED = "SKIPPED"


@dataclass(frozen=True)
class CiPreflightResult:
    """Result of the CI (Jenkins) preconditions.

    Attributes:
        status: ``PASS`` / ``FAILED`` / ``SKIPPED``.
        reason: Machine reason (``"not_applicable"`` when skipped; the failing
            precondition id when failed).
        details: Per-check evidence.
    """

    status: str
    reason: str | None = None
    details: tuple[str, ...] = field(default_factory=tuple)


def check_ci_preconditions(
    config: JenkinsConfig,
    *,
    client: JenkinsClient | None,
) -> CiPreflightResult:
    """Run the CI (Jenkins) preconditions (applicability-conditional, fail-closed).

    Args:
        config: The ``ci`` (Jenkins) config stanza.
        client: A connected ``JenkinsClient`` (required when applicable).

    Returns:
        A :class:`CiPreflightResult` (SKIPPED when ``available == false``).
    """
    if not config.available:
        return CiPreflightResult(
            status=CheckpointStatus.SKIPPED, reason="not_applicable"
        )
    if client is None:
        return CiPreflightResult(
            status=CheckpointStatus.FAILED,
            reason="missing_dependency",
            details=("a JenkinsClient is required when ci.available=true",),
        )
    if not config.pipeline:
        return CiPreflightResult(
            status=CheckpointStatus.FAILED,
            reason="pipeline_unset",
            details=("ci.available=true requires a pipeline name",),
        )
    try:
        return _probe_server(config.pipeline, client)
    except JenkinsApiError as exc:
        return CiPreflightResult(
            status=CheckpointStatus.FAILED,
            reason="unreachable",
            details=(str(exc),),
        )


def _probe_server(pipeline: str, client: JenkinsClient) -> CiPreflightResult:
    # Reachability + token authentication: ``me/api/json`` requires a valid
    # token and proves both at once (a non-2xx raises JenkinsApiError above).
    who = client.whoami().json_body
    if not who:
        return CiPreflightResult(
            status=CheckpointStatus.FAILED,
            reason="token_invalid",
            details=("me/api/json returned no authenticated identity",),
        )
    # Pipeline/job existence: a missing job raises JenkinsApiError (HTTP 404),
    # handled by the caller as ``unreachable``; a present job returns metadata.
    job = client.job_exists(pipeline).json_body
    if not job:
        return CiPreflightResult(
            status=CheckpointStatus.FAILED,
            reason="pipeline_missing",
            details=(f"job/{pipeline}/api/json returned no job metadata",),
        )
    return CiPreflightResult(
        status=CheckpointStatus.PASS,
        details=("reachable; token authenticated; pipeline exists",),
    )


__all__ = [
    "CheckpointStatus",
    "CiPreflightResult",
    "check_ci_preconditions",
]
