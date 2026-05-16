"""EnvelopeValidator — fuenf-stufige Envelope-Validierung.

Eigenstaendige Klasse (entkoppelt von ArtifactEnvelope-Pydantic-Validierung),
da sie zusaetzliche Cross-Field-Checks gegen externe Wahrheiten erlaubt
(z.B. ProducerRegistry).

Pruefschritte (AG3-022 §2.1.6.2) in genau dieser Reihenfolge:

1. Pydantic-Schema (durch Pydantic-v2 bereits erzwungen; ungueltige
   Envelopes erreichen diesen Validator nicht).
2. Producer registriert fuer `envelope.artifact_class`
   (-> `ProducerNotRegisteredError`).
3. `attempt >= 1` (redundant fail-closed; durch Pydantic schon geprueft)
   (-> `EnvelopeFieldError`).
4. `status` vs. `artifact_class` gemaess Matrix §2.1.6.1
   (-> `EnvelopeFieldError`).
5. `finished_at >= started_at` (redundant fail-closed; durch Pydantic schon)
   (-> `EnvelopeFieldError`).

Bei erstem Fehler wird abgebrochen (fail-closed). Es werden immer die
spezifischen Sub-Exceptions geworfen, nie `EnvelopeValidationError` direkt.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from agentkit.artifacts.errors import EnvelopeFieldError
from agentkit.core_types import ArtifactClass, EnvelopeStatus

if TYPE_CHECKING:
    from agentkit.artifacts.envelope import ArtifactEnvelope
    from agentkit.artifacts.producer_registry import ProducerRegistry

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
}


class EnvelopeValidator:
    """Fuenf-stufiger Envelope-Validator (AG3-022 §2.1.6.2).

    Entkoppelt von ArtifactEnvelope-Pydantic-Validierung, um
    Cross-Field-Checks gegen externe Wahrheiten (ProducerRegistry) zu
    ermoeglichen.

    Args:
        registry: ProducerRegistry fuer Producer-Lookup (Schritt 2).
    """

    def __init__(self, registry: ProducerRegistry) -> None:
        self._registry = registry

    def validate(self, envelope: ArtifactEnvelope) -> None:
        """Validiert ein ArtifactEnvelope in fuenf Schritten (fail-closed).

        Schritt 1: Pydantic-Schema (bereits durch Pydantic-v2 erzwungen;
            ungueltige Envelopes erreichen diesen Validator nicht).
        Schritt 2: Producer ist fuer `envelope.artifact_class` registriert.
        Schritt 3: `attempt >= 1` (redundant fail-closed).
        Schritt 4: `status` vs. `artifact_class` Matrix-Konsistenz.
        Schritt 5: `finished_at >= started_at` (redundant fail-closed).

        Args:
            envelope: Das zu pruefende ArtifactEnvelope.

        Raises:
            ProducerNotRegisteredError: Schritt 2 — Producer unbekannt.
            EnvelopeFieldError: Schritt 3/4/5 — Feld-Invariante verletzt.
        """
        # Schritt 2: Producer registriert?
        # Wirft ProducerNotRegisteredError (fail-closed).
        self._registry.validate(envelope)

        # Schritt 3: attempt >= 1 (redundant fail-closed)
        if envelope.attempt < 1:
            msg = f"attempt muss >= 1 sein, erhalten: {envelope.attempt}"
            raise EnvelopeFieldError(msg)

        # Schritt 4: status vs. artifact_class Matrix
        allowed = _ALLOWED_STATUSES[envelope.artifact_class]
        if envelope.status not in allowed:
            msg = (
                f"EnvelopeStatus '{envelope.status}' ist fuer "
                f"ArtifactClass '{envelope.artifact_class}' nicht erlaubt. "
                f"Erlaubte Status: {sorted(s.value for s in allowed)}"
            )
            raise EnvelopeFieldError(msg)

        # Schritt 5: finished_at >= started_at (redundant fail-closed)
        if envelope.finished_at < envelope.started_at:
            msg = (
                f"finished_at ({envelope.finished_at}) muss >= started_at "
                f"({envelope.started_at}) sein"
            )
            raise EnvelopeFieldError(msg)
