"""Story-exit service implementing the canonical FK-58 exit sequence."""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Protocol

from pydantic import BaseModel, ConfigDict, field_validator

from agentkit.backend.control_plane.records import BindingDeleteScope, ControlPlaneOperationRecord
from agentkit.backend.governance.guard_system.records import StoryExecutionLockRecord
from agentkit.backend.governance.principal_capabilities.principals import Principal
from agentkit.backend.story_exit.models import (
    STORY_EXIT_PRODUCER_ID,
    AdmissibilityAssessment,
    AlternativeReview,
    DeltaQuarantine,
    ExitClass,
    ExitManifestSnapshot,
    ExitReason,
    StoryExitRecord,
    TerminalState,
)
from agentkit.backend.telemetry.contract.records import ExecutionEventRecord
from agentkit.backend.telemetry.events import EventType

if TYPE_CHECKING:
    from collections.abc import Callable

    from agentkit.backend.control_plane.repository import ControlPlaneRuntimeRepository


class StoryExitError(RuntimeError):
    """Fail-closed story-exit rejection."""


class _GovernanceTeardown(Protocol):
    def deactivate_locks(self, story_id: str) -> object:
        """Deactivate lock exports and guard regime for ``story_id``."""


class _StoryServicePort(Protocol):
    def administratively_cancel_for_story_exit(
        self,
        story_display_id: str,
        *,
        story_exit_record: object,
        story_exit_operation_committed: bool,
        principal: object,
        op_id: str,
    ) -> object:
        """Administratively cancel the story for a validated story exit."""


class ExitRunState(BaseModel):
    """Service-owned run signals used to derive exit admissibility."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    project_key: str
    story_id: str
    run_id: str
    session_id: str
    integration_budget_exhausted: bool = False
    approved_manifest_no_longer_sufficient: bool = False
    human_design_required: bool = False
    integration_strategy_blocked: bool = False
    story_contract_not_fit: bool = False
    remediation_exhausted: bool = False
    split_or_replan_available: bool = False
    reclassification_available: bool = False
    standard_contract_viable: bool = False
    architecture_blockers: tuple[str, ...] = ()
    open_questions: tuple[str, ...] = ()
    recommendation: str = ""
    out_of_contract_deltas: tuple[str, ...] = ()

    @field_validator(
        "architecture_blockers",
        "open_questions",
        "out_of_contract_deltas",
        mode="before",
    )
    @classmethod
    def _tuple_of_strings(cls, value: object) -> tuple[str, ...]:
        if value is None:
            return ()
        if isinstance(value, str):
            return (value.strip(),) if value.strip() else ()
        if isinstance(value, list | tuple):
            return tuple(str(item).strip() for item in value if str(item).strip())
        return ()


@dataclass(frozen=True)
class StoryExitRequest:
    """Human CLI request for a story exit."""

    project_key: str
    story_id: str
    run_id: str
    session_id: str
    reason: ExitReason
    principal: Principal
    note: str | None = None
    exit_id: str | None = None


@dataclass(frozen=True)
class StoryExitResult:
    """Successful story-exit result."""

    exit_id: str
    record: StoryExitRecord
    manifest_snapshot: ExitManifestSnapshot
    artifact_dir: Path
    operating_mode: str
    fence_committed: bool
    binding_revoked: bool
    exit_finalized: bool


class StoryExitService:
    """Orchestrates the single canonical story-exit transaction."""

    def __init__(
        self,
        *,
        control_plane_repository: ControlPlaneRuntimeRepository,
        story_service: _StoryServicePort,
        governance: _GovernanceTeardown,
        artifact_root: Path | str = Path("var/story_exit"),
        run_state_loader: Callable[[StoryExitRequest], ExitRunState] | None = None,
        now_fn: Callable[[], datetime] | None = None,
    ) -> None:
        self._repo = control_plane_repository
        self._story_service = story_service
        self._governance = governance
        self._artifact_root = Path(artifact_root)
        self._run_state_loader = run_state_loader or self._default_run_state
        self._now_fn = now_fn or (lambda: datetime.now(tz=UTC))

    def exit_story(self, request: StoryExitRequest) -> StoryExitResult:
        """Execute Phase A-E story exit with fence-first idempotency."""

        exit_id = request.exit_id or f"story-exit-{uuid.uuid4().hex}"
        normalized = StoryExitRequest(
            project_key=request.project_key,
            story_id=request.story_id,
            run_id=request.run_id,
            session_id=request.session_id,
            reason=request.reason,
            principal=request.principal,
            note=request.note,
            exit_id=exit_id,
        )
        if normalized.principal is not Principal.HUMAN_CLI:
            raise StoryExitError("story exit requires Principal.HUMAN_CLI")

        run_state = self._run_state_loader(normalized)
        self._validate_bound_run(normalized)
        now = self._now_fn()
        assessment = self._derive_admissibility(normalized.reason, run_state)
        alternatives = self._derive_alternative_review(run_state)
        manifest = self._manifest_snapshot(normalized, run_state, now=now)
        record = self._record(
            normalized,
            assessment=assessment,
            alternatives=alternatives,
            now=now,
        )
        dossier = self._dossier(record, manifest)
        self.exit_gate(record=record, dossier=dossier)

        artifact_dir = self._artifact_dir(normalized.story_id, exit_id)
        artifact_paths = self._write_artifacts(
            artifact_dir=artifact_dir,
            record=record,
            manifest=manifest,
            dossier=dossier,
            deltas=run_state.out_of_contract_deltas,
            now=now,
        )
        record = record.model_copy(update={"artifact_paths": artifact_paths})
        self._write_json(artifact_dir / "story_exit_record.json", record)

        self._commit_fence(normalized, record=record, now=now)
        story_exit_committed = self._repo.has_committed_story_exit_operation_for_run(
            normalized.project_key,
            normalized.story_id,
            normalized.run_id,
        )
        self._administratively_cancel(normalized, record, story_exit_committed)
        teardown_mode = self._commit_teardown(normalized, record=record, now=now)
        deactivation = self._governance.deactivate_locks(normalized.story_id)
        self.exit_finalized(
            request=normalized,
            deactivation_result=deactivation,
            operating_mode=teardown_mode,
        )
        return StoryExitResult(
            exit_id=exit_id,
            record=record,
            manifest_snapshot=manifest,
            artifact_dir=artifact_dir,
            operating_mode=teardown_mode,
            fence_committed=True,
            binding_revoked=True,
            exit_finalized=True,
        )

    def exit_gate(self, *, record: StoryExitRecord | None, dossier: str | None) -> None:
        """Pre-mutation approval gate; no cleanup or closure semantics."""

        if record is None:
            raise StoryExitError("exit_gate rejected: story_exit_record is missing")
        if not record.is_gate_admissible:
            blocked = (
                *record.admissibility_assessment.blocking_predicates(),
                *record.alternative_review.blocking_checks(),
            )
            raise StoryExitError(
                "exit_gate rejected: exit reason is not admissible "
                f"({', '.join(blocked)})"
            )
        if not dossier or not dossier.strip():
            raise StoryExitError("exit_gate rejected: viability_dossier is missing")

    def exit_finalized(
        self,
        *,
        request: StoryExitRequest,
        deactivation_result: object,
        operating_mode: str,
    ) -> None:
        """Post-teardown verification of cleanup and free-mode fallback."""

        binding = self._repo.load_binding(request.session_id)
        lock = self._repo.load_lock(
            request.project_key,
            request.story_id,
            request.run_id,
            "story_execution",
        )
        qa_lock = self._repo.load_lock(
            request.project_key,
            request.story_id,
            request.run_id,
            "qa_artifact_write",
        )
        if binding is not None:
            raise StoryExitError("exit_finalized rejected: session binding still exists")
        if lock is None or lock.status != "INACTIVE":
            raise StoryExitError("exit_finalized rejected: story lock is not inactive")
        if qa_lock is None or qa_lock.status != "INACTIVE":
            raise StoryExitError("exit_finalized rejected: QA lock is not inactive")
        if not bool(getattr(deactivation_result, "restored_to_ai_augmented", False)):
            raise StoryExitError("exit_finalized rejected: guards were not deactivated")
        if operating_mode != "ai_augmented":
            raise StoryExitError("exit_finalized rejected: session is not ai_augmented")

    def _default_run_state(self, request: StoryExitRequest) -> ExitRunState:
        binding = self._repo.load_binding(request.session_id)
        if binding is None:
            raise StoryExitError("story exit requires an active bound run")
        return ExitRunState(
            project_key=binding.project_key,
            story_id=binding.story_id,
            run_id=binding.run_id,
            session_id=binding.session_id,
        )

    def _validate_bound_run(self, request: StoryExitRequest) -> None:
        binding = self._repo.load_binding(request.session_id)
        if binding is None:
            raise StoryExitError("story exit requires an active session binding")
        if (
            binding.project_key != request.project_key
            or binding.story_id != request.story_id
            or binding.run_id != request.run_id
        ):
            raise StoryExitError(
                "story exit refused: session binding belongs to a different run"
            )

    def _derive_admissibility(
        self,
        reason: ExitReason,
        run_state: ExitRunState,
    ) -> AdmissibilityAssessment:
        hard_evidence = self._reason_has_hard_evidence(reason, run_state)
        return AdmissibilityAssessment(
            normal_difficulty_excluded=hard_evidence,
            mere_agent_uncertainty_excluded=hard_evidence,
            usual_remediation_excluded=run_state.remediation_exhausted,
            split_or_replan_excluded=not run_state.split_or_replan_available,
        )

    def _reason_has_hard_evidence(
        self,
        reason: ExitReason,
        run_state: ExitRunState,
    ) -> bool:
        if reason is ExitReason.SOLUTION_VIABILITY_REQUIRES_HUMAN_DESIGN:
            return run_state.human_design_required or bool(run_state.architecture_blockers)
        if reason is ExitReason.INTEGRATION_STRATEGY_NOT_SCOPE_QUESTION:
            return run_state.integration_strategy_blocked
        if reason is ExitReason.INTEGRATION_BUDGET_EXHAUSTED:
            return run_state.integration_budget_exhausted
        if reason is ExitReason.APPROVED_MANIFEST_NO_LONGER_SUFFICIENT:
            return run_state.approved_manifest_no_longer_sufficient
        return run_state.story_contract_not_fit

    def _derive_alternative_review(self, run_state: ExitRunState) -> AlternativeReview:
        return AlternativeReview(
            standard_contract_checked=True,
            standard_contract_rejection_reason=(
                "Bound standard contract no longer fits the required decision space."
                if not run_state.standard_contract_viable
                else ""
            ),
            reclassification_checked=True,
            reclassification_rejection_reason=(
                "Integration-stabilization reclassification does not resolve the "
                "human design decision."
                if not run_state.reclassification_available
                else ""
            ),
            split_checked=True,
            split_rejection_reason=(
                "Story split or normal replan does not isolate the blocked decision."
                if not run_state.split_or_replan_available
                else ""
            ),
        )

    def _manifest_snapshot(
        self,
        request: StoryExitRequest,
        run_state: ExitRunState,
        *,
        now: datetime,
    ) -> ExitManifestSnapshot:
        return ExitManifestSnapshot(
            project_key=request.project_key,
            story_id=request.story_id,
            run_id=request.run_id,
            session_id=request.session_id,
            reason=request.reason,
            integration_budget_exhausted=run_state.integration_budget_exhausted,
            approved_manifest_no_longer_sufficient=(
                run_state.approved_manifest_no_longer_sufficient
            ),
            human_design_required=run_state.human_design_required,
            integration_strategy_blocked=run_state.integration_strategy_blocked,
            story_contract_not_fit=run_state.story_contract_not_fit,
            remediation_exhausted=run_state.remediation_exhausted,
            split_or_replan_available=run_state.split_or_replan_available,
            reclassification_available=run_state.reclassification_available,
            standard_contract_viable=run_state.standard_contract_viable,
            architecture_blockers=run_state.architecture_blockers,
            open_questions=run_state.open_questions,
            recommendation=run_state.recommendation,
            out_of_contract_deltas=run_state.out_of_contract_deltas,
            captured_at=now,
        )

    def _record(
        self,
        request: StoryExitRequest,
        *,
        assessment: AdmissibilityAssessment,
        alternatives: AlternativeReview,
        now: datetime,
    ) -> StoryExitRecord:
        if request.exit_id is None:
            raise StoryExitError("story exit requires an exit_id")
        return StoryExitRecord(
            exit_id=request.exit_id,
            project_key=request.project_key,
            story_id=request.story_id,
            run_id=request.run_id,
            session_id=request.session_id,
            reason=request.reason,
            note=request.note,
            principal=request.principal,
            terminal_state=TerminalState.CANCELLED,
            exit_class=ExitClass.VIABILITY_HANDOFF,
            admissibility_assessment=assessment,
            alternative_review=alternatives,
            created_at=now,
        )

    def _dossier(
        self,
        record: StoryExitRecord,
        manifest: ExitManifestSnapshot,
    ) -> str:
        blockers = "\n".join(f"- {item}" for item in manifest.architecture_blockers)
        questions = "\n".join(f"- {item}" for item in manifest.open_questions)
        return "\n".join(
            [
                f"# Viability Dossier: {record.story_id}",
                "",
                f"Exit ID: {record.exit_id}",
                f"Reason: {record.reason.value}",
                "",
                "## Problem Core",
                blockers or "- Bound run evidence requires human design review.",
                "",
                "## Why The Story Contract Ends",
                "- The current run is administratively cancelled, not delivered.",
                "- Further work leaves story_execution and returns to ai_augmented.",
                "",
                "## Open Questions",
                questions or "- Human owner must decide the next integration/design step.",
                "",
                "## Recommendation",
                manifest.recommendation
                or "Continue manually in ai_augmented or create a new official story.",
            ]
        )

    def _artifact_dir(self, story_id: str, exit_id: str) -> Path:
        return self._artifact_root / story_id / exit_id

    def _write_artifacts(
        self,
        *,
        artifact_dir: Path,
        record: StoryExitRecord,
        manifest: ExitManifestSnapshot,
        dossier: str,
        deltas: tuple[str, ...],
        now: datetime,
    ) -> dict[str, str]:
        artifact_dir.mkdir(parents=True, exist_ok=True)
        paths = {
            "viability_dossier": str(artifact_dir / "viability_dossier.md"),
            "story_exit_record": str(artifact_dir / "story_exit_record.json"),
            "exit_manifest_snapshot": str(artifact_dir / "exit_manifest_snapshot.json"),
        }
        (artifact_dir / "viability_dossier.md").write_text(dossier, encoding="utf-8")
        self._write_json(artifact_dir / "exit_manifest_snapshot.json", manifest)
        if deltas:
            quarantine = DeltaQuarantine(
                exit_id=record.exit_id,
                story_id=record.story_id,
                deltas=deltas,
                created_at=now,
            )
            self._write_json(artifact_dir / "delta_quarantine.json", quarantine)
            paths["delta_quarantine"] = str(artifact_dir / "delta_quarantine.json")
        return paths

    def _write_json(self, path: Path, model: BaseModel) -> None:
        path.write_text(
            json.dumps(model.model_dump(mode="json"), indent=2, sort_keys=True),
            encoding="utf-8",
        )

    def _commit_fence(
        self,
        request: StoryExitRequest,
        *,
        record: StoryExitRecord,
        now: datetime,
    ) -> None:
        existing = self._repo.load_operation(record.exit_id)
        if existing is not None:
            if (
                existing.status == "committed"
                and existing.operation_kind == "story_exit"
                and existing.project_key == request.project_key
                and existing.story_id == request.story_id
                and existing.run_id == request.run_id
            ):
                return
            raise StoryExitError("story exit fence collides with a foreign operation")
        op_record = self._operation_record(
            request,
            record=record,
            now=now,
            exit_status="exit_gate_passed",
        )
        self._repo.commit_operation_with_side_effects(
            op_record,
            binding_to_save=None,
            binding_to_delete=None,
            locks=(),
            events=(),
        )

    def _administratively_cancel(
        self,
        request: StoryExitRequest,
        record: StoryExitRecord,
        story_exit_committed: bool,
    ) -> None:
        story = self._story_service.administratively_cancel_for_story_exit(
            request.story_id,
            story_exit_record=record,
            story_exit_operation_committed=story_exit_committed,
            principal=request.principal,
            op_id=record.exit_id,
        )
        if str(getattr(story, "status", "")) != "Cancelled":
            raise StoryExitError("story exit teardown requires story status Cancelled")

    def _commit_teardown(
        self,
        request: StoryExitRequest,
        *,
        record: StoryExitRecord,
        now: datetime,
    ) -> str:
        binding = self._repo.load_binding(request.session_id)
        if binding is None:
            worktree_roots: tuple[str, ...] = ()
            binding_version = f"exit-{record.exit_id}"
        elif (
            binding.project_key == request.project_key
            and binding.story_id == request.story_id
            and binding.run_id == request.run_id
        ):
            worktree_roots = binding.worktree_roots
            binding_version = binding.binding_version
        else:
            raise StoryExitError("story exit teardown refused: binding collision")
        lock = self._inactive_lock(
            request,
            lock_type="story_execution",
            worktree_roots=worktree_roots,
            binding_version=binding_version,
            now=now,
        )
        qa_lock = self._inactive_lock(
            request,
            lock_type="qa_artifact_write",
            worktree_roots=worktree_roots,
            binding_version=binding_version,
            now=now,
        )
        events = (
            self._event(
                request,
                event_type=EventType.STORY_EXIT_BINDING_REVOKED,
                payload={"exit_id": record.exit_id, "session_id": request.session_id},
                now=now,
            ),
            self._event(
                request,
                event_type=EventType.STORY_EXIT_COMPLETED,
                payload={"exit_id": record.exit_id},
                now=now,
            ),
        )
        op_record = self._operation_record(
            request,
            record=record,
            now=now,
            exit_status="binding_revoked",
        )
        self._repo.commit_operation_with_side_effects(
            op_record,
            binding_to_save=None,
            binding_to_delete=BindingDeleteScope(
                session_id=request.session_id,
                project_key=request.project_key,
                story_id=request.story_id,
                run_id=request.run_id,
            ),
            locks=(lock, qa_lock),
            events=events,
        )
        from agentkit.backend.control_plane.runtime import _resolve_operating_mode

        return _resolve_operating_mode(binding=None, lock=lock)

    def _operation_record(
        self,
        request: StoryExitRequest,
        *,
        record: StoryExitRecord,
        now: datetime,
        exit_status: str,
    ) -> ControlPlaneOperationRecord:
        payload: dict[str, object] = {
            "status": "committed",
            "op_id": record.exit_id,
            "operation_kind": "story_exit",
            "run_id": request.run_id,
            "phase": None,
            "exit_status": exit_status,
            "exit_class": record.exit_class.value,
            "terminal_state": record.terminal_state.value,
        }
        return ControlPlaneOperationRecord(
            op_id=record.exit_id,
            project_key=request.project_key,
            story_id=request.story_id,
            run_id=request.run_id,
            session_id=request.session_id,
            operation_kind="story_exit",
            phase=None,
            status="committed",
            response_payload=payload,
            created_at=now,
            updated_at=now,
        )

    def _inactive_lock(
        self,
        request: StoryExitRequest,
        *,
        lock_type: str,
        worktree_roots: tuple[str, ...],
        binding_version: str,
        now: datetime,
    ) -> StoryExecutionLockRecord:
        return StoryExecutionLockRecord(
            project_key=request.project_key,
            story_id=request.story_id,
            run_id=request.run_id,
            lock_type=lock_type,
            status="INACTIVE",
            worktree_roots=worktree_roots,
            binding_version=binding_version,
            activated_at=now,
            updated_at=now,
            deactivated_at=now,
        )

    def _event(
        self,
        request: StoryExitRequest,
        *,
        event_type: EventType,
        payload: dict[str, object],
        now: datetime,
    ) -> ExecutionEventRecord:
        return ExecutionEventRecord(
            project_key=request.project_key,
            story_id=request.story_id,
            run_id=request.run_id,
            event_id=f"event-{uuid.uuid4().hex}",
            event_type=event_type.value,
            occurred_at=now,
            source_component=STORY_EXIT_PRODUCER_ID,
            severity="INFO",
            phase=None,
            payload=payload,
        )
