"""Worker-health sidecar tests."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from agentkit.implementation.worker_health import AgentHealthState
from agentkit.implementation.worker_health.engine import maybe_request_llm_assessment
from agentkit.implementation.worker_health.models import LlmAssessmentStatus
from agentkit.implementation.worker_health.sidecar import (
    map_loop_probability_to_delta,
    run_worker_health_sidecar,
)
from agentkit.state_backend.store.worker_health_repository import (
    StateBackendWorkerHealthRepository,
)

if TYPE_CHECKING:
    from pathlib import Path


class _FakeAssessmentClient:
    def __init__(self, probability: int | None = None) -> None:
        self.probability = probability
        self.calls = 0

    def assess_loop_probability(self, state: AgentHealthState) -> int:
        self.calls += 1
        if self.probability is None:
            raise TimeoutError("assessment timed out")
        return self.probability


@pytest.fixture()
def _sqlite_backend(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AGENTKIT_STATE_BACKEND", "sqlite")
    monkeypatch.setenv("AGENTKIT_ALLOW_SQLITE", "1")
    monkeypatch.delenv("AGENTKIT_STATE_DATABASE_URL", raising=False)


def test_loop_probability_mapping() -> None:
    assert map_loop_probability_to_delta(30) == -10
    assert map_loop_probability_to_delta(31) == 0
    assert map_loop_probability_to_delta(61) == 10


def test_sidecar_reads_and_writes_backend_state(
    tmp_path: Path,
    _sqlite_backend: None,
) -> None:
    repository = StateBackendWorkerHealthRepository(tmp_path)
    state = AgentHealthState(worker_id="worker-1", story_id="AG3-080", total_score=70)
    assert maybe_request_llm_assessment(state) is True
    repository.save(state)

    client = _FakeAssessmentClient(probability=85)
    exit_code = run_worker_health_sidecar(
        "AG3-080",
        project_root=tmp_path,
        repository=repository,
        assessment_client=client,
        iterations=1,
    )

    updated = repository.load(story_id="AG3-080", worker_id="worker-1")
    assert exit_code == 0
    assert client.calls == 1
    assert updated is not None
    assert updated.llm_assessment.status is LlmAssessmentStatus.COMPLETED
    assert updated.llm_assessment.delta == 10
    assert (tmp_path / "_temp" / "qa" / "AG3-080" / "agent-health.json").is_file()


def test_sidecar_timeout_marks_failed_delta_zero(
    tmp_path: Path,
    _sqlite_backend: None,
) -> None:
    repository = StateBackendWorkerHealthRepository(tmp_path)
    state = AgentHealthState(worker_id="worker-1", story_id="AG3-080", total_score=70)
    assert maybe_request_llm_assessment(state) is True
    repository.save(state)

    exit_code = run_worker_health_sidecar(
        "AG3-080",
        project_root=tmp_path,
        repository=repository,
        assessment_client=_FakeAssessmentClient(probability=None),
        iterations=1,
    )

    updated = repository.load(story_id="AG3-080", worker_id="worker-1")
    assert exit_code == 0  # state was found; failure is in the assessment, not the sidecar
    assert updated is not None
    assert updated.llm_assessment.status is LlmAssessmentStatus.FAILED
    assert updated.llm_assessment.delta == 0


def test_sidecar_returns_1_when_story_state_never_found(
    tmp_path: Path,
    _sqlite_backend: None,
) -> None:
    """Bounded run with no state for the story yields exit code 1.

    This verifies the deliberate contract: 0 = ran/healthy (state found and
    processed), 1 = story state never seen during the entire run (indicates the
    story does not exist in the state backend or the backend is unavailable).
    """
    repository = StateBackendWorkerHealthRepository(tmp_path)
    # Deliberately do NOT save any state for "AG3-NOSUCH".

    exit_code = run_worker_health_sidecar(
        "AG3-NOSUCH",
        project_root=tmp_path,
        repository=repository,
        assessment_client=_FakeAssessmentClient(probability=50),
        iterations=3,  # run three loops — still no state found
    )

    assert exit_code == 1


def test_scoring_continues_without_sidecar_result() -> None:
    state = AgentHealthState(worker_id="worker-1", story_id="AG3-080", total_score=70)

    assert maybe_request_llm_assessment(state) is True
    assert state.llm_assessment.status is LlmAssessmentStatus.PENDING
    assert state.llm_assessment.delta == 0
