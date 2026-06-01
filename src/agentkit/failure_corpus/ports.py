"""Ports des Failure-Corpus-BC (KONFLIKT-2, AG3-028).

``failure_corpus`` persistiert und liest ausschliesslich ueber die in AG3-035
etablierte ``ProjectionAccessor``-Grenze (FK-69 §69.9/§69.14). Es haelt dafuer
nur diese schmalen Konsumenten-Sichten und importiert KEIN
``state_backend.store`` (AC#6): der fc_incidents-DB-Repo-Adapter lebt auf der
Accessor-Seite in ``state_backend/store``.

Der Import von ``ProjectionKind``/``ProjectionRecord``/``ProjectionFilter`` steht
ausschliesslich unter ``TYPE_CHECKING`` — zur Laufzeit gibt es keinen Import von
``telemetry``, damit kein Zyklus ``failure_corpus`` <-> ``telemetry`` entsteht.

Codex-r1 Remediation 2026-06-01:
- ``record_fc_incident`` gibt die DB-seitig vergebene ``IncidentId`` zurueck
  (``FC-YYYY-NNNN``), womit die „write_projection gibt None zurueck"-Spannung
  fc-scoped geloest ist (FK-41 §41.3.1 verlangt eine vergebene id).
- ``read_projection`` deckt die Corpus-Neuheit der IngressCriteria
  (FK-41 §41.4.3) ab.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from agentkit.failure_corpus.incident import IncidentDraft
    from agentkit.failure_corpus.types import IncidentId
    from agentkit.telemetry.projection_accessor import ProjectionFilter, ProjectionKind
    from agentkit.telemetry.projection_records import ProjectionRecord


@runtime_checkable
class IncidentWriterPort(Protocol):
    """Schmale fc-Schreib-Sicht auf den ``ProjectionAccessor`` (FK-41 §41.3.1).

    ``record_fc_incident`` allokiert die ``FC-YYYY-NNNN``-id in derselben
    DB-Schreibtransaktion (gap-free pro (project_key, Jahr), race-sicher) und
    gibt sie zurueck. Der ``ProjectionAccessor`` erfuellt dieses Protocol per
    Strukturtyping.
    """

    def record_fc_incident(self, draft: IncidentDraft) -> IncidentId:
        """Persistiere genau einen Incident (append-only) und gib die id zurueck."""
        ...


@runtime_checkable
class ProjectionReaderPort(Protocol):
    """Schmale Lese-Sicht auf den ``ProjectionAccessor`` (FK-69 §69.4).

    Wird fuer die Corpus-Neuheit der IngressCriteria gebraucht (FK-41 §41.4.3:
    "Fehlertyp neu / noch nicht im Corpus vertreten"). Der ``ProjectionAccessor``
    erfuellt dieses Protocol per Strukturtyping.
    """

    def read_projection(
        self,
        projection_kind: ProjectionKind,
        filter: ProjectionFilter,  # noqa: A002
    ) -> list[ProjectionRecord]:
        """Lese gefilterte Projektions-Records (z.B. FC_INCIDENTS fuer Neuheit)."""
        ...


__all__ = [
    "IncidentWriterPort",
    "ProjectionReaderPort",
]
