"""Reset-Purge-Delta: a full Story-Reset leaves no FK-69 read-model / counter rows.

AG3-081 AC6 (FK-69 §69.9 / §69.10.1, FK-61 §61.4.3 Trigger 4): a full Story-Reset
purges — in the SINGLE ``ProjectionAccessor.purge_run()`` call (no parallel purge
service, no separately-invoked flush) — both the run's FK-69 §69.3 read-model rows
AND the story's ``guard_invocation_counters``. The counter purge is integrated
into ``purge_run`` via the injected ``GuardCounterPurgePort``; a real reset that
calls ``purge_run`` therefore drains the counters as a side effect of that one
path. After the reset:

- the FK-69 read-models of the ``run_id`` are gone (qa_stage_results, qa_findings,
  story_metrics, fc_incidents) — verified with a negative read;
- the ``guard_invocation_counters`` of the scope are gone;
- ``fc_check_proposals`` are UNTOUCHED (FK-41 §41.3.3) — the check lifecycle is
  story-independent; purge_run carries NO fc_check_proposals purge path.
- ``fc_patterns`` are NOT deleted by purge_run (FK-69 §69.9): patterns are
  recomputed (not deleted); recompute is AG3-082.

AG3-078 NOTE: FC_PATTERNS and FC_CHECK_PROPOSALS were moved into
_ACCESSOR_OWNED_KINDS in AG3-078 so the accessor can read/write them.
purge_run does NOT extend to cover them (FK-41 §41.3.3/FK-69 §69.9): they
are simply absent from PurgeResult.purged_rows.  The
``ProjectionKindNotAccessorOwnedError`` path no longer applies to these kinds.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest

from agentkit.backend.kpi_analytics.fact_store.guard_counter import GuardCounterService
from agentkit.backend.state_backend.store import reset_backend_cache_for_tests
from agentkit.backend.state_backend.store.guard_counter_repository import (
    StateBackendGuardCounterRepository,
)
from agentkit.backend.state_backend.store.projection_repositories import (
    build_projection_repositories,
)
from agentkit.backend.telemetry.projection_accessor import (
    ProjectionAccessor,
    ProjectionFilter,
    ProjectionKind,
)
from agentkit.backend.verify_system.stage_registry.records import QAStageResultRecord

if TYPE_CHECKING:
    from collections.abc import Generator
    from pathlib import Path

_PROJECT = "int-proj"
_STORY = "INT-RESET-001"
_RUN = "run-reset-001"


@pytest.fixture(autouse=True)
def _sqlite_backend(monkeypatch: pytest.MonkeyPatch) -> Generator[None, None, None]:
    monkeypatch.setenv("AGENTKIT_STATE_BACKEND", "sqlite")
    monkeypatch.setenv("AGENTKIT_ALLOW_SQLITE", "1")
    monkeypatch.delenv("AGENTKIT_STATE_DATABASE_URL", raising=False)
    reset_backend_cache_for_tests()
    yield
    reset_backend_cache_for_tests()


def _seed_qa_stage_result(accessor: ProjectionAccessor) -> None:
    accessor.write_projection(
        ProjectionKind.QA_STAGE_RESULTS,
        QAStageResultRecord(
            project_key=_PROJECT,
            story_id=_STORY,
            run_id=_RUN,
            attempt_no=1,
            stage_id="structural",
            layer="structural",
            producer_component="qa-structural-check",
            status="PASS",
            blocking=False,
            total_checks=5,
            failed_checks=0,
            warning_checks=0,
            artifact_id="art-reset-001",
            recorded_at=datetime(2026, 6, 11, 10, 0, 0, tzinfo=UTC),
        ),
    )


def _seed_counters(store_dir: Path) -> None:
    service = GuardCounterService(StateBackendGuardCounterRepository(store_dir))
    now = datetime(2026, 6, 11, 10, 0, 0, tzinfo=UTC)
    for guard in ("orchestrator_guard", "self_protection"):
        service.record_invocation(
            project_key=_PROJECT,
            story_id=_STORY,
            guard_key=guard,
            blocked=False,
            now=now,
        )


def test_full_reset_leaves_no_fk69_or_counter_rows_proposals_untouched(
    tmp_path: Path,
) -> None:
    accessor = ProjectionAccessor(build_projection_repositories(tmp_path))
    _seed_qa_stage_result(accessor)
    _seed_counters(tmp_path)

    # Pre-conditions: the FK-69 read-model + counters exist.
    assert (
        len(
            accessor.read_projection(
                ProjectionKind.QA_STAGE_RESULTS,
                ProjectionFilter(project_key=_PROJECT, story_id=_STORY, run_id=_RUN),
            )
        )
        == 1
    )
    counter_repo = StateBackendGuardCounterRepository(tmp_path)
    assert len(counter_repo.read_counters_for_story(_PROJECT, _STORY)) == 2

    # --- full reset: ONE purge_run() call removes BOTH the FK-69 read-models AND
    # the guard counters (counter purge is integrated into purge_run via the
    # GuardCounterPurgePort — NOT a separately-invoked flush).
    purge_result = accessor.purge_run(_PROJECT, _STORY, _RUN)

    # FK-69 read-models of the run are gone (negative read -> no residual rows).
    assert purge_result.errors == []
    assert (
        accessor.read_projection(
            ProjectionKind.QA_STAGE_RESULTS,
            ProjectionFilter(project_key=_PROJECT, story_id=_STORY, run_id=_RUN),
        )
        == []
    )
    # The guard counters of the scope are gone (no residual counter rows) — purged
    # by the SAME purge_run() call, surfaced via purged_guard_counters.
    assert purge_result.purged_guard_counters == 2
    assert counter_repo.read_counters_for_story(_PROJECT, _STORY) == []

    # fc_check_proposals are UNTOUCHED (FK-41 §41.3.3): the check lifecycle is
    # story-independent; purge_run carries NO FC_CHECK_PROPOSALS purge path.
    # AG3-078: FC_CHECK_PROPOSALS is now accessor-owned (readable/writable via
    # the accessor), but purge_run does NOT extend to it (FK-69 §69.9).
    assert ProjectionKind.FC_CHECK_PROPOSALS not in purge_result.purged_rows
    # fc_patterns are NOT deleted by purge_run (FK-69 §69.9): patterns are
    # recomputed (not deleted); the recompute is AG3-082.
    assert ProjectionKind.FC_PATTERNS not in purge_result.purged_rows
    # FC_CHECK_PROPOSALS is now accessor-owned (AG3-078): read_projection must
    # succeed (not raise ProjectionKindNotAccessorOwnedError). The accessor
    # accepts the call; project_key is required (fail-closed).
    proposals_after_reset = accessor.read_projection(
        ProjectionKind.FC_CHECK_PROPOSALS,
        ProjectionFilter(project_key=_PROJECT, story_id=_STORY),
    )
    # No proposals were seeded in this test, so the result is an empty list.
    assert isinstance(proposals_after_reset, list)
