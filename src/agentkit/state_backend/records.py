"""Canonical runtime record types for the state backend."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from datetime import datetime

    from agentkit.story_context_manager.models import PhaseStatus


@dataclass(frozen=True)
class AttemptRecord:
    """Immutable record of a single phase execution attempt."""

    attempt_id: str
    phase: str
    entered_at: datetime
    exit_status: PhaseStatus | None = None
    guard_evaluations: tuple[dict[str, object], ...] = ()
    artifacts_produced: tuple[str, ...] = ()
    outcome: str | None = None
    yield_status: str | None = None
    resume_trigger: str | None = None


@dataclass(frozen=True)
class ExecutionReport:
    """Summary of a completed story execution."""

    story_id: str
    story_type: str
    status: str
    phases_executed: tuple[str, ...]
    started_at: str | None = None
    completed_at: str | None = None
    issue_closed: bool = False
    warnings: tuple[str, ...] = ()
    metrics: dict[str, object] | None = None

    def to_dict(self) -> dict[str, object]:
        """Serialize to the canonical export shape."""

        payload: dict[str, object] = {
            "story_id": self.story_id,
            "story_type": self.story_type,
            "status": self.status,
            "phases_executed": list(self.phases_executed),
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "issue_closed": self.issue_closed,
            "warnings": list(self.warnings),
        }
        if self.metrics is not None:
            payload["metrics"] = self.metrics
        return payload


@dataclass(frozen=True)
class ExecutionEventRecord:
    """Canonical append-only telemetry event for one runtime execution."""

    project_key: str
    story_id: str
    run_id: str
    event_id: str
    event_type: str
    occurred_at: datetime
    source_component: str
    severity: str
    phase: str | None = None
    flow_id: str | None = None
    node_id: str | None = None
    payload: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class SessionRunBindingRecord:
    """Central session-to-run binding used for operating mode resolution."""

    session_id: str
    project_key: str
    story_id: str
    run_id: str
    principal_type: str
    worktree_roots: tuple[str, ...]
    binding_version: str
    updated_at: datetime


@dataclass(frozen=True)
class StoryExecutionLockRecord:
    """Central lock record for the active story-execution regime."""

    project_key: str
    story_id: str
    run_id: str
    lock_type: str
    status: str
    worktree_roots: tuple[str, ...]
    binding_version: str
    activated_at: datetime
    updated_at: datetime
    deactivated_at: datetime | None = None


@dataclass(frozen=True)
class ControlPlaneOperationRecord:
    """Idempotent mutation record for one control-plane operation."""

    op_id: str
    project_key: str
    story_id: str
    run_id: str | None
    session_id: str | None
    operation_kind: str
    phase: str | None
    status: str
    response_payload: dict[str, object]
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True)
class StoryMetricsRecord:
    """Closure-time operational metrics for one completed story run."""

    project_key: str
    story_id: str
    run_id: str
    story_type: str
    story_size: str
    mode: str
    processing_time_min: float
    qa_rounds: int
    increments: int
    final_status: str
    completed_at: str
    adversarial_findings: int | None = None
    adversarial_tests_created: int | None = None
    files_changed: int | None = None
    agentkit_version: str | None = None
    agentkit_commit: str | None = None
    config_version: str | None = None
    llm_roles: tuple[str, ...] = ()

    def to_metrics_payload(self) -> dict[str, object]:
        """Serialize the closure metrics payload for projections."""

        payload: dict[str, object] = {
            "story_size": self.story_size,
            "mode": self.mode,
            "processing_time_min": self.processing_time_min,
            "qa_rounds": self.qa_rounds,
            "increments": self.increments,
            "final_status": self.final_status,
            "completed_at": self.completed_at,
        }
        if self.adversarial_findings is not None:
            payload["adversarial_findings"] = self.adversarial_findings
        if self.adversarial_tests_created is not None:
            payload["adversarial_tests_created"] = self.adversarial_tests_created
        if self.files_changed is not None:
            payload["files_changed"] = self.files_changed
        if self.agentkit_version is not None:
            payload["agentkit_version"] = self.agentkit_version
        if self.agentkit_commit is not None:
            payload["agentkit_commit"] = self.agentkit_commit
        if self.config_version is not None:
            payload["config_version"] = self.config_version
        if self.llm_roles:
            payload["llm_roles"] = list(self.llm_roles)
        return payload


@dataclass(frozen=True)
class QAStageResultRecord:
    """Queryable outcome of one QA stage for a single verify attempt."""

    project_key: str
    story_id: str
    run_id: str
    attempt_no: int
    stage_id: str
    layer: str
    producer_component: str
    status: str
    blocking: bool
    total_checks: int
    failed_checks: int
    warning_checks: int
    artifact_id: str
    recorded_at: datetime


@dataclass(frozen=True)
class QAFindingRecord:
    """Queryable projection of one QA finding for a single verify attempt."""

    project_key: str
    story_id: str
    run_id: str
    attempt_no: int
    stage_id: str
    finding_id: str
    check_id: str
    status: str
    severity: str
    blocking: bool
    source_component: str
    artifact_id: str
    occurred_at: datetime
    category: str | None = None
    reason: str | None = None
    description: str | None = None
    detail: str | None = None
    metadata: dict[str, object] = field(default_factory=dict)
