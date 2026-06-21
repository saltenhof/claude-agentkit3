"""Unit tests for worker-health scoring and interventions."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from agentkit.backend.implementation.worker_health import (
    AgentHealthState,
    CommitFailureCategory,
    PostToolOutcome,
    ToolCallRecord,
    classify_commit_failure,
    compute_health_score,
    intervention_decision_result,
)
from agentkit.backend.implementation.worker_health.scoring import register_commit_failure


def _state(score: int = 0) -> AgentHealthState:
    started = datetime(2026, 6, 9, 8, 0, tzinfo=UTC)
    return AgentHealthState(
        worker_id="worker-1",
        story_id="AG3-080",
        started_at=started,
        last_updated=started,
        total_score=score,
    )


def test_compute_health_score_is_deterministic_for_identical_state() -> None:
    base = _state()
    base.tool_call_count = 120
    base.tests_green_since = base.started_at + timedelta(minutes=1)
    base.last_updated = base.started_at + timedelta(minutes=120)
    for _ in range(5):
        base.recent_tool_calls.append(
            ToolCallRecord(
                at=base.started_at,
                operation="file_edit",
                target="src/app.py",
                args_hash="same",
            )
        )
    first = base.model_copy(deep=True)
    second = base.model_copy(deep=True)

    assert compute_health_score(first) == compute_health_score(second)
    assert first.score_components == second.score_components


def test_post_tool_outcome_contract_is_harness_neutral() -> None:
    outcome = PostToolOutcome(exit_code=1, stdout="out", stderr="ruff check failed")

    assert outcome.exit_code == 1
    assert "tool_name" not in PostToolOutcome.model_fields
    assert classify_commit_failure(outcome).category is CommitFailureCategory.FIXABLE_LOCAL


def test_classify_commit_failure_categories_and_unknown_fallback() -> None:
    cases = {
        "ruff check failed": CommitFailureCategory.FIXABLE_LOCAL,
        "FAILED test_example": CommitFailureCategory.FIXABLE_CODE,
        "SECRET_CONTENT in test fixture": CommitFailureCategory.POLICY_CONFLICT,
        "permission denied": CommitFailureCategory.ENVIRONMENTAL,
        "unrecognised failure text": CommitFailureCategory.ENVIRONMENTAL,
    }

    for stderr, expected in cases.items():
        assert classify_commit_failure(PostToolOutcome(stderr=stderr)).category is expected


def test_commit_failure_repeat_escalates_to_category_maximum() -> None:
    state = _state()
    outcome = PostToolOutcome(exit_code=1, stderr="SECRET_CONTENT detected")

    register_commit_failure(state, outcome)
    assert state.hook_failures[0].contribution == 15
    register_commit_failure(state, outcome)

    assert state.hook_failures[0].count == 2
    assert state.hook_failures[0].contribution == 25


def test_intervention_thresholds_and_once_guarantee() -> None:
    assert intervention_decision_result(_state(49)).exit_code == 0
    assert intervention_decision_result(_state(50)).exit_code == 0

    soft = _state(70)
    first = intervention_decision_result(soft)
    second = intervention_decision_result(soft)
    assert first.exit_code == 2
    assert "PROGRESSING" in first.message
    assert "BLOCKED" in first.message
    assert "SPARRING_NEEDED" in first.message
    assert second.exit_code == 0
    assert len([i for i in soft.interventions if i.kind == "soft"]) == 1

    soft.total_score = 85
    hard = intervention_decision_result(soft)
    final = intervention_decision_result(soft)
    permanent = intervention_decision_result(soft)

    assert hard.exit_code == 2
    assert "worker-manifest.json" in hard.message
    assert final.exit_code == 0
    assert permanent.exit_code == 2
    assert "Permanent block" in permanent.message
