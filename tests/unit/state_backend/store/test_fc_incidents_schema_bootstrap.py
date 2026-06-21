"""Bootstrap-Idempotenz + exakter FK-41-§41.3.1-Vertrag fuer ``fc_incidents`` (AG3-028, AK#4).

Pinnt (Codex-r1 Remediation):
- zweimaliger Bootstrap ist fehlerfrei (CREATE TABLE IF NOT EXISTS)
- exakte FK-41-§41.3.1-Spalten + NOT-NULL + CHECK-Constraints (category/severity/
  role/incident_status)
- die beiden Indizes (project_key,story_id,run_id) und (incident_status)
- PK (UNIQUE incident_id): doppelter Insert -> IntegrityError (append-only)
- fc_incident_counters-Tabelle vorhanden (FC-YYYY-NNNN-Allokation)
- alte DB (anderer SCHEMA_VERSION-Slug) bleibt unangetastet (FK-18 §18.9a)
"""

from __future__ import annotations

import sqlite3
from typing import TYPE_CHECKING

import pytest

from agentkit.backend.state_backend.config import ALLOW_SQLITE_ENV, STATE_BACKEND_ENV
from agentkit.backend.state_backend.sqlite_store import _connect, state_db_path_for
from agentkit.backend.state_backend.store import reset_backend_cache_for_tests
from agentkit.backend.state_backend.store.fc_incident_repository import _decode_json_list

if TYPE_CHECKING:
    from collections.abc import Generator
    from pathlib import Path

# FK-41 §41.3.1 column order of the INSERT used by the repository adapter.
_COLUMNS = (
    "project_key, incident_id, run_id, story_id, category, severity, "
    "phase, role, model, symptom, evidence_json, recorded_at, "
    "incident_status, tags, impact, pattern_ref"
)
_INSERT = f"""
    INSERT INTO fc_incidents ({_COLUMNS})
    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
"""

_VALID_ROW = (
    "proj-a",                          # project_key
    "FC-2026-0001",                    # incident_id
    "run-1",                           # run_id
    "AG3-001",                         # story_id
    "scope_drift",                     # category
    "high",                            # severity
    "implementation",                  # phase
    "worker",                          # role
    "claude-opus",                     # model
    "scope exceeded",                  # symptom
    '["e1"]',                          # evidence_json (list[str])
    "2026-06-01T12:00:00+00:00",       # recorded_at
    "observed",                        # incident_status
    None,                              # tags
    None,                              # impact
    None,                              # pattern_ref
)


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

    def test_counter_table_present(self, story_dir: Path) -> None:
        with _connect(story_dir) as conn:
            result = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' "
                "AND name='fc_incident_counters'"
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
        assert "idx_fc_incidents_project_story_run" in indices
        assert "idx_fc_incidents_incident_status" in indices


class TestExactColumnContract:
    def test_columns_match_fk41(self, story_dir: Path) -> None:
        with _connect(story_dir) as conn:
            cols = {
                str(row[1]): {"notnull": bool(row[3])}
                for row in conn.execute(
                    "PRAGMA table_info(fc_incidents)"
                ).fetchall()
            }
        # Pflicht-Spalten (FK-41 §41.3.1) inkl. NOT NULL.
        for name in (
            "project_key",
            "incident_id",
            "run_id",
            "story_id",
            "category",
            "severity",
            "phase",
            "role",
            "model",
            "symptom",
            "evidence_json",
            "recorded_at",
            "incident_status",
        ):
            assert name in cols, f"missing column {name}"
            assert cols[name]["notnull"], f"{name} must be NOT NULL (FK-41 §41.3.1)"
        # Optionale Spalten (FK-41 §41.3.1) — vorhanden, nullbar.
        for name in ("tags", "impact", "pattern_ref"):
            assert name in cols, f"missing optional column {name}"
            assert not cols[name]["notnull"], f"{name} must be nullable"
        # Alt-Schema-Spalten duerfen NICHT mehr existieren.
        for stale in ("source_bc", "summary", "observed_at", "normalized_at"):
            assert stale not in cols, f"stale column {stale} must be gone"


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
                f"""
                INSERT INTO fc_incidents (
                    project_key, incident_id, run_id, story_id, category,
                    severity, phase, role, model, symptom, evidence_json,
                    recorded_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,  # noqa: F541
                (
                    "proj-a",
                    "FC-2026-0002",
                    "run-1",
                    "AG3-001",
                    "scope_drift",
                    "high",
                    "implementation",
                    "worker",
                    "m",
                    "s",
                    "[]",
                    "2026-06-01T12:00:00+00:00",
                ),
            )
            conn.commit()
            status = conn.execute(
                "SELECT incident_status FROM fc_incidents "
                "WHERE incident_id='FC-2026-0002'"
            ).fetchone()[0]
        assert status == "observed"

    def test_rejects_invalid_category(self, story_dir: Path) -> None:
        bad = (_VALID_ROW[0], "FC-2026-0003", *_VALID_ROW[2:4], "not_a_cat", *_VALID_ROW[5:])
        with _connect(story_dir) as conn, pytest.raises(sqlite3.IntegrityError):
            conn.execute(_INSERT, bad)
            conn.commit()

    def test_rejects_invalid_severity(self, story_dir: Path) -> None:
        # FK-27 Severity-Wert ist KEIN gueltiger IncidentSeverity-Wert.
        bad = (
            _VALID_ROW[0],
            "FC-2026-0004",
            *_VALID_ROW[2:5],
            "BLOCKING",
            *_VALID_ROW[6:],
        )
        with _connect(story_dir) as conn, pytest.raises(sqlite3.IntegrityError):
            conn.execute(_INSERT, bad)
            conn.commit()

    def test_rejects_invalid_role(self, story_dir: Path) -> None:
        bad = (
            _VALID_ROW[0],
            "FC-2026-0005",
            *_VALID_ROW[2:7],
            "admin",  # not in worker|qa|governance
            *_VALID_ROW[8:],
        )
        with _connect(story_dir) as conn, pytest.raises(sqlite3.IntegrityError):
            conn.execute(_INSERT, bad)
            conn.commit()

    def test_rejects_invalid_incident_status(self, story_dir: Path) -> None:
        bad = (
            _VALID_ROW[0],
            "FC-2026-0006",
            *_VALID_ROW[2:12],
            "monitoring",
            *_VALID_ROW[13:],
        )
        with _connect(story_dir) as conn, pytest.raises(sqlite3.IntegrityError):
            conn.execute(_INSERT, bad)
            conn.commit()

    def test_rejects_null_project_key(self, story_dir: Path) -> None:
        bad = (None, *_VALID_ROW[1:])
        with _connect(story_dir) as conn, pytest.raises(sqlite3.IntegrityError):
            conn.execute(_INSERT, bad)
            conn.commit()

    def test_rejects_null_run_id(self, story_dir: Path) -> None:
        bad = (*_VALID_ROW[:2], None, *_VALID_ROW[3:])
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

    def test_rejects_short_sequence_id(self, story_dir: Path) -> None:
        """FC-YYYY-NNNN braucht >= 4-stellige Sequenz; FC-2026-1 wird abgelehnt."""
        bad = (_VALID_ROW[0], "FC-2026-1", *_VALID_ROW[2:])
        with _connect(story_dir) as conn, pytest.raises(sqlite3.IntegrityError):
            conn.execute(_INSERT, bad)
            conn.commit()

    def test_rejects_nondigit_suffix_id(self, story_dir: Path) -> None:
        """Nicht-Ziffern-Suffix (FC-2026-0001x) wird vom DB-CHECK abgelehnt."""
        bad = (_VALID_ROW[0], "FC-2026-0001x", *_VALID_ROW[2:])
        with _connect(story_dir) as conn, pytest.raises(sqlite3.IntegrityError):
            conn.execute(_INSERT, bad)
            conn.commit()

    def test_rejects_object_evidence_element(self, story_dir: Path) -> None:
        """evidence_json mit Objekt-Element wird DB-seitig (Trigger) abgelehnt."""
        # index 10 == evidence_json
        bad = (*_VALID_ROW[:10], '[{"k": "v"}]', *_VALID_ROW[11:])
        with _connect(story_dir) as conn, pytest.raises(
            (sqlite3.IntegrityError, sqlite3.OperationalError)
        ):
            conn.execute(_INSERT, bad)
            conn.commit()

    def test_rejects_number_evidence_element(self, story_dir: Path) -> None:
        """evidence_json mit Number-Element wird DB-seitig (Trigger) abgelehnt."""
        bad = (*_VALID_ROW[:10], "[1, 2]", *_VALID_ROW[11:])
        with _connect(story_dir) as conn, pytest.raises(
            (sqlite3.IntegrityError, sqlite3.OperationalError)
        ):
            conn.execute(_INSERT, bad)
            conn.commit()

    def test_rejects_number_tags_element(self, story_dir: Path) -> None:
        """tags-Array mit Number-Element wird DB-seitig (Trigger) abgelehnt."""
        # index 13 == tags
        bad = (*_VALID_ROW[:13], "[1]", *_VALID_ROW[14:])
        with _connect(story_dir) as conn, pytest.raises(
            (sqlite3.IntegrityError, sqlite3.OperationalError)
        ):
            conn.execute(_INSERT, bad)
            conn.commit()

    @pytest.mark.parametrize("non_array_tags", ['"x"', '{"k": "v"}', "1"])
    def test_rejects_non_array_tags(
        self, story_dir: Path, non_array_tags: str
    ) -> None:
        """tags als JSON-Scalar/Objekt (kein Array) wird DB-seitig abgelehnt (CHECK).

        Codex-r6: ohne den tags-Array-CHECK wuerde json_each einen Scalar/ein
        Objekt faelschlich als text-Rows durchwinken.
        """
        bad = (*_VALID_ROW[:13], non_array_tags, *_VALID_ROW[14:])
        with _connect(story_dir) as conn, pytest.raises(
            (sqlite3.IntegrityError, sqlite3.OperationalError)
        ):
            conn.execute(_INSERT, bad)
            conn.commit()

    def test_accepts_valid_string_tags(self, story_dir: Path) -> None:
        """tags als JSON-Array aus Strings wird akzeptiert."""
        ok = (*_VALID_ROW[:13], '["t1", "t2"]', *_VALID_ROW[14:])
        with _connect(story_dir) as conn:
            conn.execute(_INSERT, ok)
            conn.commit()
            count = conn.execute("SELECT COUNT(*) FROM fc_incidents").fetchone()[0]
        assert count == 1


class TestEvidenceDecodeFailClosed:
    """``_decode_json_list`` ist fail-closed (NO ERROR BYPASSING): das frühere
    stille ``str()``-Coercion korrupter Persistenz ist entfernt. ``evidence``/
    ``tags`` sind FK-41 §41.4.1 ``list[str]``. Deckt die Backend-Luecke ab, die
    der SQLite-CHECK (kein Elementtyp im JSON-Array) nicht schliessen kann.
    """

    def test_string_list_decodes(self) -> None:
        assert _decode_json_list('["a", "b"]') == ["a", "b"]
        assert _decode_json_list(["a", "b"]) == ["a", "b"]
        assert _decode_json_list(None) == []
        assert _decode_json_list("") == []

    def test_object_element_rejected(self) -> None:
        with pytest.raises(ValueError, match="only strings"):
            _decode_json_list('[{"k": "v"}]')
        with pytest.raises(ValueError, match="only strings"):
            _decode_json_list([{"k": "v"}])

    def test_number_element_rejected(self) -> None:
        with pytest.raises(ValueError, match="only strings"):
            _decode_json_list("[1, 2]")

    def test_non_array_rejected(self) -> None:
        with pytest.raises(ValueError, match="JSON array"):
            _decode_json_list('{"k": "v"}')


class TestSideBySideMigration:
    def test_old_schema_db_untouched(self, tmp_path: Path) -> None:
        old_dir = tmp_path / "stories" / "OLD"
        old_dir.mkdir(parents=True, exist_ok=True)
        old_db = old_dir / "agentkit_3_9_0.sqlite"
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
        assert "fc_incidents" not in tables
        assert "dummy" in tables
