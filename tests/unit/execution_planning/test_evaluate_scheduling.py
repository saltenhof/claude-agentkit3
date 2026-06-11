"""Unit tests for ``evaluate_scheduling`` + the single Execution-Input selector (AG3-100).

Pins FK-70 §70.8 (the mandatory top-surface with the seven result fields), §70.8a.3
(the one deterministic triage selector feeding both surfaces), §70.8a.4 (determinism +
re-plan trigger) and the §70.11 invariants enforceable here (#1/#2/#3/#6/#7/#9/#10).
All tests use real domain types -- no mocks of the planning logic.
"""

from __future__ import annotations

from datetime import UTC, datetime

from agentkit.core_types import StoryDependencyKind
from agentkit.execution_planning import (
    DependencyGraph,
    EvaluateSchedulingResult,
    ExecutionCapacityBudgets,
    ExternalGate,
    GateState,
    HumanGate,
    HumanGateKind,
    SchedulingHint,
    StoryDependency,
    StoryRefForPlanning,
    evaluate_scheduling,
    next_from_snapshot,
    select_execution_input,
)

_PROJECT = "tenant-a"


def _story(
    story_id: str,
    number: int,
    *,
    repo: str | None = "repo-a",
    status: str = "defined",
) -> StoryRefForPlanning:
    return StoryRefForPlanning(
        project_key=_PROJECT,
        story_id=story_id,
        story_number=number,
        title=f"Story {story_id}",
        lifecycle_status=status,
        repo=repo,
    )


def _edge(
    story_id: str,
    depends_on: str,
    kind: StoryDependencyKind = StoryDependencyKind.HARD_STORY_DEPENDENCY,
) -> StoryDependency:
    return StoryDependency(
        story_id=story_id,
        depends_on_story_id=depends_on,
        kind=kind,
        created_at=datetime(2024, 1, 1, tzinfo=UTC),
    )


def _budgets(*, repo_cap: int = 5, global_cap: int = 5) -> ExecutionCapacityBudgets:
    return ExecutionCapacityBudgets(
        repo_parallel_cap=repo_cap,
        merge_risk_cap=global_cap,
        api_rate_limit_cap=global_cap,
        llm_pool_cap=global_cap,
        ci_capacity_cap=global_cap,
    )


def _evaluate(
    stories: list[StoryRefForPlanning],
    edges: list[StoryDependency],
    *,
    budgets: ExecutionCapacityBudgets | None = None,
    human_gates: tuple[HumanGate, ...] = (),
    external_gates: tuple[ExternalGate, ...] = (),
    scheduling_hint: SchedulingHint | None = None,
) -> EvaluateSchedulingResult:
    return evaluate_scheduling(
        project_key=_PROJECT,
        stories=stories,
        dependency_graph=DependencyGraph(edges),
        budgets=budgets or _budgets(),
        human_gates=human_gates,
        external_gates=external_gates,
        scheduling_hint=scheduling_hint,
    )


class TestEvaluateSchedulingResultFields:
    def test_returns_the_seven_normative_result_fields(self) -> None:
        """AC1: the result carries all seven FK-70 §70.8 fields."""
        result = _evaluate([_story("S1", 1)], [])
        assert result.ready_candidates == ("S1",)
        assert result.blocked_stories == ()
        assert result.recommended_batch >= 0
        assert result.max_allowed_batch >= 0
        assert result.critical_path == ("S1",)
        assert result.next_wave.project_key == _PROJECT
        assert result.why_not_now == ()

    def test_feasibility_and_scheduling_are_separate_axes(self) -> None:
        """AC1 / §70.11 #3: feasibility and scheduling policy stay distinct objects."""
        result = _evaluate([_story("S1", 1), _story("S2", 2)], [])
        assert result.feasibility.project_key == _PROJECT
        assert result.scheduling_policy.project_key == _PROJECT
        # can_parallelize (feasibility) is independent from may_parallelize_now
        # (scheduling) -- two fields, never collapsed into one boolean.
        assert hasattr(result.feasibility, "can_parallelize")
        assert hasattr(result.scheduling_policy, "may_parallelize_now")


class TestInvariantNoFlightBeforeDonePredecessor:
    def test_successor_is_blocked_until_predecessor_done(self) -> None:
        """§70.11 #1 (negative): a story with an open hard predecessor is not READY."""
        stories = [_story("S1", 1), _story("S2", 2)]
        result = _evaluate(stories, [_edge("S2", "S1")])
        assert "S1" in result.ready_candidates
        assert "S2" not in result.ready_candidates
        assert "S2" in result.blocked_stories

    def test_successor_becomes_ready_when_predecessor_done(self) -> None:
        """§70.11 #1 (positive boundary): a DONE predecessor unblocks the successor."""
        stories = [_story("S1", 1, status="done"), _story("S2", 2)]
        result = _evaluate(stories, [_edge("S2", "S1")])
        assert "S2" in result.ready_candidates


class TestInvariantBlockedNotOverridden:
    def test_external_blocked_story_is_never_a_ready_candidate(self) -> None:
        """§70.11 #2: an open ExternalGate keeps the story blocked, not overridable."""
        gate = ExternalGate(
            project_key=_PROJECT,
            story_id="S1",
            gate_id="G1",
            state=GateState.OPEN,
            reason_code="external_dependency",
        )
        result = _evaluate([_story("S1", 1)], [], external_gates=(gate,))
        assert "S1" not in result.ready_candidates
        assert "S1" in result.blocked_stories
        assert any(reason.story_id == "S1" for reason in result.why_not_now)


class TestInvariantCollectiveGate:
    def test_collective_gate_only_ready_when_all_predecessors_done(self) -> None:
        """§70.11 #6: a collection story waits for all predecessors complete."""
        stories = [_story("A", 1), _story("B", 2), _story("E2E", 3)]
        edges = [_edge("E2E", "A"), _edge("E2E", "B")]
        # Only A done -> E2E still blocked.
        partial = [_story("A", 1, status="done"), _story("B", 2), _story("E2E", 3)]
        assert "E2E" not in _evaluate(partial, edges).ready_candidates
        # All predecessors done -> E2E ready.
        full = [
            _story("A", 1, status="done"),
            _story("B", 2, status="done"),
            _story("E2E", 3),
        ]
        assert "E2E" in _evaluate(full, edges).ready_candidates
        del stories


class TestInvariantSoftDependencyPriorityOnly:
    def test_soft_dependency_does_not_block_feasibility(self) -> None:
        """§70.11 #7: a soft dependency never sets a story not-ready by itself."""
        stories = [_story("S1", 1), _story("S2", 2)]
        result = _evaluate(
            stories,
            [_edge("S2", "S1", StoryDependencyKind.SOFT_STORY_DEPENDENCY)],
        )
        assert "S2" in result.ready_candidates
        assert "S2" not in result.blocked_stories


class TestInvariantOptionalHumanReviewNotBlocking:
    def test_optional_review_open_keeps_story_ready(self) -> None:
        """§70.11 #10 (negative): an OPEN optional review never blocks scheduling."""
        optional = HumanGate(
            project_key=_PROJECT,
            story_id="S1",
            gate_id="REVIEW-1",
            kind=HumanGateKind.OPTIONAL_REVIEW,
            state=GateState.OPEN,
            reason_code="optional_plan_review",
        )
        result = _evaluate([_story("S1", 1)], [], human_gates=(optional,))
        assert "S1" in result.ready_candidates
        assert "S1" not in result.blocked_stories

    def test_blocking_human_gate_holds_story_back(self) -> None:
        """§70.11 #10 (contrast): a declared blocking Human-Gate DOES hold back."""
        blocking = HumanGate(
            project_key=_PROJECT,
            story_id="S1",
            gate_id="GATE-1",
            kind=HumanGateKind.BLOCKING_GATE,
            state=GateState.OPEN,
            reason_code="manual_approval_required",
        )
        result = _evaluate([_story("S1", 1)], [], human_gates=(blocking,))
        assert "S1" not in result.ready_candidates
        assert "S1" in result.blocked_stories


class TestInvariantCycleQuarantineAndEscalation:
    def test_cycle_quarantines_subgraph_and_escalates_fail_closed(self) -> None:
        """§70.11 #9: a cycle quarantines the subgraph + escalates, no silent run-on."""
        stories = [_story("A", 1), _story("B", 2), _story("C", 3)]
        # A -> B -> A is a cycle; C depends on the cyclic A.
        edges = [_edge("A", "B"), _edge("B", "A"), _edge("C", "A")]
        result = _evaluate(stories, edges)
        assert result.escalated is True
        assert "A" in result.quarantined_story_ids
        assert "B" in result.quarantined_story_ids
        # C transitively depends on the cycle -> quarantined too, never READY.
        assert "C" in result.quarantined_story_ids
        assert "A" not in result.ready_candidates
        assert "B" not in result.ready_candidates
        assert "C" not in result.ready_candidates
        assert {"A", "B", "C"} <= set(result.blocked_stories)
        assert any(
            reason.reason_code == "quarantined_cycle" for reason in result.why_not_now
        )

    def test_acyclic_graph_does_not_escalate(self) -> None:
        """§70.11 #9 (boundary): a clean DAG raises no quarantine/escalation."""
        result = _evaluate([_story("S1", 1), _story("S2", 2)], [_edge("S2", "S1")])
        assert result.escalated is False
        assert result.quarantined_story_ids == ()


class TestDeterminism:
    def test_same_input_yields_identical_output(self) -> None:
        """§70.8a.4: identical (stories, caps, statuses) -> identical evaluation."""
        stories = [_story("S2", 2), _story("S1", 1), _story("S3", 3)]
        edges = [_edge("S3", "S1")]
        first = _evaluate(stories, edges)
        second = _evaluate(list(reversed(stories)), edges)
        assert first == second

    def test_cap_change_changes_the_pick_replan_trigger(self) -> None:
        """§70.6.2a: a cap change is a re-plan trigger -> a different selection."""
        stories = [_story("S1", 1, repo="repo-a"), _story("S2", 2, repo="repo-b")]
        wide = _evaluate(stories, [], budgets=_budgets(repo_cap=5, global_cap=5))
        narrow = _evaluate(stories, [], budgets=_budgets(repo_cap=5, global_cap=1))
        wide_pick = select_execution_input(
            project_key=_PROJECT, stories=stories, evaluation=wide,
            budgets=_budgets(repo_cap=5, global_cap=5),
        )
        narrow_pick = select_execution_input(
            project_key=_PROJECT, stories=stories, evaluation=narrow,
            budgets=_budgets(repo_cap=5, global_cap=1),
        )
        assert len(wide_pick.eligible_ready) == 2
        assert len(narrow_pick.eligible_ready) == 1
        assert wide_pick.global_slots_left != narrow_pick.global_slots_left


class TestSingleSelectorConsistency:
    def test_snapshot_and_next_derive_from_one_selector(self) -> None:
        """AC3: agent-pull ``next`` is exactly the first card of the snapshot pick."""
        stories = [
            _story("S1", 1, repo="repo-a"),
            _story("S2", 2, repo="repo-b"),
            _story("S3", 3, repo="repo-a"),
        ]
        budgets = _budgets(repo_cap=5, global_cap=5)
        evaluation = _evaluate(stories, [], budgets=budgets)
        snapshot = select_execution_input(
            project_key=_PROJECT, stories=stories, evaluation=evaluation,
            budgets=budgets,
        )
        nxt = next_from_snapshot(
            project_key=_PROJECT, stories=stories, evaluation=evaluation,
            budgets=budgets,
        )
        assert nxt.story is not None
        assert nxt.story.story.story_id == snapshot.eligible_ready[0].story.story_id
        assert nxt.reason is not None
        assert nxt.reason.active_tiebreaker == (
            "critical_path_desc_then_story_number_asc"
        )

    def test_triage_round_robin_and_critical_path_priority(self) -> None:
        """§70.8a.3: repos round-robin alphabetical, critical-path first per repo."""
        stories = [
            _story("S1", 1, repo="repo-a"),
            _story("S2", 2, repo="repo-a"),
            _story("S3", 3, repo="repo-b"),
        ]
        # S2 on the critical path via a successor edge.
        edges = [_edge("S4", "S2")]
        stories.append(_story("S4", 4, repo="repo-a"))
        budgets = _budgets(repo_cap=5, global_cap=2)
        evaluation = _evaluate(stories, edges, budgets=budgets)
        snapshot = select_execution_input(
            project_key=_PROJECT, stories=stories, evaluation=evaluation,
            budgets=budgets,
        )
        picked = [card.story.story_id for card in snapshot.eligible_ready]
        assert len(picked) == 2
        # Round-robin: first repo-a card, then repo-b card.
        assert picked[0] in {"S1", "S2"}
        assert picked[1] == "S3"

    def test_repo_cap_exhaustion_skips_repo_in_round_robin(self) -> None:
        """§70.8a.3: a repo whose per-repo cap is full is skipped during the pick."""
        stories = [
            _story("S1", 1, repo="repo-a"),
            _story("S2", 2, repo="repo-a"),
            _story("S3", 3, repo="repo-b"),
        ]
        # repo_parallel_cap=1 -> only ONE card per repo may be picked, even though
        # global slots allow more; repo-a contributes one card, then is skipped.
        budgets = _budgets(repo_cap=1, global_cap=5)
        evaluation = _evaluate(stories, [], budgets=budgets)
        snapshot = select_execution_input(
            project_key=_PROJECT, stories=stories, evaluation=evaluation,
            budgets=budgets,
        )
        picked = [card.story.story_id for card in snapshot.eligible_ready]
        repos_picked = {card.story.repo for card in snapshot.eligible_ready}
        # One card per repo (repo-a cap=1 exhausted after one pick), both repos used.
        assert len(picked) == 2
        assert repos_picked == {"repo-a", "repo-b"}

    def test_next_is_null_when_nothing_delegable(self) -> None:
        """§70.8a.2: ``next`` is None + no reason when no card is delegable."""
        stories = [_story("S1", 1), _story("S2", 2)]
        # global cap 0 -> no slots at all.
        budgets = _budgets(repo_cap=5, global_cap=0)
        evaluation = _evaluate(stories, [], budgets=budgets)
        nxt = next_from_snapshot(
            project_key=_PROJECT, stories=stories, evaluation=evaluation,
            budgets=budgets,
        )
        assert nxt.story is None
        assert nxt.reason is None


class TestSelectorIdempotency:
    def test_repeated_next_calls_return_same_answer(self) -> None:
        """§70.8a.2: idempotent agent-pull without backlog change."""
        stories = [_story("S1", 1), _story("S2", 2)]
        budgets = _budgets()
        evaluation = _evaluate(stories, [], budgets=budgets)
        first = next_from_snapshot(
            project_key=_PROJECT, stories=stories, evaluation=evaluation,
            budgets=budgets,
        )
        second = next_from_snapshot(
            project_key=_PROJECT, stories=stories, evaluation=evaluation,
            budgets=budgets,
        )
        assert first == second


class TestRunningStoriesExcluded:
    def test_running_stories_appear_in_running_not_eligible(self) -> None:
        """§70.8a.1: a FLIGHT story is reported under ``running``, not eligible."""
        stories = [
            _story("S1", 1, status="in progress"),
            _story("S2", 2),
        ]
        budgets = _budgets(repo_cap=5, global_cap=5)
        evaluation = _evaluate(stories, [], budgets=budgets)
        snapshot = select_execution_input(
            project_key=_PROJECT, stories=stories, evaluation=evaluation,
            budgets=budgets,
        )
        running_ids = {card.story.story_id for card in snapshot.running}
        eligible_ids = {card.story.story_id for card in snapshot.eligible_ready}
        assert "S1" in running_ids
        assert "S1" not in eligible_ids
        # global_slots_left reduced by the one running story.
        assert snapshot.global_slots_left == 4
