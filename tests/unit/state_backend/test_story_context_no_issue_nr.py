"""AG3-120 AC4: story_contexts persistence carries no ``issue_nr`` (real SQLite).

AK3 owns the user story via ``story_id``; GitHub is only the code backend
(FK-12 §12.1.1, FK-91 §91.2 rule 9). The GitHub-issue-derived story key is
fully removed from the runtime projection — the ``story_contexts`` table has no
``issue_nr`` column, the persisted ``context.json`` projection has no
``issue_nr`` key, and the round-tripped ``StoryContext`` model has no such
attribute. Exercised against a REAL SQLite state-backend (no fake repo).
"""

from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest

from agentkit.backend.state_backend.config import ALLOW_SQLITE_ENV, STATE_BACKEND_ENV
from agentkit.backend.state_backend.paths import CONTEXT_EXPORT_FILE
from agentkit.backend.state_backend.persistence_test_support import reset_backend_cache_for_tests
from agentkit.backend.state_backend.story_lifecycle_store import (
    load_story_context,
    save_story_context,
)
from agentkit.backend.story_context_manager.models import StoryContext
from agentkit.backend.story_context_manager.types import StoryMode, StoryType

if TYPE_CHECKING:
    from collections.abc import Generator
    from pathlib import Path


@pytest.fixture(autouse=True)
def sqlite_backend_env(monkeypatch: pytest.MonkeyPatch) -> Generator[None, None, None]:
    monkeypatch.setenv(STATE_BACKEND_ENV, "sqlite")
    monkeypatch.setenv(ALLOW_SQLITE_ENV, "1")
    monkeypatch.delenv("AGENTKIT_STATE_DATABASE_URL", raising=False)
    reset_backend_cache_for_tests()
    yield
    reset_backend_cache_for_tests()


def _save_round_trip(tmp_path: Path) -> tuple[Path, StoryContext]:
    project_root = tmp_path / "demo-project"
    story_dir = project_root / "stories" / "AG3-120"
    story_dir.mkdir(parents=True, exist_ok=True)
    ctx = StoryContext(
        project_key="demo-project",
        story_id="AG3-120",
        story_type=StoryType.IMPLEMENTATION,
        execution_route=StoryMode.EXECUTION,
        title="issue_nr removal round-trip",
        project_root=project_root,
        created_at=datetime.now(tz=UTC),
    )
    save_story_context(story_dir, ctx)
    loaded = load_story_context(story_dir)
    assert loaded is not None
    return story_dir, loaded


def test_round_tripped_context_has_no_issue_nr(tmp_path: Path) -> None:
    """A real SQLite save/load yields a StoryContext without an issue_nr attribute."""
    _story_dir, loaded = _save_round_trip(tmp_path)
    assert loaded.story_id == "AG3-120"
    assert not hasattr(loaded, "issue_nr")


def test_projection_json_has_no_issue_nr_key(tmp_path: Path) -> None:
    """The persisted context.json projection carries no ``issue_nr`` key."""
    story_dir, _loaded = _save_round_trip(tmp_path)
    projection = json.loads((story_dir / CONTEXT_EXPORT_FILE).read_text(encoding="utf-8"))
    assert "issue_nr" not in projection


def test_story_contexts_table_has_no_issue_nr_column(tmp_path: Path) -> None:
    """The real SQLite ``story_contexts`` DDL has no ``issue_nr`` column."""
    story_dir, _loaded = _save_round_trip(tmp_path)
    db_files = list(story_dir.rglob("*.sqlite"))
    assert db_files, "no SQLite database file was created by the real backend"
    columns: set[str] = set()
    for db_file in db_files:
        conn = sqlite3.connect(db_file)
        try:
            rows = conn.execute("PRAGMA table_info(story_contexts)").fetchall()
        finally:
            conn.close()
        columns.update(row[1] for row in rows)
    assert "story_id" in columns, "expected the story_contexts table to exist"
    assert "issue_nr" not in columns
