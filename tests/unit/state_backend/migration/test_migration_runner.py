"""MigrationRunner idempotency tests (AG3-038 AC5, FK-62 §62.4; AG3-117 head 3.6).

Proves a double run produces no error, no duplicate cursor row, and the second run
applies nothing: data inserted AFTER the full first run survives a second run (the
already-recorded versions — including the v3.6 drop+rebuild — are skipped, so no
schema churn touches the data).
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


def test_first_run_applies_v3_4_v3_5_v3_6_and_creates_tables(tmp_path: Path) -> None:
    conn = _open(tmp_path / "m.sqlite")
    try:
        applied = MigrationRunner().run(conn)
        conn.commit()
        assert applied == ["3.4", "3.5", "3.6"]
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
        # AG3-117: after v3.6 the fact tables carry the FK-62 reconciled columns.
        guard_cols = {
            str(row[1])
            for row in conn.execute(
                "PRAGMA table_info(fact_guard_period)"
            ).fetchall()
        }
        assert "guard_key" in guard_cols
        assert "guard_id" not in guard_cols
        assert "period_grain" in guard_cols
        assert "period_end" not in guard_cols
        pool_cols = {
            str(row[1])
            for row in conn.execute("PRAGMA table_info(fact_pool_period)").fetchall()
        }
        assert "pool_key" in pool_cols
        assert "response_time_p50_ms" in pool_cols
        assert "response_time_p95_ms" not in pool_cols
        story_cols = {
            str(row[1])
            for row in conn.execute("PRAGMA table_info(fact_story)").fetchall()
        }
        assert {"opened_at", "closed_at", "qa_round_count", "are_gate_passed"} <= (
            story_cols
        )
        assert "started_at" not in story_cols
        assert "agentkit_version" not in story_cols
    finally:
        conn.close()


def test_double_run_is_idempotent_no_error_no_dup_no_drop(tmp_path: Path) -> None:
    db_path = tmp_path / "m.sqlite"
    runner = MigrationRunner()

    conn = _open(db_path)
    try:
        assert runner.run(conn) == ["3.4", "3.5", "3.6"]
        # Insert a row (FK-62 reconciled schema) to prove the second run does NOT
        # re-run the v3.6 drop+rebuild that would have wiped it.
        conn.execute(
            "INSERT INTO fact_corpus_period (project_key, period_start, "
            "new_incident_count, patterns_total_count, patterns_with_active_check, "
            "computed_at) VALUES ('p1', '2026-06-01', 3, 1, 1, '2026-06-02')"
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
        count = conn.execute(
            "SELECT COUNT(*) FROM schema_versions WHERE version = '3.6'"
        ).fetchone()[0]
        assert count == 1
        # Data survived -> the second run did not re-run the v3.6 drop+rebuild.
        survived = conn.execute(
            "SELECT new_incident_count FROM fact_corpus_period "
            "WHERE project_key = 'p1'"
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
        assert "3.6" in runner.applied_versions(conn)
    finally:
        conn.close()
