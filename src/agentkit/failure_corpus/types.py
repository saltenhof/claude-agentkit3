"""Value-Types des Failure-Corpus-BC (FK-41 §41.1/§41.4).

Blatt-Modul: importiert ausschliesslich stdlib. Keine Abhaengigkeit zu
telemetry, state_backend oder anderen BCs (Bluttyp-0-naehe; FK-41 §41.1).

Quellen:
- FK-41 §41.4 -- IncidentSeverity (LOW/MEDIUM/HIGH/CRITICAL)
- bc-cut-decisions §BC 13 failure-corpus -- Value-Type-Identitaeten
"""

from __future__ import annotations

from enum import StrEnum
from typing import NewType

# Stabile fachliche Identitaeten (FK-41 §41.1). NewType statt blossem ``str``,
# damit IncidentId/PatternId/CheckId nicht vermischbar sind (Typdisziplin).
IncidentId = NewType("IncidentId", str)
PatternId = NewType("PatternId", str)
CheckId = NewType("CheckId", str)


class IncidentSeverity(StrEnum):
    """Schwere eines Incidents pro FK-41 §41.4 (vier Stufen, lower-case).

    Eigenstaendige Failure-Corpus-Skala (LOW/MEDIUM/HIGH/CRITICAL), nicht zu
    verwechseln mit der verify-system-``Severity`` (BLOCKING/MAJOR/MINOR,
    FK-27): Incidents werden nach fachlicher Auswirkung klassifiziert, nicht
    nach QA-Finding-Blockingness.

    Attributes:
        LOW: geringe Auswirkung.
        MEDIUM: mittlere Auswirkung.
        HIGH: hohe Auswirkung.
        CRITICAL: kritische Auswirkung.
    """

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


__all__ = [
    "CheckId",
    "IncidentId",
    "IncidentSeverity",
    "PatternId",
]
