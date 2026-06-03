"""Port supplying the ``sonarqube_gate`` runtime inputs (AG3-052).

The QA-subflow stage runs the SonarQube-Green-Gate capability over inputs
that come from the environment (the resolved applicability plus the
commit-bound attestation, the accepted-exception ledger, the current
branch-scan issues, the authoritative main HEAD, and the overall open
non-accepted issue count). Those inputs are produced by an adapter that
talks to the ``integrations.sonar`` client and the config/state; the
``verify-system`` BC depends only on this port, not on the adapter.

The default port resolves NOT_APPLICABLE_UNAVAILABLE (no Sonar wired,
i.e. ``sonarqube.available == false``): the stage SKIPs and the policy
engine proceeds — never fail-open, never fail-closed (FK-33 §33.6.5).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Protocol

from agentkit.verify_system.sonarqube_gate.applicability import SonarApplicability

if TYPE_CHECKING:
    from collections.abc import Callable

    from agentkit.verify_system.sonarqube_gate.attestation import SonarAttestation
    from agentkit.verify_system.sonarqube_gate.ledger import (
        AcceptedExceptionLedgerEntry,
    )
    from agentkit.verify_system.sonarqube_gate.reconciler import SonarIssue


def _no_op_issue_applier(issue_key: str) -> None:
    """Default issue applier: no Sonar exception to transition.

    Used when the gate runs without a wired Sonar admin step (the absent
    default port and the test ports). With no ledger entries the reconciler
    never produces an issue key, so this is never invoked on those paths.
    """
    del issue_key  # No Sonar transition wired (absent/test path).


@dataclass(frozen=True)
class PostApplyGateState:
    """The POST-apply quality-gate read from Sonar (AG3-052 E4).

    After the reconciler transitions each single-matched issue to
    ``Accepted``, Sonar recomputes the quality gate itself (Accepted issues
    drop out of the gate). The gate RE-READS the resulting verdict + the
    fresh open-non-accepted count and evaluates green against THIS state —
    AK never subtracts accepted keys from a stale pre-apply count and never
    interprets individual QG rules (FK-33 §33.6.3/§33.6.4).

    Attributes:
        quality_gate_status: The RE-READ quality-gate status after the
            accepts were applied (e.g. ``OK``/``ERROR``).
        overall_open_issue_count: The RE-READ count of open, non-accepted
            issues across the whole analysed scope after the accepts.
    """

    quality_gate_status: str
    overall_open_issue_count: int


@dataclass(frozen=True)
class SonarGateInputs:
    """All runtime inputs needed to evaluate the gate for one scan target.

    Attributes:
        applicability: Pre-resolved applicability (FK-33 §33.6.5).
        attestation: Commit-bound attestation (``None`` => unreadable when
            APPLICABLE => fail-closed). Carries the commit binding for the
            stale check; its pre-apply ``quality_gate_status`` is NOT the
            green verdict (that comes from the post-apply re-read, E4).
        main_head_revision: Authoritative current HEAD (stale check).
        ledger_entries: Accepted-exception ledger entries to reconcile.
        current_issues: Current Sonar issues for the scan target (matched by
            the reconciler against the ledger; the pre-apply scan view).
        issue_applier: Callback that actually transitions a matched issue
            to ``Accepted`` in Sonar (scoped ``Administer Issues`` token,
            FK-33 §33.6.4). Invoked by the gate for each single-matched
            ledger issue BEFORE the green/red verdict; a failure here is a
            configured-but-unreachable Sonar => fail-closed. Defaults to a
            no-op for paths without a wired Sonar admin step.
        post_apply_reader: Callback that RE-READS the quality-gate verdict +
            the open-non-accepted count from Sonar AFTER the accepts were
            applied (AG3-052 E4). The gate evaluates green against this fresh
            read — Sonar itself removed the Accepted issues from the gate; AK
            only reads the new verdict, it does NOT subtract. For an APPLICABLE
            run the reader is MANDATORY (``None`` => fail-closed: the gate
            cannot confirm green without re-reading the post-apply state).
            Defaults to ``None`` (no Sonar wired to re-read).
    """

    applicability: SonarApplicability
    attestation: SonarAttestation | None = None
    main_head_revision: str = ""
    ledger_entries: tuple[AcceptedExceptionLedgerEntry, ...] = ()
    current_issues: tuple[SonarIssue, ...] = field(default_factory=tuple)
    issue_applier: Callable[[str], None] = _no_op_issue_applier
    post_apply_reader: Callable[[], PostApplyGateState] | None = None


class SonarGateInputPort(Protocol):
    """Read-port resolving :class:`SonarGateInputs` for a QA-subflow run."""

    def resolve_inputs(self, story_id: str, story_dir: object) -> SonarGateInputs:
        """Resolve the gate inputs for the given story/scan target."""
        ...


@dataclass(frozen=True)
class _AbsentSonarGatePort:
    """Default port: Sonar deliberately absent (``available == false``)."""

    def resolve_inputs(self, story_id: str, story_dir: object) -> SonarGateInputs:
        """Return the absent-Sonar inputs (SKIP, no fail-closed).

        Resolves to ``NOT_APPLICABLE_UNAVAILABLE`` (FK-33 §33.6.5): a
        deliberately absent Sonar is skipped, never failed closed.
        """
        del story_id, story_dir  # Port params unused by the absent-default.
        return SonarGateInputs(
            applicability=SonarApplicability.NOT_APPLICABLE_UNAVAILABLE
        )


#: Module-level default port (Sonar absent => stage SKIP). Named ``ABSENT_``
#: (deliberately NOT carrying the not-applicable stem) so the legacy-token
#: guard reserves that stem for the two normative applicability values only.
ABSENT_SONAR_GATE_PORT: SonarGateInputPort = _AbsentSonarGatePort()


__all__ = [
    "ABSENT_SONAR_GATE_PORT",
    "PostApplyGateState",
    "SonarGateInputPort",
    "SonarGateInputs",
]
