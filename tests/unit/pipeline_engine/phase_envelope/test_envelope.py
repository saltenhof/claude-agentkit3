"""Unit tests for PhaseEnvelope model (AK 1)."""

from __future__ import annotations

from dataclasses import FrozenInstanceError, asdict, is_dataclass

import pytest
from tests.phase_state_factory import make_phase_state

from agentkit.pipeline_engine.phase_envelope.envelope import PhaseEnvelope
from agentkit.pipeline_engine.phase_envelope.runtime import PhaseOrigin, RuntimeMetadata
from agentkit.pipeline_engine.phase_executor import PhaseState, PhaseStatus


def _make_runtime(*, origin: PhaseOrigin = PhaseOrigin.NEW) -> RuntimeMetadata:
    return RuntimeMetadata(origin=origin)


def _make_state() -> PhaseState:
    return make_phase_state(
        story_id="AG3-024",
        phase="setup",
        status=PhaseStatus.PENDING,
    )


def test_phase_envelope_frozen() -> None:
    """PhaseEnvelope must be immutable (frozen=True)."""
    env = PhaseEnvelope(state=_make_state(), runtime=_make_runtime())
    assert is_dataclass(env)
    with pytest.raises(FrozenInstanceError):
        env.state = _make_state()  # type: ignore[misc]


def test_phase_envelope_extra_forbid() -> None:
    """PhaseEnvelope must reject extra fields (extra=forbid)."""
    with pytest.raises(TypeError):
        PhaseEnvelope(  # type: ignore[call-arg]
            state=_make_state(),
            runtime=_make_runtime(),
            extra_field="boom",
        )


def test_phase_envelope_model_dump_roundtrip() -> None:
    """PhaseEnvelope can be serialised and the key fields are preserved."""
    state = _make_state()
    runtime = _make_runtime(origin=PhaseOrigin.NEW)
    env = PhaseEnvelope(state=state, runtime=runtime)
    data = asdict(env)
    assert data["state"].story_id == "AG3-024"
    assert data["state"].phase == "setup"
    assert data["runtime"]["origin"] == PhaseOrigin.NEW


def test_phase_envelope_loaded_origin() -> None:
    """PhaseEnvelope keeps the loaded origin."""
    runtime = _make_runtime(origin=PhaseOrigin.LOADED)
    env = PhaseEnvelope(state=_make_state(), runtime=runtime)
    assert env.runtime.origin is PhaseOrigin.LOADED
