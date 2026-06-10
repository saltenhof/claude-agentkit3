"""Worker-health LLM assessment sidecar."""

from __future__ import annotations

import re
import time
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeoutError
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Protocol

from agentkit.config.worker_health import WorkerHealthConfig
from agentkit.implementation.worker_health.artifacts import export_agent_health
from agentkit.implementation.worker_health.models import (
    AgentHealthState,
    LlmAssessmentStatus,
    utc_now,
)
from agentkit.multi_llm_hub.client import HubClient, HubClientProtocol
from agentkit.multi_llm_hub.config import load_multi_llm_hub_config
from agentkit.state_backend.store.worker_health_repository import (
    StateBackendWorkerHealthRepository,
    WorkerHealthStateRepository,
)

if TYPE_CHECKING:
    from pathlib import Path

    from agentkit.multi_llm_hub.entities import HubBackendName


class WorkerHealthAssessmentClient(Protocol):
    """Boundary for obtaining loop probability from an external LLM."""

    def assess_loop_probability(self, state: AgentHealthState) -> int: ...


class HubWorkerHealthAssessmentClient:
    """Multi-LLM Hub backed worker-health assessment client."""

    def __init__(
        self,
        *,
        hub_client: HubClientProtocol | None = None,
        models: list[str] | None = None,
    ) -> None:
        config = load_multi_llm_hub_config()
        self._hub_client = hub_client or HubClient(config.base_url)
        self._models = models or ["gemini", "grok", "qwen"]

    def assess_loop_probability(self, state: AgentHealthState) -> int:
        """Request and parse one loop-probability assessment."""

        llms = [_backend_name(model) for model in self._models]
        lease = self._hub_client.acquire(
            owner="agentkit-worker-health",
            description=f"Worker-health assessment for {state.story_id}",
            llms=llms,
        )
        try:
            responses = self._hub_client.send(
                session_id=lease.session_id,
                token=lease.token,
                message=_assessment_prompt(state),
                target=llms[0] if llms else None,
            )
        finally:
            self._hub_client.release(session_id=lease.session_id, token=lease.token)
        for message in responses.values():
            probability = parse_loop_probability(message.text)
            if probability is not None:
                return probability
        raise RuntimeError("LLM assessment response did not contain LOOP_PROBABILITY")


def run_worker_health_sidecar(
    story_id: str,
    *,
    project_root: Path,
    repository: WorkerHealthStateRepository | None = None,
    assessment_client: WorkerHealthAssessmentClient | None = None,
    config: WorkerHealthConfig | None = None,
    iterations: int | None = None,
) -> int:
    """Poll the state backend and resolve pending LLM assessments.

    Returns:
        0 on clean shutdown (idle timeout or requested iterations completed).
        1 when the story state was never found during the entire run (indicates
        the story may not exist or the state backend is unavailable).
    """
    worker_health = config or WorkerHealthConfig()
    repo = repository or StateBackendWorkerHealthRepository(project_root)
    client = assessment_client or HubWorkerHealthAssessmentClient(
        models=worker_health.llm_assessment.models,
    )
    loops = 0
    idle_since = utc_now()
    state_found = False
    while iterations is None or loops < iterations:
        loops += 1
        state = repo.load_latest_for_story(story_id)
        if state is not None:
            state_found = True
        if state is not None and state.llm_assessment.status == LlmAssessmentStatus.PENDING:
            _resolve_pending_assessment(
                state,
                repository=repo,
                assessment_client=client,
                project_root=project_root,
                config=worker_health,
            )
            idle_since = utc_now()
        elif state is not None:
            idle_since = _refresh_expired_assessment(
                state,
                repository=repo,
                project_root=project_root,
                idle_since=idle_since,
            )
        if iterations is not None:
            continue
        if (utc_now() - idle_since).total_seconds() >= worker_health.sidecar.idle_shutdown_seconds:
            return 0
        time.sleep(worker_health.sidecar.poll_interval_seconds)
    # Iterations-bounded exit: return 1 if the story state was never found
    # (indicates story not in state backend), 0 for normal completion.
    return 0 if state_found else 1


def parse_loop_probability(text: str) -> int | None:
    """Parse ``LOOP_PROBABILITY: <0-100>`` from LLM output."""

    match = re.search(r"LOOP_PROBABILITY:\s*(\d{1,3})", text)
    if match is None:
        return None
    value = int(match.group(1))
    if value < 0 or value > 100:
        return None
    return value


def map_loop_probability_to_delta(
    probability: int,
    *,
    max_delta: int = 10,
) -> int:
    """Map loop probability to a score delta."""

    if probability <= 30:
        return -max_delta
    if probability <= 60:
        return 0
    return max_delta


def _resolve_pending_assessment(
    state: AgentHealthState,
    *,
    repository: WorkerHealthStateRepository,
    assessment_client: WorkerHealthAssessmentClient,
    project_root: Path,
    config: WorkerHealthConfig,
) -> None:
    try:
        probability = _assess_with_timeout(
            assessment_client,
            state,
            timeout_seconds=config.llm_assessment.timeout_seconds,
        )
    except Exception as exc:  # noqa: BLE001
        _mark_assessment_failed(state, error=str(exc))
    else:
        now = utc_now()
        delta = map_loop_probability_to_delta(
            probability,
            max_delta=config.llm_assessment.max_delta,
        )
        state.llm_assessment.status = LlmAssessmentStatus.COMPLETED
        state.llm_assessment.result = probability
        state.llm_assessment.delta = delta
        state.llm_assessment.completed_at = now
        state.llm_assessment.expires_at = now + timedelta(minutes=30)
        state.llm_assessment.last_completed_score = state.total_score
        state.llm_assessment.error = None
        state.score_components.llm_assessment = delta
        state.total_score = state.score_components.total()
        state.last_updated = now
    repository.save(state)
    export_agent_health(project_root=project_root, state=state)


def _mark_assessment_failed(state: AgentHealthState, *, error: str) -> None:
    now = utc_now()
    state.llm_assessment.status = LlmAssessmentStatus.FAILED
    state.llm_assessment.result = None
    state.llm_assessment.delta = 0
    state.llm_assessment.completed_at = now
    state.llm_assessment.expires_at = now + timedelta(minutes=30)
    state.llm_assessment.last_completed_score = state.total_score
    state.llm_assessment.error = error
    state.score_components.llm_assessment = 0
    state.total_score = state.score_components.total()
    state.last_updated = now


def _assess_with_timeout(
    assessment_client: WorkerHealthAssessmentClient,
    state: AgentHealthState,
    *,
    timeout_seconds: int,
) -> int:
    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(assessment_client.assess_loop_probability, state)
        try:
            return int(future.result(timeout=timeout_seconds))
        except FutureTimeoutError as exc:
            future.cancel()
            raise TimeoutError("assessment timed out") from exc


def _refresh_expired_assessment(
    state: AgentHealthState,
    *,
    repository: WorkerHealthStateRepository,
    project_root: Path,
    idle_since: datetime,
) -> datetime:
    now = utc_now()
    if (
        state.llm_assessment.status in {LlmAssessmentStatus.COMPLETED, LlmAssessmentStatus.FAILED}
        and state.llm_assessment.expires_at is not None
        and state.llm_assessment.expires_at <= now
    ):
        state.llm_assessment.status = LlmAssessmentStatus.IDLE
        state.llm_assessment.delta = 0
        state.score_components.llm_assessment = 0
        state.total_score = state.score_components.total()
        state.last_updated = now
        repository.save(state)
        export_agent_health(project_root=project_root, state=state)
        return now
    return idle_since


def _assessment_prompt(state: AgentHealthState) -> str:
    calls = "\n".join(
        f"{call.at.isoformat()} {call.operation} {call.target} {call.command}"
        for call in state.recent_tool_calls[-20:]
    )
    return (
        "Here is the tool-call log of an AI agent working on an implementation story.\n"
        f"Story: {state.story_id}\n"
        f"Runtime minutes: {(state.last_updated - state.started_at).total_seconds() / 60.0:.1f}\n"
        f"Tool calls: {state.tool_call_count}\n\n"
        f"Recent tool calls:\n{calls}\n\n"
        "How likely is it from 0-100 that the agent is stuck in a loop?\n"
        "Answer only with: LOOP_PROBABILITY: <0-100>"
    )


def _backend_name(value: str) -> HubBackendName:
    allowed: tuple[HubBackendName, ...] = ("chatgpt", "gemini", "grok", "qwen", "kimi")
    if value not in allowed:
        return "gemini"
    return value
