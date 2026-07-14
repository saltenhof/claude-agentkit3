"""Holder-identity read tests for the project mode-lock repository."""

from __future__ import annotations

import sqlite3
from typing import TYPE_CHECKING

import pytest

from agentkit.backend.state_backend.config import versioned_sqlite_db_file
from agentkit.backend.state_backend.paths import state_backend_dir
from agentkit.backend.state_backend.store.mode_lock_repository import (
    ModeLockHolderRecord,
    ModeLockRepository,
)

if TYPE_CHECKING:
    from pathlib import Path

_PROJECT = "proj-1"
_STORY = "AG3-131"
_RUN = "run-1"


def test_read_missing_returns_none(tmp_path: Path) -> None:
    repo = ModeLockRepository(tmp_path)
    assert repo.read_lock(_PROJECT) is None
    assert repo.read_holder(_PROJECT, _STORY, _RUN) is None
    assert repo.list_holders(_PROJECT) == ()


def test_holder_identity_roundtrip(tmp_path: Path) -> None:
    repo = ModeLockRepository(tmp_path)
    repo.acquire(_PROJECT, _STORY, _RUN, "fast")

    holder = repo.read_holder(_PROJECT, _STORY, _RUN)
    assert isinstance(holder, ModeLockHolderRecord)
    assert holder.project_key == _PROJECT
    assert holder.story_id == _STORY
    assert holder.run_id == _RUN
    assert holder.mode == "fast"
    assert repo.list_holders(_PROJECT) == (holder,)


def test_summary_divergence_fails_closed(tmp_path: Path) -> None:
    repo = ModeLockRepository(tmp_path)
    repo.acquire(_PROJECT, _STORY, _RUN, "standard")
    db = state_backend_dir(tmp_path) / versioned_sqlite_db_file()
    with sqlite3.connect(db) as conn:
        conn.execute(
            "UPDATE project_mode_lock SET holder_count = 99 WHERE project_key = ?",
            (_PROJECT,),
        )

    with pytest.raises(RuntimeError, match="diverges"):
        repo.read_lock(_PROJECT)


@pytest.mark.parametrize("value", ["", "execution"])
def test_acquire_rejects_invalid_identity_or_mode(tmp_path: Path, value: str) -> None:
    repo = ModeLockRepository(tmp_path)
    args = (_PROJECT, _STORY, _RUN, value)
    with pytest.raises(ValueError):
        repo.acquire(*args)
