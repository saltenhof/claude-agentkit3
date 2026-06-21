"""ProducerRegistry — register of the allowed artifact producers.

Registers, per `ArtifactClass`, the allowed producer names and their
types. Includes the LLM-status mapping per FK-71 §71.2.

Init mechanics (AG3-022 §2.1.5.1):
- The constructor seeds all `ArtifactClass` values with an empty
  producer dict (class seed; currently nine values incl. ``prompt_audit``,
  AG3-015).
- No concrete producers are registered in AG3-022; this happens in
  AG3-023 through BC-specific init hooks.
- `validate(envelope)` is fail-closed: unknown producer names raise
  `ProducerNotRegisteredError`.

LLM-status mapping (FK-71 §71.2, lines 145-161):
- ``"PASS"``              -> ``EnvelopeStatus.PASS``
- ``"PASS_WITH_CONCERNS"``-> ``EnvelopeStatus.WARN`` (LLM wire string only)
- ``"FAIL"``              -> ``EnvelopeStatus.FAIL``
- ``"ERROR"``             -> ``EnvelopeStatus.ERROR``
- ``"TIMEOUT"``           -> ``EnvelopeStatus.ERROR``
- Unknown strings         -> ``LlmStatusMappingError`` (fail-closed)

`PASS_WITH_CONCERNS` is exclusively an LLM-check wire string. It is
mapped here to `EnvelopeStatus.WARN` — no reintroduction into
PolicyVerdict or the policy engine (AG3-021 §2.1.1.2).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Final

from agentkit.backend.artifacts.errors import (
    LlmStatusMappingError,
    ProducerNotRegisteredError,
    ProducerTypeMismatchError,
)
from agentkit.backend.core_types import ArtifactClass, EnvelopeStatus

if TYPE_CHECKING:
    from agentkit.backend.artifacts.envelope import ArtifactEnvelope
    from agentkit.backend.artifacts.producer import ProducerType

# ---------------------------------------------------------------------------
# LLM-status mapping as a class constant (FK-71 §71.2 lines 145-161)
# ---------------------------------------------------------------------------

_LLM_STATUS_MAPPING: Final[dict[str, EnvelopeStatus]] = {
    "PASS": EnvelopeStatus.PASS,
    "PASS_WITH_CONCERNS": EnvelopeStatus.WARN,
    "FAIL": EnvelopeStatus.FAIL,
    "ERROR": EnvelopeStatus.ERROR,
    "TIMEOUT": EnvelopeStatus.ERROR,
}


class ProducerRegistry:
    """Registry of the allowed artifact producers per ArtifactClass.

    Populated with `register(...)` at app initialization and used
    read-only afterwards (no thread-safety overhead needed).

    Example::

        registry = ProducerRegistry()
        registry.register(ArtifactClass.QA, "qa-structural", ProducerType.DETERMINISTIC)
        registry.validate(envelope)  # raises ProducerNotRegisteredError if unknown
    """

    def __init__(self) -> None:
        # Class seed: all ArtifactClass values as keys, each with an empty
        # producer dict (AG3-022 §2.1.5.1). Iterates over the enum, so it
        # stays automatically in sync with enum extensions (e.g. AG3-015
        # ``prompt_audit``).
        self._producers: dict[ArtifactClass, dict[str, ProducerType]] = {
            ac: {} for ac in ArtifactClass
        }

    def register(
        self,
        artifact_class: ArtifactClass,
        producer_name: str,
        producer_type: ProducerType,
    ) -> None:
        """Register a producer for an ArtifactClass.

        Args:
            artifact_class: Artifact class for which this producer applies.
            producer_name: Canonical producer name (e.g. ``qa-structural``).
            producer_type: Type of the producer (WORKER / LLM_REVIEWER / DETERMINISTIC).
        """
        self._producers[artifact_class][producer_name] = producer_type

    def validate(self, envelope: ArtifactEnvelope) -> None:
        """Check whether the producer in the envelope is registered (fail-closed).

        BOTH aspects are checked against the registry:
        1. The producer name must be registered for the given
           ``ArtifactClass``.
        2. The ``ProducerType`` in the envelope must match the
           registered type — otherwise a producer name could silently
           flip its type (defense in depth against drift).

        Args:
            envelope: The ArtifactEnvelope to check.

        Raises:
            ProducerNotRegisteredError: When the producer name is not
                registered for the given ArtifactClass.
            ProducerTypeMismatchError: When the producer name is
                registered, but its type given in the envelope differs
                from the registered type.
        """
        allowed = self._producers[envelope.artifact_class]
        registered_type = allowed.get(envelope.producer.name)
        if registered_type is None:
            msg = (
                f"Producer '{envelope.producer.name}' is not registered for "
                f"ArtifactClass '{envelope.artifact_class}'. "
                f"Known producers: {set(allowed.keys()) or '{}'}"
            )
            raise ProducerNotRegisteredError(msg)
        if registered_type is not envelope.producer.type:
            msg = (
                f"Producer '{envelope.producer.name}' is registered for "
                f"ArtifactClass '{envelope.artifact_class}' as "
                f"'{registered_type.value}', but the envelope claims "
                f"'{envelope.producer.type.value}' (type drift)."
            )
            raise ProducerTypeMismatchError(msg)

    def map_llm_status_to_envelope_status(self, llm_status: str) -> EnvelopeStatus:
        """Map an LLM check status to `EnvelopeStatus` (FK-71 §71.2).

        Args:
            llm_status: LLM wire string (e.g. ``"PASS_WITH_CONCERNS"``).

        Returns:
            Corresponding `EnvelopeStatus`.

        Raises:
            LlmStatusMappingError: On an unknown LLM status (fail-closed).
        """
        try:
            return _LLM_STATUS_MAPPING[llm_status]
        except KeyError:
            known = list(_LLM_STATUS_MAPPING.keys())
            msg = f"Unknown LLM check status '{llm_status}'. Known values: {known}"
            raise LlmStatusMappingError(msg) from None

    def known_producers(self, artifact_class: ArtifactClass) -> set[str]:
        """Return all registered producer names for an ArtifactClass.

        Args:
            artifact_class: Artifact class for which producers are queried.

        Returns:
            Set of registered producer names (empty if none registered).
        """
        return set(self._producers[artifact_class].keys())
