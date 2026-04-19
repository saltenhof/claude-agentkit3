"""Flow-oriented runtime state store component."""

from __future__ import annotations

from agentkit.phase_state_store.models import (
    FlowExecution,
    NodeExecutionLedger,
    OverrideRecord,
)


def load_flow_execution(story_dir):
    from agentkit.state_backend import load_flow_execution as _load_flow_execution

    return _load_flow_execution(story_dir)


def load_node_execution_ledger(story_dir, flow_id: str, node_id: str):
    from agentkit.state_backend import (
        load_node_execution_ledger as _load_node_execution_ledger,
    )

    return _load_node_execution_ledger(story_dir, flow_id, node_id)


def load_override_records(story_dir):
    from agentkit.state_backend import load_override_records as _load_override_records

    return _load_override_records(story_dir)


def save_flow_execution(story_dir, record: FlowExecution) -> None:
    from agentkit.state_backend import save_flow_execution as _save_flow_execution

    _save_flow_execution(story_dir, record)


def save_node_execution_ledger(story_dir, record: NodeExecutionLedger) -> None:
    from agentkit.state_backend import (
        save_node_execution_ledger as _save_node_execution_ledger,
    )

    _save_node_execution_ledger(story_dir, record)


def save_override_record(story_dir, record: OverrideRecord) -> None:
    from agentkit.state_backend import save_override_record as _save_override_record

    _save_override_record(story_dir, record)

__all__ = [
    "FlowExecution",
    "NodeExecutionLedger",
    "OverrideRecord",
    "load_flow_execution",
    "load_node_execution_ledger",
    "load_override_records",
    "save_flow_execution",
    "save_node_execution_ledger",
    "save_override_record",
]
