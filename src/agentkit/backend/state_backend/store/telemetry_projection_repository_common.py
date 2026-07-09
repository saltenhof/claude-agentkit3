"""Telemetry projection repository protocols and shared backend helpers.

Each repository protocol defines the write and read boundary for one
FK-69 table family. The concrete implementations encapsulate driver access
without introducing a new operative truth.

Architecture Conformance (AC#7):
- ``ProjectionAccessor`` in ``agentkit.backend.telemetry`` may NOT import directly from
  ``agentkit.backend.state_backend owner modules``.
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

import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

if TYPE_CHECKING:
    from collections.abc import Iterator
    from datetime import datetime
    from pathlib import Path

    from agentkit.backend.closure import StoryMetricsRecord
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
        owner_session_id: str,
        expected_ownership_epoch: int,
        projection_dir: Path | None = None,
    ) -> tuple[str, ...]:
        """Persist QA-layer results atomically; returns the artifact IDs.

        ``owner_session_id`` / ``expected_ownership_epoch`` (AG3-144, FK-91
        §91.1a Rule 15) are the caller's early-captured active
        ``run_ownership_records`` snapshot, re-verified at commit time (the
        AG3-142 fence, no-lease-no-write).
        """
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
    try:
        # Setup runs inside try so a bootstrap failure closes the conn (no leak).
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys = ON")
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


@contextmanager
def _postgres_connect() -> Iterator[Any]:
    from agentkit.backend.state_backend import postgres_store
    from agentkit.backend.state_backend.schema_bootstrap import ensure_versioned_schema

    with postgres_store.borrow_repository_connection() as conn:
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
    try:
        # Setup runs inside try so a bootstrap failure closes the conn (no leak).
        conn.row_factory = sqlite3.Row
        # AG3-028 Codex-r2: busy_timeout FIRST, so a held write lock (e.g. the
        # BEGIN IMMEDIATE allocation in fc_incident_repository) makes other
        # writers wait instead of immediately raising SQLITE_BUSY — race-safe
        # first allocation.
        conn.execute("PRAGMA busy_timeout = 30000")
        # Only switch when not already WAL (the WAL switch does not honour
        # busy_timeout; setting it repeatedly would raise spurious locks under
        # concurrency).
        current_mode = conn.execute("PRAGMA journal_mode").fetchone()
        if current_mode is None or str(current_mode[0]).lower() != "wal":
            conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys = ON")
        # Bootstrap via the canonical schema owner (SINGLE SOURCE OF TRUTH,
        # finding B)
        sqlite_store._ensure_schema(conn)
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

