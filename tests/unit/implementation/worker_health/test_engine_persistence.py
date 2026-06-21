"""Engine and persistence tests for worker health."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import pytest

from agentkit.backend.config.worker_health import WorkerHealthConfig, WorkerHealthToolCallLogConfig
from agentkit.backend.governance.guard_evaluation import HookEvent
from agentkit.backend.implementation.worker_health import PostToolOutcome, apply_post_tool_use
from agentkit.backend.implementation.worker_health.artifacts import (
    AGENT_HEALTH_FILE,
    TOOL_CALL_LOG_FILE,
    export_agent_health,
)
from agentkit.backend.state_backend.store.worker_health_repository import (
    StateBackendWorkerHealthRepository,
)

if TYPE_CHECKING:
    from pathlib import Path


@pytest.fixture()
def _sqlite_backend(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AGENTKIT_STATE_BACKEND", "sqlite")
    monkeypatch.setenv("AGENTKIT_ALLOW_SQLITE", "1")
    monkeypatch.delenv("AGENTKIT_STATE_DATABASE_URL", raising=False)


def test_failed_git_commit_through_post_engine_updates_hook_conflict(
    tmp_path: Path,
    _sqlite_backend: None,
) -> None:
    repository = StateBackendWorkerHealthRepository(tmp_path)
    event = HookEvent(
        operation="bash_command",
        freshness_class="mutation",
        operation_args={
            "story_id": "AG3-080",
            "worker_id": "worker-1",
            "command": "git commit -m change",
        },
    )
    outcome = PostToolOutcome(exit_code=1, stderr="SECRET_CONTENT detected")

    state = apply_post_tool_use(
        event=event,
        outcome=outcome,
        repository=repository,
        project_root=tmp_path,
    )

    persisted = repository.load(story_id="AG3-080", worker_id="worker-1")
    assert persisted is not None
    assert state.hook_failures[0].reason == "SECRET_CONTENT"
    assert persisted.score_components.hook_conflict == 15
    assert persisted.total_score >= 15
    assert (tmp_path / "_temp" / "qa" / "AG3-080" / AGENT_HEALTH_FILE).is_file()


def test_successful_git_commit_through_post_engine_does_not_update_hook_conflict(
    tmp_path: Path,
    _sqlite_backend: None,
) -> None:
    repository = StateBackendWorkerHealthRepository(tmp_path)
    event = HookEvent(
        operation="bash_command",
        freshness_class="mutation",
        operation_args={
            "story_id": "AG3-080",
            "worker_id": "worker-1",
            "command": "git commit -m change",
        },
    )

    state = apply_post_tool_use(
        event=event,
        outcome=PostToolOutcome(exit_code=0),
        repository=repository,
        project_root=tmp_path,
    )

    persisted = repository.load(story_id="AG3-080", worker_id="worker-1")
    assert persisted is not None
    assert state.hook_failures == []
    assert persisted.score_components.hook_conflict == 0
    assert persisted.total_score == 0


def test_agent_health_export_is_idempotent_and_tool_log_trims(
    tmp_path: Path,
    _sqlite_backend: None,
) -> None:
    repository = StateBackendWorkerHealthRepository(tmp_path)
    config = WorkerHealthConfig(
        tool_call_log=WorkerHealthToolCallLogConfig(max_entries=2),
    )
    event = HookEvent(
        operation="file_read",
        freshness_class="guarded_read",
        operation_args={"story_id": "AG3-080", "worker_id": "worker-1"},
    )

    state = None
    for _ in range(3):
        state = apply_post_tool_use(
            event=event,
            outcome=PostToolOutcome(exit_code=0),
            repository=repository,
            project_root=tmp_path,
            config=config,
        )
    assert state is not None
    health_path = export_agent_health(project_root=tmp_path, state=state)
    first = health_path.read_text(encoding="utf-8")
    export_agent_health(project_root=tmp_path, state=state)
    second = health_path.read_text(encoding="utf-8")
    log_path = tmp_path / "_temp" / "qa" / "AG3-080" / TOOL_CALL_LOG_FILE

    assert first == second
    assert len(log_path.read_text(encoding="utf-8").splitlines()) == 2
    assert json.loads(first)["story_id"] == "AG3-080"
