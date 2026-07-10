"""Mandatory payload field contract data (FK-61 §61.12.2, FK-25 §25.8).

Raw data sibling of ``agentkit.backend.telemetry.events`` — extracted to keep
``events.py`` well under the PY_MODULE_TOP_LEVEL_MAX_LOC_100 threshold.
Re-exported via ``agentkit.backend.telemetry.events`` so all existing imports remain
unchanged (``from agentkit.backend.telemetry.events import MANDATORY_PAYLOAD_FIELDS``).

No imports from ``agentkit.backend.telemetry.events`` here — that would cause a
circular import.  String wire-keys are used throughout (``EventType`` is a
``StrEnum`` so string keys ARE the canonical wire keys, ARCH-55).
``events.py`` wraps the raw mapping into ``Mapping[EventType, ...]`` on import.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Mapping


# ---------------------------------------------------------------------------
# Raw mandatory payload contracts keyed by canonical wire string
# (EventType wire values, ARCH-55 English-only). events.py wraps this into
# the typed Mapping[EventType, tuple[str, ...]] on import.
# ---------------------------------------------------------------------------
#
# ``ExecutionEventRecord.payload`` stays ``dict[str, object]`` (no per-type
# subclass explosion). The mandatory event-specific fields are pinned here as
# an explicit, typed contract so producers can be validated fail-closed at the
# write boundary. Only events with mandatory event-specific fields appear; an
# event absent from this map carries no mandatory payload fields.
#
# The field *names* are the canonical wire keys (ARCH-55, English-only). The
# concept-level value types (e.g. ``blocked_dimensions: list[IntegrityDimension]``,
# ``verdict: LlmEnvelopeStatus``) are documented in FK-61 §61.12.2 / FK-25 §25.8;
# this validator enforces field *presence* (FAIL-CLOSED), not cross-BC value
# typing, to keep the AC8 import boundary (telemetry imports no governance enum).
def _build_mandatory_payload_fields_raw() -> Mapping[str, tuple[str, ...]]:
    """Build the raw mandatory-payload contract mapping.

    The literal lives inside a function so the module top-level stays
    under PY_MODULE_TOP_LEVEL_MAX_LOC_100; the wire-key strings are the
    canonical EventType values (ARCH-55).
    """
    return {
        # FK-27 §27.4.3 — review-completion fact. ``guard.multi_llm`` Gate 2 counts
        # this per mandatory reviewer ``role`` (FK-37 §37.1.6), so ``role`` is the
        # load-bearing wire key and is mandatory (an unlabelled completion is
        # uncountable -> FAIL-CLOSED). Added by AG3-042, reconciled here.
        "llm_call_complete": ("role",),
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
        "integrity_violation": ("guard", "detail"),
        # ``review_response.verdict`` carries the LLM envelope status (PASS/REWORK/
        # FAIL, FK-61 §61.12.2). Presence is mandatory; value typing stays at the
        # producer (review_guard.py).
        "review_response": ("verdict",),
        # FK-34 §34.8.4 — review-pair divergence fact with optional quorum result.
        "review_divergence": (
            "story_id",
            "reviewer_a",
            "reviewer_b",
            "divergent",
            "quorum_triggered",
            "final_verdict",
        ),
        # FK-61 §61.12.1 — new event payloads
        "vectordb_search": (
            "total_hits",
            "hits_above_threshold",
            "hits_classified_conflict",
            "threshold_value",
        ),
        "compaction_event": ("story_id",),
        "impact_violation_check": (
            "declared_impact",
            "actual_impact",
            "result",
        ),
        "doc_fidelity_check": ("level", "result"),
        "conformance_assessment_started": (
            "assessment_id",
            "level",
            "story_id",
            "run_id",
        ),
        "conformance_level_evaluated": (
            "assessment_id",
            "level",
            "status",
            "reason",
        ),
        "conformance_assessment_completed": (
            "assessment_id",
            "level",
            "status",
            "references_used",
        ),
        # FK-25 §25.8 — exploration / mandate events
        "mandate_classification": (
            "escalation_class",
            "decision_summary",
            "story_id",
            "run_id",
        ),
        "fine_design_decision": (
            "decision_id",
            "question",
            "decision",
            "llm_responses",
            "normative_basis",
            "story_id",
        ),
        "scope_explosion_check": ("status", "indicators", "story_id"),
        "impact_exceedance_check": (
            "declared",
            "actual",
            "exceeded",
            "story_id",
        ),
        # FK-68 §68.2.2 (Z. 380-389) — BC14 Execution-Planning events. The mandatory
        # payload fields are the audit catalogue AG3-099 emits against; AG3-081 pins
        # them here (one mandatory set per event name, no second contract system).
        "dependency_recorded": ("story_id", "depends_on_id"),
        "story_ready": ("story_id",),
        "story_blocked": ("story_id", "reason"),
        "plan_revised": ("plan_id", "trigger"),
        "scheduling_decided": ("story_id", "wave_id", "decision"),
        "gate_resolved": ("gate_id", "result"),
        "rulebook_compiled": ("rulebook_id",),
        "wave_collapsed": ("wave_id", "story_count"),
        # FK-35 §35.3 / FK-91 Kapitel 35 — Governance-Observer events (AG3-085).
        # ``GOVERNANCE_SIGNAL`` is consumed-only by the observer (produced by
        # AG3-086 hook-sensors); its mandatory fields are pinned here so the
        # hook-sensor producer can validate against the same contract.
        "governance_signal": ("risk_points", "signal_type", "actor"),
        # The three observer-emitted events (FK-35 §35.3.7 / §35.3.6 / §35.3.8):
        "governance_adjudication": (
            "incident_type",
            "severity",
            "confidence",
            "recommended_action",
            "signal_type",
        ),
        "governance_incident_opened": ("risk_score", "event_count", "dominant_signals"),
        "governance_measure_applied": ("measure", "severity"),
        # FK-91 §91.1a / formal.operating-modes.events — ownership-transfer facts.
        "run_ownership_takeover_offered": (
            "challenge_id",
            "requesting_session_id",
        ),
        "run_ownership_takeover_approval_requested": (
            "approval_id",
            "requesting_session_id",
            "status",
            "reason",
        ),
        "session_run_binding_transferred": (
            "previous_owner_session_id",
            "new_owner_session_id",
            "ownership_epoch",
        ),
        "session_disowned": ("previous_owner_session_id", "reason"),
        "takeover_approval_changed": (
            "project_key",
            "story_id",
            "approval_id",
            "challenge_id",
            "approval",
        ),
        # FK-68 §68.2.2 (Z. 397-399) — BC15 ARE / Requirements events.
        "are_requirements_linked": ("story_id", "requirement_count"),
        "are_evidence_submitted": ("story_id", "evidence_type"),
        # ARE-payload conflict resolution (story §2.1.3 / AC2, Owner = telemetry BC):
        # FK-68 §68.2.2 is the canonical Single Source of Truth for ``are_gate_result``
        # (mandatory = ``story_id``, ``result``). The FK-61 §61.12.2 metric fields
        # ``covered``/``required``/``coverage_ratio`` stay ENRICHED but OPTIONAL (NOT
        # mandatory) — one mandatory set per event name, no second String-Map path.
        "are_gate_result": ("story_id", "result"),
        # Integration-stabilization contract events (FK-05 §5.14, AG3-069 AC11).
        # Wire keys + producers per formal-spec/integration-stabilization/events.md.
        # ``event_name`` is the canonical wire identifier on the payload; the other
        # mandatory keys carry the audit-load-bearing facts (manifest binding,
        # detected surface, exhausted caps, achieved targets). Every IS event is
        # emitted through the real EventEmitter at its boundary (FAIL-CLOSED).
        "integration_manifest_approved": (
            "event_name",
            "manifest_version",
            "manifest_hash",
        ),
        "undeclared_surface_detected": ("event_name", "surface_path"),
        "stabilization_budget_exhausted": ("event_name", "exhausted_caps"),
        "stability_gate_passed": ("event_name", "achieved_targets"),
    }


_MANDATORY_PAYLOAD_FIELDS_RAW: Mapping[str, tuple[str, ...]] = (
    _build_mandatory_payload_fields_raw()
)

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
