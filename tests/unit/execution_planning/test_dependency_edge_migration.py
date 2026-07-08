"""dependency_edge write-path migration tests (AC5).

AC5: all planning writes flow through the BC-9 planning projection write path; a
test proves the direct state_backend repo write path for planning is no longer
used (also for ``dependency_edge``). The migrated
``PlanningWritePathStoryDependencyRepository`` routes ``add``/``remove``/``list``
through ``PlanningProjectionAccessor`` and the ``dependency_edge`` planning table.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest

from agentkit.backend.bootstrap.composition_root import (
    build_planning_projection_accessor,
    build_planning_story_dependency_repository,
)
from agentkit.backend.core_types import StoryDependencyKind
from agentkit.backend.execution_planning.entities import PlannedStory, StoryDependency
from agentkit.backend.execution_planning.errors import (
    StoryDependencyConflictError,
    StoryDependencyNotFoundError,
)
from agentkit.backend.execution_planning.lifecycle import add_dependency
from agentkit.backend.execution_planning.persistence.errors import (
    PlanningProjectionDeleteNotSupportedError,
)
from agentkit.backend.execution_planning.persistence.filter import (
    DependencyEdgeDeleteKey,
    PlanningProjectionFilter,
)
from agentkit.backend.execution_planning.persistence.schema_kind import PlanningSchemaKind
from agentkit.backend.state_backend.config import ALLOW_SQLITE_ENV, STATE_BACKEND_ENV
from agentkit.backend.state_backend.persistence_test_support import reset_backend_cache_for_tests

if TYPE_CHECKING:
    from collections.abc import Generator
    from pathlib import Path

_PROJECT = "PROJ-MIG"


@pytest.fixture(autouse=True)
def sqlite_env(monkeypatch: pytest.MonkeyPatch) -> Generator[None, None, None]:
    monkeypatch.setenv(STATE_BACKEND_ENV, "sqlite")
    monkeypatch.setenv(ALLOW_SQLITE_ENV, "1")
    reset_backend_cache_for_tests()
    yield
    reset_backend_cache_for_tests()


@pytest.fixture()
def story_dir(tmp_path: Path) -> Path:
    path = tmp_path / "stories" / "AG3-099"
    path.mkdir(parents=True, exist_ok=True)
    return path


class _StubStoryRepo:
    """Minimal planning-story reader for ``add_dependency`` (no DB needed)."""

    def __init__(self) -> None:
        self._stories = {
            "S1": PlannedStory(
                project_key=_PROJECT, story_id="S1", story_number=1, title="S1",
                lifecycle_status="approved",
            ),
            "S2": PlannedStory(
                project_key=_PROJECT, story_id="S2", story_number=2, title="S2",
                lifecycle_status="approved",
            ),
        }

    def get(self, project_key: str, story_id: str) -> PlannedStory | None:
        return self._stories.get(story_id)

    def list_for_project(self, project_key: str) -> list[PlannedStory]:
        return list(self._stories.values())


def test_add_dependency_routes_through_planning_table(story_dir: Path) -> None:
    """``add_dependency`` persists the edge in the planning dependency_edge table."""
    dep_repo = build_planning_story_dependency_repository(story_dir)
    add_dependency(
        story_id="S2",
        depends_on_story_id="S1",
        kind=StoryDependencyKind.HARD_STORY_DEPENDENCY,
        project_key=_PROJECT,
        story_repo=_StubStoryRepo(),
        dep_repo=dep_repo,
    )
    accessor = build_planning_projection_accessor(story_dir)
    edges = accessor.read_projection(
        PlanningSchemaKind.DEPENDENCY_EDGE,
        PlanningProjectionFilter(project_key=_PROJECT),
    )
    assert len(edges) == 1
    assert edges[0].story_id == "S2"  # type: ignore[attr-defined]
    assert edges[0].depends_on_story_id == "S1"  # type: ignore[attr-defined]


def test_no_direct_state_backend_dependency_write(story_dir: Path) -> None:
    """The legacy direct ``story_dependencies`` table is NOT written for planning.

    The planning write path uses ``planning_dependency_edge``; the legacy direct
    facade table ``story_dependencies`` stays empty (no double write-truth).
    """
    import sqlite3

    from agentkit.backend.state_backend.config import versioned_sqlite_db_file
    from agentkit.backend.state_backend.paths import state_backend_dir

    dep_repo = build_planning_story_dependency_repository(story_dir)
    dep_repo.add(
        StoryDependency(
            story_id="S2",
            depends_on_story_id="S1",
            kind=StoryDependencyKind.HARD_STORY_DEPENDENCY,
            created_at=datetime.now(UTC),
        ),
        project_key=_PROJECT,
    )

    db_path = state_backend_dir(story_dir) / versioned_sqlite_db_file()
    conn = sqlite3.connect(str(db_path))
    try:
        planning_rows = conn.execute(
            "SELECT COUNT(*) FROM planning_dependency_edge"
        ).fetchone()[0]
        legacy_exists = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' "
            "AND name='story_dependencies'"
        ).fetchone()
        legacy_rows = (
            conn.execute("SELECT COUNT(*) FROM story_dependencies").fetchone()[0]
            if legacy_exists
            else 0
        )
    finally:
        conn.close()

    assert planning_rows == 1, "edge must be in the planning projection table"
    assert legacy_rows == 0, "no edge in the legacy direct state_backend table"


def test_list_and_remove_through_planning_path(story_dir: Path) -> None:
    """``list_for_project``/``list_for_story``/``remove`` use the planning path."""
    dep_repo = build_planning_story_dependency_repository(story_dir)
    edge = StoryDependency(
        story_id="S2",
        depends_on_story_id="S1",
        kind=StoryDependencyKind.HARD_STORY_DEPENDENCY,
        created_at=datetime.now(UTC),
    )
    dep_repo.add(edge, project_key=_PROJECT)

    assert len(dep_repo.list_for_project(_PROJECT)) == 1
    assert len(dep_repo.list_for_story("S2")) == 1

    with pytest.raises(StoryDependencyConflictError):
        dep_repo.add(edge, project_key=_PROJECT)

    dep_repo.remove("S2", "S1", StoryDependencyKind.HARD_STORY_DEPENDENCY)
    assert dep_repo.list_for_project(_PROJECT) == []

    with pytest.raises(StoryDependencyNotFoundError):
        dep_repo.remove("S2", "S1", StoryDependencyKind.HARD_STORY_DEPENDENCY)


def test_remove_routes_delete_through_accessor_top_surface(story_dir: Path) -> None:
    """AC5: ``remove`` routes the delete through ``delete_projection``.

    FIX THE MODEL: the delete must cross the SINGLE planning write boundary
    (``PlanningProjectionAccessor.delete_projection``), not the concrete edge
    adapter. We spy the accessor's ``delete_projection`` to prove the boundary is
    used and that no row survives.
    """
    accessor = build_planning_projection_accessor(story_dir)
    from agentkit.backend.state_backend.store.planning_projection_repository import (
        StateBackendDependencyEdgeProjectionRepository,
    )
    from agentkit.backend.state_backend.store.planning_story_dependency_repository import (
        PlanningWritePathStoryDependencyRepository,
    )

    edge_repo = StateBackendDependencyEdgeProjectionRepository(story_dir)
    dep_repo = PlanningWritePathStoryDependencyRepository(
        accessor=accessor, edge_repo=edge_repo
    )
    dep_repo.add(
        StoryDependency(
            story_id="S2",
            depends_on_story_id="S1",
            kind=StoryDependencyKind.HARD_STORY_DEPENDENCY,
            created_at=datetime.now(UTC),
        ),
        project_key=_PROJECT,
    )

    seen: list[DependencyEdgeDeleteKey] = []
    real_delete = accessor.delete_projection

    def _spy(kind: PlanningSchemaKind, key: DependencyEdgeDeleteKey) -> int:
        seen.append(key)
        return real_delete(kind, key)

    accessor.delete_projection = _spy  # type: ignore[method-assign]
    dep_repo.remove("S2", "S1", StoryDependencyKind.HARD_STORY_DEPENDENCY)

    assert len(seen) == 1
    assert seen[0].story_id == "S2"
    assert seen[0].depends_on_story_id == "S1"
    assert dep_repo.list_for_project(_PROJECT) == []


def test_delete_projection_fail_closed_for_unsupported_family(
    story_dir: Path,
) -> None:
    """``delete_projection`` fails closed for a family without delete semantics."""
    accessor = build_planning_projection_accessor(story_dir)
    with pytest.raises(PlanningProjectionDeleteNotSupportedError):
        accessor.delete_projection(
            PlanningSchemaKind.PLANNED_STORY,
            DependencyEdgeDeleteKey(
                project_key=_PROJECT,
                story_id="S1",
                depends_on_story_id="S0",
                kind="hard_story_dependency",
            ),
        )


def test_remove_fail_closed_on_zero_row_delete_after_resolution(
    story_dir: Path,
) -> None:
    """``remove`` fails closed if the edge resolves but the delete removes 0 rows.

    Defensive FAIL-CLOSED guard: ``remove`` first resolves the edge's project_key
    via ``read_for_story`` (the edge IS present), then routes the delete through
    ``delete_projection``. If that delete reports 0 removed rows -- a read/delete
    inconsistency (e.g. a concurrent removal) -- ``remove`` must raise
    ``StoryDependencyNotFoundError`` rather than silently succeed. We force the
    inconsistency by intercepting the accessor's ``delete_projection`` to return 0
    AFTER a real edge has been written, leaving the resolving read intact.
    """
    accessor = build_planning_projection_accessor(story_dir)
    from agentkit.backend.state_backend.store.planning_projection_repository import (
        StateBackendDependencyEdgeProjectionRepository,
    )
    from agentkit.backend.state_backend.store.planning_story_dependency_repository import (
        PlanningWritePathStoryDependencyRepository,
    )

    edge_repo = StateBackendDependencyEdgeProjectionRepository(story_dir)
    dep_repo = PlanningWritePathStoryDependencyRepository(
        accessor=accessor, edge_repo=edge_repo
    )
    dep_repo.add(
        StoryDependency(
            story_id="S2",
            depends_on_story_id="S1",
            kind=StoryDependencyKind.HARD_STORY_DEPENDENCY,
            created_at=datetime.now(UTC),
        ),
        project_key=_PROJECT,
    )

    # Simulate a concurrent delete: the resolving read still sees the edge, but
    # the boundary delete reports 0 rows removed.
    accessor.delete_projection = lambda *_a, **_k: 0  # type: ignore[method-assign]
    with pytest.raises(StoryDependencyNotFoundError):
        dep_repo.remove("S2", "S1", StoryDependencyKind.HARD_STORY_DEPENDENCY)


def test_write_projection_fail_closed_for_unmapped_kind(
    story_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``write_projection`` fails closed when a kind has no registered record type.

    Defensive FAIL-CLOSED guard (FK-70 §70.10.2): an unmapped planning kind is a
    wiring defect, not a silent no-op. We force the kind->record-type registry to
    drop ``PLANNED_STORY`` so the accessor's unknown-kind guard fires for a
    well-formed record, proving ``PlanningSchemaKindUnknownError`` is raised
    instead of a silent miss.
    """
    from agentkit.backend.execution_planning.persistence import accessor as accessor_module
    from agentkit.backend.execution_planning.persistence.errors import (
        PlanningSchemaKindUnknownError,
    )
    from agentkit.backend.execution_planning.persistence.records import PlannedStoryRecord

    real_map = accessor_module.planning_kind_to_record_type()
    crippled = {
        kind: rec
        for kind, rec in real_map.items()
        if kind is not PlanningSchemaKind.PLANNED_STORY
    }
    monkeypatch.setattr(
        accessor_module, "planning_kind_to_record_type", lambda: crippled
    )

    accessor = build_planning_projection_accessor(story_dir)
    record = PlannedStoryRecord(
        project_key=_PROJECT, story_id="S1", planning_status="UNSTARTED", revision=1
    )
    with pytest.raises(PlanningSchemaKindUnknownError):
        accessor.write_projection(PlanningSchemaKind.PLANNED_STORY, record)
