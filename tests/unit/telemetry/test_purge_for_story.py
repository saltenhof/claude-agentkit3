"""Unit-Tests fuer ProjectionAccessor.purge_run.

Testet:
- run-scoped purge leert die 4 aktiven Tabellen fuer (project_key, story_id, run_id)
- Andere run_ids/stories bleiben unangetastet
- PurgeResult.purged_rows zaehlt pro Kind
- errors leer wenn alle Repos ok
- errors gefuellt bei Repo-Fehler (best-effort)

Befund A (AG3-035 Remediation): purge_for_story-Alias entfernt (war stiller
No-op: project_key="" matcht keine echte Zeile -> FAIL-CLOSED-Verstoss).
Nur purge_run(project_key, story_id, run_id) existiert noch (FK-69 §69.10.1).
"""

from __future__ import annotations

from unittest.mock import MagicMock

from agentkit.telemetry.projection_accessor import (
    ProjectionAccessor,
    ProjectionKind,
    PurgeResult,
)

# ---------------------------------------------------------------------------
# Hilfsfunktionen
# ---------------------------------------------------------------------------


def _make_repos(
    *,
    qa_stage_rows: int = 0,
    qa_finding_rows: int = 0,
    story_metrics_rows: int = 0,
    phase_state_rows: int = 0,
) -> MagicMock:
    """Erzeugt Mock-Repos mit konfigurierbaren Zaehlern."""
    repos = MagicMock()
    repos.qa_stage_results = MagicMock()
    repos.qa_stage_results.purge_run.return_value = qa_stage_rows
    repos.qa_findings = MagicMock()
    repos.qa_findings.purge_run.return_value = qa_finding_rows
    repos.story_metrics = MagicMock()
    repos.story_metrics.purge_run.return_value = story_metrics_rows
    repos.phase_state_projection = MagicMock()
    repos.phase_state_projection.purge_run.return_value = phase_state_rows
    return repos


# ---------------------------------------------------------------------------
# Grundlegende Purge-Korrektheit
# ---------------------------------------------------------------------------


def test_purge_run_calls_all_four_repos() -> None:
    """purge_run leert alle 4 aktiven Tabellen fuer (project_key, story_id, run_id)."""
    repos = _make_repos(
        qa_stage_rows=3, qa_finding_rows=5, story_metrics_rows=1, phase_state_rows=2
    )
    accessor = ProjectionAccessor(repos)

    accessor.purge_run("proj-k", "STORY-001", "run-abc")

    repos.qa_stage_results.purge_run.assert_called_once_with("proj-k", "STORY-001", "run-abc")
    repos.qa_findings.purge_run.assert_called_once_with("proj-k", "STORY-001", "run-abc")
    repos.story_metrics.purge_run.assert_called_once_with("proj-k", "STORY-001", "run-abc")
    repos.phase_state_projection.purge_run.assert_called_once_with(
        "proj-k", "STORY-001", "run-abc"
    )


def test_purge_run_result_counts_per_kind() -> None:
    """PurgeResult.purged_rows enthaelt korrekte Zaehlung pro Kind."""
    repos = _make_repos(
        qa_stage_rows=3, qa_finding_rows=7, story_metrics_rows=1, phase_state_rows=4
    )
    accessor = ProjectionAccessor(repos)

    result = accessor.purge_run("pk", "S-001", "run-xyz")

    assert isinstance(result, PurgeResult)
    assert result.purged_rows[ProjectionKind.QA_STAGE_RESULTS] == 3
    assert result.purged_rows[ProjectionKind.QA_FINDINGS] == 7
    assert result.purged_rows[ProjectionKind.STORY_METRICS] == 1
    assert result.purged_rows[ProjectionKind.PHASE_STATE_PROJECTION] == 4
    assert result.errors == []


def test_purge_run_errors_empty_on_success() -> None:
    """errors ist leer wenn alle Repos erfolgreich loeschen."""
    repos = _make_repos(qa_stage_rows=0, qa_finding_rows=0)
    accessor = ProjectionAccessor(repos)

    result = accessor.purge_run("pk", "S-001", "run-xyz")

    assert result.errors == []


# ---------------------------------------------------------------------------
# run_id-Scoping: falsche run_id oder story_id wird nicht betroffen
# ---------------------------------------------------------------------------


def test_purge_run_scoped_to_run_id() -> None:
    """purge_run uebergibt korrekte run_id an alle Repos (Scoping via Aufrufargument)."""
    repos = _make_repos()
    accessor = ProjectionAccessor(repos)

    accessor.purge_run("proj", "STORY-999", "run-SPECIFIC")

    # Alle Repos bekommen run-SPECIFIC, nicht einen anderen run_id
    for repo_attr in ["qa_stage_results", "qa_findings", "story_metrics", "phase_state_projection"]:
        getattr(repos, repo_attr).purge_run.assert_called_once_with(
            "proj", "STORY-999", "run-SPECIFIC"
        )


# ---------------------------------------------------------------------------
# Fehlerbehandlung: best-effort, errors werden propagiert
# ---------------------------------------------------------------------------


def test_purge_run_error_in_one_repo_propagated_to_errors() -> None:
    """Fehler in einem Repo-Purge wird in errors[] propagiert, andere Repos laufen weiter."""
    repos = _make_repos(qa_stage_rows=2, qa_finding_rows=3)
    repos.story_metrics.purge_run.side_effect = RuntimeError("DB unavailable")
    accessor = ProjectionAccessor(repos)

    result = accessor.purge_run("pk", "S-001", "run-xyz")

    # QA-Tabellen wurden geleert
    assert result.purged_rows.get(ProjectionKind.QA_STAGE_RESULTS) == 2
    assert result.purged_rows.get(ProjectionKind.QA_FINDINGS) == 3
    # story_metrics Fehler in errors
    assert len(result.errors) == 1
    assert "story_metrics" in result.errors[0]
    assert "RuntimeError" in result.errors[0]
    # Accessor hat dennoch phase_state_projection versucht
    repos.phase_state_projection.purge_run.assert_called_once()


def test_purge_run_all_errors_collected() -> None:
    """Alle Repo-Fehler werden gesammelt; Ergebnis hat errors fuer jeden Fehlschlag."""
    repos = MagicMock()
    for attr in ["qa_stage_results", "qa_findings", "story_metrics", "phase_state_projection"]:
        getattr(repos, attr).purge_run.side_effect = ValueError(f"{attr} failed")
    accessor = ProjectionAccessor(repos)

    result = accessor.purge_run("pk", "S-001", "run-xyz")

    assert len(result.errors) == 4


# ---------------------------------------------------------------------------
# fc_*-Tabellen werden NICHT gepurgt in AG3-035
# (AG3-028 bringt fc-Repos + Schreibpfad + fc_patterns-Recompute)
# ---------------------------------------------------------------------------


def test_fc_tables_not_purged_in_ag3_035() -> None:
    """purge_run loescht KEINE fc_*-Zeilen in AG3-035 (nach AG3-028 vertagt).

    FK-69 §69.9: reset eines run_id MUSS fc_incidents entfernen und
    fc_patterns neu berechnen. Das wird mit den fc-Repos in AG3-028
    implementiert. # DRIFT-AG3-028
    """
    repos = _make_repos()
    accessor = ProjectionAccessor(repos)

    accessor.purge_run("pk", "S-001", "run-xyz")

    # Keine fc_*-Attribute auf den Mock-Repos erwartet
    # (der Mock hat keine fc_incidents.purge_run-Methode aufgerufen)
    # Sicherstellung: nur die 4 bekannten Repos werden angesprochen
    call_attrs = [
        "qa_stage_results",
        "qa_findings",
        "story_metrics",
        "phase_state_projection",
    ]
    for attr in call_attrs:
        getattr(repos, attr).purge_run.assert_called_once()

    # fc_*-Attribute wurden NICHT aufgerufen (kein hasattr-Aufruf auf fc_incidents)
    # Der Mock wuerde bei Zugriff einen neuen MagicMock erzeugen; wir pruefen
    # sicher, dass kein unerwarteter Aufruf stattfand:
    assert repos.mock_calls.count == repos.mock_calls.count  # sanity
    fc_calls = [c for c in repos.mock_calls if "fc_" in str(c)]
    assert fc_calls == [], f"Unexpected fc_* calls: {fc_calls}"


# ---------------------------------------------------------------------------
# Befund A (AG3-035 Remediation): purge_for_story-Alias entfernt
# ---------------------------------------------------------------------------


def test_purge_for_story_does_not_exist() -> None:
    """purge_for_story ist entfernt (war stiller No-op, FAIL-CLOSED-Verstoss).

    Die konzept-wahre API ist purge_run(project_key, story_id, run_id)
    (FK-69 §69.10.1, run-scoped). Aufruf mit leerem project_key waere ein
    stiller No-op (kein echtes Loeschen) -- das ist FAIL-CLOSED-widrig.
    """
    repos = _make_repos()
    accessor = ProjectionAccessor(repos)
    assert not hasattr(accessor, "purge_for_story"), (
        "purge_for_story-Alias wurde nicht entfernt. "
        "Nutze purge_run(project_key, story_id, run_id) (FK-69 §69.10.1)."
    )
