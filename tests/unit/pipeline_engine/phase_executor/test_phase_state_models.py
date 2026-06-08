"""AG3-059 tests for FK-39 phase-state ownership and field set."""

from __future__ import annotations

import ast
from dataclasses import FrozenInstanceError, is_dataclass
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path

import pytest
from pydantic import ValidationError

from agentkit.core_types import PauseReason
from agentkit.pipeline_engine.phase_envelope.envelope import PhaseEnvelope
from agentkit.pipeline_engine.phase_envelope.runtime import PhaseOrigin, RuntimeMetadata
from agentkit.pipeline_engine.phase_executor import (
    EscalationReason,
    PhaseName,
    PhaseState,
    PhaseStateMode,
    PhaseStateProducer,
    PhaseStatus,
)
from agentkit.story_context_manager.types import StoryType


def _state_data(**overrides: object) -> dict[str, object]:
    now = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
    data: dict[str, object] = {
        "schema_version": "4.0",
        "story_id": "AG3-059",
        "run_id": "22222222-2222-4222-8222-222222222222",
        "phase": PhaseName.IMPLEMENTATION,
        "status": PhaseStatus.IN_PROGRESS,
        "mode": PhaseStateMode.EXPLORATION,
        "story_type": StoryType.IMPLEMENTATION,
        "attempt": 1,
        "started_at": now,
        "phase_entered_at": now,
        "pause_reason": None,
        "escalation_reason": None,
        "warnings": [],
        "producer": PhaseStateProducer(type="test", name="ag3-059"),
    }
    data.update(overrides)
    return data


def test_phase_state_core_required_field_set() -> None:
    expected = {
        "schema_version",
        "story_id",
        "run_id",
        "phase",
        "status",
        "mode",
        "story_type",
        "attempt",
        "started_at",
        "phase_entered_at",
        "pause_reason",
        "escalation_reason",
        "warnings",
        "producer",
    }
    assert expected <= set(PhaseState.model_fields)
    assert {name for name in expected if PhaseState.model_fields[name].is_required()} == expected


def test_invalid_schema_version_rejected() -> None:
    with pytest.raises(ValidationError):
        PhaseState(**_state_data(schema_version="3.0"))


def test_phase_is_phase_name_enum_and_invalid_phase_rejected() -> None:
    state = PhaseState(**_state_data(phase=PhaseName.SETUP))
    assert state.phase is PhaseName.SETUP

    with pytest.raises(ValidationError):
        PhaseState(**_state_data(phase="verify"))


def test_pause_reason_wire_key_roundtrip_uses_uppercase_enum_value() -> None:
    state = PhaseState(
        **_state_data(
            status=PhaseStatus.PAUSED,
            pause_reason=PauseReason.AWAITING_DESIGN_REVIEW,
        )
    )
    wire = state.model_dump(mode="json")
    assert wire["pause_reason"] == "AWAITING_DESIGN_REVIEW"
    assert "paused_reason" not in wire

    restored = PhaseState.model_validate(wire)
    assert restored.pause_reason is PauseReason.AWAITING_DESIGN_REVIEW


def test_runtime_metadata_and_envelope_are_frozen_dataclasses() -> None:
    runtime = RuntimeMetadata(origin=PhaseOrigin.LOADED)
    state = PhaseState(**_state_data())
    envelope = PhaseEnvelope(state=state, runtime=runtime)

    assert is_dataclass(runtime)
    assert is_dataclass(envelope)
    with pytest.raises(FrozenInstanceError):
        runtime.origin = PhaseOrigin.NEW  # type: ignore[misc]
    with pytest.raises(FrozenInstanceError):
        envelope.state = state  # type: ignore[misc]
    with pytest.raises(TypeError):
        RuntimeMetadata(origin=PhaseOrigin.NEW, loaded_at=datetime.now(tz=UTC))  # type: ignore[call-arg]


@pytest.mark.parametrize(
    "overrides",
    [
        {"status": PhaseStatus.IN_PROGRESS, "pause_reason": PauseReason.GOVERNANCE_INCIDENT},
        {
            "status": PhaseStatus.FAILED,
            "escalation_reason": EscalationReason.INTEGRITY_FAIL,
        },
        {"started_at": datetime(2026, 1, 1, 12, 0)},
        {"phase_entered_at": datetime(2026, 1, 1, 12, 0, tzinfo=timezone(timedelta(hours=1)))},
    ],
)
def test_phase_state_consistency_validators_reject_invalid_states(
    overrides: dict[str, object],
) -> None:
    with pytest.raises(ValidationError):
        PhaseState(**_state_data(**overrides))


def test_phase_state_models_import_from_phase_executor_owner() -> None:
    import agentkit.pipeline_engine.phase_executor as owner
    import agentkit.story_context_manager as bridge

    assert owner.PhaseState is PhaseState
    assert bridge.PhaseState is PhaseState


def test_no_production_importer_sources_phase_models_from_story_context_manager() -> None:
    repo_root = Path(__file__).resolve().parents[4]
    forbidden = (
        "PhaseState",
        "PhaseStatus",
        "PhaseName",
        "PhasePayload",
        "PhaseMemory",
        "ImplementationPayload",
        "ExplorationPayload",
        "ClosurePayload",
        "QaCycleStatus",
    )
    offenders: list[str] = []
    for path in (repo_root / "src" / "agentkit").rglob("*.py"):
        if path.match("*/story_context_manager/__init__.py"):
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.ImportFrom):
                continue
            if node.module != "agentkit.story_context_manager.models":
                continue
            if any(alias.name in forbidden for alias in node.names):
                offenders.append(str(path.relative_to(repo_root)))
    assert offenders == []
