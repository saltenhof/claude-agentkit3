"""Runtime state records for hierarchical flow execution.

These records model the execution-side concepts introduced by the
component/process DSL:

- ``FlowExecution``: one concrete run of a flow definition
- ``NodeExecutionLedger``: persistent execution history per node
- ``OverrideRecord``: audit trail for manual/orchestrator interventions

The current runtime still persists ``PhaseState`` and attempt records via
``agentkit.pipeline.state``. This module establishes the canonical
component namespace for the richer flow-oriented state model so the
engine can migrate towards it incrementally.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime


@dataclass(frozen=True)
class FlowExecution:
    """Execution record for a concrete flow attempt."""

    project_key: str
    story_id: str
    run_id: str
    flow_id: str
    level: str
    owner: str
    parent_flow_id: str | None = None
    status: str = "READY"
    current_node_id: str | None = None
    attempt_no: int = 1
    started_at: datetime = field(default_factory=lambda: datetime.now(tz=UTC))
    finished_at: datetime | None = None


@dataclass(frozen=True)
class NodeExecutionLedger:
    """Persistent execution history for a node within a flow."""

    project_key: str
    story_id: str
    run_id: str
    flow_id: str
    node_id: str
    execution_count: int = 0
    success_count: int = 0
    last_outcome: str | None = None
    last_attempt_no: int | None = None
    last_executed_at: datetime | None = None


@dataclass(frozen=True)
class OverrideRecord:
    """Audit record for a manual or orchestrator-issued override."""

    override_id: str
    project_key: str
    story_id: str
    run_id: str
    flow_id: str
    target_node_id: str | None
    override_type: str
    actor_type: str
    actor_id: str
    reason: str
    created_at: datetime
    consumed_at: datetime | None = None
