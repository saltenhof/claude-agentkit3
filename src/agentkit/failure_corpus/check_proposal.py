"""CheckProposal model of the failure-corpus BC (FK-41 §41.3.3).

Leaf module (analogous to ``incident.py``/``pattern.py``): ``CheckProposal`` is
the record type of the ``fc_check_proposals`` table. Imports exclusively
foundation types (``core_types``) so that no import cycle ``failure_corpus``
<-> ``telemetry`` arises.

Schema fidelity to FK-41 §41.3.3:
- Required fields: project_key, check_id (CHK-NNNN), status (check-status),
  pattern_ref (-> fc_patterns.pattern_id), invariant, check_type (6 values),
  pipeline_stage, pipeline_layer, owner, false_positive_risk, positive_fixtures,
  negative_fixtures, created_at.
- Optional: approved_at, approved_by, rejected_reason,
  effectiveness_last_checked_at, true_positives_90d, false_positives_90d.

AG3-040 sub-block (b): delivers ONLY the record model + repository skeleton. The
functional producer (``CheckFactory``) and the check-derivation logic are out of
scope (FK-41 §41.6, follow-up story).
"""

from __future__ import annotations

import re
from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from agentkit.core_types import CheckStatus, CheckType

# FK-41 §41.3.3:265-266: positive_/negative_fixtures are JSON arrays of
# {description, expected} objects. Enforced FAIL-CLOSED (symmetrical to the
# DB CHECK/trigger fc_check_proposals_*_fixtures_shape) — the DB may not hold a
# fixtures value the repo decoder cannot read.
_REQUIRED_FIXTURE_KEYS = ("description", "expected")

# FK-41 §41.3.3:282: ``approved`` is reached by human release; ``active`` is a
# forward transition from ``approved``. Both statuses therefore require
# ``approved_by = human`` (automatic releases are not permitted).
_HUMAN_APPROVAL_STATUSES = frozenset({CheckStatus.APPROVED, CheckStatus.ACTIVE})

# FK-41 §41.3.3: check_id is ``CHK-NNNN`` (sequence at least 4 digits).
# Enforced FAIL-CLOSED (symmetrical to the DB CHECK fc_check_proposals_id_format).
# ASCII-only via ``\d`` + ``re.ASCII``: without the flag ``\d`` matches Unicode
# digits (e.g. ``CHK-１２３４`` with fullwidth digits), but the DB CHECK only
# ``[0-9]``. ``re.ASCII`` restricts ``\d`` to ASCII digits and thus keeps all
# three layers (Pydantic, SQLite, Postgres) congruent (FK-41 fail-closed,
# rejects Unicode digits) and at the same time satisfies Sonar python:S6353.
_CHECK_ID_PATTERN = re.compile(r"^CHK-\d{4,}$", re.ASCII)


class FalsePositiveRisk(StrEnum):
    """False-positive risk of a check proposal (FK-41 §41.3.3).

    Wire values (``niedrig``/``mittel``/``hoch``) are frozen FK-41 contract
    strings persisted in the ``false_positive_risk`` column; they are not
    English-renamed here (ARCH-55 out of scope — concept-level change).
    """

    NIEDRIG = "niedrig"
    MITTEL = "mittel"
    HOCH = "hoch"


def _validate_check_id(value: str) -> str:
    """FAIL-CLOSED: check_id MUST be ``CHK-NNNN`` (FK-41 §41.3.3)."""
    if _CHECK_ID_PATTERN.fullmatch(value) is None:
        raise ValueError(
            f"check_id must match CHK-NNNN (FK-41 §41.3.3), got {value!r}"
        )
    return value


def _validate_fixtures(value: object, field_name: str) -> list[dict[str, Any]]:
    """FAIL-CLOSED: fixtures MUST be list[{description, expected}] (FK-41 §41.3.3)."""
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
    """Persisted check proposal (FK-41 §41.3.3, fc_check_proposals row).

    Frozen/extra-forbid: an unknown extra field is a contract breach
    (FAIL-CLOSED).

    Attributes:
        check_id: Unique check identity (PK, format ``CHK-NNNN``).
        project_key: Project key (required, FK-41 §41.3.3).
        status: Check lifecycle (check-status, 5 values).
        pattern_ref: Reference to fc_patterns.pattern_id (required).
        invariant: Deterministic rule statement (derived from the pattern).
        check_type: Check type (6 FK-41 values).
        pipeline_stage: Target stage in the verify pipeline.
        pipeline_layer: Target layer (1 = structural, 2 = LLM eval, ...).
        owner: Team identifier.
        false_positive_risk: niedrig | mittel | hoch.
        positive_fixtures: JSON array with ``{description, expected}``.
        negative_fixtures: JSON array with ``{description, expected}``.
        created_at: Creation timestamp.
        approved_at: Optional release timestamp.
        approved_by: ``human`` on release (automatic releases not permitted).
        rejected_reason: Optional rejection reason.
        effectiveness_last_checked_at: Optional effectiveness-check timestamp.
        true_positives_90d: Optional 90-day true-positive counter.
        false_positives_90d: Optional 90-day false-positive counter.
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
        """FAIL-CLOSED: ``approved``/``active`` requires ``approved_by = human`` (FK-41 §41.3.3:282).

        Mirrors the conditional DB CHECK ``fc_check_proposals_approved_human``
        on both backends: automatic releases are not permitted.
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
