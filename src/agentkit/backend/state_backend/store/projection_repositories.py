"""ProjectionRepositories: protocol definitions and thin adapters for FK-69 tables.

Each repository protocol defines the write and read boundary for one
FK-69 table family. The concrete implementations encapsulate the existing
facade functions without introducing a new operative truth.

Architecture Conformance (AC#7):
- ``ProjectionAccessor`` in ``agentkit.backend.telemetry`` may NOT import directly from
  ``agentkit.backend.state_backend.store.facade``.
- Instead these repository protocols are injected via ``ProjectionRepositories``
  (a dependency-injection dataclass).
- Concrete implementations live here (DB layer), the accessor in ``telemetry``.

Sources:
- FK-69 §69.3 -- table scope
- FK-69 §69.4 -- write ownership and writer components
- FK-69 §69.10.1 -- reset-purge rule (run_id-scoped)
- AG3-035 §2.1.1 -- ProjectionRepositories dataclass
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
    from datetime import datetime

    from agentkit.backend.closure.post_merge_finalization.records import StoryMetricsRecord
    from agentkit.backend.state_backend.store.fc_check_proposal_repository import (
        FcCheckProposalRepository,
    )
    from agentkit.backend.state_backend.store.fc_incident_repository import (
        FCIncidentsRepository,
    )
    from agentkit.backend.state_backend.store.fc_pattern_repository import (
        FcPatternRepository,
    )
    from agentkit.backend.state_backend.store.task_repository import TaskRepository
    from agentkit.backend.telemetry.risk_window.normalized_event import NormalizedEvent
    from agentkit.backend.verify_system.protocols import LayerResult
    from agentkit.backend.verify_system.stage_registry.records import (
        QACheckOutcomeRecord,
        QAFindingRecord,
        QAStageResultRecord,
    )


# ---------------------------------------------------------------------------
# Shared parametrized WHERE-clause fragments (single source; reused across the
# projection read filters so the same predicate literal is not duplicated, S1192).
# ---------------------------------------------------------------------------
_WHERE_PROJECT_KEY = "project_key = ?"
_WHERE_STORY_ID = "story_id = ?"
_WHERE_RUN_ID = "run_id = ?"
_WHERE_ATTEMPT_NO = "attempt_no = ?"
_WHERE_STAGE_ID = "stage_id = ?"


# ---------------------------------------------------------------------------
# Repository Protocols
# ---------------------------------------------------------------------------


@runtime_checkable
class QAStageResultsRepository(Protocol):
    """Write/read/purge adapter for ``qa_stage_results`` (FK-69 §69.6).

    Schema owner: verify-system (FK-33).
    DB owner: telemetry-and-events via ProjectionAccessor.
    """

    def write(self, record: QAStageResultRecord) -> None:
        """Persist a single QAStageResultRecord."""
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
        """Load QAStageResultRecords with optional filters."""
        ...

    def purge_run(
        self,
        project_key: str,
        story_id: str,
        run_id: str,
    ) -> int:
        """Delete all qa_stage_results for (project_key, story_id, run_id).

        FK-69 §69.10.1: a full reset removes all rows of the
        affected run_id. Returns the number of deleted rows.
        """
        ...


@runtime_checkable
class QAFindingsRepository(Protocol):
    """Write/read/purge adapter for ``qa_findings`` (FK-69 §69.7).

    Schema owner: verify-system (FK-33).
    DB owner: telemetry-and-events via ProjectionAccessor.
    """

    def write(self, record: QAFindingRecord) -> None:
        """Persist a single QAFindingRecord."""
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
        """Load QAFindingRecords with optional filters."""
        ...

    def purge_run(
        self,
        project_key: str,
        story_id: str,
        run_id: str,
    ) -> int:
        """Delete all qa_findings for (project_key, story_id, run_id).

        FK-69 §69.10.1: a full reset removes all rows of the
        affected run_id. Returns the number of deleted rows.
        """
        ...


@runtime_checkable
class QACheckOutcomesRepository(Protocol):
    """Write/read/purge adapter for ``qa_check_outcomes`` (FK-69 §69.15, AG3-108).

    Schema owner: verify-system.
    DB owner: telemetry-and-events via ProjectionAccessor.
    """

    def write(self, record: QACheckOutcomeRecord) -> None:
        """Persist a single QACheckOutcomeRecord."""
        ...

    def read(
        self,
        *,
        project_key: str,
        story_id: str | None = None,
        run_id: str | None = None,
        attempt_no: int | None = None,
        stage_id: str | None = None,
        check_id: str | None = None,
        since_days: int | None = None,
        check_proposal_ref: str | None = None,
        _now: datetime | None = None,
    ) -> list[QACheckOutcomeRecord]:
        """Load QACheckOutcomeRecords with optional filters.

        Args:
            project_key: Mandatory project scope (fail-closed on empty).
            story_id: Optional story-ID filter.
            run_id: Optional run-ID filter.
            attempt_no: Optional attempt number filter.
            stage_id: Optional stage-ID exact-match filter.
            check_id: Optional check-ID exact-match filter.
            since_days: Optional UTC window: ``occurred_at >= now - since_days``.
                0 = today only; negative = treated as 0.
            check_proposal_ref: Optional exact-match filter on the FC-check proposal
                reference (``CHK-NNNN``); added in AG3-078.
            _now: Injectable UTC "now" for deterministic tests. Defaults to
                ``datetime.now(UTC)`` when ``since_days`` is set.
        """
        ...

    def purge_run(
        self,
        project_key: str,
        story_id: str,
        run_id: str,
    ) -> int:
        """Delete all qa_check_outcomes for (project_key, story_id, run_id).

        FK-69 §69.10.1: a full reset removes all rows of the
        affected run_id. Returns the number of deleted rows.
        """
        ...


@runtime_checkable
class StoryMetricsRepository(Protocol):
    """Write/read/purge adapter for ``story_metrics`` (FK-69 §69.8).

    Schema owner: story-closure (FK-29 §29.6).
    DB owner: telemetry-and-events via ProjectionAccessor.
    """

    def write(self, record: StoryMetricsRecord) -> None:
        """Persist (upsert) a StoryMetricsRecord."""
        ...

    def read(
        self,
        *,
        project_key: str | None = None,
        story_id: str | None = None,
        run_id: str | None = None,
    ) -> list[StoryMetricsRecord]:
        """Load StoryMetricsRecords with optional filters."""
        ...

    def purge_run(
        self,
        project_key: str,
        story_id: str,
        run_id: str,
    ) -> int:
        """Delete all story_metrics for (project_key, story_id, run_id).

        FK-69 §69.10.1: a full reset removes all rows of the
        affected run_id. Returns the number of deleted rows.
        """
        ...


@runtime_checkable
class RiskWindowRepository(Protocol):
    """Write/purge adapter for ``risk_window`` (FK-68 §68.8, AG3-037).

    Schema owner + DB owner: telemetry-and-events. Append-only rolling window
    of ``NormalizedEvent``s; the write path is exclusively via
    ``ProjectionAccessor.record_risk_window_event``.
    """

    def record(self, event: NormalizedEvent) -> None:
        """Persist a ``NormalizedEvent`` (append-only)."""
        ...

    def purge_run(
        self,
        project_key: str,
        story_id: str,
        run_id: str,
    ) -> int:
        """Delete all risk_window rows for (project_key, story_id, run_id)."""
        ...


@runtime_checkable
class PhaseStateProjectionRepository(Protocol):
    """Write/read/purge adapter for ``phase_state_projection`` (FK-39 §39.7).

    Schema owner: pipeline-framework (FK-39).
    DB owner: telemetry-and-events via ProjectionAccessor.
    Note: the write owner is pipeline_engine.PhaseExecutor; here only the
    purge path for ProjectionAccessor.
    """

    def purge_run(
        self,
        project_key: str,
        story_id: str,
        run_id: str,
    ) -> int:
        """Delete all phase_state_projection rows for (project_key, story_id, run_id).

        FK-69 §69.10.1: a full reset removes all rows of the
        affected run_id. Returns the number of deleted rows.
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
    """Atomic batch write path for QA-layer artifacts (FK-69 §69.4, AG3-035 #5).

    The domain entry point for the QA-subflow: writes qa_stage_results +
    qa_findings + the source artifact_records in ONE driver transaction. The
    ``ProjectionAccessor`` delegates here (``record_qa_layer_artifacts``),
    without splitting the transaction (finding D option i: the transaction stays
    in the driver). The concrete impl encapsulates the facade/driver batch -- the
    accessor in ``agentkit.backend.telemetry`` knows no facade details (AC#7).
    """

    def persist_layer_artifacts(
        self,
        story_dir: Path,
        *,
        layer_results: tuple[LayerResult, ...],
        attempt_nr: int,
        projection_dir: Path | None = None,
    ) -> tuple[str, ...]:
        """Persist QA-layer results atomically; returns the artifact IDs."""
        ...


# ---------------------------------------------------------------------------
# ProjectionRepositories Dataclass (Dependency-Injection-Container)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ProjectionRepositories:
    """Bundles all FK-69 repository instances for ``ProjectionAccessor``.

    Instantiated in the composition root (``agentkit.backend.bootstrap.composition_root``)
    and handed into ``ProjectionAccessor`` via dependency injection. The
    accessor may NOT instantiate repository implementations itself
    (AC#7 -- no direct facade import in the accessor).

    Attributes:
        qa_stage_results: Adapter for ``qa_stage_results``.
        qa_findings: Adapter for ``qa_findings``.
        qa_check_outcomes: Adapter for ``qa_check_outcomes`` (AG3-108, FK-69 §69.15).
        story_metrics: Adapter for ``story_metrics``.
        phase_state_projection: Adapter for ``phase_state_projection``.
        qa_layer_batch: Atomic QA-layer batch write path (the domain
            entry point of the QA-subflow via ``record_qa_layer_artifacts``).
        fc_incidents: Adapter for ``fc_incidents`` (AG3-028, FK-41 §41.3.1).
        risk_window: Adapter for ``risk_window`` (AG3-037, FK-68 §68.8).
        tasks: Adapter for ``tm_tasks`` and ``tm_task_links`` (FK-77).
        guard_counter_purge: Reset-purge seam for ``guard_invocation_counters``
            (AG3-081, FK-61 §61.4.3 Trigger 4). Drains the story's guard counters
            as part of the ONE reset path (``ProjectionAccessor.purge_run``).
        fc_patterns: Adapter for ``fc_patterns`` (AG3-078, FK-41 §41.3.2).
        fc_check_proposals: Adapter for ``fc_check_proposals`` (AG3-078, FK-41 §41.3.3).
    """

    qa_stage_results: QAStageResultsRepository
    qa_findings: QAFindingsRepository
    qa_check_outcomes: QACheckOutcomesRepository
    story_metrics: StoryMetricsRepository
    phase_state_projection: PhaseStateProjectionRepository
    qa_layer_batch: QALayerBatchWriter
    fc_incidents: FCIncidentsRepository
    risk_window: RiskWindowRepository
    tasks: TaskRepository
    guard_counter_purge: GuardCounterPurgePort
    fc_patterns: FcPatternRepository
    fc_check_proposals: FcCheckProposalRepository


# ---------------------------------------------------------------------------
# Backend helper functions (shared by the concrete implementations)
# ---------------------------------------------------------------------------


def _is_postgres() -> bool:
    """Canonical backend selection via load_state_backend_config (finding C fix)."""
    from agentkit.backend.state_backend.config import StateBackendKind, load_state_backend_config

    return load_state_backend_config().backend is StateBackendKind.POSTGRES


def _assert_sqlite_allowed() -> None:
    from agentkit.backend.state_backend.config import ALLOW_SQLITE_ENV, _sqlite_allowed

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
    from agentkit.backend.state_backend.config import versioned_sqlite_db_file
    from agentkit.backend.state_backend.paths import state_backend_dir

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

    from agentkit.backend.state_backend import postgres_store
    from agentkit.backend.state_backend.schema_bootstrap import ensure_versioned_schema

    conn = psycopg.connect(_postgres_database_url(), row_factory=dict_row)
    try:
        ensure_versioned_schema(conn)
        # Bootstrap via the canonical Postgres schema owner (SINGLE SOURCE OF
        # TRUTH, symmetric to _sqlite_connect_qa): guarantees the
        # FK-69 tables (incl. fc_incidents, AG3-028) exist before the
        # projection repo adapter writes/reads. Idempotent (CREATE IF NOT
        # EXISTS). Prevents "relation does not exist" when the write path
        # runs via the ProjectionAccessor without a prior other
        # postgres_store call having booted the schema.
        postgres_store._ensure_schema_once(postgres_store._CompatConnection(conn))
        conn.commit()
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


@contextmanager
def _sqlite_connect_qa(store_dir: Path) -> Iterator[sqlite3.Connection]:
    """SQLite connection for the qa_stage_results/qa_findings repos.

    Finding B (AG3-035 remediation): DDL ownership now lives in
    ``sqlite_store._ensure_schema_runtime_tables`` (SINGLE SOURCE OF TRUTH).
    This function bootstraps the complete schema via sqlite_store._ensure_schema,
    so the qa_* tables are guaranteed to exist.
    """
    from agentkit.backend.state_backend import sqlite_store

    _assert_sqlite_allowed()
    db_path = _sqlite_db_path(store_dir)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path), timeout=30.0)
    conn.row_factory = sqlite3.Row
    # AG3-028 Codex-r2: busy_timeout FIRST, so a held write lock (e.g. the
    # BEGIN IMMEDIATE allocation in fc_incident_repository) makes other writers
    # wait instead of immediately raising SQLITE_BUSY — race-safe first allocation.
    conn.execute("PRAGMA busy_timeout = 30000")
    # Only switch when not already WAL (the WAL switch does not honour
    # busy_timeout; setting it repeatedly would raise spurious locks under concurrency).
    current_mode = conn.execute("PRAGMA journal_mode").fetchone()
    if current_mode is None or str(current_mode[0]).lower() != "wal":
        conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys = ON")
    # Bootstrap via the canonical schema owner (SINGLE SOURCE OF TRUTH, finding B)
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
# Concrete implementations
# ---------------------------------------------------------------------------


class FacadeQAStageResultsRepository:
    """Thin adapter for qa_stage_results.

    Write and purge: direct SQL (no existing facade single-insert path;
    the main batch path stays ``facade.record_layer_artifacts``).
    Read: delegates to the facade for backward compatibility.

    Args:
        story_dir: Base directory for SQLite; ignored for Postgres.
    """

    def __init__(self, story_dir: Path | None = None) -> None:
        self._story_dir: Path = story_dir or Path.cwd()

    def write(self, record: QAStageResultRecord) -> None:
        """Persist a single QAStageResultRecord.

        Note: the main write path for qa_stage_results runs
        transactionally via ``facade.record_layer_artifacts`` (batch insert incl.
        artifact_records). This write path is intended for direct single inserts
        from the ProjectionAccessor.
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
        """Execute the qa_stage_results upsert on an existing connection.

        Finding D (AG3-035 remediation): batch write path via the accessor repos.
        Can be called by the driver (persist_layer_artifact_rows) with its own
        transaction without opening a new connection (SINGLE SOURCE OF TRUTH).

        Args:
            conn: Existing psycopg connection (driver transaction).
            row: Fully serialized qa_stage_results row (dict).
        """
        from agentkit.backend.state_backend import postgres_store

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

        from agentkit.backend.verify_system.stage_registry.records import (
            QAStageResultRecord as _QAStageResultRecord,
        )

        clauses: list[str] = []
        params: list[object] = []
        if project_key is not None:
            clauses.append(_WHERE_PROJECT_KEY)
            params.append(project_key)
        if story_id is not None:
            clauses.append(_WHERE_STORY_ID)
            params.append(story_id)
        if run_id is not None:
            clauses.append(_WHERE_RUN_ID)
            params.append(run_id)
        if attempt_no is not None:
            clauses.append(_WHERE_ATTEMPT_NO)
            params.append(attempt_no)
        if stage_id is not None:
            clauses.append(_WHERE_STAGE_ID)
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
        from agentkit.backend.state_backend.store import facade, mappers

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
        """Delete all qa_stage_results for (project_key, story_id, run_id).

        FK-69 §69.10.1 reset rule: active deletion, no query-filter trick.
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
    """Thin adapter for qa_findings.

    Args:
        story_dir: Base directory for SQLite; ignored for Postgres.
    """

    def __init__(self, story_dir: Path | None = None) -> None:
        self._story_dir: Path = story_dir or Path.cwd()

    def write(self, record: QAFindingRecord) -> None:
        """Persist a QAFindingRecord."""
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
        """Execute the qa_findings upsert on an existing connection.

        Finding D (AG3-035 remediation): batch write path via the accessor repos.
        Can be called by the driver (persist_layer_artifact_rows) with its own
        transaction without opening a new connection (SINGLE SOURCE OF TRUTH).

        Args:
            conn: Existing psycopg connection (driver transaction).
            row: Fully serialized qa_findings row (dict).
        """
        from agentkit.backend.state_backend import postgres_store

        postgres_store.pg_execute_finding_upsert(conn, row)

    def _pg_delete_findings_for_scope(
        self,
        conn: Any,
        project_key: str,
        run_id: str,
        attempt_no: int,
        stage_id: str,
    ) -> None:
        """Delete old qa_findings for (project_key, run_id, attempt_no, stage_id).

        Finding D: helper method for the atomic batch write path in the driver.
        Deletes old findings before re-writing so no stale
        entries remain (the idempotency invariant of the batch write).

        Args:
            conn: Existing psycopg connection (driver transaction).
            project_key: Project key.
            run_id: Run id.
            attempt_no: Attempt number.
            stage_id: Layer/stage id.
        """
        from agentkit.backend.state_backend import postgres_store

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

        from agentkit.backend.verify_system.stage_registry.records import (
            QAFindingRecord as _QAFindingRecord,
        )

        clauses: list[str] = []
        params: list[object] = []
        if project_key is not None:
            clauses.append(_WHERE_PROJECT_KEY)
            params.append(project_key)
        if story_id is not None:
            clauses.append(_WHERE_STORY_ID)
            params.append(story_id)
        if run_id is not None:
            clauses.append(_WHERE_RUN_ID)
            params.append(run_id)
        if attempt_no is not None:
            clauses.append(_WHERE_ATTEMPT_NO)
            params.append(attempt_no)
        if stage_id is not None:
            clauses.append(_WHERE_STAGE_ID)
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
        from agentkit.backend.state_backend.store import facade, mappers

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
        """Delete all qa_findings for (project_key, story_id, run_id).

        FK-69 §69.10.1 reset rule: active deletion, no query-filter trick.
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
    """Thin adapter for story_metrics over facade functions.

    Args:
        story_dir: Base directory for SQLite; ignored for Postgres.
    """

    def __init__(self, story_dir: Path | None = None) -> None:
        self._story_dir: Path = story_dir or Path.cwd()

    def write(self, record: StoryMetricsRecord) -> None:
        """Persist (upsert) a StoryMetricsRecord.

        FK-29 §29.6: PostMergeFinalization is schema owner + writer via
        write_projection.
        """
        from agentkit.backend.state_backend.store import facade

        facade.upsert_story_metrics(self._story_dir, record)

    def read(
        self,
        *,
        project_key: str | None = None,
        story_id: str | None = None,
        run_id: str | None = None,
    ) -> list[StoryMetricsRecord]:
        from agentkit.backend.state_backend.store import facade

        return facade.load_story_metrics(
            self._story_dir,
            project_key=project_key,
            story_id=story_id,
            run_id=run_id,
        )

    def purge_run(self, project_key: str, story_id: str, run_id: str) -> int:
        """Delete all story_metrics for (project_key, story_id, run_id).

        FK-69 §69.10.1 reset rule: active deletion, no query-filter trick.
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
    """Thin adapter for ``risk_window`` (FK-68 §68.8, AG3-037).

    Schema owner + DB owner: telemetry-and-events. Append-only rolling window
    of ``NormalizedEvent``s that the (out-of-scope) GovernanceObserver scores
    later. The write path is exclusively via
    ``ProjectionAccessor.record_risk_window_event``.

    Args:
        story_dir: Base directory for SQLite; ignored for Postgres.
    """

    def __init__(self, story_dir: Path | None = None) -> None:
        self._story_dir: Path = story_dir or Path.cwd()

    def record(self, event: NormalizedEvent) -> None:
        """Persist a ``NormalizedEvent`` (append-only, idempotent).

        Args:
            event: The normalized risk-window event to persist.
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
        from agentkit.backend.state_backend.store import resolve_runtime_scope

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
        """Delete all risk_window rows for (project_key, story_id, run_id).

        FK-69 §69.10.1 reset rule (analogous): a full reset removes
        all risk-window rows of the affected run_id. Returns the number of
        deleted rows.
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
    """Thin adapter for phase_state_projection.

    Schema owner: pipeline-framework (FK-39 §39.7).
    This adapter provides only the purge path (no write: pipeline_engine.
    PhaseExecutor writes; no read via ProjectionAccessor currently).

    Args:
        story_dir: Base directory for SQLite; ignored for Postgres.
    """

    def __init__(self, story_dir: Path | None = None) -> None:
        self._story_dir: Path = story_dir or Path.cwd()

    def purge_run(self, project_key: str, story_id: str, run_id: str) -> int:
        """Delete all phase_state_projection rows for (project_key, story_id, run_id).

        FK-69 §69.10.1 reset rule: active deletion.
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
    """Atomic QA-layer batch adapter (FK-69 §69.4, AG3-035 #5).

    Encapsulates ``facade.record_layer_artifacts`` -- the existing atomic
    driver batch (qa_stage_results + qa_findings + artifact_records in ONE
    transaction). Lives in the DB layer; the ``ProjectionAccessor`` in
    ``agentkit.backend.telemetry`` delegates here without knowing the facade directly (AC#7).
    """

    def persist_layer_artifacts(
        self,
        story_dir: Path,
        *,
        layer_results: tuple[LayerResult, ...],
        attempt_nr: int,
        projection_dir: Path | None = None,
    ) -> tuple[str, ...]:
        """Delegate to the atomic facade/driver batch and return the artifact IDs."""
        from agentkit.backend.state_backend.store.facade import record_layer_artifacts

        return record_layer_artifacts(
            story_dir,
            layer_results=layer_results,
            attempt_nr=attempt_nr,
            projection_dir=projection_dir,
        )


def _parse_occurred_at(
    raw: str,
    utc_tz: Any,
    datetime_cls: Any,
) -> Any:
    """Parse a SQLite-stored ISO-8601 timestamp as a UTC-aware datetime.

    SQLite stores timestamps as plain ISO strings (no trailing Z/+00:00).
    This helper attaches UTC tz-info when absent.
    """
    dt = datetime_cls.fromisoformat(raw)
    if dt.tzinfo is None:
        return dt.replace(tzinfo=utc_tz)
    return dt


class FacadeQACheckOutcomesRepository:
    """Thin adapter for ``qa_check_outcomes`` (FK-69 §69.15, AG3-108).

    Args:
        story_dir: Base directory for SQLite; ignored for Postgres.
    """

    def __init__(self, story_dir: Path | None = None) -> None:
        self._story_dir: Path = story_dir or Path.cwd()

    def write(self, record: QACheckOutcomeRecord) -> None:
        """Persist a QACheckOutcomeRecord (upsert on PK conflict)."""
        from datetime import datetime

        from agentkit.backend.verify_system.stage_registry.records import (
            QACheckOutcomeRecord as _QACheckOutcomeRecord,
        )

        if not isinstance(record, _QACheckOutcomeRecord):
            raise TypeError(f"Expected QACheckOutcomeRecord, got {type(record)!r}")
        if not record.project_key:
            raise ValueError(
                "QACheckOutcomeRecord.project_key must not be empty "
                "(FK-69 §69.15.6 rule 7 fail-closed)"
            )
        if not record.check_id or not record.check_id.strip():
            raise ValueError(
                "QACheckOutcomeRecord.check_id must not be blank or whitespace-only "
                "(FK-69 §69.11 rule 6 / §69.15.6 fail-closed)"
            )
        row: dict[str, object] = {
            "project_key": record.project_key,
            "story_id": record.story_id,
            "run_id": record.run_id,
            "stage_id": record.stage_id,
            "attempt_no": record.attempt_no,
            "check_id": record.check_id,
            "outcome": str(record.outcome),
            "occurred_at": (
                record.occurred_at.isoformat()
                if isinstance(record.occurred_at, datetime)
                else str(record.occurred_at)
            ),
            "check_proposal_ref": record.check_proposal_ref,
            "override_id": record.override_id,
        }
        if _is_postgres():
            self._pg_write(row)
        else:
            self._sqlite_write(row)

    def _sqlite_write(self, row: dict[str, object]) -> None:
        with _sqlite_connect_qa(self._story_dir) as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO qa_check_outcomes (
                    project_key, story_id, run_id, stage_id, attempt_no, check_id,
                    outcome, occurred_at, check_proposal_ref, override_id
                ) VALUES (
                    :project_key, :story_id, :run_id, :stage_id, :attempt_no,
                    :check_id, :outcome, :occurred_at, :check_proposal_ref,
                    :override_id
                )
                """,
                row,
            )

    def _pg_write(self, row: dict[str, object]) -> None:
        with _postgres_connect() as conn:
            conn.execute(
                """
                INSERT INTO qa_check_outcomes (
                    project_key, story_id, run_id, stage_id, attempt_no, check_id,
                    outcome, occurred_at, check_proposal_ref, override_id
                ) VALUES (
                    %(project_key)s, %(story_id)s, %(run_id)s, %(stage_id)s,
                    %(attempt_no)s, %(check_id)s, %(outcome)s, %(occurred_at)s,
                    %(check_proposal_ref)s, %(override_id)s
                )
                ON CONFLICT (project_key, run_id, stage_id, attempt_no, check_id)
                DO UPDATE SET
                    outcome = EXCLUDED.outcome,
                    occurred_at = EXCLUDED.occurred_at,
                    check_proposal_ref = EXCLUDED.check_proposal_ref,
                    override_id = EXCLUDED.override_id
                """,
                row,
            )

    def read(
        self,
        *,
        project_key: str,
        story_id: str | None = None,
        run_id: str | None = None,
        attempt_no: int | None = None,
        stage_id: str | None = None,
        check_id: str | None = None,
        since_days: int | None = None,
        check_proposal_ref: str | None = None,
        _now: Any = None,
    ) -> list[QACheckOutcomeRecord]:
        """Read qa_check_outcomes with optional filters."""
        if _is_postgres():
            return self._pg_read(
                project_key=project_key,
                story_id=story_id,
                run_id=run_id,
                attempt_no=attempt_no,
                stage_id=stage_id,
                check_id=check_id,
                since_days=since_days,
                check_proposal_ref=check_proposal_ref,
                _now=_now,
            )
        return self._sqlite_read(
            project_key=project_key,
            story_id=story_id,
            run_id=run_id,
            attempt_no=attempt_no,
            stage_id=stage_id,
            check_id=check_id,
            since_days=since_days,
            check_proposal_ref=check_proposal_ref,
            _now=_now,
        )

    @staticmethod
    def _build_since_cutoff(
        since_days: int | None, _now: Any
    ) -> str | None:
        """Compute the ISO-8601 cutoff for a since_days window."""
        from datetime import UTC, datetime, timedelta

        if since_days is None:
            return None
        effective_days = max(0, since_days)
        now_dt: datetime = _now if _now is not None else datetime.now(UTC)
        cutoff = now_dt - timedelta(days=effective_days)
        return cutoff.isoformat()

    def _sqlite_read(
        self,
        *,
        project_key: str,
        story_id: str | None,
        run_id: str | None,
        attempt_no: int | None,
        stage_id: str | None,
        check_id: str | None,
        since_days: int | None,
        check_proposal_ref: str | None,
        _now: Any,
    ) -> list[QACheckOutcomeRecord]:
        from datetime import UTC, datetime

        from agentkit.backend.verify_system.stage_registry.records import (
            CheckOutcome as _CheckOutcome,
        )
        from agentkit.backend.verify_system.stage_registry.records import (
            QACheckOutcomeRecord as _QACheckOutcomeRecord,
        )

        clauses: list[str] = ["project_key = ?"]
        params: list[object] = [project_key]
        if story_id is not None:
            clauses.append(_WHERE_STORY_ID)
            params.append(story_id)
        if run_id is not None:
            clauses.append(_WHERE_RUN_ID)
            params.append(run_id)
        if attempt_no is not None:
            clauses.append(_WHERE_ATTEMPT_NO)
            params.append(attempt_no)
        if stage_id is not None:
            clauses.append(_WHERE_STAGE_ID)
            params.append(stage_id)
        if check_id is not None:
            clauses.append("check_id = ?")
            params.append(check_id)
        cutoff = self._build_since_cutoff(since_days, _now)
        if cutoff is not None:
            clauses.append("occurred_at >= ?")
            params.append(cutoff)
        if check_proposal_ref is not None:
            clauses.append("check_proposal_ref = ?")
            params.append(check_proposal_ref)

        where = f"WHERE {' AND '.join(clauses)}"
        with _sqlite_connect_qa(self._story_dir) as conn:
            rows = conn.execute(
                f"SELECT * FROM qa_check_outcomes {where}",
                tuple(params),
            ).fetchall()
        return [
            _QACheckOutcomeRecord(
                project_key=str(r["project_key"]),
                story_id=str(r["story_id"]),
                run_id=str(r["run_id"]),
                stage_id=str(r["stage_id"]),
                attempt_no=int(r["attempt_no"]),
                check_id=str(r["check_id"]),
                outcome=_CheckOutcome(str(r["outcome"])),
                occurred_at=_parse_occurred_at(str(r["occurred_at"]), UTC, datetime),
                check_proposal_ref=(
                    str(r["check_proposal_ref"])
                    if r["check_proposal_ref"] is not None
                    else None
                ),
                override_id=(
                    str(r["override_id"]) if r["override_id"] is not None else None
                ),
            )
            for r in rows
        ]

    def _pg_read(
        self,
        *,
        project_key: str,
        story_id: str | None,
        run_id: str | None,
        attempt_no: int | None,
        stage_id: str | None,
        check_id: str | None,
        since_days: int | None,
        check_proposal_ref: str | None,
        _now: Any,
    ) -> list[QACheckOutcomeRecord]:
        from agentkit.backend.verify_system.stage_registry.records import (
            CheckOutcome as _CheckOutcome,
        )
        from agentkit.backend.verify_system.stage_registry.records import (
            QACheckOutcomeRecord as _QACheckOutcomeRecord,
        )

        clauses: list[str] = ["project_key = %(project_key)s"]
        pg_params: dict[str, object] = {"project_key": project_key}
        if story_id is not None:
            clauses.append("story_id = %(story_id)s")
            pg_params["story_id"] = story_id
        if run_id is not None:
            clauses.append("run_id = %(run_id)s")
            pg_params["run_id"] = run_id
        if attempt_no is not None:
            clauses.append("attempt_no = %(attempt_no)s")
            pg_params["attempt_no"] = attempt_no
        if stage_id is not None:
            clauses.append("stage_id = %(stage_id)s")
            pg_params["stage_id"] = stage_id
        if check_id is not None:
            clauses.append("check_id = %(check_id)s")
            pg_params["check_id"] = check_id
        cutoff = self._build_since_cutoff(since_days, _now)
        if cutoff is not None:
            clauses.append("occurred_at >= %(since_cutoff)s")
            pg_params["since_cutoff"] = cutoff
        if check_proposal_ref is not None:
            clauses.append("check_proposal_ref = %(check_proposal_ref)s")
            pg_params["check_proposal_ref"] = check_proposal_ref

        where = f"WHERE {' AND '.join(clauses)}"
        with _postgres_connect() as conn:
            rows = list(
                conn.execute(
                    f"SELECT * FROM qa_check_outcomes {where}",
                    pg_params,
                ).fetchall()
            )
        return [
            _QACheckOutcomeRecord(
                project_key=str(r["project_key"]),
                story_id=str(r["story_id"]),
                run_id=str(r["run_id"]),
                stage_id=str(r["stage_id"]),
                attempt_no=int(r["attempt_no"]),
                check_id=str(r["check_id"]),
                outcome=_CheckOutcome(str(r["outcome"])),
                occurred_at=r["occurred_at"],
                check_proposal_ref=r["check_proposal_ref"],
                override_id=r["override_id"],
            )
            for r in rows
        ]

    def purge_run(self, project_key: str, story_id: str, run_id: str) -> int:
        """Delete all qa_check_outcomes for (project_key, story_id, run_id).

        FK-69 §69.10.1 reset rule: active deletion, no query-filter trick.
        """
        if _is_postgres():
            return self._pg_purge(project_key, story_id, run_id)
        return self._sqlite_purge(project_key, story_id, run_id)

    def _sqlite_purge(self, project_key: str, story_id: str, run_id: str) -> int:
        with _sqlite_connect_qa(self._story_dir) as conn:
            cursor = conn.execute(
                "DELETE FROM qa_check_outcomes "
                "WHERE project_key=? AND story_id=? AND run_id=?",
                (project_key, story_id, run_id),
            )
            return int(cursor.rowcount)

    def _pg_purge(self, project_key: str, story_id: str, run_id: str) -> int:
        with _postgres_connect() as conn:
            cursor = conn.execute(
                "DELETE FROM qa_check_outcomes "
                "WHERE project_key=%s AND story_id=%s AND run_id=%s",
                (project_key, story_id, run_id),
            )
            return int(cursor.rowcount)


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
        from agentkit.backend.kpi_analytics import GuardCounterService
        from agentkit.backend.state_backend.store.guard_counter_repository import (
            StateBackendGuardCounterRepository,
        )

        drained = GuardCounterService(
            StateBackendGuardCounterRepository(self._store_dir)
        ).flush_on_story_reset(project_key, story_id)
        return len(drained)


def build_projection_repositories(store_dir: Path | None = None) -> ProjectionRepositories:
    """Build a fully wired ``ProjectionRepositories`` instance.

    A composition-root helper, used by
    ``agentkit.backend.bootstrap.composition_root.build_projection_accessor``.

    Args:
        store_dir: Base directory of the state backend. Only relevant for SQLite;
            Postgres ignores the path.

    Returns:
        ``ProjectionRepositories`` with all concrete adapter instances.
    """
    from agentkit.backend.state_backend.store.fc_check_proposal_repository import (
        StateBackendFcCheckProposalRepository,
    )
    from agentkit.backend.state_backend.store.fc_incident_repository import (
        StateBackendFCIncidentsRepository,
    )
    from agentkit.backend.state_backend.store.fc_pattern_repository import (
        StateBackendFcPatternRepository,
    )
    from agentkit.backend.state_backend.store.task_repository import StateBackendTaskRepository

    return ProjectionRepositories(
        qa_stage_results=FacadeQAStageResultsRepository(store_dir),
        qa_findings=FacadeQAFindingsRepository(store_dir),
        qa_check_outcomes=FacadeQACheckOutcomesRepository(store_dir),
        story_metrics=FacadeStoryMetricsRepository(store_dir),
        phase_state_projection=FacadePhaseStateProjectionRepository(store_dir),
        qa_layer_batch=FacadeQALayerBatchWriter(),
        fc_incidents=StateBackendFCIncidentsRepository(store_dir),
        risk_window=FacadeRiskWindowRepository(store_dir),
        tasks=StateBackendTaskRepository(store_dir),
        guard_counter_purge=StateBackendGuardCounterPurgeAdapter(store_dir),
        fc_patterns=StateBackendFcPatternRepository(store_dir),
        fc_check_proposals=StateBackendFcCheckProposalRepository(store_dir),
    )


__all__ = [
    "FacadePhaseStateProjectionRepository",
    "FacadeQACheckOutcomesRepository",
    "FacadeQAFindingsRepository",
    "FacadeQALayerBatchWriter",
    "FacadeQAStageResultsRepository",
    "FacadeRiskWindowRepository",
    "FacadeStoryMetricsRepository",
    "GuardCounterPurgePort",
    "PhaseStateProjectionRepository",
    "StateBackendGuardCounterPurgeAdapter",
    "ProjectionRepositories",
    "QACheckOutcomesRepository",
    "QAFindingsRepository",
    "QALayerBatchWriter",
    "QAStageResultsRepository",
    "RiskWindowRepository",
    "StoryMetricsRepository",
    "build_projection_repositories",
]
