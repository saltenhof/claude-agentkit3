from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from agentkit.backend.execution_planning.entities import (
    ParallelizationConfig,
    StoryDependencyKind,
)
from agentkit.backend.execution_planning.errors import StoryDependencyConflictError
from agentkit.backend.execution_planning.lifecycle import add_dependency
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
from agentkit.backend.state_backend.store.story_dependency_repository import (
    StateBackendStoryDependencyRepository,
)
from agentkit.backend.state_backend.store.story_repository import (
    StateBackendStoryRepository,
)
from agentkit.backend.story_context_manager.service import StoryService
from agentkit.backend.story_context_manager.story_model import (
    CreateStoryInput,
    WireStoryType,
)

if TYPE_CHECKING:
    from pathlib import Path


@pytest.fixture(autouse=True)
def _reset_backend() -> None:
    reset_backend_cache_for_tests()


def _configuration() -> ProjectConfiguration:
    return ProjectConfiguration(
        repo_url="",
        default_branch="main",
        are_url=None,
        default_worker_count=1,
        repositories=["https://example.test/repo.git"],
    )


def _seed_project_with_stories(tmp_path: Path) -> tuple[
    StateBackendPlanningStoryRepository,
    StateBackendStoryDependencyRepository,
]:
    """Seed two stories via the canonical path (AG3-050).

    The ``story_dependencies`` FK references the STATIC ``stories``
    stammdaten (FK-02 §2.11.3), so the edge endpoints must exist there —
    they are created via ``StoryService.create_story``. NO ``story_contexts``
    runtime rows are created: execution planning now resolves story
    existence/identity from the static ``stories`` table (A1), so a
    dependency between two statically existing stories is valid without any
    runtime snapshot.
    """
    project_repository = StateBackendProjectRepository(tmp_path)
    project_repository.save(create_project(
        "tenant-a",
        "Tenant A",
        "AK3",
        _configuration(),
        repositories=["https://example.test/repo.git"],
    ))
    service = StoryService(
        story_repository=StateBackendStoryRepository(tmp_path),
        project_repository=project_repository,
        idempotency_guard=InMemoryInflightIdempotencyGuard(),
        event_emitter=lambda *_: None,
    )
    for idx, title in enumerate(("One", "Two"), start=1):
        service.create_story(
            CreateStoryInput(
                project_key="tenant-a",
                title=title,
                type=WireStoryType.IMPLEMENTATION,
                repos=["https://example.test/repo.git"],
            ),
            op_id=f"op-seed-{idx}",
        )
    return (
        StateBackendPlanningStoryRepository(tmp_path),
        StateBackendStoryDependencyRepository(tmp_path),
    )


def test_story_dependency_repository_roundtrip(tmp_path: Path) -> None:
    story_repository, dependency_repository = _seed_project_with_stories(tmp_path)

    edge = add_dependency(
        story_id="AK3-002",
        depends_on_story_id="AK3-001",
        kind=StoryDependencyKind.HARD_STORY_DEPENDENCY,
        project_key="tenant-a",
        story_repo=story_repository,
        dep_repo=dependency_repository,
    )

    assert dependency_repository.list_for_project("tenant-a") == [edge]
    assert dependency_repository.list_for_story("AK3-002") == [edge]
    with pytest.raises(StoryDependencyConflictError):
        dependency_repository.add(edge, project_key="tenant-a")
    dependency_repository.remove("AK3-002", "AK3-001", StoryDependencyKind.HARD_STORY_DEPENDENCY)
    assert dependency_repository.list_for_project("tenant-a") == []


def test_planning_repo_resolves_static_stories_without_runtime(tmp_path: Path) -> None:
    """A1: the planning read port resolves existence/identity from the static
    ``stories`` table. No ``story_contexts`` row exists, yet both stories are
    visible to planning and ``add_dependency`` between them succeeds.

    Before the A1 fix the planning repo read ``story_contexts`` and returned
    ``None`` for both endpoints, so this ``add_dependency`` raised
    ``StoryDependencyNotFoundError``.
    """
    story_repository, dependency_repository = _seed_project_with_stories(tmp_path)

    listed = story_repository.list_for_project("tenant-a")
    assert [ref.story_id for ref in listed] == ["AK3-001", "AK3-002"]
    # No runtime snapshot -> default lifecycle status, not a missing story.
    assert {ref.lifecycle_status for ref in listed} == {"defined"}

    ref = story_repository.get("tenant-a", "AK3-001")
    assert ref is not None
    assert ref.story_number == 1

    edge = add_dependency(
        story_id="AK3-002",
        depends_on_story_id="AK3-001",
        kind=StoryDependencyKind.HARD_STORY_DEPENDENCY,
        project_key="tenant-a",
        story_repo=story_repository,
        dep_repo=dependency_repository,
    )
    assert dependency_repository.list_for_project("tenant-a") == [edge]


def test_derive_lifecycle_status_prefers_runtime_when_present(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """A1: existence comes from the static stories table, but the derived
    ``lifecycle_status`` still refines from runtime (phase-state / metrics)
    when a run already exists; otherwise it defaults to ``"defined"``."""
    from types import SimpleNamespace

    from agentkit.backend.state_backend.store import planning_story_repository as psr

    # No runtime -> default.
    monkeypatch.setattr(psr, "load_phase_state_global", lambda *_a, **_k: None)
    monkeypatch.setattr(
        psr, "load_latest_story_metrics_global", lambda *_a, **_k: None
    )
    assert (
        psr._derive_lifecycle_status(
            project_key="tenant-a",
            story_display_id="AK3-001",
            store_dir=tmp_path,
        )
        == "defined"
    )

    # Phase-state present, no metrics -> phase status value.
    monkeypatch.setattr(
        psr,
        "load_phase_state_global",
        lambda *_a, **_k: SimpleNamespace(status=SimpleNamespace(value="in_progress")),
    )
    assert (
        psr._derive_lifecycle_status(
            project_key="tenant-a",
            story_display_id="AK3-001",
            store_dir=tmp_path,
        )
        == "in_progress"
    )

    # Final metrics win over phase-state and are lower-cased.
    monkeypatch.setattr(
        psr,
        "load_latest_story_metrics_global",
        lambda *_a, **_k: SimpleNamespace(final_status="PASS"),
    )
    assert (
        psr._derive_lifecycle_status(
            project_key="tenant-a",
            story_display_id="AK3-001",
            store_dir=tmp_path,
        )
        == "pass"
    )


def test_parallelization_config_repository_roundtrip(tmp_path: Path) -> None:
    project_repository = StateBackendProjectRepository(tmp_path)
    project_repository.save(create_project(
        "tenant-a",
        "Tenant A",
        "AK3",
        _configuration(),
        repositories=["https://example.test/repo.git"],
    ))
    repository = StateBackendParallelizationConfigRepository(tmp_path)
    config = ParallelizationConfig(
        project_key="tenant-a",
        max_parallel_stories=3,
        max_parallel_stories_per_repo=2,
    )

    repository.upsert(config)

    assert repository.get("tenant-a") == config
