"""SQLite roundtrip tests for ModeLockRepository (AG3-034, FK-24 §24.3.3).

Unit path is SQLite-only (tests/unit/conftest.py forces sqlite + drops the
Postgres DSN). Verifies the project_mode_lock read path consumed by Preflight
Check 10, the seed upsert and input validation.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from agentkit.state_backend.store.mode_lock_repository import (
    ModeLockRecord,
    ModeLockRepository,
)

if TYPE_CHECKING:
    from pathlib import Path

_PROJECT = "proj-1"
_TS = "2026-06-02T00:00:00+00:00"


def test_read_missing_returns_none(tmp_path: Path) -> None:
    assert ModeLockRepository(tmp_path).read_lock(_PROJECT) is None


def test_set_then_read_roundtrip(tmp_path: Path) -> None:
    repo = ModeLockRepository(tmp_path)
    repo.set_lock(
        _PROJECT, active_mode="fast", holder_count=2, updated_at=_TS
    )
    record = repo.read_lock(_PROJECT)
    assert record == ModeLockRecord(
        project_key=_PROJECT,
        active_mode="fast",
        holder_count=2,
        updated_at=_TS,
    )


def test_idle_lock_roundtrip_with_null_mode(tmp_path: Path) -> None:
    repo = ModeLockRepository(tmp_path)
    repo.set_lock(
        _PROJECT, active_mode=None, holder_count=0, updated_at=_TS
    )
    record = repo.read_lock(_PROJECT)
    assert record is not None
    assert record.active_mode is None
    assert record.holder_count == 0


def test_set_is_upsert_on_project_key(tmp_path: Path) -> None:
    repo = ModeLockRepository(tmp_path)
    repo.set_lock(_PROJECT, active_mode="standard", holder_count=1, updated_at="t1")
    repo.set_lock(_PROJECT, active_mode="fast", holder_count=3, updated_at="t2")
    record = repo.read_lock(_PROJECT)
    assert record is not None
    assert record.active_mode == "fast"
    assert record.holder_count == 3


def test_set_rejects_unknown_mode(tmp_path: Path) -> None:
    # ``execution``/``exploration`` belong to the execution_route axis, not the
    # decoupled fast/standard mode axis the mode-lock lives on (FK-24 §24.3.3).
    with pytest.raises(ValueError, match="active_mode"):
        ModeLockRepository(tmp_path).set_lock(
            _PROJECT, active_mode="execution", holder_count=1, updated_at=_TS
        )


def test_set_rejects_negative_holder_count(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="holder_count"):
        ModeLockRepository(tmp_path).set_lock(
            _PROJECT, active_mode="fast", holder_count=-1, updated_at=_TS
        )
