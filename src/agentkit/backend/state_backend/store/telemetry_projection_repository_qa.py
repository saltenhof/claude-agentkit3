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
    from collections.abc import Mapping

    from agentkit.backend.artifacts import ArtifactReference
    from agentkit.backend.state_backend.store.telemetry_projection_repository_common import (
        QAPurgeCounts,
    )
    from agentkit.backend.verify_system.protocols import LayerResult
    from agentkit.backend.verify_system.stage_registry.records import (
        QACheckOutcomeRecord,
        QAFindingRecord,
        QAStageResultRecord,
    )
    from agentkit.backend.verify_system.stage_registry.registry import StageRegistry


class FacadeQAStageResultsRepository:
    """Read adapter for ``qa_stage_results``.

    Writes exist only in the atomic three-projection QA-layer batch. This
    adapter intentionally exposes no single-row write method.

    Args:
        story_dir: Base directory for SQLite; ignored for Postgres.
    """

    def __init__(self, story_dir: Path | None = None) -> None:
        self._story_dir: Path = story_dir or Path.cwd()

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
        from agentkit.backend.state_backend.state_backend_connection_manager import _backend_module

        rows = _backend_module().load_qa_stage_result_rows(
            self._story_dir,
            project_key=project_key,
            story_id=story_id,
            run_id=run_id,
            attempt_no=attempt_no,
            stage_id=stage_id,
        )
        return [mappers.qa_stage_result_row_to_record(row) for row in rows]


class FacadeQAFindingsRepository:
    """Read adapter for ``qa_findings`` without a split writer.

    Args:
        story_dir: Base directory for SQLite; ignored for Postgres.
    """

    def __init__(self, story_dir: Path | None = None) -> None:
        self._story_dir: Path = story_dir or Path.cwd()

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
                description=(str(r["description"]) if r["description"] is not None else None),
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
        from agentkit.backend.state_backend.state_backend_connection_manager import _backend_module

        rows = _backend_module().load_qa_finding_rows(
            self._story_dir,
            project_key=project_key,
            story_id=story_id,
            run_id=run_id,
            attempt_no=attempt_no,
            stage_id=stage_id,
        )
        return [mappers.qa_finding_row_to_record(row) for row in rows]


class FacadeQALayerBatchWriter:
    """Atomic QA-layer batch adapter (FK-69 §69.4, AG3-035 #5).

    Encapsulates the existing atomic
    driver batch (qa_stage_results + qa_findings + qa_check_outcomes in ONE
    transaction). Lives in the DB layer; the ``ProjectionAccessor`` in
    ``agentkit.backend.telemetry`` delegates here without knowing the facade directly (AC#7).
    """

    def __init__(self, story_dir: Path | None = None) -> None:
        self._story_dir = story_dir or Path.cwd()

    def persist_layer_artifacts(
        self,
        story_dir: Path,
        *,
        layer_results: tuple[LayerResult, ...],
        check_outcomes: tuple[QACheckOutcomeRecord, ...],
        artifact_references: Mapping[str, ArtifactReference],
        stage_registry: StageRegistry,
        attempt_nr: int,
        owner_session_id: str,
        expected_ownership_epoch: int,
        projection_dir: Path | None = None,
    ) -> tuple[str, ...]:
        """Persist the atomic QA-layer driver batch and return artifact IDs."""
        from typing import cast

        from agentkit.backend.state_backend import persistence_mappers as mappers
        from agentkit.backend.state_backend.state_backend_connection_manager import (
            _backend_module,
        )

        flow_row = _backend_module().load_flow_execution_row(story_dir)
        layer_payload_rows = mappers.build_qa_layer_payload_rows(
            flow_row,
            layer_results,
            attempt_nr=attempt_nr,
            stage_registry=stage_registry,
            artifact_references=artifact_references,
        )
        check_outcome_rows: list[dict[str, object]] = [
            {
                "project_key": record.project_key,
                "story_id": record.story_id,
                "run_id": record.run_id,
                "stage_id": record.stage_id,
                "attempt_no": record.attempt_no,
                "check_id": record.check_id,
                "outcome": str(record.outcome),
                "occurred_at": record.occurred_at.isoformat(),
                "check_proposal_ref": record.check_proposal_ref,
                "override_id": record.override_id,
            }
            for record in check_outcomes
        ]
        from agentkit.backend.state_backend._qa_batch_validation import (
            validate_qa_layer_batch_rows,
        )

        if flow_row is None:
            raise ValueError("QA projection rows require a flow execution scope")
        validate_qa_layer_batch_rows(
            flow_row=flow_row,
            canonical_story_id=str(flow_row["story_id"]),
            layer_payload_rows=layer_payload_rows,
            check_outcome_rows=check_outcome_rows,
            attempt_nr=attempt_nr,
        )
        return cast(
            "tuple[str, ...]",
            _backend_module().persist_layer_artifact_rows(
                story_dir,
                flow_row=flow_row,
                layer_payload_rows=layer_payload_rows,
                check_outcome_rows=check_outcome_rows,
                attempt_nr=attempt_nr,
                owner_session_id=owner_session_id,
                expected_ownership_epoch=expected_ownership_epoch,
                projection_dir=projection_dir,
            ),
        )

    def purge_run(
        self,
        *,
        project_key: str,
        story_id: str,
        run_id: str,
    ) -> QAPurgeCounts:
        """Delete the complete QA projection set in one driver transaction."""
        from agentkit.backend.state_backend.state_backend_connection_manager import (
            _backend_module,
        )
        from agentkit.backend.state_backend.store.telemetry_projection_repository_common import (
            QAPurgeCounts,
        )

        raw = _backend_module().purge_qa_projection_rows(
            self._story_dir,
            project_key=project_key,
            story_id=story_id,
            run_id=run_id,
        )
        return QAPurgeCounts(
            stage_results=int(raw["qa_stage_results"]),
            findings=int(raw["qa_findings"]),
            check_outcomes=int(raw["qa_check_outcomes"]),
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
    """Read adapter for ``qa_check_outcomes`` (FK-69 §69.15).

    Outcome rows are written only with their stage and finding projections by
    ``ProjectionAccessor.record_qa_layer_artifacts``.

    Args:
        story_dir: Base directory for SQLite; ignored for Postgres.
    """

    def __init__(self, story_dir: Path | None = None) -> None:
        self._story_dir: Path = story_dir or Path.cwd()

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
    def _build_since_cutoff(since_days: int | None, _now: Any) -> str | None:
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
                check_proposal_ref=(str(r["check_proposal_ref"]) if r["check_proposal_ref"] is not None else None),
                override_id=(str(r["override_id"]) if r["override_id"] is not None else None),
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
