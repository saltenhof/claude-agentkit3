"""Unit tests for RuntimeMetadata and PhaseOrigin (AK 2)."""

from __future__ import annotations

import os
from datetime import UTC, datetime

import pytest

from agentkit.pipeline_engine.phase_envelope.runtime import PhaseOrigin, RuntimeMetadata


def test_phase_origin_values() -> None:
    """PhaseOrigin has exactly NEW and LOADED values."""
    assert PhaseOrigin.NEW == "new"
    assert PhaseOrigin.LOADED == "loaded"
    assert set(PhaseOrigin) == {PhaseOrigin.NEW, PhaseOrigin.LOADED}


def test_runtime_metadata_new_has_no_loaded_at() -> None:
    """RuntimeMetadata with origin=NEW must have loaded_at=None."""
    meta = RuntimeMetadata(
        origin=PhaseOrigin.NEW,
        loaded_at=None,
        process_id=os.getpid(),
        worker_id=None,
    )
    assert meta.origin is PhaseOrigin.NEW
    assert meta.loaded_at is None


def test_runtime_metadata_loaded_has_loaded_at() -> None:
    """RuntimeMetadata with origin=LOADED must have a loaded_at timestamp."""
    ts = datetime.now(tz=UTC)
    meta = RuntimeMetadata(
        origin=PhaseOrigin.LOADED,
        loaded_at=ts,
        process_id=os.getpid(),
        worker_id="worker-42",
    )
    assert meta.origin is PhaseOrigin.LOADED
    assert meta.loaded_at == ts
    assert meta.worker_id == "worker-42"


def test_runtime_metadata_frozen() -> None:
    """RuntimeMetadata is frozen (immutable)."""
    from pydantic import ValidationError
    meta = RuntimeMetadata(
        origin=PhaseOrigin.NEW,
        loaded_at=None,
        process_id=1,
        worker_id=None,
    )
    with pytest.raises(ValidationError):
        meta.process_id = 999  # type: ignore[misc]


def test_runtime_metadata_extra_forbid() -> None:
    """RuntimeMetadata rejects extra fields."""
    from pydantic import ValidationError
    with pytest.raises(ValidationError):
        RuntimeMetadata(  # type: ignore[call-arg]
            origin=PhaseOrigin.NEW,
            loaded_at=None,
            process_id=1,
            worker_id=None,
            extra="boom",
        )


def test_runtime_metadata_worker_id_optional() -> None:
    """worker_id can be None (engine running without named worker)."""
    meta = RuntimeMetadata(
        origin=PhaseOrigin.NEW,
        loaded_at=None,
        process_id=1,
        worker_id=None,
    )
    assert meta.worker_id is None
