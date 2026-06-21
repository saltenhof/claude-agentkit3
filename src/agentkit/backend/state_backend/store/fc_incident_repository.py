"""fc_incidents repository adapter (FK-41 §41.3.1, FK-69 §69.9, AG3-028 CONFLICT-2).

The DB-owner-side adapter for ``fc_incidents``. Lives — like the other
FK-69 repos — on the accessor side in ``state_backend/store`` and is injected
via ``ProjectionRepositories`` into the ``ProjectionAccessor``. The
``failure_corpus`` BC does NOT know this adapter (AC#6); it writes/reads
exclusively via the ``ProjectionAccessor``.

Codex-r2 remediation 2026-06-01 (user decision: incident_id GLOBALLY unique):
- Schema exactly per FK-41 §41.3.1 (project_key NOT NULL, incident_id
  FC-YYYY-NNNN, run_id NOT NULL, role, phase, model, symptom, evidence list[str],
  recorded_at, status, optional tags/impact/pattern_ref).
- ``project_key`` is mandatory and is **always** filtered in
  ``read``/``purge_run`` (missing project_key -> ValueError, FAIL-CLOSED). FK-41
  §41.3.1: "queries are always project-bound".
- ``incident_id`` (``FC-YYYY-NNNN``) is **globally unique** (PK
  ``incident_id`` alone) and is allocated via a **global per-year counter**
  (``fc_incident_counters`` keyed on ``year`` alone).
- The allocation runs race-safely in ONE atomic statement (no
  SELECT-then-INSERT TOCTOU): Postgres ``INSERT ... ON CONFLICT(year) DO UPDATE
  SET next_seq = fc_incident_counters.next_seq + 1 RETURNING next_seq - 1``
  (also covers the initial-row case); SQLite ``BEGIN IMMEDIATE`` + the same
  atomic UPSERT with ``RETURNING`` (SQLite >= 3.35).

``fc_incidents`` is append-only (exactly one record per ``incident_id``,
FK-41 §41.3.1): INSERT, no UPSERT.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

from agentkit.backend.state_backend.store.projection_repositories import (
    _is_postgres,
    _postgres_connect,
    _sqlite_connect_qa,
)

if TYPE_CHECKING:
    from pathlib import Path

    from agentkit.backend.failure_corpus.incident import Incident, IncidentDraft
    from agentkit.backend.failure_corpus.types import IncidentId


@runtime_checkable
class FCIncidentsRepository(Protocol):
    """Write/read/purge adapter for ``fc_incidents`` (FK-69 §69.9).

    Schema owner: failure-corpus (FK-41 §41.3.1).
    DB owner: telemetry-and-events via ProjectionAccessor.
    """

    def record_incident(self, draft: IncidentDraft) -> IncidentId:
        """Allocate FC-YYYY-NNNN, persist (append-only INSERT), return the id."""
        ...

    def read(
        self,
        *,
        project_key: str,
        story_id: str | None = None,
        run_id: str | None = None,
    ) -> list[Incident]:
        """Load incidents; ``project_key`` is mandatory (FK-41 §41.3.1)."""
        ...

    def purge_run(
        self,
        project_key: str,
        story_id: str,
        run_id: str,
    ) -> int:
        """Delete all fc_incidents rows for (project_key, story_id, run_id).

        FK-41 §41.3 / FK-69 §69.9: a full story reset deletes all
        ``fc_incidents`` rows of the affected ``run_id``. Project-bound
        (project_key mandatory). Returns the number of deleted rows.
        """
        ...


def _draft_to_row(draft: IncidentDraft, incident_id: str) -> dict[str, Any]:
    """Serialize an ``IncidentDraft`` + allocated id into an fc_incidents row."""
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
    """Deserialize an fc_incidents row into an ``Incident``."""
    from datetime import datetime

    from agentkit.backend.core_types import FailureCategory, IncidentStatus
    from agentkit.backend.failure_corpus.incident import Incident as _Incident
    from agentkit.backend.failure_corpus.types import (
        IncidentId,
        IncidentRole,
        IncidentSeverity,
    )

    # psycopg already returns Postgres JSON columns as list/dict; SQLite
    # returns TEXT as a JSON string. Handle both cases robustly.
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
    """Decode a JSON ``list[str]`` column (SQLite TEXT or Postgres JSON).

    FAIL-CLOSED (NO ERROR BYPASSING): a non-string element is corrupt
    persistence and is NOT silently coerced via ``str()`` but reported as an
    error. ``evidence``/``tags`` are ``list[str]`` per FK-41 §41.4.1.
    """
    if raw is None:
        return []
    if isinstance(raw, str):
        decoded: object = json.loads(raw) if raw else []
    elif isinstance(raw, list):
        decoded = raw
    else:
        raise TypeError(f"unexpected JSON-list column type: {type(raw)!r}")
    if not isinstance(decoded, list):
        raise ValueError(
            f"fc_incidents JSON-list column must be a JSON array, got "
            f"{type(decoded).__name__}"
        )
    if not all(isinstance(x, str) for x in decoded):
        raise ValueError(
            "fc_incidents JSON-list column must contain only strings (FK-41 "
            f"§41.4.1 list[str]), got element types "
            f"{[type(x).__name__ for x in decoded]}"
        )
    return list(decoded)


def _require_project_key(project_key: str | None) -> str:
    """FAIL-CLOSED: ``project_key`` is mandatory (FK-41 §41.3.1, project-bound)."""
    if not project_key:
        raise ValueError(
            "fc_incidents queries require a project_key (FK-41 §41.3.1: "
            "queries are always project-bound)"
        )
    return project_key


class StateBackendFCIncidentsRepository:
    """Thin adapter for ``fc_incidents`` (SQLite + Postgres).

    Args:
        store_dir: Base directory for SQLite; ignored for Postgres.
    """

    def __init__(self, store_dir: Path | None = None) -> None:
        from pathlib import Path as _Path

        self._store_dir: Path = store_dir or _Path.cwd()

    # -- Write + id allocation ---------------------------------------------

    def record_incident(self, draft: IncidentDraft) -> IncidentId:
        """Allocate FC-YYYY-NNNN and persist (append-only) in one transaction.

        FK-41 §41.3.1: globally unique, gap-free per year (counter keyed on
        ``year`` alone), race-safe. Returns the
        allocated ``IncidentId``.
        """
        from agentkit.backend.failure_corpus.types import IncidentId

        year = draft.recorded_at.year
        incident_id = (
            self._pg_record(draft, year)
            if _is_postgres()
            else self._sqlite_record(draft, year)
        )
        return IncidentId(incident_id)

    def _sqlite_record(self, draft: IncidentDraft, year: int) -> str:
        # _sqlite_connect_qa first runs the schema bootstrap and already holds
        # the connection in an open transaction (commit at block end).
        # BEGIN IMMEDIATE immediately takes the RESERVED write lock (analogous to
        # AG3-050 create_story_atomic) and serializes competing first/follow-up
        # allocations via busy_timeout. Allocation (one atomic UPSERT with
        # RETURNING) + INSERT run in ONE transaction on ONE connection.
        with _sqlite_connect_qa(self._store_dir) as conn:
            # _sqlite_connect_qa may, via the schema bootstrap, have an implicit
            # transaction open; commit cleanly before we take the explicit
            # write lock (otherwise "transaction within a transaction").
            conn.commit()
            conn.execute("BEGIN IMMEDIATE")
            seq = self._sqlite_allocate_seq(conn, year)
            incident_id = _format_incident_id(year, seq)
            row = _draft_to_row(draft, incident_id)
            conn.execute(_SQLITE_INSERT, row)
        return incident_id

    @staticmethod
    def _sqlite_allocate_seq(conn: Any, year: int) -> int:
        # One atomic statement: covers the initial row (VALUES 2 -> RETURNING 1)
        # and follow-up allocation (next_seq+1 -> RETURNING previous next_seq). No
        # SELECT-then-INSERT TOCTOU. SQLite >= 3.35 supports RETURNING.
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
        # One atomic statement: the initial-row case (row missing) is covered by
        # the VALUES(...,2) branch, the follow-up case by DO UPDATE. No
        # SELECT ... FOR UPDATE on a possibly missing row (the old bug:
        # FOR UPDATE locks nothing on a missing row -> two txns returned
        # FC-YYYY-0001). RETURNING yields the allocated number atomically.
        cursor = conn.execute(
            "INSERT INTO fc_incident_counters (year, next_seq) VALUES (%s, 2) "
            "ON CONFLICT (year) DO UPDATE SET "
            "next_seq = fc_incident_counters.next_seq + 1 "
            "RETURNING (next_seq - 1) AS allocated_seq",
            (year,),
        )
        return int(cursor.fetchone()["allocated_seq"])

    # -- Read ---------------------------------------------------------------

    def read(
        self,
        *,
        project_key: str,
        story_id: str | None = None,
        run_id: str | None = None,
    ) -> list[Incident]:
        """Load incidents; ``project_key`` is mandatory (FAIL-CLOSED)."""
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
        """Delete all fc_incidents rows for (project_key, story_id, run_id).

        FK-41 §41.3 / FK-69 §69.9: active deletion, no query-filter trick.
        ``project_key`` is mandatory and is filtered (FAIL-CLOSED).
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
    """Format an fc_incidents id as ``FC-YYYY-NNNN`` (FK-41 §41.3.1/§41.4.1)."""
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
