"""SQLite-backed canonical runtime store with JSON projections."""

from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from typing import TYPE_CHECKING, Any, cast

from agentkit.exceptions import CorruptStateError
from agentkit.phase_state_store.models import (
    FlowExecution,
    NodeExecutionLedger,
    OverrideRecord,
)
from agentkit.state_backend.exports import (
    build_verify_decision_artifact,
    load_json_object,
    now_iso,
    serialize_layer_result,
    state_db_path,
    write_execution_report_projection,
    write_layer_projection,
    write_phase_snapshot_projection,
    write_phase_state_projection,
    write_story_context_projection,
    write_verify_decision_projection,
)
from agentkit.state_backend.records import AttemptRecord, ExecutionReport
from agentkit.story_context_manager.models import (
    PhaseSnapshot,
    PhaseState,
    PhaseStatus,
    StoryContext,
)

if TYPE_CHECKING:
    from pathlib import Path

    from agentkit.qa.policy_engine.engine import VerifyDecision
    from agentkit.qa.protocols import LayerResult


def load_json_safe(path: Path) -> dict[str, object] | None:
    """Compatibility helper for non-canonical export reads."""

    return load_json_object(path)


def _dump_json(data: object) -> str:
    return json.dumps(data, sort_keys=True, default=str)


def _load_json(data: str | None, default: Any) -> Any:
    if data is None:
        return default
    return json.loads(data)


@contextmanager
def _connect(story_dir: Path) -> sqlite3.Connection:
    db_path = state_db_path(story_dir)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    _ensure_schema(conn)
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def _ensure_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS story_contexts (
            story_id TEXT PRIMARY KEY,
            story_type TEXT NOT NULL,
            execution_route TEXT NOT NULL,
            implementation_contract TEXT,
            issue_nr INTEGER,
            title TEXT NOT NULL,
            payload_json TEXT NOT NULL,
            updated_at TEXT NOT NULL
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
            story_id TEXT NOT NULL,
            artifact_kind TEXT NOT NULL,
            artifact_name TEXT NOT NULL,
            producer TEXT NOT NULL,
            status TEXT,
            attempt_nr INTEGER,
            payload_json TEXT NOT NULL,
            created_at TEXT NOT NULL,
            PRIMARY KEY (story_id, artifact_kind, artifact_name, attempt_nr)
        );

        CREATE TABLE IF NOT EXISTS decision_records (
            story_id TEXT NOT NULL,
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
    )


def _story_id_for(story_dir: Path) -> str | None:
    with _connect(story_dir) as conn:
        row = conn.execute(
            "SELECT story_id FROM story_contexts LIMIT 1",
        ).fetchone()
    if row is None:
        return None
    return str(row["story_id"])


def save_story_context(story_dir: Path, ctx: StoryContext) -> None:
    payload = ctx.model_dump(mode="json")
    with _connect(story_dir) as conn:
        conn.execute(
            """
            INSERT INTO story_contexts (
                story_id, story_type, execution_route, implementation_contract,
                issue_nr, title, payload_json, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(story_id) DO UPDATE SET
                story_type=excluded.story_type,
                execution_route=excluded.execution_route,
                implementation_contract=excluded.implementation_contract,
                issue_nr=excluded.issue_nr,
                title=excluded.title,
                payload_json=excluded.payload_json,
                updated_at=excluded.updated_at
            """,
            (
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
        row = conn.execute(
            """
            SELECT payload_json FROM story_contexts
            WHERE story_id = ?
            """,
            (story_id,),
        ).fetchone()
    if row is None:
        return None
    try:
        return StoryContext.model_validate(json.loads(str(row["payload_json"])))
    except Exception as exc:  # noqa: BLE001
        raise CorruptStateError(
            f"story_contexts payload is invalid in {state_db_path(story_dir)}: {exc}",
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
            f"phase_states payload is invalid in {state_db_path(story_dir)}: {exc}",
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
            f"{state_db_path(story_dir)} for phase {phase!r}: {exc}",
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


_ARTIFACT_PRODUCERS: dict[str, str] = {
    "structural": "qa-structural-check",
    "semantic": "qa-semantic-review",
    "adversarial": "qa-adversarial",
}


def record_layer_artifacts(
    story_dir: Path,
    *,
    layer_results: tuple[LayerResult, ...],
    attempt_nr: int,
) -> tuple[str, ...]:
    story_id = _story_id_for(story_dir)
    if story_id is None:
        raise CorruptStateError(
            "Cannot persist QA layer artifacts without story context "
            "in canonical backend",
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
            )
            if artifact_name is None:
                continue
            conn.execute(
                """
                INSERT INTO artifact_records (
                    story_id, artifact_kind, artifact_name, producer,
                    status, attempt_nr, payload_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(story_id, artifact_kind, artifact_name, attempt_nr)
                DO UPDATE SET
                    producer=excluded.producer,
                    status=excluded.status,
                    payload_json=excluded.payload_json,
                    created_at=excluded.created_at
                """,
                (
                    story_id,
                    layer_result.layer,
                    artifact_name,
                    _ARTIFACT_PRODUCERS.get(layer_result.layer, "qa-layer"),
                    "PASS" if layer_result.passed else "FAIL",
                    attempt_nr,
                    _dump_json(payload),
                    now_iso(),
                ),
            )
            produced.append(artifact_name)
    return tuple(produced)


def record_verify_decision(
    story_dir: Path,
    *,
    decision: VerifyDecision,
    attempt_nr: int,
) -> tuple[str, str]:
    story_id = _story_id_for(story_dir)
    if story_id is None:
        raise CorruptStateError(
            "Cannot persist verify decision without story context in canonical backend",
        )
    canonical_payload = build_verify_decision_artifact(
        decision,
        attempt_nr=attempt_nr,
    )
    written = write_verify_decision_projection(
        story_dir,
        decision=decision,
        attempt_nr=attempt_nr,
    )
    with _connect(story_dir) as conn:
        conn.execute(
            """
            INSERT INTO decision_records (
                story_id, decision_kind, attempt_nr, status, passed,
                summary, payload_json, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(story_id, decision_kind, attempt_nr) DO UPDATE SET
                status=excluded.status,
                passed=excluded.passed,
                summary=excluded.summary,
                payload_json=excluded.payload_json,
                created_at=excluded.created_at
            """,
            (
                story_id,
                "verify",
                attempt_nr,
                decision.status,
                1 if decision.passed else 0,
                decision.summary,
                _dump_json(canonical_payload),
                now_iso(),
            ),
        )
        conn.execute(
            """
            INSERT INTO artifact_records (
                story_id, artifact_kind, artifact_name, producer,
                status, attempt_nr, payload_json, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(story_id, artifact_kind, artifact_name, attempt_nr)
            DO UPDATE SET
                producer=excluded.producer,
                status=excluded.status,
                payload_json=excluded.payload_json,
                created_at=excluded.created_at
            """,
            (
                story_id,
                "verify_decision",
                written[0],
                "qa-policy-engine",
                decision.status,
                attempt_nr,
                _dump_json(canonical_payload),
                now_iso(),
            ),
        )
    return written


def load_latest_verify_decision(story_dir: Path) -> dict[str, object] | None:
    story_id = _story_id_for(story_dir)
    if story_id is None:
        return None
    with _connect(story_dir) as conn:
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
        return cast("dict[str, object]", json.loads(str(row["payload_json"])))
    except json.JSONDecodeError as exc:
        raise CorruptStateError(
            f"decision_records payload is invalid in {state_db_path(story_dir)}: {exc}",
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
    with _connect(story_dir) as conn:
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
        return cast("dict[str, object]", json.loads(str(row["payload_json"])))
    except json.JSONDecodeError as exc:
        raise CorruptStateError(
            f"artifact_records payload is invalid in {state_db_path(story_dir)}: {exc}",
        ) from exc


def read_artifact_record(
    story_dir: Path,
    artifact_kind: str,
) -> dict[str, object] | None:
    """Canonical reader name for protected runtime modules."""

    return load_artifact_record(story_dir, artifact_kind)


def record_closure_report(story_dir: Path, report: ExecutionReport) -> Path:
    story_id = _story_id_for(story_dir) or report.story_id
    path = write_execution_report_projection(story_dir, report)
    payload = report.to_dict()
    with _connect(story_dir) as conn:
        conn.execute(
            """
            INSERT INTO artifact_records (
                story_id, artifact_kind, artifact_name, producer,
                status, attempt_nr, payload_json, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(story_id, artifact_kind, artifact_name, attempt_nr)
            DO UPDATE SET
                producer=excluded.producer,
                status=excluded.status,
                payload_json=excluded.payload_json,
                created_at=excluded.created_at
            """,
            (
                story_id,
                "closure_report",
                path.name,
                "closure-phase",
                report.status.upper(),
                0,
                _dump_json(payload),
                now_iso(),
            ),
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
