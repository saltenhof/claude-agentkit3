"""Unit tests for the ChangeFrame model and its sub-models (AG3-045 AC3).

Covers the seven FK-23 §23.4.1 mandatory parts (English wire keys, ARCH-55),
the lifecycle defaults (FK-25 §25.4.2), the mandatory ``created_at`` field
(§23.4.2) and adversarial inputs (empty / whitespace / naive datetime / empty
required collections) -- fail-closed at the model boundary.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest
from pydantic import ValidationError

from agentkit.backend.exploration.change_frame import (
    CHANGE_FRAME_SCHEMA_VERSION,
    SEVEN_PARTS,
    AffectedBuildingBlocks,
    ChangeFrame,
    ConformanceStatement,
    ContractChanges,
    GoalAndScope,
    OpenPoints,
    SolutionDirection,
    VerificationSketch,
)

_TS = datetime(2026, 6, 5, 10, 30, tzinfo=UTC)
#: FK-02 §2.3.1: ``run_id`` is a UUID. Pinned stable UUID for the happy-path.
_RUN_ID = "11111111-1111-4111-8111-111111111111"


def _valid_parts() -> dict[str, Any]:
    return {
        "goal_and_scope": GoalAndScope(
            changes="Integrate the broker API for real-time prices.",
            does_not_change="Existing historical REST API stays unchanged.",
        ),
        "affected_building_blocks": AffectedBuildingBlocks(
            affected=["trading-engine/broker-client"],
            untouched=["reporting-service"],
        ),
        "solution_direction": SolutionDirection(
            pattern="Adapter pattern for broker integration.",
            anchoring="New BrokerAdapter in the trading-engine module.",
            rationale="Smallest fitting solution: only the data interface is "
            "abstracted.",
        ),
        "contract_changes": ContractChanges(
            interfaces=["New WebSocket endpoint /ws/market-data"],
        ),
        "conformance_statement": ConformanceStatement(
            reference_documents=["concepts/trading-architecture.md"],
            conformant=["WebSocket endpoint follows the API guidelines."],
        ),
        "verification_sketch": VerificationSketch(
            unit="BrokerAdapter logic, MarketQuote mapping.",
        ),
        "open_points": OpenPoints(
            decided=[],
            assumptions=["Broker API supports WebSocket streaming."],
            approval_needed=[],
        ),
    }


def _valid_kwargs() -> dict[str, Any]:
    return {
        "story_id": "AG3-045",
        "run_id": _RUN_ID,
        "created_at": _TS,
        **_valid_parts(),
    }


def test_happy_path_constructs_with_lifecycle_defaults() -> None:
    frame = ChangeFrame(**_valid_kwargs())
    assert frame.schema_version == CHANGE_FRAME_SCHEMA_VERSION
    assert frame.frozen is False
    assert frame.frozen_at is None
    assert frame.story_id == "AG3-045"


@pytest.mark.parametrize("missing", SEVEN_PARTS)
def test_each_mandatory_part_is_required(missing: str) -> None:
    kwargs = _valid_kwargs()
    del kwargs[missing]
    with pytest.raises(ValidationError):
        ChangeFrame(**kwargs)


def test_created_at_is_mandatory() -> None:
    kwargs = _valid_kwargs()
    del kwargs["created_at"]
    with pytest.raises(ValidationError):
        ChangeFrame(**kwargs)


@pytest.mark.parametrize("field", ["story_id", "run_id"])
@pytest.mark.parametrize("bad", ["", "   ", "\n\t"])
def test_identity_fields_reject_empty_and_whitespace(field: str, bad: str) -> None:
    kwargs = _valid_kwargs()
    kwargs[field] = bad
    with pytest.raises(ValidationError):
        ChangeFrame(**kwargs)


@pytest.mark.parametrize(
    "bad_story_id",
    [
        "ag3-045",
        "AG3045",
        "AG3-",
        "-045",
        "foo",
        "AG3-04a",
        # Anchored \A...\Z + fullmatch (shared SSOT) rejects trailing/embedded
        # newlines, surrounding whitespace and control chars that a ^...$ +
        # .match() would have tolerated (latent bug):
        "AG3-045\n",
        "AG3-\n045",
        "\nAG3-045",
        " AG3-045",
        "AG3-045 ",
        "AG3-045\x00",
        "AG3-\x07045",
    ],
)
def test_story_id_must_match_display_id_pattern(bad_story_id: str) -> None:
    # FK-23 §23.4.2 / FK-02 §2.3.1: story_id must be a story display id, not just
    # any non-blank string. A malformed id is rejected fail-closed.
    kwargs = _valid_kwargs()
    kwargs["story_id"] = bad_story_id
    with pytest.raises(ValidationError):
        ChangeFrame(**kwargs)


@pytest.mark.parametrize(
    "bad_run_id",
    ["run-1", "not-a-uuid", "1234", "11111111-1111-1111-1111"],
)
def test_run_id_must_be_uuid(bad_run_id: str) -> None:
    # FK-23 §23.4.2 / FK-02 §2.3.1: run_id is the setup-minted UUID. A non-UUID
    # value is rejected fail-closed.
    kwargs = _valid_kwargs()
    kwargs["run_id"] = bad_run_id
    with pytest.raises(ValidationError):
        ChangeFrame(**kwargs)


def test_naive_timestamp_rejected() -> None:
    kwargs = _valid_kwargs()
    # Intentional naive datetime to exercise the tz-aware validator.
    kwargs["created_at"] = datetime(2026, 6, 5, 10, 30)  # noqa: DTZ001
    with pytest.raises(ValidationError):
        ChangeFrame(**kwargs)


def test_schema_version_is_fixed() -> None:
    kwargs = _valid_kwargs()
    kwargs["schema_version"] = "2.0"
    with pytest.raises(ValidationError):
        ChangeFrame(**kwargs)


def test_frozen_at_without_frozen_flag_is_accepted() -> None:
    # FK-23 §23.4 does NOT mandate a frozen/frozen_at consistency invariant.
    # AG3-045 deliberately does not enforce one; freeze logic is AG3-047's owner.
    kwargs = _valid_kwargs()
    kwargs["frozen_at"] = _TS  # frozen still False
    frame = ChangeFrame(**kwargs)
    assert frame.frozen is False
    assert frame.frozen_at == _TS


def test_frozen_flag_without_frozen_at_is_accepted() -> None:
    # frozen_at stays optional even when frozen is True (FK-23 §23.4 mandates no
    # invariant; setting frozen_at is AG3-047 freeze logic, not this BC).
    kwargs = _valid_kwargs()
    kwargs["frozen"] = True  # no frozen_at
    frame = ChangeFrame(**kwargs)
    assert frame.frozen is True
    assert frame.frozen_at is None


def test_frozen_consistent_pair_is_accepted() -> None:
    kwargs = _valid_kwargs()
    kwargs["frozen"] = True
    kwargs["frozen_at"] = _TS
    frame = ChangeFrame(**kwargs)
    assert frame.frozen is True
    assert frame.frozen_at == _TS


def test_change_frame_is_immutable() -> None:
    frame = ChangeFrame(**_valid_kwargs())
    with pytest.raises(ValidationError):
        frame.frozen = True  # type: ignore[misc]


# --- Part-level fail-closed validation -------------------------------------


def test_goal_and_scope_rejects_blank() -> None:
    with pytest.raises(ValidationError):
        GoalAndScope(changes="  ", does_not_change="x")
    with pytest.raises(ValidationError):
        GoalAndScope(changes="x", does_not_change="")


def test_affected_building_blocks_requires_one_affected() -> None:
    with pytest.raises(ValidationError):
        AffectedBuildingBlocks(affected=[])
    with pytest.raises(ValidationError):
        AffectedBuildingBlocks(affected=["  "])


def test_solution_direction_requires_all_three_non_blank() -> None:
    with pytest.raises(ValidationError):
        SolutionDirection(pattern="p", anchoring="a", rationale="  ")


def test_contract_changes_requires_at_least_one_array() -> None:
    with pytest.raises(ValidationError):
        ContractChanges()
    # A single non-empty array is enough.
    assert ContractChanges(events=["MarketDataReceived"]).events == [
        "MarketDataReceived"
    ]


def test_conformance_statement_requires_one_reference() -> None:
    with pytest.raises(ValidationError):
        ConformanceStatement(reference_documents=[])


def test_verification_sketch_requires_at_least_one_level() -> None:
    with pytest.raises(ValidationError):
        VerificationSketch()
    with pytest.raises(ValidationError):
        VerificationSketch(unit="  ")
    assert VerificationSketch(e2e="full flow").e2e == "full flow"


def test_open_points_arrays_required_and_may_be_empty() -> None:
    # FK-23 §23.4.2: the three sub-arrays must be PRESENT (may be empty).
    points = OpenPoints(decided=[], assumptions=[], approval_needed=[])
    assert points.decided == []
    assert points.assumptions == []
    assert points.approval_needed == []
    with pytest.raises(ValidationError):
        OpenPoints(decided=["  "], assumptions=[], approval_needed=[])


@pytest.mark.parametrize("missing", ["decided", "assumptions", "approval_needed"])
def test_open_points_missing_subarray_rejected(missing: str) -> None:
    # FK-23 §23.4.2: a missing sub-array key is a schema violation (no default).
    kwargs: dict[str, Any] = {
        "decided": [],
        "assumptions": [],
        "approval_needed": [],
    }
    del kwargs[missing]
    with pytest.raises(ValidationError):
        OpenPoints(**kwargs)


def test_from_payload_round_trips_and_validates() -> None:
    frame = ChangeFrame(**_valid_kwargs())
    dumped = frame.model_dump(mode="json")
    assert dumped["story_id"] == "AG3-045"
    assert set(SEVEN_PARTS).issubset(dumped.keys())
    restored = ChangeFrame.from_payload(dumped)
    assert restored == frame


def test_from_payload_rejects_non_mapping() -> None:
    with pytest.raises(TypeError):
        ChangeFrame.from_payload(["not", "a", "mapping"])


def test_from_payload_fails_closed_on_corrupt_payload() -> None:
    corrupt = ChangeFrame(**_valid_kwargs()).model_dump(mode="json")
    del corrupt["goal_and_scope"]  # drop a mandatory part
    with pytest.raises(ValidationError):
        ChangeFrame.from_payload(corrupt)


# -- AG3-097: optional 8th component fine_design_decisions (AK9 / AK10) -----
def test_fine_design_decisions_defaults_empty() -> None:
    """The optional 8th component defaults to an empty tuple (AK9)."""
    frame = ChangeFrame(**_valid_kwargs())
    assert frame.fine_design_decisions == ()


def test_fine_design_decisions_carries_decisions_and_serializes() -> None:
    """The 8th field carries FineDesignDecision items + serializes (AK9)."""
    from agentkit.backend.exploration.mandate.fine_design import FineDesignDecision

    decision = FineDesignDecision(
        decision_id="FD-001",
        question="single or split run_status key?",
        decision="single run_status key",
        rationale="consistent with the state model",
        normative_basis=("FK-39", "FK-26 §26.2"),
        llm_responses=("chatgpt: single", "qwen: single"),
    )
    frame = ChangeFrame(**_valid_kwargs(), fine_design_decisions=(decision,))

    dumped = frame.model_dump(mode="json")
    assert "fine_design_decisions" in dumped  # English wire-key (ARCH-55)
    assert dumped["fine_design_decisions"][0]["decision_id"] == "FD-001"
    restored = ChangeFrame.from_payload(dumped)
    assert restored == frame
    assert restored.fine_design_decisions[0].decision == "single run_status key"


def test_fine_design_decisions_english_wire_key_only() -> None:
    """ARCH-55: the German FK concept-name is NOT a code key (AK10)."""
    dumped = ChangeFrame(**_valid_kwargs()).model_dump(mode="json")
    assert "fine_design_decisions" in dumped
    assert "feindesign_entscheidungen" not in dumped


def test_freeze_behavior_unchanged_with_eighth_field() -> None:
    """The 8th field does not change the freeze behavior (AK9, AG3-047 owns it).

    frozen_at stays optional even when frozen is True (no new consistency
    invariant), and the model stays frozen=True (immutable).
    """
    frame = ChangeFrame(**_valid_kwargs(), frozen=True)
    assert frame.frozen is True
    assert frame.frozen_at is None  # no invariant forcing frozen_at
    with pytest.raises(ValidationError):
        frame.fine_design_decisions = ()  # type: ignore[misc]
