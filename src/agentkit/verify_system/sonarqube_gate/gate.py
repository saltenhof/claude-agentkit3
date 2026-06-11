"""SonarQube-Green-Gate capability orchestration (FK-33 §33.6).

This is the callable capability API used at the QA-subflow gate point
(wired by ``verify_system.system``) AND, without touching this story, at
the Setup-green-main precondition (FK-22, AG3-034) and the Closure
pre-merge scan / Integrity-Gate Dim 9 (FK-29/FK-35) — those are
consumers (AG3-052 §2.2 / AC8).

State-machine conformance (``formal.deterministic-checks.state-machine``):

* APPLICABLE -> read-attestation -> run-sonarqube-gate:
  green => ``sonarqube_gate_passed``; red/stale/unreachable or a 0/>1
  ledger reconciliation => ``failed`` DIRECTLY (never via policy).
* NOT_APPLICABLE_UNAVAILABLE (``available == false``) =>
  ``sonarqube_gate_not_applicable`` => policy proceeds.
* NOT_APPLICABLE_FAST (``mode == fast``) => the ``sonarqube_gate`` stage
  is DROPPED entirely (no Sonar verdict, no Sonar artefact, no policy over
  a Sonar outcome). The fast QA-subflow terminates via the Layer-1
  tests-green floor (FK-24 §24.3.4, FK-27 §27.6a). There is intentionally
  NO ``not_applicable_fast`` gate status: the state machine
  (``formal.deterministic-checks.state-machine``) knows no such Sonar
  state. The drop is enforced by the caller (``run_qa_subflow``), which
  never invokes the gate for a fast resolution; :func:`evaluate_sonarqube_gate`
  must therefore never be reached with ``NOT_APPLICABLE_FAST``.

Never fail-open.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from agentkit.verify_system.sonarqube_gate.applicability import (
    SonarApplicability,
    resolve_applicability,
)
from agentkit.verify_system.sonarqube_gate.attestation import is_green_status
from agentkit.verify_system.sonarqube_gate.errors import (
    ReconcilerApplyError,
    ReconcilerFailClosedError,
)
from agentkit.verify_system.sonarqube_gate.reconciler import reconcile_single_match

if TYPE_CHECKING:
    from collections.abc import Callable

    from agentkit.verify_system.sonarqube_gate.attestation import SonarAttestation
    from agentkit.verify_system.sonarqube_gate.ledger import (
        AcceptedExceptionLedgerEntry,
    )
    from agentkit.verify_system.sonarqube_gate.port import PostApplyGateState
    from agentkit.verify_system.sonarqube_gate.reconciler import SonarIssue


def _no_op_issue_applier(issue_key: str) -> None:
    """Default no-op issue applier (no Sonar admin step wired)."""
    del issue_key


@dataclass(frozen=True)
class SonarGateOutcome:
    """Result of one ``sonarqube_gate`` evaluation.

    Maps onto the ``formal.deterministic-checks`` gate states.

    Attributes:
        applicability: Resolved applicability state.
        passed: ``True`` only for an APPLICABLE green verdict; ``None``
            for a not-applicable outcome (no Sonar verdict produced).
        gate_status: State-machine status id reached
            (``sonarqube_gate_passed`` / ``failed`` /
            ``sonarqube_gate_not_applicable``).
        accepted_issue_keys: Issue keys the reconciler applied (empty
            unless APPLICABLE-green with ledger matches).
        failure_reason: Reason string when ``failed``; else ``None``.
    """

    applicability: SonarApplicability
    passed: bool | None
    gate_status: str
    accepted_issue_keys: tuple[str, ...] = ()
    failure_reason: str | None = None


def _not_applicable(applicability: SonarApplicability) -> SonarGateOutcome:
    """Build the NOT_APPLICABLE_UNAVAILABLE outcome (absent Sonar => SKIP).

    Only ``NOT_APPLICABLE_UNAVAILABLE`` reaches the gate as a runnable
    not-applicable state: it produces a ``sonarqube_gate_not_applicable``
    status and lets the policy engine aggregate over the other layers.
    ``NOT_APPLICABLE_FAST`` never reaches the gate — the caller drops the
    stage entirely (no invented ``not_applicable_fast`` Sonar status; the
    state machine knows none). Reaching this helper with FAST is a wiring
    bug and fails closed.
    """
    if applicability is not SonarApplicability.NOT_APPLICABLE_UNAVAILABLE:
        msg = (
            "evaluate_sonarqube_gate must not be invoked for "
            f"{applicability!r}; a fast resolution drops the sonarqube_gate "
            "stage in the caller (no Sonar verdict, no Sonar artefact)."
        )
        raise ValueError(msg)
    return SonarGateOutcome(
        applicability=applicability,
        passed=None,
        gate_status="sonarqube_gate_not_applicable",
    )


def _failed(applicability: SonarApplicability, reason: str) -> SonarGateOutcome:
    return SonarGateOutcome(
        applicability=applicability,
        passed=False,
        gate_status="failed",
        failure_reason=reason,
    )


def evaluate_sonarqube_gate(
    *,
    applicability: SonarApplicability,
    attestation: SonarAttestation | None,
    main_head_revision: str,
    ledger_entries: tuple[AcceptedExceptionLedgerEntry, ...],
    current_issues: tuple[SonarIssue, ...],
    issue_applier: Callable[[str], None] = _no_op_issue_applier,
    post_apply_reader: Callable[[], PostApplyGateState] | None = None,
) -> SonarGateOutcome:
    """Evaluate the gate for an already-resolved applicability.

    Wiring order for an APPLICABLE flow (FK-33 §33.6.3/§33.6.4, AC4):
    read attestation (stale-check) -> run reconciler on the final scan and
    APPLY each single-matched exception to Sonar BEFORE the verdict ->
    RE-READ the post-apply quality gate + open count from Sonar -> green/red.
    A stale/unreadable attestation, a 0/>1 ledger match, a failed apply, or a
    missing post-apply re-read fails closed DIRECTLY.

    E4 (red->green through the accept, no AK subtraction): once the reconciler
    has transitioned the single-matched issues to ``Accepted``, SonarQube
    itself recomputes the quality gate (Accepted issues drop out). The gate
    therefore RE-READS the resulting verdict + the fresh open-non-accepted
    count via ``post_apply_reader`` and evaluates green against THAT — it does
    NOT subtract accepted keys from a stale pre-apply count (FK-33 §33.6.3:
    "AK reads the gate status but does not re-interpret individual rules";
    §33.6.4: "Accepted counts as green"). The attestation's pre-apply
    ``quality_gate_status`` is used ONLY for the commit-binding stale-check,
    never for the green verdict.

    Args:
        applicability: Resolved applicability (see
            :func:`resolve_for_context`).
        attestation: The commit-bound attestation; ``None`` is treated as
            unreadable (fail-closed) for an APPLICABLE gate.
        main_head_revision: Authoritative current HEAD for stale-check.
        ledger_entries: Accepted-exception ledger entries to reconcile.
        current_issues: Current Sonar issues for the scan target (the
            pre-apply scan view the reconciler matches against).
        issue_applier: Callback that transitions a single-matched issue to
            ``Accepted`` in Sonar (scoped ``Administer Issues`` token,
            FK-33 §33.6.4). A raised exception fails the gate closed.
        post_apply_reader: Callback that RE-READS the quality-gate verdict +
            the open-non-accepted count from Sonar AFTER the accepts were
            applied (E4). MANDATORY for an APPLICABLE run; ``None`` fails
            closed (the gate cannot confirm green without the post-apply
            read). A raised exception is a configured-but-unreachable Sonar
            => fail-closed.

    Returns:
        A :class:`SonarGateOutcome`.
    """
    if applicability is not SonarApplicability.APPLICABLE:
        return _not_applicable(applicability)

    # APPLICABLE: read-attestation must succeed (fail-closed otherwise). The
    # attestation binds the verdict to a concrete analysis/commit; its status
    # is the PRE-apply read, used here only for the stale (commit-binding)
    # check, not for the green verdict (E4).
    if attestation is None:
        return _failed(applicability, "attestation_unreadable")
    if not attestation.is_bound_to(main_head_revision):
        return _failed(
            applicability,
            f"stale_attestation: last_analyzed_revision={attestation.last_analyzed_revision!r} "
            f"!= main_head={main_head_revision!r}",
        )

    # Reconciler runs on the final scan BEFORE the green/red verdict (AC4):
    # match single, then APPLY the accepted transition in Sonar (the worker
    # never holds Administer-Issues rights; the applier carries the scoped
    # token). 0/>1 match or a failed transition fails closed.
    try:
        reconciliation = reconcile_single_match(ledger_entries, current_issues)
        for issue_key in reconciliation.accepted_issue_keys:
            issue_applier(issue_key)
    except ReconcilerFailClosedError as exc:
        return _failed(applicability, f"ledger_reconcile_fail_closed: {exc}")
    except ReconcilerApplyError as exc:
        return _failed(applicability, f"ledger_apply_fail_closed: {exc}")

    # E4: the verdict MUST reflect the POST-apply scan state RE-READ from
    # Sonar. Without a re-read the gate cannot confirm green (fail-closed): a
    # missing reader on an APPLICABLE run is a broken precondition, not a pass.
    if post_apply_reader is None:
        return _failed(
            applicability,
            "post_apply_reread_unavailable: cannot confirm green without "
            "re-reading the post-apply quality gate (FK-33 §33.6.4)",
        )
    try:
        post = post_apply_reader()
    except (OSError, ValueError) as exc:
        # Configured-but-unreachable Sonar on the post-apply re-read.
        return _failed(applicability, f"post_apply_reread_failed: {exc}")

    if not is_green_status(
        post.quality_gate_status,
        overall_open_issue_count=post.overall_open_issue_count,
    ):
        return _failed(
            applicability,
            f"red_gate: quality_gate_status={post.quality_gate_status!r}, "
            f"overall_open_issues_post={post.overall_open_issue_count}, "
            f"accepted={len(reconciliation.accepted_issue_keys)}",
        )

    return SonarGateOutcome(
        applicability=applicability,
        passed=True,
        gate_status="sonarqube_gate_passed",
        accepted_issue_keys=reconciliation.accepted_issue_keys,
    )


def resolve_for_context(
    *,
    available: bool,
    fast: bool,
    story_type: object,
) -> SonarApplicability:
    """Convenience pass-through to :func:`resolve_applicability`.

    Re-exported on the capability surface so consumers (AG3-034, closure)
    resolve applicability without importing the ``applicability`` submodule.
    Typed loosely to keep the enum imports localised in the submodule.

    ``fast`` is the SEPARATE fast/standard axis (FK-24 §24.3.3), NOT the
    ``execution_route`` path — consumers pass ``story_context.mode is
    WireStoryMode.FAST``.
    """
    from agentkit.story_context_manager.types import StoryType

    resolved_type = story_type if isinstance(story_type, StoryType) else None
    if resolved_type is None:
        msg = f"story_type must be a StoryType; got {story_type!r}"
        raise TypeError(msg)
    return resolve_applicability(
        available=available, fast=fast, story_type=resolved_type
    )


__all__ = ["SonarGateOutcome", "evaluate_sonarqube_gate", "resolve_for_context"]
