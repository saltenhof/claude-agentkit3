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
import threading
from concurrent.futures import ThreadPoolExecutor
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


def test_state_backend_allocates_story_numbers_monotone_sequence(
    tmp_path: Path,
) -> None:
    """Sequential proof: the single canonical allocator (create_story_atomic
    behind StoryService.create_story) hands out a monotone, gap-free SEQUENCE.

    This test makes no race-safety claim; concurrent atomicity is proven
    separately by ``test_state_backend_concurrent_allocation_is_gap_free``.
    """
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


def test_state_backend_vectordb_conflict_flag_sqlite_roundtrip(
    tmp_path: Path,
) -> None:
    """AG3-068 (FK-21 §21.12): the ``vectordb_conflict_resolved`` producer flag
    round-trips through the REAL SQLite state-backend repository.

    The InMemory repo proves the service contract; this proves the SQLite
    persistence path (``_story_to_sqlite_row`` / ``_sqlite_row_to_story`` /
    the migrated column) faithfully writes and reads the flag — both True and
    the fail-closed False default.
    """
    facade.reset_backend_cache_for_tests()
    project_repository = StateBackendProjectRepository(tmp_path)
    project_repository.save(
        create_project(
            "tenant-a", "Tenant A", "AK3", _configuration(),
            repositories=["https://example.test/repo.git"],
        ),
    )
    service = _service(project_repository=project_repository, store_dir=tmp_path)

    service.create_story(
        CreateStoryInput(
            project_key="tenant-a",
            title="Conflict-resolved story",
            type=WireStoryType.IMPLEMENTATION,
            repos=["https://example.test/repo.git"],
            vectordb_conflict_resolved=True,
        ),
        op_id="op-flag-true",
    )
    service.create_story(
        CreateStoryInput(
            project_key="tenant-a",
            title="Plain story",
            type=WireStoryType.IMPLEMENTATION,
            repos=["https://example.test/repo.git"],
        ),
        op_id="op-flag-default",
    )

    # Read back through a FRESH SQLite repository instance (no in-memory cache).
    facade.reset_backend_cache_for_tests()
    reloaded = StateBackendStoryRepository(tmp_path)
    flagged = reloaded.get_by_display_id("AK3-001")
    plain = reloaded.get_by_display_id("AK3-002")
    assert flagged is not None and plain is not None
    assert flagged.vectordb_conflict_resolved is True
    assert plain.vectordb_conflict_resolved is False


def test_state_backend_concurrent_allocation_is_gap_free(tmp_path: Path) -> None:
    """C2: a REAL concurrent proof that ``create_story_atomic`` is race-safe.

    Many threads call ``StoryService.create_story`` against the same project at
    once. The SQLite path serialises the allocation transaction via
    ``BEGIN IMMEDIATE`` + WAL, so the allocated ``story_number`` set MUST be
    unique (no duplicate number), gap-free (a contiguous 1..N range), and the
    materialised display IDs MUST match the numbers one-to-one.

    Without transactional allocation, two threads could read the same counter
    value and produce duplicate numbers / a gap — this asserts that does not
    happen.
    """
    facade.reset_backend_cache_for_tests()
    project_repository = StateBackendProjectRepository(tmp_path)
    project_repository.save(
        create_project(
            "tenant-a", "Tenant A", "AK3", _configuration(),
            repositories=["https://example.test/repo.git"],
        ),
    )

    worker_count = 16

    # Provision the schema once up front (as production does at startup) so the
    # concurrent phase contends only on the BEGIN IMMEDIATE allocation
    # transaction — which honours busy_timeout — and not on autocommit
    # CREATE TABLE DDL (whose read->write upgrade ignores busy_timeout).
    StateBackendStoryRepository(tmp_path).list_for_project("tenant-a")

    def _allocate(i: int) -> Story:
        # Each thread uses its own service/repository instances against the
        # same on-disk SQLite database (real cross-connection concurrency).
        service = StoryService(
            story_repository=StateBackendStoryRepository(tmp_path),
            project_repository=project_repository,
            idempotency_repository=StateBackendIdempotencyKeyRepository(tmp_path),
            event_emitter=lambda *_: None,
        )
        return service.create_story(
            CreateStoryInput(
                project_key="tenant-a",
                title=f"Concurrent {i}",
                type=WireStoryType.IMPLEMENTATION,
                repos=["https://example.test/repo.git"],
            ),
            op_id=f"op-conc-{i}",
        )

    barrier = threading.Barrier(worker_count)

    def _run(i: int) -> Story:
        barrier.wait()  # maximise contention: release all threads together
        return _allocate(i)

    with ThreadPoolExecutor(max_workers=worker_count) as pool:
        results = list(pool.map(_run, range(worker_count)))

    numbers = sorted(story.story_number for story in results)
    assert numbers == list(range(1, worker_count + 1)), (
        "allocated numbers must be unique and gap-free under concurrency"
    )
    assert len(set(numbers)) == worker_count  # no duplicate number raced through
    for story in results:
        assert story.story_display_id == format_story_display_id(
            "AK3", story.story_number
        )

    # The persisted stammdaten agree with the allocation (atomic create).
    persisted = StateBackendStoryRepository(tmp_path).list_for_project("tenant-a")
    assert [s.story_number for s in persisted] == list(range(1, worker_count + 1))


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


def test_cross_project_dependency_edge_fails_closed(tmp_path: Path) -> None:
    """A3: the project-scoped composite FK rejects an edge whose endpoints
    belong to a DIFFERENT project than the edge's ``project_key``.

    Before the composite-FK fix the single-column FK only checked that the
    display IDs existed *somewhere*, so this cross-project edge was accepted.
    """
    facade.reset_backend_cache_for_tests()
    project_repository = StateBackendProjectRepository(tmp_path)
    project_repository.save(
        create_project(
            "tenant-a", "Tenant A", "AK3", _configuration(),
            repositories=["https://example.test/repo.git"],
        ),
    )
    project_repository.save(
        create_project(
            "tenant-b", "Tenant B", "BB2", _configuration(),
            repositories=["https://example.test/repo.git"],
        ),
    )
    service = _service(project_repository=project_repository, store_dir=tmp_path)
    a = _create(service, title="A", op_id="op-a", project_key="tenant-a")
    b = _create(service, title="B", op_id="op-b", project_key="tenant-b")
    assert a.story_display_id == "AK3-001"
    assert b.story_display_id == "BB2-001"

    dep_repo = StateBackendStoryDependencyRepository(tmp_path)
    # Edge under tenant-a: the dependent endpoint (AK3-001) is in tenant-a, but
    # the predecessor (BB2-001) lives in tenant-b. The composite FK
    # (project_key, depends_on_story_id) -> stories(project_key,
    # story_display_id) has no (tenant-a, BB2-001) row, so it fails closed.
    with pytest.raises(sqlite3.IntegrityError):
        dep_repo.add(
            StoryDependency(
                story_id=a.story_display_id,
                depends_on_story_id=b.story_display_id,
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
