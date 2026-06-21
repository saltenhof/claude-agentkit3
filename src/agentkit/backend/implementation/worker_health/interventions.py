"""PreToolUse intervention decisions for the worker-health monitor."""

from __future__ import annotations

from dataclasses import dataclass

from agentkit.backend.config.worker_health import WorkerHealthConfig
from agentkit.backend.implementation.worker_health.models import (
    AgentHealthState,
    InterventionKind,
    InterventionRecord,
    utc_now,
)


@dataclass(frozen=True)
class InterventionResult:
    """Health-monitor PreToolUse decision result."""

    exit_code: int
    message: str
    state: AgentHealthState


def intervention_decision(
    state: AgentHealthState,
    *,
    config: WorkerHealthConfig | None = None,
) -> int:
    """Return the PreToolUse exit code for the current health state."""

    return intervention_decision_result(state, config=config).exit_code


def intervention_decision_result(
    state: AgentHealthState,
    *,
    config: WorkerHealthConfig | None = None,
) -> InterventionResult:
    """Apply intervention state transitions and return the decision."""

    worker_health = config or WorkerHealthConfig()
    thresholds = worker_health.scoring.thresholds

    if state.hard_stop_issued and state.final_call_used:
        message = _permanent_block_message(state)
        _record_intervention(state, InterventionKind.PERMANENT_BLOCK, message)
        return InterventionResult(exit_code=2, message=message, state=state)

    if state.hard_stop_issued and not state.final_call_used:
        state.final_call_used = True
        message = "AGENTKIT HEALTH MONITOR - Final call permitted for worker-manifest.json."
        _record_intervention(state, InterventionKind.FINAL_CALL, message)
        return InterventionResult(exit_code=0, message=message, state=state)

    if state.total_score >= thresholds.hard_stop:
        state.hard_stop_issued = True
        state.final_call_used = False
        message = _hard_stop_message(state)
        _record_intervention(state, InterventionKind.HARD_STOP, message)
        return InterventionResult(exit_code=2, message=message, state=state)

    if state.total_score < thresholds.intervention:
        return InterventionResult(exit_code=0, message="", state=state)

    if not state.soft_intervention_issued:
        state.soft_intervention_issued = True
        state.observation_calls_remaining = 5
        message = _soft_intervention_message(state)
        _record_intervention(state, InterventionKind.SOFT, message)
        return InterventionResult(exit_code=2, message=message, state=state)

    if state.observation_calls_remaining > 0:
        state.observation_calls_remaining -= 1

    return InterventionResult(exit_code=0, message="", state=state)


def _record_intervention(
    state: AgentHealthState,
    kind: InterventionKind,
    message: str,
) -> None:
    state.interventions.append(
        InterventionRecord(
            at=utc_now(),
            kind=kind,
            score=state.total_score,
            message=message,
        )
    )
    state.last_updated = utc_now()


def _soft_intervention_message(state: AgentHealthState) -> str:
    return (
        "AGENTKIT HEALTH MONITOR - Intervention\n\n"
        "Your behavior pattern shows signs of stagnation or constraint conflict.\n"
        f"Score: {state.total_score}/100.\n\n"
        "Declare your status with one of these options:\n"
        "1. PROGRESSING - describe the next concrete milestone.\n"
        "2. BLOCKED - write worker-manifest.json with status BLOCKED and stop.\n"
        "3. SPARRING_NEEDED - get a second opinion through the MCP pool.\n"
        "Respond to this message before continuing work."
    )


def _hard_stop_message(state: AgentHealthState) -> str:
    return (
        "AGENTKIT HEALTH MONITOR - Hard Stop\n\n"
        f"Score: {state.total_score}/100. Maximum tolerance exceeded.\n\n"
        "You MUST now immediately:\n"
        "1. write worker-manifest.json with status BLOCKED\n"
        "2. fill blocking_issue and attempted_remediations\n"
        "3. execute no further tool calls after that\n\n"
        "Your next tool call is your final call."
    )


def _permanent_block_message(state: AgentHealthState) -> str:
    return (
        "AGENTKIT HEALTH MONITOR - Permanent block.\n"
        f"Score: {state.total_score}/100. worker-manifest.json final-call window is closed."
    )
