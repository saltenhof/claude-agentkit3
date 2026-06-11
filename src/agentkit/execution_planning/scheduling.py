"""``evaluate_scheduling`` top-surface + the single deterministic selector (AG3-100).

This module owns the FK-70 §70.8 ``evaluate_scheduling`` mandatory-call top-surface
that the ``PipelineEngine`` admission path (FK-20 §20.8.2) MUST consult before any
story start, and the FK-70 §70.8a Execution-Input top-surface with its **one**
deterministic triage selector (§70.8a.3) that both HTTP surface variants
(``snapshot`` / ``next``) derive from. A second selector implementation is
explicitly inadmissible (§70.8a, FIX-THE-MODEL / SINGLE SOURCE OF TRUTH).

Responsibility split (consumption / enforcement layer):

* It does NOT redefine the planning domain model -- it CONSUMES the AG3-098
  domain types (``ExecutionFeasibility``/``ExecutionSchedulingPolicy``/
  ``HumanGate``/``ExternalGate``/``ExecutionWave``) and the pure ``derive_plan``
  derivation (FK-70 §70.6).
* It does NOT rebuild persistence/revision -- idempotency (#8) is a pure-function
  property (same typed input -> same output), revision-bound where AG3-099 supplies
  a revision token.
* It enforces the §70.11 invariants that are derivable here: #1 (no FLIGHT before a
  DONE hard predecessor), #2 (BLOCKED not heuristically overridden), #3 (feasibility
  vs. scheduling kept separate), #4 (tenant-scoped -- single project_key), #6 (E2E /
  collective gates), #7 (soft dependency is priority-only), #9 (cycle/deadlock
  quarantine + fail-closed escalation), #10 (optional Human-Review is NOT a blocker).

The functions here are pure; the HTTP routes and the control-plane admission reader
wire the real repositories around them.
"""

from __future__ import annotations

from enum import StrEnum
from typing import TYPE_CHECKING

from pydantic import BaseModel, ConfigDict, Field

from agentkit.execution_planning.entities import (
    ExecutionFeasibility,
    ExecutionSchedulingPolicy,
    ExecutionWave,
)
from agentkit.execution_planning.readiness import derive_plan

if TYPE_CHECKING:
    from collections.abc import Sequence

    from agentkit.execution_planning.dependency_graph import DependencyGraph
    from agentkit.execution_planning.entities import (
        BlockingCondition,
        ExecutionCapacityBudgets,
        ExternalGate,
        HumanGate,
        PlanDerivation,
        SchedulingHint,
        StoryRefForPlanning,
    )

__all__ = [
    "EvaluateSchedulingResult",
    "ExecutionInputNext",
    "ExecutionInputNextReason",
    "ExecutionInputSnapshot",
    "ExecutionInputStackCard",
    "ExecutionInputStoryRef",
    "RepoSlotInfo",
    "SchedulingDecisionKind",
    "SchedulingTriageReason",
    "WhyNotNow",
    "evaluate_scheduling",
    "next_from_snapshot",
    "select_execution_input",
]

#: Lifecycle statuses (lower-cased) that count a story as already running (FLIGHT).
_RUNNING_STATUSES = frozenset({"in progress", "in_progress", "flight", "running"})


class SchedulingDecisionKind(StrEnum):
    """Per-story scheduling decision from ``evaluate_scheduling`` (§70.8)."""

    READY = "ready"
    BLOCKED = "blocked"
    DEFER = "defer"


class WhyNotNow(BaseModel):
    """Typed, machine-readable reason a story is not startable right now (§70.8)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    story_id: str
    decision: SchedulingDecisionKind
    reason_code: str
    detail: str | None = None


class ExecutionInputStoryRef(BaseModel):
    """A ``story_summary``-style story reference inside a stack card (FK-70 §70.8a.1).

    Wire-bound to ``frontend-contracts.entity.story_summary`` as the reference shape
    the deterministic selector owns: the story identity plus the display-relevant
    triage fields (number, title, repo). It is a compact reference, never the full
    Inspector story detail.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    story_id: str
    story_number: int = Field(ge=1)
    title: str
    repo: str | None = None


class ExecutionInputStackCard(BaseModel):
    """One predecessor/story/successor stack card (FK-70 §70.8a.1).

    Wire-bound to ``frontend-contracts.entity.execution_input_stack``: exactly the
    three formal refs ``story`` (required) plus optional ``predecessor`` /
    ``successor``, each an :class:`ExecutionInputStoryRef` (a ``story_summary``-style
    reference, never story detail). The flat-field prototype shape is inadmissible —
    the formal entity is the authoritative wire contract.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    story: ExecutionInputStoryRef
    predecessor: ExecutionInputStoryRef | None = None
    successor: ExecutionInputStoryRef | None = None


class RepoSlotInfo(BaseModel):
    """Remaining slots for one repo, used by the deterministic selector (§70.8a.3)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    repo: str
    repo_slots_left: int = Field(ge=0)


class SchedulingTriageReason(BaseModel):
    """Machine-readable triage reason for one picked card (FK-70 §70.8a.2/.3)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    repo_bucket: str
    on_critical_path: bool
    global_slots_left: int = Field(ge=0)
    repo_slots: tuple[RepoSlotInfo, ...] = Field(default_factory=tuple)
    active_tiebreaker: str


class ExecutionInputNextReason(BaseModel):
    """Formal ``next``-reason entity introduced by AG3-100 (FK-70 §70.8a.2).

    Wire-bound to ``frontend-contracts.entity.execution_input_next``. Carries the
    machine-readable triage justification for the single next card: repo bucket,
    critical-path flag, remaining slots per relevant cap, active tiebreaker.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    repo_bucket: str
    on_critical_path: bool
    global_slots_left: int = Field(ge=0)
    repo_slots: tuple[RepoSlotInfo, ...] = Field(default_factory=tuple)
    active_tiebreaker: str


class ExecutionInputSnapshot(BaseModel):
    """UI snapshot surface payload (FK-70 §70.8a.1).

    Wire-bound to ``frontend-contracts.entity.execution_input_snapshot``. The whole
    triage pick result: ``running`` (already delegated), ``eligible_ready`` (the
    triage-filtered delegable subset), ``total_ready`` (theoretically ready before
    triage), ``global_slots_left``. Empty lists are a valid 200 answer (not a 404).
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    project_key: str
    running: tuple[ExecutionInputStackCard, ...] = Field(default_factory=tuple)
    eligible_ready: tuple[ExecutionInputStackCard, ...] = Field(default_factory=tuple)
    total_ready: int = Field(ge=0)
    global_slots_left: int = Field(ge=0)


class ExecutionInputNext(BaseModel):
    """Agent-pull surface payload (FK-70 §70.8a.2).

    Exactly one next story (or ``None``) plus its triage reason. The first card of
    the same single-selector pick that feeds the snapshot.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    project_key: str
    story: ExecutionInputStackCard | None = None
    reason: ExecutionInputNextReason | None = None


class EvaluateSchedulingResult(BaseModel):
    """FK-70 §70.8 ``evaluate_scheduling`` top-surface result.

    Carries the seven normative result fields plus the typed quarantine/escalation
    surface for invariant #9. ``recommended_batch``/``max_allowed_batch`` and
    ``critical_path`` come from the pure plan derivation (FK-70 §70.6).
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    project_key: str
    ready_candidates: tuple[str, ...] = Field(default_factory=tuple)
    blocked_stories: tuple[str, ...] = Field(default_factory=tuple)
    recommended_batch: int = Field(ge=0)
    max_allowed_batch: int = Field(ge=0)
    critical_path: tuple[str, ...] = Field(default_factory=tuple)
    next_wave: ExecutionWave
    why_not_now: tuple[WhyNotNow, ...] = Field(default_factory=tuple)
    #: Invariant #9: story ids in a quarantined (cyclic/deadlocked) subgraph.
    quarantined_story_ids: tuple[str, ...] = Field(default_factory=tuple)
    #: Invariant #9: fail-closed escalation flag (a quarantine was raised).
    escalated: bool = False
    feasibility: ExecutionFeasibility
    scheduling_policy: ExecutionSchedulingPolicy

    def is_ready(self, story_id: str) -> bool:
        """Return whether a story is a READY scheduling candidate (admission gate)."""

        return story_id in self.ready_candidates


def evaluate_scheduling(
    *,
    project_key: str,
    stories: Sequence[StoryRefForPlanning],
    dependency_graph: DependencyGraph,
    budgets: ExecutionCapacityBudgets,
    completed_story_ids: set[str] | None = None,
    human_gates: Sequence[HumanGate] = (),
    external_gates: Sequence[ExternalGate] = (),
    blocking_conditions: Sequence[BlockingCondition] = (),
    scheduling_hint: SchedulingHint | None = None,
) -> EvaluateSchedulingResult:
    """Evaluate dependencies, readiness and scheduling policy (FK-70 §70.8).

    The single ``PipelineEngine``/admission top-surface (FK-20 §20.8.2): it derives
    feasibility (hard graph + gate rules) and scheduling policy (budgets) SEPARATELY
    (#3), enforces the §70.11 invariants derivable here, and returns the seven
    normative result fields. A story only becomes a ``ready_candidate`` when it is
    feasible AND not in a quarantined subgraph -- the engine starts a story ONLY for
    a READY candidate, never by reaching into the backlog itself.

    Args:
        project_key: Tenant/project scope (single tenant -- #4).
        stories: Planning story read models for the project.
        dependency_graph: The project's dependency graph.
        budgets: The scheduling capacity budgets (caps).
        completed_story_ids: Explicitly completed ids; derived from statuses when
            omitted. A FLIGHT predecessor that is not yet completed keeps a successor
            out of READY (#1).
        human_gates: First-class human gates. Only a BLOCKING open gate holds a story
            back; an optional review never blocks (#10).
        external_gates: First-class external gates (open -> BLOCKED_EXTERNAL).
        blocking_conditions: Pre-derived typed blockers (e.g. conflict/contract).
        scheduling_hint: Optional rulebook hint that may only narrow the batch (#7).

    Returns:
        The ``EvaluateSchedulingResult`` (ready/blocked/defer).
    """
    project_stories = [story for story in stories if story.project_key == project_key]
    resolved_completed = (
        completed_story_ids
        if completed_story_ids is not None
        else _completed_from_statuses(project_stories)
    )

    quarantined, escalated = _quarantine_cyclic_subgraph(dependency_graph)

    plan = derive_plan(
        graph=dependency_graph,
        completed_story_ids=resolved_completed,
        all_stories=project_stories,
        project_key=project_key,
        budgets=budgets,
        scheduling_hint=scheduling_hint,
        human_gates=human_gates,
        external_gates=external_gates,
        blocking_conditions=blocking_conditions,
    )

    ready_candidates = tuple(
        story.story_id
        for story in plan.ready_set
        if story.story_id not in quarantined
    )
    quarantined_ready = tuple(
        story.story_id
        for story in plan.ready_set
        if story.story_id in quarantined
    )
    blocked_stories = tuple(
        sorted(
            {story.story_id for story in plan.blocked_set} | set(quarantined_ready),
        ),
    )
    why_not_now = _why_not_now(plan, quarantined)

    return EvaluateSchedulingResult(
        project_key=project_key,
        ready_candidates=ready_candidates,
        blocked_stories=blocked_stories,
        recommended_batch=plan.recommended_batch,
        max_allowed_batch=plan.max_allowed_batch,
        critical_path=plan.critical_path,
        next_wave=plan.execution_wave,
        why_not_now=why_not_now,
        quarantined_story_ids=quarantined,
        escalated=escalated,
        feasibility=plan.feasibility,
        scheduling_policy=plan.scheduling_policy,
    )


def select_execution_input(
    *,
    project_key: str,
    stories: Sequence[StoryRefForPlanning],
    evaluation: EvaluateSchedulingResult,
    budgets: ExecutionCapacityBudgets,
) -> ExecutionInputSnapshot:
    """The ONE deterministic triage selector (FK-70 §70.8a.3).

    Both surface variants (``snapshot`` / ``next``) derive from this single
    function -- a second selector is inadmissible (§70.8a). Triage:

    1. ``global_slots_left = min(merge_risk_cap, llm_pool_cap, ci_capacity_cap,
       api_rate_limit_cap, repo_parallel_cap) - len(running)``, lower-bounded 0.
    2. ``repo_slots_left = repo_parallel_cap - running_in_repo - already_picked``.
    3. Per repo: bucket sorted by ``critical_path`` desc, then story number asc.
    4. Round-robin over repos (repos alphabetical for determinism) until
       ``global_slots_left`` is exhausted or no repo has cards/slots.

    Args:
        project_key: Tenant/project scope.
        stories: Planning story read models for the project.
        evaluation: The ``evaluate_scheduling`` result (ready candidates + critical
            path) -- the selector NEVER re-derives readiness, keeping one truth.
        budgets: The capacity budgets (caps).

    Returns:
        The whole pick result as an ``ExecutionInputSnapshot``.
    """
    stories_by_id = {
        story.story_id: story
        for story in stories
        if story.project_key == project_key
    }
    running_ids = sorted(
        story_id
        for story_id, story in stories_by_id.items()
        if story.lifecycle_status.lower() in _RUNNING_STATUSES
    )
    running_in_repo: dict[str, int] = {}
    for story_id in running_ids:
        repo = _repo_of(stories_by_id[story_id])
        running_in_repo[repo] = running_in_repo.get(repo, 0) + 1

    ready_ids = [
        story_id
        for story_id in evaluation.ready_candidates
        if story_id in stories_by_id and story_id not in running_ids
    ]
    total_ready = len(ready_ids)

    global_cap = _global_cap(budgets)
    global_slots_left = max(0, global_cap - len(running_ids))

    on_critical_path = set(evaluation.critical_path)
    buckets = _repo_buckets(ready_ids, stories_by_id, on_critical_path)
    picked = _round_robin_pick(
        buckets=buckets,
        global_slots_left=global_slots_left,
        repo_parallel_cap=budgets.repo_parallel_cap,
        running_in_repo=running_in_repo,
    )

    running_cards = tuple(
        _stack_card(stories_by_id[story_id]) for story_id in running_ids
    )
    eligible_cards = tuple(
        _stack_card(stories_by_id[story_id]) for story_id in picked
    )
    return ExecutionInputSnapshot(
        project_key=project_key,
        running=running_cards,
        eligible_ready=eligible_cards,
        total_ready=total_ready,
        global_slots_left=global_slots_left,
    )


def next_from_snapshot(
    *,
    project_key: str,
    stories: Sequence[StoryRefForPlanning],
    evaluation: EvaluateSchedulingResult,
    budgets: ExecutionCapacityBudgets,
) -> ExecutionInputNext:
    """Derive the agent-pull ``next`` answer from the SAME single selector.

    Returns exactly the first card of the snapshot pick (or ``None``) plus the
    machine-readable triage reason for that card. Idempotent: same input -> same
    answer (no internal state). Builds NO second selector (§70.8a).
    """
    snapshot = select_execution_input(
        project_key=project_key,
        stories=stories,
        evaluation=evaluation,
        budgets=budgets,
    )
    if not snapshot.eligible_ready:
        return ExecutionInputNext(project_key=project_key, story=None, reason=None)
    first = snapshot.eligible_ready[0]
    repo = first.story.repo or _NO_REPO
    running_in_repo = sum(
        1 for card in snapshot.running if (card.story.repo or _NO_REPO) == repo
    )
    repo_slots_left = max(0, budgets.repo_parallel_cap - running_in_repo - 1)
    reason = ExecutionInputNextReason(
        repo_bucket=repo,
        on_critical_path=first.story.story_id in set(evaluation.critical_path),
        global_slots_left=snapshot.global_slots_left,
        repo_slots=(RepoSlotInfo(repo=repo, repo_slots_left=repo_slots_left),),
        active_tiebreaker=_TIEBREAKER,
    )
    return ExecutionInputNext(project_key=project_key, story=first, reason=reason)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

_NO_REPO = "(no-repo)"
_TIEBREAKER = "critical_path_desc_then_story_number_asc"


def _global_cap(budgets: ExecutionCapacityBudgets) -> int:
    """Global slot cap per FK-70 §70.8a.3 -- the central caps WITHOUT the repo cap.

    The repo-parallel cap is a PER-REPO bound applied in the round-robin (#3 step 2),
    not part of the global ``min`` (§70.8a.3 step 1). Keeping it out of the global cap
    is what makes the per-repo bound a distinct, effective constraint.
    """
    return min(
        budgets.merge_risk_cap,
        budgets.api_rate_limit_cap,
        budgets.llm_pool_cap,
        budgets.ci_capacity_cap,
    )


def _completed_from_statuses(stories: Sequence[StoryRefForPlanning]) -> set[str]:
    from agentkit.execution_planning.readiness import completed_story_ids_from_statuses

    return completed_story_ids_from_statuses(stories)


def _quarantine_cyclic_subgraph(graph: DependencyGraph) -> tuple[tuple[str, ...], bool]:
    """Quarantine the cyclic subgraph fail-closed (#9).

    When a cycle/deadlock is detected, EVERY story on the cycle AND every story that
    transitively depends on a cycle node is quarantined (it can never become DONE),
    and the result is flagged ``escalated`` -- rather than silently letting the whole
    backlog run on. Returns the sorted quarantined ids and the escalation flag.
    """
    has_cycle, path = graph.has_cycle()
    if not has_cycle:
        return (), False
    quarantined: set[str] = set(path)
    for node in list(quarantined):
        quarantined |= graph.transitive_successors(node)
    return tuple(sorted(quarantined)), True


def _why_not_now(
    plan: PlanDerivation,
    quarantined: tuple[str, ...],
) -> tuple[WhyNotNow, ...]:
    """Build the typed ``why_not_now`` list for blocked + quarantined stories."""
    quarantined_set = set(quarantined)
    reasons: list[WhyNotNow] = []
    for wave_story in plan.blocked_set:
        if wave_story.story_id in quarantined_set:
            continue
        reasons.append(
            WhyNotNow(
                story_id=wave_story.story_id,
                decision=SchedulingDecisionKind.BLOCKED,
                reason_code=(
                    wave_story.blocked_by[0].reason_code
                    if wave_story.blocked_by
                    else "blocked"
                ),
                detail=(
                    wave_story.blocked_by[0].kind.value
                    if wave_story.blocked_by
                    else None
                ),
            )
        )
    reasons.extend(
        WhyNotNow(
            story_id=story_id,
            decision=SchedulingDecisionKind.BLOCKED,
            reason_code="quarantined_cycle",
            detail="cycle/deadlock quarantine (FK-70 §70.11 #9)",
        )
        for story_id in quarantined
    )
    return tuple(sorted(reasons, key=lambda reason: reason.story_id))


def _repo_of(story: StoryRefForPlanning) -> str:
    return story.repo or _NO_REPO


def _repo_buckets(
    ready_ids: Sequence[str],
    stories_by_id: dict[str, StoryRefForPlanning],
    on_critical_path: set[str],
) -> dict[str, list[str]]:
    """Group ready ids per repo, each bucket sorted critical-path desc then number asc."""
    buckets: dict[str, list[str]] = {}
    for story_id in ready_ids:
        repo = _repo_of(stories_by_id[story_id])
        buckets.setdefault(repo, []).append(story_id)
    for repo_ids in buckets.values():
        repo_ids.sort(
            key=lambda story_id: (
                0 if story_id in on_critical_path else 1,
                stories_by_id[story_id].story_number,
                story_id,
            ),
        )
    return buckets


def _round_robin_pick(
    *,
    buckets: dict[str, list[str]],
    global_slots_left: int,
    repo_parallel_cap: int,
    running_in_repo: dict[str, int],
) -> list[str]:
    """Round-robin over alphabetically sorted repos until global slots exhausted."""
    repo_order = sorted(buckets)
    cursors = {repo: 0 for repo in repo_order}
    picked_in_repo: dict[str, int] = {repo: 0 for repo in repo_order}
    picked: list[str] = []
    remaining_global = global_slots_left
    while remaining_global > 0:
        progressed = False
        for repo in repo_order:
            if remaining_global <= 0:
                break
            repo_slots_left = (
                repo_parallel_cap
                - running_in_repo.get(repo, 0)
                - picked_in_repo[repo]
            )
            if repo_slots_left <= 0:
                continue
            if cursors[repo] >= len(buckets[repo]):
                continue
            picked.append(buckets[repo][cursors[repo]])
            cursors[repo] += 1
            picked_in_repo[repo] += 1
            remaining_global -= 1
            progressed = True
        if not progressed:
            break
    return picked


def _story_ref(story: StoryRefForPlanning) -> ExecutionInputStoryRef:
    return ExecutionInputStoryRef(
        story_id=story.story_id,
        story_number=story.story_number,
        title=story.title,
        repo=story.repo,
    )


def _stack_card(story: StoryRefForPlanning) -> ExecutionInputStackCard:
    # FK-70 §70.8a.1 / frontend-contracts.entity.execution_input_stack: the card is
    # the three nested story refs. ``predecessor`` / ``successor`` stay optional and
    # are absent here (the deterministic selector exposes the story card; the
    # predecessor/successor stack overlay is the Read-layer's enrichment, §70.8a.5).
    return ExecutionInputStackCard(story=_story_ref(story))
