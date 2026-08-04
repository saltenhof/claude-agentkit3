"""ProjectionAccessor roundtrip for qa_check_outcomes (AG3-108, FK-69 §69.15).

Covers:
- generic split writes are rejected in favor of the atomic QA-layer batch
- read_projection(QA_CHECK_OUTCOMES, filter) -> correct rows back
- ProjectionFilter.check_id equality filter
- ProjectionFilter.since_days UTC window
- Fail-closed: read without project_key raises ValueError
- purge_run removes qa_check_outcomes rows for the given (project, story, run)
- QA_CHECK_OUTCOMES is in the accessor-owned kinds set
"""

from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

import pytest
from tests.qa_artifact_support import seed_qa_check_outcome

from agentkit.backend.state_backend.store.telemetry_projection_repository_misc import (
    build_projection_repositories,
)
from agentkit.backend.telemetry.errors import (
    QALayerArtifactWriteViaDedicatedMethodError,
)
from agentkit.backend.telemetry.projection_accessor import (
    ProjectionAccessor,
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


@pytest.fixture()
def accessor(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> ProjectionAccessor:
    monkeypatch.setenv("AGENTKIT_STATE_BACKEND", "sqlite")
    monkeypatch.setenv("AGENTKIT_ALLOW_SQLITE", "1")
    os.environ["AGENTKIT_STATE_BACKEND"] = "sqlite"
    os.environ["AGENTKIT_ALLOW_SQLITE"] = "1"
    from agentkit.backend.state_backend.persistence_test_support import reset_backend_cache_for_tests

    reset_backend_cache_for_tests()
    repos = build_projection_repositories(tmp_path)
    acc = ProjectionAccessor(repos)
    yield acc
    reset_backend_cache_for_tests()


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
        override_id=override_id,
    )


def _seed_outcome(accessor: ProjectionAccessor, record: QACheckOutcomeRecord) -> None:
    """Seed a row below the business boundary for read/filter/purge tests."""
    repository = accessor._repos.qa_check_outcomes  # noqa: SLF001 -- test setup locates the configured SQLite store
    seed_qa_check_outcome(repository._story_dir, record)  # noqa: SLF001 -- test-only DB seed, not a production writer


# ---------------------------------------------------------------------------
# ProjectionKind registration
# ---------------------------------------------------------------------------


def test_qa_check_outcomes_kind_exists() -> None:
    """QA_CHECK_OUTCOMES is a registered ProjectionKind."""
    assert hasattr(ProjectionKind, "QA_CHECK_OUTCOMES")
    assert ProjectionKind.QA_CHECK_OUTCOMES == "qa_check_outcomes"


# ---------------------------------------------------------------------------
# Split-write rejection and repository read semantics
# ---------------------------------------------------------------------------


def test_check_outcome_split_write_is_rejected(accessor: ProjectionAccessor) -> None:
    """A check outcome cannot be written apart from stage and finding rows."""
    rec = _record(check_id="artifact.protocol", outcome=CheckOutcome.TRIGGERED)
    with pytest.raises(QALayerArtifactWriteViaDedicatedMethodError):
        accessor.write_projection(ProjectionKind.QA_CHECK_OUTCOMES, rec)


def test_repository_read_returns_seeded_outcome(accessor: ProjectionAccessor) -> None:
    """The accessor reads canonical rows materialized by the batch repository."""
    rec = _record(check_id="artifact.protocol", outcome=CheckOutcome.TRIGGERED)
    _seed_outcome(accessor, rec)

    rows = accessor.read_projection(
        ProjectionKind.QA_CHECK_OUTCOMES,
        ProjectionFilter(project_key="proj-test", run_id="run-1"),
    )

    assert len(rows) == 1
    row = rows[0]
    assert isinstance(row, QACheckOutcomeRecord)
    assert row.check_id == "artifact.protocol"
    assert row.outcome is CheckOutcome.TRIGGERED
    assert row.project_key == "proj-test"
    assert row.story_id == "AG3-108"
    assert row.run_id == "run-1"
    assert row.stage_id == "structural"
    assert row.attempt_no == 1


def test_roundtrip_overridden_outcome(accessor: ProjectionAccessor) -> None:
    rec = _record(
        check_id="qa_review",
        outcome=CheckOutcome.OVERRIDDEN,
        override_id="ovr-007",
    )
    _seed_outcome(accessor, rec)

    rows = accessor.read_projection(
        ProjectionKind.QA_CHECK_OUTCOMES,
        ProjectionFilter(project_key="proj-test", run_id="run-1"),
    )
    assert len(rows) == 1
    assert rows[0].outcome is CheckOutcome.OVERRIDDEN
    assert rows[0].override_id == "ovr-007"


def test_multiple_checks_same_run(accessor: ProjectionAccessor) -> None:
    """Multiple checks in the same run all round-trip correctly."""
    for check_id, outcome in [
        ("artifact.protocol", CheckOutcome.CLEAN),
        ("branch.story", CheckOutcome.TRIGGERED),
        ("impl_fidelity", CheckOutcome.OVERRIDDEN),
    ]:
        _seed_outcome(accessor, _record(check_id=check_id, outcome=outcome))

    rows = accessor.read_projection(
        ProjectionKind.QA_CHECK_OUTCOMES,
        ProjectionFilter(project_key="proj-test", run_id="run-1"),
    )
    assert len(rows) == 3
    by_check = {r.check_id: r for r in rows}  # type: ignore[union-attr]
    assert by_check["artifact.protocol"].outcome is CheckOutcome.CLEAN
    assert by_check["branch.story"].outcome is CheckOutcome.TRIGGERED
    assert by_check["impl_fidelity"].outcome is CheckOutcome.OVERRIDDEN


# ---------------------------------------------------------------------------
# ProjectionFilter.check_id equality filter
# ---------------------------------------------------------------------------


def test_filter_by_check_id(accessor: ProjectionAccessor) -> None:
    """ProjectionFilter.check_id filters to the matching check only."""
    _seed_outcome(accessor, _record(check_id="c1"))
    _seed_outcome(accessor, _record(check_id="c2"))

    rows = accessor.read_projection(
        ProjectionKind.QA_CHECK_OUTCOMES,
        ProjectionFilter(project_key="proj-test", check_id="c1"),
    )
    assert len(rows) == 1
    assert rows[0].check_id == "c1"  # type: ignore[union-attr]


def test_filter_by_check_id_no_match(accessor: ProjectionAccessor) -> None:
    _seed_outcome(accessor, _record(check_id="c1"))

    rows = accessor.read_projection(
        ProjectionKind.QA_CHECK_OUTCOMES,
        ProjectionFilter(project_key="proj-test", check_id="nonexistent"),
    )
    assert rows == []


# ---------------------------------------------------------------------------
# ProjectionFilter.since_days UTC window
# ---------------------------------------------------------------------------


def _now_dt() -> datetime:
    return datetime(2026, 6, 10, 12, 0, 0, tzinfo=UTC)


def test_since_days_window_includes_recent(accessor: ProjectionAccessor) -> None:
    recent_ts = _now_dt() - timedelta(days=2)
    _seed_outcome(accessor, _record(occurred_at=recent_ts))

    # Directly call FacadeQACheckOutcomesRepository since ProjectionFilter
    # does not yet have a _now injection path; use the repo directly.
    from agentkit.backend.state_backend.store.telemetry_projection_repository_qa import (
        FacadeQACheckOutcomesRepository,
    )

    repo = accessor._repos.qa_check_outcomes  # type: ignore[attr-defined]
    assert isinstance(repo, FacadeQACheckOutcomesRepository)

    rows = repo.read(project_key="proj-test", since_days=7, _now=_now_dt())
    assert len(rows) == 1


def test_since_days_window_excludes_old(accessor: ProjectionAccessor) -> None:
    old_ts = _now_dt() - timedelta(days=30)
    _seed_outcome(accessor, _record(occurred_at=old_ts))

    from agentkit.backend.state_backend.store.telemetry_projection_repository_qa import (
        FacadeQACheckOutcomesRepository,
    )

    repo = accessor._repos.qa_check_outcomes  # type: ignore[attr-defined]
    assert isinstance(repo, FacadeQACheckOutcomesRepository)

    rows = repo.read(project_key="proj-test", since_days=7, _now=_now_dt())
    assert rows == []


def test_since_days_boundary_at_cutoff_included(accessor: ProjectionAccessor) -> None:
    cutoff_ts = _now_dt() - timedelta(days=7)
    _seed_outcome(accessor, _record(occurred_at=cutoff_ts))


    repo = accessor._repos.qa_check_outcomes  # type: ignore[attr-defined]
    rows = repo.read(project_key="proj-test", since_days=7, _now=_now_dt())
    assert len(rows) == 1


def test_since_days_zero(accessor: ProjectionAccessor) -> None:
    """since_days=0 excludes rows strictly before now."""
    old_ts = _now_dt() - timedelta(seconds=5)
    _seed_outcome(accessor, _record(occurred_at=old_ts))


    repo = accessor._repos.qa_check_outcomes  # type: ignore[attr-defined]
    rows = repo.read(project_key="proj-test", since_days=0, _now=_now_dt())
    assert rows == []


# ---------------------------------------------------------------------------
# Fail-closed: missing project_key
# ---------------------------------------------------------------------------


def test_read_without_project_key_raises(accessor: ProjectionAccessor) -> None:
    """read_projection without project_key is fail-closed (FK-69 §69.15.6 rule 7)."""
    with pytest.raises(ValueError, match="project_key"):
        accessor.read_projection(
            ProjectionKind.QA_CHECK_OUTCOMES,
            ProjectionFilter(),
        )


# ---------------------------------------------------------------------------
# purge_run
# ---------------------------------------------------------------------------


def test_purge_run_removes_qa_check_outcomes(accessor: ProjectionAccessor) -> None:
    """purge_run removes qa_check_outcomes for the purged run."""
    _seed_outcome(accessor, _record(run_id="run-1", check_id="c1"))
    _seed_outcome(accessor, _record(run_id="run-2", check_id="c1"))

    result = accessor.purge_run("proj-test", "AG3-108", "run-1")

    purged = result.purged_rows.get(ProjectionKind.QA_CHECK_OUTCOMES, 0)
    assert purged == 1

    remaining = accessor.read_projection(
        ProjectionKind.QA_CHECK_OUTCOMES,
        ProjectionFilter(project_key="proj-test"),
    )
    assert len(remaining) == 1
    assert remaining[0].run_id == "run-2"  # type: ignore[union-attr]
