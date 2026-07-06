"""Edge-Command-Queue vocabulary A-core (FK-91 §91.1b, AG3-145).

Blood-type A: pure, DB-free, unit-testable. FK-91 §91.1b defines the
Edge-Command-Queue (Auftrag/Meldung) that replaces backend-side physical
worktree operations (FK-10 §10.2.4a): the backend commissions a command, the
Project Edge executes it dev-locally and reports a typed result. This module
owns the closed, contract-pinned command-kind / result-type / lifecycle-status
vocabulary shared by both sides of the wire (backend command creation +
``harness_client`` edge executor) -- no I/O, no transactions.

``provision_worktree`` / ``teardown_worktree`` / ``preflight_probe`` (AG3-145
Teilschritt B) plus ``sync_push`` (the AG3-147 official Edge-Push-Gate path,
FK-10 §10.2.4b / FK-15 §15.5.4) are EXECUTED by the edge; ``takeover_reconcile``
/ ``merge_local`` are REGISTERED here (contract-pinned vocabulary) but their
commissioning/execution belongs to AG3-151 / AG3-152 respectively. An edge that
receives a command of a kind outside :data:`EXECUTABLE_COMMAND_KINDS` reports a
deterministic error result -- never a silent no-op (Scope item 4).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

__all__ = (
    "ALL_COMMAND_KINDS",
    "ALL_COMMAND_STATUSES",
    "EXECUTABLE_COMMAND_KINDS",
    "OPEN_COMMAND_STATUSES",
    "PREFLIGHT_FINDING_CODES",
    "RESULT_TYPES",
    "TAKEOVER_ERROR_RESULT_TYPES",
    "CommandKind",
    "CommandStatus",
    "PreflightEdgeFinding",
    "PreflightOwnershipContext",
    "PreflightProbeEvidence",
    "ResultType",
    "TakeoverErrorResultType",
    "decide_branch_preflight",
    "decide_worktree_preflight",
    "edge_command_id",
    "is_executable_command_kind",
    "is_known_command_kind",
)

#: FK-91 §91.1b "Auftragsarten (initial)": the closed set of command kinds the
#: Edge-Command-Queue can carry. Six total; four are executed (see
#: :data:`EXECUTABLE_COMMAND_KINDS`) -- the remaining two are registered
#: vocabulary owned by AG3-151 / AG3-152.
CommandKind = Literal[
    "provision_worktree",
    "teardown_worktree",
    "preflight_probe",
    "sync_push",
    "takeover_reconcile",
    "merge_local",
]

ALL_COMMAND_KINDS: frozenset[str] = frozenset(
    {
        "provision_worktree",
        "teardown_worktree",
        "preflight_probe",
        "sync_push",
        "takeover_reconcile",
        "merge_local",
    }
)

#: The edge executors that exist: the AG3-145 worktree/preflight trio plus the
#: AG3-147 ``sync_push`` official Edge-Push-Gate path (FK-10 §10.2.4b). A command
#: of any OTHER registered kind is a deterministic error result at the edge.
EXECUTABLE_COMMAND_KINDS: frozenset[str] = frozenset(
    {"provision_worktree", "teardown_worktree", "preflight_probe", "sync_push"}
)

#: FK-91 §91.1a Rule 16 (no wall-clock end): a command record's lifecycle
#: status. ``created`` = enqueued, not yet fetched by any GET; ``delivered`` =
#: the GET ack fired at least once; ``completed`` / ``failed`` are terminal (a
#: result was applied). ``superseded`` is a terminal backend transition for a
#: commissioned boundary command whose wait point escalated and rebound a newer
#: epoch; it is not a silent wall-clock expiry because the caller writes a
#: durable backlog verdict and audit payload at the same boundary decision.
CommandStatus = Literal["created", "delivered", "completed", "failed", "superseded"]

ALL_COMMAND_STATUSES: frozenset[str] = frozenset(
    {"created", "delivered", "completed", "failed", "superseded"}
)

#: The non-terminal statuses a session's GET may return / a POST result may
#: resolve from (SOLL-165: no wall-clock end -- an open command stays open
#: indefinitely, never silently dropped by a status sweep).
OPEN_COMMAND_STATUSES: frozenset[str] = frozenset({"created", "delivered"})

#: FK-91 §91.1b "Result-Typen": the three named report shapes.
ResultType = Literal["branch_ref_report", "push_status_report", "worktree_report"]

RESULT_TYPES: frozenset[str] = frozenset(
    {"branch_ref_report", "push_status_report", "worktree_report"}
)

#: FK-91 §91.1b / FK-30 §30.6.3: the named takeover-family error states --
#: benannte Result-Zustaende, never a collective FAIL.
#: ``local_stale_or_dirty_takeover_target`` doubles as a named Check-8
#: preflight finding (AG3-145 Teilschritt C, FK-22 §22.3.1).
TakeoverErrorResultType = Literal[
    "remote_branch_diverged_after_takeover",
    "local_stale_or_dirty_takeover_target",
    "contested_local_writes",
]

TAKEOVER_ERROR_RESULT_TYPES: frozenset[str] = frozenset(
    {
        "remote_branch_diverged_after_takeover",
        "local_stale_or_dirty_takeover_target",
        "contested_local_writes",
    }
)


def is_known_command_kind(kind: str) -> bool:
    """Return whether ``kind`` is one of the six registered command kinds."""
    return kind in ALL_COMMAND_KINDS


def is_executable_command_kind(kind: str) -> bool:
    """Return whether ``kind`` has a productive edge executor in THIS story.

    An edge dispatch loop uses this to decide between running an executor and
    reporting the deterministic "unsupported command kind" error result
    (never a silent no-op, AG3-145 Scope item 4).
    """
    return kind in EXECUTABLE_COMMAND_KINDS


def edge_command_id(run_id: str, command_kind: str, repo_id: str) -> str:
    """Return the deterministic command identity for a commissioned command.

    The Edge-Command-Queue identity is ``command_id`` (FK-91 §91.1b). The
    setup/reset commissioning path derives it deterministically from
    ``(run_id, command_kind, repo_id)`` so re-commissioning a command that
    already exists (a re-entered, still-paused setup phase) is idempotent by
    construction -- ``load_command`` finds the existing record instead of
    inserting a duplicate. Pure Blood-type A: no I/O.

    Args:
        run_id: The authoritative run id of the commissioning run.
        command_kind: One of :data:`ALL_COMMAND_KINDS`.
        repo_id: The participating repo the command targets.

    Returns:
        A stable, collision-free command identity string.
    """
    return f"{run_id}::{command_kind}::{repo_id}"


# ---------------------------------------------------------------------------
# Preflight checks 7/8 decision logic (FK-22 §22.3.1, AG3-145 Teilschritt C)
#
# Blood-type A: pure, DB-free. The Project Edge collects the ``preflight_probe``
# evidence (branch class + head SHA + local worktree/marker state -- NO
# decision, FK-22 §22.3.1); the BACKEND decides here with ownership context
# (active ``run_ownership_records`` row + ``takeover_transfer_records``.
# ``takeover_base_sha``) and the remote story-branch head SHA from the
# provider-adapter ``ls-remote`` ref-read (AG3-146). Every outcome is a NAMED,
# differentiated finding -- never a single collective FAIL.
# ---------------------------------------------------------------------------

#: PASS reason: neither a leftover branch nor a leftover worktree exists.
PREFLIGHT_FINDING_NO_LEFTOVER = "no_leftover_state"
#: PASS reason: the leftover state belongs to a LEGITIMATE takeover of this run.
PREFLIGHT_FINDING_LEGITIMATE_TAKEOVER = "legitimate_takeover"
#: FAIL (fail-closed): the edge probe result is missing or unreadable.
PREFLIGHT_FINDING_EDGE_PROBE_MISSING = "edge_probe_missing"
#: FAIL (Check 7): a ``story/{id}`` branch of an unfinished FOREIGN run exists.
PREFLIGHT_FINDING_STALE_FOREIGN_BRANCH = "stale_foreign_branch"
#: FAIL (Check 7): the local story branch is ahead of its remote ref.
PREFLIGHT_FINDING_LOCALLY_AHEAD = "locally_ahead"
#: FAIL (Check 7): the remote story branch diverged from the takeover base SHA.
PREFLIGHT_FINDING_REMOTE_DIVERGED = "remote_branch_diverged_after_takeover"
#: FAIL (Check 8): a foreign-run worktree directory exists locally.
PREFLIGHT_FINDING_FOREIGN_WORKTREE = "foreign_worktree"
#: FAIL (Check 8): the local worktree marker names a DIFFERENT story.
PREFLIGHT_FINDING_WRONG_MARKER = "wrong_marker_wrong_story"
#: FAIL (Check 7/8): the takeover target is locally stale/dirty (off the base).
PREFLIGHT_FINDING_LOCAL_STALE_OR_DIRTY = "local_stale_or_dirty_takeover_target"

#: The closed, contract-pinnable set of named preflight finding codes.
PREFLIGHT_FINDING_CODES: frozenset[str] = frozenset(
    {
        PREFLIGHT_FINDING_NO_LEFTOVER,
        PREFLIGHT_FINDING_LEGITIMATE_TAKEOVER,
        PREFLIGHT_FINDING_EDGE_PROBE_MISSING,
        PREFLIGHT_FINDING_STALE_FOREIGN_BRANCH,
        PREFLIGHT_FINDING_LOCALLY_AHEAD,
        PREFLIGHT_FINDING_REMOTE_DIVERGED,
        PREFLIGHT_FINDING_FOREIGN_WORKTREE,
        PREFLIGHT_FINDING_WRONG_MARKER,
        PREFLIGHT_FINDING_LOCAL_STALE_OR_DIRTY,
    }
)


@dataclass(frozen=True)
class PreflightProbeEvidence:
    """One repo's decision input: edge ``preflight_probe`` + backend reads.

    Combines the edge's pure collection
    (:class:`~agentkit.backend.control_plane.models.PreflightProbeReport`) with
    the two BACKEND per-repo reads the decision needs: the remote story-branch
    head SHA (provider-adapter ``ls-remote``, AG3-146) and the per-repo
    ``takeover_base_sha`` from ``takeover_transfer_records`` (FK-56 §56.13c).
    Never a decision itself -- the decision functions below consume it.

    Attributes:
        repo_id: The participating repo this evidence is for.
        branch_present: Whether a local ``story/{id}`` branch exists.
        head_sha: The local branch head SHA (``None`` when absent).
        worktree_present: Whether a local worktree directory exists.
        marker_present: Whether a ``.agentkit-story.json`` marker exists.
        marker_story_id: The ``story_id`` recorded in the local marker.
        remote_head_sha: The remote story-branch head SHA from the ``ls-remote``
            ref-read (``None`` when absent remotely or unresolved -- never a
            worktree git subprocess).
        takeover_base_sha: The per-repo ``takeover_base_sha`` from the active
            ``takeover_transfer_records`` row (``None`` when no takeover produced
            a base for this run/repo).
    """

    repo_id: str
    branch_present: bool
    head_sha: str | None = None
    worktree_present: bool = False
    marker_present: bool = False
    marker_story_id: str | None = None
    remote_head_sha: str | None = None
    takeover_base_sha: str | None = None


@dataclass(frozen=True)
class PreflightOwnershipContext:
    """Backend ownership decision context for checks 7/8 (FK-22 §22.3.1).

    Attributes:
        own_session_active_ownership: Whether the story's active
            ``run_ownership_records`` row belongs to THIS run/session (a
            legitimate active owner exists for the run being set up). Combined
            with a per-repo ``takeover_base_sha`` (on the evidence) this is what
            distinguishes a ``legitimate takeover`` from a ``stale foreign``
            leftover.
    """

    own_session_active_ownership: bool = False


@dataclass(frozen=True)
class PreflightEdgeFinding:
    """A single NAMED, differentiated preflight finding (FK-22 §22.3.1)."""

    passed: bool
    finding_code: str
    detail: str
    cleanup_hint: str | None = None


def _is_legitimate_takeover(
    evidence: PreflightProbeEvidence, ownership: PreflightOwnershipContext
) -> bool:
    """Whether an active own-session ownership + a repo takeover base both hold."""
    return (
        ownership.own_session_active_ownership
        and evidence.takeover_base_sha is not None
    )


def decide_branch_preflight(
    evidence: PreflightProbeEvidence | None,
    ownership: PreflightOwnershipContext,
) -> PreflightEdgeFinding:
    """Decide Check 7 (``no_story_branch``) for one repo, differentiated.

    FK-22 §22.3.1: distinguishes ``stale foreign`` (FAIL -- a human decides)
    from ``legitimate takeover`` (active own-session ownership PLUS alignment to
    ``takeover_base_sha`` -> PASS). A missing/unreadable probe FAILs fail-closed
    (never an optimistic PASS).

    Args:
        evidence: The repo's probe evidence, or ``None`` when the probe result
            is missing/unreadable.
        ownership: The backend ownership decision context.

    Returns:
        A NAMED :class:`PreflightEdgeFinding`.
    """
    if evidence is None:
        return PreflightEdgeFinding(
            passed=False,
            finding_code=PREFLIGHT_FINDING_EDGE_PROBE_MISSING,
            detail="edge preflight_probe result missing or unreadable",
            cleanup_hint=(
                "Re-run the Project Edge preflight_probe command; the backend "
                "never optimistically passes without the probe evidence."
            ),
        )
    if not evidence.branch_present:
        return PreflightEdgeFinding(
            passed=True,
            finding_code=PREFLIGHT_FINDING_NO_LEFTOVER,
            detail=f"no leftover story branch in repo {evidence.repo_id!r}",
        )
    if _is_legitimate_takeover(evidence, ownership):
        return _decide_takeover_branch(evidence)
    if (
        evidence.remote_head_sha is not None
        and evidence.head_sha is not None
        and evidence.head_sha != evidence.remote_head_sha
    ):
        return PreflightEdgeFinding(
            passed=False,
            finding_code=PREFLIGHT_FINDING_LOCALLY_AHEAD,
            detail=(
                f"local story branch in repo {evidence.repo_id!r} is ahead of "
                f"its remote ref ({evidence.head_sha} != {evidence.remote_head_sha})"
            ),
            cleanup_hint=(
                "A prior run left un-pushed local commits; recover or discard "
                "the branch before restarting."
            ),
        )
    return PreflightEdgeFinding(
        passed=False,
        finding_code=PREFLIGHT_FINDING_STALE_FOREIGN_BRANCH,
        detail=(
            f"branch of an unfinished prior (foreign) run exists in repo "
            f"{evidence.repo_id!r}"
        ),
        cleanup_hint=(
            "Delete the leftover story branch (or recover the prior run) "
            "before restarting; no active ownership legitimizes it."
        ),
    )


def _decide_takeover_branch(
    evidence: PreflightProbeEvidence,
) -> PreflightEdgeFinding:
    """Decide the branch check for a LEGITIMATE takeover (own active ownership)."""
    if evidence.head_sha != evidence.takeover_base_sha:
        return PreflightEdgeFinding(
            passed=False,
            finding_code=PREFLIGHT_FINDING_LOCAL_STALE_OR_DIRTY,
            detail=(
                f"takeover target in repo {evidence.repo_id!r} is off the "
                f"takeover base ({evidence.head_sha} != "
                f"{evidence.takeover_base_sha})"
            ),
            cleanup_hint=(
                "Reset the local story branch to the takeover base SHA before "
                "restarting the taken-over run."
            ),
        )
    if (
        evidence.remote_head_sha is not None
        and evidence.remote_head_sha != evidence.takeover_base_sha
    ):
        return PreflightEdgeFinding(
            passed=False,
            finding_code=PREFLIGHT_FINDING_REMOTE_DIVERGED,
            detail=(
                f"remote story branch in repo {evidence.repo_id!r} diverged from "
                f"the takeover base ({evidence.remote_head_sha} != "
                f"{evidence.takeover_base_sha})"
            ),
            cleanup_hint=(
                "The remote advanced after the takeover; reconcile the remote "
                "divergence before restarting."
            ),
        )
    return PreflightEdgeFinding(
        passed=True,
        finding_code=PREFLIGHT_FINDING_LEGITIMATE_TAKEOVER,
        detail=(
            f"legitimately taken-over branch in repo {evidence.repo_id!r} "
            "aligned to the takeover base"
        ),
    )


def decide_worktree_preflight(
    evidence: PreflightProbeEvidence | None,
    ownership: PreflightOwnershipContext,
    *,
    story_id: str,
) -> PreflightEdgeFinding:
    """Decide Check 8 (``no_stale_worktree``) for one repo, differentiated.

    FK-22 §22.3.1: named findings for a foreign worktree, a wrong-marker/wrong-
    story worktree, and a ``local_stale_or_dirty_takeover_target``; a legitimate
    takeover of THIS run's own active ownership PASSes. A missing/unreadable
    probe FAILs fail-closed.

    Args:
        evidence: The repo's probe evidence, or ``None`` when missing/unreadable.
        ownership: The backend ownership decision context.
        story_id: The story being set up (marker cross-check).

    Returns:
        A NAMED :class:`PreflightEdgeFinding`.
    """
    if evidence is None:
        return PreflightEdgeFinding(
            passed=False,
            finding_code=PREFLIGHT_FINDING_EDGE_PROBE_MISSING,
            detail="edge preflight_probe result missing or unreadable",
            cleanup_hint=(
                "Re-run the Project Edge preflight_probe command; the backend "
                "never optimistically passes without the probe evidence."
            ),
        )
    if not evidence.worktree_present:
        return PreflightEdgeFinding(
            passed=True,
            finding_code=PREFLIGHT_FINDING_NO_LEFTOVER,
            detail=f"no leftover worktree in repo {evidence.repo_id!r}",
        )
    if (
        evidence.marker_present
        and evidence.marker_story_id is not None
        and evidence.marker_story_id != story_id
    ):
        return PreflightEdgeFinding(
            passed=False,
            finding_code=PREFLIGHT_FINDING_WRONG_MARKER,
            detail=(
                f"local worktree in repo {evidence.repo_id!r} carries a marker "
                f"for a DIFFERENT story ({evidence.marker_story_id!r} != "
                f"{story_id!r})"
            ),
            cleanup_hint=(
                "A foreign story's worktree occupies this path; remove it "
                "before restarting."
            ),
        )
    if _is_legitimate_takeover(evidence, ownership):
        if not evidence.marker_present or evidence.marker_story_id != story_id:
            return PreflightEdgeFinding(
                passed=False,
                finding_code=PREFLIGHT_FINDING_LOCAL_STALE_OR_DIRTY,
                detail=(
                    f"takeover target worktree in repo {evidence.repo_id!r} is "
                    "stale/dirty (missing or mismatched story marker)"
                ),
                cleanup_hint=(
                    "Re-materialize the story marker or reset the worktree to "
                    "the takeover base before restarting the taken-over run."
                ),
            )
        return PreflightEdgeFinding(
            passed=True,
            finding_code=PREFLIGHT_FINDING_LEGITIMATE_TAKEOVER,
            detail=(
                f"legitimately taken-over worktree in repo {evidence.repo_id!r}"
            ),
        )
    return PreflightEdgeFinding(
        passed=False,
        finding_code=PREFLIGHT_FINDING_FOREIGN_WORKTREE,
        detail=(
            f"worktree of an unfinished prior (foreign) run exists in repo "
            f"{evidence.repo_id!r}"
        ),
        cleanup_hint=(
            "Remove the stale worktree (via the Project Edge teardown) before "
            "restarting; no active ownership legitimizes it."
        ),
    )
