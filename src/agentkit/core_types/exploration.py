"""ExplorationGateStatus — Status des Exploration-Exit-Gates.

Source of truth: FK-23 §23.5.0 — concept/technical-design/23_modusermittlung_exploration_change_frame.md

Wire-Werte sind lowercase (Konzept-Code-Beispiel `PENDING = "pending"`).
"""

from __future__ import annotations

from enum import StrEnum


class ExplorationGateStatus(StrEnum):
    """Status des dreistufigen Exploration-Exit-Gates.

    Attributes:
        PENDING: Gate noch nicht vollstaendig bestanden bzw. Zwischenstufe.
        APPROVED: Alle Stufen bestanden — bereit fuer Implementation.
        REJECTED: Gate endgueltig abgelehnt; Eskalation.
    """

    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
