"""Integration: per-test Postgres schema isolation (AG3-051 §2.1.7, AK6).

Two tests write the SAME fixed story id into the SAME table. Before AG3-051 the
shared versioned schema accumulated rows across tests and the second insert
collided on ``UNIQUE(project_key, story_id)``. The per-test
``postgres_isolated_schema`` fixture (attached by the integration conftest)
TRUNCATEs the worker test schema around each test, so both writes are fresh and
both tests pass regardless of execution order.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from agentkit.backend.state_backend.store import (
    load_story_context_global,
    load_story_contexts_global,
    save_story_context,
)
from agentkit.backend.story_context_manager.models import StoryContext
from agentkit.backend.story_context_manager.types import StoryMode, StoryType

if TYPE_CHECKING:
    from pathlib import Path

_FIXED_PROJECT = "isolation-project"
_FIXED_STORY = "TEST-001"


def _write_fixed_story(tmp_path: Path) -> None:
    project_root = tmp_path / _FIXED_PROJECT
    story_dir = project_root / "stories" / _FIXED_STORY
    story_dir.mkdir(parents=True, exist_ok=True)
    ctx = StoryContext(
        project_key=_FIXED_PROJECT,
        story_id=_FIXED_STORY,
        story_type=StoryType.IMPLEMENTATION,
        execution_route=StoryMode.EXECUTION,
        title="Schema isolation probe",
        project_root=project_root,
    )
    save_story_context(story_dir, ctx)

    assert load_story_context_global(_FIXED_PROJECT, _FIXED_STORY) is not None
    rows = load_story_contexts_global(_FIXED_PROJECT)
    # Per-test TRUNCATE guarantees exactly one row — no accrual from sibling tests.
    assert len(rows) == 1
    assert rows[0].story_id == _FIXED_STORY


@pytest.mark.integration
def test_first_writer_of_fixed_id(tmp_path: Path) -> None:
    """First test writes ``TEST-001`` into the isolated schema."""
    _write_fixed_story(tmp_path)


@pytest.mark.integration
def test_second_writer_of_same_fixed_id(tmp_path: Path) -> None:
    """Second test writes the SAME ``TEST-001`` — green because of per-test reset."""
    _write_fixed_story(tmp_path)
