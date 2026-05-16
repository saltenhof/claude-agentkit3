"""Fehlerklassen des Artefakt-BCs (agentkit.artifacts).

Alle Fehler erben von `EnvelopeValidationError` (Basis).
Sub-Klassen koennen fachlich differenziert werden:

- `ProducerNotRegisteredError` — fail-closed bei unbekanntem Producer-Namen
- `ProducerTypeMismatchError` — fail-closed bei Typ-Drift gegen Registry
- `EnvelopeFieldError` — Pflichtfeld-Verletzung oder Matrix-Bruch
- `LlmStatusMappingError` — unbekannter LLM-Check-Status

FK-71 §71.2 (Fehlermodell), bc-cut-decisions.md §BC 8.
"""

from __future__ import annotations


class EnvelopeValidationError(Exception):
    """Basis-Fehler fuer alle Envelope-Validierungsprobleme."""


class ProducerNotRegisteredError(EnvelopeValidationError):
    """Producer-Name ist fuer die gegebene ArtifactClass nicht registriert.

    Wird von `ProducerRegistry.validate` geworfen (fail-closed).
    """


class ProducerTypeMismatchError(EnvelopeValidationError):
    """Producer-Name ist registriert, aber mit anderem ``ProducerType``.

    Beispiel: registriert als ``DETERMINISTIC``, Envelope behauptet
    ``LLM_REVIEWER``. Wird von `ProducerRegistry.validate` geworfen
    (fail-closed), damit ein Producer-Name nicht still seinen Typ
    drehen kann.
    """


class EnvelopeFieldError(EnvelopeValidationError):
    """Pflichtfeld-Verletzung oder Matrix-Inkonsistenz im Envelope.

    Beispiele:
    - `attempt < 1`
    - `finished_at < started_at`
    - `status` ist fuer `artifact_class` laut Matrix nicht erlaubt.
    """


class LlmStatusMappingError(EnvelopeValidationError):
    """Unbekannter LLM-Check-Status kann nicht gemappt werden (fail-closed).

    Wird von `ProducerRegistry.map_llm_status_to_envelope_status` geworfen.
    """
