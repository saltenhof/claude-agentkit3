"""Unit tests for RuntimeMetadata and PhaseOrigin (AK 2)."""

from __future__ import annotations

from dataclasses import FrozenInstanceError, is_dataclass

import pytest

from agentkit.backend.pipeline_engine.phase_envelope.runtime import PhaseOrigin, RuntimeMetadata


def test_phase_origin_values() -> None:
    """PhaseOrigin has exactly NEW and LOADED values."""
    assert PhaseOrigin.NEW.value == "new"
    assert PhaseOrigin.LOADED.value == "loaded"
    assert set(PhaseOrigin) == {PhaseOrigin.NEW, PhaseOrigin.LOADED}


def test_runtime_metadata_new_has_origin() -> None:
    """RuntimeMetadata with origin=NEW carries only the domain origin."""
    meta = RuntimeMetadata(origin=PhaseOrigin.NEW)
    assert meta.origin is PhaseOrigin.NEW
    assert is_dataclass(meta)


def test_runtime_metadata_loaded_has_origin() -> None:
    """RuntimeMetadata with origin=LOADED carries only the domain origin."""
    meta = RuntimeMetadata(origin=PhaseOrigin.LOADED)
    assert meta.origin is PhaseOrigin.LOADED


def test_runtime_metadata_frozen() -> None:
    """RuntimeMetadata is frozen (immutable)."""
    meta = RuntimeMetadata(origin=PhaseOrigin.NEW)
    with pytest.raises(FrozenInstanceError):
        meta.origin = PhaseOrigin.LOADED  # type: ignore[misc]


def test_runtime_metadata_extra_forbid() -> None:
    """RuntimeMetadata rejects extra fields."""
    with pytest.raises(TypeError):
        RuntimeMetadata(  # type: ignore[call-arg]
            origin=PhaseOrigin.NEW,
            extra="boom",
        )


def test_runtime_metadata_rejects_removed_diagnostics() -> None:
    """RuntimeMetadata does not persist ephemeral diagnostics."""
    with pytest.raises(TypeError):
        RuntimeMetadata(origin=PhaseOrigin.NEW, worker_id=None)  # type: ignore[call-arg]
