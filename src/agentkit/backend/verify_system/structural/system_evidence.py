"""Independent SYSTEM evidence for the BLOCKING Layer-1 checks (FK-33 §33.5).

FK-33 §33.5.1/§33.5.2 core rule: a BLOCKING (or MAJOR) structural check may
only decide on Trust-A (authoritative system) or Trust-B (system-emitted)
evidence -- NEVER on Trust-C ``WORKER_ASSERTION`` (the worker's own
``worker-manifest.json``). "Class C may never be blocking ... the agent must
not be able to pass its own check" (FK-07-008).

The branch / commit-history / push / secret-scan / impact BLOCKING checks
therefore decide on INDEPENDENT system evidence collected here (real ``git``
in production), NOT on the worker manifest. ``git`` branch/commit/diff data is
Trust B ("system-emitted data ... commit history, build result",
FK-33 §33.5.1). The actual change impact (FK-23 §23.8) is computed from the
SYSTEM diff, not read back from what the worker declared.

This module owns ONLY the port contract + the value object + a fail-closed
absent default. The productive subprocess-``git`` provider is wired by the
composition root (``build_verify_system``), keeping ``verify_system`` free of
subprocess and of any ``agentkit.backend.closure`` import (BC-topology, AG3-035).

FAIL-CLOSED: the absent default returns ``available=False`` so every BLOCKING
check that needs system evidence FAILs when no provider is wired (a missing
git provider can never silently pass a worker's self-report).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from pathlib import Path

    from agentkit.backend.story_context_manager.story_model import ChangeImpact

__all__ = [
    "ABSENT_CHANGE_EVIDENCE_PORT",
    "ABSENT_PUSH_VERIFICATION_PORT",
    "ChangeEvidence",
    "ChangeEvidencePort",
    "PushVerificationPort",
]


@dataclass(frozen=True)
class ChangeEvidence:
    """Independent system evidence about the story's change set (FK-33 §33.5).

    Every field is derived from the SYSTEM (real ``git`` / a diff-based impact
    calculation), NOT from ``worker-manifest.json``. ``available`` is the
    fail-closed discriminator: ``False`` means the evidence could not be
    collected (no git repo / git unreadable), so the BLOCKING checks that
    consult it FAIL (NO ERROR BYPASSING) rather than fall back to worker self-
    report.

    Attributes:
        available: ``True`` only when the git evidence was collected. ``False``
            => unconfirmable => the consulting BLOCKING checks fail closed.
        current_branch: The actual checked-out branch (``git rev-parse
            --abbrev-ref HEAD``), or ``None`` when unresolvable.
        commit_messages: The story-branch commit messages since the base ref
            (``git log <base>..HEAD``), newest first. Empty when there are
            none.
        pushed: Whether the story branch is SERVER-verified-pushed in every
            participating repo (AG3-147). Sourced from the two-stage push
            barrier via :class:`PushVerificationPort` (the Edge push report AND
            the server ``ls-remote`` ref-read), NOT a backend-local ``git``
            upstream check (SOLL-142/170: "allein lokal" is forbidden).
            Independent of any worker claim.
        secret_files: Changed paths (``git diff --name-only``) that match a
            forbidden secret filename or extension, computed over the SYSTEM
            diff via the shared guard-system secret pattern source.
        secret_content_hits: Changed-path references whose added diff lines
            match the shared content secret patterns.
        changed_files: All changed paths in the diff (``git diff --name-only``
            since the base ref), for the hygiene scans.
        actual_impact: The SYSTEM-computed actual change impact (FK-23 §23.8),
            or ``None`` when it cannot be derived.
    """

    available: bool
    current_branch: str | None = None
    commit_messages: tuple[str, ...] = ()
    pushed: bool = False
    secret_files: tuple[str, ...] = ()
    secret_content_hits: tuple[str, ...] = ()
    changed_files: tuple[str, ...] = ()
    actual_impact: ChangeImpact | None = None


@runtime_checkable
class PushVerificationPort(Protocol):
    """Confirm the story branch is server-verified-pushed (AG3-147, FK-10 §10.2.4b).

    The AC11 retarget seam: ``completion.push`` KEEPS deciding on
    :attr:`ChangeEvidence.pushed`, but that field is no longer computed from a
    backend-local ``git`` upstream check (SOLL-142/170: "allein lokal" is
    forbidden). It is sourced HERE, from the two-stage push barrier (the Edge
    push report AND the server ``ls-remote`` ref-read); the Edge report alone is
    never sufficient (FK-91 §91.1b). The provider that fills ``ChangeEvidence``
    consults this port instead of shelling git. The productive adapter is wired
    by the composition root (verify-system never imports control-plane /
    state-backend directly -- BC-topology, AG3-035).
    """

    def confirm_story_pushed(self, story_dir: Path) -> bool:
        """Whether the story branch is server-verified-pushed in every repo.

        Args:
            story_dir: The story working directory (the run scope is resolved
                from it Backend-side).

        Returns:
            ``True`` only when the two-stage barrier confirms EVERY participating
            repo. Fail-closed ``False`` on any unresolvable scope / unverified
            repo (so ``completion.push`` FAILs rather than fall back to a local
            self-report).
        """
        ...


@dataclass(frozen=True)
class _AbsentPushVerificationPort:
    """Default port: the push is never confirmable (fail-closed)."""

    def confirm_story_pushed(self, story_dir: Path) -> bool:
        """Return ``False`` -- no push-verification adapter wired (fail-closed)."""
        del story_dir
        return False


#: Default fail-closed push-verification port (no barrier adapter wired). The
#: BLOCKING ``completion.push`` check FAILs on this default (NO ERROR BYPASSING).
ABSENT_PUSH_VERIFICATION_PORT: PushVerificationPort = _AbsentPushVerificationPort()


@runtime_checkable
class ChangeEvidencePort(Protocol):
    """Read-port returning INDEPENDENT system evidence for a story (FK-33 §33.5).

    The productive adapter (wired via the composition root) runs read-only
    ``git`` commands over the story worktree and computes the actual impact
    from the diff; unit tests pass a recording double. The verify-system BC
    never imports subprocess / closure directly (BC-topology).
    """

    def collect(self, story_dir: Path) -> ChangeEvidence:
        """Collect the system change evidence for ``story_dir``.

        Args:
            story_dir: The story working directory (git worktree root).

        Returns:
            A :class:`ChangeEvidence`; ``available=False`` when the evidence
            cannot be collected (fail-closed).
        """
        ...


@dataclass(frozen=True)
class _AbsentChangeEvidencePort:
    """Default port: system evidence is always unconfirmable (fail-closed)."""

    def collect(self, story_dir: Path) -> ChangeEvidence:
        """Return an ``available=False`` evidence (no git provider wired)."""
        del story_dir
        return ChangeEvidence(available=False)


#: Default fail-closed port (no live git evidence provider wired). The BLOCKING
#: branch / commit / push / secrets / impact checks FAIL on this default.
ABSENT_CHANGE_EVIDENCE_PORT: ChangeEvidencePort = _AbsentChangeEvidencePort()
