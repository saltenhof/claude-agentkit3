"""StorySize und StoryMode — Story-Stammdaten-Enums.

Source of truth:
- StorySize: DK-10 §10.4 — concept/domain-design/10-story-lifecycle-und-erstellung.md
  (5 Stufen XS/S/M/L/XL; kein XXL, kein epic).
- StoryMode: FK-24 §24.3.2 — concept/technical-design/24_story_type_mode_terminalitaet.md
  plus AG3-018 (Fast-Modus).

`execution_route` ist `StoryMode | None`; nicht-implementierende Storys
tragen `None`, nicht einen eigenen Sentinel-Enum-Wert. Die zulaessigen
StoryMode-Werte sind in der Klasse selbst dokumentiert.
"""

from __future__ import annotations

from enum import StrEnum


class StorySize(StrEnum):
    """Story-Groesse pro DK-10 §10.4.

    Wire-Wert ist identisch zum Python-Member (upper-case).

    Attributes:
        XS: 1-2 Dateien, 1 Modul, kein neuer Test noetig.
        S: 3-10 Dateien, 1 Modul, wenige Unit-Tests.
        M: 10-30 Dateien, 1-2 Module, Unit- und Integrationstests.
        L: 30-80 Dateien, 2-4 Module, Unit/Integration/E2E.
        XL: 80+ Dateien, 4+ Module, Architekturwirksam.
    """

    XS = "XS"
    S = "S"
    M = "M"
    L = "L"
    XL = "XL"


class StoryMode(StrEnum):
    """Execution-Route fuer einen governenden Story-Lauf.

    Drei mogliche Werte; `execution_route` ist `StoryMode | None` und
    traegt `None` fuer nicht-implementierende Storys.

    Achtung: `mode`/`execution_route` darf nicht mit `operating_mode`
    aus FK-56 verwechselt werden — letzteres trennt `ai_augmented`
    und `story_execution`.

    Attributes:
        EXECUTION: Direkter Execution-Pfad ohne Exploration-Vorlauf.
        EXPLORATION: Exploration-Pfad als Vorlauf vor Implementation.
        FAST: Fast-Modus (AG3-018) — Disable von Story-scoped Guards.
    """

    EXECUTION = "execution"
    EXPLORATION = "exploration"
    FAST = "fast"
