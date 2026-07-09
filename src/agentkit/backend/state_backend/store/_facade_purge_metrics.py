"""Runtime residue purge and story metrics facade operations."""

from __future__ import annotations

from agentkit.backend.state_backend.artifact_catalog_store import (
    purge_run_bound_artifact_envelopes as purge_run_bound_artifact_envelopes,
)
from agentkit.backend.state_backend.governance_runtime_store import (
    purge_guard_decisions as purge_guard_decisions,
)
from agentkit.backend.state_backend.pipeline_runtime_store import (
    count_runtime_execution_residue as count_runtime_execution_residue,
)
from agentkit.backend.state_backend.pipeline_runtime_store import (
    purge_attempts as purge_attempts,
)
from agentkit.backend.state_backend.pipeline_runtime_store import (
    purge_flow_executions as purge_flow_executions,
)
from agentkit.backend.state_backend.pipeline_runtime_store import (
    purge_node_execution_ledgers as purge_node_execution_ledgers,
)
from agentkit.backend.state_backend.pipeline_runtime_store import (
    purge_override_records as purge_override_records,
)
from agentkit.backend.state_backend.pipeline_runtime_store import (
    purge_phase_snapshots as purge_phase_snapshots,
)
from agentkit.backend.state_backend.pipeline_runtime_store import (
    purge_phase_states as purge_phase_states,
)
from agentkit.backend.state_backend.telemetry_event_store import (
    load_latest_story_metrics_global as load_latest_story_metrics_global,
)
from agentkit.backend.state_backend.telemetry_event_store import (
    load_story_metrics as load_story_metrics,
)
from agentkit.backend.state_backend.telemetry_event_store import (
    load_story_metrics_for_scope as load_story_metrics_for_scope,
)
from agentkit.backend.state_backend.telemetry_event_store import (
    purge_execution_events as purge_execution_events,
)
from agentkit.backend.state_backend.telemetry_event_store import (
    upsert_story_metrics as upsert_story_metrics,
)
from agentkit.backend.state_backend.verify_artifact_store import (
    purge_decision_records as purge_decision_records,
)

__all__ = [
    "purge_flow_executions",
    "purge_node_execution_ledgers",
    "purge_attempts",
    "purge_override_records",
    "purge_guard_decisions",
    "purge_phase_states",
    "purge_phase_snapshots",
    "purge_decision_records",
    "purge_execution_events",
    "purge_run_bound_artifact_envelopes",
    "count_runtime_execution_residue",
    "upsert_story_metrics",
    "load_story_metrics",
    "load_story_metrics_for_scope",
    "load_latest_story_metrics_global",
]
