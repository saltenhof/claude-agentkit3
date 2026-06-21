"""Tests fuer idempotenten Bootstrap der ``attempts``-Tabelle (AG3-025 §2.1.1.2).

Verifiziert:
- zweimaliger Bootstrap ist ohne Fehler erfolgreich (CREATE TABLE IF NOT EXISTS)
- keine Duplikate in der Schema-Definition
- AttemptRecord-Roundtrip auf frischer DB
"""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest

from agentkit.backend.core_types.attempt import AttemptOutcome, FailureCause
from agentkit.backend.pipeline_engine.phase_executor import PhaseName
from agentkit.backend.pipeline_engine.phase_executor.records import AttemptRecord
from agentkit.backend.state_backend.config import ALLOW_SQLITE_ENV, STATE_BACKEND_ENV
from agentkit.backend.state_backend.sqlite_store import _connect, state_db_path_for
from agentkit.backend.state_backend.store import (
    load_attempts,
    reset_backend_cache_for_tests,
    save_attempt,
)

if TYPE_CHECKING:
    from collections.abc import Generator
    from pathlib import Path


_NOW = datetime(2026, 5, 17, 10, 0, 0, tzinfo=UTC)
_LATER = datetime(2026, 5, 17, 10, 5, 0, tzinfo=UTC)


@pytest.fixture(autouse=True)
def sqlite_env(monkeypatch: pytest.MonkeyPatch) -> Generator[None, None, None]:
    monkeypatch.setenv(STATE_BACKEND_ENV, "sqlite")
    monkeypatch.setenv(ALLOW_SQLITE_ENV, "1")
    reset_backend_cache_for_tests()
    yield
    reset_backend_cache_for_tests()


@pytest.fixture()
def story_dir(tmp_path: Path) -> Path:
    path = tmp_path / "stories" / "TEST-ISO-001"
    path.mkdir(parents=True, exist_ok=True)
    return path


class TestAttemptsTableBootstrapIdempotent:
    """AK7: Bootstrap ist idempotent re-runnable."""

    def test_double_bootstrap_no_error(self, story_dir: Path) -> None:
        """Zweimaliger Verbindungsaufbau (= zweimaliger Bootstrap) ist fehlerfrei."""
        # First connection triggers _ensure_schema (CREATE TABLE IF NOT EXISTS)
        with _connect(story_dir) as conn1:
            tables = [
                row[0]
                for row in conn1.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                ).fetchall()
            ]
            assert "attempts" in tables

        # Second connection repeats _ensure_schema — must not fail
        with _connect(story_dir) as conn2:
            tables2 = [
                row[0]
                for row in conn2.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                ).fetchall()
            ]
            assert "attempts" in tables2

    def test_triple_bootstrap_no_error(self, story_dir: Path) -> None:
        """Dreimaliger Bootstrap ist ebenfalls fehlerfrei."""
        for _ in range(3):
            with _connect(story_dir) as conn:
                result = conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' AND name='attempts'"
                ).fetchone()
                assert result is not None, "attempts table must exist after bootstrap"

    def test_bootstrap_creates_attempts_indices(self, story_dir: Path) -> None:
        """Bootstrap erstellt beide required Indizes (Story §2.1.1.1)."""
        with _connect(story_dir) as conn:
            indices = {
                row[0]
                for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='index'"
                ).fetchall()
            }
        # AG3-025 Re-Review: Index ist jetzt story-scoped (story_id, run_id, phase)
        # statt nur (run_id, phase) — verhindert Cross-Story-Kontamination bei
        # generate_attempt_id und load_attempts.
        assert "idx_attempts_story_run_phase" in indices
        assert "idx_attempts_outcome" in indices


class TestAttemptsSchemaConstraints:
    """AK2/AK3: DB-CHECK-Constraints verproben."""

    def test_roundtrip_completed(self, story_dir: Path) -> None:
        """Vollstaendiger Roundtrip: COMPLETED ohne failure_cause."""
        record = AttemptRecord(
            run_id="run-x",
            phase=PhaseName.SETUP,
            attempt=1,
            outcome=AttemptOutcome.COMPLETED,
            failure_cause=None,
            started_at=_NOW,
            ended_at=_LATER,
        )
        save_attempt(story_dir, record)
        loaded = load_attempts(story_dir, "setup")
        assert len(loaded) == 1
        assert loaded[0].outcome == AttemptOutcome.COMPLETED
        assert loaded[0].failure_cause is None

    def test_roundtrip_failed_with_cause(self, story_dir: Path) -> None:
        """Roundtrip: FAILED MIT failure_cause."""
        record = AttemptRecord(
            run_id="run-y",
            phase=PhaseName.IMPLEMENTATION,
            attempt=1,
            outcome=AttemptOutcome.FAILED,
            failure_cause=FailureCause.HANDLER_REPORTED_FAILED,
            started_at=_NOW,
            ended_at=_LATER,
        )
        save_attempt(story_dir, record)
        loaded = load_attempts(story_dir, "implementation")
        assert len(loaded) == 1
        assert loaded[0].failure_cause == FailureCause.HANDLER_REPORTED_FAILED

    def test_db_check_constraint_rejects_failed_without_cause(
        self,
        story_dir: Path,
    ) -> None:
        """DB-CHECK-Constraint: outcome=FAILED ohne failure_cause -> IntegrityError."""
        db_path = state_db_path_for(story_dir)
        # Trigger bootstrap by doing a normal connect first
        with _connect(story_dir) as _:
            pass

        with sqlite3.connect(str(db_path)) as conn, pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                """
                INSERT INTO attempts
                    (run_id, phase, attempt, outcome, failure_cause,
                     started_at, ended_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    "run-bad",
                    "setup",
                    1,
                    "FAILED",  # failure outcome
                    None,      # NULL failure_cause — violates constraint
                    _NOW.isoformat(),
                    _LATER.isoformat(),
                ),
            )
            conn.commit()

    def test_db_check_constraint_rejects_completed_with_cause(
        self,
        story_dir: Path,
    ) -> None:
        """DB-CHECK-Constraint: outcome=COMPLETED mit failure_cause -> IntegrityError."""
        db_path = state_db_path_for(story_dir)
        with _connect(story_dir) as _:
            pass

        with sqlite3.connect(str(db_path)) as conn, pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                """
                INSERT INTO attempts
                    (run_id, phase, attempt, outcome, failure_cause,
                     started_at, ended_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    "run-bad2",
                    "setup",
                    1,
                    "COMPLETED",
                    "GUARD_REJECTED",  # cause on success — violates constraint
                    _NOW.isoformat(),
                    _LATER.isoformat(),
                ),
            )
            conn.commit()

    def test_old_schema_version_db_unaffected(self, tmp_path: Path) -> None:
        """AK7: alte DB (3.4.0 Slug) bleibt unangetastet nach Schema-Bump."""
        # Alte DB-Datei unter alter Schema-Version anlegen
        old_db_dir = tmp_path / "stories" / "TEST-OLD"
        old_db_dir.mkdir(parents=True, exist_ok=True)

        old_db_path = old_db_dir / "agentkit_3_4_0.sqlite"
        # Minimale leere alte DB
        with sqlite3.connect(str(old_db_path)) as conn:
            conn.execute("CREATE TABLE IF NOT EXISTS dummy (id TEXT PRIMARY KEY)")
            conn.commit()

        # Neue DB (aktuelle SCHEMA_VERSION) oeffnen — beruehrt die alte
        # nicht. Derived from config so it does not drift on schema bumps.
        from agentkit.backend.state_backend.config import versioned_sqlite_db_file
        from agentkit.backend.state_backend.sqlite_store import state_db_path_for as sdb
        new_db_path = sdb(old_db_dir)
        expected_name = versioned_sqlite_db_file()
        assert new_db_path.name == expected_name, (
            f"Expected {expected_name} but got {new_db_path.name!r}"
        )
        assert new_db_path.name != old_db_path.name
        # Alte DB bleibt unveraendert
        assert old_db_path.exists()
        with sqlite3.connect(str(old_db_path)) as old_conn:
            tables = [
                row[0]
                for row in old_conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                ).fetchall()
            ]
            # Nur 'dummy' — kein 'attempts' in alter DB
            assert "dummy" in tables
            assert "attempts" not in tables
