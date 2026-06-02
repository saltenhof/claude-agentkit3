"""FailurePattern-Modell des Failure-Corpus-BC (FK-41 §41.3.2).

Blatt-Modul (analog ``incident.py``): ``FailurePattern`` ist der Record-Typ der
``fc_patterns``-Tabelle. Importiert ausschliesslich Foundation-Typen
(``core_types``), damit kein Import-Zyklus ``failure_corpus`` <-> ``telemetry``
entsteht.

Schema-Treue zu FK-41 §41.3.2:
- Pflichtfelder: project_key, pattern_id (FP-NNNN), status (pattern-status),
  category (FailureCategory), invariant, incident_refs (list[str]),
  promotion_rule, risk_level, incident_count, confirmed_at, confirmed_by.
- Optional: owner, check_ref, retired_at.
- ``incident_refs`` ist ein JSON-Array der zugehoerigen incident_id-Werte
  (list[str], FK-41 §41.3.2).

AG3-040 Sub-Block (b): liefert NUR das Record-Modell + Repository-Skelett. Der
funktionale Producer (``PatternPromotion``) und die Promotion-Logik
(Clustering, Schwellwerte) sind Out of Scope (FK-41 §41.5, Folge-Story).
"""

from __future__ import annotations

import re
from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from agentkit.core_types import FailureCategory, PatternStatus

# FK-41 §41.3.2: pattern_id ist ``FP-NNNN`` (Sequenz mindestens 4-stellig).
# FAIL-CLOSED erzwingen (symmetrisch zum DB-CHECK fc_patterns_id_format).
# ASCII-only ([0-9], nicht ``\d``): ``\d`` matcht Unicode-Ziffern (z. B. ``FP-１２３４``
# mit Fullwidth-Ziffern), der DB-CHECK aber nur ``[0-9]`` — ASCII haelt alle drei
# Schichten (Pydantic, SQLite, Postgres) exakt deckungsgleich.
_PATTERN_ID_PATTERN = re.compile(r"^FP-[0-9]{4,}$")


class PromotionRule(StrEnum):
    """Promotion-Regel eines FailurePattern (FK-41 §41.3.2).

    Attributes:
        WIEDERHOLUNG: wiederholte gleichartige Incidents.
        HOHE_SCHWERE: einzelner kritischer Incident.
        CHECKBARKEIT: deterministisch pruefbar bei niedrigem FP-Risiko.
    """

    WIEDERHOLUNG = "wiederholung"
    HOHE_SCHWERE = "hohe_schwere"
    CHECKBARKEIT = "checkbarkeit"


class PatternRiskLevel(StrEnum):
    """Risikostufe eines FailurePattern (FK-41 §41.3.2)."""

    MITTEL = "mittel"
    HOCH = "hoch"
    KRITISCH = "kritisch"


def _validate_incident_refs(value: object) -> list[str]:
    """FAIL-CLOSED: incident_refs MUSS eine Liste von Strings sein (FK-41 §41.3.2)."""
    if not isinstance(value, list):
        raise ValueError(  # noqa: TRY004 — pydantic wraps ValueError into ValidationError
            f"incident_refs must be a list of strings (FK-41 §41.3.2), got {type(value)!r}"
        )
    if not all(isinstance(item, str) for item in value):
        raise ValueError("incident_refs items must all be strings (FK-41 §41.3.2)")
    return list(value)


def _validate_pattern_id(value: str) -> str:
    """FAIL-CLOSED: pattern_id MUSS ``FP-NNNN`` sein (FK-41 §41.3.2)."""
    if _PATTERN_ID_PATTERN.fullmatch(value) is None:
        raise ValueError(
            f"pattern_id must match FP-NNNN (FK-41 §41.3.2), got {value!r}"
        )
    return value


class FailurePatternRecord(BaseModel):
    """Persistiertes FailurePattern (FK-41 §41.3.2, fc_patterns-Zeile).

    Frozen/extra-forbid: ein unbekanntes Zusatzfeld ist ein Vertragsbruch
    (FAIL-CLOSED).

    Attributes:
        pattern_id: Eindeutige Pattern-Identitaet (PK, Format ``FP-NNNN``).
        project_key: Projekt-Schluessel (Pflicht, FK-41 §41.3.2).
        status: Pattern-Lebenszyklus (pattern-status, 4 Werte).
        category: Failure-Kategorie (FailureCategory, 12 Werte).
        invariant: Praezise, deterministische Regelaussage.
        incident_refs: JSON-Array der zugehoerigen incident_id-Werte (list[str]).
        promotion_rule: Promotion-Regel (wiederholung | hohe_schwere | checkbarkeit).
        risk_level: Risikostufe (mittel | hoch | kritisch).
        incident_count: Denormalisierter Zaehler; rebuildbar aus incident_refs.
        confirmed_at: Zeitstempel der menschlichen Bestaetigung (optional).
        confirmed_by: ``human`` bei Bestaetigung (kein automatischer Eintrag).
        owner: Optionaler Team-Identifier.
        check_ref: Optionaler Verweis auf fc_check_proposals.check_id.
        retired_at: Optionaler Ausserdienststellungs-Zeitpunkt.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    pattern_id: str
    project_key: str
    status: PatternStatus
    category: FailureCategory
    invariant: str
    incident_refs: list[str] = Field(default_factory=list)
    promotion_rule: PromotionRule
    risk_level: PatternRiskLevel
    incident_count: int
    confirmed_at: datetime | None = None
    confirmed_by: str | None = None
    owner: str | None = None
    check_ref: str | None = None
    retired_at: datetime | None = None

    @field_validator("pattern_id")
    @classmethod
    def _check_pattern_id(cls, value: str) -> str:
        return _validate_pattern_id(value)

    @field_validator("incident_refs", mode="before")
    @classmethod
    def _check_incident_refs(cls, value: object) -> list[str]:
        return _validate_incident_refs(value)

    @model_validator(mode="after")
    def _check_human_confirmation(self) -> FailurePatternRecord:
        """FAIL-CLOSED: ``accepted`` erfordert ``confirmed_by = human`` (FK-41 §41.3.2:239).

        Spiegelt den konditionalen DB-CHECK ``fc_patterns_accepted_human`` auf
        beiden Backends: kein Pattern wechselt in Status ``accepted`` ohne
        menschliche Bestaetigung.
        """
        if self.status is PatternStatus.ACCEPTED and self.confirmed_by != "human":
            raise ValueError(
                "accepted pattern requires confirmed_by='human' (FK-41 §41.3.2)"
            )
        return self


__all__ = [
    "FailurePatternRecord",
    "PatternRiskLevel",
    "PromotionRule",
]
