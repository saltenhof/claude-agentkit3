"""Typed verify-evidence edge collection contract (AG3-156)."""

from __future__ import annotations

import hashlib
from datetime import datetime, timedelta
from enum import StrEnum
from pathlib import PurePosixPath, PureWindowsPath
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

VERIFY_EVIDENCE_SCHEMA_VERSION: Literal["1.0"] = "1.0"
VERIFY_EVIDENCE_RESULT_TYPE: Literal["verify_evidence_report"] = (
    "verify_evidence_report"
)
MAX_EVIDENCE_FILE_BYTES = 350 * 1024
MAX_EVIDENCE_RESULT_BYTES = 2 * 1024 * 1024
SHA256_PATTERN = r"^[0-9a-f]{64}$"


class VerifyEvidenceStage(StrEnum):
    """The two frozen verify-evidence wait-point stages."""

    BASE_COLLECTION = "base_collection"
    DYNAMIC_REQUESTS = "dynamic_requests"


class VerifyEvidenceObservationStatus(StrEnum):
    """Named edge collection outcomes; final D3 stays backend-owned."""

    COLLECTED = "COLLECTED"
    UNRESOLVED = "UNRESOLVED"
    TIMEOUT = "TIMEOUT"
    REJECTED = "REJECTED"


class VerifyTestCommand(BaseModel):
    """Whitelisted test execution form transported argument-wise."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    runner: Literal["pytest"] = "pytest"
    arguments: tuple[str, ...] = Field(default=(), max_length=32)
    timeout_seconds: int = Field(default=30, ge=1, le=120)

    @field_validator("arguments")
    @classmethod
    def _arguments_are_whitelisted(
        cls, arguments: tuple[str, ...]
    ) -> tuple[str, ...]:
        expect_value = False
        for argument in arguments:
            expect_value = _validate_test_argument(argument, expect_value)
        if expect_value:
            raise ValueError("pytest option value is missing")
        return arguments


class VerifyEvidenceRequest(BaseModel):
    """Canonical reviewer request carried to the Project Edge."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    request_index: int = Field(ge=0, le=7)
    request_type: Literal[
        "NEED_FILE",
        "NEED_SCHEMA",
        "NEED_CALLSITE",
        "NEED_RUNTIME_BINDING",
        "NEED_TEST_EVIDENCE",
    ]
    target: str = Field(min_length=1, max_length=1024)
    region: str | None = Field(default=None, max_length=512)
    test_command: VerifyTestCommand | None = None

    @model_validator(mode="after")
    def _test_command_matches_type(self) -> VerifyEvidenceRequest:
        is_test = self.request_type == "NEED_TEST_EVIDENCE"
        if is_test != (self.test_command is not None):
            raise ValueError(
                "test_command is required only for NEED_TEST_EVIDENCE"
            )
        return self


class VerifyEvidenceCanonicalRequest(BaseModel):
    """One canonical checkpointed reviewer request, including local kinds."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    request_type: Literal[
        "NEED_FILE",
        "NEED_SCHEMA",
        "NEED_CALLSITE",
        "NEED_RUNTIME_BINDING",
        "NEED_TEST_EVIDENCE",
        "NEED_CONCEPT_SOURCE",
        "NEED_DIFF_EXPANSION",
    ]
    target: str = Field(min_length=1, max_length=1024)
    region: str | None = Field(default=None, max_length=512)
    reason: str = Field(min_length=1, max_length=4096)


class VerifyEvidenceRepository(BaseModel):
    """One repository's edge collection inputs without a physical path."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    repo_id: str = Field(min_length=1)
    affected: bool = True
    change_evidence_available: bool = True
    changed_paths: tuple[str, ...] = ()
    expected_head_sha: str = Field(min_length=1)

    @field_validator("changed_paths")
    @classmethod
    def _relative_paths_only(cls, paths: tuple[str, ...]) -> tuple[str, ...]:
        return tuple(_validated_relative_path(path) for path in paths)

    @field_validator("repo_id")
    @classmethod
    def _repo_id_is_not_reserved(cls, repo_id: str) -> str:
        if repo_id.startswith("_"):
            raise ValueError("verify-evidence repository ids cannot use reserved namespaces")
        return repo_id


class VerifyEvidenceFile(BaseModel):
    """One bounded file observation returned by the Project Edge."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    repo_id: str = Field(min_length=1)
    path: str = Field(min_length=1)
    content: str = Field(max_length=MAX_EVIDENCE_FILE_BYTES)
    size: int = Field(ge=0, le=MAX_EVIDENCE_FILE_BYTES)
    sha256: str = Field(pattern=SHA256_PATTERN)

    @field_validator("path")
    @classmethod
    def _path_is_relative(cls, path: str) -> str:
        return _validated_relative_path(path)

    @model_validator(mode="after")
    def _content_binding_matches(self) -> VerifyEvidenceFile:
        encoded = self.content.encode("utf-8")
        if len(encoded) != self.size:
            raise ValueError("verify-evidence file size does not match content")
        if hashlib.sha256(encoded).hexdigest() != self.sha256:
            raise ValueError("verify-evidence file sha256 does not match content")
        return self

    @classmethod
    def from_content(
        cls, *, repo_id: str, path: str, content: str
    ) -> VerifyEvidenceFile:
        """Build a content-bound file observation."""
        encoded = content.encode("utf-8")
        return cls(
            repo_id=repo_id,
            path=path,
            content=content,
            size=len(encoded),
            sha256=hashlib.sha256(encoded).hexdigest(),
        )


class VerifyEvidenceObservation(BaseModel):
    """Edge observations for one request; never the backend D3 decision."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    request_index: int = Field(ge=0, le=7)
    status: VerifyEvidenceObservationStatus
    candidates: tuple[VerifyEvidenceFile, ...] = ()
    content: str | None = Field(
        default=None, min_length=1, max_length=MAX_EVIDENCE_FILE_BYTES
    )
    finding_code: str | None = Field(default=None, max_length=128)
    duration_ms: int = Field(default=0, ge=0)

    @model_validator(mode="after")
    def _content_is_byte_bounded(self) -> VerifyEvidenceObservation:
        if (
            self.content is not None
            and len(self.content.encode("utf-8")) > MAX_EVIDENCE_FILE_BYTES
        ):
            raise ValueError("verify-evidence observation content exceeds the byte limit")
        if (
            self.status is VerifyEvidenceObservationStatus.COLLECTED
            and self.content is None
            and not self.candidates
        ):
            raise ValueError("a collected observation requires content or candidates")
        return self


class CollectVerifyEvidenceCommandPayload(BaseModel):
    """Two-stage batch payload for ``collect_verify_evidence``."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["1.0"] = VERIFY_EVIDENCE_SCHEMA_VERSION
    stage: VerifyEvidenceStage
    story_id: str = Field(min_length=1)
    project_key: str = Field(min_length=1)
    run_id: str = Field(min_length=1)
    implementation_attempt: int = Field(ge=1)
    batch_id: str = Field(pattern=SHA256_PATTERN)
    generation: str = Field(pattern=SHA256_PATTERN)
    candidate_digest: str = Field(pattern=SHA256_PATTERN)
    request_digest: str = Field(pattern=SHA256_PATTERN)
    preflight_template_version: int = Field(ge=1)
    deadline_at: datetime
    repositories: tuple[VerifyEvidenceRepository, ...] = Field(min_length=1)
    spawn_worktree_repo: str = Field(min_length=1)
    worker_hint_paths: tuple[str, ...] = ()
    requests: tuple[VerifyEvidenceRequest, ...] = Field(max_length=8, default=())
    preflight_requests: tuple[VerifyEvidenceCanonicalRequest, ...] = Field(
        max_length=8, default=()
    )
    preflight_attempt_id: str | None = Field(default=None, max_length=256)
    preflight_checkpoint_state: Literal["started", "ready"] | None = None
    preflight_request_hash: str | None = Field(
        default=None, pattern=SHA256_PATTERN
    )
    raw_preflight_response: str | None = Field(default=None, max_length=262_144)
    base_manifest: dict[str, object] | None = None

    @field_validator("deadline_at")
    @classmethod
    def _deadline_is_utc(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() != timedelta(0):
            raise ValueError("deadline_at must be timezone-aware UTC")
        return value

    @field_validator("worker_hint_paths")
    @classmethod
    def _hint_paths_are_relative(cls, paths: tuple[str, ...]) -> tuple[str, ...]:
        normalized: list[str] = []
        for raw_path in paths:
            if ":" in raw_path:
                repo_id, path = raw_path.split(":", 1)
                if not repo_id:
                    raise ValueError("repo-scoped worker hint requires a repo id")
                normalized.append(f"{repo_id}:{_validated_relative_path(path)}")
            else:
                normalized.append(_validated_relative_path(raw_path))
        return tuple(normalized)

    @model_validator(mode="after")
    def _stage_fields_match(self) -> CollectVerifyEvidenceCommandPayload:
        if self.stage is VerifyEvidenceStage.BASE_COLLECTION:
            _validate_base_payload(self)
        else:
            _validate_dynamic_payload(self)
        _validate_repository_bindings(self)
        return self


def _validate_base_payload(payload: CollectVerifyEvidenceCommandPayload) -> None:
    dynamic_fields = (
        payload.preflight_attempt_id,
        payload.preflight_checkpoint_state,
        payload.preflight_request_hash,
    )
    if (
        payload.requests
        or payload.preflight_requests
        or any(value is not None for value in dynamic_fields)
        or payload.raw_preflight_response is not None
        or payload.base_manifest is not None
    ):
        raise ValueError("base_collection cannot carry preflight requests")


def _validate_dynamic_payload(payload: CollectVerifyEvidenceCommandPayload) -> None:
    dynamic_fields = (
        payload.preflight_attempt_id,
        payload.preflight_checkpoint_state,
        payload.preflight_request_hash,
    )
    if any(value is None for value in dynamic_fields):
        raise ValueError("dynamic_requests requires a preflight attempt")
    if payload.preflight_checkpoint_state == "started":
        if (
            payload.requests
            or payload.preflight_requests
            or payload.raw_preflight_response is not None
            or payload.base_manifest is not None
        ):
            raise ValueError("a started preflight attempt cannot carry a response")
        return
    if payload.raw_preflight_response is None or payload.base_manifest is None:
        raise ValueError("a ready preflight checkpoint requires response and manifest")


def _validate_repository_bindings(
    payload: CollectVerifyEvidenceCommandPayload,
) -> None:
    repo_ids = {repo.repo_id for repo in payload.repositories}
    if payload.spawn_worktree_repo not in repo_ids:
        raise ValueError("spawn_worktree_repo must be in repositories")
    for hint in payload.worker_hint_paths:
        if ":" in hint and hint.split(":", 1)[0] not in repo_ids:
            raise ValueError("worker hint references an unknown repository")


def _validate_test_argument(argument: str, expect_value: bool) -> bool:
    simple_flags = {"-q", "-v", "-vv", "-x", "-s", "--quiet"}
    value_flags = {"-k", "-m", "--maxfail", "--tb"}
    if len(argument) > 512:
        raise ValueError("pytest argument exceeds the bounded length")
    if any(token in argument for token in ("\n", "\r", ";", "|", ">", "<")):
        raise ValueError("pytest argument contains a shell operator")
    if expect_value:
        if not argument or argument.startswith("-"):
            raise ValueError("pytest option requires a bounded value")
        return False
    if argument in simple_flags or any(
        argument.startswith(f"{flag}=") for flag in value_flags
    ):
        return False
    if argument in value_flags:
        return True
    if argument.startswith("-"):
        raise ValueError(f"pytest option is not whitelisted: {argument}")
    _validate_test_target(argument)
    return False


def _validate_test_target(argument: str) -> None:
    raw_path = argument.split("::", maxsplit=1)[0]
    path = PurePosixPath(raw_path.replace("\\", "/"))
    windows_path = PureWindowsPath(raw_path)
    if (
        path.is_absolute()
        or windows_path.is_absolute()
        or bool(windows_path.drive)
        or ".." in path.parts
    ):
        raise ValueError("pytest target must stay inside the worktree")


class VerifyEvidenceReport(BaseModel):
    """Typed result echo and observations for one collection batch."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    result_type: Literal["verify_evidence_report"] = VERIFY_EVIDENCE_RESULT_TYPE
    stage: VerifyEvidenceStage
    batch_id: str = Field(pattern=SHA256_PATTERN)
    generation: str = Field(pattern=SHA256_PATTERN)
    candidate_digest: str = Field(pattern=SHA256_PATTERN)
    request_digest: str = Field(pattern=SHA256_PATTERN)
    finding_code: str | None = Field(default=None, max_length=128)
    files: tuple[VerifyEvidenceFile, ...] = ()
    observations: tuple[VerifyEvidenceObservation, ...] = ()

    @model_validator(mode="after")
    def _shape_matches_stage(self) -> VerifyEvidenceReport:
        if self.stage is VerifyEvidenceStage.BASE_COLLECTION and self.observations:
            raise ValueError("base_collection report cannot carry observations")
        if self.stage is VerifyEvidenceStage.DYNAMIC_REQUESTS and self.files:
            raise ValueError("dynamic_requests report cannot carry base files")
        total = sum(item.size for item in self.files)
        total += sum(candidate.size for item in self.observations for candidate in item.candidates)
        total += sum(
            len(item.content.encode("utf-8"))
            for item in self.observations
            if item.content is not None
        )
        if total > MAX_EVIDENCE_RESULT_BYTES:
            raise ValueError("verify-evidence result exceeds the total content limit")
        return self


def _validated_relative_path(raw_path: str) -> str:
    path = PurePosixPath(raw_path.replace("\\", "/"))
    windows_path = PureWindowsPath(raw_path)
    if (
        path.is_absolute()
        or windows_path.is_absolute()
        or bool(windows_path.drive)
        or not raw_path.strip()
        or ".." in path.parts
    ):
        raise ValueError(f"verify-evidence path must be relative: {raw_path!r}")
    return path.as_posix()


__all__ = [
    "CollectVerifyEvidenceCommandPayload",
    "MAX_EVIDENCE_FILE_BYTES",
    "MAX_EVIDENCE_RESULT_BYTES",
    "VERIFY_EVIDENCE_RESULT_TYPE",
    "VERIFY_EVIDENCE_SCHEMA_VERSION",
    "VerifyEvidenceFile",
    "VerifyEvidenceCanonicalRequest",
    "VerifyEvidenceObservation",
    "VerifyEvidenceObservationStatus",
    "VerifyEvidenceReport",
    "VerifyEvidenceRepository",
    "VerifyEvidenceRequest",
    "VerifyEvidenceStage",
    "VerifyTestCommand",
]
