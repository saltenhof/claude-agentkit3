"""Telemetry-owned metrics, risk-window, phase projection, and repository builder."""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING, Any

from agentkit.backend.state_backend.store.telemetry_projection_repository_common import (
    ProjectionRepositories,
    _is_postgres,
    _postgres_connect,
    _sqlite_connect,
    _sqlite_connect_qa,
)
from agentkit.backend.state_backend.store.telemetry_projection_repository_qa import (
    FacadeQACheckOutcomesRepository,
    FacadeQAFindingsRepository,
    FacadeQALayerBatchWriter,
    FacadeQAStageResultsRepository,
)

if TYPE_CHECKING:
    from agentkit.backend.closure import StoryMetricsRecord
    from agentkit.backend.telemetry.risk_window.normalized_event import NormalizedEvent

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
        write_projection. AG3-144 (Codex round-3, FK-91 §91.1a Rule 15): the
        Postgres path is fenced -- see :meth:`_pg_write` -- so this is no
        longer a bare delegation to ``facade.upsert_story_metrics`` (which
        stays unfenced and is retained only as a low-level seeding helper for
        tests; the production write boundary is HERE).
        """
        from agentkit.backend.state_backend.store import mappers

        row = mappers.story_metrics_to_row(record)
        if _is_postgres():
            self._pg_write(row)
        else:
            self._sqlite_write(row)

    def _sqlite_write(self, row: dict[str, object]) -> None:
        from agentkit.backend.state_backend import sqlite_store

        sqlite_store.upsert_story_metrics_row(self._story_dir, row)

    def _pg_write(self, row: dict[str, object]) -> None:
        """Fence-first (AG3-144 Codex round-3), then upsert in ONE transaction.

        Mirrors ``FacadeQACheckOutcomesRepository._pg_write`` /
        ``StateBackendArtifactRepository._pg_write``: the caller's ambient
        ``OwnershipFenceScope`` (bound by the owning phase handler, FK-91
        §91.1a Rule 15) is re-verified AT COMMIT TIME, in THIS SAME
        transaction, under ``SELECT ... FOR UPDATE``, BEFORE the
        ``story_metrics`` upsert. No scope bound at all is a hard,
        fail-closed error -- never a silent unfenced write. Closure Step 5
        (``closure.phase._resolve_metrics``) is the sole production writer
        and binds its early-captured lease snapshot around this call
        (Codex r2 finding: this write was previously reachable unfenced).

        Raises:
            CorruptStateError: When no ``OwnershipFenceScope`` is bound for
                this call, or it belongs to a different story.
            OwnershipFenceViolationError: When the story's active ownership
                record no longer admits the bound scope's snapshot at commit
                time -- nothing written.
        """
        from agentkit.backend.state_backend import postgres_store
        from agentkit.backend.state_backend.governance_runtime_store import (
            require_ownership_fence_scope,
        )

        scope = require_ownership_fence_scope(story_id=str(row["story_id"]))
        with _postgres_connect() as conn:
            # Sanctioned StateBackendRepository -> StateBackendDrivers edge
            # (same BC): the AG3-142 fence predicate is re-localized in
            # postgres_store.py and reused verbatim here.
            postgres_store._enforce_ownership_fence_row(
                postgres_store._CompatConnection(conn),
                project_key=scope.project_key,
                story_id=str(row["story_id"]),
                run_id=scope.run_id,
                session_id=scope.owner_session_id,
                expected_ownership_epoch=scope.expected_ownership_epoch,
            )
            conn.execute(
                """
                INSERT INTO story_metrics (
                    project_key, story_id, run_id, story_type, story_size, mode,
                    processing_time_min, qa_rounds, increments, final_status,
                    completed_at, adversarial_findings, adversarial_tests_created,
                    files_changed, agentkit_version, agentkit_commit,
                    config_version, llm_roles_json
                ) VALUES (
                    %(project_key)s, %(story_id)s, %(run_id)s, %(story_type)s,
                    %(story_size)s, %(mode)s, %(processing_time_min)s, %(qa_rounds)s,
                    %(increments)s, %(final_status)s, %(completed_at)s,
                    %(adversarial_findings)s, %(adversarial_tests_created)s,
                    %(files_changed)s, %(agentkit_version)s, %(agentkit_commit)s,
                    %(config_version)s, %(llm_roles_json)s
                )
                ON CONFLICT (project_key, run_id) DO UPDATE SET
                    story_id=excluded.story_id,
                    story_type=excluded.story_type,
                    story_size=excluded.story_size,
                    mode=excluded.mode,
                    processing_time_min=excluded.processing_time_min,
                    qa_rounds=excluded.qa_rounds,
                    increments=excluded.increments,
                    final_status=excluded.final_status,
                    completed_at=excluded.completed_at,
                    adversarial_findings=excluded.adversarial_findings,
                    adversarial_tests_created=excluded.adversarial_tests_created,
                    files_changed=excluded.files_changed,
                    agentkit_version=excluded.agentkit_version,
                    agentkit_commit=excluded.agentkit_commit,
                    config_version=excluded.config_version,
                    llm_roles_json=excluded.llm_roles_json
                """,
                row,
            )

    def read(
        self,
        *,
        project_key: str | None = None,
        story_id: str | None = None,
        run_id: str | None = None,
    ) -> list[StoryMetricsRecord]:
        from agentkit.backend.state_backend.telemetry_event_store import (
            load_story_metrics,
        )

        return load_story_metrics(
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
        from agentkit.backend.state_backend.runtime_scope_resolver import (
            resolve_runtime_scope,
        )

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


