"""CheckProposal-Modell des Failure-Corpus-BC (FK-41 §41.3.3).

Blatt-Modul (analog ``incident.py``/``pattern.py``): ``CheckProposal`` ist der
Record-Typ der ``fc_check_proposals``-Tabelle. Importiert ausschliesslich
Foundation-Typen (``core_types``), damit kein Import-Zyklus ``failure_corpus``
<-> ``telemetry`` entsteht.

Schema-Treue zu FK-41 §41.3.3:
- Pflichtfelder: project_key, check_id (CHK-NNNN), status (check-status),
  pattern_ref (-> fc_patterns.pattern_id), invariant, check_type (6 Werte),
  pipeline_stage, pipeline_layer, owner, false_positive_risk, positive_fixtures,
  negative_fixtures, created_at.
- Optional: approved_at, approved_by, rejected_reason,
  effectiveness_last_checked_at, true_positives_90d, false_positives_90d.

AG3-040 Sub-Block (b): liefert NUR das Record-Modell + Repository-Skelett. Der
funktionale Producer (``CheckFactory``) und die Check-Ableitungs-Logik sind Out
of Scope (FK-41 §41.6, Folge-Story).
"""

from __future__ import annotations

import re
from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from agentkit.core_types import CheckStatus, CheckType

# FK-41 §41.3.3:265-266: positive_/negative_fixtures sind JSON-Arrays von
# {description, expected}-Objekten. FAIL-CLOSED erzwingen (symmetrisch zum
# DB-CHECK/Trigger fc_check_proposals_*_fixtures_shape) — die DB darf keinen
# fixtures-Wert halten, den der Repo-Decoder nicht lesen kann.
_REQUIRED_FIXTURE_KEYS = ("description", "expected")

# FK-41 §41.3.3:282: ``approved`` wird durch menschliche Freigabe erreicht;
# ``active`` ist ein Vorwaerts-Uebergang aus ``approved``. Beide Status setzen
# daher ``approved_by = human`` voraus (automatische Freigaben unzulaessig).
_HUMAN_APPROVAL_STATUSES = frozenset({CheckStatus.APPROVED, CheckStatus.ACTIVE})

# FK-41 §41.3.3: check_id ist ``CHK-NNNN`` (Sequenz mindestens 4-stellig).
# FAIL-CLOSED erzwingen (symmetrisch zum DB-CHECK fc_check_proposals_id_format).
# ASCII-only ([0-9], nicht ``\d``): ``\d`` matcht Unicode-Ziffern (z. B. ``CHK-１２３４``
# mit Fullwidth-Ziffern), der DB-CHECK aber nur ``[0-9]`` — ASCII haelt alle drei
# Schichten (Pydantic, SQLite, Postgres) exakt deckungsgleich.
_CHECK_ID_PATTERN = re.compile(r"^CHK-[0-9]{4,}$")


class FalsePositiveRisk(StrEnum):
    """False-Positive-Risiko eines Check-Proposals (FK-41 §41.3.3)."""

    NIEDRIG = "niedrig"
    MITTEL = "mittel"
    HOCH = "hoch"


def _validate_check_id(value: str) -> str:
    """FAIL-CLOSED: check_id MUSS ``CHK-NNNN`` sein (FK-41 §41.3.3)."""
    if _CHECK_ID_PATTERN.fullmatch(value) is None:
        raise ValueError(
            f"check_id must match CHK-NNNN (FK-41 §41.3.3), got {value!r}"
        )
    return value


def _validate_fixtures(value: object, field_name: str) -> list[dict[str, Any]]:
    """FAIL-CLOSED: fixtures MUSS list[{description, expected}] sein (FK-41 §41.3.3)."""
    if not isinstance(value, list):
        raise ValueError(  # noqa: TRY004 — pydantic wraps ValueError into ValidationError
            f"{field_name} must be a JSON array of objects (FK-41 §41.3.3), "
            f"got {type(value)!r}"
        )
    for item in value:
        if not isinstance(item, dict):
            raise ValueError(
                f"{field_name} items must be objects (FK-41 §41.3.3), "
                f"got {type(item)!r}"
            )
        missing = [key for key in _REQUIRED_FIXTURE_KEYS if key not in item]
        if missing:
            raise ValueError(
                f"{field_name} objects require keys {list(_REQUIRED_FIXTURE_KEYS)} "
                f"(FK-41 §41.3.3), missing {missing}"
            )
    return [dict(item) for item in value]


class CheckProposalRecord(BaseModel):
    """Persistiertes Check-Proposal (FK-41 §41.3.3, fc_check_proposals-Zeile).

    Frozen/extra-forbid: ein unbekanntes Zusatzfeld ist ein Vertragsbruch
    (FAIL-CLOSED).

    Attributes:
        check_id: Eindeutige Check-Identitaet (PK, Format ``CHK-NNNN``).
        project_key: Projekt-Schluessel (Pflicht, FK-41 §41.3.3).
        status: Check-Lebenszyklus (check-status, 5 Werte).
        pattern_ref: Verweis auf fc_patterns.pattern_id (Pflicht).
        invariant: Deterministische Regelaussage (abgeleitet aus Pattern).
        check_type: Check-Typ (6 FK-41-Werte).
        pipeline_stage: Ziel-Stage in der Verify-Pipeline.
        pipeline_layer: Ziel-Layer (1 = Structural, 2 = LLM-Eval, ...).
        owner: Team-Identifier.
        false_positive_risk: niedrig | mittel | hoch.
        positive_fixtures: JSON-Array mit ``{description, expected}``.
        negative_fixtures: JSON-Array mit ``{description, expected}``.
        created_at: Erstellungszeitpunkt.
        approved_at: Optionaler Freigabe-Zeitpunkt.
        approved_by: ``human`` bei Freigabe (automatische Freigaben unzulaessig).
        rejected_reason: Optionaler Ablehnungsgrund.
        effectiveness_last_checked_at: Optionaler Wirksamkeits-Pruefzeitpunkt.
        true_positives_90d: Optionaler 90-Tage-True-Positive-Zaehler.
        false_positives_90d: Optionaler 90-Tage-False-Positive-Zaehler.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    check_id: str
    project_key: str
    status: CheckStatus
    pattern_ref: str
    invariant: str
    check_type: CheckType
    pipeline_stage: str
    pipeline_layer: int
    owner: str
    false_positive_risk: FalsePositiveRisk
    positive_fixtures: list[dict[str, Any]] = Field(default_factory=list)
    negative_fixtures: list[dict[str, Any]] = Field(default_factory=list)
    created_at: datetime
    approved_at: datetime | None = None
    approved_by: str | None = None
    rejected_reason: str | None = None
    effectiveness_last_checked_at: datetime | None = None
    true_positives_90d: int | None = None
    false_positives_90d: int | None = None

    @field_validator("check_id")
    @classmethod
    def _check_check_id(cls, value: str) -> str:
        return _validate_check_id(value)

    @field_validator("positive_fixtures", mode="before")
    @classmethod
    def _check_positive_fixtures(cls, value: object) -> list[dict[str, Any]]:
        return _validate_fixtures(value, "positive_fixtures")

    @field_validator("negative_fixtures", mode="before")
    @classmethod
    def _check_negative_fixtures(cls, value: object) -> list[dict[str, Any]]:
        return _validate_fixtures(value, "negative_fixtures")

    @model_validator(mode="after")
    def _check_human_approval(self) -> CheckProposalRecord:
        """FAIL-CLOSED: ``approved``/``active`` erfordert ``approved_by = human`` (FK-41 §41.3.3:282).

        Spiegelt den konditionalen DB-CHECK ``fc_check_proposals_approved_human``
        auf beiden Backends: automatische Freigaben sind unzulaessig.
        """
        if self.status in _HUMAN_APPROVAL_STATUSES and self.approved_by != "human":
            raise ValueError(
                "approved/active check requires approved_by='human' (FK-41 §41.3.3)"
            )
        return self


__all__ = [
    "CheckProposalRecord",
    "FalsePositiveRisk",
]
