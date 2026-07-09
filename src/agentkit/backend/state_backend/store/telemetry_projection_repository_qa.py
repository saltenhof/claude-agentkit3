"""Telemetry-owned QA projection repository adapters."""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING, Any

from agentkit.backend.state_backend.store.telemetry_projection_repository_common import (
    _WHERE_ATTEMPT_NO,
    _WHERE_PROJECT_KEY,
    _WHERE_RUN_ID,
    _WHERE_STAGE_ID,
    _WHERE_STORY_ID,
    _is_postgres,
    _postgres_connect,
    _sqlite_connect_qa,
)

if TYPE_CHECKING:
    from agentkit.backend.verify_system.protocols import LayerResult
    from agentkit.backend.verify_system.stage_registry.records import (
        QACheckOutcomeRecord,
        QAFindingRecord,
        QAStageResultRecord,
    )

class FacadeQAStageResultsRepository:
    """Thin adapter for qa_stage_results.

    Write and purge: direct SQL (no existing facade single-insert path;
    the main batch path stays ``ProjectionAccessor.record_qa_layer_artifacts``).
    Read: delegates to the facade for backward compatibility.

    Args:
        story_dir: Base directory for SQLite; ignored for Postgres.
    """

    def __init__(self, story_dir: Path | None = None) -> None:
        self._story_dir: Path = story_dir or Path.cwd()

    def write(self, record: QAStageResultRecord) -> None:
        """Persist a single QAStageResultRecord.

        Note: the main write path for qa_stage_results runs
        transactionally via ``ProjectionAccessor.record_qa_layer_artifacts``
        (batch insert incl. artifact_records). This write path is intended for
        direct single inserts from the ProjectionAccessor.
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
        from agentkit.backend.state_backend import persistence_mappers as mappers
        from agentkit.backend.state_backend.store import facade

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
        from agentkit.backend.state_backend import persistence_mappers as mappers
        from agentkit.backend.state_backend.store import facade

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


class FacadeQALayerBatchWriter:
    """Atomic QA-layer batch adapter (FK-69 §69.4, AG3-035 #5).

    Encapsulates the existing atomic
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
        owner_session_id: str,
        expected_ownership_epoch: int,
        projection_dir: Path | None = None,
    ) -> tuple[str, ...]:
        """Persist the atomic QA-layer driver batch and return artifact IDs."""
        from datetime import datetime
        from typing import cast

        from agentkit.backend.boundary.shared.time import now_iso
        from agentkit.backend.core_types.qa_artifact_names import LAYER_ARTIFACT_FILES
        from agentkit.backend.state_backend import persistence_mappers as mappers
        from agentkit.backend.state_backend.state_backend_connection_manager import (
            _backend_module,
        )

        flow_row = _backend_module().load_flow_execution_row(story_dir)
        layer_payload_rows: list[dict[str, object]] = []
        for layer_result in layer_results:
            artifact_name = LAYER_ARTIFACT_FILES.get(layer_result.layer)
            if artifact_name is None:
                continue
            recorded_at = datetime.fromisoformat(now_iso())
            stage_row: dict[str, object] | None = None
            finding_rows: list[dict[str, object]] = []
            if flow_row is not None:
                stage_row = mappers.build_qa_stage_result_row(
                    flow_row,
                    layer_result,
                    attempt_no=attempt_nr,
                    artifact_id="",
                    recorded_at=recorded_at,
                )
                finding_rows = mappers.build_qa_finding_rows(
                    flow_row,
                    layer_result,
                    attempt_no=attempt_nr,
                    artifact_id="",
                    recorded_at=recorded_at,
                )
            layer_payload_rows.append(
                {
                    "layer": layer_result.layer,
                    "artifact_name": artifact_name,
                    "producer_component": mappers.get_producer_component_for_layer(
                        layer_result.layer,
                    ),
                    "payload": mappers.serialize_layer_result_to_dict(
                        layer_result,
                        attempt_nr=attempt_nr,
                    ),
                    "passed": layer_result.passed,
                    "recorded_at": recorded_at.isoformat(),
                    "stage_row": stage_row,
                    "finding_rows": finding_rows,
                }
            )
        return cast(
            "tuple[str, ...]",
            _backend_module().persist_layer_artifact_rows(
                story_dir,
                flow_row=flow_row,
                layer_payload_rows=layer_payload_rows,
                attempt_nr=attempt_nr,
                owner_session_id=owner_session_id,
                expected_ownership_epoch=expected_ownership_epoch,
                projection_dir=projection_dir,
            ),
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
        """Fence-first (AG3-144 Codex round-2), then upsert in ONE transaction.

        Mirrors ``StateBackendArtifactRepository._pg_write``: the caller's
        ambient ``OwnershipFenceScope`` (bound by the owning phase handler,
        FK-91 §91.1a Rule 15) is re-verified AT COMMIT TIME, in THIS SAME
        transaction, under ``SELECT ... FOR UPDATE``, BEFORE the
        ``qa_check_outcomes`` upsert. No scope bound at all is a hard,
        fail-closed error -- never a silent unfenced write.

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


