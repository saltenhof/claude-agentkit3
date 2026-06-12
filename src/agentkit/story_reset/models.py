"""Typed Story-Reset artifact models (FK-53 §53.5/§53.7/§53.9, AG3-071).

These are the durable, auditable carriers of the administrative Story-Reset:

* :class:`ResetStatus` — the minimal §53.5 record status (``started`` /
  ``completed`` / ``failed``).
* :class:`ResetPurgeDomain` — the typed reset purge domains (no string/flag
  geflecht; TYPISIERT STATT STRINGS). Schritt 5 (runtime) and Schritt 6
  (read-models/analytics) are SEPARATE domains with separate owners.
* :class:`StoryResetRecord` — the minimal §53.5 reset record / idempotency +
  resume anchor (modelled on the ``ControlPlaneOperationRecord`` claim pattern,
  no second hidden claim).
* :class:`StoryResetRequest` / :class:`StoryResetResult` — the service IO.
* :class:`PlannedPurge` — the ``--dry-run`` plan (no destructive mutation).
* :class:`ResetCleanStateReport` — the §53.8 end-state verification evidence.

All identifiers / enum values / wire keys are English (ARCH-55); the reset axis
deliberately emits NO ``Cancelled`` (FK-53 §53.6/§53.8 keeps the story alive).
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

#: Producer id of the Story-Reset BC (audit attribution, ARCH-55 English).
STORY_RESET_PRODUCER_ID: Literal["story_reset_service"] = "story_reset_service"


class ResetStatus(StrEnum):
    """The minimal FK-53 §53.5 reset-record status set.

    ``STARTED`` is the audit + idempotency + resume anchor written before any
    deletion (§53.7.1). ``COMPLETED`` is set only after all purge domains, the
    end-state verification and the lock release succeeded (§53.9.3). ``FAILED``
    marks an aborted, resumable reset (§53.9.2 — the story stays administratively
    blocked / not runnable).
    """

    STARTED = "started"
    COMPLETED = "completed"
    FAILED = "failed"


class ResetPurgeDomain(StrEnum):
    """The typed reset purge domains in fixed §53.7 flow order.

    Schritt 5 (``RUNTIME_EXECUTION`` + ``LOCKS_LEASES``) and Schritt 6
    (``READ_MODELS`` + ``ANALYTICS``) are SEPARATE domains with SEPARATE owners
    and must not be conflated (FIX-THE-MODEL): the runtime owner is the
    ``RuntimeExecutionPurgePort`` / governance lock owner, the read-model/analytics
    owner is the FK-69 ``ProjectionAccessor`` / AG3-082 analytics worker.
    """

    RUNTIME_EXECUTION = "runtime_execution"
    LOCKS_LEASES = "locks_leases"
    READ_MODELS = "read_models"
    ANALYTICS = "analytics"
    WORKSPACE = "workspace"
    WORKTREE = "worktree"


class StoryResetRequest(BaseModel):
    """Human-CLI request for an administrative Story-Reset (§53.3/§53.5).

    The ``reset_id`` is the idempotency / resume anchor: the same ``reset_id`` is
    a resume of the SAME reset, never a new one (§53.9.1). When omitted on the
    first ``request_reset`` it is minted by the service.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    project_key: str
    story_id: str
    requested_by: str
    reason: str
    escalation_ref: str | None = None
    reset_id: str | None = None
    dry_run: bool = False
    force: bool = False

    @field_validator("reason")
    @classmethod
    def _reason_not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("reset reason must not be empty (FK-53 §53.3)")
        return value

    @field_validator("project_key", "story_id", "requested_by")
    @classmethod
    def _required_not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("reset request requires non-empty scope identifiers")
        return value


class StoryResetRecord(BaseModel):
    """The minimal FK-53 §53.5 durable reset record (audit + resume anchor).

    Carries exactly the §53.5 fields plus the typed lifecycle ``status`` and a
    coarse ``purge_summary`` (§53.7.4: a small, durable proof — NOT a hidden
    shadow copy of the runtime state). It is modelled on the
    ``ControlPlaneOperationRecord`` idempotency pattern (the reset is fenced via a
    ``ControlPlaneOperationRecord`` of ``operation_kind='story_reset'`` keyed on
    ``reset_id``; this record is the human-readable audit twin, not a second
    operative claim).
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    producer_id: Literal["story_reset_service"] = STORY_RESET_PRODUCER_ID
    reset_id: str
    project_key: str
    story_id: str
    requested_by: str
    reason: str
    escalation_ref: str | None = None
    requested_at: datetime
    status: ResetStatus = ResetStatus.STARTED
    #: Coarse per-domain purge summary (§53.7.4), e.g. ``{"runtime_execution": 12}``.
    purge_summary: dict[str, int] = Field(default_factory=dict)
    completed_at: datetime | None = None
    failure_reason: str | None = None

    @field_validator("reason")
    @classmethod
    def _reason_not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("reset reason must not be empty (FK-53 §53.5)")
        return value


class PlannedPurge(BaseModel):
    """The ``--dry-run`` plan: which purge domains WOULD run (no mutation, §53.3).

    A dry run performs NO destructive mutation and writes NO reset record; it only
    reports the planned domains and the resolved run scope so an operator can
    review the blast radius before committing.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    project_key: str
    story_id: str
    run_id: str | None
    reason: str
    planned_domains: tuple[ResetPurgeDomain, ...]


class ResetCleanStateReport(BaseModel):
    """FK-53 §53.8 end-state verification evidence for ``verify_reset_clean_state``.

    ``is_clean`` is fail-closed: it is ``True`` only when every dimension confirms
    a clean restartable base — no runtime residue, no active locks/leases, no
    read-model/analytics residue, no tainted worktree, the reset proof exists and
    the story survived as a live (restartable, non-Cancelled) work unit.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    reset_id: str
    project_key: str
    story_id: str
    run_id: str | None
    runtime_residue_clean: bool
    locks_released: bool
    read_models_clean: bool
    analytics_clean: bool
    worktree_clean: bool
    reset_proof_present: bool
    story_preserved_restartable: bool
    residue_detail: dict[str, int] = Field(default_factory=dict)

    @property
    def is_clean(self) -> bool:
        """Whether ALL end-state dimensions confirm a clean restartable base."""

        return (
            self.runtime_residue_clean
            and self.locks_released
            and self.read_models_clean
            and self.analytics_clean
            and self.worktree_clean
            and self.reset_proof_present
            and self.story_preserved_restartable
        )

    def blocking_dimensions(self) -> tuple[str, ...]:
        """Return the names of the end-state dimensions that are NOT clean."""

        blocked: list[str] = []
        if not self.runtime_residue_clean:
            blocked.append("runtime_residue_clean")
        if not self.locks_released:
            blocked.append("locks_released")
        if not self.read_models_clean:
            blocked.append("read_models_clean")
        if not self.analytics_clean:
            blocked.append("analytics_clean")
        if not self.worktree_clean:
            blocked.append("worktree_clean")
        if not self.reset_proof_present:
            blocked.append("reset_proof_present")
        if not self.story_preserved_restartable:
            blocked.append("story_preserved_restartable")
        return tuple(blocked)


class StoryResetResult(BaseModel):
    """Successful (or resumed) Story-Reset result (§53.8/§53.10)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    reset_id: str
    record: StoryResetRecord
    clean_state: ResetCleanStateReport
    resumed: bool


__all__ = [
    "STORY_RESET_PRODUCER_ID",
    "PlannedPurge",
    "ResetCleanStateReport",
    "ResetPurgeDomain",
    "ResetStatus",
    "StoryResetRecord",
    "StoryResetRequest",
    "StoryResetResult",
]
