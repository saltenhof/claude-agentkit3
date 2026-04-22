"""Telemetry event model -- immutable facts about what happened.

Events are facts, not commands (ARCH-41). All frozen (ARCH-29).
Domain terms explicitly modeled via EventType enum (ARCH-14).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum


class EventType(StrEnum):
    """Catalog of all telemetry event types (ARCH-14).

    Each value is a domain-specific fact type that describes what happened
    in the pipeline.  Never used as a command -- events record history.
    """

    # Worker lifecycle
    AGENT_START = "agent_start"
    AGENT_END = "agent_end"
    INCREMENT_COMMIT = "increment_commit"
    DRIFT_CHECK = "drift_check"

    # Flow runtime
    FLOW_START = "flow_start"
    FLOW_END = "flow_end"
    NODE_RESULT = "node_result"
    OVERRIDE_APPLIED = "override_applied"

    # Review / LLM
    REVIEW_REQUEST = "review_request"
    REVIEW_RESPONSE = "review_response"
    REVIEW_COMPLIANT = "review_compliant"
    LLM_CALL = "llm_call"

    # Adversarial
    ADVERSARIAL_START = "adversarial_start"
    ADVERSARIAL_SPARRING = "adversarial_sparring"
    ADVERSARIAL_TEST_CREATED = "adversarial_test_created"
    ADVERSARIAL_TEST_EXECUTED = "adversarial_test_executed"
    ADVERSARIAL_END = "adversarial_end"

    # Preflight / divergence
    PREFLIGHT_REQUEST = "preflight_request"
    PREFLIGHT_RESPONSE = "preflight_response"
    PREFLIGHT_COMPLIANT = "preflight_compliant"
    REVIEW_DIVERGENCE = "review_divergence"

    # Governance / analytics
    INTEGRITY_VIOLATION = "integrity_violation"
    SESSION_RUN_BINDING_CREATED = "session_run_binding_created"
    SESSION_RUN_BINDING_REMOVED = "session_run_binding_removed"
    STORY_EXECUTION_REGIME_ACTIVATED = "story_execution_regime_activated"
    STORY_EXECUTION_REGIME_DEACTIVATED = "story_execution_regime_deactivated"
    BINDING_INVALID_DETECTED = "binding_invalid_detected"
    LOCAL_EDGE_BUNDLE_MATERIALIZED = "local_edge_bundle_materialized"
    EDGE_OPERATION_RECONCILED = "edge_operation_reconciled"
    WEB_CALL = "web_call"
    IMPACT_VIOLATION_CHECK = "impact_violation_check"
    DOC_FIDELITY_CHECK = "doc_fidelity_check"
    VECTORDB_SEARCH = "vectordb_search"
    COMPACTION_EVENT = "compaction_event"

    # General
    ERROR = "error"
    WARNING = "warning"


@dataclass(frozen=True)
class Event:
    """An immutable telemetry event (ARCH-29).

    Events are facts -- they record what happened, not what should happen
    (ARCH-41).  The ``payload`` dict carries event-specific data without
    requiring subclasses for every event type.

    Args:
        story_id: Identifier of the story this event belongs to.
        event_type: Categorisation from the ``EventType`` enum.
        timestamp: UTC instant when the event occurred (auto-populated).
        phase: Pipeline phase name, if applicable.
        payload: Arbitrary structured data describing the event detail.
        run_id: Optional identifier linking events to a single pipeline run.
    """

    story_id: str
    event_type: EventType
    timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))
    project_key: str | None = None
    event_id: str | None = None
    source_component: str = "telemetry_service"
    severity: str = "info"
    phase: str | None = None
    flow_id: str | None = None
    node_id: str | None = None
    payload: dict[str, object] = field(default_factory=dict)
    run_id: str | None = None

    def to_dict(self) -> dict[str, object]:
        """Serialize the event to a plain dictionary for storage.

        Returns:
            Dictionary with all fields serialised to JSON-safe types.
        """
        return {
            "project_key": self.project_key,
            "story_id": self.story_id,
            "event_id": self.event_id,
            "event_type": self.event_type.value,
            "timestamp": self.timestamp.isoformat(),
            "source_component": self.source_component,
            "severity": self.severity,
            "phase": self.phase,
            "flow_id": self.flow_id,
            "node_id": self.node_id,
            "payload": self.payload,
            "run_id": self.run_id,
        }
