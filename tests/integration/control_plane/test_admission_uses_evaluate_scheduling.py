"""Productive wiring: Tor-2 admission consumes ``evaluate_scheduling`` (AG3-100).

FK-70 §70.8 / FK-20 §20.8.2: the ONE pre-start admission path (``PreStartGuard``
Tor 2 over ``build_execution_planning_admission_reader``) is MIGRATED off the legacy
``assess_readiness`` source onto the ``evaluate_scheduling`` top-surface. This proves
the migration on the REAL productive path (no spy): edges written through the BC-9
planning projection write path drive a real ``evaluate_scheduling`` evaluation, and:

* a predecessor with no open dependency is admitted (READY candidate);
* a successor with an open hard predecessor is NOT admitted (negative path -- no
  setup start without a READY result, never a direct backlog reach);
* the admission reader's answer is IDENTICAL to a direct ``evaluate_scheduling``
  evaluation over the same stores -- proving a SINGLE source of truth, not a second
  parallel admission/scheduling truth.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest

from agentkit.backend.bootstrap.composition_root import (
    build_planning_story_dependency_repository,
)
from agentkit.backend.control_plane.dispatch import (
    build_execution_planning_admission_reader,
    build_pre_start_guard,
)
from agentkit.backend.core_types import StoryDependencyKind
from agentkit.backend.execution_planning.dependency_graph import DependencyGraph
from agentkit.backend.execution_planning.entities import (
    ExecutionCapacityBudgets,
    ParallelizationConfig,
    StoryDependency,
)
from agentkit.backend.execution_planning.scheduling import evaluate_scheduling
from agentkit.backend.project_management.entities import ProjectConfiguration
from agentkit.backend.project_management.lifecycle import create_project
from agentkit.backend.state_backend.persistence_test_support import reset_backend_cache_for_tests
from agentkit.backend.state_backend.store.inflight_idempotency_guard import (
    InMemoryInflightIdempotencyGuard,
)
from agentkit.backend.state_backend.store.parallelization_config_repository import (
    StateBackendParallelizationConfigRepository,
)
from agentkit.backend.state_backend.store.planning_story_repository import (
    StateBackendPlanningStoryRepository,
)
from agentkit.backend.state_backend.store.project_management_repository import (
    StateBackendProjectRepository,
)
from agentkit.backend.state_backend.store.story_repository import (
    StateBackendStoryRepository,
)
from agentkit.backend.story_context_manager.service import StoryService
from agentkit.backend.story_context_manager.story_model import CreateStoryInput

if TYPE_CHECKING:
    from pathlib import Path

_PROJECT = "tenant-a"


@pytest.fixture(autouse=True)
def _sqlite_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AGENTKIT_STATE_BACKEND", "sqlite")
    monkeypatch.setenv("AGENTKIT_ALLOW_SQLITE", "1")
    reset_backend_cache_for_tests()


def _story_service(tmp_path: Path) -> StoryService:
    return StoryService(
        story_repository=StateBackendStoryRepository(tmp_path),
        project_repository=StateBackendProjectRepository(tmp_path),
        idempotency_guard=InMemoryInflightIdempotencyGuard(),
        event_emitter=lambda *_: None,
    )


def _seed(tmp_path: Path) -> tuple[str, str]:
    config = ProjectConfiguration(
        repo_url="",
        default_branch="main",
        default_worker_count=2,
        repositories=["repo-a"],
    )
    StateBackendProjectRepository(tmp_path).save(
        create_project(_PROJECT, "Tenant A", "AG3", config, repositories=["repo-a"]),
    )
    service = _story_service(tmp_path)
    story_a = service.create_story(
        CreateStoryInput(
            project_key=_PROJECT, title="Predecessor A",
            type="implementation", repos=["repo-a"],
        ),
        op_id="op-a",
    )
    story_b = service.create_story(
        CreateStoryInput(
            project_key=_PROJECT, title="Dependent B",
            type="implementation", repos=["repo-a"],
        ),
        op_id="op-b",
    )
    service.approve_story(story_a.story_display_id, op_id="op-approve-a")
    service.approve_story(story_b.story_display_id, op_id="op-approve-b")
    # Real B -> A hard edge through the planning projection write path.
    build_planning_story_dependency_repository(tmp_path).add(
        StoryDependency(
            story_id=story_b.story_display_id,
            depends_on_story_id=story_a.story_display_id,
            kind=StoryDependencyKind.HARD_STORY_DEPENDENCY,
            created_at=datetime.now(UTC),
        ),
        project_key=_PROJECT,
    )
    return story_a.story_display_id, story_b.story_display_id


def test_admission_admits_ready_candidate_blocks_open_predecessor(
    tmp_path: Path,
) -> None:
    """Tor-2 admits A (READY candidate) and rejects B (open hard predecessor)."""
    story_a, story_b = _seed(tmp_path)
    reader = build_execution_planning_admission_reader(tmp_path)
    assert reader.is_ready_and_admitted(_PROJECT, story_a) is True
    assert reader.is_ready_and_admitted(_PROJECT, story_b) is False


def test_pre_start_guard_rejects_setup_for_blocked_story(tmp_path: Path) -> None:
    """Negative path: the fail-closed guard rejects a fresh setup start for B.

    B is approved (Tor 1) but NOT a ``evaluate_scheduling`` READY candidate (Tor 2),
    so the productive ``PreStartGuard`` rejects the setup start -- no story start
    without a READY result.
    """
    _story_a, story_b = _seed(tmp_path)
    guard = build_pre_start_guard(tmp_path)
    rejection = guard.evaluate(project_key=_PROJECT, story_display_id=story_b)
    assert rejection is not None
    assert "READY" in rejection or "scheduling" in rejection


def test_admission_reader_matches_direct_evaluate_scheduling(tmp_path: Path) -> None:
    """SINGLE SOURCE OF TRUTH: the reader answer equals direct evaluate_scheduling.

    Proves no second parallel admission/scheduling truth: the productive admission
    reader's READY decision is exactly what ``evaluate_scheduling`` yields over the
    same stores -- the legacy ``assess_readiness`` source is no longer the gate.
    """
    story_a, story_b = _seed(tmp_path)

    story_repo = StateBackendPlanningStoryRepository(tmp_path)
    dep_repo = build_planning_story_dependency_repository(tmp_path)
    config = StateBackendParallelizationConfigRepository(tmp_path).get(_PROJECT)
    stories = story_repo.list_for_project(_PROJECT)
    if config is None:
        config = ParallelizationConfig(
            project_key=_PROJECT, max_parallel_stories=max(1, len(stories)),
        )
    repo_cap = config.max_parallel_stories_per_repo or config.max_parallel_stories
    budgets = ExecutionCapacityBudgets(
        repo_parallel_cap=repo_cap,
        merge_risk_cap=config.max_parallel_stories,
        api_rate_limit_cap=config.max_parallel_stories,
        llm_pool_cap=config.max_parallel_stories,
        ci_capacity_cap=config.max_parallel_stories,
    )
    evaluation = evaluate_scheduling(
        project_key=_PROJECT,
        stories=stories,
        dependency_graph=DependencyGraph(dep_repo.list_for_project(_PROJECT)),
        budgets=budgets,
    )

    reader = build_execution_planning_admission_reader(tmp_path)
    assert reader.is_ready_and_admitted(_PROJECT, story_a) == evaluation.is_ready(
        story_a
    )
    assert reader.is_ready_and_admitted(_PROJECT, story_b) == evaluation.is_ready(
        story_b
    )
    # And the direct evaluation itself reflects the dependency (truth content).
    assert evaluation.is_ready(story_a) is True
    assert evaluation.is_ready(story_b) is False
