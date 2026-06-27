"""Phase-state models owned by the phase executor (FK-39)."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum
from typing import Annotated, Any, Literal
from uuid import UUID

from pydantic import (
    AliasChoices,
    BaseModel,
    ConfigDict,
    Field,
    Tag,
    ValidationInfo,
    field_validator,
    model_validator,
)

from agentkit.backend.core_types import (
    ExplorationGateStatus,
    PauseReason,
    QaContext,
    SpawnRequest,
    StoryMode,
)
from agentkit.backend.story_context_manager.types import StoryType

PHASE_STATE_SCHEMA_VERSION: Literal["4.0"] = "4.0"

_SHA256_HEX_PATTERN = re.compile(r"^[0-9a-f]{64}$")
_QA_CYCLE_ID_PATTERN = re.compile(r"^[0-9a-f]{12}$")


class PhaseStatus(StrEnum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    PAUSED = "paused"
    COMPLETED = "completed"
    FAILED = "failed"
    ESCALATED = "escalated"


class PhaseName(StrEnum):
    SETUP = "setup"
    EXPLORATION = "exploration"
    IMPLEMENTATION = "implementation"
    CLOSURE = "closure"


class PhaseStateMode(StrEnum):
    EXECUTION = StoryMode.EXECUTION.value
    EXPLORATION = StoryMode.EXPLORATION.value
    FAST = "fast"


class EscalationReason(StrEnum):
    WORKER_BLOCKED = "worker_blocked"
    MAX_ROUNDS_EXCEEDED = "max_rounds_exceeded"
    IMPLEMENTATION_REQUIRED_AFTER_EXPLORATION = (
        "implementation_required_after_exploration"
    )
    PREFLIGHT_FAIL = "preflight_fail"
    INTEGRITY_FAIL = "integrity_fail"
    MERGE_FAIL = "merge_fail"
    DOC_FIDELITY_FAIL = "doc_fidelity_fail"
    IMPACT_VIOLATION = "impact_violation"
    DESIGN_REVIEW_REJECTED = "design_review_rejected"
    GOVERNANCE_VIOLATION = "governance_violation"
    #: AG3-086 (FK-42 §42.4.2 step 5 / FK-55 §55.9a): a CCAG permission request's
    #: TTL elapsed without a human decision -> the run is deterministically
    #: ESCALATED.
    PERMISSION_REQUEST_EXPIRED = "permission_request_expired"


class PhaseStateProducer(BaseModel):
    """Typed writer identity for the durable phase-state projection."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    type: str
    name: str

    @field_validator("type", "name")
    @classmethod
    def _not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("producer fields must not be blank")
        return value


class QaCycleStatus(StrEnum):
    IDLE = "idle"
    AWAITING_QA = "awaiting_qa"
    AWAITING_POLICY = "awaiting_policy"
    AWAITING_REMEDIATION = "awaiting_remediation"
    PASS = "pass"
    ESCALATED = "escalated"


class AreBundleStatus(StrEnum):
    """Setup ARE bundle load status (FK-22 §22.4b)."""

    LOADED = "LOADED"
    SKIPPED = "SKIPPED"
    FAILED = "FAILED"


class AreBundleSignal(BaseModel):
    """Typed Setup payload signal for the ARE bundle step."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    status: AreBundleStatus
    requirement_count: int = Field(ge=0)


class SetupPayload(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    phase_type: Literal["setup"] = "setup"
    are_bundle: AreBundleSignal | None = None


class ExplorationPayload(BaseModel):
    """Phase-specific payload for the exploration phase (FK-23 §23.5.0)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    phase_type: Literal["exploration"] = "exploration"
    gate_status: ExplorationGateStatus = ExplorationGateStatus.PENDING


class ImplementationPayload(BaseModel):
    """Payload for the Implementation phase."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    phase_type: Literal["implementation"] = "implementation"
    qa_cycle_status: QaCycleStatus = QaCycleStatus.IDLE
    verify_context: QaContext | None = None
    qa_cycle_round: int = Field(default=0, ge=0)
    qa_cycle_id: str | None = None
    evidence_epoch: datetime | None = None
    evidence_fingerprint: str | None = None

    @field_validator("qa_cycle_id")
    @classmethod
    def _validate_qa_cycle_id(cls, value: str | None) -> str | None:
        if value is None:
            return value
        if not _QA_CYCLE_ID_PATTERN.fullmatch(value):
            raise ValueError(
                "qa_cycle_id must be a 12-char lowercase hex UUID-fragment "
                f"(FK-27 §27.2.1); got {value!r}"
            )
        return value

    @field_validator("evidence_epoch")
    @classmethod
    def _validate_evidence_epoch(cls, value: datetime | None) -> datetime | None:
        if value is None:
            return value
        return _validate_utc_datetime(value, field_name="evidence_epoch")

    @field_validator("evidence_fingerprint")
    @classmethod
    def _validate_evidence_fingerprint(cls, value: str | None) -> str | None:
        if value is None:
            return value
        if not _SHA256_HEX_PATTERN.fullmatch(value):
            raise ValueError(
                "evidence_fingerprint must be a 64-char lowercase hex SHA-256 "
                f"digest (FK-27 §27.2.1); got {value!r}"
            )
        return value

    @model_validator(mode="after")
    def _validate_qa_cycle_round_when_id_set(self) -> ImplementationPayload:
        if self.qa_cycle_id is not None and self.qa_cycle_round < 1:
            raise ValueError(
                "qa_cycle_round must be >= 1 when qa_cycle_id is set; "
                f"got qa_cycle_round={self.qa_cycle_round!r} with "
                f"qa_cycle_id={self.qa_cycle_id!r}"
            )
        return self


class ClosureProgress(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    integrity_passed: bool = False
    story_branch_pushed: bool = False
    merge_done: bool = False
    story_closed: bool = False
    metrics_written: bool = False
    postflight_done: bool = False

    @model_validator(mode="after")
    def _validate_checkpoint_order(self) -> ClosureProgress:
        ordered_checkpoints = (
            ("integrity_passed", self.integrity_passed, self.story_branch_pushed),
            ("merge_done", self.merge_done, self.integrity_passed),
            ("story_closed", self.story_closed, self.merge_done),
            ("metrics_written", self.metrics_written, self.story_closed),
            ("postflight_done", self.postflight_done, self.metrics_written),
        )
        for field_name, current, previous in ordered_checkpoints:
            if current and not previous:
                raise ValueError(
                    f"{field_name} cannot be true before the previous "
                    "closure checkpoint",
                )
        return self


class MultiRepoClosureState(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    pre_merge_check_passed: list[str] = Field(default_factory=list)
    pushed_repos: list[str] = Field(default_factory=list)
    merged_repos: list[str] = Field(default_factory=list)
    rolled_back_repos: list[str] = Field(default_factory=list)
    failed_repo: str | None = None


class ClosurePayload(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    phase_type: Literal["closure"] = "closure"
    progress: ClosureProgress = Field(default_factory=ClosureProgress)
    multi_repo: MultiRepoClosureState | None = None

    @model_validator(mode="after")
    def _validate_multi_repo_context(
        self,
        info: ValidationInfo,
    ) -> ClosurePayload:
        participating_repos = _participating_repos_from_context(info)
        if (
            participating_repos is not None
            and len(participating_repos) >= 2
            and self.multi_repo is None
        ):
            raise ValueError(
                "multi_repo is required for stories with multiple "
                "participating_repos",
            )
        return self


PhasePayload = (
    Annotated[SetupPayload, Tag("setup")]
    | Annotated[ExplorationPayload, Tag("exploration")]
    | Annotated[ImplementationPayload, Tag("implementation")]
    | Annotated[ClosurePayload, Tag("closure")]
)


class ExplorationPhaseMemory(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    review_rounds: int = Field(default=0, ge=0)


class ImplementationPhaseMemory(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    qa_feedback_rounds: int = Field(default=0, ge=0)


class PhaseMemory(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    exploration: ExplorationPhaseMemory = Field(
        default_factory=ExplorationPhaseMemory,
    )
    implementation: ImplementationPhaseMemory = Field(
        default_factory=ImplementationPhaseMemory,
    )


class PhaseState(BaseModel):
    """Durable FK-39 phase state: PhaseStateCore plus payload and memory."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    schema_version: Literal["4.0"]
    story_id: str
    run_id: str
    phase: PhaseName
    status: PhaseStatus
    mode: PhaseStateMode
    story_type: StoryType
    attempt: int = Field(ge=1)
    started_at: datetime
    phase_entered_at: datetime
    pause_reason: PauseReason | None = Field(
        validation_alias=AliasChoices("pause_reason", "paused_reason"),
        serialization_alias="pause_reason",
    )
    escalation_reason: EscalationReason | None
    payload: PhasePayload | None = None
    memory: PhaseMemory = Field(default_factory=PhaseMemory)
    review_round: int = 0
    errors: list[str] = Field(default_factory=list)
    warnings: list[str]
    producer: PhaseStateProducer
    attempt_id: str | None = None
    agents_to_spawn: list[SpawnRequest] = Field(default_factory=list)

    @field_validator("schema_version")
    @classmethod
    def _validate_schema_version(cls, value: Literal["4.0"]) -> Literal["4.0"]:
        if value != PHASE_STATE_SCHEMA_VERSION:
            raise ValueError("schema_version must be '4.0'")
        return value

    @field_validator("run_id")
    @classmethod
    def _validate_run_id_uuid(cls, value: str) -> str:
        try:
            UUID(value)
        except ValueError as exc:
            raise ValueError("run_id must be a UUID string") from exc
        return value

    @field_validator("started_at", "phase_entered_at")
    @classmethod
    def _validate_timestamps_utc(cls, value: datetime) -> datetime:
        return _validate_utc_datetime(value, field_name="timestamp")

    @field_validator("payload")
    @classmethod
    def _validate_payload_matches_phase(
        cls,
        value: PhasePayload | None,
        info: ValidationInfo,
    ) -> PhasePayload | None:
        phase = info.data.get("phase")
        if value is not None and phase is not None and value.phase_type != phase.value:
            raise ValueError("payload.phase_type must match phase")
        return value

    @model_validator(mode="after")
    def _validate_reason_consistency(self) -> PhaseState:
        if self.pause_reason is not None and self.status is not PhaseStatus.PAUSED:
            raise ValueError("pause_reason may only be set when status is PAUSED")
        if (
            self.escalation_reason is not None
            and self.status is not PhaseStatus.ESCALATED
        ):
            raise ValueError(
                "escalation_reason may only be set when status is ESCALATED"
            )
        return self


class PhaseSnapshot(BaseModel):
    story_id: str
    phase: PhaseName
    status: PhaseStatus
    completed_at: datetime
    artifacts: list[str] = Field(default_factory=list)
    evidence: dict[str, Any] = Field(default_factory=dict)

    model_config = ConfigDict(extra="forbid", frozen=True)


def phase_state_mode_from_context(
    *,
    execution_route: StoryMode | None,
    fast: bool,
) -> PhaseStateMode:
    """Resolve FK-39 ``mode`` from execution_route plus fast special case."""

    if fast:
        return PhaseStateMode.FAST
    if execution_route is None:
        return PhaseStateMode.EXECUTION
    return PhaseStateMode(execution_route.value)


@dataclass(frozen=True)
class PhaseStateSpec:
    """Complete specification for constructing a :class:`PhaseState`.

    Groups all required and optional fields into a single typed object so
    that :func:`build_phase_state_from_spec` stays below the S107
    parameter-count threshold.  Pass this spec to
    :func:`build_phase_state_from_spec` for construction.
    """

    story_id: str
    run_id: str
    phase: str | PhaseName
    status: PhaseStatus
    mode: PhaseStateMode
    story_type: StoryType
    attempt: int
    started_at: datetime
    phase_entered_at: datetime
    producer: PhaseStateProducer | dict[str, str]
    pause_reason: PauseReason | None = None
    escalation_reason: EscalationReason | None = None
    payload: PhasePayload | None = None
    memory: PhaseMemory | None = None
    review_round: int = 0
    errors: list[str] | None = None
    warnings: list[str] | None = None
    attempt_id: str | None = None
    agents_to_spawn: list[SpawnRequest] | None = None


def build_phase_state_from_spec(spec: PhaseStateSpec) -> PhaseState:
    """Construct a complete PhaseState from a :class:`PhaseStateSpec`.

    Single-argument entry point that satisfies S107.  Callers should construct
    a :class:`PhaseStateSpec` and pass it here.
    """
    return PhaseState(
        schema_version=PHASE_STATE_SCHEMA_VERSION,
        story_id=spec.story_id,
        run_id=spec.run_id,
        phase=spec.phase,
        status=spec.status,
        mode=spec.mode,
        story_type=spec.story_type,
        attempt=spec.attempt,
        started_at=spec.started_at,
        phase_entered_at=spec.phase_entered_at,
        pause_reason=spec.pause_reason,
        escalation_reason=spec.escalation_reason,
        payload=spec.payload,
        memory=spec.memory or PhaseMemory(),
        review_round=spec.review_round,
        errors=spec.errors or [],
        warnings=spec.warnings or [],
        producer=spec.producer,
        attempt_id=spec.attempt_id,
        agents_to_spawn=spec.agents_to_spawn or [],
    )



def evolve_phase_state(state: PhaseState, **updates: object) -> PhaseState:
    """Return a validated state copy while preserving FK-39 core fields."""

    data = state.model_dump(mode="python", by_alias=False)
    data.update(updates)
    return PhaseState.model_validate(data)


def _validate_utc_datetime(value: datetime, *, field_name: str) -> datetime:
    if value.tzinfo is None:
        raise ValueError(f"{field_name} must be tz-aware UTC; naive datetime rejected")
    if value.utcoffset() != timedelta(0):
        raise ValueError(f"{field_name} must be UTC (offset=0)")
    return value


def _participating_repos_from_context(info: ValidationInfo) -> list[str] | None:
    context = info.context
    if not isinstance(context, dict):
        return None
    participating_repos = context.get("participating_repos")
    if participating_repos is None:
        return None
    if not isinstance(participating_repos, list):
        return None
    return [str(repo) for repo in participating_repos]


__all__ = [
    "AreBundleSignal",
    "AreBundleStatus",
    "ClosurePayload",
    "ClosureProgress",
    "EscalationReason",
    "ExplorationPayload",
    "ExplorationPhaseMemory",
    "ImplementationPayload",
    "ImplementationPhaseMemory",
    "MultiRepoClosureState",
    "PHASE_STATE_SCHEMA_VERSION",
    "PhaseMemory",
    "PhaseName",
    "PhasePayload",
    "PhaseSnapshot",
    "PhaseState",
    "PhaseStateMode",
    "PhaseStateProducer",
    "PhaseStatus",
    "QaCycleStatus",
    "SetupPayload",
    "PhaseStateSpec",
    "build_phase_state_from_spec",
    "evolve_phase_state",
    "phase_state_mode_from_context",
]
