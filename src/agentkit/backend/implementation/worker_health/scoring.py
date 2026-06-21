"""Deterministic worker-health scoring heuristics."""

from __future__ import annotations

import hashlib
from typing import TYPE_CHECKING

from agentkit.backend.config.worker_health import WorkerHealthConfig
from agentkit.backend.implementation.worker_health.models import (
    AgentHealthState,
    CommitFailureCategory,
    CommitFailureClassification,
    HookFailure,
    PostToolOutcome,
    ScoreComponents,
    StorySize,
    ToolCallRecord,
)

if TYPE_CHECKING:
    from datetime import datetime

_FAILURE_PATTERNS: dict[str, CommitFailureCategory] = {
    "SECRET_CONTENT": CommitFailureCategory.POLICY_CONFLICT,
    "password detected": CommitFailureCategory.POLICY_CONFLICT,
    "policy violation": CommitFailureCategory.POLICY_CONFLICT,
    "ruff check": CommitFailureCategory.FIXABLE_LOCAL,
    "mypy: error": CommitFailureCategory.FIXABLE_LOCAL,
    "format failed": CommitFailureCategory.FIXABLE_LOCAL,
    "FAILED test_": CommitFailureCategory.FIXABLE_CODE,
    "pytest failed": CommitFailureCategory.FIXABLE_CODE,
    "build failed": CommitFailureCategory.FIXABLE_CODE,
    "command not found": CommitFailureCategory.ENVIRONMENTAL,
    "permission denied": CommitFailureCategory.ENVIRONMENTAL,
    "network": CommitFailureCategory.ENVIRONMENTAL,
}
_CATEGORY_BASE_SCORES: dict[CommitFailureCategory, int] = {
    CommitFailureCategory.FIXABLE_LOCAL: 5,
    CommitFailureCategory.FIXABLE_CODE: 5,
    CommitFailureCategory.POLICY_CONFLICT: 15,
    CommitFailureCategory.ENVIRONMENTAL: 10,
}
_CATEGORY_MAX_SCORES: dict[CommitFailureCategory, int] = {
    CommitFailureCategory.FIXABLE_LOCAL: 10,
    CommitFailureCategory.FIXABLE_CODE: 10,
    CommitFailureCategory.POLICY_CONFLICT: 25,
    CommitFailureCategory.ENVIRONMENTAL: 15,
}


def classify_commit_failure(
    outcome: PostToolOutcome | str,
) -> CommitFailureClassification:
    """Classify a failed commit from the neutral PostToolUse outcome."""

    stderr = outcome.stderr if isinstance(outcome, PostToolOutcome) else outcome
    lowered = stderr.lower()
    for pattern, category in _FAILURE_PATTERNS.items():
        if pattern.lower() in lowered:
            return CommitFailureClassification(
                category=category,
                reason=pattern,
                base_score=_CATEGORY_BASE_SCORES[category],
                max_score=_CATEGORY_MAX_SCORES[category],
            )
    category = CommitFailureCategory.ENVIRONMENTAL
    return CommitFailureClassification(
        category=category,
        reason="UNKNOWN",
        base_score=_CATEGORY_BASE_SCORES[category],
        max_score=_CATEGORY_MAX_SCORES[category],
    )


def compute_health_score(
    state: AgentHealthState,
    *,
    config: WorkerHealthConfig | None = None,
) -> int:
    """Compute the deterministic worker-health score."""

    worker_health = config or WorkerHealthConfig()
    components = ScoreComponents(
        runtime=score_runtime(state, worker_health),
        repetition=score_repetition(state, worker_health),
        hook_conflict=score_hook_conflicts(state, worker_health),
        stagnation=score_stagnation(state, worker_health),
        tool_calls=score_tool_calls(state, worker_health),
        llm_assessment=state.llm_assessment.delta,
    )
    state.score_components = components
    state.total_score = components.total()
    return state.total_score


def score_runtime(state: AgentHealthState, config: WorkerHealthConfig) -> int:
    """Score elapsed runtime against configured story-size percentiles."""

    elapsed_minutes = max(
        0.0,
        (state.last_updated - state.started_at).total_seconds() / 60.0,
    )
    p50, p75, p95 = _runtime_thresholds(config, state.story_size)
    max_points = config.scoring.runtime.max_points
    if elapsed_minutes < p50:
        return 0
    if elapsed_minutes < p75:
        return max_points // 3
    if elapsed_minutes < p95:
        return (max_points * 2) // 3
    return max_points


def score_repetition(state: AgentHealthState, config: WorkerHealthConfig) -> int:
    """Score repeated edit/read cycles against the same target."""

    settings = config.scoring.repetition
    window = state.recent_tool_calls[-settings.window_size :]
    if not window:
        return 0
    counts: dict[str, int] = {}
    for call in window:
        if call.target:
            counts[call.target] = counts.get(call.target, 0) + 1
    if not counts:
        return 0
    repeats = max(counts.values())
    if repeats < settings.same_file_threshold:
        return 0
    overage = repeats - settings.same_file_threshold + 1
    return min(settings.max_points, overage * 5)


def score_hook_conflicts(state: AgentHealthState, config: WorkerHealthConfig) -> int:
    """Score known commit/hook failures."""

    settings = config.scoring.hook_conflict
    if not state.hook_failures:
        return 0
    return min(
        settings.max_points,
        max(failure.contribution for failure in state.hook_failures),
    )


def score_stagnation(state: AgentHealthState, config: WorkerHealthConfig) -> int:
    """Score green-test/no-commit stagnation."""

    if state.tests_green_since is None:
        return 0
    reference = state.last_commit_at or state.started_at
    if reference >= state.tests_green_since:
        return 0
    minutes = (state.last_updated - state.tests_green_since).total_seconds() / 60.0
    settings = config.scoring.stagnation
    if minutes < settings.no_commit_warning_minutes:
        return 0
    if minutes < settings.no_commit_critical_minutes:
        return settings.max_points // 2
    return settings.max_points


def score_tool_calls(state: AgentHealthState, config: WorkerHealthConfig) -> int:
    """Score total tool-call volume."""

    settings = config.scoring.tool_calls
    if state.tool_call_count < settings.soft_limit:
        return 0
    if state.tool_call_count < settings.hard_limit:
        return settings.max_points // 2
    return settings.max_points


def register_commit_failure(
    state: AgentHealthState,
    outcome: PostToolOutcome,
    *,
    config: WorkerHealthConfig | None = None,
) -> None:
    """Add or update a commit-failure entry in state."""

    worker_health = config or WorkerHealthConfig()
    classification = classify_commit_failure(outcome)
    threshold = worker_health.scoring.hook_conflict.same_reason_threshold
    for failure in state.hook_failures:
        if failure.reason == classification.reason:
            failure.count += 1
            failure.contribution = (
                classification.max_score
                if failure.count >= threshold
                else classification.base_score
            )
            failure.at = state.last_updated
            failure.stderr_excerpt = _excerpt(outcome.stderr)
            return
    contribution = classification.base_score
    state.hook_failures.append(
        HookFailure(
            at=state.last_updated,
            reason=classification.reason,
            category=classification.category,
            count=1,
            contribution=contribution,
            stderr_excerpt=_excerpt(outcome.stderr),
        )
    )


def build_tool_call_record(
    *,
    operation: str,
    operation_args: dict[str, object],
    at: datetime,
) -> ToolCallRecord:
    """Build a stable neutral tool-call record from HookEvent fields."""

    command = str(operation_args.get("command", ""))
    target = _target_from_args(operation_args)
    args_hash = hashlib.sha256(
        repr(sorted(operation_args.items())).encode("utf-8"),
    ).hexdigest()[:16]
    return ToolCallRecord(
        at=at,
        operation=operation,
        target=target,
        command=command,
        args_hash=args_hash,
    )


def is_failed_git_commit(
    *,
    operation: str,
    operation_args: dict[str, object],
    outcome: PostToolOutcome,
) -> bool:
    """Return whether the neutral event/outcome represents a failed git commit."""

    command = str(operation_args.get("command", ""))
    return (
        operation == "bash_command"
        and "git commit" in command
        and outcome.exit_code is not None
        and outcome.exit_code != 0
    )


def _runtime_thresholds(
    config: WorkerHealthConfig,
    story_size: StorySize,
) -> tuple[int, int, int]:
    runtime = config.scoring.runtime
    if story_size == "S":
        return runtime.S
    if story_size == "L":
        return runtime.L
    return runtime.M


def _target_from_args(operation_args: dict[str, object]) -> str:
    for key in ("file_path", "path", "target"):
        value = operation_args.get(key)
        if isinstance(value, str):
            return value
    return ""


def _excerpt(text: str, *, limit: int = 500) -> str:
    return text[:limit]
