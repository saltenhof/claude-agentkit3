from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest

from agentkit.backend.project_management.entities import ProjectConfiguration
from agentkit.backend.project_management.errors import ProjectStoryIdPrefixConflictError
from agentkit.backend.project_management.lifecycle import archive_project, create_project
from agentkit.backend.state_backend.store import facade
from agentkit.backend.state_backend.store.project_management_repository import (
    StateBackendProjectRepository,
)

if TYPE_CHECKING:
    from pathlib import Path


def _configuration() -> ProjectConfiguration:
    return ProjectConfiguration(
        repo_url="",
        default_branch="main",
        are_url=None,
        default_worker_count=2,
        repositories=["https://example.test/repo.git"],
    )


@pytest.fixture(autouse=True)
def _reset_backend() -> None:
    facade.reset_backend_cache_for_tests()


def test_repository_saves_gets_and_lists_projects(tmp_path: Path) -> None:
    repository = StateBackendProjectRepository(tmp_path)
    project = create_project("tenant-a", "Tenant A", "AG3", _configuration(), repositories=["https://example.test/repo.git"])

    repository.save(project)

    assert repository.get("tenant-a") == project
    assert repository.list() == [project]


def test_repository_excludes_archived_projects_by_default(tmp_path: Path) -> None:
    repository = StateBackendProjectRepository(tmp_path)
    project = create_project("tenant-a", "Tenant A", "AG3", _configuration(), repositories=["https://example.test/repo.git"])
    archived = archive_project(
        project,
        archived_at=datetime(2026, 5, 3, 10, 0, tzinfo=UTC),
    )

    repository.save(archived)

    assert repository.list() == []
    assert repository.list(include_archived=True) == [archived]


def test_repository_rejects_duplicate_story_id_prefix(tmp_path: Path) -> None:
    repository = StateBackendProjectRepository(tmp_path)
    repository.save(create_project("tenant-a", "Tenant A", "AG3", _configuration(), repositories=["https://example.test/repo.git"]))

    with pytest.raises(ProjectStoryIdPrefixConflictError):
        repository.save(create_project("tenant-b", "Tenant B", "AG3", _configuration(), repositories=["https://example.test/repo.git"]))


# ---------------------------------------------------------------------------
# AG3-020: JSON migration loader (old records without 'repositories' field)
# ---------------------------------------------------------------------------


def test_repository_roundtrip_includes_repositories(tmp_path: Path) -> None:
    """Saving a project with repositories and reading it back preserves the list."""
    from agentkit.backend.project_management.entities import ProjectConfiguration

    config = ProjectConfiguration(
        repo_url="",
        default_branch="main",
        are_url=None,
        default_worker_count=1,
        repositories=["repo-a", "repo-b"],
    )
    repository = StateBackendProjectRepository(tmp_path)
    project = create_project(
        "p1",
        "Project 1",
        "P1",
        config,
        repositories=["repo-a", "repo-b"],
    )
    repository.save(project)

    loaded = repository.get("p1")
    assert loaded is not None
    assert loaded.configuration.repositories == ["repo-a", "repo-b"]


def test_repository_reads_old_record_without_repositories_field(tmp_path: Path) -> None:
    """Old DB records without 'repositories' key are backfilled from repo_url without crashing."""
    import json
    import sqlite3

    from agentkit.backend.state_backend import sqlite_store
    from agentkit.backend.state_backend.store import facade

    # Write an old-style record directly into the DB, bypassing the ORM.
    db_path = sqlite_store.state_db_path_for(tmp_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    sqlite_store._ensure_schema(conn)
    old_config = json.dumps(
        {
            "repo_url": "https://example.test/legacy.git",
            "default_branch": "main",
            "are_url": None,
            "default_worker_count": 1,
            # 'repositories' intentionally absent — simulates old DB row
        }
    )
    conn.execute(
        """
        INSERT INTO projects (key, name, story_id_prefix, configuration_json, archived_at)
        VALUES (?, ?, ?, ?, NULL)
        """,
        ("legacy-proj", "Legacy Project", "LEG", old_config),
    )
    conn.commit()
    conn.close()

    facade.reset_backend_cache_for_tests()
    repository = StateBackendProjectRepository(tmp_path)
    project = repository.get("legacy-proj")

    assert project is not None
    # Backfill derives repos from repo_url
    assert project.configuration.repositories == ["https://example.test/legacy.git"]
