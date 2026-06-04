"""Setup green-main precondition (FK-22 §22.4c) — consumes AG3-052.

Before a worktree is created for a code-producing story, Setup checks
deterministically (no LLM) whether the current ``main`` is *for itself* green.
This is the FIRST of the three ``sonarqube_gate`` lifecycle points (FK-33
§33.6.3, point 1); Setup is **caller, not owner** of the gate logic (FK-22
§22.4c.1).  All Sonar semantics live in the ``verify_system.sonarqube_gate``
capability (AG3-052) — this module resolves applicability via
:func:`resolve_for_context` and reads the commit-bound main attestation through
the injected capability port; it builds **no** attestation/reconciler/green
definition of its own (no second Sonar truth).

Applicability first (FK-33 §33.6.5): the precondition is only evaluated when
APPLICABLE (``available == true`` AND ``mode != fast`` AND code story).
``available == false`` -> SKIPPED (deliberate absence, skip-edge); ``mode ==
fast`` -> SKIPPED (sanity-gate replaces the green gate); concept/research ->
the precondition does not apply (no worktree, no analyzed code).  Only a
configured-but-red/stale/unreachable ``main`` (``available == true``) fails
closed — absent is not broken.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING, Protocol

from agentkit.story_context_manager.story_model import WireStoryMode
from agentkit.verify_system.sonarqube_gate import (
    SonarApplicability,
    is_green,
    resolve_for_context,
)

if TYPE_CHECKING:
    from agentkit.story_context_manager.types import StoryType
    from agentkit.verify_system.sonarqube_gate import SonarAttestation


class MainGreenStatus(StrEnum):
    """Outcome of the green-main precondition (FK-22 §22.4c.3 table)."""

    GREEN = "GREEN"
    SKIPPED = "SKIPPED"
    RED = "RED"
    STALE = "STALE"


@dataclass(frozen=True)
class MainGreenResult:
    """Result of the green-main precondition (FK-22 §22.4c).

    Attributes:
        status: GREEN (proceed) / SKIPPED (not applicable, proceed) / RED /
            STALE (both fail-closed).
        main_head: The current ``main`` HEAD revision (when resolved).
        analyzed_revision: The attestation's analyzed revision (STALE only).
        cleanup_proposal: Active, blame-free cleanup proposal on RED/STALE
            (FK-22 §22.4c.3) — never a silent failure.
    """

    status: MainGreenStatus
    main_head: str | None = None
    analyzed_revision: str | None = None
    cleanup_proposal: str | None = None

    @property
    def blocks_setup(self) -> bool:
        """Whether Setup must fail-closed (RED/STALE)."""
        return self.status in (MainGreenStatus.RED, MainGreenStatus.STALE)


@dataclass(frozen=True)
class MainAttestationView:
    """Commit-bound main-attestation view + open count (AG3-052 capability output).

    Carries the canonical AG3-052 :class:`SonarAttestation` (so the green
    definition is the capability's, not a second truth) plus the overall
    open-non-accepted issue count Sonar reported for the attested analysis —
    both inputs the AG3-052 green criterion (:func:`is_green` = QG OK AND
    overall-zero, FK-33 §33.6.3) needs.

    Attributes:
        attestation: The commit-bound ``SonarAttestation`` of ``main``.
        overall_open_issue_count: Open non-accepted issue count across the whole
            analysed overall-code scope (FK-33 §33.6.3 Broken-Window criterion).
    """

    attestation: SonarAttestation
    overall_open_issue_count: int


class MainGreenPort(Protocol):
    """Capability seam for the green-main read (``sonarqube_gate``).

    Resolves the current ``main`` HEAD and the commit-bound main attestation
    (QG per ``analysisId``, FK-33 §33.6.3) — never a bare ``projectKey``
    live-read.  Keeps ``governance`` free of any direct SonarQube adapter import.
    """

    def main_head_revision(self) -> str:
        """Return the current ``git main`` HEAD revision."""
        ...

    def read_main_attestation(self) -> MainAttestationView | None:
        """Return the commit-bound main attestation, or ``None`` if unreachable."""
        ...


_CLEANUP_PROPOSAL = (
    "start_independent_cleanup_worker (out_of_story, blame_free): main muss "
    "fuer sich gruen sein, bevor eine neue Story aufsetzt (Broken-Window). "
    "Vorschlag: eigenstaendiger Cleanup-Remediation-Worker ausserhalb dieses "
    "Story-Scopes (FK-22 §22.4c.3)."
)


def check_main_green_precondition(
    *,
    available: bool,
    mode: WireStoryMode | None,
    story_type: StoryType,
    port: MainGreenPort | None,
) -> MainGreenResult:
    """Evaluate the green-main precondition (FK-22 §22.4c), consuming AG3-052.

    Resolves applicability via :func:`resolve_for_context` (FK-33 §33.6.5); a
    not-applicable resolution (``available == false`` / fast / non-code story)
    is a SKIP (no fail-closed).  For an APPLICABLE story it reads the commit-
    bound main attestation through ``port`` and applies the AG3-052 green
    definition — ``is_green`` (QG OK AND overall-zero open non-accepted issues,
    FK-33 §33.6.3) for RED and ``SonarAttestation.is_bound_to`` for STALE — NOT
    a local ``quality_gate_ok`` (no second green truth).  RED or STALE fail
    closed with an active, blame-free cleanup proposal (§22.4c.3).

    Args:
        available: ``sonarqube.available`` (FK-03).
        mode: The story's fast/standard ``mode`` (``StoryContext.mode``,
            decoupled axis, FK-24 §24.3.3) — NOT ``execution_route``.
        story_type: The story type (only impl/bugfix are APPLICABLE).
        port: The ``sonarqube_gate`` capability seam.  Must be wired for an
            APPLICABLE story; ``None`` on an APPLICABLE story is a
            configured-but-unreachable RED (fail-closed, never a silent skip).

    Returns:
        The :class:`MainGreenResult`.
    """
    applicability = resolve_for_context(
        available=available,
        fast=mode is WireStoryMode.FAST,
        story_type=story_type,
    )
    if applicability is not SonarApplicability.APPLICABLE:
        # available==false / fast / non-code -> deliberate skip (skip-edge to
        # worktrees_ready); NOT a fail-closed (absent != broken, FK-33 §33.6.5).
        return MainGreenResult(status=MainGreenStatus.SKIPPED)

    if port is None:
        # APPLICABLE but no capability wired == configured-but-unreachable.
        return MainGreenResult(
            status=MainGreenStatus.RED,
            cleanup_proposal=_CLEANUP_PROPOSAL,
        )

    main_head = port.main_head_revision()
    view = port.read_main_attestation()
    if view is None:
        # configured-but-unreachable main attestation -> fail-closed RED.
        return MainGreenResult(
            status=MainGreenStatus.RED,
            main_head=main_head,
            cleanup_proposal=_CLEANUP_PROPOSAL,
        )
    attestation = view.attestation
    # STALE check FIRST via the AG3-052 commit binding: a green status for a
    # stale commit is invalid (FK-33 §33.6.3 — no stale green).
    if not attestation.is_bound_to(main_head):
        return MainGreenResult(
            status=MainGreenStatus.STALE,
            main_head=main_head,
            analyzed_revision=attestation.last_analyzed_revision,
            cleanup_proposal=_CLEANUP_PROPOSAL,
        )
    # GREEN only when the AG3-052 criterion holds: QG OK AND overall-zero open
    # non-accepted issues (is_green) — NOT a bare quality_gate_ok.
    if not is_green(
        attestation, overall_open_issue_count=view.overall_open_issue_count
    ):
        return MainGreenResult(
            status=MainGreenStatus.RED,
            main_head=main_head,
            cleanup_proposal=_CLEANUP_PROPOSAL,
        )
    return MainGreenResult(status=MainGreenStatus.GREEN, main_head=main_head)


__all__ = [
    "MainAttestationView",
    "MainGreenPort",
    "MainGreenResult",
    "MainGreenStatus",
    "check_main_green_precondition",
]
