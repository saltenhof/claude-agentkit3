"""Incident models of the failure-corpus BC (FK-41 §41.3.1/§41.4.1).

Leaf module (KONFLIKT-2, AG3-028): ``Incident`` is the record type that the
``ProjectionAccessor`` resolves via the ``_KIND_TO_RECORD_TYPE`` mapping for
``ProjectionKind.FC_INCIDENTS``. So that no import cycle
``failure_corpus`` <-> ``telemetry`` arises there, this module imports only
foundation types (``core_types``) and the BC-owned ``types`` — analogous to
``verify_system.stage_registry.records``, which references telemetry without
importing telemetry.

Schema fidelity to FK-41 §41.3.1/§41.4.1 (Codex-r1 remediation 2026-06-01):
- Required fields: project_key, incident_id (FC-YYYY-NNNN), run_id, story_id,
  category, severity, phase, role, model, symptom, evidence (list[str]),
  recorded_at, incident_status.
- Optional: tags, impact, pattern_ref.
- ``evidence`` is a list of strings (FK-41 §41.4.1), not a dict.
- ``incident_id`` is assigned DB-side within the write transaction
  (``FC-YYYY-NNNN``, globally unique, gap-free per year); the triage therefore
  first produces an ``IncidentDraft`` without an id.
"""

from __future__ import annotations

import re
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

from agentkit.core_types import FailureCategory, IncidentStatus
from agentkit.failure_corpus.types import IncidentId, IncidentRole, IncidentSeverity

# FK-41 §41.3.1/§41.4.1: incident_id is ``FC-YYYY-NNNN`` (year 4 digits,
# sequence at least 4 digits). Codex-r2: enforce FAIL-CLOSED.
_INCIDENT_ID_PATTERN = re.compile(r"^FC-\d{4}-\d{4,}$")


def _validate_evidence_list(value: object) -> list[str]:
    """FAIL-CLOSED: evidence MUST be a list of strings (FK-41 §41.4.1).

    Otherwise Pydantic v2 would, depending on mode, silently wave a ``dict``
    through or coerce it unclearly. Codex-r2: make it explicitly hard — a
    dict/free JSON is a contract violation.
    """
    if not isinstance(value, list):
        raise ValueError(  # noqa: TRY004 — pydantic wraps ValueError into ValidationError
            f"evidence must be a list of strings (FK-41 §41.4.1), got {type(value)!r}"
        )
    if not all(isinstance(item, str) for item in value):
        raise ValueError("evidence items must all be strings (FK-41 §41.4.1)")
    return list(value)


def _validate_incident_id(value: str) -> str:
    """FAIL-CLOSED: incident_id MUST be ``FC-YYYY-NNNN`` (FK-41 §41.3.1)."""
    if _INCIDENT_ID_PATTERN.fullmatch(value) is None:
        raise ValueError(
            f"incident_id must match FC-YYYY-NNNN (FK-41 §41.3.1), got {value!r}"
        )
    return value


class IncidentCandidate(BaseModel):
    """Incoming incident candidate (input for ``record_incident``, FK-41 §41.4.1/§41.4.2).

    Frozen/extra-forbid: a candidate is an immutable input value; an unknown
    additional field is a contract violation (FAIL-CLOSED).

    Besides the FK-41 §41.4.1 persistence fields, the candidate carries the
    **gate inputs** for the admission criteria (FK-41 §41.4.3): ``merge_blocked``
    and ``rework_minutes``. These are NOT stored in ``fc_incidents`` — they only
    drive the ``IngressCriteria`` decision.

    Attributes:
        project_key: Project key (required; queries are always project-bound,
            FK-41 §41.3.1).
        story_id: Story anchor of the incident.
        run_id: Run anchor (required, FK-41 §41.3.1).
        category: Failure category (FK-41 §41.4.1, 12 values).
        severity: Incident severity (FK-41 §41.3.1, 4 levels).
        phase: Affected pipeline phase.
        role: Acting actor (worker | qa | governance, FK-41 §41.3.1).
        model: LLM model used.
        symptom: Free-text description of the error picture.
        evidence: List of evidence strings (FK-41 §41.4.1).
        tags: Optional keywords.
        impact: Optional impact description.
        merge_blocked: Gate input (FK-41 §41.4.3) — whether the finding blocked
            the merge. NOT persisted.
        rework_minutes: Gate input (FK-41 §41.4.3) — rework effort in minutes.
            NOT persisted.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    project_key: str
    story_id: str
    run_id: str
    category: FailureCategory
    severity: IncidentSeverity
    phase: str
    role: IncidentRole
    model: str
    symptom: str
    evidence: list[str] = Field(default_factory=list)
    tags: list[str] | None = None
    impact: str | None = None
    # Gate inputs (FK-41 §41.4.3) — not part of fc_incidents.
    merge_blocked: bool = False
    rework_minutes: int = 0

    @field_validator("evidence", mode="before")
    @classmethod
    def _check_evidence(cls, value: object) -> list[str]:
        return _validate_evidence_list(value)


class IncidentDraft(BaseModel):
    """Normalized, not-yet-persisted incident (before id allocation).

    Carries all FK-41 §41.3.1 persistence fields except ``incident_id`` (which is
    assigned DB-side within the write transaction as ``FC-YYYY-NNNN``) and
    ``recorded_at`` is set (normalization timestamp). The candidate's gate inputs
    (``merge_blocked``/``rework_minutes``) are deliberately NOT included here
    anymore — they are neither a persistence nor a read-model part.

    Frozen/extra-forbid.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    project_key: str
    story_id: str
    run_id: str
    category: FailureCategory
    severity: IncidentSeverity
    phase: str
    role: IncidentRole
    model: str
    symptom: str
    evidence: list[str] = Field(default_factory=list)
    recorded_at: datetime
    incident_status: IncidentStatus = IncidentStatus.OBSERVED
    tags: list[str] | None = None
    impact: str | None = None
    pattern_ref: str | None = None

    @field_validator("evidence", mode="before")
    @classmethod
    def _check_evidence(cls, value: object) -> list[str]:
        return _validate_evidence_list(value)


class Incident(BaseModel):
    """Persisted incident (FK-41 §41.3.1, fc_incidents row).

    Frozen/extra-forbid: an incident is append-only (exactly one record per
    ``incident_id``); after normalization it is no longer modified.

    Attributes:
        project_key: Project key (required, FK-41 §41.3.1).
        incident_id: Unique incident identity (PK, format ``FC-YYYY-NNNN``).
        run_id: Run anchor (required, FK-41 §41.3.1).
        story_id: Story anchor.
        category: Failure category.
        severity: Incident severity.
        phase: Affected pipeline phase.
        role: Acting actor (worker | qa | governance).
        model: LLM model used.
        symptom: Symptom description (normalized).
        evidence: List of evidence strings.
        recorded_at: Recording timestamp.
        incident_status: Lifecycle state (default ``OBSERVED``, FK-41 §41.3.1).
        tags: Optional keywords.
        impact: Optional impact description.
        pattern_ref: Optional reference to fc_patterns.pattern_id (after clustering).
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    project_key: str
    incident_id: IncidentId
    run_id: str
    story_id: str
    category: FailureCategory
    severity: IncidentSeverity
    phase: str
    role: IncidentRole
    model: str
    symptom: str
    evidence: list[str] = Field(default_factory=list)
    recorded_at: datetime
    incident_status: IncidentStatus = IncidentStatus.OBSERVED
    tags: list[str] | None = None
    impact: str | None = None
    pattern_ref: str | None = None

    @field_validator("incident_id", mode="before")
    @classmethod
    def _check_incident_id(cls, value: object) -> str:
        return _validate_incident_id(str(value))

    @field_validator("evidence", mode="before")
    @classmethod
    def _check_evidence(cls, value: object) -> list[str]:
        return _validate_evidence_list(value)


__all__ = [
    "Incident",
    "IncidentCandidate",
    "IncidentDraft",
]
