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
}

_EXPECTED_MANDATORY_FIELDS_BY_NAME: dict[str, tuple[str, ...]] = {
    "integrity_gate_result": ("blocked_dimensions",),
    "are_gate_result": ("covered", "required", "coverage_ratio"),
}


def test_mandatory_payload_fields_match_contract() -> None:
    assert dict(MANDATORY_PAYLOAD_FIELDS) == _EXPECTED_MANDATORY_FIELDS


def test_mandatory_payload_fields_by_name_match_contract() -> None:
    assert dict(MANDATORY_PAYLOAD_FIELDS_BY_NAME) == _EXPECTED_MANDATORY_FIELDS_BY_NAME
