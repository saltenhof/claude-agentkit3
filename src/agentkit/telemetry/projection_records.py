"""Sammeldatei: Re-Export der FK-69 Projektions-Record-Klassen als Union-Typ.

Schema-Owner bleiben die jeweiligen BCs (verify-system, story-closure, etc.).
Diese Datei definiert NUR die Union fuer den ProjectionAccessor.

Quellen:
- FK-69 §69.3 -- Tabellenumfang
- FK-69 §69.4 -- Schreib-Ownership (Schema-Owner je Tabelle)
"""

from __future__ import annotations

from agentkit.closure import StoryMetricsRecord
from agentkit.verify_system.stage_registry.records import (
    QAFindingRecord,
    QAStageResultRecord,
)

# ProjectionRecord: Discriminated union ueber alle FK-69-Read-Model-Klassen.
# Phase-State-Projection wird als dict[str, object] repraesentiert (kein
# eigenes BC-Record-Typ existiert fuer phase_state_projection in phase-framework).
# fc_*-Records fehlen noch (AG3-028 bringt die fc-Repository-Schreibpfade).
ProjectionRecord = QAStageResultRecord | QAFindingRecord | StoryMetricsRecord

__all__ = [
    "ProjectionRecord",
    "QAFindingRecord",
    "QAStageResultRecord",
    "StoryMetricsRecord",
]
