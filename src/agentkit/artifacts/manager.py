"""ArtifactManager — Top-Surface fuer Artefakt-Lese-/Schreib-Koordination.

Einziger autorisierter Schreib-Einstiegspunkt fuer Artefakt-Persistenz im
Artefakt-BC. Alle Producer-BCs schreiben ausschliesslich ueber diese
Klasse; direkter Zugriff auf ``ArtifactRepository``-Implementierungen ist
nur innerhalb des ``state_backend``-BC erlaubt.

Fail-closed-Semantik:
- ``write`` validiert den Envelope vor der Persistenz; partial writes
  sind nicht moeglich.
- ``read`` wirft ``ArtifactNotFoundError`` bei Nicht-Existenz (kein
  silent None-Return).
- ``exists`` ist der einzige lesende Pfad ohne Fehler-Garantie.

bc-cut-decisions.md §BC 8, FK-71 §71.2.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from agentkit.artifacts.errors import ArtifactNotFoundError

if TYPE_CHECKING:
    from agentkit.artifacts.envelope import ArtifactEnvelope
    from agentkit.artifacts.reference import ArtifactReference
    from agentkit.artifacts.repository import ArtifactRepository
    from agentkit.artifacts.validator import EnvelopeValidator
    from agentkit.core_types import ArtifactClass


class ArtifactManager:
    """Top-Surface fuer typisierte Artefakt-Persistenz.

    Koordiniert Validierung (``EnvelopeValidator``) und Persistenz
    (``ArtifactRepository``). Kein Producer-BC soll den Repository-
    Adapter direkt benutzen; stattdessen erhaelt er einen
    ArtifactManager via Dependency-Injection.

    Args:
        repository: Persistenz-Backend (SQLite oder Postgres).
        validator: Envelope-Validator (fuenf Pruefschritte, AG3-022).

    Performance-Hinweis: ``write`` macht kein zusaetzliches
    ``read``-Roundtrip nach dem Schreiben (kein Double-Hit).
    """

    def __init__(
        self,
        repository: ArtifactRepository,
        validator: EnvelopeValidator,
    ) -> None:
        self._repository = repository
        self._validator = validator

    def write(self, envelope: ArtifactEnvelope) -> ArtifactReference:
        """Validiert und persistiert einen ArtifactEnvelope.

        Schritt 1: ``EnvelopeValidator.validate`` — schlaegt fail-closed
            bei jeder Validierungsverletzung (kein partial write).
        Schritt 2: ``ArtifactRepository.write_envelope`` — atomare
            Persistenz.

        Args:
            envelope: Zu persistierender ArtifactEnvelope mit allen
                Pflichtfeldern.

        Returns:
            ``ArtifactReference`` — opake Referenz auf den Eintrag.

        Raises:
            ProducerNotRegisteredError: Wenn der Producer unbekannt ist.
            ProducerTypeMismatchError: Wenn der Producer-Typ nicht stimmt.
            EnvelopeFieldError: Wenn ein Pflichtfeld ungueltig ist.
            Exception: Backend-Fehler aus der Repository-Implementierung.
        """
        # Schritt 1: Validierung — fail-closed, wirft spezifische Exception.
        self._validator.validate(envelope)
        # Schritt 2: atomare Persistenz — kein Read-Roundtrip danach.
        return self._repository.write_envelope(envelope)

    def read(self, reference: ArtifactReference) -> ArtifactEnvelope:
        """Laedt einen ArtifactEnvelope anhand seiner Reference.

        Args:
            reference: Opake Reference (Rueckgabe von ``write``).

        Returns:
            Gespeicherter ArtifactEnvelope.

        Raises:
            ArtifactNotFoundError: Wenn kein Artefakt mit dieser
                Reference existiert (fail-closed; kein silent None).
        """
        result = self._repository.read_envelope(reference)
        if result is None:
            msg = (
                f"Kein Artefakt gefunden fuer Reference: "
                f"artifact_class={reference.artifact_class!r}, "
                f"story_id={reference.story_id!r}, "
                f"run_id={reference.run_id!r}, "
                f"record_key={reference.record_key!r}"
            )
            raise ArtifactNotFoundError(msg)
        return result

    def read_latest(
        self,
        *,
        story_id: str,
        run_id: str | None,
        artifact_class: ArtifactClass,
        stage: str,
    ) -> ArtifactEnvelope:
        """Laedt den hoechsten-attempt-Envelope im (story, run, class, stage)-Scope.

        Args:
            story_id: Story-Display-ID.
            run_id: Run-Korrelations-ID; ``None`` matched ueber alle Runs.
            artifact_class: Erzeugerklasse-Filter.
            stage: Stage-Filter.

        Returns:
            ``ArtifactEnvelope`` mit dem hoechsten ``attempt`` im Scope.

        Raises:
            ArtifactNotFoundError: Wenn kein Envelope im Scope existiert
                (fail-closed; kein silent None).
        """
        result = self._repository.find_latest_envelope(
            story_id=story_id,
            run_id=run_id,
            artifact_class=artifact_class,
            stage=stage,
        )
        if result is None:
            msg = (
                "Kein Artefakt im Scope: "
                f"story_id={story_id!r}, run_id={run_id!r}, "
                f"artifact_class={artifact_class!r}, stage={stage!r}"
            )
            raise ArtifactNotFoundError(msg)
        return result

    def exists(self, reference: ArtifactReference) -> bool:
        """Prueft, ob ein Artefakt mit dieser Reference existiert.

        Read-only-Pfad ohne Fehlergarantie (Backend-Fehler propagieren
        direkt aus der Repository-Implementierung).

        Args:
            reference: Opake Reference.

        Returns:
            True wenn vorhanden, False sonst.
        """
        return self._repository.exists_envelope(reference)


__all__ = ["ArtifactManager"]
