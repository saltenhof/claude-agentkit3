"""FailurePattern model of the failure-corpus BC (FK-41 §41.3.2).

Leaf module (analogous to ``incident.py``): ``FailurePattern`` is the record type
of the ``fc_patterns`` table. Imports only foundation types (``core_types``), so
that no import cycle ``failure_corpus`` <-> ``telemetry`` arises.

Schema fidelity to FK-41 §41.3.2:
- Required fields: project_key, pattern_id (FP-NNNN), status (pattern-status),
  category (FailureCategory), invariant, incident_refs (list[str]),
  promotion_rule, risk_level, incident_count, confirmed_at, confirmed_by.
- Optional: owner, check_ref, retired_at.
- ``incident_refs`` is a JSON array of the associated incident_id values
  (list[str], FK-41 §41.3.2).

AG3-040 sub-block (b): delivers ONLY the record model + repository skeleton. The
functional producer (``PatternPromotion``) and the promotion logic (clustering,
thresholds) are out of scope (FK-41 §41.5, follow-up story).
"""

from __future__ import annotations

import re
from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from agentkit.core_types import FailureCategory, PatternStatus

# FK-41 §41.3.2: pattern_id is ``FP-NNNN`` (sequence at least 4 digits).
# Enforce FAIL-CLOSED (symmetric to the DB CHECK fc_patterns_id_format).
# ASCII-only via ``\d`` + ``re.ASCII``: without the flag ``\d`` matches Unicode
# digits (e.g. ``FP-１２３４`` with fullwidth digits), but the DB CHECK only
# ``[0-9]``. ``re.ASCII`` restricts ``\d`` to ASCII digits and thus keeps all
# three layers (Pydantic, SQLite, Postgres) congruent (FK-41 fail-closed,
# rejects Unicode digits) and at the same time satisfies Sonar python:S6353.
_PATTERN_ID_PATTERN = re.compile(r"^FP-\d{4,}$", re.ASCII)


class PromotionRule(StrEnum):
    """Promotion rule of a FailurePattern (FK-41 §41.3.2).

    Attributes:
        WIEDERHOLUNG: repeated incidents of the same kind.
        HOHE_SCHWERE: single critical incident.
        CHECKBARKEIT: deterministically checkable at low FP risk.
    """

    WIEDERHOLUNG = "wiederholung"
    HOHE_SCHWERE = "hohe_schwere"
    CHECKBARKEIT = "checkbarkeit"


class PatternRiskLevel(StrEnum):
    """Risk level of a FailurePattern (FK-41 §41.3.2)."""

    MITTEL = "mittel"
    HOCH = "hoch"
    KRITISCH = "kritisch"


def _validate_incident_refs(value: object) -> list[str]:
    """FAIL-CLOSED: incident_refs MUST be a list of strings (FK-41 §41.3.2)."""
    if not isinstance(value, list):
        raise ValueError(  # noqa: TRY004 — pydantic wraps ValueError into ValidationError
            f"incident_refs must be a list of strings (FK-41 §41.3.2), got {type(value)!r}"
        )
    if not all(isinstance(item, str) for item in value):
        raise ValueError("incident_refs items must all be strings (FK-41 §41.3.2)")
    return list(value)


def _validate_pattern_id(value: str) -> str:
    """FAIL-CLOSED: pattern_id MUST be ``FP-NNNN`` (FK-41 §41.3.2)."""
    if _PATTERN_ID_PATTERN.fullmatch(value) is None:
        raise ValueError(
            f"pattern_id must match FP-NNNN (FK-41 §41.3.2), got {value!r}"
        )
    return value


class FailurePatternRecord(BaseModel):
    """Persisted FailurePattern (FK-41 §41.3.2, fc_patterns row).

    Frozen/extra-forbid: an unknown additional field is a contract violation
    (FAIL-CLOSED).

    Attributes:
        pattern_id: Unique pattern identity (PK, format ``FP-NNNN``).
        project_key: Project key (required, FK-41 §41.3.2).
        status: Pattern lifecycle (pattern-status, 4 values).
        category: Failure category (FailureCategory, 12 values).
        invariant: Precise, deterministic rule statement.
        incident_refs: JSON array of the associated incident_id values (list[str]).
        promotion_rule: Promotion rule (wiederholung | hohe_schwere | checkbarkeit).
        risk_level: Risk level (mittel | hoch | kritisch).
        incident_count: Denormalized counter; rebuildable from incident_refs.
        confirmed_at: Timestamp of the human confirmation (optional).
        confirmed_by: ``human`` on confirmation (no automatic entry).
        owner: Optional team identifier.
        check_ref: Optional reference to fc_check_proposals.check_id.
        retired_at: Optional decommissioning timestamp.
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
        """FAIL-CLOSED: ``accepted`` requires ``confirmed_by = human`` (FK-41 §41.3.2:239).

        Mirrors the conditional DB CHECK ``fc_patterns_accepted_human`` on both
        backends: no pattern transitions into status ``accepted`` without human
        confirmation.
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
