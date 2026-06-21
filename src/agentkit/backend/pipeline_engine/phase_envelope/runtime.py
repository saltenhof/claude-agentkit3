"""PhaseOrigin and RuntimeMetadata -- ephemeral execution context for a phase.

RuntimeMetadata is NOT persisted. It is reconstructed on every load
from the repository. Only PhaseState (durable) is written to storage.

Source of truth: FK-39 §39.3 -- concept/technical-design/39_phase_state_persistenz.md
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class PhaseOrigin(StrEnum):
    """Whether a PhaseEnvelope was freshly created or loaded from storage.

    Attributes:
        NEW: First call -- state was created in this process, not loaded.
        LOADED: State was loaded from persistent storage (resume path).
    """

    NEW = "new"
    LOADED = "loaded"


@dataclass(frozen=True, slots=True)
class RuntimeMetadata:
    """Ephemeral metadata attached to a PhaseEnvelope at runtime.

    This object is NEVER persisted. It is constructed fresh on every
    ``PhaseEnvelopeStore.load`` or when a new envelope is created by
    the runner.

    Attributes:
        origin: Whether the envelope was freshly created or loaded.
    """

    origin: PhaseOrigin
