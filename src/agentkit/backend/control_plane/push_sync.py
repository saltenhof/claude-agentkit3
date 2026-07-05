"""Sync-point / push-barrier A-core (FK-10 §10.2.4b, FK-12 §12.1.3, AG3-147).

Blood-type A: pure, DB-free, wire-free, unit-testable. This module owns the
*fachliche* heart of the pushed-only enforcement (PO-Entscheidung II, FK-10
§10.2.4b): "what is not committed AND pushed to the story branch does not exist
for AgentKit and is never takeover-eligible". It contains **no** I/O, no
subprocess, no persistence and no wire models -- the R-layer (runtime consume,
HTTP read model, edge gate) maps the Edge-Command-Queue results (AG3-145) and
the provider ``ls-remote`` ref-read (AG3-146) onto the primitive inputs below.

The pieces (each pure):

* The four **sync-point barrier types** (FK-10 §10.2.4b hybrid): phase
  completion, QA-cycle boundary, yield-point, closure entry.
* The **two-stage barrier predicate** (In-Scope #1, AC1/AC3): a repo counts as
  verified-pushed only when BOTH the Edge push report AND the server-side
  ``ls-remote`` ref-read confirm the SAME head SHA. The Edge report alone is
  never sufficient (FK-91 §91.1b). Multi-repo aggregation is a hard AND: a
  single un-verified repo blocks the whole barrier (AC3).
* The **push-freshness / backlog** record + its pure projection (In-Scope #3,
  AC5): last reported head SHA + instant + backlog hint per ``(story, run,
  repo)``. Freshness/silence is INFORMATION, never an ownership decision.
* The **write-authorization rule** (In-Scope #5, AC7/AC8): ``story/*`` writes
  are released ONLY for the current ``(owner_session, ownership_epoch)``.
* The **ref-protection degradation rule** (In-Scope #6, AC9): a provider that
  cannot back the ref-protection capability yields a deterministic WARNING
  finding, never a silent pass.
* The **official-ref rule** (In-Scope #7, AC10): the only push target is
  ``story/{story_id}``; there is no WIP-ref push path.
* The **push-gate decision** (In-Scope #4, AC6): online-pflichtig, bounded; a
  stale ACTIVE bundle grants no push (the FK-56 §56.9a re-sync fallback does
  not apply to the push path, FK-15 §15.5.4).
* The **merge precondition** (In-Scope #9, AC12, SOLL-190): the reusable
  "pushed in all participating repos, server-verified" checkpoint AG3-152
  consumes before ``merge_local``.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from collections.abc import Sequence
    from datetime import datetime

__all__ = [
    "STORY_REF_PREFIX",
    "BarrierVerdict",
    "MergePrecondition",
    "PushBarrierBlockCode",
    "PushFreshnessRecord",
    "PushGateDecision",
    "PushGateRefusalCode",
    "RefProtectionDegradationFinding",
    "RepoPushVerdict",
    "RepoPushVerificationInput",
    "StoryRefWriteAuthorization",
    "StoryRefWriteRefusalCode",
    "SyncPointBarrierType",
    "assess_ref_protection_capability",
    "authorize_story_ref_write",
    "decide_push_gate",
    "evaluate_push_barrier",
    "evaluate_repo_push",
    "is_official_story_ref",
    "official_story_ref",
    "project_push_freshness",
    "verify_pushed_across_repos",
]

#: The canonical push target namespace (FK-22 §22, In-Scope #7). The official
#: push path pushes EXACTLY ``story/{story_id}`` -- no WIP ref path exists.
STORY_REF_PREFIX = "story/"

#: The push-status outcome the Edge reports per repo (FK-91 §91.1b): ``pushed``
#: means the commit reached the remote; ``behind_remote`` is a push backlog.
PushOutcome = Literal["pushed", "behind_remote"]


class SyncPointBarrierType(StrEnum):
    """The four hard fail-closed push barriers (FK-10 §10.2.4b hybrid)."""

    PHASE_COMPLETION = "phase_completion"
    QA_CYCLE_BOUNDARY = "qa_cycle_boundary"
    YIELD_POINT = "yield_point"
    CLOSURE_ENTRY = "closure_entry"


class PushBarrierBlockCode(StrEnum):
    """Named, contract-pinned barrier block reasons (never a collective FAIL)."""

    NO_EDGE_PUSH_REPORT = "no_edge_push_report"
    EDGE_REPORTS_BACKLOG = "edge_reports_backlog"
    MISSING_EDGE_HEAD_SHA = "missing_edge_head_sha"
    SERVER_REF_UNRESOLVED = "server_ref_unresolved"
    SERVER_HEAD_MISMATCH = "server_head_mismatch"
    NO_PARTICIPATING_REPOS = "no_participating_repos"


class StoryRefWriteRefusalCode(StrEnum):
    """Named ``story/*`` write-release refusals (FK-12 §12.1.3, AC7)."""

    NO_ACTIVE_OWNERSHIP = "no_active_ownership"
    OWNERSHIP_TRANSFERRED = "ownership_transferred"
    STALE_OWNERSHIP_EPOCH = "stale_ownership_epoch"


class PushGateRefusalCode(StrEnum):
    """Named Edge-push-gate refusals (FK-15 §15.5.4, AC6/AC7/AC10)."""

    OFFLINE_NO_SERVER_CONFIRMATION = "offline_no_server_confirmation"
    OWNERSHIP_NOT_CONFIRMED = "ownership_not_confirmed"
    NON_OFFICIAL_REF = "non_official_ref"


#: The degradation finding code emitted when a provider cannot back ref
#: protection (In-Scope #6, AC9). WARNING severity: a spiegel-pflichtiger
#: handling requirement, never a silent pass (CLAUDE.md SEVERITY-SEMANTIK).
REF_PROTECTION_DEGRADATION_CODE = "ref_protection_capability_unavailable"


@dataclass(frozen=True)
class RepoPushVerificationInput:
    """One repo's two-stage barrier input (Edge report + server ref-read).

    Attributes:
        repo_id: The participating repo this input is for.
        edge_reported_pushed: Whether the Edge ``push_status_report`` reported a
            successful push (``push_outcome == "pushed"``). ``False`` for a
            ``behind_remote`` backlog OR a missing report.
        edge_report_present: Whether an Edge sync-point report exists at all for
            this repo/barrier. ``False`` fails closed (AC1b: no Edge report ->
            block, even when the server ref-read would pass).
        edge_reported_head_sha: The head SHA the Edge ``branch_ref_report``
            carried (``None`` when absent -- fails closed).
        server_ref_resolved: Whether the server ``ls-remote`` ref-read resolved
            the story branch to exactly one head SHA (AG3-146 ``ref_read``).
        server_head_sha: The server-resolved head SHA (``None`` when
            unresolved).
    """

    repo_id: str
    edge_report_present: bool
    edge_reported_pushed: bool
    edge_reported_head_sha: str | None
    server_ref_resolved: bool
    server_head_sha: str | None


@dataclass(frozen=True)
class RepoPushVerdict:
    """The per-repo two-stage verification verdict."""

    repo_id: str
    verified: bool
    block_code: PushBarrierBlockCode | None
    detail: str


@dataclass(frozen=True)
class BarrierVerdict:
    """The aggregated barrier verdict across all participating repos (AC3)."""

    barrier_type: SyncPointBarrierType
    passed: bool
    repo_verdicts: tuple[RepoPushVerdict, ...]

    @property
    def blocking_repos(self) -> tuple[str, ...]:
        """The repos whose un-verified push blocks this barrier."""
        return tuple(v.repo_id for v in self.repo_verdicts if not v.verified)

    def blocking_summary(self) -> str:
        """A deterministic, human-readable summary of the blocking repos."""
        return "; ".join(
            f"{v.repo_id}: {v.block_code.value if v.block_code else 'blocked'} "
            f"({v.detail})"
            for v in self.repo_verdicts
            if not v.verified
        )


def evaluate_repo_push(inp: RepoPushVerificationInput) -> RepoPushVerdict:
    """Decide whether ONE repo is verified-pushed (Edge report AND server read).

    Both stages are mandatory (FK-91 §91.1b: the Edge report alone is never
    sufficient). The verdict is verified iff: an Edge push report exists AND it
    reported ``pushed`` AND carried a head SHA AND the server ref-read resolved
    AND the server head SHA equals the Edge-reported head SHA.

    Args:
        inp: The repo's two-stage verification input.

    Returns:
        A named :class:`RepoPushVerdict` (fail-closed on any missing stage).
    """
    if not inp.edge_report_present:
        return _repo_block(
            inp, PushBarrierBlockCode.NO_EDGE_PUSH_REPORT,
            "no Edge push report for this repo at the barrier (fail-closed; the "
            "server ref-read alone never satisfies the barrier)",
        )
    if not inp.edge_reported_pushed:
        return _repo_block(
            inp, PushBarrierBlockCode.EDGE_REPORTS_BACKLOG,
            "the Edge reported a push backlog (behind_remote), not a push",
        )
    if inp.edge_reported_head_sha is None:
        return _repo_block(
            inp, PushBarrierBlockCode.MISSING_EDGE_HEAD_SHA,
            "the Edge push report carried no branch head SHA",
        )
    if not inp.server_ref_resolved or inp.server_head_sha is None:
        return _repo_block(
            inp, PushBarrierBlockCode.SERVER_REF_UNRESOLVED,
            "the server ls-remote ref-read did not resolve the story branch "
            "(remote unreachable or ref absent)",
        )
    if inp.server_head_sha != inp.edge_reported_head_sha:
        return _repo_block(
            inp, PushBarrierBlockCode.SERVER_HEAD_MISMATCH,
            f"the server head SHA {inp.server_head_sha} does not confirm the "
            f"Edge-reported head SHA {inp.edge_reported_head_sha}",
        )
    return RepoPushVerdict(
        repo_id=inp.repo_id,
        verified=True,
        block_code=None,
        detail=f"push verified: edge and server agree on head {inp.server_head_sha}",
    )


def _repo_block(
    inp: RepoPushVerificationInput,
    code: PushBarrierBlockCode,
    detail: str,
) -> RepoPushVerdict:
    """Build a fail-closed, named per-repo block verdict."""
    return RepoPushVerdict(
        repo_id=inp.repo_id, verified=False, block_code=code, detail=detail
    )


def evaluate_push_barrier(
    barrier_type: SyncPointBarrierType,
    inputs: Sequence[RepoPushVerificationInput],
) -> BarrierVerdict:
    """Aggregate the two-stage verification across all participating repos.

    Fail-closed hard AND (AC3): the barrier passes iff EVERY participating repo
    is verified-pushed. An empty input set is a fail-closed block (no repo could
    be confirmed), never an optimistic pass.

    Args:
        barrier_type: Which of the four sync-point barriers is evaluated.
        inputs: One verification input per participating repo.

    Returns:
        The aggregated :class:`BarrierVerdict`.
    """
    if not inputs:
        empty = RepoPushVerdict(
            repo_id="",
            verified=False,
            block_code=PushBarrierBlockCode.NO_PARTICIPATING_REPOS,
            detail="no participating repos supplied to the push barrier",
        )
        return BarrierVerdict(barrier_type, passed=False, repo_verdicts=(empty,))
    verdicts = tuple(evaluate_repo_push(inp) for inp in inputs)
    passed = all(v.verified for v in verdicts)
    return BarrierVerdict(barrier_type, passed=passed, repo_verdicts=verdicts)


@dataclass(frozen=True)
class MergePrecondition:
    """The reusable "pushed in all repos, server-verified" checkpoint (AC12)."""

    satisfied: bool
    blocking_repos: tuple[str, ...]
    detail: str


def verify_pushed_across_repos(
    inputs: Sequence[RepoPushVerificationInput],
) -> MergePrecondition:
    """SOLL-190 merge precondition: story branch pushed+verified in every repo.

    Shares the exact two-stage engine as the closure-entry barrier so the merge
    precondition and the barrier can never diverge (SINGLE SOURCE OF TRUTH).
    AG3-152 consumes this before productive ``merge_local`` (In-Scope #9).

    Args:
        inputs: One verification input per participating repo.

    Returns:
        A :class:`MergePrecondition` (fail-closed on any un-verified repo).
    """
    verdict = evaluate_push_barrier(SyncPointBarrierType.CLOSURE_ENTRY, inputs)
    return MergePrecondition(
        satisfied=verdict.passed,
        blocking_repos=verdict.blocking_repos,
        detail=(
            "all participating repos server-verified as pushed"
            if verdict.passed
            else f"unverified repos: {verdict.blocking_summary()}"
        ),
    )


@dataclass(frozen=True)
class PushFreshnessRecord:
    """Persisted push-freshness / backlog projection per ``(story, run, repo)``.

    The DATABASE row for the read model (In-Scope #3, AC5). Freshness/silence is
    INFORMATION only -- consumers (AG3-148/AG3-153) never derive an ownership
    transition from it (no automatic silence -> transfer).

    Attributes:
        project_key: The project scope.
        story_id: The story scope.
        run_id: The authoritative run scope.
        repo_id: The participating repo.
        last_reported_head_sha: The most recent Edge-reported branch head SHA
            (``None`` when no branch head was ever reported).
        last_pushed_head_sha: The most recent head SHA confirmed as pushed
            (``None`` until a first successful push).
        last_reported_at: The instant of the most recent sync-point report.
        backlog: Whether an unresolved push backlog exists for this repo.
        backlog_detail: A human-readable backlog hint (``None`` when no backlog).
    """

    project_key: str
    story_id: str
    run_id: str
    repo_id: str
    last_reported_head_sha: str | None
    last_pushed_head_sha: str | None
    last_reported_at: datetime
    backlog: bool
    backlog_detail: str | None


def project_push_freshness(
    previous: PushFreshnessRecord | None,
    *,
    project_key: str,
    story_id: str,
    run_id: str,
    repo_id: str,
    reported_head_sha: str | None,
    push_outcome: PushOutcome,
    reported_at: datetime,
) -> PushFreshnessRecord:
    """Compute the next push-freshness record from a sync-point report (pure).

    A ``pushed`` outcome clears the backlog and advances the pushed head SHA; a
    ``behind_remote`` outcome raises a visible backlog (In-Scope #2/#3, AC4)
    while preserving the last known pushed head SHA. This is a pure state
    transition; persistence is the caller's (Postgres-only) job.

    Args:
        previous: The prior record for this repo, or ``None`` on first report.
        project_key: The project scope.
        story_id: The story scope.
        run_id: The authoritative run scope.
        repo_id: The participating repo.
        reported_head_sha: The branch head SHA the Edge reported (may be
            ``None``).
        push_outcome: ``pushed`` or ``behind_remote``.
        reported_at: The instant of this report.

    Returns:
        The next :class:`PushFreshnessRecord`.
    """
    pushed = push_outcome == "pushed"
    prior_pushed_sha = previous.last_pushed_head_sha if previous else None
    return PushFreshnessRecord(
        project_key=project_key,
        story_id=story_id,
        run_id=run_id,
        repo_id=repo_id,
        last_reported_head_sha=reported_head_sha,
        last_pushed_head_sha=reported_head_sha if pushed else prior_pushed_sha,
        last_reported_at=reported_at,
        backlog=not pushed,
        backlog_detail=(
            None
            if pushed
            else (
                "opportunistic push behind remote; local work continues, "
                "completion stays fail-closed blocked until pushed"
            )
        ),
    )


@dataclass(frozen=True)
class StoryRefWriteAuthorization:
    """The ``story/*`` write-release verdict (FK-12 §12.1.3, AC7/AC8)."""

    granted: bool
    refusal_code: StoryRefWriteRefusalCode | None
    detail: str


def authorize_story_ref_write(
    *,
    active_owner_session_id: str | None,
    active_ownership_epoch: int | None,
    requesting_session_id: str,
    requesting_ownership_epoch: int,
) -> StoryRefWriteAuthorization:
    """Release ``story/*`` write capability only for the current owner (In-Scope #5).

    AK3 grants the write only for the story's active
    ``(owner_session, ownership_epoch)`` -- an ex-owner (transferred session or
    a stale epoch) is refused (AC7b). The credential MECHANIC lives in the
    provider adapter (AG3-146); this is the pure release predicate.

    Args:
        active_owner_session_id: The active ``run_ownership_records`` session id
            (``None`` when no active ownership exists).
        active_ownership_epoch: The active ownership epoch (``None`` when none).
        requesting_session_id: The session requesting the write.
        requesting_ownership_epoch: The epoch the requester presents.

    Returns:
        A named :class:`StoryRefWriteAuthorization` (fail-closed refusal).
    """
    if active_owner_session_id is None or active_ownership_epoch is None:
        return _write_refusal(
            StoryRefWriteRefusalCode.NO_ACTIVE_OWNERSHIP,
            "no active run ownership; no session may write story/* refs",
        )
    if requesting_session_id != active_owner_session_id:
        return _write_refusal(
            StoryRefWriteRefusalCode.OWNERSHIP_TRANSFERRED,
            f"session {requesting_session_id!r} is not the active owner "
            f"{active_owner_session_id!r} (ownership transferred)",
        )
    if requesting_ownership_epoch != active_ownership_epoch:
        return _write_refusal(
            StoryRefWriteRefusalCode.STALE_OWNERSHIP_EPOCH,
            f"epoch {requesting_ownership_epoch} is stale; the active epoch is "
            f"{active_ownership_epoch}",
        )
    return StoryRefWriteAuthorization(
        granted=True,
        refusal_code=None,
        detail=(
            f"write released for active owner {active_owner_session_id!r} "
            f"epoch {active_ownership_epoch}"
        ),
    )


def _write_refusal(
    code: StoryRefWriteRefusalCode, detail: str
) -> StoryRefWriteAuthorization:
    """Build a fail-closed, named write-release refusal."""
    return StoryRefWriteAuthorization(granted=False, refusal_code=code, detail=detail)


@dataclass(frozen=True)
class RefProtectionDegradationFinding:
    """A deterministic ref-protection degradation WARNING (In-Scope #6, AC9)."""

    finding_code: str
    severity: Literal["warning"]
    detail: str
    provider_label: str


def assess_ref_protection_capability(
    *, capability_supported: bool, provider_label: str
) -> RefProtectionDegradationFinding | None:
    """Assess a provider's ref-protection capability (In-Scope #6, AC9).

    A provider that cannot back ``ref_protection_administration`` produces a
    deterministic WARNING finding (a spiegel-pflichtiger handling requirement,
    never a silent pass -- CLAUDE.md SEVERITY-SEMANTIK). The Edge push gate
    stays the mandatory, provider-independent base regardless.

    Args:
        capability_supported: Whether the provider adapter reports the
            ``ref_protection_administration`` capability as wired/usable.
        provider_label: A human-readable provider label for the finding.

    Returns:
        ``None`` when the capability is backed; a WARNING finding otherwise.
    """
    if capability_supported:
        return None
    return RefProtectionDegradationFinding(
        finding_code=REF_PROTECTION_DEGRADATION_CODE,
        severity="warning",
        detail=(
            f"provider {provider_label!r} cannot administer story/* ref "
            "protection; the Edge push gate remains the mandatory base, but "
            "direct developer pushes are not provider-blocked -- escalate "
            "(WARNING, no silent degradation)"
        ),
        provider_label=provider_label,
    )


def official_story_ref(story_id: str) -> str:
    """Return the ONLY sanctioned push target ref for a story (In-Scope #7)."""
    return f"{STORY_REF_PREFIX}{story_id}"


def is_official_story_ref(ref: str, *, story_id: str) -> bool:
    """Whether ``ref`` is exactly the official ``story/{story_id}`` target.

    Accepts either the short ``story/{id}`` or the fully-qualified
    ``refs/heads/story/{id}`` form; every other ref (a WIP ref, another
    branch) is rejected (AC10 -- no WIP-ref push path).
    """
    target = official_story_ref(story_id)
    return ref in {target, f"refs/heads/{target}"}


@dataclass(frozen=True)
class PushGateDecision:
    """The online-pflichtig Edge-push-gate decision (FK-15 §15.5.4, AC6)."""

    allowed: bool
    refusal_code: PushGateRefusalCode | None
    detail: str


def decide_push_gate(
    *,
    server_reachable: bool,
    server_confirms_ownership: bool,
    target_ref: str,
    story_id: str,
) -> PushGateDecision:
    """Decide the official Edge push gate (online-pflichtig, bounded, no fallback).

    The gate is the single sanctioned push mechanic for ``story/*`` (FK-55
    §55.9). It verifies ownership online IMMEDIATELY before the push; without a
    reachable server there is no push (AC6 offline). It deliberately takes NO
    "ACTIVE bundle" input: a stale ACTIVE bundle can never grant a push -- the
    FK-56 §56.9a re-sync fallback does not apply to the push path (FK-15
    §15.5.4). The non-official-ref guard enforces the WIP-ref discard (AC10).

    Args:
        server_reachable: Whether the online ownership check reached the server
            within its bound (``False`` == offline).
        server_confirms_ownership: Whether the server confirmed the pushing
            session as the current owner.
        target_ref: The ref the push targets.
        story_id: The story being pushed (official-ref cross-check).

    Returns:
        A named :class:`PushGateDecision` (fail-closed refusal).
    """
    if not is_official_story_ref(target_ref, story_id=story_id):
        return _gate_refusal(
            PushGateRefusalCode.NON_OFFICIAL_REF,
            f"push target {target_ref!r} is not the official ref "
            f"{official_story_ref(story_id)!r}; no WIP-ref push path exists",
        )
    if not server_reachable:
        return _gate_refusal(
            PushGateRefusalCode.OFFLINE_NO_SERVER_CONFIRMATION,
            "the online ownership check could not reach the server; offline "
            "means local work yes, push no (no ACTIVE-bundle re-sync fallback "
            "for the push path)",
        )
    if not server_confirms_ownership:
        return _gate_refusal(
            PushGateRefusalCode.OWNERSHIP_NOT_CONFIRMED,
            "the server did not confirm the pushing session as current owner; "
            "the ex-owner fails at the gate (first of the double lock)",
        )
    return PushGateDecision(
        allowed=True,
        refusal_code=None,
        detail=f"push gate open for {official_story_ref(story_id)!r}",
    )


def _gate_refusal(code: PushGateRefusalCode, detail: str) -> PushGateDecision:
    """Build a fail-closed, named push-gate refusal."""
    return PushGateDecision(allowed=False, refusal_code=code, detail=detail)
