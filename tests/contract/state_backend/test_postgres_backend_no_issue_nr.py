"""AG3-120 AC4: story_contexts carries no ``issue_nr`` on REAL Postgres.

AK3 owns the user story via ``story_id``; GitHub is only the code backend
(FK-12 §12.1.1, FK-91 §91.2 rule 9). The GitHub-issue-derived story key is fully
removed from the relational projection (FK-18 §18.9a). This contract test runs
against a REAL Postgres backend (no fake repo) and proves:

* the ``story_contexts`` table has NO ``issue_nr`` column
  (``information_schema.columns`` query), and
* a ``StoryContext`` round-trips (save -> load -> upsert -> read-model) with no
  ``issue_nr`` attribute on the model and no ``issue_nr`` key in the read-model.

The SQLite analogue lives in
``tests/unit/state_backend/test_story_context_no_issue_nr.py``; this is the
matching Postgres proof required by AC4 ("echtes SQLite UND echtes Postgres").
"""

from __future__ import annotations

import os
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import psycopg
import pytest

from agentkit.backend.state_backend.config import SCHEMA_OVERRIDE_ENV
from agentkit.backend.state_backend.store import (
    load_story_context,
    load_story_context_global,
    save_story_context,
)
from agentkit.backend.story_context_manager.models import StoryContext
from agentkit.backend.story_context_manager.types import StoryMode, StoryType

if TYPE_CHECKING:
    from pathlib import Path

pytest_plugins = ("tests.fixtures.postgres_backend",)


@pytest.mark.contract
def test_story_contexts_table_has_no_issue_nr_column_on_postgres(
    tmp_path: Path,
    postgres_backend_env: str,
) -> None:
    """The real Postgres ``story_contexts`` DDL exposes no ``issue_nr`` column."""
    url = postgres_backend_env
    schema = os.environ[SCHEMA_OVERRIDE_ENV]

    with psycopg.connect(url) as conn:
        rows = conn.execute(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_schema = %s AND table_name = 'story_contexts'",
            (schema,),
        ).fetchall()

    columns = {str(row[0]) for row in rows}
    assert "story_id" in columns, "expected the story_contexts table to exist"
    assert "issue_nr" not in columns


@pytest.mark.contract
def test_story_context_round_trips_without_issue_nr_on_postgres(
    tmp_path: Path,
    postgres_backend_env: str,
) -> None:
    """save -> load -> upsert -> read-model round-trip with no ``issue_nr``."""
    project_root = tmp_path / "demo-project"
    story_dir = project_root / "stories" / "AG3-120"
    story_dir.mkdir(parents=True, exist_ok=True)

    ctx = StoryContext(
        project_key="demo-project",
        story_id="AG3-120",
        story_type=StoryType.IMPLEMENTATION,
        execution_route=StoryMode.EXECUTION,
        title="issue_nr removal round-trip (postgres)",
        project_root=project_root,
        created_at=datetime.now(tz=UTC),
    )

    # save -> load
    save_story_context(story_dir, ctx)
    loaded = load_story_context(story_dir)
    assert loaded is not None
    assert loaded.story_id == "AG3-120"
    assert not hasattr(loaded, "issue_nr")

    # upsert (save again with a mutated title) -> the row is updated, not doubled
    upserted = ctx.model_copy(update={"title": "upserted title"})
    save_story_context(story_dir, upserted)

    # read-model (global projection) reflects the upsert and carries no issue_nr
    read_model = load_story_context_global("demo-project", "AG3-120")
    assert read_model is not None
    assert read_model.story_id == "AG3-120"
    assert read_model.title == "upserted title"
    assert not hasattr(read_model, "issue_nr")
