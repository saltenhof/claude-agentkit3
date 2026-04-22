"""PostgreSQL-backed canonical runtime store with JSON projections."""

from __future__ import annotations

import json
from contextlib import contextmanager
from datetime import datetime
from typing import TYPE_CHECKING, Any, cast

import psycopg
from psycopg.rows import dict_row

from agentkit.exceptions import CorruptStateError
from agentkit.phase_state_store.models import (
    FlowExecution,
    NodeExecutionLedger,
    OverrideRecord,
)
from agentkit.state_backend.config import (
    STATE_DATABASE_URL_ENV,
    load_state_backend_config,
)
from agentkit.state_backend.exports import (
    build_verify_decision_artifact,
    load_json_object,
    now_iso,
    serialize_layer_result,
    write_execution_report_projection,
    write_layer_projection,
    write_phase_snapshot_projection,
    write_phase_state_projection,
    write_story_context_projection,
    write_verify_decision_projection,
)
from agentkit.state_backend.qa_read_models import (
    build_qa_findings,
    build_qa_stage_result,
    producer_component_for_layer,
)
from agentkit.state_backend.records import (
    AttemptRecord,
    ControlPlaneOperationRecord,
    ExecutionEventRecord,
    ExecutionReport,
    QAFindingRecord,
    QAStageResultRecord,
    SessionRunBindingRecord,
    StoryExecutionLockRecord,
    StoryMetricsRecord,
)
from agentkit.story_context_manager.models import (
    PhaseSnapshot,
    PhaseState,
    PhaseStatus,
    StoryContext,
)

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

    from agentkit.qa.policy_engine.engine import VerifyDecision
    from agentkit.qa.protocols import LayerResult
    from agentkit.state_backend.scope import RuntimeStateScope


_PROJECT_KEY_FILTER = "project_key = ?"
_STORY_ID_FILTER = "story_id = ?"
_RUN_ID_FILTER = "run_id = ?"


def _database_url() -> str:
    config = load_state_backend_config()
    if not config.database_url:
        raise RuntimeError(
            f"{STATE_DATABASE_URL_ENV} must be set when "
            "AGENTKIT_STATE_BACKEND=postgres",
        )
    return config.database_url


def _database_label() -> str:
    return STATE_DATABASE_URL_ENV


class _CompatConnection:
    """Compatibility wrapper translating sqlite-style queries to psycopg."""

    def __init__(self, conn: psycopg.Connection[Any]) -> None:
        self._conn = conn

    def execute(
        self,
        query: str,
        params: tuple[object, ...] = (),
    ) -> psycopg.Cursor[dict[str, Any]]:
        normalized = query.replace("?", "%s")
        return self._conn.execute(normalized, params)

    def executescript(self, script: str) -> None:
        statements = [stmt.strip() for stmt in script.split(";") if stmt.strip()]
        for statement in statements:
            self._conn.execute(statement)


def load_json_safe(path: Path) -> dict[str, object] | None:
    """Compatibility helper for non-canonical export reads."""

    return load_json_object(path)


def _dump_json(data: object) -> str:
    return json.dumps(data, sort_keys=True, default=str)


def _load_json(data: str | None, default: Any) -> Any:
    if data is None:
        return default
    return json.loads(data)


def _cast_json_record(value: object) -> dict[str, object]:
    return cast("dict[str, object]", value)


def _cast_optional_str(value: object) -> str | None:
    return cast("str | None", value)


@contextmanager
def _connect_global() -> Iterator[_CompatConnection]:
    conn = psycopg.connect(
        _database_url(),
        row_factory=dict_row,
    )
    compat = _CompatConnection(conn)
    _ensure_schema(compat)
    try:
        yield compat
        conn.commit()
    finally:
        conn.close()


@contextmanager
def _connect(story_dir: Path) -> Iterator[_CompatConnection]:
    del story_dir
    with _connect_global() as compat:
        yield compat


def _insert_execution_event(
    conn: _CompatConnection,
    event: ExecutionEventRecord,
) -> None:
    conn.execute(
        """
        INSERT INTO execution_events (
            project_key, story_id, run_id, event_id, event_type,
            occurred_at, source_component, severity, phase, flow_id,
            node_id, payload_json
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            event.project_key,
            event.story_id,
            event.run_id,
            event.event_id,
            event.event_type,
            event.occurred_at.isoformat(),
            event.source_component,
            event.severity,
            event.phase,
            event.flow_id,
            event.node_id,
            _dump_json(event.payload),
        ),
    )


def _schema_create_script() -> str:
    return """
        CREATE TABLE IF NOT EXISTS story_contexts (
            project_key TEXT NOT NULL,
            story_id TEXT NOT NULL,
            story_type TEXT NOT NULL,
            execution_route TEXT NOT NULL,
            implementation_contract TEXT,
            issue_nr INTEGER,
            title TEXT NOT NULL,
            payload_json TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            PRIMARY KEY (project_key, story_id)
        );

        CREATE TABLE IF NOT EXISTS phase_states (
            story_id TEXT PRIMARY KEY,
            phase TEXT NOT NULL,
            status TEXT NOT NULL,
            paused_reason TEXT,
            review_round INTEGER NOT NULL,
            attempt_id TEXT,
            errors_json TEXT NOT NULL,
            payload_json TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS phase_snapshots (
            story_id TEXT NOT NULL,
            phase TEXT NOT NULL,
            status TEXT NOT NULL,
            completed_at TEXT NOT NULL,
            payload_json TEXT NOT NULL,
            PRIMARY KEY (story_id, phase)
        );

        CREATE TABLE IF NOT EXISTS attempt_records (
            story_id TEXT NOT NULL,
            phase TEXT NOT NULL,
            seq INTEGER NOT NULL,
            attempt_id TEXT NOT NULL,
            entered_at TEXT NOT NULL,
            exit_status TEXT,
            outcome TEXT,
            yield_status TEXT,
            resume_trigger TEXT,
            guard_evaluations_json TEXT NOT NULL,
            artifacts_json TEXT NOT NULL,
            PRIMARY KEY (story_id, phase, seq)
        );

        CREATE TABLE IF NOT EXISTS flow_executions (
            story_id TEXT PRIMARY KEY,
            project_key TEXT NOT NULL,
            run_id TEXT NOT NULL,
            flow_id TEXT NOT NULL,
            level TEXT NOT NULL,
            owner TEXT NOT NULL,
            parent_flow_id TEXT,
            status TEXT NOT NULL,
            current_node_id TEXT,
            attempt_no INTEGER NOT NULL,
            started_at TEXT NOT NULL,
            finished_at TEXT
        );

        CREATE TABLE IF NOT EXISTS node_execution_ledgers (
            story_id TEXT NOT NULL,
            flow_id TEXT NOT NULL,
            node_id TEXT NOT NULL,
            project_key TEXT NOT NULL,
            run_id TEXT NOT NULL,
            execution_count INTEGER NOT NULL,
            success_count INTEGER NOT NULL,
            last_outcome TEXT,
            last_attempt_no INTEGER,
            last_executed_at TEXT,
            PRIMARY KEY (story_id, flow_id, node_id)
        );

        CREATE TABLE IF NOT EXISTS execution_events (
            project_key TEXT NOT NULL,
            story_id TEXT NOT NULL,
            run_id TEXT NOT NULL,
            event_id TEXT NOT NULL,
            event_type TEXT NOT NULL,
            occurred_at TEXT NOT NULL,
            source_component TEXT NOT NULL,
            severity TEXT NOT NULL,
            phase TEXT,
            flow_id TEXT,
            node_id TEXT,
            payload_json TEXT NOT NULL,
            PRIMARY KEY (project_key, run_id, event_id)
        );

        CREATE TABLE IF NOT EXISTS session_run_bindings (
            session_id TEXT PRIMARY KEY,
            project_key TEXT NOT NULL,
            story_id TEXT NOT NULL,
            run_id TEXT NOT NULL,
            principal_type TEXT NOT NULL,
            worktree_roots_json TEXT NOT NULL,
            binding_version TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS story_execution_locks (
            project_key TEXT NOT NULL,
            story_id TEXT NOT NULL,
            run_id TEXT NOT NULL,
            lock_type TEXT NOT NULL,
            status TEXT NOT NULL,
            worktree_roots_json TEXT NOT NULL,
            binding_version TEXT NOT NULL,
            activated_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            deactivated_at TEXT,
            PRIMARY KEY (project_key, run_id, lock_type)
        );

        CREATE TABLE IF NOT EXISTS control_plane_operations (
            op_id TEXT PRIMARY KEY,
            project_key TEXT NOT NULL,
            story_id TEXT NOT NULL,
            run_id TEXT,
            session_id TEXT,
            operation_kind TEXT NOT NULL,
            phase TEXT,
            status TEXT NOT NULL,
            response_json TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS story_metrics (
            project_key TEXT NOT NULL,
            story_id TEXT NOT NULL,
            run_id TEXT NOT NULL,
            story_type TEXT NOT NULL,
            story_size TEXT NOT NULL,
            mode TEXT NOT NULL,
            processing_time_min DOUBLE PRECISION NOT NULL,
            qa_rounds INTEGER NOT NULL,
            increments INTEGER NOT NULL,
            final_status TEXT NOT NULL,
            completed_at TEXT NOT NULL,
            adversarial_findings INTEGER,
            adversarial_tests_created INTEGER,
            files_changed INTEGER,
            agentkit_version TEXT,
            agentkit_commit TEXT,
            config_version TEXT,
            llm_roles_json TEXT NOT NULL,
            PRIMARY KEY (project_key, run_id)
        );

        CREATE TABLE IF NOT EXISTS override_records (
            override_id TEXT PRIMARY KEY,
            story_id TEXT NOT NULL,
            project_key TEXT NOT NULL,
            run_id TEXT NOT NULL,
            flow_id TEXT NOT NULL,
            target_node_id TEXT,
            override_type TEXT NOT NULL,
            actor_type TEXT NOT NULL,
            actor_id TEXT NOT NULL,
            reason TEXT NOT NULL,
            created_at TEXT NOT NULL,
            consumed_at TEXT
        );

        CREATE TABLE IF NOT EXISTS artifact_records (
            project_key TEXT,
            story_id TEXT NOT NULL,
            run_id TEXT,
            artifact_id TEXT,
            artifact_class TEXT,
            artifact_kind TEXT NOT NULL,
            artifact_format TEXT,
            artifact_status TEXT,
            produced_in_phase TEXT,
            artifact_name TEXT NOT NULL,
            producer TEXT NOT NULL,
            producer_component TEXT,
            producer_trust TEXT,
            protection_level TEXT,
            frozen INTEGER,
            integrity_verified INTEGER,
            status TEXT,
            attempt_nr INTEGER NOT NULL,
            attempt_no INTEGER,
            qa_cycle_id TEXT,
            qa_cycle_round INTEGER,
            evidence_epoch INTEGER,
            payload_json TEXT NOT NULL,
            created_at TEXT NOT NULL,
            finished_at TEXT,
            storage_ref TEXT,
            PRIMARY KEY (story_id, artifact_kind, artifact_name, attempt_nr)
        );

        CREATE TABLE IF NOT EXISTS qa_stage_results (
            project_key TEXT NOT NULL,
            story_id TEXT NOT NULL,
            run_id TEXT NOT NULL,
            attempt_no INTEGER NOT NULL,
            stage_id TEXT NOT NULL,
            layer TEXT NOT NULL,
            producer_component TEXT NOT NULL,
            status TEXT NOT NULL,
            blocking INTEGER NOT NULL,
            total_checks INTEGER NOT NULL,
            failed_checks INTEGER NOT NULL,
            warning_checks INTEGER NOT NULL,
            artifact_id TEXT NOT NULL,
            recorded_at TEXT NOT NULL,
            PRIMARY KEY (project_key, run_id, attempt_no, stage_id)
        );

        CREATE TABLE IF NOT EXISTS qa_findings (
            project_key TEXT NOT NULL,
            story_id TEXT NOT NULL,
            run_id TEXT NOT NULL,
            attempt_no INTEGER NOT NULL,
            stage_id TEXT NOT NULL,
            finding_id TEXT NOT NULL,
            check_id TEXT NOT NULL,
            status TEXT NOT NULL,
            severity TEXT NOT NULL,
            blocking INTEGER NOT NULL,
            source_component TEXT NOT NULL,
            artifact_id TEXT NOT NULL,
            occurred_at TEXT NOT NULL,
            category TEXT,
            reason TEXT,
            description TEXT,
            detail TEXT,
            metadata_json TEXT NOT NULL,
            PRIMARY KEY (project_key, run_id, attempt_no, stage_id, finding_id)
        );

        CREATE TABLE IF NOT EXISTS decision_records (
            project_key TEXT,
            story_id TEXT NOT NULL,
            run_id TEXT,
            flow_id TEXT,
            decision_kind TEXT NOT NULL,
            attempt_nr INTEGER NOT NULL,
            status TEXT NOT NULL,
            passed INTEGER NOT NULL,
            summary TEXT NOT NULL,
            payload_json TEXT NOT NULL,
            created_at TEXT NOT NULL,
            PRIMARY KEY (story_id, decision_kind, attempt_nr)
        );
"""

def _schema_alter_statements() -> tuple[str, ...]:
    return (
        (
            "ALTER TABLE story_execution_locks "
            "DROP CONSTRAINT IF EXISTS story_execution_locks_pkey"
        ),
        (
            "ALTER TABLE story_execution_locks "
            "ADD CONSTRAINT story_execution_locks_pkey "
            "PRIMARY KEY (project_key, run_id, lock_type)"
        ),
        "ALTER TABLE artifact_records ADD COLUMN IF NOT EXISTS project_key TEXT",
        "ALTER TABLE artifact_records ADD COLUMN IF NOT EXISTS run_id TEXT",
        "ALTER TABLE artifact_records ADD COLUMN IF NOT EXISTS artifact_id TEXT",
        "ALTER TABLE artifact_records ADD COLUMN IF NOT EXISTS artifact_class TEXT",
        "ALTER TABLE artifact_records ADD COLUMN IF NOT EXISTS artifact_format TEXT",
        "ALTER TABLE artifact_records ADD COLUMN IF NOT EXISTS artifact_status TEXT",
        "ALTER TABLE artifact_records ADD COLUMN IF NOT EXISTS produced_in_phase TEXT",
        "ALTER TABLE artifact_records ADD COLUMN IF NOT EXISTS producer_component TEXT",
        "ALTER TABLE artifact_records ADD COLUMN IF NOT EXISTS producer_trust TEXT",
        "ALTER TABLE artifact_records ADD COLUMN IF NOT EXISTS protection_level TEXT",
        "ALTER TABLE artifact_records ADD COLUMN IF NOT EXISTS frozen INTEGER",
        (
            "ALTER TABLE artifact_records "
            "ADD COLUMN IF NOT EXISTS integrity_verified INTEGER"
        ),
        "ALTER TABLE artifact_records ADD COLUMN IF NOT EXISTS attempt_no INTEGER",
        "ALTER TABLE artifact_records ADD COLUMN IF NOT EXISTS qa_cycle_id TEXT",
        "ALTER TABLE artifact_records ADD COLUMN IF NOT EXISTS qa_cycle_round INTEGER",
        "ALTER TABLE artifact_records ADD COLUMN IF NOT EXISTS evidence_epoch INTEGER",
        "ALTER TABLE artifact_records ADD COLUMN IF NOT EXISTS finished_at TEXT",
        "ALTER TABLE artifact_records ADD COLUMN IF NOT EXISTS storage_ref TEXT",
        "ALTER TABLE decision_records ADD COLUMN IF NOT EXISTS project_key TEXT",
        "ALTER TABLE decision_records ADD COLUMN IF NOT EXISTS run_id TEXT",
        "ALTER TABLE decision_records ADD COLUMN IF NOT EXISTS flow_id TEXT",
    )


def _ensure_reporting_indexes(conn: _CompatConnection) -> None:
    conn.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS artifact_records_scope_identity_idx
        ON artifact_records (project_key, run_id, artifact_id)
        """
    )
    conn.execute(
        "ALTER TABLE decision_records DROP CONSTRAINT IF EXISTS decision_records_pkey"
    )
    conn.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS decision_records_scope_identity_idx
        ON decision_records (project_key, run_id, decision_kind, attempt_nr)
        """
    )


def _ensure_schema(conn: _CompatConnection) -> None:
    conn.executescript(_schema_create_script())
    for statement in _schema_alter_statements():
        conn.execute(statement)
    _ensure_reporting_indexes(conn)


def _story_id_for(story_dir: Path) -> str | None:
    story_id = story_dir.name
    return story_id or None


def _artifact_id_for(artifact_kind: str, attempt_no: int | None = None) -> str:
    if attempt_no is None:
        return artifact_kind.replace("_", "-")
    return f"{artifact_kind.replace('_', '-')}-attempt-{attempt_no}"


def _artifact_class_for(artifact_kind: str) -> str:
    if artifact_kind == "closure_report":
        return "closure"
    return "qa"


def _produced_in_phase_for(artifact_kind: str) -> str:
    if artifact_kind == "closure_report":
        return "closure"
    return "verify"


def _producer_trust_for(producer_component: str) -> str:
    if producer_component in {"qa-semantic-review"}:
        return "verified_llm"
    if producer_component in {"qa-adversarial"}:
        return "agent"
    return "system"


def _upsert_artifact_record(
    conn: _CompatConnection,
    *,
    flow: FlowExecution,
    artifact_kind: str,
    artifact_name: str,
    producer_component: str,
    lifecycle_status: str,
    payload: dict[str, object],
    created_at: datetime,
    attempt_no: int | None = None,
) -> str:
    artifact_id = _artifact_id_for(artifact_kind, attempt_no)
    legacy_artifact_name = f"{artifact_name}@{flow.run_id}"
    conn.execute(
        """
        INSERT INTO artifact_records (
            project_key, story_id, run_id, artifact_id, artifact_class,
            artifact_kind, artifact_format, artifact_status, produced_in_phase,
            artifact_name, producer, producer_component, producer_trust,
            protection_level, frozen, integrity_verified, status, attempt_nr,
            attempt_no, qa_cycle_id, qa_cycle_round, evidence_epoch,
            payload_json, created_at, finished_at, storage_ref
        ) VALUES (
            ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
        )
        ON CONFLICT(project_key, run_id, artifact_id) DO UPDATE SET
            story_id=excluded.story_id,
            artifact_class=excluded.artifact_class,
            artifact_kind=excluded.artifact_kind,
            artifact_format=excluded.artifact_format,
            artifact_status=excluded.artifact_status,
            produced_in_phase=excluded.produced_in_phase,
            artifact_name=excluded.artifact_name,
            producer=excluded.producer,
            producer_component=excluded.producer_component,
            producer_trust=excluded.producer_trust,
            protection_level=excluded.protection_level,
            frozen=excluded.frozen,
            integrity_verified=excluded.integrity_verified,
            status=excluded.status,
            attempt_nr=excluded.attempt_nr,
            attempt_no=excluded.attempt_no,
            qa_cycle_id=excluded.qa_cycle_id,
            qa_cycle_round=excluded.qa_cycle_round,
            evidence_epoch=excluded.evidence_epoch,
            payload_json=excluded.payload_json,
            created_at=excluded.created_at,
            finished_at=excluded.finished_at,
            storage_ref=excluded.storage_ref
        """,
        (
            flow.project_key,
            flow.story_id,
            flow.run_id,
            artifact_id,
            _artifact_class_for(artifact_kind),
            artifact_kind,
            "json",
            "produced",
            _produced_in_phase_for(artifact_kind),
            legacy_artifact_name,
            producer_component,
            producer_component,
            _producer_trust_for(producer_component),
            "hook_locked",
            0,
            0,
            lifecycle_status,
            attempt_no if attempt_no is not None else 0,
            attempt_no,
            (
                f"verify-attempt-{attempt_no}"
                if attempt_no is not None and artifact_kind != "closure_report"
                else None
            ),
            attempt_no,
            attempt_no,
            _dump_json(payload),
            created_at.isoformat(),
            created_at.isoformat(),
            artifact_name,
        ),
    )
    return artifact_id


def save_story_context(story_dir: Path, ctx: StoryContext) -> None:
    payload = ctx.model_dump(mode="json")
    with _connect(story_dir) as conn:
        conn.execute(
            """
            INSERT INTO story_contexts (
                project_key,
                story_id,
                story_type,
                execution_route,
                implementation_contract,
                issue_nr,
                title,
                payload_json,
                updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(project_key, story_id) DO UPDATE SET
                story_type=excluded.story_type,
                execution_route=excluded.execution_route,
                implementation_contract=excluded.implementation_contract,
                issue_nr=excluded.issue_nr,
                title=excluded.title,
                payload_json=excluded.payload_json,
                updated_at=excluded.updated_at
            """,
            (
                ctx.project_key,
                ctx.story_id,
                ctx.story_type.value,
                ctx.execution_route.value,
                (
                    ctx.implementation_contract.value
                    if ctx.implementation_contract is not None
                    else None
                ),
                ctx.issue_nr,
                ctx.title,
                _dump_json(payload),
                now_iso(),
            ),
        )
    write_story_context_projection(story_dir, payload)


def load_story_context(story_dir: Path) -> StoryContext | None:
    story_id = _story_id_for(story_dir)
    if story_id is None:
        return None
    with _connect(story_dir) as conn:
        rows = conn.execute(
            """
            SELECT payload_json FROM story_contexts
            WHERE story_id = ?
            """,
            (story_id,),
        ).fetchall()
    if not rows:
        return None
    if len(rows) > 1:
        raise CorruptStateError(
            "story_contexts lookup is ambiguous without explicit project scope",
            detail={"story_dir": str(story_dir), "story_id": story_id},
        )
    try:
        return StoryContext.model_validate(json.loads(str(rows[0]["payload_json"])))
    except Exception as exc:  # noqa: BLE001
        raise CorruptStateError(
            f"story_contexts payload is invalid in {_database_label()}: {exc}",
        ) from exc


def read_story_context_record(story_dir: Path) -> StoryContext | None:
    """Canonical reader name for protected runtime modules."""

    return load_story_context(story_dir)


def save_phase_state(story_dir: Path, state: PhaseState) -> None:
    payload = state.model_dump(mode="json")
    with _connect(story_dir) as conn:
        conn.execute(
            """
            INSERT INTO phase_states (
                story_id, phase, status, paused_reason, review_round,
                attempt_id, errors_json, payload_json, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(story_id) DO UPDATE SET
                phase=excluded.phase,
                status=excluded.status,
                paused_reason=excluded.paused_reason,
                review_round=excluded.review_round,
                attempt_id=excluded.attempt_id,
                errors_json=excluded.errors_json,
                payload_json=excluded.payload_json,
                updated_at=excluded.updated_at
            """,
            (
                state.story_id,
                state.phase,
                state.status.value,
                state.paused_reason,
                state.review_round,
                state.attempt_id,
                _dump_json(state.errors),
                _dump_json(payload),
                now_iso(),
            ),
        )
    write_phase_state_projection(story_dir, payload)


def load_phase_state(story_dir: Path) -> PhaseState | None:
    story_id = _story_id_for(story_dir)
    if story_id is None:
        return None
    with _connect(story_dir) as conn:
        row = conn.execute(
            """
            SELECT payload_json FROM phase_states
            WHERE story_id = ?
            """,
            (story_id,),
        ).fetchone()
    if row is None:
        return None
    try:
        return PhaseState.model_validate(json.loads(str(row["payload_json"])))
    except Exception as exc:  # noqa: BLE001
        raise CorruptStateError(
            f"phase_states payload is invalid in {_database_label()}: {exc}",
        ) from exc


def read_phase_state_record(story_dir: Path) -> PhaseState | None:
    """Canonical reader name for protected runtime modules."""

    return load_phase_state(story_dir)


def save_phase_snapshot(story_dir: Path, snapshot: PhaseSnapshot) -> None:
    payload = snapshot.model_dump(mode="json")
    with _connect(story_dir) as conn:
        conn.execute(
            """
            INSERT INTO phase_snapshots (
                story_id, phase, status, completed_at, payload_json
            ) VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(story_id, phase) DO UPDATE SET
                status=excluded.status,
                completed_at=excluded.completed_at,
                payload_json=excluded.payload_json
            """,
            (
                snapshot.story_id,
                snapshot.phase,
                snapshot.status.value,
                snapshot.completed_at.isoformat(),
                _dump_json(payload),
            ),
        )
    write_phase_snapshot_projection(story_dir, snapshot.phase, payload)


def load_phase_snapshot(story_dir: Path, phase: str) -> PhaseSnapshot | None:
    story_id = _story_id_for(story_dir)
    if story_id is None:
        return None
    with _connect(story_dir) as conn:
        row = conn.execute(
            """
            SELECT payload_json FROM phase_snapshots
            WHERE story_id = ? AND phase = ?
            """,
            (story_id, phase),
        ).fetchone()
    if row is None:
        return None
    try:
        return PhaseSnapshot.model_validate(json.loads(str(row["payload_json"])))
    except Exception as exc:  # noqa: BLE001
        raise CorruptStateError(
            "phase_snapshots payload is invalid in "
            f"{_database_label()} for phase {phase!r}: {exc}",
        ) from exc


def read_phase_snapshot_record(story_dir: Path, phase: str) -> PhaseSnapshot | None:
    """Canonical reader name for protected runtime modules."""

    return load_phase_snapshot(story_dir, phase)


def save_attempt(story_dir: Path, attempt: AttemptRecord) -> None:
    story_id = _story_id_for(story_dir)
    if story_id is None:
        raise CorruptStateError(
            "Cannot persist attempt without story context in canonical backend",
        )
    with _connect(story_dir) as conn:
        row = conn.execute(
            """
            SELECT COALESCE(MAX(seq), 0) AS max_seq
            FROM attempt_records
            WHERE story_id = ? AND phase = ?
            """,
            (story_id, attempt.phase),
        ).fetchone()
        seq = int(row["max_seq"]) + 1 if row is not None else 1
        conn.execute(
            """
            INSERT INTO attempt_records (
                story_id, phase, seq, attempt_id, entered_at, exit_status,
                outcome, yield_status, resume_trigger,
                guard_evaluations_json, artifacts_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                story_id,
                attempt.phase,
                seq,
                attempt.attempt_id,
                attempt.entered_at.isoformat(),
                attempt.exit_status.value if attempt.exit_status else None,
                attempt.outcome,
                attempt.yield_status,
                attempt.resume_trigger,
                _dump_json(list(attempt.guard_evaluations)),
                _dump_json(list(attempt.artifacts_produced)),
            ),
        )


def load_attempts(story_dir: Path, phase: str) -> list[AttemptRecord]:
    story_id = _story_id_for(story_dir)
    if story_id is None:
        return []
    with _connect(story_dir) as conn:
        rows = conn.execute(
            """
            SELECT * FROM attempt_records
            WHERE story_id = ? AND phase = ?
            ORDER BY seq ASC
            """,
            (story_id, phase),
        ).fetchall()
    records: list[AttemptRecord] = []
    for row in rows:
        try:
            records.append(
                AttemptRecord(
                    attempt_id=str(row["attempt_id"]),
                    phase=str(row["phase"]),
                    entered_at=datetime.fromisoformat(str(row["entered_at"])),
                    exit_status=(
                        PhaseStatus(str(row["exit_status"]))
                        if row["exit_status"] is not None
                        else None
                    ),
                    guard_evaluations=tuple(
                        cast(
                            "list[dict[str, object]]",
                            _load_json(str(row["guard_evaluations_json"]), []),
                        )
                    ),
                    artifacts_produced=tuple(
                        str(item)
                        for item in cast(
                            "list[object]",
                            _load_json(str(row["artifacts_json"]), []),
                        )
                    ),
                    outcome=str(row["outcome"]) if row["outcome"] is not None else None,
                    yield_status=(
                        str(row["yield_status"])
                        if row["yield_status"] is not None
                        else None
                    ),
                    resume_trigger=(
                        str(row["resume_trigger"])
                        if row["resume_trigger"] is not None
                        else None
                    ),
                )
            )
        except (TypeError, ValueError):
            continue
    return records


def save_flow_execution(story_dir: Path, record: FlowExecution) -> None:
    with _connect(story_dir) as conn:
        conn.execute(
            """
            INSERT INTO flow_executions (
                story_id, project_key, run_id, flow_id, level, owner,
                parent_flow_id, status, current_node_id, attempt_no,
                started_at, finished_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(story_id) DO UPDATE SET
                project_key=excluded.project_key,
                run_id=excluded.run_id,
                flow_id=excluded.flow_id,
                level=excluded.level,
                owner=excluded.owner,
                parent_flow_id=excluded.parent_flow_id,
                status=excluded.status,
                current_node_id=excluded.current_node_id,
                attempt_no=excluded.attempt_no,
                started_at=excluded.started_at,
                finished_at=excluded.finished_at
            """,
            (
                record.story_id,
                record.project_key,
                record.run_id,
                record.flow_id,
                record.level,
                record.owner,
                record.parent_flow_id,
                record.status,
                record.current_node_id,
                record.attempt_no,
                record.started_at.isoformat(),
                record.finished_at.isoformat() if record.finished_at else None,
            ),
        )


def append_execution_event(story_dir: Path, event: ExecutionEventRecord) -> None:
    with _connect(story_dir) as conn:
        _insert_execution_event(conn, event)


def append_execution_event_global(event: ExecutionEventRecord) -> None:
    with _connect_global() as conn:
        _insert_execution_event(conn, event)


def save_session_run_binding_global(record: SessionRunBindingRecord) -> None:
    with _connect_global() as conn:
        conn.execute(
            """
            INSERT INTO session_run_bindings (
                session_id, project_key, story_id, run_id, principal_type,
                worktree_roots_json, binding_version, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT (session_id) DO UPDATE SET
                project_key = EXCLUDED.project_key,
                story_id = EXCLUDED.story_id,
                run_id = EXCLUDED.run_id,
                principal_type = EXCLUDED.principal_type,
                worktree_roots_json = EXCLUDED.worktree_roots_json,
                binding_version = EXCLUDED.binding_version,
                updated_at = EXCLUDED.updated_at
            """,
            (
                record.session_id,
                record.project_key,
                record.story_id,
                record.run_id,
                record.principal_type,
                _dump_json(list(record.worktree_roots)),
                record.binding_version,
                record.updated_at.isoformat(),
            ),
        )


def load_session_run_binding_global(
    session_id: str,
) -> SessionRunBindingRecord | None:
    with _connect_global() as conn:
        row = conn.execute(
            """
            SELECT * FROM session_run_bindings
            WHERE session_id = ?
            """,
            (session_id,),
        ).fetchone()
    if row is None:
        return None
    return SessionRunBindingRecord(
        session_id=str(row["session_id"]),
        project_key=str(row["project_key"]),
        story_id=str(row["story_id"]),
        run_id=str(row["run_id"]),
        principal_type=str(row["principal_type"]),
        worktree_roots=tuple(_load_json(row["worktree_roots_json"], [])),
        binding_version=str(row["binding_version"]),
        updated_at=datetime.fromisoformat(str(row["updated_at"])),
    )


def delete_session_run_binding_global(session_id: str) -> None:
    with _connect_global() as conn:
        conn.execute(
            """
            DELETE FROM session_run_bindings
            WHERE session_id = ?
            """,
            (session_id,),
        )


def save_story_execution_lock_global(record: StoryExecutionLockRecord) -> None:
    with _connect_global() as conn:
        conn.execute(
            """
            INSERT INTO story_execution_locks (
                project_key, story_id, run_id, lock_type, status,
                worktree_roots_json, binding_version, activated_at,
                updated_at, deactivated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT (project_key, run_id, lock_type) DO UPDATE SET
                story_id = EXCLUDED.story_id,
                status = EXCLUDED.status,
                worktree_roots_json = EXCLUDED.worktree_roots_json,
                binding_version = EXCLUDED.binding_version,
                activated_at = EXCLUDED.activated_at,
                updated_at = EXCLUDED.updated_at,
                deactivated_at = EXCLUDED.deactivated_at
            """,
            (
                record.project_key,
                record.story_id,
                record.run_id,
                record.lock_type,
                record.status,
                _dump_json(list(record.worktree_roots)),
                record.binding_version,
                record.activated_at.isoformat(),
                record.updated_at.isoformat(),
                (
                    record.deactivated_at.isoformat()
                    if record.deactivated_at is not None
                    else None
                ),
            ),
        )


def load_story_execution_lock_global(
    project_key: str,
    story_id: str,
    run_id: str,
    lock_type: str = "story_execution",
) -> StoryExecutionLockRecord | None:
    with _connect_global() as conn:
        row = conn.execute(
            """
            SELECT * FROM story_execution_locks
            WHERE project_key = ? AND story_id = ? AND run_id = ? AND lock_type = ?
            """,
            (project_key, story_id, run_id, lock_type),
        ).fetchone()
    if row is None:
        return None
    deactivated_at_raw = row["deactivated_at"]
    return StoryExecutionLockRecord(
        project_key=str(row["project_key"]),
        story_id=str(row["story_id"]),
        run_id=str(row["run_id"]),
        lock_type=str(row["lock_type"]),
        status=str(row["status"]),
        worktree_roots=tuple(_load_json(row["worktree_roots_json"], [])),
        binding_version=str(row["binding_version"]),
        activated_at=datetime.fromisoformat(str(row["activated_at"])),
        updated_at=datetime.fromisoformat(str(row["updated_at"])),
        deactivated_at=(
            datetime.fromisoformat(str(deactivated_at_raw))
            if deactivated_at_raw is not None
            else None
        ),
    )


def save_control_plane_operation_global(record: ControlPlaneOperationRecord) -> None:
    with _connect_global() as conn:
        conn.execute(
            """
            INSERT INTO control_plane_operations (
                op_id, project_key, story_id, run_id, session_id,
                operation_kind, phase, status, response_json,
                created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT (op_id) DO UPDATE SET
                project_key = EXCLUDED.project_key,
                story_id = EXCLUDED.story_id,
                run_id = EXCLUDED.run_id,
                session_id = EXCLUDED.session_id,
                operation_kind = EXCLUDED.operation_kind,
                phase = EXCLUDED.phase,
                status = EXCLUDED.status,
                response_json = EXCLUDED.response_json,
                updated_at = EXCLUDED.updated_at
            """,
            (
                record.op_id,
                record.project_key,
                record.story_id,
                record.run_id,
                record.session_id,
                record.operation_kind,
                record.phase,
                record.status,
                _dump_json(record.response_payload),
                record.created_at.isoformat(),
                record.updated_at.isoformat(),
            ),
        )


def load_control_plane_operation_global(
    op_id: str,
) -> ControlPlaneOperationRecord | None:
    with _connect_global() as conn:
        row = conn.execute(
            """
            SELECT * FROM control_plane_operations
            WHERE op_id = ?
            """,
            (op_id,),
        ).fetchone()
    if row is None:
        return None
    return ControlPlaneOperationRecord(
        op_id=str(row["op_id"]),
        project_key=str(row["project_key"]),
        story_id=str(row["story_id"]),
        run_id=_cast_optional_str(row["run_id"]),
        session_id=_cast_optional_str(row["session_id"]),
        operation_kind=str(row["operation_kind"]),
        phase=_cast_optional_str(row["phase"]),
        status=str(row["status"]),
        response_payload=_cast_json_record(_load_json(row["response_json"], {})),
        created_at=datetime.fromisoformat(str(row["created_at"])),
        updated_at=datetime.fromisoformat(str(row["updated_at"])),
    )


def load_execution_events(
    story_dir: Path,
    *,
    project_key: str | None = None,
    story_id: str | None = None,
    run_id: str | None = None,
    event_type: str | None = None,
) -> list[ExecutionEventRecord]:
    clauses: list[str] = []
    params: list[object] = []
    if project_key is not None:
        clauses.append(_PROJECT_KEY_FILTER)
        params.append(project_key)
    if story_id is not None:
        clauses.append(_STORY_ID_FILTER)
        params.append(story_id)
    if run_id is not None:
        clauses.append(_RUN_ID_FILTER)
        params.append(run_id)
    if event_type is not None:
        clauses.append("event_type = ?")
        params.append(event_type)
    where_clause = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    with _connect(story_dir) as conn:
        rows = conn.execute(
            f"""
            SELECT project_key, story_id, run_id, event_id, event_type,
                   occurred_at, source_component, severity, phase, flow_id,
                   node_id, payload_json
            FROM execution_events
            {where_clause}
            ORDER BY occurred_at ASC, event_id ASC
            """,
            tuple(params),
        ).fetchall()
    events: list[ExecutionEventRecord] = []
    for row in rows:
        events.append(
            ExecutionEventRecord(
                project_key=str(row["project_key"]),
                story_id=str(row["story_id"]),
                run_id=str(row["run_id"]),
                event_id=str(row["event_id"]),
                event_type=str(row["event_type"]),
                occurred_at=datetime.fromisoformat(str(row["occurred_at"])),
                source_component=str(row["source_component"]),
                severity=str(row["severity"]),
                phase=str(row["phase"]) if row["phase"] is not None else None,
                flow_id=str(row["flow_id"]) if row["flow_id"] is not None else None,
                node_id=str(row["node_id"]) if row["node_id"] is not None else None,
                payload=_cast_json_record(_load_json(str(row["payload_json"]), {})),
            )
        )
    return events


def load_flow_execution(story_dir: Path) -> FlowExecution | None:
    story_id = _story_id_for(story_dir)
    if story_id is None:
        return None
    with _connect(story_dir) as conn:
        row = conn.execute(
            """
            SELECT * FROM flow_executions
            WHERE story_id = ?
            """,
            (story_id,),
        ).fetchone()
    if row is None:
        return None
    return FlowExecution(
        project_key=str(row["project_key"]),
        story_id=str(row["story_id"]),
        run_id=str(row["run_id"]),
        flow_id=str(row["flow_id"]),
        level=str(row["level"]),
        owner=str(row["owner"]),
        parent_flow_id=(
            str(row["parent_flow_id"]) if row["parent_flow_id"] is not None else None
        ),
        status=str(row["status"]),
        current_node_id=(
            str(row["current_node_id"]) if row["current_node_id"] is not None else None
        ),
        attempt_no=int(row["attempt_no"]),
        started_at=datetime.fromisoformat(str(row["started_at"])),
        finished_at=(
            datetime.fromisoformat(str(row["finished_at"]))
            if row["finished_at"] is not None
            else None
        ),
    )


def upsert_story_metrics(story_dir: Path, metrics: StoryMetricsRecord) -> None:
    with _connect(story_dir) as conn:
        conn.execute(
            """
            INSERT INTO story_metrics (
                project_key, story_id, run_id, story_type, story_size, mode,
                processing_time_min, qa_rounds, increments, final_status,
                completed_at, adversarial_findings, adversarial_tests_created,
                files_changed, agentkit_version, agentkit_commit,
                config_version, llm_roles_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(project_key, run_id) DO UPDATE SET
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
            (
                metrics.project_key,
                metrics.story_id,
                metrics.run_id,
                metrics.story_type,
                metrics.story_size,
                metrics.mode,
                metrics.processing_time_min,
                metrics.qa_rounds,
                metrics.increments,
                metrics.final_status,
                metrics.completed_at,
                metrics.adversarial_findings,
                metrics.adversarial_tests_created,
                metrics.files_changed,
                metrics.agentkit_version,
                metrics.agentkit_commit,
                metrics.config_version,
                _dump_json(list(metrics.llm_roles)),
            ),
        )


def load_story_metrics(
    story_dir: Path,
    *,
    project_key: str | None = None,
    story_id: str | None = None,
    run_id: str | None = None,
) -> list[StoryMetricsRecord]:
    clauses: list[str] = []
    params: list[object] = []
    if project_key is not None:
        clauses.append(_PROJECT_KEY_FILTER)
        params.append(project_key)
    if story_id is not None:
        clauses.append(_STORY_ID_FILTER)
        params.append(story_id)
    if run_id is not None:
        clauses.append(_RUN_ID_FILTER)
        params.append(run_id)
    where_clause = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    with _connect(story_dir) as conn:
        rows = conn.execute(
            f"""
            SELECT *
            FROM story_metrics
            {where_clause}
            ORDER BY completed_at ASC, run_id ASC
            """,
            tuple(params),
        ).fetchall()
    return [_story_metrics_from_row(row) for row in rows]


def load_story_metrics_for_scope(
    scope: RuntimeStateScope,
) -> list[StoryMetricsRecord]:
    return load_story_metrics(
        scope.story_dir,
        project_key=scope.project_key,
        story_id=scope.story_id,
        run_id=scope.run_id,
    )


def load_qa_stage_results(
    story_dir: Path,
    *,
    project_key: str | None = None,
    story_id: str | None = None,
    run_id: str | None = None,
    attempt_no: int | None = None,
    stage_id: str | None = None,
) -> list[QAStageResultRecord]:
    clauses: list[str] = []
    params: list[object] = []
    if project_key is not None:
        clauses.append(_PROJECT_KEY_FILTER)
        params.append(project_key)
    if story_id is not None:
        clauses.append(_STORY_ID_FILTER)
        params.append(story_id)
    if run_id is not None:
        clauses.append(_RUN_ID_FILTER)
        params.append(run_id)
    if attempt_no is not None:
        clauses.append("attempt_no = ?")
        params.append(attempt_no)
    if stage_id is not None:
        clauses.append("stage_id = ?")
        params.append(stage_id)
    where_clause = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    with _connect(story_dir) as conn:
        rows = conn.execute(
            f"""
            SELECT *
            FROM qa_stage_results
            {where_clause}
            ORDER BY attempt_no ASC, stage_id ASC
            """,
            tuple(params),
        ).fetchall()
    return [_qa_stage_result_from_row(row) for row in rows]


def load_qa_stage_results_for_scope(
    scope: RuntimeStateScope,
    *,
    attempt_no: int | None = None,
    stage_id: str | None = None,
) -> list[QAStageResultRecord]:
    return load_qa_stage_results(
        scope.story_dir,
        project_key=scope.project_key,
        story_id=scope.story_id,
        run_id=scope.run_id,
        attempt_no=attempt_no,
        stage_id=stage_id,
    )


def load_qa_findings(
    story_dir: Path,
    *,
    project_key: str | None = None,
    story_id: str | None = None,
    run_id: str | None = None,
    attempt_no: int | None = None,
    stage_id: str | None = None,
) -> list[QAFindingRecord]:
    clauses: list[str] = []
    params: list[object] = []
    if project_key is not None:
        clauses.append(_PROJECT_KEY_FILTER)
        params.append(project_key)
    if story_id is not None:
        clauses.append(_STORY_ID_FILTER)
        params.append(story_id)
    if run_id is not None:
        clauses.append(_RUN_ID_FILTER)
        params.append(run_id)
    if attempt_no is not None:
        clauses.append("attempt_no = ?")
        params.append(attempt_no)
    if stage_id is not None:
        clauses.append("stage_id = ?")
        params.append(stage_id)
    where_clause = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    with _connect(story_dir) as conn:
        rows = conn.execute(
            f"""
            SELECT *
            FROM qa_findings
            {where_clause}
            ORDER BY attempt_no ASC, stage_id ASC, occurred_at ASC, finding_id ASC
            """,
            tuple(params),
        ).fetchall()
    return [_qa_finding_from_row(row) for row in rows]


def load_qa_findings_for_scope(
    scope: RuntimeStateScope,
    *,
    attempt_no: int | None = None,
    stage_id: str | None = None,
) -> list[QAFindingRecord]:
    return load_qa_findings(
        scope.story_dir,
        project_key=scope.project_key,
        story_id=scope.story_id,
        run_id=scope.run_id,
        attempt_no=attempt_no,
        stage_id=stage_id,
    )


def save_node_execution_ledger(story_dir: Path, record: NodeExecutionLedger) -> None:
    with _connect(story_dir) as conn:
        conn.execute(
            """
            INSERT INTO node_execution_ledgers (
                story_id, flow_id, node_id, project_key, run_id,
                execution_count, success_count, last_outcome,
                last_attempt_no, last_executed_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(story_id, flow_id, node_id) DO UPDATE SET
                project_key=excluded.project_key,
                run_id=excluded.run_id,
                execution_count=excluded.execution_count,
                success_count=excluded.success_count,
                last_outcome=excluded.last_outcome,
                last_attempt_no=excluded.last_attempt_no,
                last_executed_at=excluded.last_executed_at
            """,
            (
                record.story_id,
                record.flow_id,
                record.node_id,
                record.project_key,
                record.run_id,
                record.execution_count,
                record.success_count,
                record.last_outcome,
                record.last_attempt_no,
                (
                    record.last_executed_at.isoformat()
                    if record.last_executed_at is not None
                    else None
                ),
            ),
        )


def load_node_execution_ledger(
    story_dir: Path,
    flow_id: str,
    node_id: str,
) -> NodeExecutionLedger | None:
    story_id = _story_id_for(story_dir)
    if story_id is None:
        return None
    with _connect(story_dir) as conn:
        row = conn.execute(
            """
            SELECT * FROM node_execution_ledgers
            WHERE story_id = ? AND flow_id = ? AND node_id = ?
            """,
            (story_id, flow_id, node_id),
        ).fetchone()
    if row is None:
        return None
    return NodeExecutionLedger(
        project_key=str(row["project_key"]),
        story_id=str(row["story_id"]),
        run_id=str(row["run_id"]),
        flow_id=str(row["flow_id"]),
        node_id=str(row["node_id"]),
        execution_count=int(row["execution_count"]),
        success_count=int(row["success_count"]),
        last_outcome=str(row["last_outcome"]) if row["last_outcome"] else None,
        last_attempt_no=(
            int(row["last_attempt_no"]) if row["last_attempt_no"] is not None else None
        ),
        last_executed_at=(
            datetime.fromisoformat(str(row["last_executed_at"]))
            if row["last_executed_at"] is not None
            else None
        ),
    )


def _story_metrics_from_row(row: dict[str, Any]) -> StoryMetricsRecord:
    llm_roles = _load_json(str(row["llm_roles_json"]), [])
    return StoryMetricsRecord(
        project_key=str(row["project_key"]),
        story_id=str(row["story_id"]),
        run_id=str(row["run_id"]),
        story_type=str(row["story_type"]),
        story_size=str(row["story_size"]),
        mode=str(row["mode"]),
        processing_time_min=float(row["processing_time_min"]),
        qa_rounds=int(row["qa_rounds"]),
        increments=int(row["increments"]),
        final_status=str(row["final_status"]),
        completed_at=str(row["completed_at"]),
        adversarial_findings=(
            int(row["adversarial_findings"])
            if row["adversarial_findings"] is not None
            else None
        ),
        adversarial_tests_created=(
            int(row["adversarial_tests_created"])
            if row["adversarial_tests_created"] is not None
            else None
        ),
        files_changed=(
            int(row["files_changed"])
            if row["files_changed"] is not None
            else None
        ),
        agentkit_version=(
            str(row["agentkit_version"])
            if row["agentkit_version"] is not None
            else None
        ),
        agentkit_commit=(
            str(row["agentkit_commit"])
            if row["agentkit_commit"] is not None
            else None
        ),
        config_version=(
            str(row["config_version"])
            if row["config_version"] is not None
            else None
        ),
        llm_roles=tuple(str(role) for role in llm_roles if isinstance(role, str)),
    )


def _qa_stage_result_from_row(row: dict[str, Any]) -> QAStageResultRecord:
    return QAStageResultRecord(
        project_key=str(row["project_key"]),
        story_id=str(row["story_id"]),
        run_id=str(row["run_id"]),
        attempt_no=int(row["attempt_no"]),
        stage_id=str(row["stage_id"]),
        layer=str(row["layer"]),
        producer_component=str(row["producer_component"]),
        status=str(row["status"]),
        blocking=bool(row["blocking"]),
        total_checks=int(row["total_checks"]),
        failed_checks=int(row["failed_checks"]),
        warning_checks=int(row["warning_checks"]),
        artifact_id=str(row["artifact_id"]),
        recorded_at=datetime.fromisoformat(str(row["recorded_at"])),
    )


def _qa_finding_from_row(row: dict[str, Any]) -> QAFindingRecord:
    return QAFindingRecord(
        project_key=str(row["project_key"]),
        story_id=str(row["story_id"]),
        run_id=str(row["run_id"]),
        attempt_no=int(row["attempt_no"]),
        stage_id=str(row["stage_id"]),
        finding_id=str(row["finding_id"]),
        check_id=str(row["check_id"]),
        status=str(row["status"]),
        severity=str(row["severity"]),
        blocking=bool(row["blocking"]),
        source_component=str(row["source_component"]),
        artifact_id=str(row["artifact_id"]),
        occurred_at=datetime.fromisoformat(str(row["occurred_at"])),
        category=str(row["category"]) if row["category"] is not None else None,
        reason=str(row["reason"]) if row["reason"] is not None else None,
        description=(
            str(row["description"]) if row["description"] is not None else None
        ),
        detail=str(row["detail"]) if row["detail"] is not None else None,
        metadata=_cast_json_record(_load_json(str(row["metadata_json"]), {})),
    )


def save_override_record(story_dir: Path, record: OverrideRecord) -> None:
    with _connect(story_dir) as conn:
        conn.execute(
            """
            INSERT INTO override_records (
                override_id, story_id, project_key, run_id, flow_id,
                target_node_id, override_type, actor_type, actor_id,
                reason, created_at, consumed_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(override_id) DO UPDATE SET
                target_node_id=excluded.target_node_id,
                override_type=excluded.override_type,
                actor_type=excluded.actor_type,
                actor_id=excluded.actor_id,
                reason=excluded.reason,
                created_at=excluded.created_at,
                consumed_at=excluded.consumed_at
            """,
            (
                record.override_id,
                record.story_id,
                record.project_key,
                record.run_id,
                record.flow_id,
                record.target_node_id,
                record.override_type,
                record.actor_type,
                record.actor_id,
                record.reason,
                record.created_at.isoformat(),
                record.consumed_at.isoformat() if record.consumed_at else None,
            ),
        )


def load_override_records(story_dir: Path) -> tuple[OverrideRecord, ...]:
    story_id = _story_id_for(story_dir)
    if story_id is None:
        return ()
    with _connect(story_dir) as conn:
        rows = conn.execute(
            """
            SELECT * FROM override_records
            WHERE story_id = ?
            ORDER BY created_at ASC
            """,
            (story_id,),
        ).fetchall()
    return tuple(
        OverrideRecord(
            override_id=str(row["override_id"]),
            project_key=str(row["project_key"]),
            story_id=str(row["story_id"]),
            run_id=str(row["run_id"]),
            flow_id=str(row["flow_id"]),
            target_node_id=(
                str(row["target_node_id"])
                if row["target_node_id"] is not None
                else None
            ),
            override_type=str(row["override_type"]),
            actor_type=str(row["actor_type"]),
            actor_id=str(row["actor_id"]),
            reason=str(row["reason"]),
            created_at=datetime.fromisoformat(str(row["created_at"])),
            consumed_at=(
                datetime.fromisoformat(str(row["consumed_at"]))
                if row["consumed_at"] is not None
                else None
            ),
        )
        for row in rows
    )

def record_layer_artifacts(
    story_dir: Path,
    *,
    layer_results: tuple[LayerResult, ...],
    attempt_nr: int,
    projection_dir: Path | None = None,
) -> tuple[str, ...]:
    story_id = _story_id_for(story_dir)
    if story_id is None:
        raise CorruptStateError(
            "Cannot persist QA layer artifacts without story context "
            "in canonical backend",
        )
    flow = load_flow_execution(story_dir)
    if flow is None:
        raise CorruptStateError(
            "Cannot materialize FK-16 QA read models without flow execution "
            "scope in canonical Postgres backend",
        )
    produced: list[str] = []
    with _connect(story_dir) as conn:
        for layer_result in layer_results:
            payload = serialize_layer_result(
                layer_result,
                attempt_nr=attempt_nr,
            )
            artifact_name = write_layer_projection(
                story_dir,
                layer_result=layer_result,
                attempt_nr=attempt_nr,
                projection_dir=projection_dir,
            )
            if artifact_name is None:
                continue
            recorded_at = datetime.fromisoformat(now_iso())
            producer_component = producer_component_for_layer(layer_result.layer)
            artifact_id = _upsert_artifact_record(
                conn,
                flow=flow,
                artifact_kind=layer_result.layer,
                artifact_name=artifact_name,
                producer_component=producer_component,
                lifecycle_status="PASS" if layer_result.passed else "FAIL",
                payload=payload,
                created_at=recorded_at,
                attempt_no=attempt_nr,
            )
            conn.execute(
                """
                DELETE FROM qa_findings
                WHERE project_key = ? AND run_id = ? AND attempt_no = ? AND stage_id = ?
                """,
                (
                    flow.project_key,
                    flow.run_id,
                    attempt_nr,
                    layer_result.layer,
                ),
            )
            stage_record = build_qa_stage_result(
                flow,
                layer_result,
                attempt_no=attempt_nr,
                artifact_id=artifact_id,
                recorded_at=recorded_at,
            )
            conn.execute(
                """
                INSERT INTO qa_stage_results (
                    project_key, story_id, run_id, attempt_no, stage_id, layer,
                    producer_component, status, blocking, total_checks,
                    failed_checks, warning_checks, artifact_id, recorded_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(project_key, run_id, attempt_no, stage_id)
                DO UPDATE SET
                    story_id=excluded.story_id,
                    layer=excluded.layer,
                    producer_component=excluded.producer_component,
                    status=excluded.status,
                    blocking=excluded.blocking,
                    total_checks=excluded.total_checks,
                    failed_checks=excluded.failed_checks,
                    warning_checks=excluded.warning_checks,
                    artifact_id=excluded.artifact_id,
                    recorded_at=excluded.recorded_at
                """,
                (
                    stage_record.project_key,
                    stage_record.story_id,
                    stage_record.run_id,
                    stage_record.attempt_no,
                    stage_record.stage_id,
                    stage_record.layer,
                    stage_record.producer_component,
                    stage_record.status,
                    1 if stage_record.blocking else 0,
                    stage_record.total_checks,
                    stage_record.failed_checks,
                    stage_record.warning_checks,
                    stage_record.artifact_id,
                    stage_record.recorded_at.isoformat(),
                ),
            )
            for finding_record in build_qa_findings(
                flow,
                layer_result,
                attempt_no=attempt_nr,
                artifact_id=artifact_id,
                recorded_at=recorded_at,
            ):
                conn.execute(
                    """
                    INSERT INTO qa_findings (
                        project_key, story_id, run_id, attempt_no, stage_id,
                        finding_id, check_id, status, severity, blocking,
                        source_component, artifact_id, occurred_at, category,
                        reason, description, detail, metadata_json
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(project_key, run_id, attempt_no, stage_id, finding_id)
                    DO UPDATE SET
                        story_id=excluded.story_id,
                        check_id=excluded.check_id,
                        status=excluded.status,
                        severity=excluded.severity,
                        blocking=excluded.blocking,
                        source_component=excluded.source_component,
                        artifact_id=excluded.artifact_id,
                        occurred_at=excluded.occurred_at,
                        category=excluded.category,
                        reason=excluded.reason,
                        description=excluded.description,
                        detail=excluded.detail,
                        metadata_json=excluded.metadata_json
                    """,
                    (
                        finding_record.project_key,
                        finding_record.story_id,
                        finding_record.run_id,
                        finding_record.attempt_no,
                        finding_record.stage_id,
                        finding_record.finding_id,
                        finding_record.check_id,
                        finding_record.status,
                        finding_record.severity,
                        1 if finding_record.blocking else 0,
                        finding_record.source_component,
                        finding_record.artifact_id,
                        finding_record.occurred_at.isoformat(),
                        finding_record.category,
                        finding_record.reason,
                        finding_record.description,
                        finding_record.detail,
                        _dump_json(finding_record.metadata),
                    ),
                )
            produced.append(artifact_name)
    return tuple(produced)


def record_verify_decision(
    story_dir: Path,
    *,
    decision: VerifyDecision,
    attempt_nr: int,
    projection_dir: Path | None = None,
) -> tuple[str, ...]:
    story_id = _story_id_for(story_dir)
    if story_id is None:
        raise CorruptStateError(
            "Cannot persist verify decision without story context in canonical backend",
        )
    flow = load_flow_execution(story_dir)
    if flow is None:
        raise CorruptStateError(
            "Cannot persist verify decision artifact without flow execution "
            "scope in canonical Postgres backend",
        )
    canonical_payload = build_verify_decision_artifact(
        decision,
        attempt_nr=attempt_nr,
    )
    written = write_verify_decision_projection(
        story_dir,
        decision=decision,
        attempt_nr=attempt_nr,
        projection_dir=projection_dir,
    )
    with _connect(story_dir) as conn:
        recorded_at = datetime.fromisoformat(now_iso())
        conn.execute(
            """
            INSERT INTO decision_records (
                project_key, story_id, run_id, flow_id, decision_kind,
                attempt_nr, status, passed, summary, payload_json, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(project_key, run_id, decision_kind, attempt_nr)
            DO UPDATE SET
                story_id=excluded.story_id,
                flow_id=excluded.flow_id,
                status=excluded.status,
                passed=excluded.passed,
                summary=excluded.summary,
                payload_json=excluded.payload_json,
                created_at=excluded.created_at
            """,
            (
                flow.project_key,
                story_id,
                flow.run_id,
                flow.flow_id,
                "verify",
                attempt_nr,
                decision.status,
                1 if decision.passed else 0,
                decision.summary,
                _dump_json(canonical_payload),
                recorded_at.isoformat(),
            ),
        )
        _upsert_artifact_record(
            conn,
            flow=flow,
            artifact_kind="verify_decision",
            artifact_name=written[0],
            producer_component="qa-policy-engine",
            lifecycle_status=decision.status,
            payload=canonical_payload,
            created_at=recorded_at,
            attempt_no=attempt_nr,
        )
    return written


def load_latest_verify_decision(story_dir: Path) -> dict[str, object] | None:
    story_id = _story_id_for(story_dir)
    if story_id is None:
        return None
    flow = load_flow_execution(story_dir)
    with _connect(story_dir) as conn:
        if flow is not None:
            row = conn.execute(
                """
                SELECT payload_json
                FROM decision_records
                WHERE project_key = ? AND story_id = ? AND run_id = ?
                  AND decision_kind = 'verify'
                ORDER BY attempt_nr DESC
                LIMIT 1
                """,
                (flow.project_key, flow.story_id, flow.run_id),
            ).fetchone()
            if row is None:
                row = conn.execute(
                    """
                    SELECT payload_json
                    FROM decision_records
                    WHERE story_id = ? AND decision_kind = 'verify'
                    ORDER BY attempt_nr DESC
                    LIMIT 1
                    """,
                    (story_id,),
                ).fetchone()
        else:
            row = conn.execute(
                """
                SELECT payload_json
                FROM decision_records
                WHERE story_id = ? AND decision_kind = 'verify'
                ORDER BY attempt_nr DESC
                LIMIT 1
                """,
                (story_id,),
            ).fetchone()
    if row is None:
        return None
    try:
        return _cast_json_record(json.loads(str(row["payload_json"])))
    except json.JSONDecodeError as exc:
        raise CorruptStateError(
            f"decision_records payload is invalid in {_database_label()}: {exc}",
        ) from exc


def load_latest_verify_decision_for_scope(
    scope: RuntimeStateScope,
) -> dict[str, object] | None:
    with _connect(scope.story_dir) as conn:
        row = conn.execute(
            """
            SELECT payload_json
            FROM decision_records
            WHERE project_key = ? AND story_id = ? AND run_id = ?
              AND decision_kind = 'verify'
            ORDER BY attempt_nr DESC
            LIMIT 1
            """,
            (scope.project_key, scope.story_id, scope.run_id),
        ).fetchone()
    if row is None:
        return None
    try:
        return _cast_json_record(json.loads(str(row["payload_json"])))
    except json.JSONDecodeError as exc:
        raise CorruptStateError(
            f"decision_records payload is invalid in {_database_label()}: {exc}",
        ) from exc


def read_latest_verify_decision_record(story_dir: Path) -> dict[str, object] | None:
    """Canonical reader name for protected runtime modules."""

    return load_latest_verify_decision(story_dir)


def load_artifact_record(
    story_dir: Path,
    artifact_kind: str,
) -> dict[str, object] | None:
    story_id = _story_id_for(story_dir)
    if story_id is None:
        return None
    flow = load_flow_execution(story_dir)
    with _connect(story_dir) as conn:
        if flow is not None:
            row = conn.execute(
                """
                SELECT payload_json
                FROM artifact_records
                WHERE project_key = ? AND story_id = ? AND run_id = ?
                  AND artifact_kind = ?
                ORDER BY attempt_no DESC NULLS LAST, created_at DESC
                LIMIT 1
                """,
                (flow.project_key, flow.story_id, flow.run_id, artifact_kind),
            ).fetchone()
        else:
            row = conn.execute(
                """
                SELECT payload_json
                FROM artifact_records
                WHERE story_id = ? AND artifact_kind = ?
                ORDER BY attempt_nr DESC, created_at DESC
                LIMIT 1
                """,
                (story_id, artifact_kind),
            ).fetchone()
    if row is None:
        return None
    try:
        return _cast_json_record(json.loads(str(row["payload_json"])))
    except json.JSONDecodeError as exc:
        raise CorruptStateError(
            f"artifact_records payload is invalid in {_database_label()}: {exc}",
        ) from exc


def load_artifact_record_for_scope(
    scope: RuntimeStateScope,
    artifact_kind: str,
) -> dict[str, object] | None:
    with _connect(scope.story_dir) as conn:
        row = conn.execute(
            """
            SELECT payload_json
            FROM artifact_records
            WHERE project_key = ? AND story_id = ? AND run_id = ?
              AND artifact_kind = ?
            ORDER BY attempt_no DESC NULLS LAST, created_at DESC
            LIMIT 1
            """,
            (scope.project_key, scope.story_id, scope.run_id, artifact_kind),
        ).fetchone()
    if row is None:
        return None
    try:
        return _cast_json_record(json.loads(str(row["payload_json"])))
    except json.JSONDecodeError as exc:
        raise CorruptStateError(
            f"artifact_records payload is invalid in {_database_label()}: {exc}",
        ) from exc


def read_artifact_record(
    story_dir: Path,
    artifact_kind: str,
) -> dict[str, object] | None:
    """Canonical reader name for protected runtime modules."""

    return load_artifact_record(story_dir, artifact_kind)


def record_closure_report(
    story_dir: Path,
    report: ExecutionReport,
    *,
    projection_dir: Path | None = None,
) -> Path:
    flow = load_flow_execution(story_dir)
    if flow is None:
        raise CorruptStateError(
            "Cannot persist closure artifact without flow execution scope "
            "in canonical Postgres backend",
        )
    path = write_execution_report_projection(
        story_dir,
        report,
        projection_dir=projection_dir,
    )
    payload = report.to_dict()
    with _connect(story_dir) as conn:
        _upsert_artifact_record(
            conn,
            flow=flow,
            artifact_kind="closure_report",
            artifact_name=path.name,
            producer_component="story-closure",
            lifecycle_status=report.status.upper(),
            payload=payload,
            created_at=datetime.fromisoformat(now_iso()),
        )
    return path


def backend_has_valid_context(story_dir: Path) -> bool:
    return load_story_context(story_dir) is not None


def backend_has_valid_phase_state(story_dir: Path) -> bool:
    return load_phase_state(story_dir) is not None


def backend_has_completed_snapshot(story_dir: Path, phase: str) -> bool:
    snapshot = load_phase_snapshot(story_dir, phase)
    return snapshot is not None and snapshot.status == PhaseStatus.COMPLETED


def backend_has_structural_artifact(story_dir: Path) -> bool:
    record = load_artifact_record(story_dir, "structural")
    return record is not None


def backend_has_structural_artifact_for_scope(scope: RuntimeStateScope) -> bool:
    return load_artifact_record_for_scope(scope, "structural") is not None


def backend_verify_decision_passed(story_dir: Path) -> bool:
    payload = load_latest_verify_decision(story_dir)
    if payload is None:
        return False
    status = payload.get("status")
    return (
        isinstance(status, str)
        and bool(payload.get("passed"))
        and status in ("PASS", "PASS_WITH_WARNINGS")
    )


def backend_verify_decision_passed_for_scope(scope: RuntimeStateScope) -> bool:
    payload = load_latest_verify_decision_for_scope(scope)
    if payload is None:
        return False
    status = payload.get("status")
    return (
        isinstance(status, str)
        and bool(payload.get("passed"))
        and status in ("PASS", "PASS_WITH_WARNINGS")
    )
