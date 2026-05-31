"""Contract-Test: ProjectionKind pinnt die FK-69-Tabellen (FK-69 §69.3).

Dieser Test ist der fachliche Vertrag zwischen dem Accessor und dem FK-69-Konzept.
Aenderungen an ProjectionKind MUESSEN FK-69 §69.3 gegengeprueft werden.

DRIFT 1 (aufgeloest, AG3-035): FK-69 §69.3 autorisiert genau 7 Tabellen.
Die Story-Skizze nannte faelschlich 8 (inkl. WORKFLOW_METRICS) -- das ist
NICHT in FK-69. Dieser Contract-Test pinnt die korrekte Anzahl und die
korrekten Werte.
"""

from __future__ import annotations

from agentkit.telemetry.projection_accessor import ProjectionKind

# ---------------------------------------------------------------------------
# FK-69 §69.3: Genau 7 Tabellen
# ---------------------------------------------------------------------------


_FK69_EXPECTED_KINDS = {
    "qa_stage_results",
    "qa_findings",
    "story_metrics",
    "phase_state_projection",
    "fc_incidents",
    "fc_patterns",
    "fc_check_proposals",
}


def test_projection_kind_has_exactly_seven_values() -> None:
    """FK-69 §69.3 autorisiert exakt 7 Tabellen -- kein WORKFLOW_METRICS.

    DRIFT 1 (AG3-035): Story-Skizze nannte faelschlich 8 Werte. FK-69
    §69.3 ist autoritativ: genau 7.
    """
    actual_values = {kind.value for kind in ProjectionKind}
    assert len(actual_values) == 7, (
        f"ProjectionKind sollte genau 7 Werte haben (FK-69 §69.3). "
        f"Gefunden: {sorted(actual_values)}"
    )


def test_projection_kind_values_match_fk69_tables() -> None:
    """ProjectionKind-Werte entsprechen exakt den FK-69 §69.3-Tabellennamen."""
    actual_values = {kind.value for kind in ProjectionKind}
    assert actual_values == _FK69_EXPECTED_KINDS, (
        f"ProjectionKind-Werte weichen von FK-69 §69.3 ab.\n"
        f"Erwartet: {sorted(_FK69_EXPECTED_KINDS)}\n"
        f"Gefunden: {sorted(actual_values)}"
    )


def test_workflow_metrics_is_not_in_projection_kind() -> None:
    """WORKFLOW_METRICS ist NICHT in ProjectionKind (DRIFT 1 Aufloesung, FK-69 §69.3)."""
    values = {kind.value for kind in ProjectionKind}
    assert "workflow_metrics" not in values, (
        "WORKFLOW_METRICS darf NICHT in ProjectionKind sein. "
        "FK-69 §69.3 listet diese Tabelle nicht auf (sie ist FK-68). "
        "Story AG3-035 §2.1.1/AK2 ist auf die 7 FK-69-Werte angeglichen."
    )


def test_qa_stage_results_in_projection_kind() -> None:
    assert ProjectionKind.QA_STAGE_RESULTS == "qa_stage_results"


def test_qa_findings_in_projection_kind() -> None:
    assert ProjectionKind.QA_FINDINGS == "qa_findings"


def test_story_metrics_in_projection_kind() -> None:
    assert ProjectionKind.STORY_METRICS == "story_metrics"


def test_phase_state_projection_in_projection_kind() -> None:
    assert ProjectionKind.PHASE_STATE_PROJECTION == "phase_state_projection"


def test_fc_incidents_in_projection_kind() -> None:
    assert ProjectionKind.FC_INCIDENTS == "fc_incidents"


def test_fc_patterns_in_projection_kind() -> None:
    assert ProjectionKind.FC_PATTERNS == "fc_patterns"


def test_fc_check_proposals_in_projection_kind() -> None:
    assert ProjectionKind.FC_CHECK_PROPOSALS == "fc_check_proposals"


# ---------------------------------------------------------------------------
# Verifiziere DRIFT-AG3-035-Aufloesung: DRIFT-Kommentar aus verify_system entfernt
# ---------------------------------------------------------------------------


def test_drift_ag3_035_resolved_in_verify_system() -> None:
    """Direkter state_backend-Import mit DRIFT-Marker entfernt aus verify_system/system.py.

    AG3-035 hat diesen Drift aufgeloest: StoryContext wird jetzt via Injection
    uebergeben, nicht via direktem state_backend.store-Import in _execute_layer.
    """
    import pathlib

    system_py = pathlib.Path(__file__).parents[3] / "src" / "agentkit" / "verify_system" / "system.py"
    content = system_py.read_text(encoding="utf-8")
    # Der urspruengliche DRIFT-Marker-Import muss weg sein:
    assert 'load_story_context  # DRIFT-AG3-035' not in content, (
        "verify_system/system.py enthaelt noch den urspruenglichen DRIFT-AG3-035-Import. "
        "AG3-035 hat diesen Drift aufgeloest: StoryContext via Injection."
    )
