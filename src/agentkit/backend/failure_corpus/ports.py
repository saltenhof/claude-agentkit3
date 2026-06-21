"""Ports of the failure-corpus BC (KONFLIKT-2, AG3-028).

``failure_corpus`` persists and reads exclusively via the ``ProjectionAccessor``
boundary established in AG3-035 (FK-69 §69.9/§69.14). For that it holds only
these narrow consumer views and imports NO ``state_backend.store`` (AC#6): the
fc_incidents DB repo adapter lives on the accessor side in
``state_backend/store``.

The import of ``ProjectionKind``/``ProjectionRecord``/``ProjectionFilter`` stands
exclusively under ``TYPE_CHECKING`` — at runtime there is no import of
``telemetry``, so that no cycle ``failure_corpus`` <-> ``telemetry`` arises.

Codex-r1 remediation 2026-06-01:
- ``record_fc_incident`` returns the DB-side assigned ``IncidentId``
  (``FC-YYYY-NNNN``), which resolves the "write_projection returns None"
  tension fc-scoped (FK-41 §41.3.1 requires an assigned id).
- ``read_projection`` covers the corpus novelty of the IngressCriteria
  (FK-41 §41.4.3).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from agentkit.backend.failure_corpus.incident import IncidentDraft
    from agentkit.backend.failure_corpus.types import IncidentId
    from agentkit.backend.telemetry.projection_accessor import ProjectionFilter, ProjectionKind
    from agentkit.backend.telemetry.projection_records import ProjectionRecord


@runtime_checkable
class IncidentWriterPort(Protocol):
    """Narrow fc write view onto the ``ProjectionAccessor`` (FK-41 §41.3.1).

    ``record_fc_incident`` allocates the ``FC-YYYY-NNNN`` id within the same DB
    write transaction (globally unique, gap-free per year, race-safe) and returns
    it. The ``ProjectionAccessor`` satisfies this protocol via structural typing.
    """

    def record_fc_incident(self, draft: IncidentDraft) -> IncidentId:
        """Persist exactly one incident (append-only) and return the id."""
        ...


@runtime_checkable
class ProjectionReaderPort(Protocol):
    """Narrow read view onto the ``ProjectionAccessor`` (FK-69 §69.4).

    Needed for the corpus novelty of the IngressCriteria (FK-41 §41.4.3:
    "error type novel / not yet present in the corpus"). The
    ``ProjectionAccessor`` satisfies this protocol via structural typing.
    """

    def read_projection(
        self,
        projection_kind: ProjectionKind,
        filter: ProjectionFilter,  # noqa: A002
    ) -> list[ProjectionRecord]:
        """Read filtered projection records (e.g. FC_INCIDENTS for novelty)."""
        ...


__all__ = [
    "IncidentWriterPort",
    "ProjectionReaderPort",
]
