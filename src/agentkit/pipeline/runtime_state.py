"""Runtime persistence helpers for pipeline execution.

This module owns the file-backed runtime bookkeeping used by the engine:
attempt numbering, flow/node ledgers, and override record persistence.
The engine remains responsible for orchestration decisions.
"""

from __future__ import annotations

import uuid
from dataclasses import replace
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from agentkit.state_backend import (
    FlowExecution,
    NodeExecutionLedger,
    OverrideRecord,
    load_attempts,
    load_flow_execution,
    load_node_execution_ledger,
    load_override_records,
    save_flow_execution,
    save_node_execution_ledger,
    save_override_record,
)
from agentkit.telemetry.events import Event, EventType
from agentkit.telemetry.storage import StateBackendEmitter

if TYPE_CHECKING:
    from pathlib import Path

    from agentkit.process.language.model import WorkflowDefinition
    from agentkit.story_context_manager.models import StoryContext


class EngineRuntimeState:
    """Persist runtime execution state for a workflow run."""

    def __init__(
        self,
        workflow: WorkflowDefinition,
        story_dir: Path,
    ) -> None:
        self._workflow = workflow
        self._story_dir = story_dir
        self._run_id = str(uuid.uuid4())
        self._telemetry = StateBackendEmitter(
            story_dir,
            default_source_component="pipeline_engine",
        )

    def generate_attempt_id(self, phase: str) -> str:
        """Generate the next attempt id for a phase."""

        existing = load_attempts(self._story_dir, phase)
        next_num = len(existing) + 1
        return f"{phase}-{next_num:03d}"

    def project_key_for(self, ctx: StoryContext) -> str:
        """Return the canonical project key from StoryContext."""

        return ctx.project_key

    def resolve_run_id(self, ctx: StoryContext) -> str:
        """Reuse an existing run id or a stable per-instance fallback."""

        existing = load_flow_execution(self._story_dir)
        if (
            existing is not None
            and existing.flow_id == self._workflow.flow_id
            and existing.story_id == ctx.story_id
            and existing.project_key == self.project_key_for(ctx)
        ):
            return existing.run_id
        return self._run_id

    def attempt_number(self, attempt_id: str) -> int:
        """Parse the numeric suffix from an attempt id."""

        try:
            return int(attempt_id.rsplit("-", maxsplit=1)[1])
        except (IndexError, ValueError):
            return 1

    def record_flow_execution(
        self,
        ctx: StoryContext,
        phase_name: str,
        attempt_id: str,
        *,
        status: str,
        node_id: str | None,
        finished_at: datetime | None = None,
    ) -> None:
        """Persist the current top-level flow execution state."""

        existing = load_flow_execution(self._story_dir)
        run_id = self.resolve_run_id(ctx)
        attempt_no = self.attempt_number(attempt_id)
        is_new_flow = (
            existing is None or existing.flow_id != self._workflow.flow_id
        )
        started_at = (
            existing.started_at
            if existing is not None and existing.flow_id == self._workflow.flow_id
            else datetime.now(tz=UTC)
        )
        record = FlowExecution(
            project_key=self.project_key_for(ctx),
            story_id=ctx.story_id,
            run_id=run_id,
            flow_id=self._workflow.flow_id,
            level=self._workflow.level.value,
            owner=self._workflow.owner,
            parent_flow_id=None,
            status=status,
            current_node_id=node_id or phase_name,
            attempt_no=attempt_no,
            started_at=started_at,
            finished_at=finished_at,
        )
        save_flow_execution(self._story_dir, record)
        if is_new_flow:
            self._emit_event(
                ctx,
                EventType.AGENT_START,
                phase=phase_name,
                node_id=node_id or phase_name,
                payload={
                    "flow_id": self._workflow.flow_id,
                    "level": self._workflow.level.value,
                    "owner": self._workflow.owner,
                    "attempt_no": attempt_no,
                    "agent_type": "pipeline_engine",
                },
            )
            self._emit_event(
                ctx,
                EventType.FLOW_START,
                phase=phase_name,
                node_id=node_id or phase_name,
                payload={
                    "flow_id": self._workflow.flow_id,
                    "level": self._workflow.level.value,
                    "owner": self._workflow.owner,
                    "attempt_no": attempt_no,
                },
            )

    def record_node_outcome(
        self,
        ctx: StoryContext,
        node_id: str,
        attempt_id: str,
        *,
        outcome: str,
        target_node_id: str | None = None,
    ) -> None:
        """Persist node execution history for the current flow node."""

        existing = load_node_execution_ledger(
            self._story_dir,
            self._workflow.flow_id,
            node_id,
        )
        execution_count = 1
        success_count = 1 if outcome == "PASS" else 0
        if existing is not None:
            execution_count = existing.execution_count + 1
            success_count = existing.success_count + (1 if outcome == "PASS" else 0)

        ledger = NodeExecutionLedger(
            project_key=self.project_key_for(ctx),
            story_id=ctx.story_id,
            run_id=self.resolve_run_id(ctx),
            flow_id=self._workflow.flow_id,
            node_id=node_id,
            execution_count=execution_count,
            success_count=success_count,
            last_outcome=outcome,
            last_attempt_no=self.attempt_number(attempt_id),
            last_executed_at=datetime.now(tz=UTC),
        )
        save_node_execution_ledger(self._story_dir, ledger)
        payload: dict[str, object] = {
            "flow_id": self._workflow.flow_id,
            "node_id": node_id,
            "kind": "phase",
            "outcome": outcome,
            "attempt_no": self.attempt_number(attempt_id),
        }
        if target_node_id is not None:
            payload["target_node_id"] = target_node_id
        self._emit_event(
            ctx,
            EventType.NODE_RESULT,
            phase=node_id,
            node_id=node_id,
            payload=payload,
        )

    def record_flow_end(
        self,
        ctx: StoryContext,
        phase_name: str,
        attempt_id: str,
        *,
        status: str,
        node_id: str | None,
    ) -> None:
        """Emit the canonical terminal event for the current flow run."""

        self._emit_event(
            ctx,
            EventType.FLOW_END,
            phase=phase_name,
            node_id=node_id or phase_name,
            payload={
                "flow_id": self._workflow.flow_id,
                "level": self._workflow.level.value,
                "owner": self._workflow.owner,
                "attempt_no": self.attempt_number(attempt_id),
                "status": status,
            },
        )

    def iter_active_overrides(self, ctx: StoryContext) -> list[OverrideRecord]:
        """Load active overrides for the current run."""

        run_id = self.resolve_run_id(ctx)
        matches: list[OverrideRecord] = []
        for record in load_override_records(self._story_dir):
            if record.consumed_at is not None:
                continue
            if record.flow_id != self._workflow.flow_id or record.run_id != run_id:
                continue
            matches.append(record)
        return matches

    def consume_override(self, ctx: StoryContext, record: OverrideRecord) -> None:
        """Mark an override as consumed."""

        save_override_record(
            self._story_dir,
            replace(record, consumed_at=datetime.now(tz=UTC)),
        )
        self._emit_event(
            ctx,
            EventType.OVERRIDE_APPLIED,
            phase=record.target_node_id,
            node_id=record.target_node_id,
            payload={
                "flow_id": record.flow_id,
                "node_id": record.target_node_id,
                "override_type": record.override_type,
                "actor_type": record.actor_type,
                "override_id": record.override_id,
            },
        )

    def _emit_event(
        self,
        ctx: StoryContext,
        event_type: EventType,
        *,
        phase: str | None,
        node_id: str | None,
        payload: dict[str, object],
    ) -> None:
        self._telemetry.emit(
            Event(
                project_key=self.project_key_for(ctx),
                story_id=ctx.story_id,
                event_type=event_type,
                phase=phase,
                flow_id=self._workflow.flow_id,
                node_id=node_id,
                payload=payload,
                run_id=self.resolve_run_id(ctx),
            ),
        )
