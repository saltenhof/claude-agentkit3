"""Value-Types des Failure-Corpus-BC (FK-41 §41.1/§41.3.1/§41.4).

Blatt-Modul: importiert ausschliesslich stdlib. Keine Abhaengigkeit zu
telemetry, state_backend oder anderen BCs (Bluttyp-0-naehe; FK-41 §41.1).

Quellen:
- FK-41 §41.3.1 -- IncidentRole (worker | qa | governance)
- FK-41 §41.4 -- IncidentSeverity (FK-41 §41.3.1: niedrig/mittel/hoch/kritisch;
  hier als stabile englische Wire-Werte low/medium/high/critical, 4 Stufen)
- bc-cut-decisions §BC 13 failure-corpus -- Value-Type-Identitaeten
"""

from __future__ import annotations

from enum import StrEnum
from typing import NewType

# Stabile fachliche Identitaeten (FK-41 §41.1). NewType statt blossem ``str``,
# damit IncidentId/PatternId/CheckId nicht vermischbar sind (Typdisziplin).
# Format: IncidentId = "FC-YYYY-NNNN" (FK-41 §41.3.1/§41.4.1).
IncidentId = NewType("IncidentId", str)
PatternId = NewType("PatternId", str)
CheckId = NewType("CheckId", str)


class IncidentSeverity(StrEnum):
    """Schwere eines Incidents pro FK-41 §41.3.1/§41.4 (vier Stufen).

    Eigenstaendige Failure-Corpus-Skala (4 Stufen, fachliche Auswirkung), nicht
    zu verwechseln mit der verify-system-``core_types.Severity``
    (BLOCKING/MAJOR/MINOR, 3 Stufen, FK-27 QA-Finding-Blockingness).

    FK-41 §41.3.1 nennt die Stufen ``niedrig | mittel | hoch | kritisch``; hier
    als stabile englische Wire-Werte (analog ``FailureCategory``). Es gibt in
    ``core_types`` aktuell KEINE 4-stufige Incident-Severity-Enum als SSOT — die
    dort vorhandene ``Severity`` ist die FK-27-QA-Skala mit anderer Semantik und
    nur 3 Werten. Diese Enum ist daher die FK-41-§41.3.1-treue SSOT fuer die
    ``fc_incidents.severity``-Spalte. Siehe Worker-Notiz (AG3-021-Frage).

    Attributes:
        LOW: geringe Auswirkung (FK-41 ``niedrig``).
        MEDIUM: mittlere Auswirkung (FK-41 ``mittel``).
        HIGH: hohe Auswirkung (FK-41 ``hoch``).
        CRITICAL: kritische Auswirkung (FK-41 ``kritisch``).
    """

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class IncidentRole(StrEnum):
    """Ausfuehrender Akteur eines Incidents pro FK-41 §41.3.1.

    Genau die drei FK-41-§41.3.1-Werte (``worker | qa | governance``). Die
    ``fc_incidents.role``-Spalte CHECK-constrained sich auf diese Werte.

    Attributes:
        WORKER: Implementierender Worker-Agent.
        QA: QA-/Verify-Akteur.
        GOVERNANCE: Governance-Beobachtung.
    """

    WORKER = "worker"
    QA = "qa"
    GOVERNANCE = "governance"


__all__ = [
    "CheckId",
    "IncidentId",
    "IncidentRole",
    "IncidentSeverity",
    "PatternId",
]
