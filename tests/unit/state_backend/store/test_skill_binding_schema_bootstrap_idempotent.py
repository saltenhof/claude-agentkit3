"""Bootstrap-Idempotenz + Schema-Vertrag fuer ``skill_bindings`` (AG3-048, AK#1).

Pinnt (mirror ``test_attempt_schema_bootstrap_idempotent.py``):
- zweimaliger/dreimaliger Bootstrap ist fehlerfrei (CREATE TABLE IF NOT EXISTS)
- exakte SkillBinding-Spalten (binding_id PK, UNIQUE(project_key, skill_name))
- Index idx_skill_bindings_project_skill
- CHECK-Constraints fuer binding_mode (SYMLINK) und status (alle 6 Werte)
- alte DB (anderer SCHEMA_VERSION-Slug) bleibt unangetastet (FK-18 §18.9a)
"""

from __future__ import annotations

import sqlite3
from typing import TYPE_CHECKING

import pytest

from agentkit.backend.skills.binding import SkillLifecycleStatus
from agentkit.backend.state_backend.config import ALLOW_SQLITE_ENV, STATE_BACKEND_ENV
from agentkit.backend.state_backend.sqlite_store import _connect, state_db_path_for
from agentkit.backend.state_backend.store import reset_backend_cache_for_tests

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
    path = tmp_path / "stories" / "SKILL-BIND-TEST"
    path.mkdir(parents=True, exist_ok=True)
    return path


class TestBootstrapIdempotent:
    def test_table_present_after_bootstrap(self, story_dir: Path) -> None:
        with _connect(story_dir) as conn:
            result = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' "
                "AND name='skill_bindings'"
            ).fetchone()
        assert result is not None

    def test_double_bootstrap_no_error(self, story_dir: Path) -> None:
        for _ in range(3):
            with _connect(story_dir) as conn:
                assert (
                    conn.execute(
                        "SELECT name FROM sqlite_master WHERE type='table' "
                        "AND name='skill_bindings'"
                    ).fetchone()
                    is not None
                )

    def test_index_created(self, story_dir: Path) -> None:
        with _connect(story_dir) as conn:
            indices = {
                row[0]
                for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='index'"
                ).fetchall()
            }
        assert "idx_skill_bindings_project_skill" in indices


class TestColumnContract:
    def test_columns_match_model(self, story_dir: Path) -> None:
        with _connect(story_dir) as conn:
            cols = {
                str(row[1]): {"notnull": bool(row[3]), "pk": int(row[5])}
                for row in conn.execute(
                    "PRAGMA table_info(skill_bindings)"
                ).fetchall()
            }
        for name in (
            "binding_id",
            "project_key",
            "skill_name",
            "bundle_id",
            "bundle_version",
            "target_path",
            "binding_mode",
            "status",
            "pinned_at",
        ):
            assert name in cols, f"missing column {name}"
            assert cols[name]["notnull"], f"{name} must be NOT NULL"
        assert cols["binding_id"]["pk"] == 1
        # No invented manifest_digest column (the model is owner of the shape).
        assert "manifest_digest" not in cols

    def test_unique_project_skill(self, story_dir: Path) -> None:
        row = (
            "b1",
            "proj-a",
            "execute-userstory",
            "core",
            "1.0",
            "/x",
            "SYMLINK",
            "BOUND",
            "2026-06-01T12:00:00+00:00",
        )
        cols = (
            "binding_id, project_key, skill_name, bundle_id, bundle_version, "
            "target_path, binding_mode, status, pinned_at"
        )
        insert = f"INSERT INTO skill_bindings ({cols}) VALUES (?,?,?,?,?,?,?,?,?)"
        with _connect(story_dir) as conn:
            conn.execute(insert, row)
            conn.commit()
        # Same (project_key, skill_name), different binding_id -> UNIQUE violation.
        dup = ("b2", *row[1:])
        with _connect(story_dir) as conn, pytest.raises(sqlite3.IntegrityError):
            conn.execute(insert, dup)
            conn.commit()


class TestCheckConstraints:
    _COLS = (
        "binding_id, project_key, skill_name, bundle_id, bundle_version, "
        "target_path, binding_mode, status, pinned_at"
    )
    _INSERT = f"INSERT INTO skill_bindings ({_COLS}) VALUES (?,?,?,?,?,?,?,?,?)"
    _VALID = (
        "b1",
        "proj-a",
        "execute-userstory",
        "core",
        "1.0",
        "/x",
        "SYMLINK",
        "BOUND",
        "2026-06-01T12:00:00+00:00",
    )

    def test_valid_row_inserts(self, story_dir: Path) -> None:
        with _connect(story_dir) as conn:
            conn.execute(self._INSERT, self._VALID)
            conn.commit()
            count = conn.execute(
                "SELECT COUNT(*) FROM skill_bindings"
            ).fetchone()[0]
        assert count == 1

    @pytest.mark.parametrize("status", [s.value for s in SkillLifecycleStatus])
    def test_all_six_status_values_accepted(
        self, story_dir: Path, status: str
    ) -> None:
        row = ("b1", "proj-a", status, "core", "1.0", "/x", "SYMLINK", status,
               "2026-06-01T12:00:00+00:00")
        with _connect(story_dir) as conn:
            conn.execute(self._INSERT, row)
            conn.commit()
            got = conn.execute(
                "SELECT status FROM skill_bindings WHERE binding_id='b1'"
            ).fetchone()[0]
        assert got == status

    def test_rejects_invalid_status(self, story_dir: Path) -> None:
        bad = (*self._VALID[:7], "NOT_A_STATUS", self._VALID[8])
        with _connect(story_dir) as conn, pytest.raises(sqlite3.IntegrityError):
            conn.execute(self._INSERT, bad)
            conn.commit()

    def test_rejects_non_symlink_mode(self, story_dir: Path) -> None:
        bad = (*self._VALID[:6], "COPY", *self._VALID[7:])
        with _connect(story_dir) as conn, pytest.raises(sqlite3.IntegrityError):
            conn.execute(self._INSERT, bad)
            conn.commit()


class TestSideBySideMigration:
    def test_old_schema_db_untouched(self, tmp_path: Path) -> None:
        old_dir = tmp_path / "stories" / "OLD"
        old_dir.mkdir(parents=True, exist_ok=True)
        old_db = old_dir / "agentkit_3_13_0.sqlite"
        with sqlite3.connect(str(old_db)) as conn:
            conn.execute("CREATE TABLE dummy (id TEXT PRIMARY KEY)")
            conn.commit()

        new_db = state_db_path_for(old_dir)
        from agentkit.backend.state_backend.config import versioned_sqlite_db_file

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
        assert "skill_bindings" not in tables
        assert "dummy" in tables
