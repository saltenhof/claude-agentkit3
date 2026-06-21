"""Integration-Test: ProjectionAccessor Import-/Buildability-Smoke-Test.

Reine Import-/Buildability-Pruefung ohne DB-Zugriff (kein ``save_*``/``read_*``,
keine offene Connection). AG3-051 (Codex-Fix): ``telemetry/`` ist daher NICHT in
der Postgres-Allow-List der integration conftest.py — dieser Test zieht **kein**
Docker/Postgres an und laeuft Docker-frei.

Fuer den echten SQLite-Roundtrip (write -> read): siehe
``tests/unit/telemetry/test_projection_roundtrip.py``.
"""

from __future__ import annotations


def test_projection_accessor_module_importable() -> None:
    """ProjectionAccessor und ProjectionKind sind korrekt importierbar."""
    from agentkit.backend.telemetry.projection_accessor import (
        ProjectionKind,
    )

    # Sanity: alle 8 FK-69-Tabellen sind in ProjectionKind (AG3-108 added
    # qa_check_outcomes as the per-check-outcome read model, FK-69 §69.15).
    assert len(list(ProjectionKind)) == 8
    assert ProjectionKind.QA_STAGE_RESULTS == "qa_stage_results"
    assert ProjectionKind.STORY_METRICS == "story_metrics"
    assert ProjectionKind.QA_CHECK_OUTCOMES == "qa_check_outcomes"


def test_projection_repositories_buildable() -> None:
    """build_projection_repositories kann ohne Fehler aufgerufen werden."""
    from pathlib import Path

    from agentkit.backend.state_backend.store.projection_repositories import (
        build_projection_repositories,
    )

    repos = build_projection_repositories(Path("."))
    assert repos is not None
    assert repos.qa_stage_results is not None
    assert repos.qa_findings is not None
    assert repos.story_metrics is not None
    assert repos.phase_state_projection is not None


def test_composition_root_builds_accessor() -> None:
    """build_projection_accessor in Composition-Root funktioniert."""
    from pathlib import Path

    from agentkit.backend.bootstrap.composition_root import build_projection_accessor

    accessor = build_projection_accessor(Path("."))
    assert accessor is not None
