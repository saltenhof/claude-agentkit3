from __future__ import annotations

from datetime import UTC, datetime

import pytest

from agentkit.phase_state_store.models import FlowExecution
from agentkit.state_backend import (
    resolve_runtime_scope,
    save_flow_execution,
    save_story_context,
)
from agentkit.state_backend.config import ALLOW_SQLITE_ENV, STATE_BACKEND_ENV
from agentkit.state_backend.store import reset_backend_cache_for_tests
from agentkit.story_context_manager.models import StoryContext
from agentkit.story_context_manager.types import StoryMode, StoryType


@pytest.fixture(autouse=True)
def sqlite_backend_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(STATE_BACKEND_ENV, "sqlite")
    monkeypatch.setenv(ALLOW_SQLITE_ENV, "1")
    monkeypatch.delenv("AGENTKIT_STATE_DATABASE_URL", raising=False)
    reset_backend_cache_for_tests()
    yield
    reset_backend_cache_for_tests()


def test_resolve_runtime_scope_uses_story_context_when_run_unavailable(
    tmp_path,
) -> None:
    project_root = tmp_path / "demo-project"
    story_dir = project_root / "stories" / "AG3-111"
    story_dir.mkdir(parents=True, exist_ok=True)
    save_story_context(
        story_dir,
        StoryContext(
            project_key="demo-project",
            story_id="AG3-111",
            story_type=StoryType.IMPLEMENTATION,
            execution_route=StoryMode.EXECUTION,
            title="scope test",
            project_root=project_root,
            created_at=datetime.now(tz=UTC),
        ),
    )

    scope = resolve_runtime_scope(story_dir)

    assert scope.project_key == "demo-project"
    assert scope.story_id == "AG3-111"
    assert scope.run_id is None
    assert scope.flow_id is None
    assert scope.attempt_no is None


def test_resolve_runtime_scope_prefers_explicit_flow_scope(tmp_path) -> None:
    story_dir = tmp_path / "AG3-222"
    story_dir.mkdir(parents=True, exist_ok=True)
    save_flow_execution(
        story_dir,
        FlowExecution(
            project_key="proj-scope",
            story_id="AG3-222",
            run_id="run-scope-001",
            flow_id="implementation",
            level="story",
            owner="pipeline_engine",
            attempt_no=3,
        ),
    )

    scope = resolve_runtime_scope(story_dir)

    assert scope.project_key == "proj-scope"
    assert scope.story_id == "AG3-222"
    assert scope.run_id == "run-scope-001"
    assert scope.flow_id == "implementation"
    assert scope.attempt_no == 3
