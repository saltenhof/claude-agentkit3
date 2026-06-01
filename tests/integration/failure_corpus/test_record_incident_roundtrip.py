"""Integration-Test: record_incident End-to-End-Empfaenger-Pfad (AG3-028 AK#7).

Laeuft via integration-conftest gegen Postgres. Ein Aufrufer-BC ruft
``FailureCorpus.record_incident``; der Incident ist anschliessend in
``fc_incidents`` ueber den Accessor lesbar. Zusaetzlich: purge_run entfernt die
Zeilen des Runs (AK#9 auf Postgres).

Der SQLite-Pfad desselben Empfaenger-Vertrags ist in
``tests/unit/failure_corpus/test_top.py`` und
``tests/unit/telemetry/test_fc_incidents_projection_roundtrip.py`` abgedeckt
(AK#7: beide Backends).
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from agentkit.bootstrap.composition_root import build_failure_corpus
from agentkit.core_types import FailureCategory, IncidentStatus
from agentkit.failure_corpus import IncidentCandidate, IncidentSeverity
from agentkit.state_backend.store.projection_repositories import (
    build_projection_repositories,
)
from agentkit.telemetry.projection_accessor import (
    ProjectionAccessor,
    ProjectionFilter,
    ProjectionKind,
)

_NOW = datetime(2026, 6, 1, 12, 0, 0, tzinfo=UTC)


def _candidate(*, story_id: str, run_id: str, summary: str) -> IncidentCandidate:
    return IncidentCandidate(
        category=FailureCategory.ARCHITECTURE_VIOLATION,
        severity=IncidentSeverity.CRITICAL,
        source_bc="verify-system",
        story_id=story_id,
        run_id=run_id,
        summary=summary,
        evidence={"layer": "structural"},
        observed_at=_NOW,
    )


def test_record_incident_persists_and_is_readable() -> None:
    accessor = ProjectionAccessor(build_projection_repositories(Path.cwd()))
    corpus = build_failure_corpus(accessor)

    incident_id = corpus.record_incident(
        _candidate(story_id="INT-FC-1", run_id="run-int-1", summary="arch broken")
    )

    rows = accessor.read_projection(
        ProjectionKind.FC_INCIDENTS,
        ProjectionFilter(story_id="INT-FC-1", run_id="run-int-1"),
    )
    assert len(rows) == 1
    incident = rows[0]
    assert incident.incident_id == incident_id
    assert incident.category is FailureCategory.ARCHITECTURE_VIOLATION
    assert incident.severity is IncidentSeverity.CRITICAL
    assert incident.incident_status is IncidentStatus.OBSERVED
    assert incident.evidence == {"layer": "structural"}


def test_record_incident_purge_run_removes_rows() -> None:
    accessor = ProjectionAccessor(build_projection_repositories(Path.cwd()))
    corpus = build_failure_corpus(accessor)

    corpus.record_incident(
        _candidate(story_id="INT-FC-2", run_id="run-purge", summary="to purge")
    )
    corpus.record_incident(
        _candidate(story_id="INT-FC-2", run_id="run-keep", summary="to keep")
    )

    result = accessor.purge_run("any-project", "INT-FC-2", "run-purge")
    # AK#9: fc_incidents-Zeile des Runs wird aktiv entfernt. (Andere FK-69-
    # Tabellen wie phase_state_projection werden vom Pipeline-Layer bootstrappt
    # und sind in dieser BC-isolierten Persistenz-Sicht nicht garantiert
    # vorhanden; der best-effort-Purge sammelt deren Fehler separat in errors.)
    assert result.purged_rows.get(ProjectionKind.FC_INCIDENTS, 0) == 1
    fc_errors = [e for e in result.errors if "fc_incidents" in e]
    assert fc_errors == [], f"fc_incidents purge must not error: {fc_errors}"

    purged = accessor.read_projection(
        ProjectionKind.FC_INCIDENTS,
        ProjectionFilter(story_id="INT-FC-2", run_id="run-purge"),
    )
    assert purged == []

    kept = accessor.read_projection(
        ProjectionKind.FC_INCIDENTS,
        ProjectionFilter(story_id="INT-FC-2", run_id="run-keep"),
    )
    assert len(kept) == 1
