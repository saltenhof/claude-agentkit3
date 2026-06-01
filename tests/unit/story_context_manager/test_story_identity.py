"""Story-identity unification tests (AG3-050).

Covers the canonical single-source identity/allocation path
(``StoryService.create_story`` -> ``StoryRepository.create_story_atomic``,
FK-02 §2.11.2 / FK-91 §91.1a), the single display-ID formatter (FK-02
§2.11.2), numeric ordering by ``story_number`` (no lexicographic display-ID
sort), and the StoryDependency foreign key onto the STATIC ``stories``
stammdaten (FK-02 §2.11.3, FK-18 §18.6a).
"""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from pathlib import Path

import pytest

from agentkit.execution_planning.entities import (
    StoryDependency,
    StoryDependencyKind,
)
from agentkit.project_management.entities import Project, ProjectConfiguration
from agentkit.project_management.lifecycle import archive_project, create_project
from agentkit.state_backend.store import facade
from agentkit.state_backend.store.project_management_repository import (
    StateBackendProjectRepository,
)
from agentkit.state_backend.store.story_dependency_repository import (
    StateBackendStoryDependencyRepository,
)
from agentkit.state_backend.store.story_repository import (
    StateBackendIdempotencyKeyRepository,
    StateBackendStoryRepository,
)
from agentkit.story_context_manager.display_id import (
    format_story_display_id,
)
from agentkit.story_context_manager.errors import (
    ForbiddenError,
    StoryProjectNotFoundError,
)
from agentkit.story_context_manager.service import StoryService
from agentkit.story_context_manager.story_model import (
    CreateStoryInput,
    Story,
    WireStoryType,
)
from agentkit.story_context_manager.story_repository import InMemoryStoryRepository


def _configuration() -> ProjectConfiguration:
    return ProjectConfiguration(
        repo_url="",
        default_branch="main",
        are_url=None,
        default_worker_count=1,
        repositories=["https://example.test/repo.git"],
    )


class _ProjectRepository:
    def __init__(self) -> None:
        self.projects: dict[str, Project] = {
            "tenant-a": create_project(
                "tenant-a",
                "Tenant A",
                "AK3",
                _configuration(),
                repositories=["https://example.test/repo.git"],
            ),
        }

    def get(self, key: str) -> Project | None:
        return self.projects.get(key)

    def list(self, *, include_archived: bool = False) -> list[Project]:
        return list(self.projects.values())

    def save(self, project: Project) -> None:
        self.projects[project.key] = project


def _service(
    *,
    project_repository: _ProjectRepository,
    store_dir: Path | None = None,
    in_memory: bool = False,
) -> StoryService:
    if in_memory:
        from agentkit.story_context_manager.idempotency import (
            InMemoryIdempotencyKeyRepository,
        )

        return StoryService(
            story_repository=InMemoryStoryRepository(),
            project_repository=project_repository,
            idempotency_repository=InMemoryIdempotencyKeyRepository(),
            event_emitter=lambda *_: None,
        )
    assert store_dir is not None
    return StoryService(
        story_repository=StateBackendStoryRepository(store_dir),
        project_repository=project_repository,
        idempotency_repository=StateBackendIdempotencyKeyRepository(store_dir),
        event_emitter=lambda *_: None,
    )


def _create(
    service: StoryService,
    *,
    title: str,
    op_id: str,
    project_key: str = "tenant-a",
) -> Story:
    return service.create_story(
        CreateStoryInput(
            project_key=project_key,
            title=title,
            type=WireStoryType.IMPLEMENTATION,
            repos=["https://example.test/repo.git"],
        ),
        op_id=op_id,
    )


# ---------------------------------------------------------------------------
# B — single display-ID formatter (FK-02 §2.11.2)
# ---------------------------------------------------------------------------


def test_format_story_display_id_pads_to_min_width_three() -> None:
    assert format_story_display_id("AK3", 42) == "AK3-042"
    assert format_story_display_id("BB2", 1) == "BB2-001"


def test_format_story_display_id_grows_beyond_three_digits() -> None:
    # Min-width, not max-width: >= 1000 renders wider.
    assert format_story_display_id("AK3", 1000) == "AK3-1000"
    assert format_story_display_id("AK3", 12345) == "AK3-12345"


def test_format_story_display_id_rejects_unallocated_number() -> None:
    with pytest.raises(ValueError, match="story_number must be >= 1"):
        format_story_display_id("AK3", 0)


def test_canonical_create_story_uses_padded_formatter() -> None:
    project_repository = _ProjectRepository()
    service = _service(project_repository=project_repository, in_memory=True)

    first = _create(service, title="First", op_id="op-1")
    second = _create(service, title="Second", op_id="op-2")

    assert first.story_number == 1
    assert second.story_number == 2
    assert first.story_display_id == "AK3-001"
    assert second.story_display_id == "AK3-002"
    assert first.story_display_id == format_story_display_id(
        "AK3", first.story_number
    )


# ---------------------------------------------------------------------------
# B — numeric ordering by story_number (no lexicographic display-ID sort)
# ---------------------------------------------------------------------------


def test_list_for_project_orders_numerically_across_1000_boundary() -> None:
    """A lexicographic display-ID sort would put AK3-1000 before AK3-999."""
    repo = InMemoryStoryRepository()
    spec_numbers = [9, 10, 999, 1000, 1001, 1, 2000]
    for number in spec_numbers:
        repo.save(
            Story(
                project_key="tenant-a",
                story_number=number,
                story_display_id=format_story_display_id("AK3", number),
                title=f"Story {number}",
                story_type=WireStoryType.IMPLEMENTATION,
                participating_repos=["repo-a"],
                created_at=datetime.now(UTC),
            ),
        )

    ordered = repo.list_for_project("tenant-a")
    numbers = [story.story_number for story in ordered]

    assert numbers == sorted(spec_numbers)
    # Explicit proof the lexicographic bug is absent: 999 precedes 1000.
    display_ids = [story.story_display_id for story in ordered]
    assert display_ids.index("AK3-999") < display_ids.index("AK3-1000")


# ---------------------------------------------------------------------------
# C — canonical create + atomic allocation through the single repository
# ---------------------------------------------------------------------------


def test_create_story_rejects_archived_project() -> None:
    project_repository = _ProjectRepository()
    project_repository.projects["tenant-a"] = archive_project(
        project_repository.projects["tenant-a"],
        archived_at=datetime(2026, 5, 3, tzinfo=UTC),
    )
    service = _service(project_repository=project_repository, in_memory=True)

    with pytest.raises(ForbiddenError):
        _create(service, title="X", op_id="op-archived")


def test_create_story_rejects_missing_project() -> None:
    service = _service(project_repository=_ProjectRepository(), in_memory=True)

    with pytest.raises(StoryProjectNotFoundError):
        _create(service, title="X", op_id="op-missing", project_key="missing")


def test_state_backend_allocates_story_numbers_monotone(tmp_path: Path) -> None:
    """The single canonical allocator (create_story_atomic behind
    StoryService.create_story) hands out monotone, gap-free numbers."""
    facade.reset_backend_cache_for_tests()
    project_repository = StateBackendProjectRepository(tmp_path)
    project_repository.save(
        create_project(
            "tenant-a", "Tenant A", "AK3", _configuration(),
            repositories=["https://example.test/repo.git"],
        ),
    )
    service = _service(project_repository=project_repository, store_dir=tmp_path)

    created = [
        _create(service, title=f"Story {i}", op_id=f"op-mono-{i}")
        for i in range(1, 7)
    ]

    assert [story.story_number for story in created] == [1, 2, 3, 4, 5, 6]
    assert [story.story_display_id for story in created] == [
        "AK3-001", "AK3-002", "AK3-003", "AK3-004", "AK3-005", "AK3-006",
    ]


# ---------------------------------------------------------------------------
# A — StoryDependency FK targets the STATIC `stories` stammdaten, fail-closed
# ---------------------------------------------------------------------------


def _seed_two_stories(tmp_path: Path) -> tuple[str, str]:
    facade.reset_backend_cache_for_tests()
    project_repository = StateBackendProjectRepository(tmp_path)
    project_repository.save(
        create_project(
            "tenant-a", "Tenant A", "AK3", _configuration(),
            repositories=["https://example.test/repo.git"],
        ),
    )
    service = _service(project_repository=project_repository, store_dir=tmp_path)
    a = _create(service, title="A", op_id="op-a")
    b = _create(service, title="B", op_id="op-b")
    return a.story_display_id, b.story_display_id


def test_dependency_attaches_to_stories_stammdaten(tmp_path: Path) -> None:
    """The edge is valid once both endpoints exist in `stories` — no
    story_contexts row was created by the canonical path."""
    a_id, b_id = _seed_two_stories(tmp_path)
    dep_repo = StateBackendStoryDependencyRepository(tmp_path)
    edge = StoryDependency(
        story_id=b_id,
        depends_on_story_id=a_id,
        kind=StoryDependencyKind.HARD_STORY_DEPENDENCY,
        created_at=datetime.now(UTC),
    )

    dep_repo.add(edge, project_key="tenant-a")

    assert dep_repo.list_for_project("tenant-a") == [edge]


def test_dependency_on_unknown_story_fails_closed(tmp_path: Path) -> None:
    """FK violation: a dependency onto a story that is not in `stories`
    must be rejected at the database layer (fail-closed)."""
    a_id, _b_id = _seed_two_stories(tmp_path)
    dep_repo = StateBackendStoryDependencyRepository(tmp_path)

    with pytest.raises(sqlite3.IntegrityError):
        dep_repo.add(
            StoryDependency(
                story_id=a_id,
                depends_on_story_id="AK3-999",  # never created in `stories`
                kind=StoryDependencyKind.HARD_STORY_DEPENDENCY,
                created_at=datetime.now(UTC),
            ),
            project_key="tenant-a",
        )


# ---------------------------------------------------------------------------
# C — audit: the dead lifecycle.create_story path is gone
# ---------------------------------------------------------------------------


def test_lifecycle_create_story_module_removed() -> None:
    """ZERO DEBT: the duplicate padded allocator path is deleted, not
    deprecated (AG3-050 / FK-02 §2.11.2)."""
    assert not (
        Path(__file__).parents[3]
        / "src"
        / "agentkit"
        / "story_context_manager"
        / "lifecycle.py"
    ).exists()

    with pytest.raises(ImportError):
        __import__("agentkit.story_context_manager.lifecycle")
