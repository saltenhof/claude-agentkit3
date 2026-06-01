"""Ports des Failure-Corpus-BC (KONFLIKT-2, AG3-028).

``failure_corpus`` persistiert ausschliesslich ueber die in AG3-035 etablierte
``ProjectionAccessor.write_projection``-Schreibgrenze (FK-69 §69.9/§69.14). Es
haelt dafuer nur diese schmale Konsumenten-Sicht und importiert KEIN
``state_backend.store`` (AC#6): der fc_incidents-DB-Repo-Adapter lebt auf der
Accessor-Seite in ``state_backend/store``.

Der Import von ``ProjectionKind``/``ProjectionRecord`` steht ausschliesslich
unter ``TYPE_CHECKING`` — zur Laufzeit gibt es keinen Import von ``telemetry``,
damit kein Zyklus ``failure_corpus`` <-> ``telemetry`` entsteht.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from agentkit.telemetry.projection_accessor import ProjectionKind
    from agentkit.telemetry.projection_records import ProjectionRecord


@runtime_checkable
class ProjectionWriterPort(Protocol):
    """Schmale Schreib-Sicht auf den ``ProjectionAccessor`` (FK-69 §69.9).

    Spiegelt exakt die echte AG3-035-API
    ``write_projection(projection_kind, record)`` (NICHT ``(table, row)``).
    Der ``ProjectionAccessor`` erfuellt dieses Protocol per Strukturtyping.
    """

    def write_projection(
        self,
        projection_kind: ProjectionKind,
        record: ProjectionRecord,
    ) -> None:
        """Persistiere einen typisierten Projektions-Record (FK-69 §69.4)."""
        ...


__all__ = [
    "ProjectionWriterPort",
]
