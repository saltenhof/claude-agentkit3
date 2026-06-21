"""EnvelopeValidator — five-step envelope validation.

A standalone class (decoupled from ArtifactEnvelope Pydantic validation),
since it allows additional cross-field checks against external truths
(e.g. ProducerRegistry).

Check steps (AG3-022 §2.1.6.2) in exactly this order:

1. Pydantic schema (already enforced by Pydantic v2; invalid envelopes
   do not reach this validator).
2. Producer registered for `envelope.artifact_class`
   (-> `ProducerNotRegisteredError`).
3. `attempt >= 1` (redundant fail-closed; already checked by Pydantic)
   (-> `EnvelopeFieldError`).
4. `status` vs. `artifact_class` per matrix §2.1.6.1
   (-> `EnvelopeFieldError`).
5. `finished_at >= started_at` (redundant fail-closed; already by Pydantic)
   (-> `EnvelopeFieldError`).

On the first error it aborts (fail-closed). The specific sub-exceptions
are always raised, never `EnvelopeValidationError` directly.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from agentkit.backend.artifacts.errors import EnvelopeFieldError
from agentkit.backend.core_types import ArtifactClass, EnvelopeStatus

if TYPE_CHECKING:
    from agentkit.backend.artifacts.envelope import ArtifactEnvelope
    from agentkit.backend.artifacts.producer_registry import ProducerRegistry

# ---------------------------------------------------------------------------
# ArtifactClass × EnvelopeStatus Matrix (AG3-022 §2.1.6.1)
# ---------------------------------------------------------------------------

_ALLOWED_STATUSES: dict[ArtifactClass, frozenset[EnvelopeStatus]] = {
    ArtifactClass.WORKER: frozenset({
        EnvelopeStatus.PASS,
        EnvelopeStatus.FAIL,
        EnvelopeStatus.WARN,
        EnvelopeStatus.ERROR,
    }),
    ArtifactClass.QA: frozenset({
        EnvelopeStatus.PASS,
        EnvelopeStatus.FAIL,
        EnvelopeStatus.WARN,
        EnvelopeStatus.ERROR,
    }),
    ArtifactClass.PIPELINE: frozenset({
        EnvelopeStatus.PASS,
        EnvelopeStatus.FAIL,
        EnvelopeStatus.WARN,
        EnvelopeStatus.ERROR,
    }),
    ArtifactClass.TELEMETRY: frozenset({
        EnvelopeStatus.PASS,
        EnvelopeStatus.ERROR,
    }),
    ArtifactClass.GOVERNANCE: frozenset({
        EnvelopeStatus.PASS,
        EnvelopeStatus.FAIL,
        EnvelopeStatus.WARN,
        EnvelopeStatus.ERROR,
    }),
    ArtifactClass.ENTWURF: frozenset({
        EnvelopeStatus.PASS,
        EnvelopeStatus.FAIL,
        EnvelopeStatus.ERROR,
    }),
    ArtifactClass.HANDOVER: frozenset({
        EnvelopeStatus.PASS,
        EnvelopeStatus.FAIL,
        EnvelopeStatus.WARN,
        EnvelopeStatus.ERROR,
    }),
    ArtifactClass.ADVERSARIAL_TEST_SANDBOX: frozenset({
        EnvelopeStatus.PASS,
        EnvelopeStatus.FAIL,
        EnvelopeStatus.WARN,
        EnvelopeStatus.ERROR,
    }),
    # AG3-015 / FK-44 §44.6: prompt-audit records are deterministic
    # evidence of a materialization. A record either documents a
    # successful prompt usage (PASS) or an infrastructure failure during
    # materialization (ERROR). There is no FAIL/WARN semantic for an
    # audit record (it is not a verdict).
    ArtifactClass.PROMPT_AUDIT: frozenset({
        EnvelopeStatus.PASS,
        EnvelopeStatus.ERROR,
    }),
}


class EnvelopeValidator:
    """Five-step envelope validator (AG3-022 §2.1.6.2).

    Decoupled from ArtifactEnvelope Pydantic validation to enable
    cross-field checks against external truths (ProducerRegistry).

    Args:
        registry: ProducerRegistry for the producer lookup (step 2).
    """

    def __init__(self, registry: ProducerRegistry) -> None:
        self._registry = registry

    def validate(self, envelope: ArtifactEnvelope) -> None:
        """Validate an ArtifactEnvelope in five steps (fail-closed).

        Step 1: Pydantic schema (already enforced by Pydantic v2;
            invalid envelopes do not reach this validator).
        Step 2: Producer is registered for `envelope.artifact_class`.
        Step 3: `attempt >= 1` (redundant fail-closed).
        Step 4: `status` vs. `artifact_class` matrix consistency.
        Step 5: `finished_at >= started_at` (redundant fail-closed).

        Args:
            envelope: The ArtifactEnvelope to check.

        Raises:
            ProducerNotRegisteredError: Step 2 — producer unknown.
            EnvelopeFieldError: Step 3/4/5 — field invariant violated.
        """
        # Step 2: producer registered?
        # Raises ProducerNotRegisteredError (fail-closed).
        self._registry.validate(envelope)

        # Step 3: attempt >= 1 (redundant fail-closed)
        if envelope.attempt < 1:
            msg = f"attempt must be >= 1, received: {envelope.attempt}"
            raise EnvelopeFieldError(msg)

        # Step 4: status vs. artifact_class matrix
        allowed = _ALLOWED_STATUSES[envelope.artifact_class]
        if envelope.status not in allowed:
            msg = (
                f"EnvelopeStatus '{envelope.status}' is not allowed for "
                f"ArtifactClass '{envelope.artifact_class}'. "
                f"Allowed statuses: {sorted(s.value for s in allowed)}"
            )
            raise EnvelopeFieldError(msg)

        # Step 5: finished_at >= started_at (redundant fail-closed)
        if envelope.finished_at < envelope.started_at:
            msg = (
                f"finished_at ({envelope.finished_at}) must be >= started_at "
                f"({envelope.started_at})"
            )
            raise EnvelopeFieldError(msg)
