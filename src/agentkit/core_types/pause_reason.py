"""PauseReason — Grund eines PAUSED-Phase-Zustandes.

Source of truth: FK-39 §39.2.2 — concept/technical-design/39_phase_state_persistenz.md
(Glossar-Eintrag Z. 62-69 und Beschreibung in §39.2.2).

Genau drei normierte Werte; jeder andere String ist ungueltig und wird
vom Phase Runner fail-closed abgewiesen (siehe `from_yield_status`).

Konzept-Drift-Notiz (AG3-021 Codex-Review): FK-39 §39.2.2 enthaelt im
Code-Beispiel lowercase Wire-Strings, das FK-39-Glossar (Z. 62-69)
nutzt UPPER_SNAKE_CASE. Die Story AG3-021 §2.1.1.1 traegt die
UPPER_SNAKE_CASE-Variante normativ; konsistent mit
QaContext/AttemptOutcome/FailureCause/EnvelopeStatus (upper-case).
Die Konzept-Inkonsistenz im FK-39-Code-Block ist im Story-Bericht
gemeldet.
"""

from __future__ import annotations

from enum import StrEnum
from types import MappingProxyType
from typing import TYPE_CHECKING, Final

if TYPE_CHECKING:
    from collections.abc import Mapping

# Synonym-Tabelle aus AG3-021 §2.1.4 — mappt historisch beobachtete
# Free-String-Werte auf die drei normierten PauseReason-Member.
# Vergleich ist case-insensitive (auf der Input-Seite); Schluessel sind
# bereits lowercase.
_YIELD_STATUS_SYNONYMS: Final[Mapping[str, str]] = MappingProxyType(
    {
        "awaiting_design_review": "AWAITING_DESIGN_REVIEW",
        "design_review_pending": "AWAITING_DESIGN_REVIEW",
        "design_review": "AWAITING_DESIGN_REVIEW",
        "awaiting_design_challenge": "AWAITING_DESIGN_CHALLENGE",
        "design_challenge": "AWAITING_DESIGN_CHALLENGE",
        "design_challenge_pending": "AWAITING_DESIGN_CHALLENGE",
        "governance_incident": "GOVERNANCE_INCIDENT",
        "governance_pause": "GOVERNANCE_INCIDENT",
        "governance_intervention": "GOVERNANCE_INCIDENT",
    },
)


class PauseReason(StrEnum):
    """Drei normierte Werte fuer `phase_state.paused_reason`.

    Attributes:
        AWAITING_DESIGN_REVIEW: Entwurfsartefakt wartet auf Design-Review
            (Exploration-Phase).
        AWAITING_DESIGN_CHALLENGE: Design-Review hat Einwaende erhoben,
            Pipeline pausiert bis Challenge-Prozess abgeschlossen.
        GOVERNANCE_INCIDENT: Governance-Observer hat kritischen Incident
            erkannt; Mensch muss intervenieren.
    """

    AWAITING_DESIGN_REVIEW = "AWAITING_DESIGN_REVIEW"
    AWAITING_DESIGN_CHALLENGE = "AWAITING_DESIGN_CHALLENGE"
    GOVERNANCE_INCIDENT = "GOVERNANCE_INCIDENT"

    @classmethod
    def from_yield_status(cls, raw: str) -> PauseReason:
        """Map a free-form yield-status string to a normierten PauseReason.

        Vorgesehen fuer den Migrationspfad v2 -> v3, in dem `result.yield_status`
        noch als freier String herumgereicht wird (siehe AG3-021 §2.1.4).
        Akzeptiert sowohl Synonyme aus dem Bestand
        (z.B. ``"design_review_pending"``) als auch den normierten
        Wire-Wert selbst (``"AWAITING_DESIGN_REVIEW"``).

        Args:
            raw: Beliebiger Yield-Status-String.

        Returns:
            Der zugehoerige ``PauseReason``-Wert.

        Raises:
            ValueError: Wenn ``raw`` weder ein Synonym noch ein
                normierter Wert ist (fail-closed; kein Default).
        """
        if not raw:
            raise ValueError(
                "PauseReason.from_yield_status received empty string",
            )

        normalized = raw.strip().lower()
        if not normalized:
            raise ValueError(
                "PauseReason.from_yield_status received whitespace-only string",
            )

        target_name = _YIELD_STATUS_SYNONYMS.get(normalized)
        if target_name is None:
            # The normalized form may itself be the canonical lowercase
            # wire-string variant — but our wire format is upper-case.
            # Accept the canonical upper-case wire-string regardless of case.
            try:
                return cls(raw.strip().upper())
            except ValueError as exc:
                raise ValueError(
                    f"PauseReason.from_yield_status: unknown yield_status "
                    f"{raw!r}; allowed synonyms: "
                    f"{sorted(_YIELD_STATUS_SYNONYMS)} or a canonical "
                    f"member name {sorted(m.value for m in cls)}",
                ) from exc

        return cls(target_name)
