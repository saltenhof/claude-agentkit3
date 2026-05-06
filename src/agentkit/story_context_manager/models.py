"""Pydantic models for story data.

ClosurePayload and MultiRepoClosureState follow FK-29 §29.1.6.2 and
FK-39 §39.2.3.
"""

from __future__ import annotations

import re
from datetime import datetime
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

from agentkit.story_context_manager.sizing import StorySize, estimate_size
from agentkit.story_context_manager.types import (
    ImplementationContract,
    StoryMode,
    StoryType,
    get_profile,
)

_STORY_ID_PATTERN = re.compile(r"^[A-Z][A-Z0-9]{1,9}-\d+$")


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


class VerifyContext(StrEnum):
    POST_IMPLEMENTATION = "POST_IMPLEMENTATION"
    POST_REMEDIATION = "POST_REMEDIATION"


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
    model_config = ConfigDict(extra="forbid", frozen=True)

    phase_type: Literal["exploration"] = "exploration"
    gate_status: str | None = None


class ImplementationPayload(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    phase_type: Literal["implementation"] = "implementation"
    qa_cycle_status: QaCycleStatus = QaCycleStatus.IDLE
    verify_context: VerifyContext | None = None
    qa_cycle_round: int = Field(default=0, ge=0)
    qa_cycle_id: str | None = None
    evidence_epoch: str | None = None
    evidence_fingerprint: str | None = None


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
    story_number: int = Field(ge=1)
    story_id: str
    story_type: StoryType
    execution_route: StoryMode
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
    story_size: StorySize = StorySize.SMALL
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
        profile = get_profile(self.story_type)

        if self.execution_route not in profile.allowed_modes:
            raise ValueError(
                "execution_route "
                f"{self.execution_route!r} is not allowed for story_type "
                f"{self.story_type!r}",
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
    paused_reason: str | None = None
    review_round: int = 0
    errors: list[str] = Field(default_factory=list)
    attempt_id: str | None = None

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
    "VerifyContext",
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
