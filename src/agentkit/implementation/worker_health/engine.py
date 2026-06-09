"""Worker-health hook entry points."""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

from agentkit.config.worker_health import WorkerHealthConfig
from agentkit.implementation.worker_health.artifacts import (
    TOOL_CALL_LOG_FILE,
    append_tool_call_log,
    export_agent_health,
    load_tool_call_window,
)
from agentkit.implementation.worker_health.models import (
    AgentHealthState,
    LlmAssessmentStatus,
    PostToolOutcome,
    utc_now,
)
from agentkit.implementation.worker_health.scoring import (
    build_tool_call_record,
    compute_health_score,
    is_failed_git_commit,
    register_commit_failure,
)
from agentkit.installer.paths import qa_story_dir

if TYPE_CHECKING:
    from pathlib import Path

    from agentkit.governance.guard_evaluation import HookEvent
    from agentkit.state_backend.store.worker_health_repository import (
        WorkerHealthStateRepository,
    )


def apply_post_tool_use(
    *,
    event: HookEvent,
    outcome: PostToolOutcome,
    repository: WorkerHealthStateRepository,
    project_root: Path,
    config: WorkerHealthConfig | None = None,
    story_id: str | None = None,
    worker_id: str | None = None,
) -> AgentHealthState:
    """Update worker-health state after a neutral PostToolUse event."""

    worker_health = config or WorkerHealthConfig()
    resolved_story_id = story_id or _story_id_from_event(event)
    resolved_worker_id = worker_id or _worker_id_from_event(event)
    state = repository.load(
        story_id=resolved_story_id,
        worker_id=resolved_worker_id,
    )
    if state is None:
        state = AgentHealthState(
            worker_id=resolved_worker_id,
            story_id=resolved_story_id,
            project_key=_string_arg(event, "project_key") or os.environ.get("AGENTKIT_PROJECT_KEY", ""),
            run_id=_string_arg(event, "run_id") or os.environ.get("AGENTKIT_RUN_ID", ""),
            tool_call_log_path=str(
                qa_story_dir(project_root, resolved_story_id) / TOOL_CALL_LOG_FILE
            ),
        )
    state.last_updated = utc_now()
    record = build_tool_call_record(
        operation=event.operation,
        operation_args=dict(event.operation_args),
        at=state.last_updated,
    )
    state.tool_call_count += 1
    log_path = append_tool_call_log(
        project_root=project_root,
        story_id=resolved_story_id,
        record=record,
        config=worker_health,
    )
    state.tool_call_log_path = str(log_path)
    state.recent_tool_calls = load_tool_call_window(log_path)

    if is_failed_git_commit(
        operation=event.operation,
        operation_args=dict(event.operation_args),
        outcome=outcome,
    ):
        register_commit_failure(state, outcome, config=worker_health)

    compute_health_score(state, config=worker_health)
    maybe_request_llm_assessment(state, config=worker_health)
    repository.save(state)
    export_agent_health(project_root=project_root, state=state)
    return state


def maybe_request_llm_assessment(
    state: AgentHealthState,
    *,
    config: WorkerHealthConfig | None = None,
) -> bool:
    """Set ``llm_assessment.status=pending`` when debounce rules allow it."""

    worker_health = config or WorkerHealthConfig()
    settings = worker_health.llm_assessment
    now = state.last_updated
    assessment = state.llm_assessment
    if state.total_score < settings.trigger_score:
        return False
    if assessment.status == LlmAssessmentStatus.PENDING:
        return False
    if assessment.completed_at is not None:
        since_last = (now - assessment.completed_at).total_seconds()
        if since_last < settings.throttle_seconds:
            return False
    if (
        assessment.last_completed_score is not None
        and state.total_score - assessment.last_completed_score
        < settings.score_rise_threshold
    ):
        return False
    assessment.status = LlmAssessmentStatus.PENDING
    assessment.requested_at = now
    assessment.requested_score = state.total_score
    assessment.result = None
    assessment.error = None
    assessment.delta = 0
    return True


def _story_id_from_event(event: HookEvent) -> str:
    story_id = _string_arg(event, "story_id") or os.environ.get("AGENTKIT_STORY_ID", "")
    if not story_id:
        raise RuntimeError("health_monitor requires story_id in HookEvent or AGENTKIT_STORY_ID")
    return story_id


def _worker_id_from_event(event: HookEvent) -> str:
    return (
        _string_arg(event, "worker_id")
        or os.environ.get("AGENTKIT_WORKER_ID", "")
        or event.session_id
        or "worker"
    )


def _string_arg(event: HookEvent, key: str) -> str:
    value = event.operation_args.get(key)
    return value if isinstance(value, str) else ""
