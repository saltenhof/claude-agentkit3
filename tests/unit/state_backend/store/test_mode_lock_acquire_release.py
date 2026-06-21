"""Atomic acquire/release tests for ModeLockRepository (AG3-018, FK-24 §24.3.3).

The enforcement half of the Fast/Standard between-modes mutex: the atomic
``acquire``/``release`` CAS (NOT a plain upsert). Unit path is SQLite-only
(tests/unit/conftest.py forces sqlite). Covers: acquire sets active_mode +
holder_count; same-mode increment; opposite-mode fail-closed; release decrement;
reset to idle at 0; over-release / double-release idle-safety (recovery/resume).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from agentkit.backend.state_backend.store.mode_lock_repository import (
    ModeLockConflictError,
    ModeLockRepository,
)

if TYPE_CHECKING:
    from pathlib import Path

_PROJECT = "proj-mutex"


def test_acquire_idle_sets_mode_and_holder(tmp_path: Path) -> None:
    repo = ModeLockRepository(tmp_path)
    record = repo.acquire(_PROJECT, "fast")
    assert record.active_mode == "fast"
    assert record.holder_count == 1
    # Persisted (read path agrees).
    read = repo.read_lock(_PROJECT)
    assert read is not None
    assert read.active_mode == "fast"
    assert read.holder_count == 1


def test_acquire_same_mode_increments(tmp_path: Path) -> None:
    repo = ModeLockRepository(tmp_path)
    repo.acquire(_PROJECT, "standard")
    record = repo.acquire(_PROJECT, "standard")
    assert record.active_mode == "standard"
    assert record.holder_count == 2


def test_acquire_opposite_mode_fails_closed(tmp_path: Path) -> None:
    repo = ModeLockRepository(tmp_path)
    repo.acquire(_PROJECT, "standard")
    with pytest.raises(ModeLockConflictError, match="opposite mode"):
        repo.acquire(_PROJECT, "fast")
    # The held lock is unchanged (no partial mutation on the failed acquire).
    read = repo.read_lock(_PROJECT)
    assert read is not None
    assert read.active_mode == "standard"
    assert read.holder_count == 1


def test_release_decrements_then_resets_at_zero(tmp_path: Path) -> None:
    repo = ModeLockRepository(tmp_path)
    repo.acquire(_PROJECT, "fast")
    repo.acquire(_PROJECT, "fast")  # holder_count == 2
    after_first = repo.release(_PROJECT, "fast")
    assert after_first.active_mode == "fast"
    assert after_first.holder_count == 1
    after_second = repo.release(_PROJECT, "fast")
    # At 0 the lock resets to idle (active_mode None), so the opposite mode may
    # now acquire.
    assert after_second.active_mode is None
    assert after_second.holder_count == 0


def test_release_at_zero_allows_opposite_mode_to_acquire(tmp_path: Path) -> None:
    repo = ModeLockRepository(tmp_path)
    repo.acquire(_PROJECT, "fast")
    repo.release(_PROJECT, "fast")
    # Idle now -> the opposite mode is allowed.
    record = repo.acquire(_PROJECT, "standard")
    assert record.active_mode == "standard"
    assert record.holder_count == 1


def test_release_idle_lock_is_noop(tmp_path: Path) -> None:
    # Recovery/resume safety: a release of a never-acquired lock must not drive
    # the holder count negative.
    repo = ModeLockRepository(tmp_path)
    record = repo.release(_PROJECT, "fast")
    assert record.active_mode is None
    assert record.holder_count == 0


def test_double_release_does_not_go_negative(tmp_path: Path) -> None:
    # A resumed closure that double-releases must stay at idle, never negative.
    repo = ModeLockRepository(tmp_path)
    repo.acquire(_PROJECT, "fast")
    repo.release(_PROJECT, "fast")  # -> idle
    second = repo.release(_PROJECT, "fast")  # over-release
    assert second.active_mode is None
    assert second.holder_count == 0


def test_release_wrong_mode_is_noop(tmp_path: Path) -> None:
    # Releasing a mode that is not the held one is idle-safe (no decrement).
    repo = ModeLockRepository(tmp_path)
    repo.acquire(_PROJECT, "standard")
    record = repo.release(_PROJECT, "fast")
    assert record.active_mode == "standard"
    assert record.holder_count == 1


def test_concurrent_opposite_acquires_cannot_both_pass(tmp_path: Path) -> None:
    """FIX-2 (race-safe CAS): two opposite-mode first-acquires never both pass.

    Two threads acquire opposite modes on the SAME idle project against the SAME
    SQLite DB. The ``BEGIN IMMEDIATE`` write-lock serialises the read-decide-write
    so the second acquirer reads the post-acquire row and fails closed. Exactly one
    acquire succeeds; the lock holds exactly one mode with holder_count == 1.
    """
    import threading

    barrier = threading.Barrier(2)
    results: dict[str, object] = {}

    def _acquire(mode: str) -> None:
        # Each thread uses its own repository instance (own connection), the real
        # concurrency shape; they share the on-disk DB under ``tmp_path``.
        repo = ModeLockRepository(tmp_path)
        barrier.wait()
        try:
            repo.acquire(_PROJECT, mode)
            results[mode] = "ok"
        except ModeLockConflictError:
            results[mode] = "conflict"

    threads = [
        threading.Thread(target=_acquire, args=("fast",)),
        threading.Thread(target=_acquire, args=("standard",)),
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    outcomes = sorted(str(v) for v in results.values())
    assert outcomes == ["conflict", "ok"], (
        f"exactly one acquire must win; got {results}"
    )
    record = ModeLockRepository(tmp_path).read_lock(_PROJECT)
    assert record is not None
    assert record.holder_count == 1
    assert record.active_mode in {"fast", "standard"}


def test_acquire_rejects_unknown_mode(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="mode"):
        ModeLockRepository(tmp_path).acquire(_PROJECT, "execution")


def test_release_rejects_unknown_mode(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="mode"):
        ModeLockRepository(tmp_path).release(_PROJECT, "exploration")
