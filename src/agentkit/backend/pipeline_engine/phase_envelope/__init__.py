"""PhaseEnvelope sub -- FK-39 persistence boundary for pipeline phases.

Public API:
    PhaseEnvelope         -- frozen Pydantic model (state + runtime).
    RuntimeMetadata       -- ephemeral process-local context.
    PhaseOrigin           -- StrEnum: NEW | LOADED.
    PhaseEnvelopeStore    -- BC-owned facade for load / save / exists.
    PhaseEnvelopeRepository -- Protocol for storage backends.
    InvalidPauseReasonError -- raised on unknown yield_status strings.
"""

from __future__ import annotations

from agentkit.backend.pipeline_engine.phase_envelope.envelope import PhaseEnvelope
from agentkit.backend.pipeline_engine.phase_envelope.errors import InvalidPauseReasonError
from agentkit.backend.pipeline_engine.phase_envelope.repository import PhaseEnvelopeRepository
from agentkit.backend.pipeline_engine.phase_envelope.runtime import PhaseOrigin, RuntimeMetadata
from agentkit.backend.pipeline_engine.phase_envelope.store import PhaseEnvelopeStore

__all__ = [
    "InvalidPauseReasonError",
    "PhaseEnvelope",
    "PhaseEnvelopeRepository",
    "PhaseEnvelopeStore",
    "PhaseOrigin",
    "RuntimeMetadata",
]
