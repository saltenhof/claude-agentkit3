"""Bootstrap-Idempotenz + FK-41-§41.3.2/§41.3.3-Vertrag fuer fc_patterns /
fc_check_proposals (AG3-040 Sub-Block (b), AK2).

Pinnt:
- zweimaliger Bootstrap ist fehlerfrei (CREATE TABLE IF NOT EXISTS)
- beide Tabellen + Indizes vorhanden
- exakte FK-41-Spalten (Pflicht NOT NULL, Optional nullbar)
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
    def test_tables_present(self, story_dir: Path) -> None:
        with _connect(story_dir) as conn:
            tables = {
                row[0]
                for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                ).fetchall()
            }
        assert "fc_patterns" in tables
        assert "fc_check_proposals" in tables

    def test_double_bootstrap_no_error(self, story_dir: Path) -> None:
        for _ in range(2):
            with _connect(story_dir) as conn:
                assert (
                    conn.execute(
                        "SELECT name FROM sqlite_master WHERE type='table' "
                        "AND name='fc_check_proposals'"
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
        assert "idx_fc_patterns_project" in indices
        assert "idx_fc_patterns_status" in indices
        assert "idx_fc_check_proposals_project" in indices
        assert "idx_fc_check_proposals_pattern_ref" in indices
        assert "idx_fc_check_proposals_status" in indices


class TestExactColumnContract:
    def test_fc_patterns_columns(self, story_dir: Path) -> None:
        with _connect(story_dir) as conn:
            cols = {
                str(row[1]): {"notnull": bool(row[3])}
                for row in conn.execute("PRAGMA table_info(fc_patterns)").fetchall()
            }
        for name in (
            "pattern_id",
            "project_key",
            "status",
            "category",
            "invariant",
            "incident_refs",
            "promotion_rule",
            "risk_level",
            "incident_count",
        ):
            assert name in cols, f"missing column {name}"
            assert cols[name]["notnull"], f"{name} must be NOT NULL (FK-41 §41.3.2)"
        for name in ("confirmed_at", "confirmed_by", "owner", "check_ref", "retired_at"):
            assert name in cols, f"missing optional column {name}"
            assert not cols[name]["notnull"], f"{name} must be nullable"

    def test_fc_check_proposals_columns(self, story_dir: Path) -> None:
        with _connect(story_dir) as conn:
            cols = {
                str(row[1]): {"notnull": bool(row[3])}
                for row in conn.execute(
                    "PRAGMA table_info(fc_check_proposals)"
                ).fetchall()
            }
        for name in (
            "check_id",
            "project_key",
            "status",
            "pattern_ref",
            "invariant",
            "check_type",
            "pipeline_stage",
            "pipeline_layer",
            "owner",
            "false_positive_risk",
            "positive_fixtures",
            "negative_fixtures",
            "created_at",
        ):
            assert name in cols, f"missing column {name}"
            assert cols[name]["notnull"], f"{name} must be NOT NULL (FK-41 §41.3.3)"
        for name in (
            "approved_at",
            "approved_by",
            "rejected_reason",
            "effectiveness_last_checked_at",
            "true_positives_90d",
            "false_positives_90d",
        ):
            assert name in cols, f"missing optional column {name}"
            assert not cols[name]["notnull"], f"{name} must be nullable"


class TestSideBySideMigration:
    def test_old_schema_db_untouched(self, tmp_path: Path) -> None:
        old_dir = tmp_path / "stories" / "OLD"
        old_dir.mkdir(parents=True, exist_ok=True)
        old_db = old_dir / "agentkit_3_14_0.sqlite"
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
        assert "fc_patterns" not in tables
        assert "fc_check_proposals" not in tables
        assert "dummy" in tables
