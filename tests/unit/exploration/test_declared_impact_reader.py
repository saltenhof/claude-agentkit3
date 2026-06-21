"""Unit tests for the composition-root DeclaredImpactReader (AG3-047, FK-25 §25.7.1).

The state-backed ``_StateBackendDeclaredImpactReader`` reads the story's declared
``change_impact`` from the real ``StoryRepository`` and FAILS CLOSED (raises) when
the story is absent -- never a silent ``LOCAL`` default (FIX-THE-MODEL).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from agentkit.backend.bootstrap.composition_root import _StateBackendDeclaredImpactReader
from agentkit.backend.exceptions import CorruptStateError
from agentkit.backend.state_backend.config import ALLOW_SQLITE_ENV, STATE_BACKEND_ENV
from agentkit.backend.state_backend.store import reset_backend_cache_for_tests
from agentkit.backend.state_backend.store.story_repository import StateBackendStoryRepository
from agentkit.backend.story_context_manager.story_model import (
    ChangeImpact,
    Story,
    WireStoryType,
)

if TYPE_CHECKING:
    from collections.abc import Generator
    from pathlib import Path


@pytest.fixture(autouse=True)
def sqlite_backend_env(
    monkeypatch: pytest.MonkeyPatch,
) -> Generator[None, None, None]:
    monkeypatch.setenv(STATE_BACKEND_ENV, "sqlite")
    monkeypatch.setenv(ALLOW_SQLITE_ENV, "1")
    reset_backend_cache_for_tests()
    yield
    reset_backend_cache_for_tests()


def test_reads_declared_impact_from_persisted_story(tmp_path: Path) -> None:
    """The reader returns the authoritative declared change_impact."""
    StateBackendStoryRepository(tmp_path).save(
        Story(
            project_key="p",
            story_number=47,
            story_display_id="AG3-047",
            title="t",
            story_type=WireStoryType.IMPLEMENTATION,
            participating_repos=["r"],
            change_impact=ChangeImpact.CROSS_COMPONENT,
        )
    )
    reader = _StateBackendDeclaredImpactReader(tmp_path)

    assert reader.declared_change_impact(story_id="AG3-047") is (
        ChangeImpact.CROSS_COMPONENT
    )


def test_absent_story_fails_closed_no_local_default(tmp_path: Path) -> None:
    """An absent story RAISES (no silent LOCAL default; FK-25 §25.7.1)."""
    reader = _StateBackendDeclaredImpactReader(tmp_path)

    with pytest.raises(CorruptStateError, match="declared change_impact"):
        reader.declared_change_impact(story_id="AG3-999")
