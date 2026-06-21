"""SQLite roundtrip + CHECK tests for StateBackendFcPatternRepository (AG3-040 (b)).

Unit-Pfad ist SQLite-only (tests/unit/conftest.py erzwingt sqlite + loescht die
Postgres-DSN). Der kanonische Postgres-Roundtrip liegt im Contract-Test
``tests/contract/state_backend/test_fc_pattern_repository_postgres.py`` (analog
``test_skill_binding_repository_postgres.py``).

Verifiziert (FK-41 §41.3.2, AG3-040 AK2):
- save -> load roundtrip mit allen Feldern intakt (Enums by value,
  incident_refs list[str], tz-aware datetimes)
- save upsert auf pattern_id (in-place update)
- list_for_project sortiert + projektisoliert
- Protocol-Erfuellung (StateBackendFcPatternRepository IS-A FcPatternRepository)
- fail-closed DB-CHECKs (status, category, promotion_rule, risk_level,
  pattern_id-Format, incident_refs string-array)
"""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest

from agentkit.backend.core_types import FailureCategory, PatternStatus
from agentkit.backend.failure_corpus.pattern import (
    FailurePatternRecord,
    PatternRiskLevel,
    PromotionRule,
)
from agentkit.backend.state_backend.config import ALLOW_SQLITE_ENV, STATE_BACKEND_ENV
from agentkit.backend.state_backend.store import reset_backend_cache_for_tests
from agentkit.backend.state_backend.store.fc_pattern_repository import (
    FcPatternRepository,
    StateBackendFcPatternRepository,
)

if TYPE_CHECKING:
    from collections.abc import Generator
    from pathlib import Path

_NOW = datetime(2026, 6, 1, 12, 0, 0, tzinfo=UTC)


def _seed_check(tmp_path: Path, *, check_id: str, pattern_ref: str) -> None:
    """Persistiere ein Check-Proposal als FK-Ziel fuer fc_patterns.check_ref."""
    from agentkit.backend.core_types import CheckStatus, CheckType
    from agentkit.backend.failure_corpus.check_proposal import (
        CheckProposalRecord,
        FalsePositiveRisk,
    )
    from agentkit.backend.state_backend.store.fc_check_proposal_repository import (
        StateBackendFcCheckProposalRepository,
    )

    StateBackendFcCheckProposalRepository(tmp_path).save(
        CheckProposalRecord(
            check_id=check_id,
            project_key="proj-a",
            status=CheckStatus.DRAFT,
            pattern_ref=pattern_ref,
            invariant="inv",
            check_type=CheckType.CHANGED_FILE_POLICY,
            pipeline_stage="structural",
            pipeline_layer=1,
            owner="team-x",
            false_positive_risk=FalsePositiveRisk.LOW,
            positive_fixtures=[],
            negative_fixtures=[],
            created_at=_NOW,
        )
    )


def _make_pattern(
    *,
    pattern_id: str = "FP-0001",
    project_key: str = "proj-a",
    status: PatternStatus = PatternStatus.CANDIDATE,
    incident_refs: list[str] | None = None,
) -> FailurePatternRecord:
    # FK-41 §41.3.2:239: 'accepted' erfordert confirmed_by='human'. Setze den
    # menschlichen Marker abhaengig vom Status, damit der Lifecycle-Invarianten-
    # CHECK (DB) und der Pydantic-model_validator nicht greifen.
    accepted = status is PatternStatus.ACCEPTED
    return FailurePatternRecord(
        pattern_id=pattern_id,
        project_key=project_key,
        status=status,
        category=FailureCategory.SCOPE_DRIFT,
        invariant="Bugfix-Stories aendern nur das betroffene Modul",
        incident_refs=incident_refs if incident_refs is not None else ["FC-2026-0001"],
        promotion_rule=PromotionRule.REPETITION,
        risk_level=PatternRiskLevel.HIGH,
        incident_count=1,
        confirmed_at=_NOW if accepted else None,
        confirmed_by="human" if accepted else None,
    )


@pytest.fixture(autouse=True)
def sqlite_env(monkeypatch: pytest.MonkeyPatch) -> Generator[None, None, None]:
    monkeypatch.setenv(STATE_BACKEND_ENV, "sqlite")
    monkeypatch.setenv(ALLOW_SQLITE_ENV, "1")
    reset_backend_cache_for_tests()
    yield
    reset_backend_cache_for_tests()


def _sqlite(tmp_path: Path) -> sqlite3.Connection:
    from agentkit.backend.state_backend.sqlite_store import _connect

    return _connect(tmp_path)  # type: ignore[return-value]


# ---------------------------------------------------------------------------
# Protocol satisfaction
# ---------------------------------------------------------------------------


def test_satisfies_protocol(tmp_path: Path) -> None:
    repo = StateBackendFcPatternRepository(tmp_path)
    assert isinstance(repo, FcPatternRepository)


# ---------------------------------------------------------------------------
# Pydantic id-format validation (ASCII-only, deckungsgleich mit DB-CHECK)
# ---------------------------------------------------------------------------


def test_model_rejects_unicode_digit_pattern_id() -> None:
    """FK-41 §41.3.2: pattern_id ist ASCII-``[0-9]``, nicht ``\\d``.

    Fullwidth-Ziffern (``FP-１２３４``) wuerden ``\\d`` matchen, aber der DB-CHECK
    nutzt ``[0-9]`` -> sie muessen bereits vom Pydantic-Validator abgelehnt
    werden, damit Pydantic und DB exakt uebereinstimmen.
    """
    from pydantic import ValidationError

    with pytest.raises(ValidationError, match="pattern_id must match"):
        _make_pattern(pattern_id="FP-１２３４")


# ---------------------------------------------------------------------------
# SQLite roundtrip
# ---------------------------------------------------------------------------


class TestSqliteRoundtrip:
    def test_save_and_load(self, tmp_path: Path) -> None:
        repo = StateBackendFcPatternRepository(tmp_path)
        pattern = _make_pattern()
        repo.save(pattern)
        loaded = repo.load("FP-0001")
        assert loaded is not None
        assert loaded == pattern
        assert loaded.status is PatternStatus.CANDIDATE
        assert loaded.category is FailureCategory.SCOPE_DRIFT
        assert loaded.promotion_rule is PromotionRule.REPETITION
        assert loaded.risk_level is PatternRiskLevel.HIGH
        assert loaded.incident_refs == ["FC-2026-0001"]

    def test_confirmed_fields_survive(self, tmp_path: Path) -> None:
        """Roundtrip mit gesetztem check_ref exercising the circular FK.

        FK-41 §41.3.2:234: check_ref -> fc_check_proposals(check_id). Da das
        Check-Proposal seinerseits pattern_ref -> fc_patterns(pattern_id)
        verlangt, wird die zirkulaere FK in drei Schritten aufgeloest: Pattern
        ohne check_ref -> Check (pattern_ref=FP-0009) -> Pattern-Upsert mit
        check_ref=CHK-0001.
        """
        repo = StateBackendFcPatternRepository(tmp_path)
        base = FailurePatternRecord(
            pattern_id="FP-0009",
            project_key="proj-a",
            status=PatternStatus.ACCEPTED,
            category=FailureCategory.TEST_OMISSION,
            invariant="E2E-Evidenz muss Exit-Code enthalten",
            incident_refs=["FC-2026-0001", "FC-2026-0002"],
            promotion_rule=PromotionRule.FAVORABLE_CHECKABILITY,
            risk_level=PatternRiskLevel.CRITICAL,
            incident_count=2,
            confirmed_at=_NOW,
            confirmed_by="human",
            owner="team-x",
        )
        repo.save(base)
        _seed_check(tmp_path, check_id="CHK-0001", pattern_ref="FP-0009")
        pattern = base.model_copy(update={"check_ref": "CHK-0001"})
        repo.save(pattern)
        loaded = repo.load("FP-0009")
        assert loaded is not None
        assert loaded == pattern
        assert loaded.confirmed_at == _NOW
        assert loaded.confirmed_by == "human"
        assert loaded.check_ref == "CHK-0001"

    def test_load_missing_returns_none(self, tmp_path: Path) -> None:
        repo = StateBackendFcPatternRepository(tmp_path)
        assert repo.load("FP-9999") is None

    def test_upsert_on_pattern_id(self, tmp_path: Path) -> None:
        repo = StateBackendFcPatternRepository(tmp_path)
        repo.save(_make_pattern(status=PatternStatus.CANDIDATE))
        repo.save(_make_pattern(status=PatternStatus.ACCEPTED))
        loaded = repo.load("FP-0001")
        assert loaded is not None
        assert loaded.status is PatternStatus.ACCEPTED
        assert len(repo.list_for_project("proj-a")) == 1

    def test_list_for_project_sorted_and_isolated(self, tmp_path: Path) -> None:
        repo = StateBackendFcPatternRepository(tmp_path)
        repo.save(_make_pattern(pattern_id="FP-0003", project_key="proj-a"))
        repo.save(_make_pattern(pattern_id="FP-0001", project_key="proj-a"))
        repo.save(_make_pattern(pattern_id="FP-0002", project_key="proj-b"))
        ids = [p.pattern_id for p in repo.list_for_project("proj-a")]
        assert ids == ["FP-0001", "FP-0003"]
        assert len(repo.list_for_project("proj-b")) == 1


# ---------------------------------------------------------------------------
# fail-closed DB CHECKs
# ---------------------------------------------------------------------------


class TestCheckConstraints:
    _COLUMNS = (
        "pattern_id, project_key, status, category, invariant, incident_refs, "
        "promotion_rule, risk_level, incident_count"
    )
    _INSERT = (
        f"INSERT INTO fc_patterns ({_COLUMNS}) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)"
    )
    _VALID = (
        "FP-0001",
        "proj-a",
        "candidate",
        "scope_drift",
        "inv",
        '["FC-2026-0001"]',
        "repetition",
        "high",
        1,
    )

    def test_valid_row_inserts(self, tmp_path: Path) -> None:
        with _sqlite(tmp_path) as conn:
            conn.execute(self._INSERT, self._VALID)
            conn.commit()
            count = conn.execute("SELECT COUNT(*) FROM fc_patterns").fetchone()[0]
        assert count == 1

    def test_rejects_invalid_status(self, tmp_path: Path) -> None:
        bad = (*self._VALID[:2], "promoted", *self._VALID[3:])
        with _sqlite(tmp_path) as conn, pytest.raises(sqlite3.IntegrityError):
            conn.execute(self._INSERT, bad)
            conn.commit()

    def test_rejects_invalid_category(self, tmp_path: Path) -> None:
        bad = (*self._VALID[:3], "not_a_cat", *self._VALID[4:])
        with _sqlite(tmp_path) as conn, pytest.raises(sqlite3.IntegrityError):
            conn.execute(self._INSERT, bad)
            conn.commit()

    def test_rejects_invalid_promotion_rule(self, tmp_path: Path) -> None:
        bad = (*self._VALID[:6], "wiederholung", *self._VALID[7:])
        with _sqlite(tmp_path) as conn, pytest.raises(sqlite3.IntegrityError):
            conn.execute(self._INSERT, bad)
            conn.commit()

    def test_rejects_invalid_risk_level(self, tmp_path: Path) -> None:
        bad = (*self._VALID[:7], "hoch", *self._VALID[8:])
        with _sqlite(tmp_path) as conn, pytest.raises(sqlite3.IntegrityError):
            conn.execute(self._INSERT, bad)
            conn.commit()

    def test_rejects_bad_pattern_id(self, tmp_path: Path) -> None:
        bad = ("FP-1", *self._VALID[1:])
        with _sqlite(tmp_path) as conn, pytest.raises(sqlite3.IntegrityError):
            conn.execute(self._INSERT, bad)
            conn.commit()

    def test_rejects_non_human_confirmed_by(self, tmp_path: Path) -> None:
        cols = self._COLUMNS + ", confirmed_by"
        sql = f"INSERT INTO fc_patterns ({cols}) VALUES (?,?,?,?,?,?,?,?,?,?)"
        bad = (*self._VALID, "robot")
        with _sqlite(tmp_path) as conn, pytest.raises(sqlite3.IntegrityError):
            conn.execute(sql, bad)
            conn.commit()

    def test_rejects_accepted_without_human_confirmation(self, tmp_path: Path) -> None:
        """FK-41 §41.3.2:239: 'accepted' ohne confirmed_by='human' wird abgelehnt.

        Direkter DB-Insert (umgeht Pydantic) -> der konditionale CHECK
        fc_patterns_accepted_human muss fail-closed greifen.
        """
        bad = (*self._VALID[:2], "accepted", *self._VALID[3:])
        with _sqlite(tmp_path) as conn, pytest.raises(sqlite3.IntegrityError):
            conn.execute(self._INSERT, bad)
            conn.commit()

    def test_accepted_with_human_confirmation_inserts(self, tmp_path: Path) -> None:
        """Gegenprobe: 'accepted' MIT confirmed_by='human' wird akzeptiert."""
        cols = self._COLUMNS + ", confirmed_by"
        sql = f"INSERT INTO fc_patterns ({cols}) VALUES (?,?,?,?,?,?,?,?,?,?)"
        row = (*self._VALID[:2], "accepted", *self._VALID[3:], "human")
        with _sqlite(tmp_path) as conn:
            conn.execute(sql, row)
            conn.commit()
            count = conn.execute("SELECT COUNT(*) FROM fc_patterns").fetchone()[0]
        assert count == 1

    def test_rejects_unknown_check_ref_fk(self, tmp_path: Path) -> None:
        """FK-41 §41.3.2:234: check_ref -> fc_check_proposals(check_id) ist FK.

        Ein check_ref auf ein nicht existierendes Check-Proposal wird DB-seitig
        fail-closed abgelehnt (PRAGMA foreign_keys=ON; zirkulaere FK, beide
        nullable, aber bei gesetztem Wert erzwungen).
        """
        cols = self._COLUMNS + ", check_ref"
        sql = f"INSERT INTO fc_patterns ({cols}) VALUES (?,?,?,?,?,?,?,?,?,?)"
        bad = (*self._VALID, "CHK-9999")
        with _sqlite(tmp_path) as conn, pytest.raises(sqlite3.IntegrityError):
            conn.execute(sql, bad)
            conn.commit()

    def test_rejects_non_string_incident_ref(self, tmp_path: Path) -> None:
        bad = (*self._VALID[:5], "[1, 2]", *self._VALID[6:])
        with _sqlite(tmp_path) as conn, pytest.raises(
            (sqlite3.IntegrityError, sqlite3.OperationalError)
        ):
            conn.execute(self._INSERT, bad)
            conn.commit()

    def test_rejects_non_array_incident_refs(self, tmp_path: Path) -> None:
        bad = (*self._VALID[:5], '{"k": "v"}', *self._VALID[6:])
        with _sqlite(tmp_path) as conn, pytest.raises(
            (sqlite3.IntegrityError, sqlite3.OperationalError)
        ):
            conn.execute(self._INSERT, bad)
            conn.commit()

    def test_duplicate_pattern_id_rejected(self, tmp_path: Path) -> None:
        with _sqlite(tmp_path) as conn:
            conn.execute(self._INSERT, self._VALID)
            conn.commit()
        with _sqlite(tmp_path) as conn, pytest.raises(sqlite3.IntegrityError):
            conn.execute(self._INSERT, self._VALID)
            conn.commit()
