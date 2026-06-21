"""Contract test: the four FK-25 §25.8 mandate telemetry events + their payloads.

Asserts each emitted event carries EXACTLY the AG3-037-pinned mandatory payload
fields (asserted against ``MANDATORY_PAYLOAD_FIELDS`` to avoid drift) and passes
``validate_event_payload`` fail-closed.
"""

from __future__ import annotations

from tests.exploration_change_frame_fixture import EXAMPLE_RUN_ID, example_change_frame

from agentkit.backend.exploration.change_frame import (
    AffectedBuildingBlocks,
    ContractChanges,
    OpenPoints,
)
from agentkit.backend.exploration.mandate.classification import MandateClassification
from agentkit.backend.exploration.mandate.fine_design import FineDesignDecision
from agentkit.backend.exploration.mandate.impact_checker import ImpactExceedanceChecker
from agentkit.backend.exploration.mandate.scope_detector import ScopeExplosionDetector
from agentkit.backend.exploration.mandate.telemetry import MandateTelemetry
from agentkit.backend.story_context_manager.story_model import ChangeImpact
from agentkit.backend.telemetry.emitters import MemoryEmitter
from agentkit.backend.telemetry.events import (
    MANDATORY_PAYLOAD_FIELDS,
    EventType,
    validate_event_payload,
)

_STORY_ID = "AG3-047"


def _classifier() -> MandateClassification:
    return MandateClassification(
        scope_detector=ScopeExplosionDetector(),
        impact_checker=ImpactExceedanceChecker(),
    )


def _exploding_frame() -> object:
    return example_change_frame(story_id=_STORY_ID).model_copy(
        update={
            "affected_building_blocks": AffectedBuildingBlocks(
                affected=[f"m{i}" for i in range(8)],
            ),
            "contract_changes": ContractChanges(
                interfaces=["a", "b"],
                data_model=["c", "d"],
                events=["e"],
                external_integrations=["f"],
            ),
            "open_points": OpenPoints(
                decided=[], assumptions=[], approval_needed=["open"]
            ),
        }
    )


def _assert_mandatory_fields(event_type: EventType, payload: dict[str, object]) -> None:
    """Every pinned mandatory field is present and validation passes."""
    for field_name in MANDATORY_PAYLOAD_FIELDS[event_type]:
        assert field_name in payload, f"{event_type.value} missing {field_name}"
    validate_event_payload(event_type, payload)


def test_classification_emits_three_events_with_pinned_payloads() -> None:
    """emit_classification fires mandate_classification + scope + impact events."""
    emitter = MemoryEmitter()
    telemetry = MandateTelemetry(emitter)
    result = _classifier().classify(_exploding_frame(), ChangeImpact.LOCAL)

    telemetry.emit_classification(result, story_id=_STORY_ID, run_id=EXAMPLE_RUN_ID)

    by_type = {e.event_type: e for e in emitter.all_events}
    assert set(by_type) == {
        EventType.MANDATE_CLASSIFICATION,
        EventType.SCOPE_EXPLOSION_CHECK,
        EventType.IMPACT_EXCEEDANCE_CHECK,
    }

    mc = by_type[EventType.MANDATE_CLASSIFICATION].payload
    _assert_mandatory_fields(EventType.MANDATE_CLASSIFICATION, mc)
    assert mc["escalation_class"] == "scope_explosion"
    assert mc["story_id"] == _STORY_ID
    assert mc["run_id"] == EXAMPLE_RUN_ID

    scope = by_type[EventType.SCOPE_EXPLOSION_CHECK].payload
    _assert_mandatory_fields(EventType.SCOPE_EXPLOSION_CHECK, scope)
    assert scope["status"] == "exploded"
    assert isinstance(scope["indicators"], list)

    impact = by_type[EventType.IMPACT_EXCEEDANCE_CHECK].payload
    _assert_mandatory_fields(EventType.IMPACT_EXCEEDANCE_CHECK, impact)
    assert impact["declared"] == ChangeImpact.LOCAL.value
    assert impact["exceeded"] is True


def test_fine_design_decision_event_payload() -> None:
    """emit_fine_design_decision pins the AG3-037 fine_design_decision fields."""
    emitter = MemoryEmitter()
    telemetry = MandateTelemetry(emitter)
    decision = FineDesignDecision(
        decision_id="FD-001",
        question="how to resolve the broker contract?",
        decision="single run_status key",
        rationale="consistent with state-management pattern",
        normative_basis=("FK-39",),
        llm_responses=("chatgpt position",),
    )

    telemetry.emit_fine_design_decision(
        decision, story_id=_STORY_ID, run_id=EXAMPLE_RUN_ID
    )

    event = emitter.all_events[0]
    assert event.event_type is EventType.FINE_DESIGN_DECISION
    _assert_mandatory_fields(EventType.FINE_DESIGN_DECISION, event.payload)
    assert event.payload["decision_id"] == "FD-001"
    assert event.payload["llm_responses"] == ["chatgpt position"]
    assert event.payload["normative_basis"] == ["FK-39"]


def test_no_extra_unpinned_drift_in_classification_payloads() -> None:
    """The classification payloads carry no fields beyond the pinned contract.

    Guards against silent payload drift: each event payload equals exactly its
    pinned mandatory field set (no stray keys).
    """
    emitter = MemoryEmitter()
    telemetry = MandateTelemetry(emitter)
    result = _classifier().classify(
        example_change_frame(story_id=_STORY_ID), ChangeImpact.ARCHITECTURE_IMPACT
    )

    telemetry.emit_classification(result, story_id=_STORY_ID, run_id=EXAMPLE_RUN_ID)

    for event in emitter.all_events:
        pinned = set(MANDATORY_PAYLOAD_FIELDS[event.event_type])
        assert set(event.payload) == pinned, (
            f"{event.event_type.value} payload {set(event.payload)} != {pinned}"
        )
