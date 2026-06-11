"""ProjectionRepositories: Protokoll-Definitionen und duenne Adapter fuer FK-69-Tabellen.

Jedes Repository-Protocol definiert die Schreib- und Lese-Grenze fuer eine
FK-69-Tabellenfamilie. Die konkreten Implementierungen kapseln die bestehenden
facade-Funktionen ohne neue operative Wahrheit einzufuehren.

Architecture Conformance (AC#7):
- ``ProjectionAccessor`` in ``agentkit.telemetry`` darf NICHT direkt aus
  ``agentkit.state_backend.store.facade`` importieren.
- Stattdessen werden diese Repository-Protocols via ``ProjectionRepositories``
  (Dependency-Injection-Dataclass) injiziert.
- Konkrete Implementierungen liegen hier (DB-Schicht), Accessor in ``telemetry``.

Quellen:
- FK-69 §69.3 -- Tabellenumfang
- FK-69 §69.4 -- Schreib-Ownership und Writer-Komponenten
- FK-69 §69.10.1 -- Reset-Purge-Regel (run_id-scoped)
- AG3-035 §2.1.1 -- ProjectionRepositories-Dataclass
"""

from __future__ import annotations

import json
import os
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

if TYPE_CHECKING:
    from collections.abc import Iterator

    from agentkit.closure.post_merge_finalization.records import StoryMetricsRecord
    from agentkit.state_backend.store.fc_incident_repository import (
        FCIncidentsRepository,
    )
    from agentkit.state_backend.store.task_repository import TaskRepository
    from agentkit.telemetry.risk_window.normalized_event import NormalizedEvent
    from agentkit.verify_system.protocols import LayerResult
    from agentkit.verify_system.stage_registry.records import (
        QAFindingRecord,
        QAStageResultRecord,
    )


# ---------------------------------------------------------------------------
# Repository Protocols
# ---------------------------------------------------------------------------


@runtime_checkable
class QAStageResultsRepository(Protocol):
    """Schreib-/Lese-/Purge-Adapter fuer ``qa_stage_results`` (FK-69 §69.6).

    Schema-Owner: verify-system (FK-33).
    DB-Owner: telemetry-and-events via ProjectionAccessor.
    """

    def write(self, record: QAStageResultRecord) -> None:
        """Persistiere einen einzelnen QAStageResultRecord."""
        ...

    def read(
        self,
        *,
        project_key: str | None = None,
        story_id: str | None = None,
        run_id: str | None = None,
        attempt_no: int | None = None,
        stage_id: str | None = None,
    ) -> list[QAStageResultRecord]:
        """Lade QAStageResultRecords mit optionalen Filtern."""
        ...

    def purge_run(
        self,
        project_key: str,
        story_id: str,
        run_id: str,
    ) -> int:
        """Loesche alle qa_stage_results fuer (project_key, story_id, run_id).

        FK-69 §69.10.1: ein vollstaendiger Reset entfernt alle Zeilen des
        betroffenen run_id. Gibt die Anzahl geloeschter Zeilen zurueck.
        """
        ...


@runtime_checkable
class QAFindingsRepository(Protocol):
    """Schreib-/Lese-/Purge-Adapter fuer ``qa_findings`` (FK-69 §69.7).

    Schema-Owner: verify-system (FK-33).
    DB-Owner: telemetry-and-events via ProjectionAccessor.
    """

    def write(self, record: QAFindingRecord) -> None:
        """Persistiere einen einzelnen QAFindingRecord."""
        ...

    def read(
        self,
        *,
        project_key: str | None = None,
        story_id: str | None = None,
        run_id: str | None = None,
        attempt_no: int | None = None,
        stage_id: str | None = None,
    ) -> list[QAFindingRecord]:
        """Lade QAFindingRecords mit optionalen Filtern."""
        ...

    def purge_run(
        self,
        project_key: str,
        story_id: str,
        run_id: str,
    ) -> int:
        """Loesche alle qa_findings fuer (project_key, story_id, run_id).

        FK-69 §69.10.1: ein vollstaendiger Reset entfernt alle Zeilen des
        betroffenen run_id. Gibt die Anzahl geloeschter Zeilen zurueck.
        """
        ...


@runtime_checkable
class StoryMetricsRepository(Protocol):
    """Schreib-/Lese-/Purge-Adapter fuer ``story_metrics`` (FK-69 §69.8).

    Schema-Owner: story-closure (FK-29 §29.6).
    DB-Owner: telemetry-and-events via ProjectionAccessor.
    """

    def write(self, record: StoryMetricsRecord) -> None:
        """Persistiere (upsert) einen StoryMetricsRecord."""
        ...

    def read(
        self,
        *,
        project_key: str | None = None,
        story_id: str | None = None,
        run_id: str | None = None,
    ) -> list[StoryMetricsRecord]:
        """Lade StoryMetricsRecords mit optionalen Filtern."""
        ...

    def purge_run(
        self,
        project_key: str,
        story_id: str,
        run_id: str,
    ) -> int:
        """Loesche alle story_metrics fuer (project_key, story_id, run_id).

        FK-69 §69.10.1: ein vollstaendiger Reset entfernt alle Zeilen des
        betroffenen run_id. Gibt die Anzahl geloeschter Zeilen zurueck.
        """
        ...


@runtime_checkable
class RiskWindowRepository(Protocol):
    """Schreib-/Purge-Adapter fuer ``risk_window`` (FK-68 §68.8, AG3-037).

    Schema-Owner + DB-Owner: telemetry-and-events. Append-only Rolling-Window
    von ``NormalizedEvent``s; Schreibpfad ausschliesslich ueber
    ``ProjectionAccessor.record_risk_window_event``.
    """

    def record(self, event: NormalizedEvent) -> None:
        """Persistiere einen ``NormalizedEvent`` (append-only)."""
        ...

    def purge_run(
        self,
        project_key: str,
        story_id: str,
        run_id: str,
    ) -> int:
        """Loesche alle risk_window-Zeilen fuer (project_key, story_id, run_id)."""
        ...


@runtime_checkable
class PhaseStateProjectionRepository(Protocol):
    """Schreib-/Lese-/Purge-Adapter fuer ``phase_state_projection`` (FK-39 §39.7).

    Schema-Owner: pipeline-framework (FK-39).
    DB-Owner: telemetry-and-events via ProjectionAccessor.
    Hinweis: Schreib-Owner ist pipeline_engine.PhaseExecutor; hier nur
    Purge-Pfad fuer ProjectionAccessor.
    """

    def purge_run(
        self,
        project_key: str,
        story_id: str,
        run_id: str,
    ) -> int:
        """Loesche alle phase_state_projection-Zeilen fuer (project_key, story_id, run_id).

        FK-69 §69.10.1: ein vollstaendiger Reset entfernt alle Zeilen des
        betroffenen run_id. Gibt die Anzahl geloeschter Zeilen zurueck.
        """
        ...


@runtime_checkable
class GuardCounterPurgePort(Protocol):
    """Reset-purge seam for ``guard_invocation_counters`` (FK-61 §61.4.3 Trigger 4).

    The guard-counter scratchpad is owned by the KPI fact-store
    (``kpi_analytics.fact_store``), not by the FK-69 read-model accessor. To keep
    the counter purge part of the ONE reset path (``ProjectionAccessor.purge_run``)
    without coupling ``telemetry`` to ``kpi_analytics``, the accessor depends on
    this thin Protocol. The concrete adapter (wired in the composition root)
    delegates to ``GuardCounterService.flush_on_story_reset`` over the productive
    counter repository. ``guard_invocation_counters`` is keyed by
    ``(project_key, story_id, ...)`` and carries no ``run_id`` column (FK-61
    §61.4.3), so the purge is story-scoped — a full Story-Reset drains every
    weekly bucket of the story.
    """

    def purge_story(self, project_key: str, story_id: str) -> int:
        """Drain + delete every guard-counter row for ``(project_key, story_id)``.

        Returns the number of counter rows removed (FK-61 §61.4.3 Trigger 4).
        """
        ...


@runtime_checkable
class QALayerBatchWriter(Protocol):
    """Atomarer Batch-Schreibpfad fuer QA-Layer-Artefakte (FK-69 §69.4, AG3-035 #5).

    Fachlicher Eintrittspunkt fuer den QA-Subflow: schreibt qa_stage_results +
    qa_findings + die Quell-artifact_records in EINER Driver-Transaktion. Der
    ``ProjectionAccessor`` delegiert hierhin (``record_qa_layer_artifacts``),
    ohne die Transaktion zu zerteilen (Befund D Option i: Transaktion bleibt im
    Driver). Die konkrete Impl kapselt den facade-/Driver-Batch -- der Accessor
    in ``agentkit.telemetry`` kennt keine facade-Details (AC#7).
    """

    def persist_layer_artifacts(
        self,
        story_dir: Path,
        *,
        layer_results: tuple[LayerResult, ...],
        attempt_nr: int,
        projection_dir: Path | None = None,
    ) -> tuple[str, ...]:
        """Persistiere QA-Layer-Ergebnisse atomar; gibt die Artefakt-IDs zurueck."""
        ...


# ---------------------------------------------------------------------------
# ProjectionRepositories Dataclass (Dependency-Injection-Container)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ProjectionRepositories:
    """Buendelt alle FK-69-Repository-Instanzen fuer ``ProjectionAccessor``.

    Wird in der Composition-Root (``agentkit.bootstrap.composition_root``)
    instanziiert und per Dependency-Injection in ``ProjectionAccessor``
    eingereicht. Der Accessor darf NICHT selbst Repository-Implementierungen
    instantiieren (AC#7 -- kein direkter facade-Import im Accessor).

    Attributes:
        qa_stage_results: Adapter fuer ``qa_stage_results``.
        qa_findings: Adapter fuer ``qa_findings``.
        story_metrics: Adapter fuer ``story_metrics``.
        phase_state_projection: Adapter fuer ``phase_state_projection``.
        qa_layer_batch: Atomarer QA-Layer-Batch-Schreibpfad (fachlicher
            Eintrittspunkt des QA-Subflows via ``record_qa_layer_artifacts``).
        fc_incidents: Adapter fuer ``fc_incidents`` (AG3-028, FK-41 §41.3.1).
        risk_window: Adapter fuer ``risk_window`` (AG3-037, FK-68 §68.8).
        tasks: Adapter for ``tm_tasks`` and ``tm_task_links`` (FK-77).
        guard_counter_purge: Reset-purge seam for ``guard_invocation_counters``
            (AG3-081, FK-61 §61.4.3 Trigger 4). Drains the story's guard counters
            as part of the ONE reset path (``ProjectionAccessor.purge_run``).
    """

    qa_stage_results: QAStageResultsRepository
    qa_findings: QAFindingsRepository
    story_metrics: StoryMetricsRepository
    phase_state_projection: PhaseStateProjectionRepository
    qa_layer_batch: QALayerBatchWriter
    fc_incidents: FCIncidentsRepository
    risk_window: RiskWindowRepository
    tasks: TaskRepository
    guard_counter_purge: GuardCounterPurgePort


# ---------------------------------------------------------------------------
# Backend-Hilfsfunktionen (gemeinsam fuer konkrete Implementierungen)
# ---------------------------------------------------------------------------


def _is_postgres() -> bool:
    """Kanonische Backend-Selektion via load_state_backend_config (Befund C fix)."""
    from agentkit.state_backend.config import StateBackendKind, load_state_backend_config

    return load_state_backend_config().backend is StateBackendKind.POSTGRES


def _assert_sqlite_allowed() -> None:
    from agentkit.state_backend.config import ALLOW_SQLITE_ENV, _sqlite_allowed

    if not _sqlite_allowed():
        raise RuntimeError(
            "SQLite backend is disabled for this path. "
            f"Set {ALLOW_SQLITE_ENV}=1 only for narrow unit-test execution.",
        )


def _postgres_database_url() -> str:
    url = os.environ.get("AGENTKIT_STATE_DATABASE_URL", "")
    if not url:
        raise RuntimeError(
            "AGENTKIT_STATE_DATABASE_URL must be set when "
            "AGENTKIT_STATE_BACKEND=postgres"
        )
    return url


def _sqlite_db_path(store_dir: Path) -> Path:
    from agentkit.state_backend.config import versioned_sqlite_db_file
    from agentkit.state_backend.paths import state_backend_dir

    return state_backend_dir(store_dir) / versioned_sqlite_db_file()


@contextmanager
def _sqlite_connect(store_dir: Path) -> Iterator[sqlite3.Connection]:
    _assert_sqlite_allowed()
    db_path = _sqlite_db_path(store_dir)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


@contextmanager
def _postgres_connect() -> Iterator[Any]:
    import psycopg
    from psycopg.rows import dict_row

    from agentkit.state_backend import postgres_store
    from agentkit.state_backend.schema_bootstrap import ensure_versioned_schema

    conn = psycopg.connect(_postgres_database_url(), row_factory=dict_row)
    try:
        ensure_versioned_schema(conn)
        # Bootstrap via kanonischer Postgres-Schema-Owner (SINGLE SOURCE OF
        # TRUTH, symmetrisch zu _sqlite_connect_qa): garantiert, dass die
        # FK-69-Tabellen (inkl. fc_incidents, AG3-028) vorhanden sind, bevor der
        # Projektions-Repo-Adapter schreibt/liest. Idempotent (CREATE IF NOT
        # EXISTS). Verhindert "relation does not exist", wenn der Schreibpfad
        # ueber den ProjectionAccessor laeuft, ohne dass zuvor ein anderer
        # postgres_store-Call das Schema gebootet hat.
        postgres_store._ensure_schema(postgres_store._CompatConnection(conn))
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


@contextmanager
def _sqlite_connect_qa(store_dir: Path) -> Iterator[sqlite3.Connection]:
    """SQLite-Verbindung fuer qa_stage_results/qa_findings Repos.

    Befund B (AG3-035 Remediation): DDL-Ownership liegt jetzt in
    ``sqlite_store._ensure_schema_runtime_tables`` (SINGLE SOURCE OF TRUTH).
    Diese Funktion bootstrappt das komplette Schema via sqlite_store._ensure_schema,
    sodass die qa_*-Tabellen garantiert vorhanden sind.
    """
    from agentkit.state_backend import sqlite_store

    _assert_sqlite_allowed()
    db_path = _sqlite_db_path(store_dir)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path), timeout=30.0)
    conn.row_factory = sqlite3.Row
    # AG3-028 Codex-r2: busy_timeout FIRST, so a held write lock (z.B. die
    # BEGIN IMMEDIATE-Allokation in fc_incident_repository) andere Writer warten
    # laesst statt sofort SQLITE_BUSY zu werfen — race-sichere Erst-Allokation.
    conn.execute("PRAGMA busy_timeout = 30000")
    # Nur umschalten, wenn noch nicht WAL (der WAL-Switch achtet busy_timeout
    # nicht; wiederholtes Setzen wuerde unter Concurrency spuriose Locks werfen).
    current_mode = conn.execute("PRAGMA journal_mode").fetchone()
    if current_mode is None or str(current_mode[0]).lower() != "wal":
        conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys = ON")
    # Bootstrap via kanonischer Schema-Owner (SINGLE SOURCE OF TRUTH, Befund B)
    sqlite_store._ensure_schema(conn)
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Konkrete Implementierungen
# ---------------------------------------------------------------------------


class FacadeQAStageResultsRepository:
    """Duenner Adapter fuer qa_stage_results.

    Write und Purge: direktes SQL (kein bestehender facade-Einzelinsert-Pfad;
    Haupt-Batch-Pfad bleibt ``facade.record_layer_artifacts``).
    Read: delegiert an facade fuer Backward-Kompatibilitaet.

    Args:
        story_dir: Basisverzeichnis fuer SQLite; ignoriert bei Postgres.
    """

    def __init__(self, story_dir: Path | None = None) -> None:
        self._story_dir: Path = story_dir or Path.cwd()

    def write(self, record: QAStageResultRecord) -> None:
        """Persistiere einen einzelnen QAStageResultRecord.

        Hinweis: Der Haupt-Schreibpfad fuer qa_stage_results laeuft
        transaktional via ``facade.record_layer_artifacts`` (Batch-Insert inkl.
        artifact_records). Dieser Write-Pfad ist fuer direkte Einzelinserts
        des ProjectionAccessors vorgesehen.
        """
        row: dict[str, Any] = {
            "project_key": record.project_key,
            "story_id": record.story_id,
            "run_id": record.run_id,
            "attempt_no": record.attempt_no,
            "stage_id": record.stage_id,
            "layer": record.layer,
            "producer_component": record.producer_component,
            "status": record.status,
            "blocking": 1 if record.blocking else 0,
            "total_checks": record.total_checks,
            "failed_checks": record.failed_checks,
            "warning_checks": record.warning_checks,
            "artifact_id": record.artifact_id,
            "recorded_at": record.recorded_at.isoformat(),
        }
        if _is_postgres():
            self._pg_write(row)
        else:
            self._sqlite_write(row)

    def _sqlite_write(self, row: dict[str, Any]) -> None:
        with _sqlite_connect_qa(self._story_dir) as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO qa_stage_results (
                    project_key, story_id, run_id, attempt_no, stage_id, layer,
                    producer_component, status, blocking, total_checks,
                    failed_checks, warning_checks, artifact_id, recorded_at
                ) VALUES (
                    :project_key, :story_id, :run_id, :attempt_no, :stage_id,
                    :layer, :producer_component, :status, :blocking,
                    :total_checks, :failed_checks, :warning_checks,
                    :artifact_id, :recorded_at
                )
                """,
                row,
            )

    def _pg_write(self, row: dict[str, Any]) -> None:
        with _postgres_connect() as conn:
            self._pg_execute_stage_upsert(conn, row)

    def _pg_execute_stage_upsert(self, conn: Any, row: dict[str, Any]) -> None:
        """Fuehre qa_stage_results-Upsert auf bestehender Verbindung aus.

        Befund D (AG3-035 Remediation): Batch-Schreibpfad via Accessor-Repos.
        Kann vom Driver (persist_layer_artifact_rows) mit eigener Transaktion
        aufgerufen werden, ohne neue Connection zu oeffnen (SINGLE SOURCE OF TRUTH).

        Args:
            conn: Bestehende psycopg-Verbindung (Driver-Transaktion).
            row: Fertig serialisierte qa_stage_results-Zeile (dict).
        """
        from agentkit.state_backend import postgres_store

        postgres_store.pg_execute_stage_upsert(conn, row)

    def read(
        self,
        *,
        project_key: str | None = None,
        story_id: str | None = None,
        run_id: str | None = None,
        attempt_no: int | None = None,
        stage_id: str | None = None,
    ) -> list[QAStageResultRecord]:
        if _is_postgres():
            return self._pg_read(
                project_key=project_key,
                story_id=story_id,
                run_id=run_id,
                attempt_no=attempt_no,
                stage_id=stage_id,
            )
        return self._sqlite_read(
            project_key=project_key,
            story_id=story_id,
            run_id=run_id,
            attempt_no=attempt_no,
            stage_id=stage_id,
        )

    def _sqlite_read(
        self,
        *,
        project_key: str | None,
        story_id: str | None,
        run_id: str | None,
        attempt_no: int | None,
        stage_id: str | None,
    ) -> list[QAStageResultRecord]:
        from datetime import datetime

        from agentkit.verify_system.stage_registry.records import (
            QAStageResultRecord as _QAStageResultRecord,
        )

        clauses: list[str] = []
        params: list[object] = []
        if project_key is not None:
            clauses.append("project_key = ?")
            params.append(project_key)
        if story_id is not None:
            clauses.append("story_id = ?")
            params.append(story_id)
        if run_id is not None:
            clauses.append("run_id = ?")
            params.append(run_id)
        if attempt_no is not None:
            clauses.append("attempt_no = ?")
            params.append(attempt_no)
        if stage_id is not None:
            clauses.append("stage_id = ?")
            params.append(stage_id)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        with _sqlite_connect_qa(self._story_dir) as conn:
            rows = conn.execute(
                f"SELECT * FROM qa_stage_results {where}",
                tuple(params),
            ).fetchall()
        return [
            _QAStageResultRecord(
                project_key=str(r["project_key"]),
                story_id=str(r["story_id"]),
                run_id=str(r["run_id"]),
                attempt_no=int(r["attempt_no"]),
                stage_id=str(r["stage_id"]),
                layer=str(r["layer"]),
                producer_component=str(r["producer_component"]),
                status=str(r["status"]),
                blocking=bool(r["blocking"]),
                total_checks=int(r["total_checks"]),
                failed_checks=int(r["failed_checks"]),
                warning_checks=int(r["warning_checks"]),
                artifact_id=str(r["artifact_id"]),
                recorded_at=datetime.fromisoformat(str(r["recorded_at"])),
            )
            for r in rows
        ]

    def _pg_read(
        self,
        *,
        project_key: str | None,
        story_id: str | None,
        run_id: str | None,
        attempt_no: int | None,
        stage_id: str | None,
    ) -> list[QAStageResultRecord]:
        from agentkit.state_backend.store import facade, mappers

        rows = facade._backend_module().load_qa_stage_result_rows(
            self._story_dir,
            project_key=project_key,
            story_id=story_id,
            run_id=run_id,
            attempt_no=attempt_no,
            stage_id=stage_id,
        )
        return [mappers.qa_stage_result_row_to_record(row) for row in rows]

    def purge_run(self, project_key: str, story_id: str, run_id: str) -> int:
        """Loesche alle qa_stage_results fuer (project_key, story_id, run_id).

        FK-69 §69.10.1 Reset-Regel: aktives Loeschen, kein Query-Filter-Trick.
        """
        if _is_postgres():
            return self._pg_purge(project_key, story_id, run_id)
        return self._sqlite_purge(project_key, story_id, run_id)

    def _sqlite_purge(self, project_key: str, story_id: str, run_id: str) -> int:
        with _sqlite_connect_qa(self._story_dir) as conn:
            cursor = conn.execute(
                "DELETE FROM qa_stage_results "
                "WHERE project_key=? AND story_id=? AND run_id=?",
                (project_key, story_id, run_id),
            )
            return int(cursor.rowcount)

    def _pg_purge(self, project_key: str, story_id: str, run_id: str) -> int:
        with _postgres_connect() as conn:
            cursor = conn.execute(
                "DELETE FROM qa_stage_results "
                "WHERE project_key=%s AND story_id=%s AND run_id=%s",
                (project_key, story_id, run_id),
            )
            return int(cursor.rowcount)


class FacadeQAFindingsRepository:
    """Duenner Adapter fuer qa_findings.

    Args:
        story_dir: Basisverzeichnis fuer SQLite; ignoriert bei Postgres.
    """

    def __init__(self, story_dir: Path | None = None) -> None:
        self._story_dir: Path = story_dir or Path.cwd()

    def write(self, record: QAFindingRecord) -> None:
        """Persistiere einen QAFindingRecord."""
        row: dict[str, Any] = {
            "project_key": record.project_key,
            "story_id": record.story_id,
            "run_id": record.run_id,
            "attempt_no": record.attempt_no,
            "stage_id": record.stage_id,
            "finding_id": record.finding_id,
            "check_id": record.check_id,
            "status": record.status,
            "severity": record.severity,
            "blocking": 1 if record.blocking else 0,
            "source_component": record.source_component,
            "artifact_id": record.artifact_id,
            "occurred_at": record.occurred_at.isoformat(),
            "category": record.category,
            "reason": record.reason,
            "description": record.description,
            "detail": record.detail,
            "metadata_json": json.dumps(record.metadata, sort_keys=True),
        }
        if _is_postgres():
            self._pg_write(row)
        else:
            self._sqlite_write(row)

    def _sqlite_write(self, row: dict[str, Any]) -> None:
        with _sqlite_connect_qa(self._story_dir) as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO qa_findings (
                    project_key, story_id, run_id, attempt_no, stage_id,
                    finding_id, check_id, status, severity, blocking,
                    source_component, artifact_id, occurred_at,
                    category, reason, description, detail, metadata_json
                ) VALUES (
                    :project_key, :story_id, :run_id, :attempt_no, :stage_id,
                    :finding_id, :check_id, :status, :severity, :blocking,
                    :source_component, :artifact_id, :occurred_at,
                    :category, :reason, :description, :detail, :metadata_json
                )
                """,
                row,
            )

    def _pg_write(self, row: dict[str, Any]) -> None:
        with _postgres_connect() as conn:
            self._pg_execute_finding_upsert(conn, row)

    def _pg_execute_finding_upsert(self, conn: Any, row: dict[str, Any]) -> None:
        """Fuehre qa_findings-Upsert auf bestehender Verbindung aus.

        Befund D (AG3-035 Remediation): Batch-Schreibpfad via Accessor-Repos.
        Kann vom Driver (persist_layer_artifact_rows) mit eigener Transaktion
        aufgerufen werden, ohne neue Connection zu oeffnen (SINGLE SOURCE OF TRUTH).

        Args:
            conn: Bestehende psycopg-Verbindung (Driver-Transaktion).
            row: Fertig serialisierte qa_findings-Zeile (dict).
        """
        from agentkit.state_backend import postgres_store

        postgres_store.pg_execute_finding_upsert(conn, row)

    def _pg_delete_findings_for_scope(
        self,
        conn: Any,
        project_key: str,
        run_id: str,
        attempt_no: int,
        stage_id: str,
    ) -> None:
        """Loesche alte qa_findings fuer (project_key, run_id, attempt_no, stage_id).

        Befund D: Hilfsmethode fuer atomaren Batch-Schreibpfad im Driver.
        Loescht alte Findings vor dem Neuschreiben, damit keine veralteten
        Eintraege verbleiben (Idempotenz-Invariant des Batch-Writes).

        Args:
            conn: Bestehende psycopg-Verbindung (Driver-Transaktion).
            project_key: Projekt-Schluessel.
            run_id: Run-ID.
            attempt_no: Attempt-Nummer.
            stage_id: Layer/Stage-ID.
        """
        from agentkit.state_backend import postgres_store

        postgres_store.pg_delete_findings_for_scope(
            conn,
            project_key=project_key,
            run_id=run_id,
            attempt_no=attempt_no,
            stage_id=stage_id,
        )

    def read(
        self,
        *,
        project_key: str | None = None,
        story_id: str | None = None,
        run_id: str | None = None,
        attempt_no: int | None = None,
        stage_id: str | None = None,
    ) -> list[QAFindingRecord]:
        if _is_postgres():
            return self._pg_read(
                project_key=project_key,
                story_id=story_id,
                run_id=run_id,
                attempt_no=attempt_no,
                stage_id=stage_id,
            )
        return self._sqlite_read(
            project_key=project_key,
            story_id=story_id,
            run_id=run_id,
            attempt_no=attempt_no,
            stage_id=stage_id,
        )

    def _sqlite_read(
        self,
        *,
        project_key: str | None,
        story_id: str | None,
        run_id: str | None,
        attempt_no: int | None,
        stage_id: str | None,
    ) -> list[QAFindingRecord]:
        from datetime import datetime

        from agentkit.verify_system.stage_registry.records import (
            QAFindingRecord as _QAFindingRecord,
        )

        clauses: list[str] = []
        params: list[object] = []
        if project_key is not None:
            clauses.append("project_key = ?")
            params.append(project_key)
        if story_id is not None:
            clauses.append("story_id = ?")
            params.append(story_id)
        if run_id is not None:
            clauses.append("run_id = ?")
            params.append(run_id)
        if attempt_no is not None:
            clauses.append("attempt_no = ?")
            params.append(attempt_no)
        if stage_id is not None:
            clauses.append("stage_id = ?")
            params.append(stage_id)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        with _sqlite_connect_qa(self._story_dir) as conn:
            rows = conn.execute(
                f"SELECT * FROM qa_findings {where}",
                tuple(params),
            ).fetchall()
        return [
            _QAFindingRecord(
                project_key=str(r["project_key"]),
                story_id=str(r["story_id"]),
                run_id=str(r["run_id"]),
                attempt_no=int(r["attempt_no"]),
                stage_id=str(r["stage_id"]),
                finding_id=str(r["finding_id"]),
                check_id=str(r["check_id"]),
                status=str(r["status"]),
                severity=str(r["severity"]),
                blocking=bool(r["blocking"]),
                source_component=str(r["source_component"]),
                artifact_id=str(r["artifact_id"]),
                occurred_at=datetime.fromisoformat(str(r["occurred_at"])),
                category=str(r["category"]) if r["category"] is not None else None,
                reason=str(r["reason"]) if r["reason"] is not None else None,
                description=(
                    str(r["description"]) if r["description"] is not None else None
                ),
                detail=str(r["detail"]) if r["detail"] is not None else None,
                metadata=json.loads(str(r["metadata_json"])) if r["metadata_json"] else {},
            )
            for r in rows
        ]

    def _pg_read(
        self,
        *,
        project_key: str | None,
        story_id: str | None,
        run_id: str | None,
        attempt_no: int | None,
        stage_id: str | None,
    ) -> list[QAFindingRecord]:
        from agentkit.state_backend.store import facade, mappers

        rows = facade._backend_module().load_qa_finding_rows(
            self._story_dir,
            project_key=project_key,
            story_id=story_id,
            run_id=run_id,
            attempt_no=attempt_no,
            stage_id=stage_id,
        )
        return [mappers.qa_finding_row_to_record(row) for row in rows]

    def purge_run(self, project_key: str, story_id: str, run_id: str) -> int:
        """Loesche alle qa_findings fuer (project_key, story_id, run_id).

        FK-69 §69.10.1 Reset-Regel: aktives Loeschen, kein Query-Filter-Trick.
        """
        if _is_postgres():
            return self._pg_purge(project_key, story_id, run_id)
        return self._sqlite_purge(project_key, story_id, run_id)

    def _sqlite_purge(self, project_key: str, story_id: str, run_id: str) -> int:
        with _sqlite_connect_qa(self._story_dir) as conn:
            cursor = conn.execute(
                "DELETE FROM qa_findings "
                "WHERE project_key=? AND story_id=? AND run_id=?",
                (project_key, story_id, run_id),
            )
            return int(cursor.rowcount)

    def _pg_purge(self, project_key: str, story_id: str, run_id: str) -> int:
        with _postgres_connect() as conn:
            cursor = conn.execute(
                "DELETE FROM qa_findings "
                "WHERE project_key=%s AND story_id=%s AND run_id=%s",
                (project_key, story_id, run_id),
            )
            return int(cursor.rowcount)


class FacadeStoryMetricsRepository:
    """Duenner Adapter fuer story_metrics ueber facade-Funktionen.

    Args:
        story_dir: Basisverzeichnis fuer SQLite; ignoriert bei Postgres.
    """

    def __init__(self, story_dir: Path | None = None) -> None:
        self._story_dir: Path = story_dir or Path.cwd()

    def write(self, record: StoryMetricsRecord) -> None:
        """Persistiere (upsert) einen StoryMetricsRecord.

        FK-29 §29.6: PostMergeFinalization ist Schema-Owner + Writer via
        write_projection.
        """
        from agentkit.state_backend.store import facade

        facade.upsert_story_metrics(self._story_dir, record)

    def read(
        self,
        *,
        project_key: str | None = None,
        story_id: str | None = None,
        run_id: str | None = None,
    ) -> list[StoryMetricsRecord]:
        from agentkit.state_backend.store import facade

        return facade.load_story_metrics(
            self._story_dir,
            project_key=project_key,
            story_id=story_id,
            run_id=run_id,
        )

    def purge_run(self, project_key: str, story_id: str, run_id: str) -> int:
        """Loesche alle story_metrics fuer (project_key, story_id, run_id).

        FK-69 §69.10.1 Reset-Regel: aktives Loeschen, kein Query-Filter-Trick.
        """
        if _is_postgres():
            return self._pg_purge(project_key, story_id, run_id)
        return self._sqlite_purge(project_key, story_id, run_id)

    def _sqlite_purge(self, project_key: str, story_id: str, run_id: str) -> int:
        with _sqlite_connect(self._story_dir) as conn:
            cursor = conn.execute(
                "DELETE FROM story_metrics "
                "WHERE project_key=? AND story_id=? AND run_id=?",
                (project_key, story_id, run_id),
            )
            return int(cursor.rowcount)

    def _pg_purge(self, project_key: str, story_id: str, run_id: str) -> int:
        with _postgres_connect() as conn:
            cursor = conn.execute(
                "DELETE FROM story_metrics "
                "WHERE project_key=%s AND story_id=%s AND run_id=%s",
                (project_key, story_id, run_id),
            )
            return int(cursor.rowcount)


class FacadeRiskWindowRepository:
    """Duenner Adapter fuer ``risk_window`` (FK-68 §68.8, AG3-037).

    Schema-Owner + DB-Owner: telemetry-and-events. Append-only Rolling-Window
    von ``NormalizedEvent``s, das der (out-of-scope) GovernanceObserver spaeter
    scort. Schreibpfad ausschliesslich ueber
    ``ProjectionAccessor.record_risk_window_event``.

    Args:
        story_dir: Basisverzeichnis fuer SQLite; ignoriert bei Postgres.
    """

    def __init__(self, story_dir: Path | None = None) -> None:
        self._story_dir: Path = story_dir or Path.cwd()

    def record(self, event: NormalizedEvent) -> None:
        """Persistiere einen ``NormalizedEvent`` (append-only, idempotent).

        Args:
            event: Der zu persistierende normalisierte Risk-Window-Event.
        """
        row: dict[str, Any] = {
            "project_key": "",  # filled below from event scope
            "story_id": event.story_id,
            "run_id": event.run_id,
            "event_id": event.event_id,
            "risk_category": event.risk_category.value,
            "severity": event.severity.value,
            "observed_at": event.observed_at.isoformat(),
            "source_event_type": event.source_event_type.value,
            "payload_excerpt_json": json.dumps(event.payload_excerpt, sort_keys=True),
        }
        # NormalizedEvent carries no project_key (FK-68 events are run-scoped via
        # run_id); the rolling window keys on (project_key, run_id, event_id) for
        # mandant isolation. project_key is resolved from the run scope.
        row["project_key"] = self._resolve_project_key(event)
        if _is_postgres():
            self._pg_record(row)
        else:
            self._sqlite_record(row)

    def _resolve_project_key(self, event: NormalizedEvent) -> str:
        from agentkit.state_backend.store import resolve_runtime_scope

        scope = resolve_runtime_scope(self._story_dir)
        if scope.project_key and scope.story_id == event.story_id:
            return scope.project_key
        # FAIL-CLOSED: a risk-window row without a project_key would escape
        # mandant isolation (FK-68 §68.2.1 mandant rule).
        raise RuntimeError(
            "Cannot resolve project_key for risk_window event "
            f"{event.event_id!r} (story_id={event.story_id!r}); the rolling "
            "window must be mandant-scoped (FK-68 §68.2.1)."
        )

    def _sqlite_record(self, row: dict[str, Any]) -> None:
        with _sqlite_connect_qa(self._story_dir) as conn:
            conn.execute(
                """
                INSERT OR IGNORE INTO risk_window (
                    project_key, story_id, run_id, event_id, risk_category,
                    severity, observed_at, source_event_type, payload_excerpt_json
                ) VALUES (
                    :project_key, :story_id, :run_id, :event_id, :risk_category,
                    :severity, :observed_at, :source_event_type,
                    :payload_excerpt_json
                )
                """,
                row,
            )

    def _pg_record(self, row: dict[str, Any]) -> None:
        with _postgres_connect() as conn:
            conn.execute(
                """
                INSERT INTO risk_window (
                    project_key, story_id, run_id, event_id, risk_category,
                    severity, observed_at, source_event_type, payload_excerpt_json
                ) VALUES (
                    %(project_key)s, %(story_id)s, %(run_id)s, %(event_id)s,
                    %(risk_category)s, %(severity)s, %(observed_at)s,
                    %(source_event_type)s, %(payload_excerpt_json)s
                )
                ON CONFLICT (project_key, run_id, event_id) DO NOTHING
                """,
                row,
            )

    def purge_run(self, project_key: str, story_id: str, run_id: str) -> int:
        """Loesche alle risk_window-Zeilen fuer (project_key, story_id, run_id).

        FK-69 §69.10.1 Reset-Regel (analog): ein vollstaendiger Reset entfernt
        alle Risk-Window-Zeilen des betroffenen run_id. Gibt die Anzahl
        geloeschter Zeilen zurueck.
        """
        if _is_postgres():
            return self._pg_purge(project_key, story_id, run_id)
        return self._sqlite_purge(project_key, story_id, run_id)

    def _sqlite_purge(self, project_key: str, story_id: str, run_id: str) -> int:
        with _sqlite_connect_qa(self._story_dir) as conn:
            cursor = conn.execute(
                "DELETE FROM risk_window "
                "WHERE project_key=? AND story_id=? AND run_id=?",
                (project_key, story_id, run_id),
            )
            return int(cursor.rowcount)

    def _pg_purge(self, project_key: str, story_id: str, run_id: str) -> int:
        with _postgres_connect() as conn:
            cursor = conn.execute(
                "DELETE FROM risk_window "
                "WHERE project_key=%s AND story_id=%s AND run_id=%s",
                (project_key, story_id, run_id),
            )
            return int(cursor.rowcount)


class FacadePhaseStateProjectionRepository:
    """Duenner Adapter fuer phase_state_projection.

    Schema-Owner: pipeline-framework (FK-39 §39.7).
    Dieser Adapter stellt nur den Purge-Pfad bereit (kein Write: schreibt
    pipeline_engine.PhaseExecutor; kein Read via ProjectionAccessor derzeit).

    Args:
        story_dir: Basisverzeichnis fuer SQLite; ignoriert bei Postgres.
    """

    def __init__(self, story_dir: Path | None = None) -> None:
        self._story_dir: Path = story_dir or Path.cwd()

    def purge_run(self, project_key: str, story_id: str, run_id: str) -> int:
        """Loesche alle phase_state_projection-Zeilen fuer (project_key, story_id, run_id).

        FK-69 §69.10.1 Reset-Regel: aktives Loeschen.
        """
        if _is_postgres():
            return self._pg_purge(project_key, story_id, run_id)
        return self._sqlite_purge(project_key, story_id, run_id)

    def _sqlite_purge(self, project_key: str, story_id: str, run_id: str) -> int:
        with _sqlite_connect(self._story_dir) as conn:
            table_exists = bool(
                conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' "
                    "AND name='phase_state_projection'"
                ).fetchone()
            )
            if not table_exists:
                return 0
            # Check available columns for flexibility across schema versions
            columns = {
                str(row[1])
                for row in conn.execute(
                    "PRAGMA table_info(phase_state_projection)"
                ).fetchall()
            }
            if "run_id" in columns and "project_key" in columns:
                cursor = conn.execute(
                    "DELETE FROM phase_state_projection "
                    "WHERE project_key=? AND story_id=? AND run_id=?",
                    (project_key, story_id, run_id),
                )
            else:
                cursor = conn.execute(
                    "DELETE FROM phase_state_projection WHERE story_id=?",
                    (story_id,),
                )
            return int(cursor.rowcount)

    def _pg_purge(self, project_key: str, story_id: str, run_id: str) -> int:
        with _postgres_connect() as conn:
            cursor = conn.execute(
                "DELETE FROM phase_state_projection "
                "WHERE project_key=%s AND story_id=%s AND run_id=%s",
                (project_key, story_id, run_id),
            )
            return int(cursor.rowcount)


class FacadeQALayerBatchWriter:
    """Atomarer QA-Layer-Batch-Adapter (FK-69 §69.4, AG3-035 #5).

    Kapselt ``facade.record_layer_artifacts`` -- den bestehenden atomaren
    Driver-Batch (qa_stage_results + qa_findings + artifact_records in EINER
    Transaktion). Liegt in der DB-Schicht; der ``ProjectionAccessor`` in
    ``agentkit.telemetry`` delegiert hierhin, ohne facade direkt zu kennen (AC#7).
    """

    def persist_layer_artifacts(
        self,
        story_dir: Path,
        *,
        layer_results: tuple[LayerResult, ...],
        attempt_nr: int,
        projection_dir: Path | None = None,
    ) -> tuple[str, ...]:
        """Delegiere an den atomaren facade-/Driver-Batch und gib Artefakt-IDs zurueck."""
        from agentkit.state_backend.store.facade import record_layer_artifacts

        return record_layer_artifacts(
            story_dir,
            layer_results=layer_results,
            attempt_nr=attempt_nr,
            projection_dir=projection_dir,
        )


class StateBackendGuardCounterPurgeAdapter:
    """Reset-purge adapter for ``guard_invocation_counters`` (AG3-081, FK-61 §61.4.3).

    Delegates the Trigger-4 (full Story-Reset) counter drain to the kpi-owned
    ``GuardCounterService.flush_on_story_reset`` over the productive
    ``StateBackendGuardCounterRepository``. This adapter is the single seam that
    lets ``ProjectionAccessor.purge_run`` purge the guard counters as part of the
    ONE reset path, without ``telemetry`` importing ``kpi_analytics`` directly (the
    composition-root layer owns both packages and the wiring).

    Args:
        store_dir: Base directory for the SQLite counter store (Postgres ignores
            it).
    """

    def __init__(self, store_dir: Path | None = None) -> None:
        self._store_dir: Path = store_dir or Path.cwd()

    def purge_story(self, project_key: str, story_id: str) -> int:
        """Drain + delete every guard-counter row for ``(project_key, story_id)``."""
        from agentkit.kpi_analytics import GuardCounterService
        from agentkit.state_backend.store.guard_counter_repository import (
            StateBackendGuardCounterRepository,
        )

        drained = GuardCounterService(
            StateBackendGuardCounterRepository(self._store_dir)
        ).flush_on_story_reset(project_key, story_id)
        return len(drained)


def build_projection_repositories(store_dir: Path | None = None) -> ProjectionRepositories:
    """Erzeugt eine vollstaendig verdrahtete ``ProjectionRepositories``-Instanz.

    Composition-Root-Hilfsfunktion, genutzt von
    ``agentkit.bootstrap.composition_root.build_projection_accessor``.

    Args:
        store_dir: Basisverzeichnis des State-Backends. Nur fuer SQLite relevant;
            Postgres ignoriert den Pfad.

    Returns:
        ``ProjectionRepositories`` mit allen konkreten Adapter-Instanzen.
    """
    from agentkit.state_backend.store.fc_incident_repository import (
        StateBackendFCIncidentsRepository,
    )
    from agentkit.state_backend.store.task_repository import StateBackendTaskRepository

    return ProjectionRepositories(
        qa_stage_results=FacadeQAStageResultsRepository(store_dir),
        qa_findings=FacadeQAFindingsRepository(store_dir),
        story_metrics=FacadeStoryMetricsRepository(store_dir),
        phase_state_projection=FacadePhaseStateProjectionRepository(store_dir),
        qa_layer_batch=FacadeQALayerBatchWriter(),
        fc_incidents=StateBackendFCIncidentsRepository(store_dir),
        risk_window=FacadeRiskWindowRepository(store_dir),
        tasks=StateBackendTaskRepository(store_dir),
        guard_counter_purge=StateBackendGuardCounterPurgeAdapter(store_dir),
    )


__all__ = [
    "FacadePhaseStateProjectionRepository",
    "FacadeQAFindingsRepository",
    "FacadeQALayerBatchWriter",
    "FacadeQAStageResultsRepository",
    "FacadeRiskWindowRepository",
    "FacadeStoryMetricsRepository",
    "GuardCounterPurgePort",
    "PhaseStateProjectionRepository",
    "StateBackendGuardCounterPurgeAdapter",
    "ProjectionRepositories",
    "QAFindingsRepository",
    "QALayerBatchWriter",
    "QAStageResultsRepository",
    "RiskWindowRepository",
    "StoryMetricsRepository",
    "build_projection_repositories",
]
