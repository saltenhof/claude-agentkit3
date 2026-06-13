"""Telemetry event model -- immutable facts about what happened.

Events are facts, not commands (ARCH-41). All frozen (ARCH-29).
Domain terms explicitly modeled via EventType enum (ARCH-14).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Mapping


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
    #: Emitted by the double-role ``ReviewGuard`` when it denies an increment
    #: commit because a mandatory reviewer role is missing since the last commit
    #: (FK-68 §68.3.1 / AG3-036 §2.1.5).
    REVIEW_GUARD_INTERVENTION = "review_guard_intervention"
    LLM_CALL = "llm_call"
    #: Canonical "review completed" fact (FK-27 §27.4.3): emitted ONLY after the
    #: review artefact (§27.5.5) has been written successfully -- NOT on a bare
    #: API response. The ``guard.multi_llm`` Gate 2 counts this (per mandatory
    #: reviewer role) so it catches "review started, never completed"
    #: (FK-37 §37.1.6). Distinct from ``llm_call`` (which fires on the pool send).
    LLM_CALL_COMPLETE = "llm_call_complete"

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
    STORY_EXIT_BINDING_REVOKED = "story_exit_binding_revoked"
    STORY_EXIT_COMPLETED = "story_exit_completed"
    BINDING_INVALID_DETECTED = "binding_invalid_detected"
    LOCAL_EDGE_BUNDLE_MATERIALIZED = "local_edge_bundle_materialized"
    EDGE_OPERATION_RECONCILED = "edge_operation_reconciled"
    WEB_CALL = "web_call"
    IMPACT_VIOLATION_CHECK = "impact_violation_check"
    DOC_FIDELITY_CHECK = "doc_fidelity_check"
    VECTORDB_SEARCH = "vectordb_search"
    COMPACTION_EVENT = "compaction_event"
    CONFORMANCE_ASSESSMENT_STARTED = "conformance_assessment_started"
    CONFORMANCE_LEVEL_EVALUATED = "conformance_level_evaluated"
    CONFORMANCE_ASSESSMENT_COMPLETED = "conformance_assessment_completed"

    # Execution-Planning (BC14, FK-68 §68.2.2 Z. 380-389). AG3-081 owns the
    # catalogue values and their mandatory-payload contracts only; the domain
    # emitters live in the execution-planning BC (AG3-099) over the existing
    # generic emitter infrastructure.
    DEPENDENCY_RECORDED = "dependency_recorded"
    STORY_READY = "story_ready"
    STORY_BLOCKED = "story_blocked"
    PLAN_REVISED = "plan_revised"
    SCHEDULING_DECIDED = "scheduling_decided"
    GATE_RESOLVED = "gate_resolved"
    RULEBOOK_COMPILED = "rulebook_compiled"
    WAVE_COLLAPSED = "wave_collapsed"

    # ARE / Requirements (BC15, FK-68 §68.2.2 Z. 397-399). AG3-081 owns the
    # catalogue values and their mandatory-payload contracts; the domain
    # ARE emitters live in the requirements BC. ``are_gate_result`` is raised
    # here from a payload-pinning-only contract to a full enum member.
    ARE_REQUIREMENTS_LINKED = "are_requirements_linked"
    ARE_EVIDENCE_SUBMITTED = "are_evidence_submitted"
    ARE_GATE_RESULT = "are_gate_result"

    # Exploration / mandate (FK-25 §25.8). The active emitters live in the
    # exploration-and-design BC (e.g. AG3-046); this BC owns the catalogue
    # values and their mandatory-payload contracts only.
    MANDATE_CLASSIFICATION = "mandate_classification"
    FINE_DESIGN_DECISION = "fine_design_decision"
    SCOPE_EXPLOSION_CHECK = "scope_explosion_check"
    #: Impact-exceedance comparison (FK-25 §25.7). Distinct from the structural
    #: ``IMPACT_VIOLATION_CHECK`` (FK-33/FK-61 §61.4.2): the latter compares
    #: declared vs. actual impact in the QA structural layer, this one is the
    #: exploration-phase class-4 mandate exceedance check.
    IMPACT_EXCEEDANCE_CHECK = "impact_exceedance_check"

    # Governance observation (FK-35 §35.3, FK-91 Kapitel 35). AG3-085 owns the
    # catalogue values and their mandatory-payload contracts; the emitters live in
    # the governance-observer BC (``agentkit.governance.governance_observer``).
    # ``GOVERNANCE_SIGNAL`` is consumed (not produced) by the observer — produced
    # by hook-sensor AG3-086. The other three are emitted by the observer.
    #
    # Mandatory payload contracts (FK-35 §35.3.7 / §35.3.6 / §35.3.8):
    # - GOVERNANCE_SIGNAL:        risk_points (int), signal_type (str), actor (str)
    # - GOVERNANCE_ADJUDICATION:  incident_type, severity, confidence,
    #                             recommended_action, signal_type
    # - GOVERNANCE_INCIDENT_OPENED: risk_score (int), event_count (int),
    #                             dominant_signals (list)
    # - GOVERNANCE_MEASURE_APPLIED: measure (str), severity (str)
    GOVERNANCE_SIGNAL = "governance_signal"
    GOVERNANCE_ADJUDICATION = "governance_adjudication"
    GOVERNANCE_INCIDENT_OPENED = "governance_incident_opened"
    GOVERNANCE_MEASURE_APPLIED = "governance_measure_applied"

    # Governance risk window (FK-68 §68.9.2 preflight sentinel). Emitted by the
    # preflight sentinel when the preflight stream is unbalanced.
    PREFLIGHT_COMPLIANCE_VIOLATION = "preflight_compliance_violation"
    #: A cycle-bound QA artefact was invalidated (moved to ``stale/``) when a
    #: new atomic QA cycle began (FK-27 §27.2.3 / AG3-041 §2.1.3).
    ARTIFACT_INVALIDATED = "artifact_invalidated"

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


# ---------------------------------------------------------------------------
# Mandatory payload contracts per EventType (FK-61 §61.12.2, FK-25 §25.8)
# ---------------------------------------------------------------------------
#
# ``ExecutionEventRecord.payload`` stays ``dict[str, object]`` (no per-type
# subclass explosion). The mandatory event-specific fields are pinned here as an
# explicit, typed contract so producers can be validated fail-closed at the
# write boundary. Only events with mandatory event-specific fields appear; an
# event absent from this map carries no mandatory payload fields.
#
# The field *names* are the canonical wire keys (ARCH-55, English-only). The
# concept-level value types (e.g. ``blocked_dimensions: list[IntegrityDimension]``,
# ``verdict: LlmEnvelopeStatus``) are documented in FK-61 §61.12.2 / FK-25 §25.8;
# this validator enforces field *presence* (FAIL-CLOSED), not cross-BC value
# typing, to keep the AC8 import boundary (telemetry imports no governance enum).

MANDATORY_PAYLOAD_FIELDS: Mapping[EventType, tuple[str, ...]] = {
    # FK-27 §27.4.3 — review-completion fact. ``guard.multi_llm`` Gate 2 counts
    # this per mandatory reviewer ``role`` (FK-37 §37.1.6), so ``role`` is the
    # load-bearing wire key and is mandatory (an unlabelled completion is
    # uncountable -> FAIL-CLOSED). Added by AG3-042, reconciled here.
    EventType.LLM_CALL_COMPLETE: ("role",),
    # FK-68 §68.2 / §68.3.1 — every guard-hook block (exit 2) emits an
    # ``integrity_violation`` carrying ``guard`` (the emitting guard) and
    # ``detail`` (the block reason). These two are mandatory for EVERY
    # ``integrity_violation`` (FK-30 §30.7.3). The ``stage`` field is
    # prompt-integrity-specific (FK-61 §61.12.2 "for prompt_integrity_guard")
    # and is enforced CONDITIONALLY (only for ``guard="prompt_integrity_guard"``)
    # by :func:`validate_event_payload` — see ``INTEGRITY_VIOLATION_PROMPT_GUARD``
    # and ``INTEGRITY_VIOLATION_STAGES`` below. AG3-086 introduced the first
    # non-prompt-integrity emitters (``skill_usage_check``,
    # ``web_call_budget_guard``) which write NO ``stage``; the canonical
    # mandatory-payload contract owner is AG3-081 (this change is producer-driven
    # and coordinated via ``depends_on: AG3-081``).
    EventType.INTEGRITY_VIOLATION: ("guard", "detail"),
    # ``review_response.verdict`` carries the LLM envelope status (PASS/REWORK/
    # FAIL, FK-61 §61.12.2). Presence is mandatory; value typing stays at the
    # producer (review_guard.py).
    EventType.REVIEW_RESPONSE: ("verdict",),
    # FK-34 §34.8.4 — review-pair divergence fact with optional quorum result.
    EventType.REVIEW_DIVERGENCE: (
        "story_id",
        "reviewer_a",
        "reviewer_b",
        "divergent",
        "quorum_triggered",
        "final_verdict",
    ),
    # FK-61 §61.12.1 — new event payloads
    EventType.VECTORDB_SEARCH: (
        "total_hits",
        "hits_above_threshold",
        "hits_classified_conflict",
        "threshold_value",
    ),
    EventType.COMPACTION_EVENT: ("story_id",),
    EventType.IMPACT_VIOLATION_CHECK: (
        "declared_impact",
        "actual_impact",
        "result",
    ),
    EventType.DOC_FIDELITY_CHECK: ("level", "result"),
    EventType.CONFORMANCE_ASSESSMENT_STARTED: (
        "assessment_id",
        "level",
        "story_id",
        "run_id",
    ),
    EventType.CONFORMANCE_LEVEL_EVALUATED: (
        "assessment_id",
        "level",
        "status",
        "reason",
    ),
    EventType.CONFORMANCE_ASSESSMENT_COMPLETED: (
        "assessment_id",
        "level",
        "status",
        "references_used",
    ),
    # FK-25 §25.8 — exploration / mandate events
    EventType.MANDATE_CLASSIFICATION: (
        "escalation_class",
        "decision_summary",
        "story_id",
        "run_id",
    ),
    EventType.FINE_DESIGN_DECISION: (
        "decision_id",
        "question",
        "decision",
        "llm_responses",
        "normative_basis",
        "story_id",
    ),
    EventType.SCOPE_EXPLOSION_CHECK: ("status", "indicators", "story_id"),
    EventType.IMPACT_EXCEEDANCE_CHECK: (
        "declared",
        "actual",
        "exceeded",
        "story_id",
    ),
    # FK-68 §68.2.2 (Z. 380-389) — BC14 Execution-Planning events. The mandatory
    # payload fields are the audit catalogue AG3-099 emits against; AG3-081 pins
    # them here (one mandatory set per event name, no second contract system).
    EventType.DEPENDENCY_RECORDED: ("story_id", "depends_on_id"),
    EventType.STORY_READY: ("story_id",),
    EventType.STORY_BLOCKED: ("story_id", "reason"),
    EventType.PLAN_REVISED: ("plan_id", "trigger"),
    EventType.SCHEDULING_DECIDED: ("story_id", "wave_id", "decision"),
    EventType.GATE_RESOLVED: ("gate_id", "result"),
    EventType.RULEBOOK_COMPILED: ("rulebook_id",),
    EventType.WAVE_COLLAPSED: ("wave_id", "story_count"),
    # FK-35 §35.3 / FK-91 Kapitel 35 — Governance-Observer events (AG3-085).
    # ``GOVERNANCE_SIGNAL`` is consumed-only by the observer (produced by
    # AG3-086 hook-sensors); its mandatory fields are pinned here so the
    # hook-sensor producer can validate against the same contract.
    EventType.GOVERNANCE_SIGNAL: ("risk_points", "signal_type", "actor"),
    # The three observer-emitted events (FK-35 §35.3.7 / §35.3.6 / §35.3.8):
    EventType.GOVERNANCE_ADJUDICATION: (
        "incident_type",
        "severity",
        "confidence",
        "recommended_action",
        "signal_type",
    ),
    EventType.GOVERNANCE_INCIDENT_OPENED: (
        "risk_score",
        "event_count",
        "dominant_signals",
    ),
    EventType.GOVERNANCE_MEASURE_APPLIED: ("measure", "severity"),
    # FK-68 §68.2.2 (Z. 397-399) — BC15 ARE / Requirements events.
    EventType.ARE_REQUIREMENTS_LINKED: ("story_id", "requirement_count"),
    EventType.ARE_EVIDENCE_SUBMITTED: ("story_id", "evidence_type"),
    # ARE-payload conflict resolution (story §2.1.3 / AC2, Owner = telemetry BC):
    # FK-68 §68.2.2 is the canonical Single Source of Truth for ``are_gate_result``
    # (mandatory = ``story_id``, ``result``). The FK-61 §61.12.2 metric fields
    # ``covered``/``required``/``coverage_ratio`` stay ENRICHED but OPTIONAL (NOT
    # mandatory) — one mandatory set per event name, no second String-Map path.
    EventType.ARE_GATE_RESULT: ("story_id", "result"),
}

# ``integrity_gate_result`` is documented in FK-61 §61.12.2 with an enriched
# payload but is not a member of this BC's ``EventType`` catalogue (its producer
# lives in governance). Its mandatory fields are pinned by string key so
# ``validate_event_payload`` can be called for it from its owning producer
# without importing this BC's enum being a prerequisite.
#
# ``are_gate_result`` was previously pinned here (payload-pinning only); AG3-081
# raises it to a full ``EventType`` member (see ``MANDATORY_PAYLOAD_FIELDS``
# above). Per the §2.1.3 owner decision its mandatory set is FK-68's
# ``story_id``/``result`` (the FK-61 metric fields stay optional/enriched), so it
# is intentionally NO LONGER in this by-name map — exactly ONE mandatory set per
# event name lives at the enum-keyed contract.
MANDATORY_PAYLOAD_FIELDS_BY_NAME: Mapping[str, tuple[str, ...]] = {
    "integrity_gate_result": ("blocked_dimensions",),
}

# ---------------------------------------------------------------------------
# Conditional ``integrity_violation`` payload contract (FK-61 §61.12.2 / FK-68
# §68.2). ``stage`` is NOT unconditionally mandatory for every
# ``integrity_violation`` (that would reject the AG3-086 non-prompt-integrity
# emitters ``skill_usage_check`` / ``web_call_budget_guard`` fail-closed). It is
# valid and mandatory ONLY for the prompt-integrity guard, where it identifies
# the failing check stage (FK-31 §31.7.2). For every other emitting guard a
# ``stage`` is rejected as an invalid field for that producer.

#: The ``guard`` value that owns the prompt-integrity ``stage`` field.
INTEGRITY_VIOLATION_PROMPT_GUARD: str = "prompt_integrity_guard"

#: The valid ``stage`` values for a ``prompt_integrity_guard``
#: ``integrity_violation`` — one per check stage (FK-31 §31.7.2).
INTEGRITY_VIOLATION_STAGES: frozenset[str] = frozenset(
    {"escape_detection", "schema_validation", "template_integrity"}
)


class EventPayloadContractError(ValueError):
    """Raised when an event payload is missing a mandatory field (FAIL-CLOSED).

    FK-61 §61.12.2 / FK-25 §25.8 pin mandatory event-specific fields per event
    type. A producer that omits one is a programming/contract error and must
    fail closed rather than persist an under-specified event.

    Args:
        event_type: The event type (canonical wire string) being validated.
        missing: The mandatory field names that were absent (or, for a
            conditionally-invalid field, the offending field name).
        detail: Optional override message describing a conditional-field
            violation (e.g. an invalid or forbidden ``stage`` value). When
            ``None`` the default "missing mandatory field" message is used.
    """

    def __init__(
        self,
        event_type: str,
        missing: tuple[str, ...],
        *,
        detail: str | None = None,
    ) -> None:
        if detail is None:
            message = (
                f"Event {event_type!r} is missing mandatory payload field(s): "
                f"{', '.join(missing)}. FAIL-CLOSED: every mandatory field per "
                "EventType must be present (FK-61 §61.12.2 / FK-25 §25.8)."
            )
        else:
            message = (
                f"Event {event_type!r} payload contract violation: {detail}. "
                "FAIL-CLOSED."
            )
        super().__init__(message)
        self.event_type = event_type
        self.missing = missing


def validate_event_payload(
    event_type: EventType | str,
    payload: Mapping[str, object],
) -> None:
    """Validate that ``payload`` carries every mandatory field for ``event_type``.

    FAIL-CLOSED contract enforcement (story §2.1.4 / AC4): a missing mandatory
    field raises :class:`EventPayloadContractError`. Event types without
    mandatory event-specific fields validate trivially (no-op).

    Args:
        event_type: The event type to validate against. Accepts the
            ``EventType`` enum or the canonical wire string (so producers of
            cross-BC events such as ``integrity_gate_result`` / ``are_gate_result``
            can validate without importing this BC's enum).
        payload: The event payload to check for mandatory fields.

    Raises:
        EventPayloadContractError: If any mandatory field is absent.
    """
    required: tuple[str, ...]
    wire_value: str
    if isinstance(event_type, EventType):
        wire_value = event_type.value
        required = MANDATORY_PAYLOAD_FIELDS.get(event_type, ())
    else:
        wire_value = event_type
        # A wire string may match a catalogue member or a by-name-only contract.
        try:
            required = MANDATORY_PAYLOAD_FIELDS.get(EventType(event_type), ())
        except ValueError:
            required = MANDATORY_PAYLOAD_FIELDS_BY_NAME.get(event_type, ())
    if not required:
        required = MANDATORY_PAYLOAD_FIELDS_BY_NAME.get(wire_value, required)

    missing = tuple(field_name for field_name in required if field_name not in payload)
    if missing:
        raise EventPayloadContractError(wire_value, missing)

    if wire_value == EventType.INTEGRITY_VIOLATION.value:
        _validate_integrity_violation_stage(payload)


def _validate_integrity_violation_stage(payload: Mapping[str, object]) -> None:
    """Enforce the conditional ``stage`` contract on an ``integrity_violation``.

    FK-61 §61.12.2 / FK-68 §68.2: ``stage`` is valid and mandatory ONLY for the
    prompt-integrity guard (``guard="prompt_integrity_guard"``), where it names
    the failing check stage (one of :data:`INTEGRITY_VIOLATION_STAGES`). For any
    other emitting guard a ``stage`` is rejected as an invalid field for that
    producer (FAIL-CLOSED — a mislabelled stage is a contract error, not a
    silently-tolerated extra field).

    Args:
        payload: The ``integrity_violation`` payload (``guard``/``detail`` are
            already presence-checked by the caller).

    Raises:
        EventPayloadContractError: When the prompt-integrity guard omits or
            mis-values ``stage``, or when a non-prompt-integrity guard carries a
            ``stage`` field at all.
    """
    guard = payload.get("guard")
    has_stage = "stage" in payload
    if guard == INTEGRITY_VIOLATION_PROMPT_GUARD:
        if not has_stage:
            raise EventPayloadContractError(
                EventType.INTEGRITY_VIOLATION.value, ("stage",)
            )
        stage = payload.get("stage")
        if stage not in INTEGRITY_VIOLATION_STAGES:
            raise EventPayloadContractError(
                EventType.INTEGRITY_VIOLATION.value,
                ("stage",),
                detail=(
                    f"prompt_integrity_guard 'stage'={stage!r} is not one of "
                    f"{sorted(INTEGRITY_VIOLATION_STAGES)} (FK-31 §31.7.2)"
                ),
            )
    elif has_stage:
        # ``stage`` is prompt-integrity-specific; a non-prompt-integrity guard
        # that carries one is mislabelled (FK-61 §61.12.2). Reject fail-closed.
        raise EventPayloadContractError(
            EventType.INTEGRITY_VIOLATION.value,
            ("stage",),
            detail=(
                f"'stage' is prompt_integrity_guard-specific but guard={guard!r} "
                "carried it (FK-61 §61.12.2 / FK-68 §68.2)"
            ),
        )
