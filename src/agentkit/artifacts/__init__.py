"""agentkit.artifacts — Foundation-Layer fuer typisierte Artefakt-Envelopes.

Top-Surface-Re-Export des Artefakt-BCs (AG3-022 + AG3-023):

- `ArtifactEnvelope` — Pydantic-v2-Modell fuer Artefakt-Envelopes
- `ArtifactClass` — re-export aus core_types (FK-71 §71.1.1)
- `EnvelopeStatus` — re-export aus core_types (FK-71 §71.2)
- `ArtifactReference` — getypte Referenz auf ein Artefakt
- `ArtifactRepository` — Protocol fuer Persistenz-Backend
- `ArtifactManager` — Top-Surface write/read/exists (AG3-023)
- `ArtifactNotFoundError` — fail-closed bei fehlendem Artefakt
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
    ArtifactNotFoundError,
    EnvelopeFieldError,
    EnvelopeValidationError,
    LlmStatusMappingError,
    ProducerNotRegisteredError,
    ProducerTypeMismatchError,
)
from agentkit.artifacts.manager import ArtifactManager
from agentkit.artifacts.producer import Producer, ProducerId, ProducerType
from agentkit.artifacts.producer_registry import ProducerRegistry
from agentkit.artifacts.reference import ArtifactReference
from agentkit.artifacts.repository import ArtifactRepository
from agentkit.artifacts.validator import EnvelopeValidator
from agentkit.core_types import ArtifactClass, EnvelopeStatus

__all__ = [
    "ArtifactClass",
    "ArtifactEnvelope",
    "ArtifactManager",
    "ArtifactNotFoundError",
    "ArtifactReference",
    "ArtifactRepository",
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
