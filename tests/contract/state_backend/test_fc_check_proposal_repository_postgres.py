"""Contract tests for StateBackendFcCheckProposalRepository (Postgres canonical).

AG3-040 Sub-Block (b), FK-41 §41.3.3 — Roundtrip against real Postgres. Mirrors
``test_skill_binding_repository_postgres.py``: skips when neither an explicit
Postgres env nor docker is available. ``pattern_ref`` requires the referenced
fc_patterns row to exist first (FK-41 §41.3.3 FK).
"""

from __future__ import annotations

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
from agentkit.state_backend.store.fc_check_proposal_repository import (
    StateBackendFcCheckProposalRepository,
)
from agentkit.state_backend.store.fc_pattern_repository import (
    StateBackendFcPatternRepository,
)

if TYPE_CHECKING:
    from pathlib import Path

pytest_plugins = ("tests.fixtures.postgres_backend",)

_NOW = datetime(2026, 6, 1, 12, 0, 0, tzinfo=UTC)
_FIXTURES: list[dict[str, Any]] = [{"description": "d", "expected": "PASS"}]


def _seed_pattern(tmp_path: Path, pattern_id: str, project_key: str = "proj-pg") -> None:
    StateBackendFcPatternRepository(store_dir=tmp_path).save(
        FailurePatternRecord(
            pattern_id=pattern_id,
            project_key=project_key,
            status=PatternStatus.ACCEPTED,
            category=FailureCategory.SCOPE_DRIFT,
            invariant="inv",
            incident_refs=["FC-2026-0001"],
            promotion_rule=PromotionRule.REPETITION,
            risk_level=PatternRiskLevel.HIGH,
            incident_count=1,
            # FK-41 §41.3.2:239: 'accepted' erfordert confirmed_by='human'.
            confirmed_at=_NOW,
            confirmed_by="human",
        )
    )


def _make_proposal(
    *,
    check_id: str,
    pattern_ref: str,
    project_key: str = "proj-pg",
    status: CheckStatus = CheckStatus.DRAFT,
) -> CheckProposalRecord:
    # FK-41 §41.3.3:282: 'approved'/'active' erfordert approved_by='human'.
    needs_human = status in (CheckStatus.APPROVED, CheckStatus.ACTIVE)
    return CheckProposalRecord(
        check_id=check_id,
        project_key=project_key,
        status=status,
        pattern_ref=pattern_ref,
        invariant="inv",
        check_type=CheckType.CHANGED_FILE_POLICY,
        pipeline_stage="structural",
        pipeline_layer=1,
        owner="team-x",
        false_positive_risk=FalsePositiveRisk.LOW,
        positive_fixtures=_FIXTURES,
        negative_fixtures=[],
        created_at=_NOW,
        approved_at=_NOW if needs_human else None,
        approved_by="human" if needs_human else None,
    )


@pytest.mark.contract
def test_postgres_fc_check_proposal_roundtrip(
    tmp_path: Path,
    postgres_backend_env: object,
) -> None:
    _seed_pattern(tmp_path, "FP-2001")
    repo = StateBackendFcCheckProposalRepository(store_dir=tmp_path)
    proposal = _make_proposal(check_id="CHK-2001", pattern_ref="FP-2001")
    repo.save(proposal)
    loaded = repo.load("CHK-2001")
    assert loaded is not None
    assert loaded == proposal
    assert loaded.check_type is CheckType.CHANGED_FILE_POLICY
    assert loaded.positive_fixtures == _FIXTURES


@pytest.mark.contract
def test_postgres_fc_check_proposal_upsert(
    tmp_path: Path,
    postgres_backend_env: object,
) -> None:
    _seed_pattern(tmp_path, "FP-2002")
    repo = StateBackendFcCheckProposalRepository(store_dir=tmp_path)
    repo.save(
        _make_proposal(check_id="CHK-2002", pattern_ref="FP-2002", status=CheckStatus.DRAFT)
    )
    repo.save(
        _make_proposal(
            check_id="CHK-2002", pattern_ref="FP-2002", status=CheckStatus.APPROVED
        )
    )
    loaded = repo.load("CHK-2002")
    assert loaded is not None
    assert loaded.status is CheckStatus.APPROVED


@pytest.mark.contract
def test_postgres_fc_check_proposal_list_for_pattern(
    tmp_path: Path,
    postgres_backend_env: object,
) -> None:
    _seed_pattern(tmp_path, "FP-2003")
    repo = StateBackendFcCheckProposalRepository(store_dir=tmp_path)
    for cid in ("CHK-2103", "CHK-2101", "CHK-2102"):
        repo.save(_make_proposal(check_id=cid, pattern_ref="FP-2003"))
    ids = [p.check_id for p in repo.list_for_pattern("FP-2003")]
    assert ids == ["CHK-2101", "CHK-2102", "CHK-2103"]


@pytest.mark.contract
def test_postgres_max_check_seq_empty_store(
    tmp_path: Path,
    postgres_backend_env: object,
) -> None:
    """max_check_seq() returns 0 on an empty store (Postgres SQL branch).

    Global check_id allocator (FK-41 §41.3.3); the Postgres
    ``MAX(CAST(SUBSTRING(...)))`` branch must yield the documented empty value 0.
    """
    repo = StateBackendFcCheckProposalRepository(store_dir=tmp_path)
    assert repo.max_check_seq() == 0


@pytest.mark.contract
def test_postgres_max_check_seq_global_max(
    tmp_path: Path,
    postgres_backend_env: object,
) -> None:
    """max_check_seq() returns the global MAX(CHK-NNNN) suffix (Postgres SQL branch).

    Mirrors the SQLite coverage of the global check_id allocator (FK-41 §41.3.3):
    check_id is a GLOBAL identity, so the allocator spans ALL proposals. Seeds
    CHK-0001 and CHK-9999 and asserts the max suffix is 9999.
    """
    _seed_pattern(tmp_path, "FP-2004")
    repo = StateBackendFcCheckProposalRepository(store_dir=tmp_path)
    repo.save(_make_proposal(check_id="CHK-0001", pattern_ref="FP-2004"))
    repo.save(_make_proposal(check_id="CHK-9999", pattern_ref="FP-2004"))
    assert repo.max_check_seq() == 9999


# ---------------------------------------------------------------------------
# WARNING 2 — Postgres CHECK/FK parity (mirrors the SQLite TestCheckConstraints):
# direct DB writes that bypass Pydantic must still be rejected fail-closed.
# ---------------------------------------------------------------------------

_PATTERN_COLUMNS = (
    "pattern_id, project_key, status, category, invariant, incident_refs, "
    "promotion_rule, risk_level, incident_count"
)
_PATTERN_VALID = (
    "FP-4001",
    "proj-pg",
    "candidate",
    "scope_drift",
    "inv",
    '["FC-2026-0001"]',
    "repetition",
    "high",
    1,
)

_CHECK_COLUMNS = (
    "check_id, project_key, status, pattern_ref, invariant, check_type, "
    "pipeline_stage, pipeline_layer, owner, false_positive_risk, "
    "positive_fixtures, negative_fixtures, created_at"
)
_CHECK_INSERT = (
    f"INSERT INTO fc_check_proposals ({_CHECK_COLUMNS}) "
    "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)"
)


def _check_valid(pattern_ref: str = "FP-4001") -> tuple[object, ...]:
    return (
        "CHK-4001",
        "proj-pg",
        "draft",
        pattern_ref,
        "inv",
        "Changed-File-Policy",
        "structural",
        1,
        "team-x",
        "low",
        '[{"description": "d", "expected": "PASS"}]',
        "[]",
        _NOW.isoformat(),
    )


def _pg_raw_insert_check(values: tuple[object, ...]) -> None:
    """Raw INSERT into fc_check_proposals via the canonical Postgres connect path."""
    import psycopg

    from agentkit.state_backend.store.projection_repositories import _postgres_connect

    with pytest.raises(psycopg.errors.Error), _postgres_connect() as conn:
        conn.execute(_CHECK_INSERT, values)


@pytest.mark.contract
def test_postgres_rejects_bad_check_id(
    tmp_path: Path, postgres_backend_env: object
) -> None:
    _seed_pattern(tmp_path, "FP-4001")
    v = _check_valid()
    _pg_raw_insert_check(("CHK-1", *v[1:]))


@pytest.mark.contract
@pytest.mark.parametrize(
    "bad_fixtures",
    ["[1]", '["x"]', "[{}]", '[{"description": "d"}]'],
)
def test_postgres_rejects_malformed_fixture_element(
    tmp_path: Path, postgres_backend_env: object, bad_fixtures: str
) -> None:
    """FK-41 §41.3.3:265-266: each fixtures element must be {description, expected}."""
    _seed_pattern(tmp_path, "FP-4001")
    v = _check_valid()
    _pg_raw_insert_check((*v[:10], bad_fixtures, *v[11:]))


@pytest.mark.contract
def test_postgres_rejects_approved_without_human(
    tmp_path: Path, postgres_backend_env: object
) -> None:
    """FK-41 §41.3.3:282: 'approved' ohne approved_by='human' wird abgelehnt."""
    _seed_pattern(tmp_path, "FP-4001")
    v = _check_valid()
    _pg_raw_insert_check((*v[:2], "approved", *v[3:]))


@pytest.mark.contract
def test_postgres_rejects_active_without_human(
    tmp_path: Path, postgres_backend_env: object
) -> None:
    """FK-41 §41.3.3:282: 'active' erbt die approved_by='human'-Pflicht (CHECK).

    Parity zum SQLite ``test_rejects_active_without_human``; der DB-CHECK deckt
    'active' bereits ab (postgres_schema.sql:541).
    """
    _seed_pattern(tmp_path, "FP-4001")
    v = _check_valid()
    _pg_raw_insert_check((*v[:2], "active", *v[3:]))


@pytest.mark.contract
def test_postgres_rejects_unknown_pattern_ref_fk(
    postgres_backend_env: object,
) -> None:
    """pattern_ref -> fc_patterns(pattern_id) FK is fail-closed (FK-41 §41.3.3)."""
    # No _seed_pattern: the referenced FP-4001 does not exist.
    _pg_raw_insert_check(_check_valid())


@pytest.mark.contract
def test_postgres_rejects_unknown_check_ref_fk(
    tmp_path: Path, postgres_backend_env: object
) -> None:
    """FK-41 §41.3.2:234: fc_patterns.check_ref -> fc_check_proposals(check_id).

    The circular FK is added idempotently after both tables exist
    (postgres_store._ensure_failure_corpus_constraints); a check_ref pointing at a
    non-existent check_id must be rejected.
    """
    import psycopg

    from agentkit.state_backend.store.projection_repositories import _postgres_connect

    cols = _PATTERN_COLUMNS + ", check_ref"
    insert = (
        f"INSERT INTO fc_patterns ({cols}) "
        "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)"
    )
    bad = (*_PATTERN_VALID, "CHK-9999")
    with pytest.raises(psycopg.errors.Error), _postgres_connect() as conn:
        conn.execute(insert, bad)
