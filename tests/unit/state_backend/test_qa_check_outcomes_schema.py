"""Schema roundtrip tests for qa_check_outcomes (AG3-108, FK-69 §69.15).

Covers:
- Insert/read roundtrip via FacadeQACheckOutcomesRepository (SQLite)
- All three outcomes: triggered / clean / overridden
- Optional fields: check_proposal_ref, override_id
- Fail-closed: empty project_key raises ValueError
- Fail-closed: empty check_id raises ValueError
- purge_run removes exactly the target rows; other runs untouched
- check_id equality filter
- since_days UTC window including boundary
- Negative/0 since_days treated as 0 (no window or empty window)
- since_days window via PUBLIC ProjectionAccessor.read_projection (ERROR 4)
"""

from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

import pytest

from agentkit.backend.state_backend.store.projection_repositories import (
    FacadeQACheckOutcomesRepository,
)
from agentkit.backend.telemetry.projection_accessor import (
    ProjectionFilter,
    ProjectionKind,
)
from agentkit.backend.verify_system.stage_registry.records import (
    CheckOutcome,
    QACheckOutcomeRecord,
)

if TYPE_CHECKING:
    from pathlib import Path

_TS = datetime(2026, 6, 1, 10, 0, 0, tzinfo=UTC)


@pytest.fixture(autouse=True)
def _sqlite_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AGENTKIT_STATE_BACKEND", "sqlite")
    monkeypatch.setenv("AGENTKIT_ALLOW_SQLITE", "1")
    os.environ["AGENTKIT_STATE_BACKEND"] = "sqlite"
    os.environ["AGENTKIT_ALLOW_SQLITE"] = "1"


def _record(
    *,
    project_key: str = "proj-test",
    story_id: str = "AG3-108",
    run_id: str = "run-1",
    stage_id: str = "structural",
    attempt_no: int = 1,
    check_id: str = "artifact.protocol",
    outcome: CheckOutcome = CheckOutcome.CLEAN,
    occurred_at: datetime = _TS,
    check_proposal_ref: str | None = None,
    override_id: str | None = None,
) -> QACheckOutcomeRecord:
    return QACheckOutcomeRecord(
        project_key=project_key,
        story_id=story_id,
        run_id=run_id,
        stage_id=stage_id,
        attempt_no=attempt_no,
        check_id=check_id,
        outcome=outcome,
        occurred_at=occurred_at,
        check_proposal_ref=check_proposal_ref,
        override_id=override_id,
    )


# ---------------------------------------------------------------------------
# Roundtrip per outcome
# ---------------------------------------------------------------------------


def test_roundtrip_clean(tmp_path: Path) -> None:
    repo = FacadeQACheckOutcomesRepository(tmp_path)
    rec = _record(outcome=CheckOutcome.CLEAN)
    repo.write(rec)

    rows = repo.read(project_key="proj-test", run_id="run-1")
    assert len(rows) == 1
    assert rows[0].outcome is CheckOutcome.CLEAN
    assert rows[0].check_id == "artifact.protocol"
    assert rows[0].project_key == "proj-test"


def test_roundtrip_triggered(tmp_path: Path) -> None:
    repo = FacadeQACheckOutcomesRepository(tmp_path)
    rec = _record(
        check_id="impl_fidelity",
        outcome=CheckOutcome.TRIGGERED,
    )
    repo.write(rec)

    rows = repo.read(project_key="proj-test", run_id="run-1")
    assert len(rows) == 1
    assert rows[0].outcome is CheckOutcome.TRIGGERED


def test_roundtrip_overridden_with_override_id(tmp_path: Path) -> None:
    repo = FacadeQACheckOutcomesRepository(tmp_path)
    rec = _record(
        check_id="qa_review",
        outcome=CheckOutcome.OVERRIDDEN,
        override_id="ovr-42",
    )
    repo.write(rec)

    rows = repo.read(project_key="proj-test", run_id="run-1")
    assert len(rows) == 1
    assert rows[0].outcome is CheckOutcome.OVERRIDDEN
    assert rows[0].override_id == "ovr-42"


def test_roundtrip_optional_check_proposal_ref(tmp_path: Path) -> None:
    repo = FacadeQACheckOutcomesRepository(tmp_path)
    rec = _record(check_proposal_ref="CHK-0042")
    repo.write(rec)

    rows = repo.read(project_key="proj-test", run_id="run-1")
    assert rows[0].check_proposal_ref == "CHK-0042"


# ---------------------------------------------------------------------------
# Fail-closed invariants
# ---------------------------------------------------------------------------


def test_write_rejects_empty_project_key(tmp_path: Path) -> None:
    repo = FacadeQACheckOutcomesRepository(tmp_path)
    with pytest.raises(ValueError, match="project_key"):
        repo.write(_record(project_key=""))


def test_write_rejects_empty_check_id(tmp_path: Path) -> None:
    repo = FacadeQACheckOutcomesRepository(tmp_path)
    with pytest.raises(ValueError, match="check_id"):
        repo.write(_record(check_id=""))


# ---------------------------------------------------------------------------
# Upsert / idempotency
# ---------------------------------------------------------------------------


def test_upsert_replaces_on_pk_conflict(tmp_path: Path) -> None:
    """Second write on same PK replaces the outcome (upsert)."""
    repo = FacadeQACheckOutcomesRepository(tmp_path)
    repo.write(_record(outcome=CheckOutcome.CLEAN))
    repo.write(_record(outcome=CheckOutcome.TRIGGERED))

    rows = repo.read(project_key="proj-test", run_id="run-1")
    assert len(rows) == 1
    assert rows[0].outcome is CheckOutcome.TRIGGERED


# ---------------------------------------------------------------------------
# purge_run
# ---------------------------------------------------------------------------


def test_purge_run_deletes_target_rows(tmp_path: Path) -> None:
    repo = FacadeQACheckOutcomesRepository(tmp_path)
    repo.write(_record(run_id="run-a", check_id="c1"))
    repo.write(_record(run_id="run-a", check_id="c2"))
    repo.write(_record(run_id="run-b", check_id="c1"))

    count = repo.purge_run("proj-test", "AG3-108", "run-a")

    assert count == 2
    remaining = repo.read(project_key="proj-test")
    assert len(remaining) == 1
    assert remaining[0].run_id == "run-b"


def test_purge_run_returns_0_when_nothing_to_delete(tmp_path: Path) -> None:
    repo = FacadeQACheckOutcomesRepository(tmp_path)
    count = repo.purge_run("proj-test", "AG3-108", "run-nonexistent")
    assert count == 0


# ---------------------------------------------------------------------------
# check_id equality filter
# ---------------------------------------------------------------------------


def test_read_filter_check_id_equality(tmp_path: Path) -> None:
    repo = FacadeQACheckOutcomesRepository(tmp_path)
    repo.write(_record(check_id="artifact.protocol"))
    repo.write(_record(check_id="branch.story"))
    repo.write(_record(check_id="impl_fidelity"))

    rows = repo.read(project_key="proj-test", check_id="branch.story")
    assert len(rows) == 1
    assert rows[0].check_id == "branch.story"


def test_read_filter_check_id_no_match(tmp_path: Path) -> None:
    repo = FacadeQACheckOutcomesRepository(tmp_path)
    repo.write(_record(check_id="artifact.protocol"))

    rows = repo.read(project_key="proj-test", check_id="nonexistent")
    assert rows == []


# ---------------------------------------------------------------------------
# since_days UTC window
# ---------------------------------------------------------------------------


def _now_dt() -> datetime:
    return datetime(2026, 6, 10, 12, 0, 0, tzinfo=UTC)


def test_since_days_includes_recent_row(tmp_path: Path) -> None:
    """Row within the since_days window is returned."""
    repo = FacadeQACheckOutcomesRepository(tmp_path)
    # 3 days ago
    recent_ts = _now_dt() - timedelta(days=3)
    repo.write(_record(occurred_at=recent_ts))

    rows = repo.read(
        project_key="proj-test",
        since_days=7,
        _now=_now_dt(),
    )
    assert len(rows) == 1


def test_since_days_excludes_old_row(tmp_path: Path) -> None:
    """Row outside the since_days window is excluded."""
    repo = FacadeQACheckOutcomesRepository(tmp_path)
    # 10 days ago — outside the 7-day window
    old_ts = _now_dt() - timedelta(days=10)
    repo.write(_record(occurred_at=old_ts))

    rows = repo.read(
        project_key="proj-test",
        since_days=7,
        _now=_now_dt(),
    )
    assert rows == []


def test_since_days_boundary_exactly_at_cutoff(tmp_path: Path) -> None:
    """Row exactly at the cutoff (occurred_at == now - since_days) is included."""
    repo = FacadeQACheckOutcomesRepository(tmp_path)
    cutoff_ts = _now_dt() - timedelta(days=7)
    repo.write(_record(occurred_at=cutoff_ts))

    rows = repo.read(
        project_key="proj-test",
        since_days=7,
        _now=_now_dt(),
    )
    assert len(rows) == 1


def test_since_days_zero_returns_all_from_now(tmp_path: Path) -> None:
    """since_days=0 uses a cutoff of now — only rows at or after now pass."""
    repo = FacadeQACheckOutcomesRepository(tmp_path)
    old_ts = _now_dt() - timedelta(seconds=1)
    repo.write(_record(occurred_at=old_ts))

    rows = repo.read(
        project_key="proj-test",
        since_days=0,
        _now=_now_dt(),
    )
    # The row is 1 second before now -> outside the 0-day window -> excluded
    assert rows == []


def test_since_days_negative_treated_as_zero(tmp_path: Path) -> None:
    """Negative since_days is clamped to 0 (same as since_days=0)."""
    repo = FacadeQACheckOutcomesRepository(tmp_path)
    old_ts = _now_dt() - timedelta(hours=1)
    repo.write(_record(occurred_at=old_ts))

    rows = repo.read(
        project_key="proj-test",
        since_days=-5,
        _now=_now_dt(),
    )
    assert rows == []


# ---------------------------------------------------------------------------
# Cross-project isolation
# ---------------------------------------------------------------------------


def test_read_is_project_scoped(tmp_path: Path) -> None:
    repo = FacadeQACheckOutcomesRepository(tmp_path)
    repo.write(_record(project_key="proj-a", check_id="c1"))
    repo.write(_record(project_key="proj-b", check_id="c1"))

    rows_a = repo.read(project_key="proj-a")
    rows_b = repo.read(project_key="proj-b")

    assert len(rows_a) == 1
    assert rows_a[0].project_key == "proj-a"
    assert len(rows_b) == 1
    assert rows_b[0].project_key == "proj-b"


# ---------------------------------------------------------------------------
# since_days window via PUBLIC ProjectionAccessor.read_projection (AG3-108 ERROR 4)
# ---------------------------------------------------------------------------


def test_since_days_via_public_accessor_includes_recent(tmp_path: Path) -> None:
    """read_projection accepts _now and applies since_days via the PUBLIC API.

    Proves AG3-108 ERROR 4 fix: the injectable clock is threaded through
    read_projection so tests drive the PUBLIC accessor, not accessor._repos.
    """
    from agentkit.backend.bootstrap.composition_root import build_projection_accessor

    accessor = build_projection_accessor(tmp_path)
    now = _now_dt()
    recent_ts = now - timedelta(days=2)

    # Write directly via the repo so we can control occurred_at.
    repo = FacadeQACheckOutcomesRepository(tmp_path)
    repo.write(_record(occurred_at=recent_ts))

    rows = accessor.read_projection(
        ProjectionKind.QA_CHECK_OUTCOMES,
        ProjectionFilter(project_key="proj-test", since_days=7),
        _now=now,
    )
    assert len(rows) == 1
    assert rows[0].check_id == "artifact.protocol"


def test_since_days_via_public_accessor_excludes_old(tmp_path: Path) -> None:
    """read_projection with _now excludes rows outside the since_days window."""
    from agentkit.backend.bootstrap.composition_root import build_projection_accessor

    accessor = build_projection_accessor(tmp_path)
    now = _now_dt()
    old_ts = now - timedelta(days=30)

    repo = FacadeQACheckOutcomesRepository(tmp_path)
    repo.write(_record(occurred_at=old_ts))

    rows = accessor.read_projection(
        ProjectionKind.QA_CHECK_OUTCOMES,
        ProjectionFilter(project_key="proj-test", since_days=7),
        _now=now,
    )
    assert rows == []


def test_since_days_boundary_via_public_accessor(tmp_path: Path) -> None:
    """Row at exactly the since_days boundary is included via the PUBLIC accessor."""
    from agentkit.backend.bootstrap.composition_root import build_projection_accessor

    accessor = build_projection_accessor(tmp_path)
    now = _now_dt()
    cutoff_ts = now - timedelta(days=7)

    repo = FacadeQACheckOutcomesRepository(tmp_path)
    repo.write(_record(occurred_at=cutoff_ts))

    rows = accessor.read_projection(
        ProjectionKind.QA_CHECK_OUTCOMES,
        ProjectionFilter(project_key="proj-test", since_days=7),
        _now=now,
    )
    assert len(rows) == 1
