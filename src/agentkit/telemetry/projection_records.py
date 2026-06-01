"""Sammeldatei: Re-Export der FK-69 Projektions-Record-Klassen als Union-Typ.

Schema-Owner bleiben die jeweiligen BCs (verify-system, story-closure, etc.).
Diese Datei definiert NUR die Union fuer den ProjectionAccessor.

``StoryMetricsRecord`` (Schema-Owner: story-closure) und die ``ProjectionRecord``-
Union werden ausschliesslich fuer Typannotationen gebraucht (kein Laufzeit-
``isinstance``/Pydantic-Feld). Sie werden daher **lazy** ueber die Closure-Top-
Surface (``agentkit.closure``, AC001-konform) aufgeloest, damit
telemetry-and-events das story-closure-Package nicht beim Modul-Init importiert.
Die legitime Laufzeit-Richtung ist ``closure -> telemetry`` (FK-29 §29.6,
FK-69 §69.8): Closure schreibt via ``Telemetry.write_projection``. Konsistent
mit ``projection_accessor._build_kind_to_record_type`` (gleiches Anti-circular-
import-Muster).

Quellen:
- FK-69 §69.3 -- Tabellenumfang
- FK-69 §69.4 -- Schreib-Ownership (Schema-Owner je Tabelle)
- FK-29 §29.6 -- StoryMetric Schema-Owner = story-closure
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from agentkit.failure_corpus.incident import Incident
from agentkit.verify_system.stage_registry.records import (
    QAFindingRecord,
    QAStageResultRecord,
)

if TYPE_CHECKING:
    from agentkit.closure import StoryMetricsRecord

    # ProjectionRecord: Discriminated union ueber alle FK-69-Read-Model-Klassen.
    # Phase-State-Projection wird als dict[str, object] repraesentiert (kein
    # eigenes BC-Record-Typ existiert fuer phase_state_projection in phase-framework).
    # ``Incident`` ist der fc_incidents-Record (AG3-028 KONFLIKT-2). Er liegt im
    # Blatt-Modul ``failure_corpus.incident`` (importiert nur core_types + types,
    # NICHT telemetry) -- analog ``verify_system.stage_registry.records``.
    ProjectionRecord = (
        QAStageResultRecord | QAFindingRecord | StoryMetricsRecord | Incident
    )

__all__ = [
    "Incident",
    "ProjectionRecord",
    "QAFindingRecord",
    "QAStageResultRecord",
    "StoryMetricsRecord",
]


def __getattr__(name: str) -> Any:
    """Lazy Laufzeit-Aufloesung der closure-eigenen Namen (PEP 562).

    Vermeidet den Import-Zyklus telemetry <-> closure beim Modul-Init: das
    story-closure-Package wird erst beim ersten tatsaechlichen Laufzeit-Zugriff
    auf ``StoryMetricsRecord`` bzw. ``ProjectionRecord`` importiert -- zu diesem
    Zeitpunkt ist ``agentkit.closure`` laengst vollstaendig geladen.

    Args:
        name: Angefragter Modul-Attributname.

    Returns:
        Die aufgeloeste Klasse bzw. den Union-Typ.

    Raises:
        AttributeError: Fuer alle anderen Namen.
    """
    if name == "StoryMetricsRecord":
        from agentkit.closure import StoryMetricsRecord

        return StoryMetricsRecord
    if name == "ProjectionRecord":
        from agentkit.closure import StoryMetricsRecord

        return QAStageResultRecord | QAFindingRecord | StoryMetricsRecord
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
