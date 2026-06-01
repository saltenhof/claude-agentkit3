"""Accessor-Roundtrip + Purge + Fail-Closed-Pin fuer fc_incidents (AG3-028, AK#9/#10).

write -> read ueber den echten ProjectionAccessor (SQLite); purge_run entfernt
genau die Zeilen des Runs; FC_PATTERNS/FC_CHECK_PROPOSALS bleiben fail-closed.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest

from agentkit.core_types import FailureCategory, IncidentStatus
from agentkit.failure_corpus import Incident, IncidentSeverity
from agentkit.failure_corpus.types import IncidentId
from agentkit.state_backend.store.projection_repositories import (
    build_projection_repositories,
)
from agentkit.telemetry.errors import ProjectionKindNotAccessorOwnedError
from agentkit.telemetry.projection_accessor import (
    ProjectionAccessor,
    ProjectionFilter,
    ProjectionKind,
)

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

_NOW = datetime(2026, 6, 1, 12, 0, 0, tzinfo=UTC)


@pytest.fixture()
def accessor(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> Iterator[ProjectionAccessor]:
    monkeypatch.setenv("AGENTKIT_STATE_BACKEND", "sqlite")
    monkeypatch.setenv("AGENTKIT_ALLOW_SQLITE", "1")
    from agentkit.state_backend.store.facade import reset_backend_cache_for_tests

    reset_backend_cache_for_tests()
    yield ProjectionAccessor(build_projection_repositories(tmp_path))
    reset_backend_cache_for_tests()


def _incident(incident_id: str, *, story_id: str = "AG3-001", run_id: str = "run-1") -> Incident:
    return Incident(
        incident_id=IncidentId(incident_id),
        category=FailureCategory.SCOPE_DRIFT,
        severity=IncidentSeverity.HIGH,
        source_bc="governance-and-guards",
        story_id=story_id,
        run_id=run_id,
        summary="scope exceeded",
        evidence={"k": "v"},
        observed_at=_NOW,
        normalized_at=_NOW,
    )


def test_fc_incidents_accessor_owned() -> None:
    assert ProjectionAccessor.is_accessor_owned(ProjectionKind.FC_INCIDENTS) is True


def test_write_read_roundtrip(accessor: ProjectionAccessor) -> None:
    accessor.write_projection(ProjectionKind.FC_INCIDENTS, _incident("FC-1"))
    rows = accessor.read_projection(
        ProjectionKind.FC_INCIDENTS,
        ProjectionFilter(story_id="AG3-001", run_id="run-1"),
    )
    assert len(rows) == 1
    row = rows[0]
    assert isinstance(row, Incident)
    assert row.incident_id == "FC-1"
    assert row.category is FailureCategory.SCOPE_DRIFT
    assert row.severity is IncidentSeverity.HIGH
    assert row.incident_status is IncidentStatus.OBSERVED
    assert row.evidence == {"k": "v"}


def test_purge_run_removes_runs_incidents(accessor: ProjectionAccessor) -> None:
    accessor.write_projection(ProjectionKind.FC_INCIDENTS, _incident("FC-a", run_id="run-A"))
    accessor.write_projection(ProjectionKind.FC_INCIDENTS, _incident("FC-b", run_id="run-B"))

    result = accessor.purge_run("proj", "AG3-001", "run-A")
    assert result.errors == []
    assert result.purged_rows.get(ProjectionKind.FC_INCIDENTS, 0) == 1

    after_a = accessor.read_projection(
        ProjectionKind.FC_INCIDENTS,
        ProjectionFilter(story_id="AG3-001", run_id="run-A"),
    )
    assert after_a == []

    after_b = accessor.read_projection(
        ProjectionKind.FC_INCIDENTS,
        ProjectionFilter(story_id="AG3-001", run_id="run-B"),
    )
    assert len(after_b) == 1


def test_fc_patterns_fail_closed_write(accessor: ProjectionAccessor) -> None:
    with pytest.raises(ProjectionKindNotAccessorOwnedError):
        accessor.write_projection(ProjectionKind.FC_PATTERNS, _incident("FC-x"))


def test_fc_check_proposals_fail_closed_read(accessor: ProjectionAccessor) -> None:
    with pytest.raises(ProjectionKindNotAccessorOwnedError):
        accessor.read_projection(
            ProjectionKind.FC_CHECK_PROPOSALS,
            ProjectionFilter(story_id="AG3-001"),
        )


def test_fc_patterns_still_externally_owned() -> None:
    assert ProjectionAccessor.is_accessor_owned(ProjectionKind.FC_PATTERNS) is False
    assert ProjectionAccessor.is_accessor_owned(ProjectionKind.FC_CHECK_PROPOSALS) is False
