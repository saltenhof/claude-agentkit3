"""Bootstrap-Idempotenz + CHECK-Constraints fuer ``fc_incidents`` (AG3-028 §2.1.5, AK#4).

Verifiziert:
- zweimaliger Bootstrap ist fehlerfrei (CREATE TABLE IF NOT EXISTS)
- die beiden Indizes werden angelegt
- CHECK-Constraints auf category / severity / incident_status greifen
- PK (UNIQUE incident_id): doppelter Insert -> IntegrityError (append-only)
- alte DB (anderer SCHEMA_VERSION-Slug) bleibt unangetastet (FK-18 §18.9a)
"""

from __future__ import annotations

import sqlite3
from typing import TYPE_CHECKING

import pytest

from agentkit.state_backend.config import ALLOW_SQLITE_ENV, STATE_BACKEND_ENV
from agentkit.state_backend.sqlite_store import _connect, state_db_path_for
from agentkit.state_backend.store import reset_backend_cache_for_tests

if TYPE_CHECKING:
    from collections.abc import Generator
    from pathlib import Path

_VALID_ROW = (
    "FC-1",
    "scope_drift",
    "high",
    "governance-and-guards",
    "AG3-001",
    "run-1",
    "scope exceeded",
    "{}",
    "2026-06-01T12:00:00+00:00",
    "2026-06-01T12:00:00+00:00",
    "observed",
)

_INSERT = """
    INSERT INTO fc_incidents (
        incident_id, category, severity, source_bc, story_id, run_id,
        summary, evidence_json, observed_at, normalized_at, incident_status
    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
"""


@pytest.fixture(autouse=True)
def sqlite_env(monkeypatch: pytest.MonkeyPatch) -> Generator[None, None, None]:
    monkeypatch.setenv(STATE_BACKEND_ENV, "sqlite")
    monkeypatch.setenv(ALLOW_SQLITE_ENV, "1")
    reset_backend_cache_for_tests()
    yield
    reset_backend_cache_for_tests()


@pytest.fixture()
def story_dir(tmp_path: Path) -> Path:
    path = tmp_path / "stories" / "FC-TEST"
    path.mkdir(parents=True, exist_ok=True)
    return path


class TestBootstrapIdempotent:
    def test_table_present_after_bootstrap(self, story_dir: Path) -> None:
        with _connect(story_dir) as conn:
            result = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' "
                "AND name='fc_incidents'"
            ).fetchone()
        assert result is not None

    def test_double_bootstrap_no_error(self, story_dir: Path) -> None:
        for _ in range(2):
            with _connect(story_dir) as conn:
                assert (
                    conn.execute(
                        "SELECT name FROM sqlite_master WHERE type='table' "
                        "AND name='fc_incidents'"
                    ).fetchone()
                    is not None
                )

    def test_indices_created(self, story_dir: Path) -> None:
        with _connect(story_dir) as conn:
            indices = {
                row[0]
                for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='index'"
                ).fetchall()
            }
        assert "idx_fc_incidents_story_run" in indices
        assert "idx_fc_incidents_incident_status" in indices


class TestCheckConstraints:
    def test_valid_row_inserts(self, story_dir: Path) -> None:
        with _connect(story_dir) as conn:
            conn.execute(_INSERT, _VALID_ROW)
            conn.commit()
            count = conn.execute("SELECT COUNT(*) FROM fc_incidents").fetchone()[0]
        assert count == 1

    def test_default_incident_status_observed(self, story_dir: Path) -> None:
        with _connect(story_dir) as conn:
            conn.execute(
                """
                INSERT INTO fc_incidents (
                    incident_id, category, severity, source_bc, story_id,
                    run_id, summary, evidence_json, observed_at, normalized_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    "FC-default",
                    "scope_drift",
                    "high",
                    "bc",
                    "AG3-001",
                    "run-1",
                    "s",
                    "{}",
                    "2026-06-01T12:00:00+00:00",
                    "2026-06-01T12:00:00+00:00",
                ),
            )
            conn.commit()
            status = conn.execute(
                "SELECT incident_status FROM fc_incidents WHERE incident_id='FC-default'"
            ).fetchone()[0]
        assert status == "observed"

    def test_rejects_invalid_category(self, story_dir: Path) -> None:
        bad = ("FC-2", "not_a_category", *_VALID_ROW[2:])
        with _connect(story_dir) as conn, pytest.raises(sqlite3.IntegrityError):
            conn.execute(_INSERT, bad)
            conn.commit()

    def test_rejects_invalid_severity(self, story_dir: Path) -> None:
        bad = ("FC-3", "scope_drift", "BLOCKING", *_VALID_ROW[3:])
        with _connect(story_dir) as conn, pytest.raises(sqlite3.IntegrityError):
            conn.execute(_INSERT, bad)
            conn.commit()

    def test_rejects_invalid_incident_status(self, story_dir: Path) -> None:
        # alter PromotionStatus-Wert ist kein gueltiger IncidentStatus mehr
        bad = ("FC-4", *_VALID_ROW[1:-1], "monitoring")
        with _connect(story_dir) as conn, pytest.raises(sqlite3.IntegrityError):
            conn.execute(_INSERT, bad)
            conn.commit()

    def test_duplicate_incident_id_rejected(self, story_dir: Path) -> None:
        """Append-only: genau ein Datensatz pro incident_id (FK-41 §41.3.1)."""
        with _connect(story_dir) as conn:
            conn.execute(_INSERT, _VALID_ROW)
            conn.commit()
        with _connect(story_dir) as conn, pytest.raises(sqlite3.IntegrityError):
            conn.execute(_INSERT, _VALID_ROW)
            conn.commit()


class TestSideBySideMigration:
    def test_old_schema_db_untouched(self, tmp_path: Path) -> None:
        old_dir = tmp_path / "stories" / "OLD"
        old_dir.mkdir(parents=True, exist_ok=True)
        old_db = old_dir / "agentkit_3_8_0.sqlite"
        with sqlite3.connect(str(old_db)) as conn:
            conn.execute("CREATE TABLE dummy (id TEXT PRIMARY KEY)")
            conn.commit()

        new_db = state_db_path_for(old_dir)
        from agentkit.state_backend.config import versioned_sqlite_db_file

        assert new_db.name == versioned_sqlite_db_file()
        assert new_db.name != old_db.name

        with _connect(old_dir) as _:
            pass

        assert old_db.exists()
        with sqlite3.connect(str(old_db)) as old_conn:
            tables = [
                row[0]
                for row in old_conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                ).fetchall()
            ]
        assert "fc_incidents" not in tables
        assert "dummy" in tables
