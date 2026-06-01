"""fc_incidents-Repository-Adapter (FK-41 §41.3.1, FK-69 §69.9, AG3-028 KONFLIKT-2).

Der DB-Owner-seitige Adapter fuer ``fc_incidents``. Liegt — wie die uebrigen
FK-69-Repos — auf der Accessor-Seite in ``state_backend/store`` und wird via
``ProjectionRepositories`` in den ``ProjectionAccessor`` injiziert. Der
``failure_corpus``-BC kennt diesen Adapter NICHT (AC#6); er schreibt
ausschliesslich ueber ``ProjectionAccessor.write_projection``.

``fc_incidents`` ist append-only (genau ein Datensatz pro ``incident_id``,
FK-41 §41.3.1): INSERT, kein UPSERT. Ein doppelter ``incident_id`` ist ein
Fehler (PK-Verletzung -> IntegrityError, FAIL-CLOSED).

Die Tabelle ist fachlich ueber ``story_id``/``run_id`` verankert (FK-41 §41.3.1)
und traegt — anders als die uebrigen FK-69-Tabellen — KEIN ``project_key``
(Story-Schema §2.1.5). Die Accessor-Aufrufe reichen ``project_key`` mit; der
Adapter filtert/purged ausschliesslich ueber ``story_id``/``run_id``.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

from agentkit.state_backend.store.projection_repositories import (
    _is_postgres,
    _postgres_connect,
    _sqlite_connect_qa,
)

if TYPE_CHECKING:
    from pathlib import Path

    from agentkit.failure_corpus.incident import Incident


@runtime_checkable
class FCIncidentsRepository(Protocol):
    """Schreib-/Lese-/Purge-Adapter fuer ``fc_incidents`` (FK-69 §69.9).

    Schema-Owner: failure-corpus (FK-41 §41.3.1).
    DB-Owner: telemetry-and-events via ProjectionAccessor.
    """

    def write(self, record: Incident) -> None:
        """Persistiere genau einen Incident (append-only INSERT)."""
        ...

    def read(
        self,
        *,
        project_key: str | None = None,
        story_id: str | None = None,
        run_id: str | None = None,
    ) -> list[Incident]:
        """Lade Incidents mit optionalen Filtern (project_key wird ignoriert)."""
        ...

    def purge_run(
        self,
        project_key: str,
        story_id: str,
        run_id: str,
    ) -> int:
        """Loesche alle fc_incidents-Zeilen fuer (story_id, run_id).

        FK-41 §41.3 / FK-69 §69.9: ein vollstaendiger Story-Reset loescht alle
        ``fc_incidents``-Zeilen des betroffenen ``run_id``. ``project_key`` wird
        zur Signatur-Paritaet mitgereicht, aber nicht gefiltert (die Tabelle ist
        ueber story_id/run_id verankert). Gibt die Anzahl geloeschter Zeilen.
        """
        ...


def _record_to_row(record: Incident) -> dict[str, Any]:
    """Serialisiere einen ``Incident`` in eine fc_incidents-Zeile (dict)."""
    return {
        "incident_id": str(record.incident_id),
        "category": record.category.value,
        "severity": record.severity.value,
        "source_bc": record.source_bc,
        "story_id": record.story_id,
        "run_id": record.run_id,
        "summary": record.summary,
        "evidence_json": json.dumps(record.evidence, sort_keys=True),
        "observed_at": record.observed_at.isoformat(),
        "normalized_at": record.normalized_at.isoformat(),
        "incident_status": record.incident_status.value,
    }


def _row_to_record(row: dict[str, Any]) -> Incident:
    """Deserialisiere eine fc_incidents-Zeile in einen ``Incident``."""
    from datetime import datetime

    from agentkit.core_types import FailureCategory, IncidentStatus
    from agentkit.failure_corpus.incident import Incident as _Incident
    from agentkit.failure_corpus.types import IncidentId, IncidentSeverity

    # Postgres JSON-Spalten liefert psycopg bereits als dict/list zurueck;
    # SQLite TEXT als JSON-String. Beide Faelle robust behandeln.
    evidence_raw = row["evidence_json"]
    evidence: dict[str, Any]
    if isinstance(evidence_raw, str):
        evidence = json.loads(evidence_raw) if evidence_raw else {}
    elif evidence_raw is None:
        evidence = {}
    else:
        evidence = evidence_raw
    observed_at = row["observed_at"]
    normalized_at = row["normalized_at"]
    return _Incident(
        incident_id=IncidentId(str(row["incident_id"])),
        category=FailureCategory(str(row["category"])),
        severity=IncidentSeverity(str(row["severity"])),
        source_bc=str(row["source_bc"]),
        story_id=str(row["story_id"]),
        run_id=str(row["run_id"]) if row["run_id"] is not None else None,
        summary=str(row["summary"]),
        evidence=evidence,
        observed_at=(
            observed_at
            if isinstance(observed_at, datetime)
            else datetime.fromisoformat(str(observed_at))
        ),
        normalized_at=(
            normalized_at
            if isinstance(normalized_at, datetime)
            else datetime.fromisoformat(str(normalized_at))
        ),
        incident_status=IncidentStatus(str(row["incident_status"])),
    )


class StateBackendFCIncidentsRepository:
    """Duenner Adapter fuer ``fc_incidents`` (SQLite + Postgres).

    Args:
        store_dir: Basisverzeichnis fuer SQLite; ignoriert bei Postgres.
    """

    def __init__(self, store_dir: Path | None = None) -> None:
        from pathlib import Path as _Path

        self._store_dir: Path = store_dir or _Path.cwd()

    def write(self, record: Incident) -> None:
        """Persistiere genau einen Incident (append-only INSERT, FK-41 §41.3.1)."""
        row = _record_to_row(record)
        if _is_postgres():
            self._pg_write(row)
        else:
            self._sqlite_write(row)

    def _sqlite_write(self, row: dict[str, Any]) -> None:
        with _sqlite_connect_qa(self._store_dir) as conn:
            conn.execute(
                """
                INSERT INTO fc_incidents (
                    incident_id, category, severity, source_bc, story_id,
                    run_id, summary, evidence_json, observed_at, normalized_at,
                    incident_status
                ) VALUES (
                    :incident_id, :category, :severity, :source_bc, :story_id,
                    :run_id, :summary, :evidence_json, :observed_at,
                    :normalized_at, :incident_status
                )
                """,
                row,
            )

    def _pg_write(self, row: dict[str, Any]) -> None:
        with _postgres_connect() as conn:
            conn.execute(
                """
                INSERT INTO fc_incidents (
                    incident_id, category, severity, source_bc, story_id,
                    run_id, summary, evidence_json, observed_at, normalized_at,
                    incident_status
                ) VALUES (
                    %(incident_id)s, %(category)s, %(severity)s, %(source_bc)s,
                    %(story_id)s, %(run_id)s, %(summary)s, %(evidence_json)s,
                    %(observed_at)s, %(normalized_at)s, %(incident_status)s
                )
                """,
                row,
            )

    def read(
        self,
        *,
        project_key: str | None = None,
        story_id: str | None = None,
        run_id: str | None = None,
    ) -> list[Incident]:
        del project_key  # fc_incidents traegt kein project_key (Story §2.1.5)
        if _is_postgres():
            return self._pg_read(story_id=story_id, run_id=run_id)
        return self._sqlite_read(story_id=story_id, run_id=run_id)

    @staticmethod
    def _build_where(
        *,
        story_id: str | None,
        run_id: str | None,
        placeholder: str,
    ) -> tuple[str, list[object]]:
        clauses: list[str] = []
        params: list[object] = []
        if story_id is not None:
            clauses.append(f"story_id = {placeholder}")
            params.append(story_id)
        if run_id is not None:
            clauses.append(f"run_id = {placeholder}")
            params.append(run_id)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        return where, params

    def _sqlite_read(
        self,
        *,
        story_id: str | None,
        run_id: str | None,
    ) -> list[Incident]:
        where, params = self._build_where(
            story_id=story_id, run_id=run_id, placeholder="?"
        )
        with _sqlite_connect_qa(self._store_dir) as conn:
            rows = conn.execute(
                f"SELECT * FROM fc_incidents {where}",
                tuple(params),
            ).fetchall()
        return [_row_to_record(dict(r)) for r in rows]

    def _pg_read(
        self,
        *,
        story_id: str | None,
        run_id: str | None,
    ) -> list[Incident]:
        where, params = self._build_where(
            story_id=story_id, run_id=run_id, placeholder="%s"
        )
        with _postgres_connect() as conn:
            rows = conn.execute(
                f"SELECT * FROM fc_incidents {where}",
                tuple(params),
            ).fetchall()
        return [_row_to_record(dict(r)) for r in rows]

    def purge_run(self, project_key: str, story_id: str, run_id: str) -> int:
        """Loesche alle fc_incidents-Zeilen fuer (story_id, run_id).

        FK-41 §41.3 / FK-69 §69.9: aktives Loeschen, kein Query-Filter-Trick.
        """
        del project_key  # fc_incidents ist ueber story_id/run_id verankert
        if _is_postgres():
            return self._pg_purge(story_id, run_id)
        return self._sqlite_purge(story_id, run_id)

    def _sqlite_purge(self, story_id: str, run_id: str) -> int:
        with _sqlite_connect_qa(self._store_dir) as conn:
            cursor = conn.execute(
                "DELETE FROM fc_incidents WHERE story_id=? AND run_id=?",
                (story_id, run_id),
            )
            return int(cursor.rowcount)

    def _pg_purge(self, story_id: str, run_id: str) -> int:
        with _postgres_connect() as conn:
            cursor = conn.execute(
                "DELETE FROM fc_incidents WHERE story_id=%s AND run_id=%s",
                (story_id, run_id),
            )
            return int(cursor.rowcount)


__all__ = [
    "FCIncidentsRepository",
    "StateBackendFCIncidentsRepository",
]
