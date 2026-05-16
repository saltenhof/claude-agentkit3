"""ArtifactRepository — Protocol fuer Artefakt-Persistenz.

Bounded-Context-Grenze: Der ``agentkit.artifacts``-BC definiert das
Protocol; konkrete Implementierungen liegen in
``agentkit.state_backend.store.artifact_repository``. Das Protocol
selbst importiert **ausschliesslich** aus ``agentkit.artifacts`` und
``agentkit.core_types`` (keine Backend-Importe im Contract-Modul).

bc-cut-decisions.md §BC 8 — ArtifactManager-Vertrag.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from agentkit.artifacts.envelope import ArtifactEnvelope
    from agentkit.artifacts.reference import ArtifactReference


@runtime_checkable
class ArtifactRepository(Protocol):
    """Protocol fuer typisierte Artefakt-Persistenz.

    Implementierungen in ``agentkit.state_backend.store.artifact_repository``
    (SQLite, Postgres). Das Protocol ist ausschliesslich von
    ``ArtifactManager`` und Tests zu importieren — niemals von Producern
    oder Consumern direkt.

    Methoden:
        write_envelope: Schreibt einen validen ArtifactEnvelope; gibt
            eine ArtifactReference zurueck.
        read_envelope: Laedt einen Envelope anhand einer Reference;
            gibt ``None`` bei Nicht-Existenz.
        exists_envelope: Prueft Existenz ohne Volllesen.
    """

    def write_envelope(
        self,
        envelope: ArtifactEnvelope,
    ) -> ArtifactReference:
        """Persistiert einen validen ArtifactEnvelope (fail-closed).

        Args:
            envelope: Vollstaendig validierter ArtifactEnvelope.

        Returns:
            Opake Reference auf den geschriebenen Eintrag.

        Raises:
            Exception: Implementierungs-spezifischer Fehler bei
                I/O-Problemen oder Constraint-Verletzungen.
        """
        ...

    def read_envelope(
        self,
        reference: ArtifactReference,
    ) -> ArtifactEnvelope | None:
        """Laedt einen ArtifactEnvelope anhand seiner Reference.

        Args:
            reference: Opake Reference (Rueckgabe von ``write_envelope``).

        Returns:
            ArtifactEnvelope wenn vorhanden, sonst ``None``.
        """
        ...

    def exists_envelope(
        self,
        reference: ArtifactReference,
    ) -> bool:
        """Prueft, ob ein Artefakt mit dieser Reference existiert.

        Args:
            reference: Opake Reference.

        Returns:
            True wenn vorhanden, False sonst.
        """
        ...


__all__ = ["ArtifactRepository"]
