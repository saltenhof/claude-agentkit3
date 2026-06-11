"""Contract test: the EventType catalogue + mandatory payload fields (AG3-037).

Pins the full ``EventType`` wire-value catalogue and the mandatory payload
fields per event type (FK-61 §61.12 / FK-25 §25.8). Any change to the catalogue
or to a mandatory-field contract MUST be a deliberate edit reviewed against the
authoritative concepts — this test is the wire-contract guardrail.
"""

from __future__ import annotations

from agentkit.telemetry.events import (
    MANDATORY_PAYLOAD_FIELDS,
    MANDATORY_PAYLOAD_FIELDS_BY_NAME,
    EventType,
)

# ---------------------------------------------------------------------------
# Full EventType wire-value catalogue (canonical, English-only — ARCH-55)
# ---------------------------------------------------------------------------

_EXPECTED_EVENT_VALUES = {
    # Worker lifecycle
    "agent_start",
    "agent_end",
    "increment_commit",
    "drift_check",
    # Flow runtime
    "flow_start",
    "flow_end",
    "node_result",
    "override_applied",
    # Review / LLM
    "review_request",
    "review_response",
    "review_compliant",
    "review_guard_intervention",
    "llm_call",
    # ``llm_call_complete`` is the FK-27 §27.4.3 review-completion fact counted
    # by ``guard.multi_llm`` Gate 2 (added by AG3-042; reconciled into this
    # catalogue post-stash). Distinct from ``llm_call`` (the pool send).
    "llm_call_complete",
    # Adversarial
    "adversarial_start",
    "adversarial_sparring",
    "adversarial_test_created",
    "adversarial_test_executed",
    "adversarial_end",
    # Preflight / divergence
    "preflight_request",
    "preflight_response",
    "preflight_compliant",
    "review_divergence",
    # Governance / analytics
    "integrity_violation",
    "session_run_binding_created",
    "session_run_binding_removed",
    "story_execution_regime_activated",
    "story_execution_regime_deactivated",
    "story_exit_binding_revoked",
    "story_exit_completed",
    "binding_invalid_detected",
    "local_edge_bundle_materialized",
    "edge_operation_reconciled",
    "web_call",
    "impact_violation_check",
    "doc_fidelity_check",
    "vectordb_search",
    "compaction_event",
    "conformance_assessment_started",
    "conformance_level_evaluated",
    "conformance_assessment_completed",
    # Execution-Planning (BC14, FK-68 §68.2.2, AG3-081)
    "dependency_recorded",
    "story_ready",
    "story_blocked",
    "plan_revised",
    "scheduling_decided",
    "gate_resolved",
    "rulebook_compiled",
    "wave_collapsed",
    # ARE / Requirements (BC15, FK-68 §68.2.2, AG3-081)
    "are_requirements_linked",
    "are_evidence_submitted",
    "are_gate_result",
    # Exploration / mandate (FK-25 §25.8, AG3-037)
    "mandate_classification",
    "fine_design_decision",
    "scope_explosion_check",
    "impact_exceedance_check",
    # Preflight sentinel (FK-68 §68.9.2, AG3-037)
    "preflight_compliance_violation",
    # QA / general
    "artifact_invalidated",
    "error",
    "warning",
}


def test_event_type_catalogue_matches_contract() -> None:
    actual = {member.value for member in EventType}
    assert actual == _EXPECTED_EVENT_VALUES, (
        "EventType catalogue drifted from the AG3-037 contract.\n"
        f"Added (in code, not contract): {sorted(actual - _EXPECTED_EVENT_VALUES)}\n"
        f"Removed (in contract, not code): {sorted(_EXPECTED_EVENT_VALUES - actual)}"
    )


def test_ag3_037_new_event_types_present() -> None:
    for wire in (
        "vectordb_search",
        "compaction_event",
        "mandate_classification",
        "fine_design_decision",
        "scope_explosion_check",
        "impact_exceedance_check",
    ):
        assert wire in {member.value for member in EventType}


def test_impact_violation_and_exceedance_remain_distinct() -> None:
    values = {member.value for member in EventType}
    assert "impact_violation_check" in values
    assert "impact_exceedance_check" in values


# ---------------------------------------------------------------------------
# Mandatory payload fields per EventType (FK-61 §61.12.2 / FK-25 §25.8)
# ---------------------------------------------------------------------------

_EXPECTED_MANDATORY_FIELDS: dict[EventType, tuple[str, ...]] = {
    EventType.LLM_CALL_COMPLETE: ("role",),
    EventType.INTEGRITY_VIOLATION: ("stage",),
    EventType.REVIEW_RESPONSE: ("verdict",),
    EventType.REVIEW_DIVERGENCE: (
        "story_id",
        "reviewer_a",
        "reviewer_b",
        "divergent",
        "quorum_triggered",
        "final_verdict",
    ),
    EventType.VECTORDB_SEARCH: (
        "total_hits",
        "hits_above_threshold",
        "hits_classified_conflict",
        "threshold_value",
    ),
    EventType.COMPACTION_EVENT: ("story_id",),
    EventType.IMPACT_VIOLATION_CHECK: ("declared_impact", "actual_impact", "result"),
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
    EventType.IMPACT_EXCEEDANCE_CHECK: ("declared", "actual", "exceeded", "story_id"),
    # BC14 Execution-Planning (FK-68 §68.2.2, AG3-081)
    EventType.DEPENDENCY_RECORDED: ("story_id", "depends_on_id"),
    EventType.STORY_READY: ("story_id",),
    EventType.STORY_BLOCKED: ("story_id", "reason"),
    EventType.PLAN_REVISED: ("plan_id", "trigger"),
    EventType.SCHEDULING_DECIDED: ("story_id", "wave_id", "decision"),
    EventType.GATE_RESOLVED: ("gate_id", "result"),
    EventType.RULEBOOK_COMPILED: ("rulebook_id",),
    EventType.WAVE_COLLAPSED: ("wave_id", "story_count"),
    # BC15 ARE / Requirements (FK-68 §68.2.2, AG3-081). ``are_gate_result`` is now
    # a full enum member with the FK-68-canonical mandatory set (story §2.1.3).
    EventType.ARE_REQUIREMENTS_LINKED: ("story_id", "requirement_count"),
    EventType.ARE_EVIDENCE_SUBMITTED: ("story_id", "evidence_type"),
    EventType.ARE_GATE_RESULT: ("story_id", "result"),
}

# ``are_gate_result`` is intentionally absent: AG3-081 (§2.1.3) raised it to a
# full ``EventType`` member, so its single mandatory set lives in the enum-keyed
# contract above (FK-68 ``story_id``/``result``); the FK-61 metric fields stay
# optional/enriched. ``integrity_gate_result`` stays by-name (its producer lives
# in governance, not this BC's enum).
_EXPECTED_MANDATORY_FIELDS_BY_NAME: dict[str, tuple[str, ...]] = {
    "integrity_gate_result": ("blocked_dimensions",),
}


def test_mandatory_payload_fields_match_contract() -> None:
    assert dict(MANDATORY_PAYLOAD_FIELDS) == _EXPECTED_MANDATORY_FIELDS


def test_mandatory_payload_fields_by_name_match_contract() -> None:
    assert dict(MANDATORY_PAYLOAD_FIELDS_BY_NAME) == _EXPECTED_MANDATORY_FIELDS_BY_NAME
