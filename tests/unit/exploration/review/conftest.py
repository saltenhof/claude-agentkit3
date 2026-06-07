"""Shared fixtures for the exploration-review unit tests (AG3-046).

Real components + tmp_path: the artifact store is a real sqlite backend so the
:class:`ArtifactReviewResultSink` persists genuine envelopes and returns real
:class:`ArtifactReference`s (no fabricated references).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from agentkit.state_backend.config import ALLOW_SQLITE_ENV, STATE_BACKEND_ENV
from agentkit.state_backend.store import reset_backend_cache_for_tests
from agentkit.story_context_manager.models import StoryContext
from agentkit.story_context_manager.types import StoryMode, StoryType

if TYPE_CHECKING:
    from collections.abc import Generator
    from pathlib import Path

#: The fixture change-frame is stamped with this story id (AG3-045).
STORY_ID = "AG3-045"


@pytest.fixture(autouse=True)
def sqlite_backend_env(
    monkeypatch: pytest.MonkeyPatch,
) -> Generator[None, None, None]:
    """Bind the sqlite state backend for the review-result sink."""
    monkeypatch.setenv(STATE_BACKEND_ENV, "sqlite")
    monkeypatch.setenv(ALLOW_SQLITE_ENV, "1")
    reset_backend_cache_for_tests()
    yield
    reset_backend_cache_for_tests()


@pytest.fixture
def story_dir(tmp_path: Path) -> Path:
    """A story working directory under ``<root>/stories/<story_id>``."""
    sd = tmp_path / "stories" / STORY_ID
    sd.mkdir(parents=True, exist_ok=True)
    return sd


@pytest.fixture
def ctx(story_dir: Path) -> StoryContext:
    """A story context for the review run."""
    return StoryContext(
        project_key="test-project",
        story_id=STORY_ID,
        story_type=StoryType.IMPLEMENTATION,
        execution_route=StoryMode.EXPLORATION,
        title="Exploration review",
        project_root=story_dir.parent.parent,
    )
