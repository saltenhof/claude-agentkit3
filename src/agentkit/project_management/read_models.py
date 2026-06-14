"""Standalone project-scoped read-model builders for AG3-091.

Provides the backing logic for the six standalone endpoints:
  - GET .../execution-input/limits          -> ExecutionLimits
  - GET .../mode-lock                        -> ProjectModeLock
  - GET .../stories/counters                 -> StoryCounters
  - GET .../stories/{id}/flow                -> StoryFlowSnapshot
  - GET .../coverage/stories/{id}/acceptance -> StoryCoverageAcceptance
  - GET .../coverage/stories/{id}/are-evidence -> StoryAreEvidence

FIX-THE-MODEL: mode-lock and counters REUSE derive_mode_lock /
compute_story_counters (SSOT in service.py). No second computation.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from agentkit.execution_planning.readiness import derive_budgets
from agentkit.project_management._flow_constants import (
    CLOSURE_PROGRESS_TO_SUBSTEP,
    DONE_STATUS,
    LOOP_GROUPS,
    NO_PROGRESS_STATUSES,
    OPTIONAL_SUBSTEPS,
    PHASE_ORDER,
    PHASE_STATUS_TO_FLOW,
    SUBSTEP_SEQUENCE_FAST,
    SUBSTEP_SEQUENCE_STANDARD,
)
from agentkit.project_management.service import (
    compute_story_counters,
    derive_mode_lock,
)
from agentkit.project_management.views import (
    ExecutionLimits,
    ProjectModeLock,
    StoryAreEvidence,
    StoryAreLinkView,
    StoryCounters,
    StoryCoverageAcceptance,
    StoryFlowPhase,
    StoryFlowSnapshot,
    StoryFlowSubstep,
)

if TYPE_CHECKING:
    from agentkit.execution_planning.entities import ParallelizationConfig
    from agentkit.requirements_coverage.contract import AreEvidence, CoverageVerdict
    from agentkit.requirements_coverage.models import StoryAreLink
    from agentkit.story_context_manager.story_model import Story


# ---------------------------------------------------------------------------
# Backward-compat aliases (tests import these private names from this module)
# ---------------------------------------------------------------------------

_SUBSTEP_SEQUENCE_STANDARD = SUBSTEP_SEQUENCE_STANDARD
_SUBSTEP_SEQUENCE_FAST = SUBSTEP_SEQUENCE_FAST

# ---------------------------------------------------------------------------
# Execution limits
# ---------------------------------------------------------------------------

_ZERO_CAPS: dict[str, int] = {
    "repo_parallel_cap": 0,
    "merge_risk_cap": 0,
    "max_parallel_agent_cap": 0,
    "llm_pool_cap": 0,
    "ci_capacity_cap": 0,
}


def build_execution_limits(
    project_key: str,
    config: ParallelizationConfig | None,
) -> ExecutionLimits:
    """Project active caps as the execution_limits read-model (FK-70 §70.6.2).

    Zero indicates a cap that blocks all work.  When no config is present,
    the project has not yet been configured — all caps default to zero.

    Uses the canonical ``derive_budgets`` derivation (SSOT, FK-70 §70.6.2).
    The internal ``ExecutionCapacityBudgets`` field ``api_rate_limit_cap``
    maps to the wire field ``max_parallel_agent_cap`` (formal spec name).

    Args:
        project_key: Project key echoed into the wire model.
        config: Active parallelization config, or ``None`` when absent.

    Returns:
        The :class:`ExecutionLimits` wire model.
    """
    if config is None:
        return ExecutionLimits(project_key=project_key, **_ZERO_CAPS)
    # derive_budgets is the canonical five-cap fan-out (SSOT in execution_planning).
    budgets = derive_budgets(config)
    return ExecutionLimits(
        project_key=project_key,
        repo_parallel_cap=budgets.repo_parallel_cap,
        merge_risk_cap=budgets.merge_risk_cap,
        # Internal name: api_rate_limit_cap; formal wire name: max_parallel_agent_cap
        max_parallel_agent_cap=budgets.api_rate_limit_cap,
        llm_pool_cap=budgets.llm_pool_cap,
        ci_capacity_cap=budgets.ci_capacity_cap,
    )


# ---------------------------------------------------------------------------
# Mode-lock (reuses SSOT)
# ---------------------------------------------------------------------------


def build_mode_lock(project_key: str, stories: list[Story]) -> ProjectModeLock:
    """Derive the mode-lock read-model by reusing ``derive_mode_lock`` (SSOT).

    FK-24 §24.3.3 / ``invariant.mode_lock_derived``.  No second computation.

    Args:
        project_key: Project key.
        stories: All project stories.

    Returns:
        The :class:`ProjectModeLock` wire model.
    """
    return derive_mode_lock(project_key, stories)


# ---------------------------------------------------------------------------
# Story counters (reuses SSOT)
# ---------------------------------------------------------------------------


def build_story_counters(project_key: str, stories: list[Story]) -> StoryCounters:
    """Compute story counters by reusing ``compute_story_counters`` (SSOT).

    No second computation.

    Args:
        project_key: Project key.
        stories: All project stories.

    Returns:
        The :class:`StoryCounters` wire model.
    """
    return compute_story_counters(project_key, stories)


# ---------------------------------------------------------------------------
# Story flow snapshot (FK-39 phase-state projection)
# ---------------------------------------------------------------------------

# PhaseState is a runtime type; import only for type annotations.
# We use object here and access attributes defensively to keep
# the read-model layer free of runtime pipeline-engine imports.


def build_story_flow_snapshot(
    story_id: str,
    *,
    story_status: str,
    is_fast_mode: bool,
    current_phase_state: object | None,
) -> StoryFlowSnapshot:
    """Project story status + current runtime phase into the story_flow_snapshot read-model.

    Implements the canonical position-derivation algorithm (selectStoryFlow in
    storySelectors.ts, FK-39):

    - Fast-mode: exploration renders as ``skipped`` without substeps (FK-24 §24.3.3).
    - If story.status == Done -> ALL phases ``done`` (full substeps, all done).
    - If story.status in {Backlog, Approved, Cancelled, ...} OR no runtime phase ->
      ALL phases ``pending`` (full substeps, all pending).
    - Otherwise compare each phase's index to the current runtime-phase index:
      - phaseIndex < currentIndex -> ``done`` (full substeps done)
      - phaseIndex > currentIndex -> ``pending`` (full substeps pending)
      - phaseIndex == currentIndex -> active phase: state from PhaseState status,
        substep states derived from current runtime substep progress.

    No multi-phase persistence is required: completed prior phases are inferred
    from their position relative to the single current-runtime-phase state.

    Args:
        story_id: Story identifier.
        story_status: Wire-level story status string (e.g. ``"Done"``, ``"In Progress"``).
        is_fast_mode: Whether the story runs in fast mode.
        current_phase_state: The single current :class:`PhaseState` from
            ``load_phase_state_global``, or ``None`` when the story has not started.
            Typed as ``object`` to avoid a runtime import of the pipeline-engine module.

    Returns:
        The :class:`StoryFlowSnapshot` wire model.
    """
    mode: str = "fast" if is_fast_mode else "standard"
    sequence = SUBSTEP_SEQUENCE_FAST if is_fast_mode else SUBSTEP_SEQUENCE_STANDARD

    all_done = story_status == DONE_STATUS
    no_progress = story_status in NO_PROGRESS_STATUSES or current_phase_state is None

    if all_done or no_progress:
        substep_state = "done" if all_done else "pending"
        return _build_uniform_snapshot(story_id, mode, is_fast_mode, substep_state, sequence)

    # Active story — position-based derivation.
    current_phase_name = str(
        getattr(getattr(current_phase_state, "phase", None), "value", "")
        or getattr(current_phase_state, "phase", "")
    )
    current_index = (
        PHASE_ORDER.index(current_phase_name)
        if current_phase_name in PHASE_ORDER
        else -1
    )

    phases = []
    for phase_name in PHASE_ORDER:
        phases.append(
            _resolve_phase_flow_state(
                phase_name, current_index, current_phase_state, sequence, is_fast_mode
            )
        )

    return StoryFlowSnapshot(story_id=story_id, mode=mode, phases=phases)


def _build_uniform_snapshot(
    story_id: str,
    mode: str,
    is_fast_mode: bool,
    substep_state: str,
    sequence: dict[str, tuple[str, ...]],
) -> StoryFlowSnapshot:
    """Build a snapshot where all non-skipped phases share the same substep state."""
    phases = [
        _build_phase_all(phase_name, substep_state, sequence)
        for phase_name in PHASE_ORDER
        if not (phase_name == "exploration" and is_fast_mode)
    ]
    if is_fast_mode:
        phases.insert(
            PHASE_ORDER.index("exploration"),
            StoryFlowPhase(phase="exploration", state="skipped", substeps=[]),
        )
    return StoryFlowSnapshot(story_id=story_id, mode=mode, phases=phases)


def _resolve_phase_flow_state(
    phase_name: str,
    current_index: int,
    current_phase_state: object,
    sequence: dict[str, tuple[str, ...]],
    is_fast_mode: bool,
) -> StoryFlowPhase:
    """Resolve the flow state for a single phase during active story execution.

    Args:
        phase_name: The name of the phase to resolve.
        current_index: Index of the currently active phase in PHASE_ORDER (-1 if unknown).
        current_phase_state: The live PhaseState object.
        sequence: Substep sequence mapping (standard or fast).
        is_fast_mode: Whether the story runs in fast mode.

    Returns:
        The resolved :class:`StoryFlowPhase`.
    """
    if phase_name == "exploration" and is_fast_mode:
        return StoryFlowPhase(phase="exploration", state="skipped", substeps=[])
    phase_index = PHASE_ORDER.index(phase_name)
    if current_index == -1 or phase_index > current_index:
        return _build_phase_all(phase_name, "pending", sequence)
    if phase_index < current_index:
        return _build_phase_all(phase_name, "done", sequence)
    # Active phase: derive state and per-substep progress from current runtime.
    return _build_active_phase(phase_name, current_phase_state, sequence)


def _build_phase_all(
    phase_name: str,
    substep_state: str,
    sequence: dict[str, tuple[str, ...]],
) -> StoryFlowPhase:
    """Build a phase where all substeps share the same state (done or pending)."""
    substeps = _build_substeps_uniform(sequence.get(phase_name, ()), substep_state)
    return StoryFlowPhase(
        phase=phase_name,
        state=substep_state,
        substeps=substeps,
    )


def _build_substeps_uniform(
    substep_ids: tuple[str, ...],
    state: str,
) -> list[StoryFlowSubstep]:
    """Build the full annotated substep list with a uniform state."""
    annotated = _annotate_loop_positions(substep_ids)
    result = []
    for substep_id, loop_position, loop_size, loop_group in annotated:
        is_optional = substep_id in OPTIONAL_SUBSTEPS
        effective_state = state
        if is_optional and state == "pending":
            effective_state = "optional-pending"
        result.append(
            StoryFlowSubstep(
                substep=substep_id,
                state=effective_state,
                optional=is_optional,
                loop_group=loop_group,
                loop_position=loop_position,
                loop_size=loop_size,
            )
        )
    return result


def _annotate_loop_positions(
    substep_ids: tuple[str, ...],
) -> list[tuple[str, int | None, int | None, str | None]]:
    """Annotate substeps with loop-position metadata.

    Ports ``annotateLoopPositions`` from storySelectors.ts.  Returns a list
    of ``(substep_id, loop_position, loop_size, loop_group)`` tuples.
    ``loop_position`` and ``loop_size`` are ``None`` for non-loop substeps.
    """
    result: list[tuple[str, int | None, int | None, str | None]] = [
        (s, None, None, None) for s in substep_ids
    ]
    region_start = -1
    region_group: str | None = None

    def flush_region(end_exclusive: int) -> None:
        nonlocal region_start, region_group
        if region_start == -1 or region_group is None:
            return
        size = end_exclusive - region_start
        for i in range(region_start, end_exclusive):
            substep_id, _, _, _ = result[i]
            result[i] = (substep_id, i - region_start + 1, size, region_group)
        region_start = -1
        region_group = None

    for index, substep_id in enumerate(substep_ids):
        group = LOOP_GROUPS.get(substep_id)
        if group != region_group:
            flush_region(index)
            if group:
                region_start = index
                region_group = group
    flush_region(len(substep_ids))
    return result


def _build_active_phase(
    phase_name: str,
    phase_state: object,
    sequence: dict[str, tuple[str, ...]],
) -> StoryFlowPhase:
    """Build the active phase with per-substep progress from the current PhaseState.

    Substep progress is derived EXCLUSIVELY from the real durable FK-39 payload
    fields.  No invented per-substep pointer fields are read:

    - ``setup``: ``SetupPayload`` has no per-substep pointer; all substeps render
      as ``pending`` (the phase-level state stays ``active``).
    - ``exploration``: ``ExplorationPayload.gate_status`` (ExplorationGateStatus)
      — ``approved`` -> all substeps ``done``, ``rejected`` -> all ``failed``,
      ``pending`` -> all ``pending``.
    - ``implementation``: ``ImplementationPayload.qa_cycle_round`` (int, >= 0)
      is the QA-loop iteration count; surfaced as ``iteration`` on the phase.
      No reliable per-substep pointer exists -> all substeps render as ``pending``.
    - ``closure``: ``ClosurePayload.progress`` (ClosureProgress) boolean
      checkpoints drive per-substep state (done vs. pending).

    The FK-39 model has NO ``substep`` / ``current_substep`` / ``iteration``
    field on any payload model.  Reading such invented fields is forbidden.
    """
    raw_status = getattr(getattr(phase_state, "status", None), "value", "pending")
    flow_state = PHASE_STATUS_TO_FLOW.get(str(raw_status), "pending")

    substep_ids = sequence.get(phase_name, ())
    annotated = _annotate_loop_positions(substep_ids)

    payload = getattr(phase_state, "payload", None)

    # Derive per-substep states from REAL payload fields only.
    substep_states = _derive_substep_states(phase_name, substep_ids, payload)

    substeps: list[StoryFlowSubstep] = []
    for (substep_id, loop_position, loop_size, loop_group), sub_state in zip(
        annotated, substep_states, strict=True
    ):
        substeps.append(
            StoryFlowSubstep(
                substep=substep_id,
                state=sub_state,
                optional=substep_id in OPTIONAL_SUBSTEPS,
                loop_group=loop_group,
                loop_position=loop_position,
                loop_size=loop_size,
            )
        )

    # QA-loop iteration from implementation payload (real field: qa_cycle_round).
    iteration: int | None = None
    iteration_loop_group: str | None = None
    if phase_name == "implementation" and payload is not None:
        qa_round = getattr(payload, "qa_cycle_round", None)
        if qa_round is not None and int(qa_round) > 0:
            iteration = int(qa_round)
            iteration_loop_group = "remediation"

    return StoryFlowPhase(
        phase=phase_name,
        state=flow_state,
        state_reason=_escalation_reason(phase_state),
        iteration=iteration,
        iteration_loop_group=iteration_loop_group,
        substeps=substeps,
    )


def _derive_substep_states(
    phase_name: str,
    substep_ids: tuple[str, ...],
    payload: object | None,
) -> list[str]:
    """Derive substep state strings from real FK-39 payload fields.

    Returns one state string per substep_id, in the same order.
    Only real durable FK-39 payload fields are accessed; no invented fields.
    Dispatches to per-phase helpers to keep cognitive complexity low.

    Args:
        phase_name: The current phase name.
        substep_ids: Ordered tuple of canonical substep identifiers.
        payload: The phase-specific payload, or ``None``.

    Returns:
        A list of state strings aligned with ``substep_ids``.
    """
    if phase_name == "exploration":
        return _derive_exploration_substeps(substep_ids, payload)
    if phase_name == "closure":
        return _derive_closure_substeps(substep_ids, payload)
    # setup, implementation, or no payload: no per-substep durable signal.
    return _derive_default_substeps(substep_ids)


def _derive_exploration_substeps(
    substep_ids: tuple[str, ...],
    payload: object | None,
) -> list[str]:
    """Derive substep states for the exploration phase from gate_status.

    Args:
        substep_ids: Ordered tuple of canonical substep identifiers.
        payload: The ExplorationPayload, or ``None``.

    Returns:
        A list of state strings aligned with ``substep_ids``.
    """
    if payload is None:
        return _derive_default_substeps(substep_ids)
    gate_raw = getattr(payload, "gate_status", None)
    gate_value = str(getattr(gate_raw, "value", gate_raw) or "pending")
    if gate_value == "approved":
        return [
            "optional-pending" if s in OPTIONAL_SUBSTEPS else "done"
            for s in substep_ids
        ]
    if gate_value == "rejected":
        return [
            "optional-pending" if s in OPTIONAL_SUBSTEPS else "failed"
            for s in substep_ids
        ]
    # pending or unknown
    return _derive_default_substeps(substep_ids)


def _derive_closure_substeps(
    substep_ids: tuple[str, ...],
    payload: object | None,
) -> list[str]:
    """Derive substep states for the closure phase from ClosureProgress checkpoints.

    Args:
        substep_ids: Ordered tuple of canonical substep identifiers.
        payload: The ClosurePayload, or ``None``.

    Returns:
        A list of state strings aligned with ``substep_ids``.
    """
    if payload is None:
        return _derive_default_substeps(substep_ids)
    progress = getattr(payload, "progress", None)
    if progress is None:
        return _derive_default_substeps(substep_ids)
    done_substeps: set[str] = set()
    for field_name, substep_id in CLOSURE_PROGRESS_TO_SUBSTEP:
        if getattr(progress, field_name, False):
            done_substeps.add(substep_id)
    return [
        "done" if s in done_substeps else (
            "optional-pending" if s in OPTIONAL_SUBSTEPS else "pending"
        )
        for s in substep_ids
    ]


def _derive_default_substeps(substep_ids: tuple[str, ...]) -> list[str]:
    """Derive default substep states (pending / optional-pending) for phases with no durable signal.

    Used by setup, implementation, and any phase without a payload.

    Args:
        substep_ids: Ordered tuple of canonical substep identifiers.

    Returns:
        A list of state strings aligned with ``substep_ids``.
    """
    return [
        "optional-pending" if s in OPTIONAL_SUBSTEPS else "pending"
        for s in substep_ids
    ]


def _escalation_reason(phase_state: object) -> str | None:
    """Extract escalation reason from the PhaseState (FK-39 durable field).

    Reads from ``phase_state.escalation_reason`` — the real FK-39 field on
    :class:`PhaseState` — not from the payload (which has no such field).
    """
    reason = getattr(phase_state, "escalation_reason", None)
    if reason is not None:
        return str(getattr(reason, "value", reason))
    return None


# ---------------------------------------------------------------------------
# Coverage read-models (FK-40 §40.5b.6, read-only from StoryAreLink)
# ---------------------------------------------------------------------------


def build_coverage_acceptance(
    story_id: str,
    project_key: str,
    links: list[StoryAreLink],
    acceptance_criteria: list[str],
) -> StoryCoverageAcceptance:
    """Build the Soll-coverage read-model from StoryAreLink + story spec.

    Source is EXCLUSIVELY StoryAreLink + story spec (FK-40 §40.5b.6).
    No mutation, no second coverage truth.

    Args:
        story_id: Story identifier.
        project_key: Project key.
        links: All StoryAreLink edges for this story.
        acceptance_criteria: Acceptance criteria strings from the story spec.

    Returns:
        The :class:`StoryCoverageAcceptance` wire model.
    """
    linked = sorted({link.are_item_id for link in links})
    return StoryCoverageAcceptance(
        story_id=story_id,
        project_key=project_key,
        acceptance_criteria=acceptance_criteria,
        linked_requirements=linked,
    )


class AreVerdictRequiredError(ValueError):
    """Raised when non-empty links are provided without a coverage verdict.

    FAIL-CLOSED: ``build_are_evidence`` must never produce ``"linked"``
    coverage status for non-empty requirements without a live ARE verdict.
    The route layer is responsible for obtaining the verdict before calling
    this builder; when ARE is unavailable it must return 503, not call this
    builder with ``coverage_verdict=None`` and non-empty links.

    This error is a defense-in-depth guard against the route accidentally
    bypassing the 503 path and reaching the builder with missing coverage data.
    """


def build_are_evidence(
    story_id: str,
    project_key: str,
    links: list[StoryAreLink],
    coverage_verdict: CoverageVerdict | None = None,
    evidence_items: list[AreEvidence] | None = None,
) -> StoryAreEvidence:
    """Build the Ist-coverage read-model from StoryAreLink + ARE live-status (FK-40 §40.5b.6).

    Source is EXCLUSIVELY StoryAreLink + ARE live-status/coverage verdict +
    ARE evidence refs.  No mutation, no second coverage truth.

    FAIL-CLOSED: when ``links`` is non-empty, ``coverage_verdict`` MUST be
    provided.  Calling this builder with non-empty links and no verdict is
    a programming error — the caller (route layer) must obtain the ARE verdict
    or return 503 before reaching this builder.  Raises
    :class:`AreVerdictRequiredError` when this contract is violated so the
    error is visible at construction time, not silently papered over with a
    fabricated ``"linked"`` status.

    When ``links`` is empty, ``coverage_verdict`` is not needed (trivially
    no requirements to classify), and an empty :class:`StoryAreEvidence`
    is returned.

    When ``evidence_items`` is provided (from ``AreClient.list_evidence``), the
    ``evidence_paths`` field of each :class:`StoryAreLinkView` is populated with
    the concrete evidence references (test locators, commit SHAs, artifact paths)
    for that requirement (FK-40 §40.5b.6 / story §2.1.2).

    Args:
        story_id: Story identifier.
        project_key: Project key.
        links: All StoryAreLink edges for this story.
        coverage_verdict: Result from ``AreClient.check_gate``.  Required when
            ``links`` is non-empty; omitted only when ``links`` is empty.
        evidence_items: Optional list of ``AreEvidence`` from
            ``AreClient.list_evidence``.  When provided, ``evidence_paths``
            is populated per requirement.

    Returns:
        The :class:`StoryAreEvidence` wire model.

    Raises:
        AreVerdictRequiredError: When ``links`` is non-empty and
            ``coverage_verdict`` is ``None``.
    """
    if links and coverage_verdict is None:
        raise AreVerdictRequiredError(
            "coverage_verdict is required when links is non-empty; "
            "the route must obtain a verdict from AreClient or return 503 "
            "before calling build_are_evidence with linked requirements."
        )

    uncovered_ids: frozenset[str] = frozenset()
    if coverage_verdict is not None:
        uncovered_ids = frozenset(
            req.requirement_id for req in coverage_verdict.uncovered_requirements
        )

    # Build per-requirement evidence-path index from AreEvidence items.
    evidence_by_req: dict[str, list[str]] = {}
    if evidence_items:
        for ev in evidence_items:
            evidence_by_req.setdefault(ev.requirement_id, []).append(ev.evidence_ref)

    link_views = [
        StoryAreLinkView(
            are_item_id=link.are_item_id,
            kind=link.kind.value,
            coverage_status=(
                "uncovered" if link.are_item_id in uncovered_ids else "covered"
            ),
            evidence_paths=evidence_by_req.get(link.are_item_id, []),
        )
        for link in sorted(links, key=lambda lnk: lnk.are_item_id)
    ]
    return StoryAreEvidence(
        story_id=story_id,
        project_key=project_key,
        linked_requirements=link_views,
    )
