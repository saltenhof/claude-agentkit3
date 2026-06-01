"""Integration-Test: record_incident End-to-End-Empfaenger-Pfad (AG3-028 AK#7).

Laeuft via integration-conftest gegen Postgres. Ein Aufrufer-BC ruft
``FailureCorpus.record_incident``; der Incident ist anschliessend in
``fc_incidents`` ueber den Accessor lesbar (projektgebunden, FK-41 §41.3.1).
Zusaetzlich: purge_run entfernt die Zeilen des Runs (AK#9) und Cross-Project-
Isolation (Codex-r1).

Der SQLite-Pfad desselben Empfaenger-Vertrags ist in
``tests/unit/failure_corpus/test_top.py`` und
``tests/unit/telemetry/test_fc_incidents_projection_roundtrip.py`` abgedeckt
(AK#7: beide Backends).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from agentkit.bootstrap.composition_root import build_failure_corpus
from agentkit.core_types import FailureCategory, IncidentStatus
from agentkit.failure_corpus import IncidentCandidate, IncidentRole, IncidentSeverity
from agentkit.state_backend.store.projection_repositories import (
    build_projection_repositories,
)
from agentkit.telemetry.projection_accessor import (
    ProjectionAccessor,
    ProjectionFilter,
    ProjectionKind,
)


def _candidate(
    *, project_key: str, story_id: str, run_id: str, symptom: str
) -> IncidentCandidate:
    return IncidentCandidate(
        project_key=project_key,
        story_id=story_id,
        run_id=run_id,
        category=FailureCategory.ARCHITECTURE_VIOLATION,
        severity=IncidentSeverity.CRITICAL,
        phase="implementation",
        role=IncidentRole.QA,
        model="claude-opus",
        symptom=symptom,
        evidence=["layer: structural"],
        merge_blocked=True,
    )


def _fresh(accessor: ProjectionAccessor, *keys: tuple[str, str, str]) -> None:
    """Purge the test's own (project_key, story_id, run_id) tuples first.

    Test-Hygiene: macht den Test deterministisch unabhaengig von Restzeilen
    eines vorherigen Laufs derselben Session (fc_incidents lebt projektweit;
    kein State-Fantasieren, nur Vorbedingungs-Reset des eigenen Scopes).
    """
    for project_key, story_id, run_id in keys:
        accessor.purge_run(project_key, story_id, run_id)


def test_record_incident_persists_and_is_readable() -> None:
    accessor = ProjectionAccessor(build_projection_repositories(Path.cwd()))
    corpus = build_failure_corpus(accessor)
    _fresh(accessor, ("INT-PROJ", "INT-FC-1", "run-int-1"))

    incident_id = corpus.record_incident(
        _candidate(
            project_key="INT-PROJ",
            story_id="INT-FC-1",
            run_id="run-int-1",
            symptom="arch broken",
        )
    )

    rows = accessor.read_projection(
        ProjectionKind.FC_INCIDENTS,
        ProjectionFilter(
            project_key="INT-PROJ", story_id="INT-FC-1", run_id="run-int-1"
        ),
    )
    assert len(rows) == 1
    incident = rows[0]
    assert incident.incident_id == incident_id  # type: ignore[union-attr]
    assert incident.category is FailureCategory.ARCHITECTURE_VIOLATION  # type: ignore[union-attr]
    assert incident.severity is IncidentSeverity.CRITICAL  # type: ignore[union-attr]
    assert incident.incident_status is IncidentStatus.OBSERVED  # type: ignore[union-attr]
    assert incident.evidence == ["layer: structural"]  # type: ignore[union-attr]
    assert str(incident_id).startswith("FC-")


def test_record_incident_purge_run_removes_rows() -> None:
    accessor = ProjectionAccessor(build_projection_repositories(Path.cwd()))
    corpus = build_failure_corpus(accessor)
    _fresh(
        accessor,
        ("INT-PROJ", "INT-FC-2", "run-purge"),
        ("INT-PROJ", "INT-FC-2", "run-keep"),
    )

    corpus.record_incident(
        _candidate(
            project_key="INT-PROJ",
            story_id="INT-FC-2",
            run_id="run-purge",
            symptom="to purge",
        )
    )
    corpus.record_incident(
        _candidate(
            project_key="INT-PROJ",
            story_id="INT-FC-2",
            run_id="run-keep",
            symptom="to keep",
        )
    )

    result = accessor.purge_run("INT-PROJ", "INT-FC-2", "run-purge")
    # AK#9: fc_incidents-Zeile des Runs wird aktiv entfernt. Pflicht-Tabellen
    # eskalieren Purge-Fehler hart (Codex-r1); phase_state_projection bleibt
    # best-effort und sammelt etwaige Alt-Schema-Fehler separat.
    assert result.purged_rows.get(ProjectionKind.FC_INCIDENTS, 0) == 1

    purged = accessor.read_projection(
        ProjectionKind.FC_INCIDENTS,
        ProjectionFilter(
            project_key="INT-PROJ", story_id="INT-FC-2", run_id="run-purge"
        ),
    )
    assert purged == []

    kept = accessor.read_projection(
        ProjectionKind.FC_INCIDENTS,
        ProjectionFilter(
            project_key="INT-PROJ", story_id="INT-FC-2", run_id="run-keep"
        ),
    )
    assert len(kept) == 1


def test_record_incident_cross_project_isolation() -> None:
    accessor = ProjectionAccessor(build_projection_repositories(Path.cwd()))
    corpus = build_failure_corpus(accessor)
    _fresh(
        accessor,
        ("INT-PA", "X-1", "r-shared"),
        ("INT-PB", "X-1", "r-shared"),
    )

    # Gleiche story_id/run_id in zwei Projekten.
    corpus.record_incident(
        _candidate(
            project_key="INT-PA", story_id="X-1", run_id="r-shared", symptom="a"
        )
    )
    corpus.record_incident(
        _candidate(
            project_key="INT-PB", story_id="X-1", run_id="r-shared", symptom="b"
        )
    )

    rows_a = accessor.read_projection(
        ProjectionKind.FC_INCIDENTS,
        ProjectionFilter(project_key="INT-PA", story_id="X-1", run_id="r-shared"),
    )
    rows_b = accessor.read_projection(
        ProjectionKind.FC_INCIDENTS,
        ProjectionFilter(project_key="INT-PB", story_id="X-1", run_id="r-shared"),
    )
    assert len(rows_a) == 1
    assert len(rows_b) == 1
    assert rows_a[0].project_key == "INT-PA"  # type: ignore[union-attr]
    assert rows_b[0].project_key == "INT-PB"  # type: ignore[union-attr]

    # Purge in PA darf PB nicht beruehren.
    accessor.purge_run("INT-PA", "X-1", "r-shared")
    assert (
        accessor.read_projection(
            ProjectionKind.FC_INCIDENTS,
            ProjectionFilter(project_key="INT-PA", story_id="X-1", run_id="r-shared"),
        )
        == []
    )
    assert (
        len(
            accessor.read_projection(
                ProjectionKind.FC_INCIDENTS,
                ProjectionFilter(
                    project_key="INT-PB", story_id="X-1", run_id="r-shared"
                ),
            )
        )
        == 1
    )


def test_postgres_db_checks_reject_malformed_rows() -> None:
    """Postgres-DB-CHECKs lehnen Format-/Elementtyp-Verstoesse fail-closed ab.

    Codex-r4: pinnt den FK-41-§41.3.1/§41.4.1-DB-Vertrag DIREKT gegen echtes
    Postgres (nicht nur SQLite/Pydantic): incident_id != FC-YYYY-NNNN und
    evidence_json mit Nicht-String-Element muessen vom DB-CHECK abgewiesen werden.
    """
    import psycopg

    from agentkit.state_backend.store.projection_repositories import _postgres_connect

    cols = (
        "project_key, incident_id, run_id, story_id, category, severity, "
        "phase, role, model, symptom, evidence_json, recorded_at, incident_status"
    )
    insert = (
        f"INSERT INTO fc_incidents ({cols}) "
        "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)"
    )

    def _vals(incident_id: str, evidence_json: str) -> tuple[object, ...]:
        return (
            "INT-CHK",
            incident_id,
            "run-chk",
            "INT-CHK",
            "scope_drift",
            "high",
            "implementation",
            "worker",
            "m",
            "s",
            evidence_json,
            "2026-06-01T12:00:00+00:00",
            "observed",
        )

    bad_rows = [
        _vals("FC-2026-1", '["e1"]'),  # Sequenz < 4 Ziffern
        _vals("FC-2026-0001x", '["e1"]'),  # Nicht-Ziffern-Suffix
        _vals("FC-2026-0002", '[{"k": "v"}]'),  # Objekt-Element
        _vals("FC-2026-0003", "[1]"),  # Number-Element
    ]

    def _attempt(vals: tuple[object, ...]) -> None:
        with _postgres_connect() as conn:
            conn.execute(insert, vals)

    for vals in bad_rows:
        with pytest.raises(psycopg.errors.IntegrityError):
            _attempt(vals)
