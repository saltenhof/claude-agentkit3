"""agentkit.artifacts — Foundation-Layer fuer typisierte Artefakt-Envelopes.

Top-Surface-Re-Export des Artefakt-BCs (AG3-022):

- `ArtifactEnvelope` — Pydantic-v2-Modell fuer Artefakt-Envelopes
- `ArtifactClass` — re-export aus core_types (FK-71 §71.1.1)
- `EnvelopeStatus` — re-export aus core_types (FK-71 §71.2)
- `ArtifactReference` — getypte Referenz auf ein Artefakt
- `Producer`, `ProducerType`, `ProducerId` — Producer-Typen
- `EnvelopeValidator` — fuenf-stufiger Envelope-Validator
- `ProducerRegistry` — Registry der erlaubten Producer

Architecture-Conformance: Dieses Paket importiert **ausschliesslich**
aus `agentkit.core_types`. Keine Importe aus `agentkit.state_backend`,
`agentkit.verify_system` oder `agentkit.governance`.
"""

from __future__ import annotations

from agentkit.artifacts.envelope import ENVELOPE_SCHEMA_VERSION, ArtifactEnvelope
from agentkit.artifacts.errors import (
    EnvelopeFieldError,
    EnvelopeValidationError,
    LlmStatusMappingError,
    ProducerNotRegisteredError,
    ProducerTypeMismatchError,
)
from agentkit.artifacts.producer import Producer, ProducerId, ProducerType
from agentkit.artifacts.producer_registry import ProducerRegistry
from agentkit.artifacts.reference import ArtifactReference
from agentkit.artifacts.validator import EnvelopeValidator
from agentkit.core_types import ArtifactClass, EnvelopeStatus

__all__ = [
    "ArtifactClass",
    "ArtifactEnvelope",
    "ArtifactReference",
    "ENVELOPE_SCHEMA_VERSION",
    "EnvelopeFieldError",
    "EnvelopeStatus",
    "EnvelopeValidationError",
    "EnvelopeValidator",
    "LlmStatusMappingError",
    "Producer",
    "ProducerId",
    "ProducerNotRegisteredError",
    "ProducerRegistry",
    "ProducerType",
    "ProducerTypeMismatchError",
]
