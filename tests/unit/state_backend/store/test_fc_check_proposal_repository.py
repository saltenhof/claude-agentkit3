"""SQLite roundtrip + CHECK tests for StateBackendFcCheckProposalRepository (AG3-040 (b)).

Unit-Pfad ist SQLite-only (tests/unit/conftest.py erzwingt sqlite + loescht die
Postgres-DSN). Der kanonische Postgres-Roundtrip liegt im Contract-Test
``tests/contract/state_backend/test_fc_check_proposal_repository_postgres.py``.

Verifiziert (FK-41 §41.3.3, AG3-040 AK2):
- save -> load roundtrip mit allen Feldern intakt (Enums by value, fixtures
  list[dict], tz-aware datetimes)
- save upsert auf check_id (in-place update)
- list_for_pattern sortiert
- pattern_ref FK -> fc_patterns(pattern_id) (fail-closed bei unbekanntem Pattern)
- Protocol-Erfuellung
- fail-closed DB-CHECKs (status, check_type, false_positive_risk,
  check_id-Format, fixtures-array)
"""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

import pytest

from agentkit.core_types import (
    CheckStatus,
    CheckType,
    FailureCategory,
    PatternStatus,
)
from agentkit.failure_corpus.check_proposal import (
    CheckProposalRecord,
    FalsePositiveRisk,
)
from agentkit.failure_corpus.pattern import (
    FailurePatternRecord,
    PatternRiskLevel,
    PromotionRule,
)
from agentkit.state_backend.config import ALLOW_SQLITE_ENV, STATE_BACKEND_ENV
from agentkit.state_backend.store import reset_backend_cache_for_tests
from agentkit.state_backend.store.fc_check_proposal_repository import (
    FcCheckProposalRepository,
    StateBackendFcCheckProposalRepository,
)
from agentkit.state_backend.store.fc_pattern_repository import (
    StateBackendFcPatternRepository,
)

if TYPE_CHECKING:
    from collections.abc import Generator
    from pathlib import Path

_NOW = datetime(2026, 6, 1, 12, 0, 0, tzinfo=UTC)

_FIXTURES: list[dict[str, Any]] = [
    {"description": "Bugfix aendert nur betroffenes Modul", "expected": "PASS"},
]


def _seed_pattern(tmp_path: Path, pattern_id: str = "FP-0001") -> None:
    """Persistiere ein Pattern als FK-Ziel fuer fc_check_proposals.pattern_ref."""
    StateBackendFcPatternRepository(tmp_path).save(
        FailurePatternRecord(
            pattern_id=pattern_id,
            project_key="proj-a",
            status=PatternStatus.ACCEPTED,
            category=FailureCategory.SCOPE_DRIFT,
            invariant="inv",
            incident_refs=["FC-2026-0001"],
            promotion_rule=PromotionRule.WIEDERHOLUNG,
            risk_level=PatternRiskLevel.HOCH,
            incident_count=1,
            # FK-41 §41.3.2:239: 'accepted' erfordert confirmed_by='human'.
            confirmed_at=_NOW,
            confirmed_by="human",
        )
    )


def _make_proposal(
    *,
    check_id: str = "CHK-0001",
    pattern_ref: str = "FP-0001",
    status: CheckStatus = CheckStatus.DRAFT,
) -> CheckProposalRecord:
    # FK-41 §41.3.3:282: 'approved'/'active' erfordert approved_by='human'. Setze
    # den menschlichen Marker abhaengig vom Status, damit der Lifecycle-
    # Invarianten-CHECK (DB) und der Pydantic-model_validator nicht greifen.
    needs_human = status in (CheckStatus.APPROVED, CheckStatus.ACTIVE)
    return CheckProposalRecord(
        check_id=check_id,
        project_key="proj-a",
        status=status,
        pattern_ref=pattern_ref,
        invariant="Bugfix-Stories: keine Dateien ausserhalb des Moduls",
        check_type=CheckType.CHANGED_FILE_POLICY,
        pipeline_stage="structural",
        pipeline_layer=1,
        owner="team-trading",
        false_positive_risk=FalsePositiveRisk.NIEDRIG,
        positive_fixtures=_FIXTURES,
        negative_fixtures=[],
        created_at=_NOW,
        approved_at=_NOW if needs_human else None,
        approved_by="human" if needs_human else None,
    )


@pytest.fixture(autouse=True)
def sqlite_env(monkeypatch: pytest.MonkeyPatch) -> Generator[None, None, None]:
    monkeypatch.setenv(STATE_BACKEND_ENV, "sqlite")
    monkeypatch.setenv(ALLOW_SQLITE_ENV, "1")
    reset_backend_cache_for_tests()
    yield
    reset_backend_cache_for_tests()


def _sqlite(tmp_path: Path) -> sqlite3.Connection:
    from agentkit.state_backend.sqlite_store import _connect

    return _connect(tmp_path)  # type: ignore[return-value]


# ---------------------------------------------------------------------------
# Protocol satisfaction
# ---------------------------------------------------------------------------


def test_satisfies_protocol(tmp_path: Path) -> None:
    repo = StateBackendFcCheckProposalRepository(tmp_path)
    assert isinstance(repo, FcCheckProposalRepository)


# ---------------------------------------------------------------------------
# Pydantic id-format validation (ASCII-only, deckungsgleich mit DB-CHECK)
# ---------------------------------------------------------------------------


def test_model_rejects_unicode_digit_check_id() -> None:
    """FK-41 §41.3.3: check_id ist ASCII-``[0-9]``, nicht ``\\d``.

    Fullwidth-Ziffern (``CHK-１２３４``) wuerden ``\\d`` matchen, aber der DB-CHECK
    nutzt ``[0-9]`` -> sie muessen bereits vom Pydantic-Validator abgelehnt
    werden, damit Pydantic und DB exakt uebereinstimmen.
    """
    from pydantic import ValidationError

    with pytest.raises(ValidationError, match="check_id must match"):
        _make_proposal(check_id="CHK-１２３４")


# ---------------------------------------------------------------------------
# SQLite roundtrip
# ---------------------------------------------------------------------------


class TestSqliteRoundtrip:
    def test_save_and_load(self, tmp_path: Path) -> None:
        _seed_pattern(tmp_path)
        repo = StateBackendFcCheckProposalRepository(tmp_path)
        proposal = _make_proposal()
        repo.save(proposal)
        loaded = repo.load("CHK-0001")
        assert loaded is not None
        assert loaded == proposal
        assert loaded.status is CheckStatus.DRAFT
        assert loaded.check_type is CheckType.CHANGED_FILE_POLICY
        assert loaded.false_positive_risk is FalsePositiveRisk.NIEDRIG
        assert loaded.positive_fixtures == _FIXTURES
        assert loaded.negative_fixtures == []

    def test_optional_fields_survive(self, tmp_path: Path) -> None:
        _seed_pattern(tmp_path)
        repo = StateBackendFcCheckProposalRepository(tmp_path)
        proposal = CheckProposalRecord(
            check_id="CHK-0009",
            project_key="proj-a",
            status=CheckStatus.ACTIVE,
            pattern_ref="FP-0001",
            invariant="inv",
            check_type=CheckType.FIXTURE_REPLAY,
            pipeline_stage="structural",
            pipeline_layer=1,
            owner="team-x",
            false_positive_risk=FalsePositiveRisk.MITTEL,
            positive_fixtures=[],
            negative_fixtures=[],
            created_at=_NOW,
            approved_at=_NOW,
            approved_by="human",
            effectiveness_last_checked_at=_NOW,
            true_positives_90d=3,
            false_positives_90d=0,
        )
        repo.save(proposal)
        loaded = repo.load("CHK-0009")
        assert loaded is not None
        assert loaded == proposal
        assert loaded.approved_by == "human"
        assert loaded.true_positives_90d == 3

    def test_load_missing_returns_none(self, tmp_path: Path) -> None:
        repo = StateBackendFcCheckProposalRepository(tmp_path)
        assert repo.load("CHK-9999") is None

    def test_upsert_on_check_id(self, tmp_path: Path) -> None:
        _seed_pattern(tmp_path)
        repo = StateBackendFcCheckProposalRepository(tmp_path)
        repo.save(_make_proposal(status=CheckStatus.DRAFT))
        repo.save(_make_proposal(status=CheckStatus.APPROVED))
        loaded = repo.load("CHK-0001")
        assert loaded is not None
        assert loaded.status is CheckStatus.APPROVED
        assert len(repo.list_for_pattern("FP-0001")) == 1

    def test_list_for_pattern_sorted(self, tmp_path: Path) -> None:
        _seed_pattern(tmp_path, "FP-0001")
        _seed_pattern(tmp_path, "FP-0002")
        repo = StateBackendFcCheckProposalRepository(tmp_path)
        repo.save(_make_proposal(check_id="CHK-0003", pattern_ref="FP-0001"))
        repo.save(_make_proposal(check_id="CHK-0001", pattern_ref="FP-0001"))
        repo.save(_make_proposal(check_id="CHK-0002", pattern_ref="FP-0002"))
        ids = [p.check_id for p in repo.list_for_pattern("FP-0001")]
        assert ids == ["CHK-0001", "CHK-0003"]
        assert len(repo.list_for_pattern("FP-0002")) == 1


# ---------------------------------------------------------------------------
# fail-closed DB CHECKs + FK
# ---------------------------------------------------------------------------


class TestCheckConstraints:
    _COLUMNS = (
        "check_id, project_key, status, pattern_ref, invariant, check_type, "
        "pipeline_stage, pipeline_layer, owner, false_positive_risk, "
        "positive_fixtures, negative_fixtures, created_at"
    )
    _INSERT = (
        f"INSERT INTO fc_check_proposals ({_COLUMNS}) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"
    )

    def _valid(self) -> tuple[Any, ...]:
        return (
            "CHK-0001",
            "proj-a",
            "draft",
            "FP-0001",
            "inv",
            "Changed-File-Policy",
            "structural",
            1,
            "team-x",
            "niedrig",
            "[]",
            "[]",
            _NOW.isoformat(),
        )

    def test_valid_row_inserts(self, tmp_path: Path) -> None:
        _seed_pattern(tmp_path)
        with _sqlite(tmp_path) as conn:
            conn.execute(self._INSERT, self._valid())
            conn.commit()
            count = conn.execute(
                "SELECT COUNT(*) FROM fc_check_proposals"
            ).fetchone()[0]
        assert count == 1

    def test_rejects_invalid_status(self, tmp_path: Path) -> None:
        _seed_pattern(tmp_path)
        v = self._valid()
        bad = (*v[:2], "observed", *v[3:])
        with _sqlite(tmp_path) as conn, pytest.raises(sqlite3.IntegrityError):
            conn.execute(self._INSERT, bad)
            conn.commit()

    def test_rejects_invalid_check_type(self, tmp_path: Path) -> None:
        _seed_pattern(tmp_path)
        v = self._valid()
        bad = (*v[:5], "Unknown-Check", *v[6:])
        with _sqlite(tmp_path) as conn, pytest.raises(sqlite3.IntegrityError):
            conn.execute(self._INSERT, bad)
            conn.commit()

    def test_rejects_invalid_fp_risk(self, tmp_path: Path) -> None:
        _seed_pattern(tmp_path)
        v = self._valid()
        bad = (*v[:9], "low", *v[10:])
        with _sqlite(tmp_path) as conn, pytest.raises(sqlite3.IntegrityError):
            conn.execute(self._INSERT, bad)
            conn.commit()

    def test_rejects_bad_check_id(self, tmp_path: Path) -> None:
        _seed_pattern(tmp_path)
        v = self._valid()
        bad = ("CHK-1", *v[1:])
        with _sqlite(tmp_path) as conn, pytest.raises(sqlite3.IntegrityError):
            conn.execute(self._INSERT, bad)
            conn.commit()

    def test_rejects_non_array_fixtures(self, tmp_path: Path) -> None:
        _seed_pattern(tmp_path)
        v = self._valid()
        bad = (*v[:10], '{"k": "v"}', *v[11:])
        with _sqlite(tmp_path) as conn, pytest.raises(sqlite3.IntegrityError):
            conn.execute(self._INSERT, bad)
            conn.commit()

    @pytest.mark.parametrize(
        "bad_fixtures",
        [
            "[1]",  # scalar element
            '["x"]',  # string element
            "[{}]",  # object missing both keys
            '[{"description": "d"}]',  # missing 'expected'
            '[{"expected": "PASS"}]',  # missing 'description'
        ],
    )
    def test_rejects_malformed_fixture_element(
        self, tmp_path: Path, bad_fixtures: str
    ) -> None:
        """FK-41 §41.3.3:265-266: fixtures-Elemente MUESSEN {description, expected}.

        Direkter DB-Insert (umgeht Pydantic) eines fixtures-Werts, den der Repo-
        Decoder ablehnen wuerde -> der BEFORE-Trigger
        trg_fc_check_proposals_fixtures_insert muss fail-closed greifen (kein
        DB-state-the-repo-rejects-Loch). Geprueft fuer positive_fixtures.
        """
        _seed_pattern(tmp_path)
        v = self._valid()
        bad = (*v[:10], bad_fixtures, *v[11:])
        with _sqlite(tmp_path) as conn, pytest.raises(
            (sqlite3.IntegrityError, sqlite3.OperationalError)
        ):
            conn.execute(self._INSERT, bad)
            conn.commit()

    def test_rejects_malformed_negative_fixture_element(self, tmp_path: Path) -> None:
        """Gleicher Element-Shape-Trigger greift auch fuer negative_fixtures."""
        _seed_pattern(tmp_path)
        v = self._valid()
        bad = (*v[:11], "[{}]", *v[12:])
        with _sqlite(tmp_path) as conn, pytest.raises(
            (sqlite3.IntegrityError, sqlite3.OperationalError)
        ):
            conn.execute(self._INSERT, bad)
            conn.commit()

    def test_rejects_approved_without_human(self, tmp_path: Path) -> None:
        """FK-41 §41.3.3:282: 'approved' ohne approved_by='human' wird abgelehnt.

        Direkter DB-Insert (umgeht Pydantic) -> der konditionale CHECK
        fc_check_proposals_approved_human muss fail-closed greifen.
        """
        _seed_pattern(tmp_path)
        v = self._valid()
        bad = (*v[:2], "approved", *v[3:])
        with _sqlite(tmp_path) as conn, pytest.raises(sqlite3.IntegrityError):
            conn.execute(self._INSERT, bad)
            conn.commit()

    def test_rejects_active_without_human(self, tmp_path: Path) -> None:
        """FK-41 §41.3.3:282: 'active' erbt die approved_by='human'-Pflicht."""
        _seed_pattern(tmp_path)
        v = self._valid()
        bad = (*v[:2], "active", *v[3:])
        with _sqlite(tmp_path) as conn, pytest.raises(sqlite3.IntegrityError):
            conn.execute(self._INSERT, bad)
            conn.commit()

    def test_approved_with_human_inserts(self, tmp_path: Path) -> None:
        """Gegenprobe: 'approved' MIT approved_by='human' wird akzeptiert."""
        _seed_pattern(tmp_path)
        cols = self._COLUMNS + ", approved_by"
        sql = (
            f"INSERT INTO fc_check_proposals ({cols}) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)"
        )
        v = self._valid()
        row = (*v[:2], "approved", *v[3:], "human")
        with _sqlite(tmp_path) as conn:
            conn.execute(sql, row)
            conn.commit()
            count = conn.execute(
                "SELECT COUNT(*) FROM fc_check_proposals"
            ).fetchone()[0]
        assert count == 1

    def test_rejects_unknown_pattern_ref_fk(self, tmp_path: Path) -> None:
        """pattern_ref -> fc_patterns(pattern_id) FK is fail-closed (FK-41 §41.3.3)."""
        # No _seed_pattern: the referenced FP-0001 does not exist.
        v = self._valid()
        with _sqlite(tmp_path) as conn, pytest.raises(sqlite3.IntegrityError):
            conn.execute(self._INSERT, v)
            conn.commit()
