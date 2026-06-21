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

import pytest

from agentkit.backend.telemetry.projection_accessor import (
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
    fc_incidents_rows: int = 0,
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
    repos.fc_incidents = MagicMock()
    repos.fc_incidents.purge_run.return_value = fc_incidents_rows
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
# Fehlerbehandlung (AG3-028 Codex-r1): Pflicht-Tabellen eskalieren hart;
# nur phase_state_projection ist best-effort (dokumentierter Alt-Schema-Fall).
# ---------------------------------------------------------------------------


def test_purge_run_mandatory_table_error_escalates() -> None:
    """Ein Purge-Fehler einer Pflicht-Tabelle (story_metrics) eskaliert hart.

    Codex-r1 (FK-69 §69.11.5): fc_incidents/QA/story_metrics-Purge-Fehler duerfen
    NICHT im blanket-catch verschwinden — kein FK-69-Zustand nach Reset.
    """
    repos = _make_repos(qa_stage_rows=2, qa_finding_rows=3)
    repos.story_metrics.purge_run.side_effect = RuntimeError("DB unavailable")
    accessor = ProjectionAccessor(repos)

    with pytest.raises(RuntimeError, match="DB unavailable"):
        accessor.purge_run("pk", "S-001", "run-xyz")


def test_purge_run_fc_incidents_error_escalates() -> None:
    """fc_incidents-Purge-Fehler eskaliert hart (Codex-r1 ERROR 4)."""
    repos = _make_repos()
    repos.fc_incidents.purge_run.side_effect = RuntimeError("fc down")
    accessor = ProjectionAccessor(repos)

    with pytest.raises(RuntimeError, match="fc down"):
        accessor.purge_run("pk", "S-001", "run-xyz")


def test_purge_run_phase_state_error_is_best_effort() -> None:
    """Nur phase_state_projection bleibt best-effort (Alt-Schema-Sonderfall)."""
    repos = _make_repos(qa_stage_rows=1, fc_incidents_rows=1)
    repos.phase_state_projection.purge_run.side_effect = ValueError("no run_id col")
    accessor = ProjectionAccessor(repos)

    result = accessor.purge_run("pk", "S-001", "run-xyz")

    # Pflicht-Tabellen liefen durch; phase_state-Fehler ist gesammelt.
    assert result.purged_rows.get(ProjectionKind.FC_INCIDENTS) == 1
    assert len(result.errors) == 1
    assert "phase_state_projection" in result.errors[0]


# ---------------------------------------------------------------------------
# fc_incidents wird gepurgt (AG3-028 KONFLIKT-2, AK#9)
# fc_patterns/fc_check_proposals folgen mit ihren Producer-Stories.
# ---------------------------------------------------------------------------


def test_fc_incidents_purged_in_ag3_028() -> None:
    """purge_run loescht fc_incidents-Zeilen des Runs (FK-41 §41.3 / FK-69 §69.9).

    AG3-028 KONFLIKT-2 loest den frueheren # DRIFT-AG3-028-Marker auf:
    fc_incidents ist accessor-owned und wird beim Reset aktiv geleert.
    """
    repos = _make_repos(fc_incidents_rows=2)
    accessor = ProjectionAccessor(repos)

    result = accessor.purge_run("pk", "S-001", "run-xyz")

    repos.fc_incidents.purge_run.assert_called_once_with("pk", "S-001", "run-xyz")
    assert result.purged_rows.get(ProjectionKind.FC_INCIDENTS) == 2

    # fc_patterns / fc_check_proposals haben (noch) keinen Repo -> nicht gepurgt
    fc_pattern_calls = [
        c
        for c in repos.mock_calls
        if "fc_patterns" in str(c) or "fc_check_proposals" in str(c)
    ]
    assert fc_pattern_calls == [], f"Unexpected fc_patterns calls: {fc_pattern_calls}"


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
