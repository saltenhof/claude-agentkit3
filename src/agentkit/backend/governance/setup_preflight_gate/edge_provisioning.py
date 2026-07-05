"""Edge-provisioning coordinator port for the setup phase (AG3-145 Teilschritt C).

FK-10 §10.2.4a moves physical worktree operations off the backend run onto the
Project Edge (commissioned, reporting). The setup phase no longer calls
``create_worktree`` / ``write_story_marker``; instead it COMMISSIONS the edge
(``provision_worktree`` per participating repo) and CONSUMES the reported
``worktree_report`` -- the reported paths are the SINGLE truth for the session's
``worktree_roots`` (FK-56 §56.8). Preflight checks 7/8 likewise consume the
edge ``preflight_probe`` evidence plus the backend ownership decision context.

This module owns the CONSUMER-side port (Protocol) + the result value objects
only. The concrete adapter -- which reaches into the control-plane
``EdgeCommandRepository`` (commission + read), the ``RunOwnershipRepository`` /
``TakeoverTransferRepository`` (ownership context) and the AG3-146 provider
adapter (``ls-remote`` ref-read) -- is built at the composition root (the
sanctioned wiring boundary). Keeping the port here lets ``phase.py`` stay free
of ``state_backend.store`` imports (architecture conformance).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from pathlib import Path

    from agentkit.backend.control_plane.edge_commands import (
        PreflightOwnershipContext,
        PreflightProbeEvidence,
    )

__all__ = [
    "EdgeProvisioningCoordinator",
    "ProbeOutcome",
    "ProvisioningOutcome",
]


@dataclass(frozen=True)
class ProbeOutcome:
    """Result of commissioning + reading the ``preflight_probe`` commands.

    Attributes:
        pending: ``True`` when at least one repo's probe command is still open
            (created/delivered, not yet reported). The setup phase then PAUSES
            fail-closed (``AWAITING_EDGE_PROVISIONING``); it never proceeds on a
            partial probe.
        evidence: Per-repo probe evidence keyed by ``repo_id``. A ``None`` value
            marks a repo whose command terminated but whose report was
            unreadable / an error -- the preflight check FAILs fail-closed for
            it (never an optimistic PASS). Empty/partial while ``pending``.
        ownership: The backend ownership decision context (active
            ``run_ownership_records`` row + ``takeover_base_sha``) shared by all
            repos of the run.
    """

    pending: bool
    evidence: dict[str, PreflightProbeEvidence | None] = field(default_factory=dict)
    ownership: PreflightOwnershipContext | None = None


@dataclass(frozen=True)
class ProvisioningOutcome:
    """Result of commissioning + reading the ``provision_worktree`` commands.

    Attributes:
        pending: ``True`` when at least one repo's provisioning command is still
            open. The setup phase PAUSES fail-closed until every repo reported.
        worktree_map: Per-repo physical worktree root (``repo_id`` -> path)
            taken from the reported ``worktree_report`` -- the SINGLE truth for
            ``StoryContext.worktree_map`` (the backend derives no path itself).
        failed_repos: Repos whose provisioning command terminated with an error
            (``command_error`` / a non-``provisioned`` outcome). A non-empty
            tuple fails the setup phase closed.
    """

    pending: bool
    worktree_map: dict[str, Path] = field(default_factory=dict)
    failed_repos: tuple[str, ...] = ()


class EdgeProvisioningCoordinator(Protocol):
    """Commission + consume the edge worktree/probe commands (FK-91 §91.1b).

    Both methods are IDEMPOTENT: they commission a repo's command only when it
    does not already exist (deterministic ``command_id``), then read back the
    reported result. A re-entered, still-paused setup phase therefore never
    double-commissions.
    """

    def ensure_preflight_probes(
        self,
        *,
        project_key: str,
        story_id: str,
        run_id: str,
        repos: tuple[str, ...],
        branch: str,
    ) -> ProbeOutcome:
        """Commission (if absent) and read the ``preflight_probe`` commands.

        Args:
            project_key: Owning project key.
            story_id: The story being set up.
            run_id: The authoritative run id (also scopes the ownership read).
            repos: The participating repos to probe.
            branch: The story branch name (``story/{id}``).

        Returns:
            A :class:`ProbeOutcome` (pending, per-repo evidence, ownership ctx).
        """
        ...

    def ensure_provisioning(
        self,
        *,
        project_key: str,
        story_id: str,
        run_id: str,
        repos: tuple[str, ...],
        branch: str,
        base_ref: str,
    ) -> ProvisioningOutcome:
        """Commission (if absent) and read the ``provision_worktree`` commands.

        Args:
            project_key: Owning project key.
            story_id: The story being set up.
            run_id: The authoritative run id (also scopes the ownership read).
            repos: The participating repos to provision.
            branch: The story branch name (``story/{id}``).
            base_ref: The base ref the story branch is cut from.

        Returns:
            A :class:`ProvisioningOutcome` (pending, worktree map, failed repos).
        """
        ...

    def ensure_teardown(
        self,
        *,
        project_key: str,
        story_id: str,
        run_id: str,
        repos: tuple[str, ...],
        branch: str,
    ) -> None:
        """Commission ``teardown_worktree`` per repo (setup-failure cleanup, D).

        Fire-and-forget: commissions one idempotent ``teardown_worktree`` command
        per participating repo so a setup that fails AFTER provisioning does not
        silently leak a worktree (FK-10 §10.4.2/§10.5.3). The caller does not
        block on the physical removal; the open command stays auditably visible.

        Args:
            project_key: Owning project key.
            story_id: The story being torn down.
            run_id: The authoritative run id (scopes the deterministic id).
            repos: The participating repos to tear down.
            branch: The story branch name (``story/{id}``).
        """
        ...
