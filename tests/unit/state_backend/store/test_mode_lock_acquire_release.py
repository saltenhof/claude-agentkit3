"""Atomic holder-aware acquire/release tests for the mode lock."""

from __future__ import annotations

import threading
from typing import TYPE_CHECKING

import pytest

from agentkit.backend.state_backend.store.mode_lock_repository import (
    ModeLockConflictError,
    ModeLockRepository,
)

if TYPE_CHECKING:
    from pathlib import Path

_PROJECT = "proj-mutex"


def test_acquire_reentry_is_idempotent(tmp_path: Path) -> None:
    repo = ModeLockRepository(tmp_path)
    first = repo.acquire(_PROJECT, "AG3-1", "run-1", "fast")
    second = repo.acquire(_PROJECT, "AG3-1", "run-1", "fast")
    assert first.holder_count == second.holder_count == 1
    assert len(repo.list_holders(_PROJECT)) == 1


def test_same_mode_distinct_holders_are_counted(tmp_path: Path) -> None:
    repo = ModeLockRepository(tmp_path)
    repo.acquire(_PROJECT, "AG3-1", "run-1", "standard")
    record = repo.acquire(_PROJECT, "AG3-2", "run-2", "standard")
    assert record.active_mode == "standard"
    assert record.holder_count == 2


def test_opposite_mode_fails_without_partial_mutation(tmp_path: Path) -> None:
    repo = ModeLockRepository(tmp_path)
    repo.acquire(_PROJECT, "AG3-1", "run-1", "standard")
    with pytest.raises(ModeLockConflictError):
        repo.acquire(_PROJECT, "AG3-2", "run-2", "fast")
    assert repo.read_holder(_PROJECT, "AG3-2", "run-2") is None
    assert repo.read_lock(_PROJECT).holder_count == 1  # type: ignore[union-attr]


def test_release_targets_exact_holder_and_is_idempotent(tmp_path: Path) -> None:
    repo = ModeLockRepository(tmp_path)
    repo.acquire(_PROJECT, "AG3-1", "run-1", "fast")
    repo.acquire(_PROJECT, "AG3-2", "run-2", "fast")
    first = repo.release(_PROJECT, "AG3-1", "run-1")
    second = repo.release(_PROJECT, "AG3-1", "run-1")
    assert first.holder_count == second.holder_count == 1
    assert repo.read_holder(_PROJECT, "AG3-2", "run-2") is not None
    idle = repo.release(_PROJECT, "AG3-2", "run-2")
    assert idle.active_mode is None
    assert idle.holder_count == 0


def test_concurrent_opposite_acquires_have_one_winner(tmp_path: Path) -> None:
    barrier = threading.Barrier(2)
    outcomes: list[str] = []

    def acquire(story: str, run: str, mode: str) -> None:
        barrier.wait()
        try:
            ModeLockRepository(tmp_path).acquire(_PROJECT, story, run, mode)
            outcomes.append("ok")
        except ModeLockConflictError:
            outcomes.append("conflict")

    threads = [
        threading.Thread(target=acquire, args=("AG3-1", "run-1", "fast")),
        threading.Thread(target=acquire, args=("AG3-2", "run-2", "standard")),
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert sorted(outcomes) == ["conflict", "ok"]
    assert ModeLockRepository(tmp_path).read_lock(_PROJECT).holder_count == 1  # type: ignore[union-attr]
