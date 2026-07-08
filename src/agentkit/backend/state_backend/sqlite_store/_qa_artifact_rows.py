"""SQLite QA artifact, verify-decision, and closure-report persistence."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any, cast

from agentkit.backend.boundary.shared.time import now_iso
from agentkit.backend.core_types import ArtifactClass
from agentkit.backend.core_types.qa_artifact_names import VERIFY_DECISION_FILE
from agentkit.backend.exceptions import CorruptStateError
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
    attempt_nr: int,
    owner_session_id: str,
    expected_ownership_epoch: int,
    projection_dir: Path | None = None,
) -> tuple[str, ...]:
    """Persist QA layer artifact rows and write projection files.

    ``layer_payload_rows`` contains pre-serialized dicts from the mapper layer.
    Each element has keys: ``layer``, ``artifact_name``, ``producer_component``,
    ``payload``, ``passed``, ``recorded_at``.
    ``flow_row`` and FK-69 fields (``stage_row``, ``finding_rows``) are
    ignored on SQLite (FK-69 read models are Postgres-only).
    artifact_records removed in 3.4.0 — projection file is the only SQLite output.

    AG3-144 (K5 Postgres-only): the narrow SQLite unit-test path receives BUT
    does not mirror the AG3-142 ownership-lease fence -- explicit, not a
    silent skip (the fence lives only in ``postgres_store.py``).
    """
    del flow_row
    del attempt_nr
    del owner_session_id
    del expected_ownership_epoch
    story_id = _story_id_for(story_dir)
    if story_id is None:
        raise CorruptStateError(
            "Cannot persist QA layer artifacts without story context in canonical backend",
        )
    produced: list[str] = []
    for item in layer_payload_rows:
        artifact_name = str(item["artifact_name"])
        payload = cast("_JsonRecord", item["payload"])
        target_dir = projection_dir or story_dir
        _write_projection(target_dir / artifact_name, payload)
        produced.append(artifact_name)
    return tuple(produced)


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
