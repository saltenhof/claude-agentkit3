"""Flow-oriented runtime state APIs.

Station 6 (AG3-024): PhaseEnvelopeStore is the canonical phase-state
facade. This module re-exports it for backward-compat consumers that
import from ``agentkit.backend.phase_state_store.store``.  There is intentionally
no second persistence implementation here -- all I/O goes through
``PhaseEnvelopeStore`` backed by ``StateBackendPhaseEnvelopeRepository``.
"""

from __future__ import annotations

from agentkit.backend.pipeline_engine.phase_envelope.store import (
    PhaseEnvelopeStore as PhaseStateStore,
)
from agentkit.backend.state_backend.store import (
    load_flow_execution,
    load_node_execution_ledger,
    load_override_records,
    save_flow_execution,
    save_node_execution_ledger,
    save_override_record,
)

__all__ = [
    "PhaseStateStore",
    "load_flow_execution",
    "load_node_execution_ledger",
    "load_override_records",
    "save_flow_execution",
    "save_node_execution_ledger",
    "save_override_record",
]
