"""Contract tests for StateBackendFcPatternRepository (Postgres canonical).

AG3-040 Sub-Block (b), FK-41 §41.3.2 — Roundtrip against real Postgres (the
canonical backend). Mirrors ``test_skill_binding_repository_postgres.py``:
skips when neither an explicit Postgres env nor docker is available.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest

from agentkit.core_types import FailureCategory, PatternStatus
from agentkit.failure_corpus.pattern import (
    FailurePatternRecord,
    PatternRiskLevel,
    PromotionRule,
)
from agentkit.state_backend.store.fc_pattern_repository import (
    StateBackendFcPatternRepository,
)

if TYPE_CHECKING:
    from pathlib import Path

pytest_plugins = ("tests.fixtures.postgres_backend",)

_NOW = datetime(2026, 6, 1, 12, 0, 0, tzinfo=UTC)


def _make_pattern(
    *,
    pattern_id: str,
    project_key: str = "proj-pg",
    status: PatternStatus = PatternStatus.CANDIDATE,
) -> FailurePatternRecord:
    # FK-41 §41.3.2:239: 'accepted' erfordert confirmed_by='human'.
    accepted = status is PatternStatus.ACCEPTED
    return FailurePatternRecord(
        pattern_id=pattern_id,
        project_key=project_key,
        status=status,
        category=FailureCategory.SCOPE_DRIFT,
        invariant="inv",
        incident_refs=["FC-2026-0001"],
        promotion_rule=PromotionRule.WIEDERHOLUNG,
        risk_level=PatternRiskLevel.HOCH,
        incident_count=1,
        confirmed_at=_NOW if accepted else None,
        confirmed_by="human" if accepted else None,
    )


@pytest.mark.contract
def test_postgres_fc_pattern_roundtrip(
    tmp_path: Path,
    postgres_backend_env: object,
) -> None:
    repo = StateBackendFcPatternRepository(store_dir=tmp_path)
    pattern = _make_pattern(pattern_id="FP-1001")
    repo.save(pattern)
    loaded = repo.load("FP-1001")
    assert loaded is not None
    assert loaded == pattern
    assert loaded.status is PatternStatus.CANDIDATE
    assert loaded.incident_refs == ["FC-2026-0001"]


@pytest.mark.contract
def test_postgres_fc_pattern_upsert(
    tmp_path: Path,
    postgres_backend_env: object,
) -> None:
    repo = StateBackendFcPatternRepository(store_dir=tmp_path)
    repo.save(_make_pattern(pattern_id="FP-1002", status=PatternStatus.CANDIDATE))
    repo.save(_make_pattern(pattern_id="FP-1002", status=PatternStatus.ACCEPTED))
    loaded = repo.load("FP-1002")
    assert loaded is not None
    assert loaded.status is PatternStatus.ACCEPTED


@pytest.mark.contract
def test_postgres_fc_pattern_list_sorted(
    tmp_path: Path,
    postgres_backend_env: object,
) -> None:
    repo = StateBackendFcPatternRepository(store_dir=tmp_path)
    pk = "proj-pg-fp-list"
    for pid in ("FP-1203", "FP-1201", "FP-1202"):
        repo.save(_make_pattern(pattern_id=pid, project_key=pk))
    ids = [p.pattern_id for p in repo.list_for_project(pk)]
    assert ids == ["FP-1201", "FP-1202", "FP-1203"]


# ---------------------------------------------------------------------------
# WARNING 2 — Postgres CHECK parity (mirrors the SQLite TestCheckConstraints):
# direct DB writes that bypass Pydantic must still be rejected fail-closed.
# ---------------------------------------------------------------------------

_PATTERN_COLUMNS = (
    "pattern_id, project_key, status, category, invariant, incident_refs, "
    "promotion_rule, risk_level, incident_count"
)
_PATTERN_INSERT = (
    f"INSERT INTO fc_patterns ({_PATTERN_COLUMNS}) "
    "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)"
)
_PATTERN_VALID = (
    "FP-3001",
    "proj-pg",
    "candidate",
    "scope_drift",
    "inv",
    '["FC-2026-0001"]',
    "wiederholung",
    "hoch",
    1,
)


def _pg_raw_insert_pattern(values: tuple[object, ...]) -> None:
    """Raw INSERT into fc_patterns via the canonical Postgres connect path."""
    import psycopg

    from agentkit.state_backend.store.projection_repositories import _postgres_connect

    with pytest.raises(psycopg.errors.Error), _postgres_connect() as conn:
        conn.execute(_PATTERN_INSERT, values)


@pytest.mark.contract
def test_postgres_rejects_bad_pattern_id(postgres_backend_env: object) -> None:
    bad = ("FP-1", *_PATTERN_VALID[1:])
    _pg_raw_insert_pattern(bad)


@pytest.mark.contract
def test_postgres_rejects_non_string_incident_ref(
    postgres_backend_env: object,
) -> None:
    bad = (*_PATTERN_VALID[:5], "[1, 2]", *_PATTERN_VALID[6:])
    _pg_raw_insert_pattern(bad)


@pytest.mark.contract
def test_postgres_rejects_accepted_without_human(
    postgres_backend_env: object,
) -> None:
    """FK-41 §41.3.2:239: 'accepted' ohne confirmed_by='human' wird abgelehnt."""
    bad = (*_PATTERN_VALID[:2], "accepted", *_PATTERN_VALID[3:])
    _pg_raw_insert_pattern(bad)
