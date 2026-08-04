"""SQLite QA artifact, verify-decision, and closure-report persistence."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any, cast

from agentkit.backend.boundary.shared.time import now_iso
from agentkit.backend.core_types import ArtifactClass
from agentkit.backend.core_types.qa_artifact_names import VERIFY_DECISION_FILE
from agentkit.backend.exceptions import CorruptStateError
from agentkit.backend.state_backend._qa_batch_validation import (
    validate_qa_layer_batch_rows,
)
from agentkit.backend.state_backend.paths import CLOSURE_REPORT_FILE

from ._common import _cast_json_record, _dump_json, _JsonRecord, _write_projection, state_db_path_for
from ._connection import _connect
from ._story_identity import _story_id_for

if TYPE_CHECKING:
    from pathlib import Path

    from agentkit.backend.state_backend.scope import RuntimeStateScope


def persist_layer_artifact_rows(
    story_dir: Path,
    *,
    flow_row: dict[str, Any] | None,
    layer_payload_rows: list[dict[str, object]],
    check_outcome_rows: list[dict[str, object]],
    attempt_nr: int,
    owner_session_id: str,
    expected_ownership_epoch: int,
    projection_dir: Path | None = None,
) -> tuple[str, ...]:
    """Persist QA layer artifact rows and write projection files.

    ``layer_payload_rows`` contains pre-serialized dicts from the mapper layer.
    Each element has keys: ``layer``, ``artifact_name``, ``producer_component``,
    ``payload``, ``passed``, ``recorded_at``.
    ``flow_row`` and FK-69 fields (``stage_row``, ``finding_rows``) use the
    same productive batch contract as Postgres. File materialization is
    optional per registered result and does not control QA-row projection.

    AG3-144 (K5 Postgres-only): the narrow SQLite unit-test path receives BUT
    does not mirror the AG3-142 ownership-lease fence -- explicit, not a
    silent skip (the fence lives only in ``postgres_store.py``).
    """
    del owner_session_id
    del expected_ownership_epoch
    story_id = _story_id_for(story_dir)
    if story_id is None:
        raise CorruptStateError(
            "Cannot persist QA layer artifacts without story context in canonical backend",
        )
    if flow_row is None:
        raise CorruptStateError(
            "Cannot materialize FK-69 QA read models without flow execution scope in canonical SQLite backend",
        )
    validate_qa_layer_batch_rows(
        flow_row=flow_row,
        canonical_story_id=story_id,
        layer_payload_rows=layer_payload_rows,
        check_outcome_rows=check_outcome_rows,
        attempt_nr=attempt_nr,
    )
    produced: list[str] = []
    with _connect(story_dir) as conn:
        for item in layer_payload_rows:
            reference = cast("dict[str, object]", item["artifact_reference"])
            artifact_attempt = item["artifact_attempt"]
            if not isinstance(artifact_attempt, int):
                raise CorruptStateError("QA projection artifact attempt must be an integer")
            row = conn.execute(
                """
                SELECT COUNT(*) AS envelope_count
                FROM artifact_envelopes
                WHERE story_id = :story_id
                  AND run_id = :run_id
                  AND artifact_class = :artifact_class
                  AND producer_name = :producer_name
                  AND attempt = :artifact_attempt
                  AND (
                    story_id || '|' || run_id || '|' || stage || '|' ||
                    CAST(attempt AS TEXT) || '|' || artifact_class || '|' ||
                    producer_name
                  ) = :record_key
                """,
                {
                    **reference,
                    "producer_name": str(item["producer_component"]),
                    "artifact_attempt": artifact_attempt,
                },
            ).fetchone()
            if row is None or int(row["envelope_count"]) != 1:
                raise CorruptStateError(
                    f"Cannot persist FK-69 QA projections without the exact canonical artifact envelope: {reference!r}"
                )
        snapshot_scope = (
            str(flow_row["project_key"]),
            str(flow_row["run_id"]),
            attempt_nr,
        )
        conn.execute(
            "DELETE FROM qa_check_outcomes WHERE project_key = ? AND run_id = ? AND attempt_no = ?",
            snapshot_scope,
        )
        conn.execute(
            "DELETE FROM qa_findings WHERE project_key = ? AND run_id = ? AND attempt_no = ?",
            snapshot_scope,
        )
        conn.execute(
            "DELETE FROM qa_stage_results WHERE project_key = ? AND run_id = ? AND attempt_no = ?",
            snapshot_scope,
        )
        for item in layer_payload_rows:
            layer = str(item["layer"])
            artifact_name = item.get("artifact_name")
            if artifact_name is not None:
                payload = cast("_JsonRecord", item["payload"])
                target_dir = projection_dir or story_dir
                _write_projection(target_dir / str(artifact_name), payload)
                produced.append(str(artifact_name))
            stage_row = cast("dict[str, object] | None", item.get("stage_row"))
            if stage_row is None:
                raise CorruptStateError(
                    f"Cannot materialize FK-69 QA read models for result {layer!r} without a stage projection",
                )
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
                stage_row,
            )
            finding_rows = cast("list[dict[str, object]]", item.get("finding_rows") or [])
            for finding_row in finding_rows:
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
                    finding_row,
                )
        for row in check_outcome_rows:
            conn.execute(
                """
                INSERT OR REPLACE INTO qa_check_outcomes (
                    project_key, story_id, run_id, stage_id, attempt_no,
                    check_id, outcome, occurred_at, check_proposal_ref,
                    override_id
                ) VALUES (
                    :project_key, :story_id, :run_id, :stage_id, :attempt_no,
                    :check_id, :outcome, :occurred_at, :check_proposal_ref,
                    :override_id
                )
                """,
                row,
            )
    return tuple(produced)


def purge_qa_projection_rows(
    story_dir: Path,
    *,
    project_key: str,
    story_id: str,
    run_id: str,
) -> dict[str, int]:
    """Purge all QA projection families atomically for one run."""
    counts: dict[str, int] = {}
    with _connect(story_dir) as conn:
        params = (project_key, story_id, run_id)
        counts["qa_check_outcomes"] = int(
            conn.execute(
                "DELETE FROM qa_check_outcomes WHERE project_key=? AND story_id=? AND run_id=?",
                params,
            ).rowcount
        )
        counts["qa_findings"] = int(
            conn.execute(
                "DELETE FROM qa_findings WHERE project_key=? AND story_id=? AND run_id=?",
                params,
            ).rowcount
        )
        counts["qa_stage_results"] = int(
            conn.execute(
                "DELETE FROM qa_stage_results WHERE project_key=? AND story_id=? AND run_id=?",
                params,
            ).rowcount
        )
    return counts


def persist_verify_decision_row(
    story_dir: Path,
    *,
    flow_row: dict[str, Any] | None,
    decision_row: dict[str, Any],
    canonical_payload: dict[str, object],
    attempt_nr: int,
    owner_session_id: str,
    expected_ownership_epoch: int,
    projection_dir: Path | None = None,
) -> tuple[str, ...]:
    """Persist a verify-decision row and write the projection file.

    AG3-144 (K5 Postgres-only): the narrow SQLite unit-test path receives BUT
    does not mirror the AG3-142 ownership-lease fence -- explicit, not a
    silent skip (the fence lives only in ``postgres_store.py``).
    """

    del flow_row
    del owner_session_id
    del expected_ownership_epoch
    story_id = _story_id_for(story_dir)
    if story_id is None:
        raise CorruptStateError(
            "Cannot persist verify decision without story context in canonical backend",
        )
    target_dir = projection_dir or story_dir
    _write_projection(target_dir / VERIFY_DECISION_FILE, canonical_payload)
    written = (VERIFY_DECISION_FILE,)
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
                decision_row["status"],
                1 if decision_row["passed"] else 0,
                decision_row["summary"],
                _dump_json(canonical_payload),
                now_iso(),
            ),
        )
    return written


def load_latest_verify_decision_payload(
    story_dir: Path,
) -> dict[str, object] | None:
    """Return the latest verify-decision payload dict, or None."""

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
        return _cast_json_record(json.loads(str(row["payload_json"])))
    except json.JSONDecodeError as exc:
        raise CorruptStateError(
            f"decision_records payload is invalid in {state_db_path_for(story_dir)}: {exc}",
        ) from exc


def load_latest_verify_decision_payload_for_scope(
    scope: RuntimeStateScope,
) -> dict[str, object] | None:
    """Return the latest verify-decision payload for a scope, or None."""

    return load_latest_verify_decision_payload(scope.story_dir)


def load_artifact_record_payload(
    story_dir: Path,
    artifact_kind: str,
) -> dict[str, object] | None:
    """Return the latest QA artifact payload from artifact_envelopes for a kind.

    Maps artifact_kind ("structural"/"semantic"/"adversarial") to stage
    "qa-layer-{kind}" and reads from artifact_envelopes (AG3-023 3.4.0).
    """
    story_id = _story_id_for(story_dir)
    if story_id is None:
        return None
    stage = f"qa-layer-{artifact_kind}"
    with _connect(story_dir) as conn:
        row = conn.execute(
            """
            SELECT payload_json
            FROM artifact_envelopes
            WHERE story_id = ? AND stage = ?
            ORDER BY attempt DESC
            LIMIT 1
            """,
            (story_id, stage),
        ).fetchone()
    if row is None:
        return None
    raw = row["payload_json"]
    if raw is None:
        return None
    try:
        return _cast_json_record(json.loads(str(raw)))
    except json.JSONDecodeError as exc:
        raise CorruptStateError(
            f"artifact_envelopes payload is invalid in {state_db_path_for(story_dir)}: {exc}",
        ) from exc


def load_artifact_record_payload_for_scope(
    scope: RuntimeStateScope,
    artifact_kind: str,
) -> dict[str, object] | None:
    """Return the latest artifact payload dict for a scope and kind, or None."""

    return load_artifact_record_payload(scope.story_dir, artifact_kind)


def find_latest_artifact_envelope_row(
    story_dir: Path,
    *,
    story_id: str,
    run_id: str | None,
    artifact_class: ArtifactClass,
    stage: str,
) -> dict[str, Any] | None:
    """Return the highest-attempt artifact_envelopes row for a scope."""
    with _connect(story_dir) as conn:
        if run_id is None:
            row = conn.execute(
                """
                SELECT * FROM artifact_envelopes
                WHERE story_id = ? AND stage = ? AND artifact_class = ?
                ORDER BY attempt DESC
                LIMIT 1
                """,
                (story_id, stage, artifact_class.value),
            ).fetchone()
        else:
            row = conn.execute(
                """
                SELECT * FROM artifact_envelopes
                WHERE story_id = ? AND run_id = ? AND stage = ?
                  AND artifact_class = ?
                ORDER BY attempt DESC
                LIMIT 1
                """,
                (story_id, run_id, stage, artifact_class.value),
            ).fetchone()
    if row is None:
        return None
    return dict(row)


def load_prompt_audit_payload_rows(
    story_dir: Path,
    story_id: str,
    run_id: str,
) -> list[object]:
    """Return prompt-audit envelope payload values for one story/run scope."""
    with _connect(story_dir) as conn:
        rows = conn.execute(
            """
            SELECT payload_json FROM artifact_envelopes
            WHERE story_id = ? AND run_id = ? AND artifact_class = ?
            """,
            (story_id, run_id, ArtifactClass.PROMPT_AUDIT.value),
        ).fetchall()
    return [row["payload_json"] for row in rows]


def persist_closure_report_row(
    story_dir: Path,
    *,
    flow_row: dict[str, Any] | None,
    report_row: dict[str, Any],
    owner_session_id: str,
    expected_ownership_epoch: int,
    projection_dir: Path | None = None,
) -> Path:
    """Persist a closure-report and write the projection file.

    AG3-144 (K5 Postgres-only): the narrow SQLite unit-test path receives BUT
    does not mirror the AG3-142 ownership-lease fence -- explicit, not a
    silent skip (the fence lives only in ``postgres_store.py``).
    """

    del flow_row
    del owner_session_id
    del expected_ownership_epoch
    target_dir = projection_dir or story_dir
    path = target_dir / CLOSURE_REPORT_FILE
    payload = cast("_JsonRecord", report_row["payload"])
    _write_projection(path, payload)
    return path


# ---------------------------------------------------------------------------
# QA read models (SQLite: Postgres-only, raise RuntimeError)
# ---------------------------------------------------------------------------


def load_qa_stage_result_rows(
    story_dir: Path,
    *,
    project_key: str | None = None,
    story_id: str | None = None,
    run_id: str | None = None,
    attempt_no: int | None = None,
    stage_id: str | None = None,
) -> list[dict[str, Any]]:
    """FK-69 QA read models are only materialized on the Postgres backend."""

    del story_dir, project_key, story_id, run_id, attempt_no, stage_id
    raise RuntimeError(
        "FK-69 QA read models are only materialized on the Postgres backend. SQLite remains a narrow unit-test backend.",
    )


def load_qa_finding_rows(
    story_dir: Path,
    *,
    project_key: str | None = None,
    story_id: str | None = None,
    run_id: str | None = None,
    attempt_no: int | None = None,
    stage_id: str | None = None,
) -> list[dict[str, Any]]:
    """FK-69 QA read models are only materialized on the Postgres backend."""

    del story_dir, project_key, story_id, run_id, attempt_no, stage_id
    raise RuntimeError(
        "FK-69 QA read models are only materialized on the Postgres backend. SQLite remains a narrow unit-test backend.",
    )
