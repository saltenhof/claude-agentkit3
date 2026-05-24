"""Roundtrip tests for story_execution_locks table on SQLite (+ opt-in Postgres).

AG3-031 Pass-7: SQLite schema consolidation and save_lock path fix.

Verifies:
- story_execution_locks DDL is bootstrapped via _ensure_schema_runtime_tables
- save -> load roundtrip on SQLite
- save -> load -> deactivate roundtrip on SQLite (via LockRecordRepository)
- Postgres paths skip when AGENTKIT_STATE_DATABASE_URL not set
"""

from __future__ import annotations

import os
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest

from agentkit.governance.guard_system.records import StoryExecutionLockRecord
from agentkit.state_backend.config import ALLOW_SQLITE_ENV, STATE_BACKEND_ENV

if TYPE_CHECKING:
    from collections.abc import Generator
    from pathlib import Path

_STATE_DATABASE_URL_ENV = "AGENTKIT_STATE_DATABASE_URL"

_NOW = datetime(2026, 5, 24, 12, 0, 0, tzinfo=UTC)
_PROJECT_KEY = "test-lock-proj"
_RUN_ID = "run-lock-001"
_LOCK_TYPE = "story_execution"


def _make_lock_record(story_id: str) -> StoryExecutionLockRecord:
    return StoryExecutionLockRecord(
        project_key=_PROJECT_KEY,
        story_id=story_id,
        run_id=_RUN_ID,
        lock_type=_LOCK_TYPE,
        status="ACTIVE",
        worktree_roots=("/tmp/wt1", "/tmp/wt2"),
        binding_version="1.0.0",
        activated_at=_NOW,
        updated_at=_NOW,
        deactivated_at=None,
    )


def _has_postgres_url() -> bool:
    return bool(os.environ.get(_STATE_DATABASE_URL_ENV, ""))


# ---------------------------------------------------------------------------
# SQLite fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def sqlite_env(
    monkeypatch: pytest.MonkeyPatch,
) -> Generator[None, None, None]:
    monkeypatch.setenv(STATE_BACKEND_ENV, "sqlite")
    monkeypatch.setenv(ALLOW_SQLITE_ENV, "1")
    from agentkit.state_backend.store import reset_backend_cache_for_tests

    reset_backend_cache_for_tests()
    yield
    reset_backend_cache_for_tests()


# ---------------------------------------------------------------------------
# Tests: schema bootstrap
# ---------------------------------------------------------------------------


class TestStoryExecutionLocksSchemaBootstrap:
    """story_execution_locks table is created by the canonical schema bootstrap."""

    def test_table_created_by_ensure_schema(self, tmp_path: Path) -> None:
        """_ensure_schema_runtime_tables creates story_execution_locks."""
        from agentkit.state_backend.sqlite_store import _connect

        story_dir = tmp_path / "TEST-LOCK-SCHEMA"
        story_dir.mkdir(parents=True, exist_ok=True)

        with _connect(story_dir) as conn:
            tables = [
                row[0]
                for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                ).fetchall()
            ]

        assert "story_execution_locks" in tables, (
            "story_execution_locks must be created during schema bootstrap"
        )

    def test_double_bootstrap_idempotent(self, tmp_path: Path) -> None:
        """Repeated bootstrap (CREATE TABLE IF NOT EXISTS) does not raise."""
        from agentkit.state_backend.sqlite_store import _connect

        story_dir = tmp_path / "TEST-LOCK-IDEM"
        story_dir.mkdir(parents=True, exist_ok=True)

        # First connect
        with _connect(story_dir) as conn1:
            tables1 = [
                row[0]
                for row in conn1.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                ).fetchall()
            ]
            assert "story_execution_locks" in tables1

        # Second connect — must not raise, table still present
        with _connect(story_dir) as conn2:
            tables2 = [
                row[0]
                for row in conn2.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                ).fetchall()
            ]
            assert "story_execution_locks" in tables2


# ---------------------------------------------------------------------------
# Tests: SQLite save + load roundtrip
# ---------------------------------------------------------------------------


class TestStoryExecutionLockSQLiteRoundtrip:
    """save_story_execution_lock_global -> load_story_execution_lock_global on SQLite."""

    def test_save_and_load(self, tmp_path: Path) -> None:
        """Persisted lock record is loadable with all fields intact."""
        from agentkit.state_backend.store import (
            load_story_execution_lock_global,
            save_story_execution_lock_global,
        )

        story_id = "TEST-LOCK-SAVE-001"
        record = _make_lock_record(story_id)

        # Need to use cwd-based global store path; cd to tmp_path
        old_cwd = os.getcwd()
        os.chdir(tmp_path)
        try:
            save_story_execution_lock_global(record)
            loaded = load_story_execution_lock_global(
                _PROJECT_KEY, story_id, _RUN_ID, _LOCK_TYPE
            )
        finally:
            os.chdir(old_cwd)

        assert loaded is not None
        assert loaded.project_key == _PROJECT_KEY
        assert loaded.story_id == story_id
        assert loaded.run_id == _RUN_ID
        assert loaded.lock_type == _LOCK_TYPE
        assert loaded.status == "ACTIVE"
        assert "/tmp/wt1" in loaded.worktree_roots
        assert "/tmp/wt2" in loaded.worktree_roots
        assert loaded.binding_version == "1.0.0"
        assert loaded.deactivated_at is None

    def test_load_nonexistent_returns_none(self, tmp_path: Path) -> None:
        """Loading a non-existent lock returns None."""
        from agentkit.state_backend.store import load_story_execution_lock_global

        old_cwd = os.getcwd()
        os.chdir(tmp_path)
        try:
            loaded = load_story_execution_lock_global(
                "no-proj", "no-story", "no-run", "story_execution"
            )
        finally:
            os.chdir(old_cwd)

        assert loaded is None

    def test_upsert_on_conflict(self, tmp_path: Path) -> None:
        """Second save with same PK updates the row (upsert semantics)."""
        from agentkit.state_backend.store import (
            load_story_execution_lock_global,
            save_story_execution_lock_global,
        )

        story_id = "TEST-LOCK-UPSERT-001"
        record_active = _make_lock_record(story_id)
        record_inactive = StoryExecutionLockRecord(
            project_key=_PROJECT_KEY,
            story_id=story_id,
            run_id=_RUN_ID,
            lock_type=_LOCK_TYPE,
            status="INACTIVE",
            worktree_roots=(),
            binding_version="1.0.0",
            activated_at=_NOW,
            updated_at=_NOW,
            deactivated_at=_NOW,
        )

        old_cwd = os.getcwd()
        os.chdir(tmp_path)
        try:
            save_story_execution_lock_global(record_active)
            save_story_execution_lock_global(record_inactive)
            loaded = load_story_execution_lock_global(
                _PROJECT_KEY, story_id, _RUN_ID, _LOCK_TYPE
            )
        finally:
            os.chdir(old_cwd)

        assert loaded is not None
        assert loaded.status == "INACTIVE"
        assert loaded.deactivated_at is not None


# ---------------------------------------------------------------------------
# Tests: save + load + deactivate_locks_for_story roundtrip
# ---------------------------------------------------------------------------


class TestStoryExecutionLockDeactivateRoundtrip:
    """Full roundtrip: save -> load -> deactivate_locks_for_story on SQLite."""

    def test_activate_then_deactivate(self, tmp_path: Path) -> None:
        """Lock activated via save, then deactivated via LockRecordRepository."""
        from agentkit.state_backend.store import (
            load_story_execution_lock_global,
            save_story_execution_lock_global,
        )
        from agentkit.state_backend.store.lock_record_repository import (
            LockRecordRepository,
        )

        story_id = "TEST-LOCK-DEACT-001"
        record = _make_lock_record(story_id)

        old_cwd = os.getcwd()
        os.chdir(tmp_path)
        try:
            # Activate
            save_story_execution_lock_global(record)
            loaded_before = load_story_execution_lock_global(
                _PROJECT_KEY, story_id, _RUN_ID, _LOCK_TYPE
            )
            assert loaded_before is not None
            assert loaded_before.status == "ACTIVE"

            # Deactivate via LockRecordRepository
            repo = LockRecordRepository(store_dir=tmp_path)
            deactivated_ids = repo.deactivate_locks_for_story(story_id)

        finally:
            os.chdir(old_cwd)

        assert len(deactivated_ids) >= 1
        assert any(story_id in lid for lid in deactivated_ids)

    def test_deactivate_unknown_story_raises(self, tmp_path: Path) -> None:
        """Deactivating a story with no lock records raises LockRecordNotFoundError."""
        from agentkit.governance.errors import LockRecordNotFoundError
        from agentkit.state_backend.store.lock_record_repository import (
            LockRecordRepository,
        )

        repo = LockRecordRepository(store_dir=tmp_path)

        # Need schema to exist in that db first; trigger bootstrap via save
        old_cwd = os.getcwd()
        os.chdir(tmp_path)
        try:
            # Bootstrap the DB by saving a different story first
            from agentkit.state_backend.store import save_story_execution_lock_global

            bootstrap_record = _make_lock_record("bootstrap-story")
            save_story_execution_lock_global(bootstrap_record)
        finally:
            os.chdir(old_cwd)

        with pytest.raises(LockRecordNotFoundError, match="unknown-story"):
            repo.deactivate_locks_for_story("unknown-story")

    def test_idempotent_deactivation(self, tmp_path: Path) -> None:
        """Re-deactivating an already-inactive story returns empty list (idempotent)."""
        from agentkit.state_backend.store import save_story_execution_lock_global
        from agentkit.state_backend.store.lock_record_repository import (
            LockRecordRepository,
        )

        story_id = "TEST-LOCK-IDEM-DEACT-001"
        record = _make_lock_record(story_id)

        old_cwd = os.getcwd()
        os.chdir(tmp_path)
        try:
            save_story_execution_lock_global(record)
            repo = LockRecordRepository(store_dir=tmp_path)
            # First deactivation
            first = repo.deactivate_locks_for_story(story_id)
            # Second deactivation (idempotent — story known but all INACTIVE)
            second = repo.deactivate_locks_for_story(story_id)
        finally:
            os.chdir(old_cwd)

        assert len(first) >= 1
        assert second == []


# ---------------------------------------------------------------------------
# Tests: Postgres (opt-in, skipped when URL not set)
# ---------------------------------------------------------------------------


@pytest.mark.skipif(
    not _has_postgres_url(),
    reason="AGENTKIT_STATE_DATABASE_URL not set — Postgres roundtrip test skipped",
)
class TestStoryExecutionLockPostgresRoundtrip:
    """Postgres save + load + deactivate roundtrip (opt-in)."""

    def test_postgres_activate_deactivate(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Postgres roundtrip: activate then deactivate."""
        monkeypatch.setenv(STATE_BACKEND_ENV, "postgres")
        from agentkit.state_backend.store import reset_backend_cache_for_tests

        reset_backend_cache_for_tests()
        try:
            from agentkit.state_backend.store import (
                load_story_execution_lock_global,
                save_story_execution_lock_global,
            )
            from agentkit.state_backend.store.lock_record_repository import (
                LockRecordRepository,
            )

            story_id = "TEST-PG-LOCK-001"
            record = _make_lock_record(story_id)

            save_story_execution_lock_global(record)
            loaded = load_story_execution_lock_global(
                _PROJECT_KEY, story_id, _RUN_ID, _LOCK_TYPE
            )
            assert loaded is not None
            assert loaded.status == "ACTIVE"

            repo = LockRecordRepository()
            deactivated = repo.deactivate_locks_for_story(story_id)
            assert len(deactivated) >= 1
        finally:
            reset_backend_cache_for_tests()
