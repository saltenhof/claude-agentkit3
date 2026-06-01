"""Accessor-Roundtrip + Purge + Fail-Closed + Cross-Project fuer fc_incidents.

record_fc_incident -> read ueber den echten ProjectionAccessor (SQLite, FK-41
§41.3.1); purge_run entfernt genau die Zeilen des Runs (projektgebunden);
FC_PATTERNS/FC_CHECK_PROPOSALS bleiben fail-closed; write_projection(FC_INCIDENTS)
ist fail-closed (id muss zurueckkommen); read/purge ohne project_key sind
fail-closed; Cross-Project-Isolation (AG3-028 Codex-r1).
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest

from agentkit.core_types import FailureCategory, IncidentStatus
from agentkit.failure_corpus import IncidentDraft, IncidentRole, IncidentSeverity
from agentkit.state_backend.store.projection_repositories import (
    build_projection_repositories,
)
from agentkit.telemetry.errors import (
    FCIncidentWriteViaDedicatedMethodError,
    ProjectionKindNotAccessorOwnedError,
)
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


def _draft(
    *,
    project_key: str = "proj-a",
    story_id: str = "AG3-001",
    run_id: str = "run-1",
    category: FailureCategory = FailureCategory.SCOPE_DRIFT,
) -> IncidentDraft:
    return IncidentDraft(
        project_key=project_key,
        story_id=story_id,
        run_id=run_id,
        category=category,
        severity=IncidentSeverity.HIGH,
        phase="implementation",
        role=IncidentRole.WORKER,
        model="claude-opus",
        symptom="scope exceeded",
        evidence=["e1", "e2"],
        recorded_at=_NOW,
    )


def test_fc_incidents_accessor_owned() -> None:
    assert ProjectionAccessor.is_accessor_owned(ProjectionKind.FC_INCIDENTS) is True


def test_record_read_roundtrip(accessor: ProjectionAccessor) -> None:
    incident_id = accessor.record_fc_incident(_draft())
    assert incident_id == "FC-2026-0001"

    rows = accessor.read_projection(
        ProjectionKind.FC_INCIDENTS,
        ProjectionFilter(project_key="proj-a", story_id="AG3-001", run_id="run-1"),
    )
    assert len(rows) == 1
    row = rows[0]
    assert row.incident_id == incident_id  # type: ignore[union-attr]
    assert row.category is FailureCategory.SCOPE_DRIFT  # type: ignore[union-attr]
    assert row.severity is IncidentSeverity.HIGH  # type: ignore[union-attr]
    assert row.incident_status is IncidentStatus.OBSERVED  # type: ignore[union-attr]
    assert row.evidence == ["e1", "e2"]  # type: ignore[union-attr]


def test_incident_id_gap_free_per_project_year(accessor: ProjectionAccessor) -> None:
    a = accessor.record_fc_incident(_draft(story_id="S1"))
    b = accessor.record_fc_incident(_draft(story_id="S2"))
    assert a == "FC-2026-0001"
    assert b == "FC-2026-0002"


def test_write_projection_fc_incidents_fail_closed(
    accessor: ProjectionAccessor,
) -> None:
    # FK-41 §41.3.1: id muss zurueckkommen -> generische write_projection verboten.
    from agentkit.failure_corpus import Incident
    from agentkit.failure_corpus.types import IncidentId

    incident = Incident(
        project_key="proj-a",
        incident_id=IncidentId("FC-2026-9999"),
        run_id="run-1",
        story_id="AG3-001",
        category=FailureCategory.SCOPE_DRIFT,
        severity=IncidentSeverity.HIGH,
        phase="implementation",
        role=IncidentRole.WORKER,
        model="m",
        symptom="s",
        recorded_at=_NOW,
    )
    with pytest.raises(FCIncidentWriteViaDedicatedMethodError):
        accessor.write_projection(ProjectionKind.FC_INCIDENTS, incident)


def test_read_requires_project_key(accessor: ProjectionAccessor) -> None:
    with pytest.raises(ValueError, match="project_key"):
        accessor.read_projection(
            ProjectionKind.FC_INCIDENTS,
            ProjectionFilter(story_id="AG3-001"),
        )


def test_purge_run_removes_runs_incidents(accessor: ProjectionAccessor) -> None:
    accessor.record_fc_incident(_draft(run_id="run-A"))
    accessor.record_fc_incident(_draft(run_id="run-B", story_id="AG3-002"))

    result = accessor.purge_run("proj-a", "AG3-001", "run-A")
    assert result.purged_rows.get(ProjectionKind.FC_INCIDENTS, 0) == 1

    after_a = accessor.read_projection(
        ProjectionKind.FC_INCIDENTS,
        ProjectionFilter(project_key="proj-a", story_id="AG3-001", run_id="run-A"),
    )
    assert after_a == []

    after_b = accessor.read_projection(
        ProjectionKind.FC_INCIDENTS,
        ProjectionFilter(project_key="proj-a", story_id="AG3-002", run_id="run-B"),
    )
    assert len(after_b) == 1


def test_cross_project_isolation(accessor: ProjectionAccessor) -> None:
    # Gleiche story_id/run_id in zwei Projekten -> read/purge betrifft nur eines.
    accessor.record_fc_incident(_draft(project_key="proj-a"))
    accessor.record_fc_incident(_draft(project_key="proj-b"))

    rows_a = accessor.read_projection(
        ProjectionKind.FC_INCIDENTS,
        ProjectionFilter(project_key="proj-a", story_id="AG3-001", run_id="run-1"),
    )
    rows_b = accessor.read_projection(
        ProjectionKind.FC_INCIDENTS,
        ProjectionFilter(project_key="proj-b", story_id="AG3-001", run_id="run-1"),
    )
    assert len(rows_a) == 1
    assert len(rows_b) == 1
    assert rows_a[0].project_key == "proj-a"  # type: ignore[union-attr]
    assert rows_b[0].project_key == "proj-b"  # type: ignore[union-attr]

    # Purge in proj-a darf proj-b nicht beruehren.
    accessor.purge_run("proj-a", "AG3-001", "run-1")
    rows_a_after = accessor.read_projection(
        ProjectionKind.FC_INCIDENTS,
        ProjectionFilter(project_key="proj-a", story_id="AG3-001", run_id="run-1"),
    )
    rows_b_after = accessor.read_projection(
        ProjectionKind.FC_INCIDENTS,
        ProjectionFilter(project_key="proj-b", story_id="AG3-001", run_id="run-1"),
    )
    assert rows_a_after == []
    assert len(rows_b_after) == 1


def test_fc_patterns_fail_closed_write(accessor: ProjectionAccessor) -> None:
    from agentkit.failure_corpus import Incident
    from agentkit.failure_corpus.types import IncidentId

    incident = Incident(
        project_key="proj-a",
        incident_id=IncidentId("FC-2026-0001"),
        run_id="run-1",
        story_id="AG3-001",
        category=FailureCategory.SCOPE_DRIFT,
        severity=IncidentSeverity.HIGH,
        phase="implementation",
        role=IncidentRole.WORKER,
        model="m",
        symptom="s",
        recorded_at=_NOW,
    )
    with pytest.raises(ProjectionKindNotAccessorOwnedError):
        accessor.write_projection(ProjectionKind.FC_PATTERNS, incident)


def test_fc_check_proposals_fail_closed_read(accessor: ProjectionAccessor) -> None:
    with pytest.raises(ProjectionKindNotAccessorOwnedError):
        accessor.read_projection(
            ProjectionKind.FC_CHECK_PROPOSALS,
            ProjectionFilter(project_key="proj-a", story_id="AG3-001"),
        )


def test_fc_patterns_still_externally_owned() -> None:
    assert ProjectionAccessor.is_accessor_owned(ProjectionKind.FC_PATTERNS) is False
    assert (
        ProjectionAccessor.is_accessor_owned(ProjectionKind.FC_CHECK_PROPOSALS)
        is False
    )
