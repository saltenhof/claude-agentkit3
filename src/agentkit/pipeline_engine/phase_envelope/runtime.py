"""PhaseOrigin and RuntimeMetadata -- ephemeral execution context for a phase.

RuntimeMetadata is NOT persisted. It is reconstructed on every load
from the repository. Only PhaseState (durable) is written to storage.

Source of truth: FK-39 §39.3 -- concept/technical-design/39_phase_state_persistenz.md
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict


class PhaseOrigin(StrEnum):
    """Whether a PhaseEnvelope was freshly created or loaded from storage.

    Attributes:
        NEW: First call -- state was created in this process, not loaded.
        LOADED: State was loaded from persistent storage (resume path).
    """

    NEW = "new"
    LOADED = "loaded"


class RuntimeMetadata(BaseModel):
    """Ephemeral metadata attached to a PhaseEnvelope at runtime.

    This object is NEVER persisted. It is constructed fresh on every
    ``PhaseEnvelopeStore.load`` or when a new envelope is created by
    the runner. Its purpose is to carry process-local context (PID,
    worker identity, load timestamp) without polluting durable PhaseState.

    Attributes:
        origin: Whether the envelope was freshly created or loaded.
        loaded_at: UTC timestamp of when the state was loaded from
            storage. ``None`` when ``origin`` is ``NEW``.
        process_id: OS process ID of the current process.
        worker_id: Worker identifier from ``AGENTKIT_WORKER_ID`` env var,
            or ``None`` when running outside a worker context.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    origin: PhaseOrigin
    loaded_at: datetime | None = None
    process_id: int
    worker_id: str | None = None
