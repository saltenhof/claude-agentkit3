"""agentkit.artifacts — foundation layer for typed artifact envelopes.

Top-surface re-export of the artifact BC (AG3-022 + AG3-023):

- `ArtifactEnvelope` — Pydantic-v2 model for artifact envelopes
- `ArtifactClass` — re-export from core_types (FK-71 §71.1.1)
- `EnvelopeStatus` — re-export from core_types (FK-71 §71.2)
- `ArtifactReference` — typed reference to an artifact
- `ArtifactRepository` — Protocol for the persistence backend
- `ArtifactManager` — top-surface write/read/exists (AG3-023)
- `ArtifactNotFoundError` — fail-closed on a missing artifact
- `Producer`, `ProducerType`, `ProducerId` — producer types
- `EnvelopeValidator` — five-step envelope validator
- `ProducerRegistry` — registry of the allowed producers

Architecture conformance: this package imports **exclusively** from
`agentkit.core_types`. No imports from `agentkit.state_backend`,
`agentkit.verify_system` or `agentkit.governance`.
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
