"""StoryDependencyKind — Story-Abhaengigkeitskanten.

Source of truth: FK-70 §70.4.2 — concept/technical-design/70_story_planung_abhaengigkeiten_ausfuehrungsplanung.md
(Z. 211-220, acht Werte).

Ersetzt das v2-Vokabular ``blocks/derives_from/branches_off`` (drei
Werte) vollstaendig.
"""

from __future__ import annotations

from enum import StrEnum


class StoryDependencyKind(StrEnum):
    """Story-Abhaengigkeitskante pro FK-70 §70.4.2.

    `soft_story_dependency` ist KEIN harter Topologie-Blocker; sie
    beeinflusst Priorisierung/Scheduling, darf aber keine Story von
    `READY` auf nicht-ausfuehrbar setzen.

    Attributes:
        HARD_STORY_DEPENDENCY: Harte Voraussetzung; Story bleibt
            blockiert bis Vorgaenger `completed`.
        SOFT_STORY_DEPENDENCY: Weicher Hint fuer Scheduling.
        SERIAL_EXECUTION_CONSTRAINT: Erzwingt sequenzielle Ausfuehrung.
        MUTEX_CONSTRAINT: Mutex zwischen zwei Stories.
        SHARED_CONTRACT_DEPENDENCY: Gemeinsamer Vertrag (Schema/API).
        SHARED_FILE_CONFLICT: Beruehren dieselben Dateien.
        EXTERNAL_DEPENDENCY: Externe Abhaengigkeit (Lib, Tool, Service).
        HUMAN_GATE_DEPENDENCY: Wartet auf menschliche Entscheidung.
    """

    HARD_STORY_DEPENDENCY = "hard_story_dependency"
    SOFT_STORY_DEPENDENCY = "soft_story_dependency"
    SERIAL_EXECUTION_CONSTRAINT = "serial_execution_constraint"
    MUTEX_CONSTRAINT = "mutex_constraint"
    SHARED_CONTRACT_DEPENDENCY = "shared_contract_dependency"
    SHARED_FILE_CONFLICT = "shared_file_conflict"
    EXTERNAL_DEPENDENCY = "external_dependency"
    HUMAN_GATE_DEPENDENCY = "human_gate_dependency"
