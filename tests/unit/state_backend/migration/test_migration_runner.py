"""MigrationRunner idempotency tests (AG3-038 AC5, FK-62 §62.4).

Proves a double run produces no error, no duplicate cursor row, and no
DROP/RECREATE: the second run applies nothing and the data inserted between runs
survives (a DROP/RECREATE would have wiped it).
"""

from __future__ import annotations

import sqlite3
from typing import TYPE_CHECKING

from agentkit.state_backend.migration import MigrationRunner

if TYPE_CHECKING:
    from pathlib import Path


def _open(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    return conn


def test_first_run_applies_v3_4_and_v3_5_and_creates_tables(tmp_path: Path) -> None:
    conn = _open(tmp_path / "m.sqlite")
    try:
        applied = MigrationRunner().run(conn)
        conn.commit()
        assert applied == ["3.4", "3.5"]
        tables = {
            str(row[0])
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        assert {
            "fact_story",
            "fact_guard_period",
            "fact_pool_period",
            "fact_pipeline_period",
            "fact_corpus_period",
            "sync_state",
            "guard_invocation_counters",
            "compaction_epochs",
            "schema_versions",
        } <= tables
    finally:
        conn.close()


def test_double_run_is_idempotent_no_error_no_dup_no_drop(tmp_path: Path) -> None:
    db_path = tmp_path / "m.sqlite"
    runner = MigrationRunner()

    conn = _open(db_path)
    try:
        assert runner.run(conn) == ["3.4", "3.5"]
        # Insert a row to prove the second run does NOT drop/recreate the table.
        conn.execute(
            "INSERT INTO fact_corpus_period (project_key, period_start, "
            "period_end, incidents_recorded, patterns_promoted, checks_approved) "
            "VALUES ('p1', '2026-06-01', '2026-07-01', 3, 1, 1)"
        )
        conn.commit()
    finally:
        conn.close()

    conn = _open(db_path)
    try:
        # Second run: nothing new applied, no error.
        assert runner.run(conn) == []
        conn.commit()
        # Cursor has exactly one row for each version (no duplicate).
        count = conn.execute(
            "SELECT COUNT(*) FROM schema_versions WHERE version = '3.4'"
        ).fetchone()[0]
        assert count == 1
        count = conn.execute(
            "SELECT COUNT(*) FROM schema_versions WHERE version = '3.5'"
        ).fetchone()[0]
        assert count == 1
        # Data survived -> no DROP/RECREATE happened.
        survived = conn.execute(
            "SELECT incidents_recorded FROM fact_corpus_period WHERE project_key = 'p1'"
        ).fetchone()[0]
        assert survived == 3
    finally:
        conn.close()


def test_applied_versions_reports_recorded_cursor(tmp_path: Path) -> None:
    conn = _open(tmp_path / "m.sqlite")
    try:
        runner = MigrationRunner()
        assert runner.applied_versions(conn) == set()
        runner.run(conn)
        conn.commit()
        assert "3.4" in runner.applied_versions(conn)
        assert "3.5" in runner.applied_versions(conn)
    finally:
        conn.close()
