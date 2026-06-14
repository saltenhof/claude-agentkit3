"""Unit tests for the AG3-091 read-model builder functions.

Tests cover:
  - build_execution_limits: zero caps on None config, correct mapping from config
  - build_mode_lock: delegates to SSOT derive_mode_lock (AC2 SSOT-guard)
  - build_story_counters: delegates to SSOT compute_story_counters
  - build_story_flow_snapshot: position-based derivation (R3 — AG3-091):
      * Backlog/Approved/no runtime -> all pending with full substeps
      * Done -> all phases done with full substeps
      * Active story + current phase -> prior phases done, later phases pending,
        current phase active (substeps from REAL FK-39 payload fields only;
        no invented substep-pointer field)
      * Fast-mode -> exploration skipped without substeps, other phases use fast sequence
  - Real FK-39 PhaseState payload derivation:
      * ImplementationPayload.qa_cycle_round -> iteration field on active phase
      * ClosurePayload.progress -> done/pending per-substep states
      * ExplorationPayload.gate_status -> approved/rejected/pending substep states
  - build_coverage_acceptance: deduplicates and sorts linked ARE items
  - build_are_evidence: FAIL-CLOSED — requires verdict for non-empty links
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from agentkit.execution_planning.entities import ParallelizationConfig
from agentkit.project_management.read_models import (
    _SUBSTEP_SEQUENCE_FAST,
    _SUBSTEP_SEQUENCE_STANDARD,
    AreVerdictRequiredError,
    build_are_evidence,
    build_coverage_acceptance,
    build_execution_limits,
    build_mode_lock,
    build_story_flow_snapshot,
)
from agentkit.project_management.views import (
    ExecutionLimits,
    StoryAreEvidence,
    StoryCoverageAcceptance,
    StoryFlowSnapshot,
)
from agentkit.requirements_coverage.models import StoryAreLink, StoryAreLinkKind

# ---------------------------------------------------------------------------
# build_execution_limits
# ---------------------------------------------------------------------------


def test_execution_limits_no_config_returns_all_zeros() -> None:
    result = build_execution_limits("my-project", None)
    assert isinstance(result, ExecutionLimits)
    assert result.project_key == "my-project"
    assert result.repo_parallel_cap == 0
    assert result.merge_risk_cap == 0
    assert result.max_parallel_agent_cap == 0
    assert result.llm_pool_cap == 0
    assert result.ci_capacity_cap == 0


def test_execution_limits_with_global_cap_only() -> None:
    config = ParallelizationConfig(
        project_key="proj-a",
        max_parallel_stories=3,
        max_parallel_stories_per_repo=None,
    )
    result = build_execution_limits("proj-a", config)
    assert result.project_key == "proj-a"
    # repo_parallel_cap falls back to max_parallel_stories when per_repo is None
    assert result.repo_parallel_cap == 3
    assert result.merge_risk_cap == 3
    assert result.max_parallel_agent_cap == 3
    assert result.llm_pool_cap == 3
    assert result.ci_capacity_cap == 3


def test_execution_limits_with_per_repo_cap_overrides_global_for_repo() -> None:
    config = ParallelizationConfig(
        project_key="proj-b",
        max_parallel_stories=5,
        max_parallel_stories_per_repo=2,
    )
    result = build_execution_limits("proj-b", config)
    assert result.repo_parallel_cap == 2
    # global caps come from max_parallel_stories
    assert result.merge_risk_cap == 5
    assert result.max_parallel_agent_cap == 5


def test_execution_limits_is_frozen() -> None:
    from pydantic import ValidationError

    result = build_execution_limits("proj-c", None)
    with pytest.raises(ValidationError):
        result.repo_parallel_cap = 99  # type: ignore[misc]


# ---------------------------------------------------------------------------
# build_story_flow_snapshot — position-based derivation (AG3-091 R3)
# ---------------------------------------------------------------------------

# Helper: build a PhaseState mock with a given phase name and status.
# NOTE: No per-substep pointer field exists on any real FK-39 payload model.
# Do NOT add `substep`, `current_substep`, or `iteration` here — they are
# invented fields forbidden by ERROR 1 fix.  Per-substep states come from
# real payload objects (ImplementationPayload.qa_cycle_round, etc.).
def _phase_state_mock(phase: str, status: str) -> object:
    ps = MagicMock()
    ps.phase.value = phase
    ps.status.value = status
    ps.payload = None
    ps.escalation_reason = None
    return ps


def test_flow_snapshot_backlog_story_all_phases_pending_with_substeps() -> None:
    """Backlog status + no runtime -> all phases pending, full substep sequences."""
    result = build_story_flow_snapshot(
        "AG3-001",
        story_status="Backlog",
        is_fast_mode=False,
        current_phase_state=None,
    )
    assert isinstance(result, StoryFlowSnapshot)
    assert result.story_id == "AG3-001"
    assert result.mode == "standard"
    assert len(result.phases) == 4
    phase_names = [p.phase for p in result.phases]
    assert phase_names == ["setup", "exploration", "implementation", "closure"]
    for phase in result.phases:
        assert phase.state == "pending"
        # Full substep sequences populated (not empty).
        expected_substeps = list(_SUBSTEP_SEQUENCE_STANDARD[phase.phase])
        actual_substep_ids = [s.substep for s in phase.substeps]
        assert actual_substep_ids == expected_substeps, (
            f"Phase {phase.phase!r}: expected substeps {expected_substeps}, "
            f"got {actual_substep_ids}"
        )


def test_flow_snapshot_approved_story_all_phases_pending() -> None:
    """Approved status -> all phases pending (not started yet)."""
    result = build_story_flow_snapshot(
        "AG3-001b",
        story_status="Approved",
        is_fast_mode=False,
        current_phase_state=None,
    )
    for phase in result.phases:
        assert phase.state == "pending"
        assert len(phase.substeps) > 0, f"Phase {phase.phase!r} must have substeps"


def test_flow_snapshot_done_story_all_phases_done_with_substeps() -> None:
    """Done status -> all phases done, full substep sequences all done."""
    result = build_story_flow_snapshot(
        "AG3-002",
        story_status="Done",
        is_fast_mode=False,
        current_phase_state=None,
    )
    assert len(result.phases) == 4
    for phase in result.phases:
        assert phase.state == "done", f"Phase {phase.phase!r} must be done"
        expected_substeps = list(_SUBSTEP_SEQUENCE_STANDARD[phase.phase])
        actual_substep_ids = [s.substep for s in phase.substeps]
        assert actual_substep_ids == expected_substeps
        for substep in phase.substeps:
            assert substep.state == "done", (
                f"Substep {substep.substep!r} in phase {phase.phase!r} must be done"
            )


def test_flow_snapshot_active_story_implementation_position_derivation() -> None:
    """Active story with current phase=implementation: setup/exploration done, closure pending.

    This is the core position-derivation test: phases BEFORE current index are done,
    phases AFTER are pending, current phase is active.

    Per ERROR 1 fix: no per-substep pointer field exists in FK-39 ImplementationPayload.
    All implementation substeps render as pending (the phase-level state is active).
    """
    ps = _phase_state_mock("implementation", "in_progress")
    result = build_story_flow_snapshot(
        "AG3-003",
        story_status="In Progress",
        is_fast_mode=False,
        current_phase_state=ps,
    )
    phases = {p.phase: p for p in result.phases}

    # Prior phases: done with full substep sequences.
    assert phases["setup"].state == "done"
    assert [s.substep for s in phases["setup"].substeps] == list(
        _SUBSTEP_SEQUENCE_STANDARD["setup"]
    )
    assert all(s.state == "done" for s in phases["setup"].substeps)

    assert phases["exploration"].state == "done"
    assert [s.substep for s in phases["exploration"].substeps] == list(
        _SUBSTEP_SEQUENCE_STANDARD["exploration"]
    )
    assert all(s.state == "done" for s in phases["exploration"].substeps)

    # Active phase: phase-level "active", substeps pending (no per-substep pointer).
    assert phases["implementation"].state == "active"
    impl_substeps = {s.substep: s for s in phases["implementation"].substeps}
    # No per-substep pointer -> all substeps are pending or optional-pending.
    for substep in phases["implementation"].substeps:
        assert substep.state in ("pending", "optional-pending"), (
            f"Substep {substep.substep!r}: expected pending/optional-pending "
            f"(no FK-39 substep pointer), got {substep.state!r}"
        )
    # Canonical substep sequence intact.
    assert list(impl_substeps.keys()) == list(_SUBSTEP_SEQUENCE_STANDARD["implementation"])

    # Later phase: pending with full substep sequences.
    assert phases["closure"].state == "pending"
    assert [s.substep for s in phases["closure"].substeps] == list(
        _SUBSTEP_SEQUENCE_STANDARD["closure"]
    )


def test_flow_snapshot_active_story_setup_phase() -> None:
    """Active story with current phase=setup: all later phases pending, no prior done."""
    ps = _phase_state_mock("setup", "in_progress")
    result = build_story_flow_snapshot(
        "AG3-004",
        story_status="In Progress",
        is_fast_mode=False,
        current_phase_state=ps,
    )
    phases = {p.phase: p for p in result.phases}
    # setup is active
    assert phases["setup"].state == "active"
    # exploration, implementation, closure are all pending
    assert phases["exploration"].state == "pending"
    assert phases["implementation"].state == "pending"
    assert phases["closure"].state == "pending"


def test_flow_snapshot_active_story_closure_phase() -> None:
    """Active story with current phase=closure: all prior phases done."""
    ps = _phase_state_mock("closure", "in_progress")
    result = build_story_flow_snapshot(
        "AG3-005",
        story_status="In Progress",
        is_fast_mode=False,
        current_phase_state=ps,
    )
    phases = {p.phase: p for p in result.phases}
    assert phases["setup"].state == "done"
    assert phases["exploration"].state == "done"
    assert phases["implementation"].state == "done"
    assert phases["closure"].state == "active"


def test_flow_snapshot_fast_mode_exploration_skipped_without_substeps() -> None:
    """Fast-mode: exploration renders as skipped without substeps (FK-24 §24.3.3)."""
    result = build_story_flow_snapshot(
        "AG3-006",
        story_status="Backlog",
        is_fast_mode=True,
        current_phase_state=None,
    )
    assert result.mode == "fast"
    exploration_phase = next(p for p in result.phases if p.phase == "exploration")
    assert exploration_phase.state == "skipped"
    assert exploration_phase.substeps == []


def test_flow_snapshot_fast_mode_active_implementation_uses_fast_sequence() -> None:
    """Fast-mode active story: implementation uses fast substep sequence (shorter).

    Per ERROR 1 fix: no per-substep pointer in ImplementationPayload.
    All implementation substeps render as pending; the phase state is active.
    """
    ps = _phase_state_mock("implementation", "in_progress")
    result = build_story_flow_snapshot(
        "AG3-007",
        story_status="In Progress",
        is_fast_mode=True,
        current_phase_state=ps,
    )
    phases = {p.phase: p for p in result.phases}
    # Exploration is skipped in fast mode
    assert phases["exploration"].state == "skipped"
    assert phases["exploration"].substeps == []
    # Setup is done (prior to implementation)
    assert phases["setup"].state == "done"
    assert [s.substep for s in phases["setup"].substeps] == list(
        _SUBSTEP_SEQUENCE_FAST["setup"]
    )
    # Implementation is active with fast substep sequence
    impl_substeps = [s.substep for s in phases["implementation"].substeps]
    assert impl_substeps == list(_SUBSTEP_SEQUENCE_FAST["implementation"])
    # qa_layer2_llm is OUT in fast mode -> not present
    assert "qa_layer2_llm" not in impl_substeps
    # No per-substep pointer -> all substeps pending or optional-pending
    for substep in phases["implementation"].substeps:
        assert substep.state in ("pending", "optional-pending"), (
            f"Substep {substep.substep!r}: expected pending/optional-pending "
            f"(no FK-39 substep pointer), got {substep.state!r}"
        )


def test_flow_snapshot_fast_mode_done_story_exploration_still_skipped() -> None:
    """Fast-mode Done story: exploration remains skipped (no substeps), rest done."""
    result = build_story_flow_snapshot(
        "AG3-008",
        story_status="Done",
        is_fast_mode=True,
        current_phase_state=None,
    )
    phases = {p.phase: p for p in result.phases}
    assert phases["exploration"].state == "skipped"
    assert phases["exploration"].substeps == []
    assert phases["setup"].state == "done"
    assert phases["implementation"].state == "done"
    assert phases["closure"].state == "done"


def test_flow_snapshot_active_setup_phase_substeps_all_pending() -> None:
    """Active setup phase: no per-substep pointer in SetupPayload -> all substeps pending.

    ERROR 1 fix: the old test read invented ``substep`` field and asserted
    before/after substep states.  After the fix, SetupPayload has no substep
    pointer; all substeps render as pending when the phase is active.
    """
    ps = _phase_state_mock("setup", "in_progress")
    result = build_story_flow_snapshot(
        "AG3-009",
        story_status="In Progress",
        is_fast_mode=False,
        current_phase_state=ps,
    )
    setup_phase = next(p for p in result.phases if p.phase == "setup")
    assert setup_phase.state == "active"
    # All substeps pending — no durable substep pointer in SetupPayload.
    for substep in setup_phase.substeps:
        assert substep.state in ("pending", "optional-pending"), (
            f"Setup substep {substep.substep!r}: expected pending (no FK-39 pointer), "
            f"got {substep.state!r}"
        )
    # Full canonical substep sequence populated.
    ids = [s.substep for s in setup_phase.substeps]
    assert ids == list(_SUBSTEP_SEQUENCE_STANDARD["setup"])


def test_flow_snapshot_escalation_reason_in_state_reason() -> None:
    """Escalation reason from PhaseState.escalation_reason is surfaced in state_reason.

    ERROR 1 fix: reads from the REAL FK-39 field ``phase_state.escalation_reason``
    (EscalationReason enum on PhaseState), NOT from the invented
    ``phase_state.payload.escalation_reason``.
    """
    phase_state = MagicMock()
    phase_state.phase.value = "implementation"
    phase_state.status.value = "escalated"
    phase_state.payload = None
    # Set the REAL FK-39 field: PhaseState.escalation_reason (EscalationReason enum).
    # Simulate the StrEnum .value attribute returning the string.
    phase_state.escalation_reason.value = "max_rounds_exceeded"
    result = build_story_flow_snapshot(
        "AG3-010",
        story_status="In Progress",
        is_fast_mode=False,
        current_phase_state=phase_state,
    )
    impl_phase = next(p for p in result.phases if p.phase == "implementation")
    assert impl_phase.state == "escalated"
    assert impl_phase.state_reason == "max_rounds_exceeded"


def test_flow_snapshot_implementation_qa_cycle_round_sets_iteration() -> None:
    """Real ImplementationPayload.qa_cycle_round drives iteration on active impl phase.

    ERROR 1 fix: iteration comes ONLY from the real FK-39 field qa_cycle_round,
    not from any invented 'iteration' attribute.
    """
    from tests.phase_state_factory import make_phase_state

    from agentkit.pipeline_engine.phase_executor.models import (
        ImplementationPayload,
        PhaseStatus,
        QaCycleStatus,
    )

    phase_state = make_phase_state(
        phase="implementation",
        status=PhaseStatus.IN_PROGRESS,
        payload=ImplementationPayload(
            qa_cycle_round=3,
            qa_cycle_status=QaCycleStatus.AWAITING_QA,
            qa_cycle_id="abc123def012",
        ),
    )
    result = build_story_flow_snapshot(
        "AG3-091-impl",
        story_status="In Progress",
        is_fast_mode=False,
        current_phase_state=phase_state,
    )
    impl_phase = next(p for p in result.phases if p.phase == "implementation")
    assert impl_phase.state == "active"
    # qa_cycle_round=3 must be surfaced as iteration=3 on the phase.
    assert impl_phase.iteration == 3, (
        f"Expected iteration=3 from qa_cycle_round, got {impl_phase.iteration!r}"
    )
    assert impl_phase.iteration_loop_group == "remediation"
    # All substeps pending (no per-substep pointer in ImplementationPayload).
    for substep in impl_phase.substeps:
        assert substep.state in ("pending", "optional-pending"), (
            f"Substep {substep.substep!r}: expected pending, got {substep.state!r}"
        )


def test_flow_snapshot_implementation_no_qa_cycle_no_iteration() -> None:
    """ImplementationPayload with qa_cycle_round=0 produces no iteration on the phase."""
    from tests.phase_state_factory import make_phase_state

    from agentkit.pipeline_engine.phase_executor.models import (
        ImplementationPayload,
        PhaseStatus,
    )

    phase_state = make_phase_state(
        phase="implementation",
        status=PhaseStatus.IN_PROGRESS,
        payload=ImplementationPayload(qa_cycle_round=0),
    )
    result = build_story_flow_snapshot(
        "AG3-091-impl-0",
        story_status="In Progress",
        is_fast_mode=False,
        current_phase_state=phase_state,
    )
    impl_phase = next(p for p in result.phases if p.phase == "implementation")
    assert impl_phase.state == "active"
    # qa_cycle_round=0 means no QA loop started yet -> no iteration.
    assert impl_phase.iteration is None


def test_flow_snapshot_closure_progress_drives_substep_states() -> None:
    """Real ClosurePayload.progress boolean checkpoints drive closure substep states.

    ERROR 1 fix: closure substep states come ONLY from the real FK-39 durable
    ClosureProgress booleans, not from any invented substep pointer.
    """
    from tests.phase_state_factory import make_phase_state

    from agentkit.pipeline_engine.phase_executor.models import (
        ClosurePayload,
        ClosureProgress,
        PhaseStatus,
    )

    # integrity_gate done, branch_push done -> merge and beyond still pending.
    phase_state = make_phase_state(
        phase="closure",
        status=PhaseStatus.IN_PROGRESS,
        payload=ClosurePayload(
            progress=ClosureProgress(
                integrity_passed=True,
                story_branch_pushed=True,
            )
        ),
    )
    result = build_story_flow_snapshot(
        "AG3-091-closure",
        story_status="In Progress",
        is_fast_mode=False,
        current_phase_state=phase_state,
    )
    closure_phase = next(p for p in result.phases if p.phase == "closure")
    assert closure_phase.state == "active"
    substep_states = {s.substep: s.state for s in closure_phase.substeps}
    # Checkpoints with True -> done
    assert substep_states["integrity_gate"] == "done"
    assert substep_states["branch_push"] == "done"
    # Remaining checkpoints -> pending (merge_done, story_closed, etc. are False)
    assert substep_states["merge"] in ("pending", "optional-pending")
    assert substep_states["story_close"] in ("pending", "optional-pending")
    assert substep_states["metrics"] in ("pending", "optional-pending")
    assert substep_states["postflight"] in ("pending", "optional-pending")


def test_flow_snapshot_exploration_gate_approved_all_substeps_done() -> None:
    """ExplorationPayload.gate_status=approved -> all exploration substeps done."""
    from tests.phase_state_factory import make_phase_state

    from agentkit.core_types import ExplorationGateStatus
    from agentkit.pipeline_engine.phase_executor.models import (
        ExplorationPayload,
        PhaseStatus,
    )

    phase_state = make_phase_state(
        phase="exploration",
        status=PhaseStatus.IN_PROGRESS,
        payload=ExplorationPayload(gate_status=ExplorationGateStatus.APPROVED),
    )
    result = build_story_flow_snapshot(
        "AG3-091-expl",
        story_status="In Progress",
        is_fast_mode=False,
        current_phase_state=phase_state,
    )
    expl_phase = next(p for p in result.phases if p.phase == "exploration")
    assert expl_phase.state == "active"
    for substep in expl_phase.substeps:
        assert substep.state in ("done", "optional-pending"), (
            f"gate_status=approved: substep {substep.substep!r} must be 'done' "
            f"(or optional-pending for optional), got {substep.state!r}"
        )


def test_flow_snapshot_unknown_phase_state_status_maps_to_pending() -> None:
    """Unknown PhaseState status value falls back to 'pending'."""
    ps = _phase_state_mock("setup", "unknown_state")
    result = build_story_flow_snapshot(
        "AG3-011",
        story_status="In Progress",
        is_fast_mode=False,
        current_phase_state=ps,
    )
    setup_phase = next(p for p in result.phases if p.phase == "setup")
    assert setup_phase.state == "pending"


# ---------------------------------------------------------------------------
# build_coverage_acceptance
# ---------------------------------------------------------------------------


def _link(are_item_id: str, kind: StoryAreLinkKind = StoryAreLinkKind.ADDRESSES) -> StoryAreLink:
    return StoryAreLink(story_id="AG3-010", are_item_id=are_item_id, kind=kind)


def test_coverage_acceptance_empty_links_and_criteria() -> None:
    result = build_coverage_acceptance("AG3-010", "proj-x", [], [])
    assert isinstance(result, StoryCoverageAcceptance)
    assert result.story_id == "AG3-010"
    assert result.project_key == "proj-x"
    assert result.acceptance_criteria == []
    assert result.linked_requirements == []


def test_coverage_acceptance_deduplicates_and_sorts_are_ids() -> None:
    links = [
        _link("ARE-003"),
        _link("ARE-001"),
        _link("ARE-001"),  # duplicate
        _link("ARE-002"),
    ]
    result = build_coverage_acceptance("AG3-010", "proj-x", links, ["AC1", "AC2"])
    assert result.linked_requirements == ["ARE-001", "ARE-002", "ARE-003"]


def test_coverage_acceptance_preserves_criteria_order() -> None:
    criteria = ["The system must do X", "The system must do Y"]
    result = build_coverage_acceptance("AG3-010", "proj-x", [], criteria)
    assert result.acceptance_criteria == criteria


# ---------------------------------------------------------------------------
# build_are_evidence
# ---------------------------------------------------------------------------


def test_are_evidence_empty_links() -> None:
    result = build_are_evidence("AG3-020", "proj-y", [])
    assert isinstance(result, StoryAreEvidence)
    assert result.story_id == "AG3-020"
    assert result.project_key == "proj-y"
    assert result.linked_requirements == []


def test_are_evidence_sorted_by_are_item_id() -> None:
    """Non-empty links require a verdict (FAIL-CLOSED); sort order is by are_item_id."""
    from agentkit.requirements_coverage.contract import AreDockpointStatus, CoverageVerdict

    links = [
        StoryAreLink(story_id="AG3-020", are_item_id="ARE-B", kind=StoryAreLinkKind.PARTIAL),
        StoryAreLink(story_id="AG3-020", are_item_id="ARE-A", kind=StoryAreLinkKind.ADDRESSES),
        StoryAreLink(story_id="AG3-020", are_item_id="ARE-C", kind=StoryAreLinkKind.DERIVES_FROM),
    ]
    # Verdict required when links non-empty (FAIL-CLOSED).
    verdict = CoverageVerdict(
        status=AreDockpointStatus.PASS,
        verdict="PASS",
        uncovered_requirements=(),
    )
    result = build_are_evidence("AG3-020", "proj-y", links, coverage_verdict=verdict)
    ids = [lv.are_item_id for lv in result.linked_requirements]
    assert ids == ["ARE-A", "ARE-B", "ARE-C"]


def test_are_evidence_kind_is_lowercased_value() -> None:
    """Non-empty links require a verdict; kind value is the lowercase string."""
    from agentkit.requirements_coverage.contract import AreDockpointStatus, CoverageVerdict

    links = [
        StoryAreLink(story_id="AG3-020", are_item_id="ARE-Z", kind=StoryAreLinkKind.RECURRING),
    ]
    verdict = CoverageVerdict(
        status=AreDockpointStatus.PASS,
        verdict="PASS",
        uncovered_requirements=(),
    )
    result = build_are_evidence("AG3-020", "proj-y", links, coverage_verdict=verdict)
    assert result.linked_requirements[0].kind == "recurring"


# ---------------------------------------------------------------------------
# build_are_evidence — FAIL-CLOSED: verdict required for non-empty links (ERROR 2)
# ---------------------------------------------------------------------------


def test_are_evidence_fail_closed_non_empty_links_without_verdict() -> None:
    """ERROR 2: build_are_evidence raises when links non-empty and no verdict.

    FAIL-CLOSED defense-in-depth: the builder must never silently produce
    ``"linked"`` coverage status for requirements without a live ARE verdict.
    The route layer is responsible for the 503; this guard prevents the builder
    from being called incorrectly.
    """
    links = [
        StoryAreLink(story_id="AG3-020", are_item_id="ARE-1", kind=StoryAreLinkKind.ADDRESSES),
    ]
    with pytest.raises(AreVerdictRequiredError):
        build_are_evidence("AG3-020", "proj-y", links)


def test_are_evidence_empty_links_without_verdict_is_allowed() -> None:
    """Empty link list with no verdict is not an error (trivially no requirements)."""
    result = build_are_evidence("AG3-020", "proj-y", [])
    assert isinstance(result, StoryAreEvidence)
    assert result.linked_requirements == []


# ---------------------------------------------------------------------------
# build_mode_lock — AC2 SSOT-guard: no second computation (MAJOR fix)
# ---------------------------------------------------------------------------


def test_build_mode_lock_delegates_to_derive_mode_lock_ssot() -> None:
    """MAJOR AC2: build_mode_lock must delegate to derive_mode_lock (SSOT).

    A spy on ``derive_mode_lock`` (as imported by the read_models module) asserts
    it is called exactly once, proving no parallel computation happens inside
    build_mode_lock itself (AC2: single source of truth).
    """
    from agentkit.project_management.views import ProjectModeLock

    sentinel = ProjectModeLock(project_key="proj-ssot", mode="idle")
    with patch(
        "agentkit.project_management.read_models.derive_mode_lock",
        return_value=sentinel,
    ) as spy:
        result = build_mode_lock("proj-ssot", [])
    spy.assert_called_once_with("proj-ssot", [])
    # Result is exactly the sentinel returned by derive_mode_lock
    assert result is sentinel


def test_build_mode_lock_fast_mode_story_returns_fast() -> None:
    """MAJOR AC2: build_mode_lock returns mode=fast when a fast-mode story is in progress.

    Covers the ``fast`` mode branch that was absent from prior tests (story.md §3 AC2).
    Constructs a real Story with mode=fast and status=In Progress and asserts the
    read-model returns mode='fast'.
    """
    from agentkit.story_context_manager.story_model import Story, StoryStatus, WireStoryMode, WireStoryType

    # Build a minimal real Story with mode=fast and status=In Progress.
    story = Story(
        project_key="proj-fast",
        story_number=1,
        story_display_id="PF-1",
        title="Fast story",
        story_type=WireStoryType.IMPLEMENTATION,
        mode=WireStoryMode.FAST,
        status=StoryStatus.IN_PROGRESS,
        participating_repos=["repo-x"],
    )

    result = build_mode_lock("proj-fast", [story])
    assert result.mode == "fast", (
        f"Expected mode='fast' for in-progress fast-mode story, got {result.mode!r}"
    )
    assert result.project_key == "proj-fast"
