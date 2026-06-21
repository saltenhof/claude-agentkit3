"""Contract-Test: ProjectionKind pinnt die FK-69-Tabellen (FK-69 §69.3).

Dieser Test ist der fachliche Vertrag zwischen dem Accessor und dem FK-69-Konzept.
Aenderungen an ProjectionKind MUESSEN FK-69 §69.3 gegengeprueft werden.

DRIFT 1 (aufgeloest, AG3-035): FK-69 §69.3 autorisiert genau 7 Tabellen.
Die Story-Skizze nannte faelschlich 8 (inkl. WORKFLOW_METRICS) -- das ist
NICHT in FK-69. Dieser Contract-Test pinnt die korrekte Anzahl und die
korrekten Werte.

AG3-108 (2026-06-13): FK-69 §69.15 autorisiert via Codex Approval Flow eine
achte Tabelle: qa_check_outcomes (Per-Check-Outcome-Read-Model, Owner
verify-system). Die Anzahl steigt auf 8.
"""

from __future__ import annotations

from agentkit.backend.telemetry.projection_accessor import ProjectionKind

# ---------------------------------------------------------------------------
# FK-69 §69.3 + §69.15: Genau 8 Tabellen (AG3-108 erweitert um qa_check_outcomes)
# ---------------------------------------------------------------------------


_FK69_EXPECTED_KINDS = {
    "qa_stage_results",
    "qa_findings",
    "qa_check_outcomes",
    "story_metrics",
    "phase_state_projection",
    "fc_incidents",
    "fc_patterns",
    "fc_check_proposals",
}


def test_projection_kind_has_exactly_seven_values() -> None:
    """FK-69 §69.3+§69.15 autorisiert exakt 8 Tabellen (AG3-108: qa_check_outcomes).

    DRIFT 1 (AG3-035): Story-Skizze nannte faelschlich 8 Werte. FK-69
    §69.3 ist autoritativ: die 7 Originaltabellen.
    AG3-108: FK-69 §69.15 erweitert den Kanon um qa_check_outcomes via
    Codex Approval Flow. Der Gesamtumfang betraegt nun 8 Tabellen.
    """
    actual_values = {kind.value for kind in ProjectionKind}
    assert len(actual_values) == 8, (
        f"ProjectionKind sollte genau 8 Werte haben (FK-69 §69.3+§69.15, AG3-108). "
        f"Gefunden: {sorted(actual_values)}"
    )


def test_projection_kind_values_match_fk69_tables() -> None:
    """ProjectionKind-Werte entsprechen exakt den FK-69 §69.3+§69.15-Tabellennamen."""
    actual_values = {kind.value for kind in ProjectionKind}
    assert actual_values == _FK69_EXPECTED_KINDS, (
        f"ProjectionKind-Werte weichen von FK-69 §69.3+§69.15 ab.\n"
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
    """verify_system/system.py importiert StoryContext NICHT mehr aus state_backend.store.

    AG3-035 (echter Drift-Fix): der BC-Topologie-Bruch ist real aufgeloest --
    ``run_qa_subflow`` loest den ``StoryContext`` ueber den injizierten
    ``StoryContextQueryPort`` auf, nicht via direktem
    ``state_backend.store``-Import. Dieser Test prueft den ECHTEN Zustand
    (Abwesenheit des Imports + Nutzung des Ports), nicht nur einen
    Marker-Kommentar (Codex-Recheck N1: keine Marker-Kosmetik).
    """
    import pathlib

    system_py = (
        pathlib.Path(__file__).parents[3]
        / "src"
        / "agentkit"
        / "backend"
        / "verify_system"
        / "system.py"
    )
    content = system_py.read_text(encoding="utf-8")
    # Kein direkter state_backend.store-Import mehr (der eigentliche Drift):
    assert "from agentkit.backend.state_backend.store import" not in content, (
        "verify_system/system.py importiert weiterhin direkt aus "
        "agentkit.backend.state_backend.store. AG3-035 verlangt Aufloesung des "
        "BC-Topologie-Drifts via StoryContextQueryPort-Injection."
    )
    # Der Port wird tatsaechlich genutzt (kein toter Pfad):
    assert "self.story_context_port.load(" in content, (
        "run_qa_subflow nutzt den injizierten StoryContextQueryPort nicht."
    )
    assert "StoryContextQueryPort" in content, (
        "verify_system/system.py referenziert den StoryContextQueryPort nicht."
    )
