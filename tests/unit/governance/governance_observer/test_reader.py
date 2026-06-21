"""Unit tests for StateBackendGovernanceEventReader construction contract (FIX C).

AG3-085 round-3 FIX C: fail-closed on SQLite backend + story_dir=None.
"""

from __future__ import annotations

import pytest

# ---------------------------------------------------------------------------
# FIX C — fail-closed on SQLite backend + story_dir=None
# ---------------------------------------------------------------------------


def test_sqlite_backend_story_dir_none_raises_at_construction(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: object,
) -> None:
    """Construction with story_dir=None raises ValueError when SQLite is active (FIX C).

    Defaulting to cwd() for SQLite is a latent wrong-database read.  The
    construction guard must raise BEFORE any DB access is attempted.
    """
    monkeypatch.setenv("AGENTKIT_STATE_BACKEND", "sqlite")
    monkeypatch.setenv("AGENTKIT_ALLOW_SQLITE", "1")
    monkeypatch.delenv("AGENTKIT_STATE_DATABASE_URL", raising=False)

    # Reset lru_cache so the monkeypatched env is picked up
    from agentkit.backend.state_backend.store.facade import reset_backend_cache_for_tests

    reset_backend_cache_for_tests()

    from agentkit.backend.governance.governance_observer.reader import (
        StateBackendGovernanceEventReader,
    )

    with pytest.raises(ValueError, match="story_dir must not be None"):
        StateBackendGovernanceEventReader(story_dir=None)


def test_postgres_backend_story_dir_none_is_accepted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Construction with story_dir=None is allowed when Postgres backend is active (FIX C).

    For Postgres the story_dir is genuinely unused (the connection is derived
    from the env), so None is a legitimate value — no raise.
    """
    monkeypatch.setenv("AGENTKIT_STATE_BACKEND", "postgres")
    monkeypatch.setenv(
        "AGENTKIT_STATE_DATABASE_URL",
        "postgresql://fake:fake@localhost:5432/fake",
    )
    monkeypatch.delenv("AGENTKIT_ALLOW_SQLITE", raising=False)

    from agentkit.backend.state_backend.store.facade import reset_backend_cache_for_tests

    reset_backend_cache_for_tests()

    from agentkit.backend.governance.governance_observer.reader import (
        StateBackendGovernanceEventReader,
    )

    # Must not raise — Postgres ignores story_dir
    reader = StateBackendGovernanceEventReader(story_dir=None)
    assert reader._story_dir is None


def test_sqlite_backend_with_story_dir_succeeds(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: object,
) -> None:
    """Construction with a real story_dir does not raise when SQLite is active (FIX C).

    The guard must only fire when story_dir is None; a valid path is accepted.
    """
    import pathlib

    monkeypatch.setenv("AGENTKIT_STATE_BACKEND", "sqlite")
    monkeypatch.setenv("AGENTKIT_ALLOW_SQLITE", "1")
    monkeypatch.delenv("AGENTKIT_STATE_DATABASE_URL", raising=False)

    from agentkit.backend.state_backend.store.facade import reset_backend_cache_for_tests

    reset_backend_cache_for_tests()

    from agentkit.backend.governance.governance_observer.reader import (
        StateBackendGovernanceEventReader,
    )

    story_dir = pathlib.Path(str(tmp_path))
    reader = StateBackendGovernanceEventReader(story_dir=story_dir)
    assert reader._story_dir == story_dir
