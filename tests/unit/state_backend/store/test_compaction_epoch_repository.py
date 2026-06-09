from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from typing import TYPE_CHECKING

import pytest

from agentkit.state_backend.store.compaction_epoch_repository import (
    StateBackendCompactionEpochRepository,
)

if TYPE_CHECKING:
    from pathlib import Path


@pytest.fixture(autouse=True)
def _sqlite_backend(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AGENTKIT_STATE_BACKEND", "sqlite")
    monkeypatch.setenv("AGENTKIT_ALLOW_SQLITE", "1")


def test_read_defaults_to_zero_and_increment_is_story_scoped(tmp_path: Path) -> None:
    repo = StateBackendCompactionEpochRepository(store_dir=tmp_path)
    assert repo.read_epoch("project", "AG3-075") == 0
    assert repo.increment_epoch("project", "AG3-075") == 1
    assert repo.increment_epoch("project", "AG3-075") == 2
    assert repo.read_epoch("project", "AG3-076") == 0


def test_sqlite_increment_has_no_lost_update_under_concurrency(tmp_path: Path) -> None:
    repo = StateBackendCompactionEpochRepository(store_dir=tmp_path)

    def _increment() -> int:
        return repo.increment_epoch("project", "AG3-075")

    with ThreadPoolExecutor(max_workers=8) as executor:
        results = list(executor.map(lambda _: _increment(), range(40)))

    assert sorted(results) == list(range(1, 41))
    assert repo.read_epoch("project", "AG3-075") == 40
