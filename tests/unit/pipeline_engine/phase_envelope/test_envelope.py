"""Unit tests for PhaseEnvelope model (AK 1)."""

from __future__ import annotations

import os
from datetime import UTC, datetime

import pytest

from agentkit.pipeline_engine.phase_envelope.envelope import PhaseEnvelope
from agentkit.pipeline_engine.phase_envelope.runtime import PhaseOrigin, RuntimeMetadata
from agentkit.story_context_manager.models import PhaseState, PhaseStatus


def _make_runtime(*, origin: PhaseOrigin = PhaseOrigin.NEW) -> RuntimeMetadata:
    return RuntimeMetadata(
        origin=origin,
        loaded_at=datetime.now(tz=UTC) if origin is PhaseOrigin.LOADED else None,
        process_id=os.getpid(),
        worker_id=None,
    )


def _make_state() -> PhaseState:
    return PhaseState(
        story_id="AG3-024",
        phase="setup",
        status=PhaseStatus.PENDING,
    )


def test_phase_envelope_frozen() -> None:
    """PhaseEnvelope must be immutable (frozen=True)."""
    from pydantic import ValidationError
    env = PhaseEnvelope(state=_make_state(), runtime=_make_runtime())
    with pytest.raises(ValidationError):
        env.state = _make_state()  # type: ignore[misc]


def test_phase_envelope_extra_forbid() -> None:
    """PhaseEnvelope must reject extra fields (extra=forbid)."""
    from pydantic import ValidationError
    with pytest.raises(ValidationError):
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
    data = env.model_dump()
    assert data["state"]["story_id"] == "AG3-024"
    assert data["state"]["phase"] == "setup"
    assert data["runtime"]["origin"] == "new"
    assert data["runtime"]["loaded_at"] is None


def test_phase_envelope_loaded_origin() -> None:
    """PhaseEnvelope with origin=LOADED has a non-None loaded_at."""
    runtime = _make_runtime(origin=PhaseOrigin.LOADED)
    env = PhaseEnvelope(state=_make_state(), runtime=runtime)
    assert env.runtime.origin is PhaseOrigin.LOADED
    assert env.runtime.loaded_at is not None
