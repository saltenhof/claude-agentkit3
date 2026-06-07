"""Pydantic models for story data.

ClosurePayload and MultiRepoClosureState follow FK-29 §29.1.6.2 and
FK-39 §39.2.3.
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta
from enum import StrEnum
from pathlib import Path
from typing import Annotated, Any, Literal
from uuid import UUID, uuid4

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    Tag,
    ValidationInfo,
    field_validator,
    model_validator,
)

from agentkit.core_types import (
    ExplorationGateStatus,
    PauseReason,
    QaContext,
    SpawnRequest,
)
from agentkit.story_context_manager.sizing import StorySize, estimate_size
from agentkit.story_context_manager.story_model import WireStoryMode
from agentkit.story_context_manager.types import (
    ImplementationContract,
    StoryMode,
    StoryType,
    get_profile,
)

_STORY_ID_PATTERN = re.compile(r"^[A-Z][A-Z0-9]{1,9}-\d+$")
#: 64-char lowercase hex (SHA-256). Used by ``evidence_fingerprint`` validation.
_SHA256_HEX_PATTERN = re.compile(r"^[0-9a-f]{64}$")
#: 12-char lowercase hex — FK-27 §27.2.1 ``qa_cycle_id`` (UUID-Fragment).
_QA_CYCLE_ID_PATTERN = re.compile(r"^[0-9a-f]{12}$")


class PhaseStatus(StrEnum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    PAUSED = "paused"
    COMPLETED = "completed"
    FAILED = "failed"
    ESCALATED = "escalated"
    BLOCKED = "blocked"


class PhaseName(StrEnum):
    SETUP = "setup"
    EXPLORATION = "exploration"
    IMPLEMENTATION = "implementation"
    CLOSURE = "closure"


class QaCycleStatus(StrEnum):
    IDLE = "idle"
    AWAITING_QA = "awaiting_qa"
    AWAITING_POLICY = "awaiting_policy"
    AWAITING_REMEDIATION = "awaiting_remediation"
    PASS = "pass"
    ESCALATED = "escalated"


class SetupPayload(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    phase_type: Literal["setup"] = "setup"


class ExplorationPayload(BaseModel):
    """Phase-specific payload for the exploration phase (FK-23 §23.5.0).

    ``gate_status`` is the ONLY orchestration-contract field on this payload
    (FK-23 §23.5.0: "gate_status is the only orchestration-contract field").
    It is typed against :class:`ExplorationGateStatus` and defaults to
    ``PENDING`` (AG3-045 §2.1.6 / AC5): the gate has not been passed until a
    later, explicit transition to ``APPROVED``.

    Deliberately NOT carried here (FK-23 §23.5.0):

    * ``design_artifact_path`` / a ``change_frame_ref`` — the change-frame path
      is derivable from the story directory convention
      (``_temp/qa/{story_id}/change_frame.json``) and is not an
      orchestration-contract field. Under Option Y (PO 2026-06-05) the
      ``ExplorationPhaseHandler`` does NOT produce or APPROVE the change-frame:
      ``on_enter`` CONSUMES / VALIDATES a worker-produced change-frame (AG3-055)
      and then PAUSES awaiting the design review (or ESCALATES fail-closed when
      none is present); the gate stays ``PENDING``. The transition to
      ``APPROVED`` is owned by the three-stage design review (AG3-046), not by
      this handler and not via a field on this frozen, single-instance payload.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    phase_type: Literal["exploration"] = "exploration"
    gate_status: ExplorationGateStatus = ExplorationGateStatus.PENDING


class ImplementationPayload(BaseModel):
    """Payload for the Implementation phase.

    QA-Zyklus-Identitaeten (FK-27 §27.2.1) -- die vier Identitaetsfelder
    folgen wortgleich dem Konzept:

    - ``qa_cycle_id``: 12-Zeichen UUID-Fragment (lowercase hex). Wird
      bei jedem ``advance_qa_cycle()`` neu generiert. Wenn gesetzt,
      muss ``qa_cycle_round >= 1`` sein.
    - ``qa_cycle_round``: Monotoner Zaehler ab 1. Inkrementiert bei
      jedem neuen Zyklus. Default ``0`` markiert den Idle-State vor
      dem ersten Zyklus.
    - ``evidence_epoch``: ISO-8601-Timestamp (UTC, tz-aware) -- der
      Zeitpunkt der letzten Code-/Artefakt-Mutation. KEIN Counter; das
      ist ein Datum.
    - ``evidence_fingerprint``: SHA-256-Hash als 64-char Hex-String
      ueber die relevanten Artefakte (FK-27 §27.2.1 + Entscheidung
      2026-04-08 Element 19).

    Befuellung/Inkrementierung ist AG3-041 (THEME-009); diese Story
    stellt nur das Datenmodell bereit.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    phase_type: Literal["implementation"] = "implementation"
    qa_cycle_status: QaCycleStatus = QaCycleStatus.IDLE
    verify_context: QaContext | None = None
    qa_cycle_round: int = Field(default=0, ge=0)
    #: 12-char lowercase hex UUID-Fragment; validated below.
    qa_cycle_id: str | None = None
    #: ISO-8601-Timestamp (UTC, tz-aware) -- Zeitpunkt der letzten
    #: Artefakt-Mutation; ``None`` solange kein Zyklus gelaufen ist.
    evidence_epoch: datetime | None = None
    #: SHA-256 hex (64 lowercase hex chars); validated below.
    evidence_fingerprint: str | None = None

    @field_validator("qa_cycle_id")
    @classmethod
    def _validate_qa_cycle_id(cls, value: str | None) -> str | None:
        """FK-27 §27.2.1: qa_cycle_id ist ein 12-char lowercase hex UUID-Fragment."""
        if value is None:
            return value
        if not _QA_CYCLE_ID_PATTERN.fullmatch(value):
            msg = (
                "qa_cycle_id must be a 12-char lowercase hex UUID-fragment "
                f"(FK-27 §27.2.1); got {value!r}"
            )
            raise ValueError(msg)
        return value

    @field_validator("evidence_epoch")
    @classmethod
    def _validate_evidence_epoch(cls, value: datetime | None) -> datetime | None:
        """FK-27 §27.2.1: evidence_epoch ist ein UTC-aware ISO-8601 Timestamp.

        Pass-4 ERROR-7: lehnt auch nicht-UTC tz-aware datetimes (z.B. +02:00) ab,
        konsistent zu PhaseEnvelopeView._validate_evidence_epoch in
        verify_system/contract.py.
        """
        if value is None:
            return value
        if value.tzinfo is None:
            msg = (
                "evidence_epoch must be tz-aware (UTC); naive datetime not "
                f"allowed (FK-27 §27.2.1): {value!r}"
            )
            raise ValueError(msg)
        if value.utcoffset() != timedelta(0):
            msg = (
                "evidence_epoch must be UTC (offset=0); non-UTC tz-aware not "
                f"allowed (FK-27 §27.2.1): {value!r}"
            )
            raise ValueError(msg)
        return value

    @field_validator("evidence_fingerprint")
    @classmethod
    def _validate_evidence_fingerprint(cls, value: str | None) -> str | None:
        """FK-27 §27.2.1: evidence_fingerprint ist ein SHA-256 hex (64 lowercase)."""
        if value is None:
            return value
        if not _SHA256_HEX_PATTERN.fullmatch(value):
            msg = (
                "evidence_fingerprint must be a 64-char lowercase hex SHA-256 "
                f"digest (FK-27 §27.2.1); got {value!r}"
            )
            raise ValueError(msg)
        return value

    @model_validator(mode="after")
    def _validate_qa_cycle_round_when_id_set(self) -> ImplementationPayload:
        """FK-27 §27.2.1: wenn qa_cycle_id gesetzt, dann qa_cycle_round >= 1."""
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
        # FK-29 §29.1.0: EXACTLY six checkpoint booleans (29_closure_sequence.md
        # §29.1.0). The mode-lock release (FK-24 §24.3.3, AG3-018) is NOT a seventh
        # checkpoint — its idempotency is the durable per-story acquire marker
        # (FIX-4): the release reads the marker, releases once, and a resumed
        # closure with no marker owes nothing.
        ordered_checkpoints = (
            ("story_branch_pushed", self.story_branch_pushed, self.integrity_passed),
            ("merge_done", self.merge_done, self.story_branch_pushed),
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


class StoryContext(BaseModel):
    story_uuid: UUID = Field(default_factory=uuid4)
    project_key: str
    story_number: int = Field(default=0)  # derived from story_id by model_validator if not given
    story_id: str
    story_type: StoryType
    execution_route: StoryMode | None = None
    #: Fast/Standard mode (FK-24 §24.3.3) — a SEPARATE axis from
    #: ``execution_route`` (which is the intra-run path EXECUTION/EXPLORATION/
    #: None). ``fast`` (AG3-018) disables story-scoped guards and is only
    #: legal for code-producing stories (implementation/bugfix). Defaults to
    #: ``standard``. This is NOT conflated into ``execution_route``.
    mode: WireStoryMode = WireStoryMode.STANDARD
    implementation_contract: ImplementationContract | None = None
    issue_nr: int | None = None

    @field_validator("project_key")
    @classmethod
    def _validate_project_key_non_empty(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("project_key must not be empty")
        return value

    @field_validator("story_id")
    @classmethod
    def _validate_story_id_branch_safe(cls, v: str) -> str:
        if _STORY_ID_PATTERN.fullmatch(v) is None:
            raise ValueError(
                f"story_id {v!r} must match "
                r"^[A-Z][A-Z0-9]{1,9}-\d+$"
            )
        return v

    title: str = ""
    story_size: StorySize = StorySize.S
    project_root: Path | None = None
    worktree_path: Path | None = None
    worktree_map: dict[str, Path] = Field(default_factory=dict)
    participating_repos: list[str] = Field(default_factory=list)
    labels: list[str] = Field(default_factory=list)
    created_at: datetime | None = None

    @model_validator(mode="before")
    @classmethod
    def _normalize_contract_defaults(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data

        data = dict(data)
        if data.get("story_number") is None and isinstance(data.get("story_id"), str):
            data["story_number"] = _story_number_from_id(data["story_id"])

        story_type_raw = data.get("story_type")
        if story_type_raw is None:
            return data

        try:
            story_type = StoryType(story_type_raw)
        except ValueError:
            return data

        profile = get_profile(story_type)
        if (
            story_type is StoryType.IMPLEMENTATION
            and data.get("implementation_contract") is None
        ):
            data["implementation_contract"] = profile.default_implementation_contract
        if data.get("story_size") is None:
            labels = data.get("labels")
            title = data.get("title")
            data["story_size"] = estimate_size(
                list(labels) if isinstance(labels, list) else [],
                title if isinstance(title, str) else "",
            )
        return data

    @model_validator(mode="after")
    def _validate_contract_shape(self) -> StoryContext:
        if self.story_number < 1:
            raise ValueError(
                f"story_number must be >= 1, got {self.story_number!r}"
            )

        profile = get_profile(self.story_type)

        if self.execution_route not in profile.allowed_modes:
            raise ValueError(
                "execution_route "
                f"{self.execution_route!r} is not allowed for story_type "
                f"{self.story_type!r}",
            )

        if (
            self.mode is WireStoryMode.FAST
            and self.story_type
            not in (StoryType.IMPLEMENTATION, StoryType.BUGFIX)
        ):
            raise ValueError(
                "mode=fast (FK-24 §24.3.3/§24.3.4) is only allowed for "
                "code-producing story_types (implementation/bugfix); "
                f"got story_type {self.story_type!r}",
            )

        if (
            self.implementation_contract
            not in profile.allowed_implementation_contracts
        ):
            if (
                self.implementation_contract is None
                and not profile.allowed_implementation_contracts
            ):
                return self
            raise ValueError(
                "implementation_contract "
                f"{self.implementation_contract!r} is not allowed for story_type "
                f"{self.story_type!r}",
            )

        return self
    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        populate_by_name=True,
    )


class PhaseState(BaseModel):
    story_id: str
    phase: str
    status: PhaseStatus
    payload: PhasePayload | None = None
    memory: PhaseMemory = Field(default_factory=PhaseMemory)
    paused_reason: PauseReason | None = None
    review_round: int = 0
    errors: list[str] = Field(default_factory=list)
    attempt_id: str | None = None
    #: Engine-control spawn orders the orchestrator must execute on phase
    #: re-entry (FK-20 §20.5.1 / FK-45 §45.3). The Implementation phase handler
    #: sets this to ``[remediation_worker]`` on a subflow FAIL below the round
    #: ceiling; the AdversarialSpawner sets ``[adversarial ...]`` for Layer-3
    #: mandatory targets. Empty when no spawn is pending. This is the SINGLE
    #: typed truth for the spawn order — no untyped second channel.
    agents_to_spawn: list[SpawnRequest] = Field(default_factory=list)

    @field_validator("phase")
    @classmethod
    def _validate_phase_name(cls, value: str) -> str:
        if value == "verify":
            raise ValueError("verify is not a top-level phase")
        try:
            PhaseName(value)
        except ValueError as exc:
            raise ValueError(
                "phase must be one of setup, exploration, implementation, closure",
            ) from exc
        return value

    @field_validator("payload")
    @classmethod
    def _validate_payload_matches_phase(
        cls,
        value: PhasePayload | None,
        info: ValidationInfo,
    ) -> PhasePayload | None:
        phase = info.data.get("phase")
        if value is not None and phase is not None and value.phase_type != phase:
            raise ValueError("payload.phase_type must match phase")
        return value

    model_config = ConfigDict(extra="forbid")


class PhaseSnapshot(BaseModel):
    story_id: str
    phase: str
    status: PhaseStatus
    completed_at: datetime
    artifacts: list[str] = Field(default_factory=list)
    evidence: dict[str, Any] = Field(default_factory=dict)

    @field_validator("phase")
    @classmethod
    def _validate_phase_name(cls, value: str) -> str:
        if value == "verify":
            raise ValueError("verify is not a top-level phase")
        try:
            PhaseName(value)
        except ValueError as exc:
            raise ValueError(
                "phase must be one of setup, exploration, implementation, closure",
            ) from exc
        return value

    model_config = ConfigDict(extra="forbid", frozen=True)

__all__ = [
    "ClosurePayload",
    "ClosureProgress",
    "ExplorationPayload",
    "ExplorationPhaseMemory",
    "ImplementationPayload",
    "ImplementationPhaseMemory",
    "MultiRepoClosureState",
    "PhaseMemory",
    "PhaseName",
    "PhasePayload",
    "PhaseSnapshot",
    "PhaseState",
    "PhaseStatus",
    "QaCycleStatus",
    "SetupPayload",
    "StoryContext",
]


def _story_number_from_id(story_id: str) -> int | None:
    suffix = story_id.rsplit("-", maxsplit=1)[-1]
    if not suffix.isdigit():
        return None
    return int(suffix)


def _participating_repos_from_context(info: ValidationInfo) -> list[str] | None:
    context = info.context
    if not isinstance(context, dict):
        return None
    raw_repos = context.get("participating_repos")
    if not isinstance(raw_repos, list):
        return None
    return [repo for repo in raw_repos if isinstance(repo, str)]
