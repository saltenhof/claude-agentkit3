"""Error classes of the artifact BC (agentkit.artifacts).

All envelope-validation errors inherit from `EnvelopeValidationError` (base).
Subclasses can be differentiated by concern:

- `ProducerNotRegisteredError` — fail-closed on an unknown producer name
- `ProducerTypeMismatchError` — fail-closed on a type drift against the registry
- `EnvelopeFieldError` — required-field violation or matrix break
- `LlmStatusMappingError` — unknown LLM check status
- `ArtifactNotFoundError` — artifact lookup fails (ArtifactManager.read)

FK-71 §71.2 (error model), bc-cut-decisions.md §BC 8.
"""

from __future__ import annotations


class EnvelopeValidationError(Exception):
    """Base error for all envelope-validation problems."""


class ProducerNotRegisteredError(EnvelopeValidationError):
    """Producer name is not registered for the given ArtifactClass.

    Raised by `ProducerRegistry.validate` (fail-closed).
    """


class ProducerTypeMismatchError(EnvelopeValidationError):
    """Producer name is registered, but with a different ``ProducerType``.

    Example: registered as ``DETERMINISTIC``, but the envelope claims
    ``LLM_REVIEWER``. Raised by `ProducerRegistry.validate` (fail-closed)
    so a producer name cannot silently flip its type.
    """


class EnvelopeFieldError(EnvelopeValidationError):
    """Required-field violation or matrix inconsistency in the envelope.

    Examples:
    - `attempt < 1`
    - `finished_at < started_at`
    - `status` is not allowed for `artifact_class` per the matrix.
    """


class LlmStatusMappingError(EnvelopeValidationError):
    """Unknown LLM check status cannot be mapped (fail-closed).

    Raised by `ProducerRegistry.map_llm_status_to_envelope_status`.
    """


class ArtifactNotFoundError(Exception):
    """Artifact lookup by an ArtifactReference fails.

    Raised by ``ArtifactManager.read`` when no entry for the given
    Reference exists in the backend (fail-closed; no silent None return).

    bc-cut-decisions.md §BC 8, FK-71 §71.2.
    """
