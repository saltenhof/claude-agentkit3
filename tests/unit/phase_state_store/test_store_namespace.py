"""Unit tests for flow-state store facade exports."""

from agentkit.phase_state_store import store as store_module
from agentkit.state_backend import (
    load_flow_execution,
    load_node_execution_ledger,
    load_override_records,
    save_flow_execution,
    save_node_execution_ledger,
    save_override_record,
)


def test_phase_state_store_namespace_reexports_state_backend_api() -> None:
    assert store_module.load_flow_execution is load_flow_execution
    assert store_module.load_node_execution_ledger is load_node_execution_ledger
    assert store_module.load_override_records is load_override_records
    assert store_module.save_flow_execution is save_flow_execution
    assert store_module.save_node_execution_ledger is save_node_execution_ledger
    assert store_module.save_override_record is save_override_record
