"""fc_incidents-Repository-Adapter (FK-41 §41.3.1, FK-69 §69.9, AG3-028 KONFLIKT-2).

Der DB-Owner-seitige Adapter fuer ``fc_incidents``. Liegt — wie die uebrigen
FK-69-Repos — auf der Accessor-Seite in ``state_backend/store`` und wird via
``ProjectionRepositories`` in den ``ProjectionAccessor`` injiziert. Der
``failure_corpus``-BC kennt diesen Adapter NICHT (AC#6); er schreibt/liest
ausschliesslich ueber den ``ProjectionAccessor``.

Codex-r2 Remediation 2026-06-01 (User-Entscheidung: incident_id GLOBAL eindeutig):
- Schema exakt nach FK-41 §41.3.1 (project_key NOT NULL, incident_id
  FC-YYYY-NNNN, run_id NOT NULL, role, phase, model, symptom, evidence list[str],
  recorded_at, status, optional tags/impact/pattern_ref).
- ``project_key`` ist Pflicht und wird in ``read``/``purge_run`` **zwingend**
  gefiltert (fehlt project_key -> ValueError, FAIL-CLOSED). FK-41 §41.3.1:
  "Abfragen sind stets projektgebunden".
- ``incident_id`` (``FC-YYYY-NNNN``) ist **global eindeutig** (PK
  ``incident_id`` allein) und wird ueber einen **globalen Per-Jahr-Zaehler**
  (``fc_incident_counters`` gekeyt auf ``year`` allein) vergeben.
- Die Allokation laeuft race-sicher in EINEM atomaren Statement (kein
  SELECT-dann-INSERT-TOCTOU): Postgres ``INSERT ... ON CONFLICT(year) DO UPDATE
  SET next_seq = fc_incident_counters.next_seq + 1 RETURNING next_seq - 1``
  (deckt den Initial-Row-Fall mit ab); SQLite ``BEGIN IMMEDIATE`` + dasselbe
  atomare UPSERT mit ``RETURNING`` (SQLite >= 3.35).

``fc_incidents`` ist append-only (genau ein Datensatz pro ``incident_id``,
FK-41 §41.3.1): INSERT, kein UPSERT.
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

    from agentkit.failure_corpus.incident import Incident, IncidentDraft
    from agentkit.failure_corpus.types import IncidentId


@runtime_checkable
class FCIncidentsRepository(Protocol):
    """Schreib-/Lese-/Purge-Adapter fuer ``fc_incidents`` (FK-69 §69.9).

    Schema-Owner: failure-corpus (FK-41 §41.3.1).
    DB-Owner: telemetry-and-events via ProjectionAccessor.
    """

    def record_incident(self, draft: IncidentDraft) -> IncidentId:
        """Allokiere FC-YYYY-NNNN, persistiere (append-only INSERT), gib id zurueck."""
        ...

    def read(
        self,
        *,
        project_key: str,
        story_id: str | None = None,
        run_id: str | None = None,
    ) -> list[Incident]:
        """Lade Incidents; ``project_key`` ist Pflicht (FK-41 §41.3.1)."""
        ...

    def purge_run(
        self,
        project_key: str,
        story_id: str,
        run_id: str,
    ) -> int:
        """Loesche alle fc_incidents-Zeilen fuer (project_key, story_id, run_id).

        FK-41 §41.3 / FK-69 §69.9: ein vollstaendiger Story-Reset loescht alle
        ``fc_incidents``-Zeilen des betroffenen ``run_id``. Projektgebunden
        (project_key Pflicht). Gibt die Anzahl geloeschter Zeilen.
        """
        ...


def _draft_to_row(draft: IncidentDraft, incident_id: str) -> dict[str, Any]:
    """Serialisiere einen ``IncidentDraft`` + vergebene id in eine fc_incidents-Zeile."""
    return {
        "project_key": draft.project_key,
        "incident_id": incident_id,
        "run_id": draft.run_id,
        "story_id": draft.story_id,
        "category": draft.category.value,
        "severity": draft.severity.value,
        "phase": draft.phase,
        "role": draft.role.value,
        "model": draft.model,
        "symptom": draft.symptom,
        "evidence_json": json.dumps(list(draft.evidence)),
        "recorded_at": draft.recorded_at.isoformat(),
        "incident_status": draft.incident_status.value,
        "tags": json.dumps(list(draft.tags)) if draft.tags is not None else None,
        "impact": draft.impact,
        "pattern_ref": draft.pattern_ref,
    }


def _row_to_record(row: dict[str, Any]) -> Incident:
    """Deserialisiere eine fc_incidents-Zeile in einen ``Incident``."""
    from datetime import datetime

    from agentkit.core_types import FailureCategory, IncidentStatus
    from agentkit.failure_corpus.incident import Incident as _Incident
    from agentkit.failure_corpus.types import (
        IncidentId,
        IncidentRole,
        IncidentSeverity,
    )

    # Postgres JSON-Spalten liefert psycopg bereits als list/dict zurueck;
    # SQLite TEXT als JSON-String. Beide Faelle robust behandeln.
    evidence = _decode_json_list(row["evidence_json"])
    tags_raw = row.get("tags")
    tags = _decode_json_list(tags_raw) if tags_raw is not None else None
    recorded_at = row["recorded_at"]
    return _Incident(
        project_key=str(row["project_key"]),
        incident_id=IncidentId(str(row["incident_id"])),
        run_id=str(row["run_id"]),
        story_id=str(row["story_id"]),
        category=FailureCategory(str(row["category"])),
        severity=IncidentSeverity(str(row["severity"])),
        phase=str(row["phase"]),
        role=IncidentRole(str(row["role"])),
        model=str(row["model"]),
        symptom=str(row["symptom"]),
        evidence=evidence,
        recorded_at=(
            recorded_at
            if isinstance(recorded_at, datetime)
            else datetime.fromisoformat(str(recorded_at))
        ),
        incident_status=IncidentStatus(str(row["incident_status"])),
        tags=tags,
        impact=str(row["impact"]) if row.get("impact") is not None else None,
        pattern_ref=(
            str(row["pattern_ref"]) if row.get("pattern_ref") is not None else None
        ),
    )


def _decode_json_list(raw: object) -> list[str]:
    """Decode a JSON list[str] column (SQLite TEXT or Postgres JSON)."""
    if raw is None:
        return []
    if isinstance(raw, str):
        return [str(x) for x in json.loads(raw)] if raw else []
    if isinstance(raw, list):
        return [str(x) for x in raw]
    raise TypeError(f"unexpected JSON-list column type: {type(raw)!r}")


def _require_project_key(project_key: str | None) -> str:
    """FAIL-CLOSED: ``project_key`` ist Pflicht (FK-41 §41.3.1, projektgebunden)."""
    if not project_key:
        raise ValueError(
            "fc_incidents queries require a project_key (FK-41 §41.3.1: "
            "Abfragen sind stets projektgebunden)"
        )
    return project_key


class StateBackendFCIncidentsRepository:
    """Duenner Adapter fuer ``fc_incidents`` (SQLite + Postgres).

    Args:
        store_dir: Basisverzeichnis fuer SQLite; ignoriert bei Postgres.
    """

    def __init__(self, store_dir: Path | None = None) -> None:
        from pathlib import Path as _Path

        self._store_dir: Path = store_dir or _Path.cwd()

    # -- Schreiben + id-Allokation -----------------------------------------

    def record_incident(self, draft: IncidentDraft) -> IncidentId:
        """Allokiere FC-YYYY-NNNN und persistiere (append-only) in einer Transaktion.

        FK-41 §41.3.1: global eindeutig, gap-free pro Jahr (Counter gekeyt auf
        ``year`` allein), race-sicher. Gibt die
        vergebene ``IncidentId`` zurueck.
        """
        from agentkit.failure_corpus.types import IncidentId

        year = draft.recorded_at.year
        incident_id = (
            self._pg_record(draft, year)
            if _is_postgres()
            else self._sqlite_record(draft, year)
        )
        return IncidentId(incident_id)

    def _sqlite_record(self, draft: IncidentDraft, year: int) -> str:
        # _sqlite_connect_qa fuehrt zuerst den Schema-Bootstrap aus und haelt die
        # Verbindung bereits in einer offenen Transaktion (commit am Block-Ende).
        # BEGIN IMMEDIATE nimmt sofort den RESERVED-Write-Lock (analog AG3-050
        # create_story_atomic) und serialisiert konkurrierende Erst-/Folge-
        # Allokationen ueber busy_timeout. Allokation (ein atomares UPSERT mit
        # RETURNING) + INSERT laufen in EINER Transaktion auf EINER Verbindung.
        with _sqlite_connect_qa(self._store_dir) as conn:
            # _sqlite_connect_qa hat ueber den Schema-Bootstrap evtl. eine
            # implizite Transaktion offen; sauber committen, bevor wir den
            # expliziten Write-Lock nehmen (sonst "transaction within a
            # transaction").
            conn.commit()
            conn.execute("BEGIN IMMEDIATE")
            seq = self._sqlite_allocate_seq(conn, year)
            incident_id = _format_incident_id(year, seq)
            row = _draft_to_row(draft, incident_id)
            conn.execute(_SQLITE_INSERT, row)
        return incident_id

    @staticmethod
    def _sqlite_allocate_seq(conn: Any, year: int) -> int:
        # Ein atomares Statement: deckt Initial-Row (VALUES 2 -> RETURNING 1) und
        # Folge-Allokation (next_seq+1 -> RETURNING vorheriges next_seq) ab. Kein
        # SELECT-dann-INSERT-TOCTOU. SQLite >= 3.35 unterstuetzt RETURNING.
        cursor = conn.execute(
            "INSERT INTO fc_incident_counters (year, next_seq) VALUES (?, 2) "
            "ON CONFLICT (year) DO UPDATE SET "
            "next_seq = fc_incident_counters.next_seq + 1 "
            "RETURNING next_seq - 1",
            (year,),
        )
        return int(cursor.fetchone()[0])

    def _pg_record(self, draft: IncidentDraft, year: int) -> str:
        with _postgres_connect() as conn:
            seq = self._pg_allocate_seq(conn, year)
            incident_id = _format_incident_id(year, seq)
            row = _draft_to_row(draft, incident_id)
            conn.execute(_PG_INSERT, row)
        return incident_id

    @staticmethod
    def _pg_allocate_seq(conn: Any, year: int) -> int:
        # Ein atomares Statement: der Initial-Row-Fall (Zeile fehlt) wird ueber
        # den VALUES(...,2)-Zweig abgedeckt, der Folgefall ueber DO UPDATE. Kein
        # SELECT ... FOR UPDATE auf einer evtl. fehlenden Zeile (der alte Bug:
        # FOR UPDATE sperrt bei fehlender Zeile nichts -> zwei Txns lieferten
        # FC-YYYY-0001). RETURNING liefert die zugewiesene Nummer atomar.
        cursor = conn.execute(
            "INSERT INTO fc_incident_counters (year, next_seq) VALUES (%s, 2) "
            "ON CONFLICT (year) DO UPDATE SET "
            "next_seq = fc_incident_counters.next_seq + 1 "
            "RETURNING (next_seq - 1) AS allocated_seq",
            (year,),
        )
        return int(cursor.fetchone()["allocated_seq"])

    # -- Lesen --------------------------------------------------------------

    def read(
        self,
        *,
        project_key: str,
        story_id: str | None = None,
        run_id: str | None = None,
    ) -> list[Incident]:
        """Lade Incidents; ``project_key`` ist Pflicht (FAIL-CLOSED)."""
        pk = _require_project_key(project_key)
        if _is_postgres():
            return self._pg_read(project_key=pk, story_id=story_id, run_id=run_id)
        return self._sqlite_read(project_key=pk, story_id=story_id, run_id=run_id)

    @staticmethod
    def _build_where(
        *,
        project_key: str,
        story_id: str | None,
        run_id: str | None,
        placeholder: str,
    ) -> tuple[str, list[object]]:
        clauses: list[str] = [f"project_key = {placeholder}"]
        params: list[object] = [project_key]
        if story_id is not None:
            clauses.append(f"story_id = {placeholder}")
            params.append(story_id)
        if run_id is not None:
            clauses.append(f"run_id = {placeholder}")
            params.append(run_id)
        return f"WHERE {' AND '.join(clauses)}", params

    def _sqlite_read(
        self,
        *,
        project_key: str,
        story_id: str | None,
        run_id: str | None,
    ) -> list[Incident]:
        where, params = self._build_where(
            project_key=project_key, story_id=story_id, run_id=run_id, placeholder="?"
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
        project_key: str,
        story_id: str | None,
        run_id: str | None,
    ) -> list[Incident]:
        where, params = self._build_where(
            project_key=project_key, story_id=story_id, run_id=run_id, placeholder="%s"
        )
        with _postgres_connect() as conn:
            rows = conn.execute(
                f"SELECT * FROM fc_incidents {where}",
                tuple(params),
            ).fetchall()
        return [_row_to_record(dict(r)) for r in rows]

    # -- Purge --------------------------------------------------------------

    def purge_run(self, project_key: str, story_id: str, run_id: str) -> int:
        """Loesche alle fc_incidents-Zeilen fuer (project_key, story_id, run_id).

        FK-41 §41.3 / FK-69 §69.9: aktives Loeschen, kein Query-Filter-Trick.
        ``project_key`` ist Pflicht und wird gefiltert (FAIL-CLOSED).
        """
        pk = _require_project_key(project_key)
        if _is_postgres():
            return self._pg_purge(pk, story_id, run_id)
        return self._sqlite_purge(pk, story_id, run_id)

    def _sqlite_purge(self, project_key: str, story_id: str, run_id: str) -> int:
        with _sqlite_connect_qa(self._store_dir) as conn:
            cursor = conn.execute(
                "DELETE FROM fc_incidents "
                "WHERE project_key=? AND story_id=? AND run_id=?",
                (project_key, story_id, run_id),
            )
            return int(cursor.rowcount)

    def _pg_purge(self, project_key: str, story_id: str, run_id: str) -> int:
        with _postgres_connect() as conn:
            cursor = conn.execute(
                "DELETE FROM fc_incidents "
                "WHERE project_key=%s AND story_id=%s AND run_id=%s",
                (project_key, story_id, run_id),
            )
            return int(cursor.rowcount)


def _format_incident_id(year: int, seq: int) -> str:
    """Formatiere eine fc_incidents-id als ``FC-YYYY-NNNN`` (FK-41 §41.3.1/§41.4.1)."""
    return f"FC-{year:04d}-{seq:04d}"


_SQLITE_INSERT = """
    INSERT INTO fc_incidents (
        project_key, incident_id, run_id, story_id, category, severity,
        phase, role, model, symptom, evidence_json, recorded_at,
        incident_status, tags, impact, pattern_ref
    ) VALUES (
        :project_key, :incident_id, :run_id, :story_id, :category, :severity,
        :phase, :role, :model, :symptom, :evidence_json, :recorded_at,
        :incident_status, :tags, :impact, :pattern_ref
    )
"""

_PG_INSERT = """
    INSERT INTO fc_incidents (
        project_key, incident_id, run_id, story_id, category, severity,
        phase, role, model, symptom, evidence_json, recorded_at,
        incident_status, tags, impact, pattern_ref
    ) VALUES (
        %(project_key)s, %(incident_id)s, %(run_id)s, %(story_id)s,
        %(category)s, %(severity)s, %(phase)s, %(role)s, %(model)s,
        %(symptom)s, %(evidence_json)s, %(recorded_at)s, %(incident_status)s,
        %(tags)s, %(impact)s, %(pattern_ref)s
    )
"""


__all__ = [
    "FCIncidentsRepository",
    "StateBackendFCIncidentsRepository",
]
