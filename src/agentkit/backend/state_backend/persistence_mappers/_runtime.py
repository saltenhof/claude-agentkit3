"""Pipeline-runtime, flow-execution, and skill-binding row mappers."""

from __future__ import annotations

import json
from datetime import datetime
from typing import TYPE_CHECKING, Any

from agentkit.backend.exceptions import CorruptStateError

from ._common import dump_json, load_json

if TYPE_CHECKING:
    from agentkit.backend.phase_state_store.models import FlowExecution, NodeExecutionLedger, OverrideRecord
    from agentkit.backend.pipeline_engine.phase_executor.models import PhaseSnapshot, PhaseState
    from agentkit.backend.pipeline_engine.phase_executor.records import AttemptRecord
    from agentkit.backend.skills.binding import SkillBinding



def phase_state_to_row(state: PhaseState) -> dict[str, Any]:
    """Convert a ``PhaseState`` to a DB-insertable row dict."""

    return {
        "story_id": state.story_id,
        "phase": state.phase,
        "status": state.status.value,
        "paused_reason": state.pause_reason,
        "review_round": state.review_round,
        "attempt_id": state.attempt_id,
        "errors_json": dump_json(state.errors),
        "payload_json": dump_json(state.model_dump(mode="json", by_alias=True)),
    }



def phase_state_payload_to_record(
    payload_json: str,
    db_label: str = "unknown",
) -> PhaseState:
    """Deserialize a ``PhaseState`` from its JSON payload."""

    from agentkit.backend.pipeline_engine.phase_executor import PhaseState as _PhaseState

    try:
        return _PhaseState.model_validate(json.loads(payload_json))
    except Exception as exc:  # noqa: BLE001
        raise CorruptStateError(
            f"phase_states payload is invalid in {db_label}: {exc}",
        ) from exc



def phase_snapshot_to_row(snapshot: PhaseSnapshot) -> dict[str, Any]:
    """Convert a ``PhaseSnapshot`` to a DB-insertable row dict."""

    return {
        "story_id": snapshot.story_id,
        "phase": snapshot.phase,
        "status": snapshot.status.value,
        "completed_at": snapshot.completed_at.isoformat(),
        "payload_json": dump_json(snapshot.model_dump(mode="json")),
    }



def phase_snapshot_payload_to_record(
    payload_json: str,
    phase: str,
    db_label: str = "unknown",
) -> PhaseSnapshot:
    """Deserialize a ``PhaseSnapshot`` from its JSON payload."""

    from agentkit.backend.pipeline_engine.phase_executor import PhaseSnapshot as _PhaseSnapshot

    try:
        return _PhaseSnapshot.model_validate(json.loads(payload_json))
    except Exception as exc:  # noqa: BLE001
        raise CorruptStateError(
            f"phase_snapshots payload is invalid in {db_label} "
            f"for phase {phase!r}: {exc}",
        ) from exc



def phase_snapshot_completed(snapshot: PhaseSnapshot) -> bool:
    """Return True if the snapshot's status is COMPLETED."""

    from agentkit.backend.pipeline_engine.phase_executor import PhaseStatus as _PhaseStatus

    return snapshot.status == _PhaseStatus.COMPLETED



def attempt_record_to_row(attempt: AttemptRecord) -> dict[str, Any]:
    """Convert an ``AttemptRecord`` to a DB-insertable row dict (Schema 3.5.0).

    Maps the Pydantic model fields to the ``attempts`` table columns as
    specified in AG3-025 §2.1.1.1.  Wire values are upper-case enum strings
    (FK-39 §39.4.2/39.4.3 and AG3-021 §2.1.1.1).
    """

    from enum import StrEnum

    phase_val = attempt.phase.value if isinstance(attempt.phase, StrEnum) else str(attempt.phase)
    return {
        "run_id": attempt.run_id,
        "phase": phase_val,
        "attempt": attempt.attempt,
        "outcome": attempt.outcome.value,
        "failure_cause": attempt.failure_cause.value if attempt.failure_cause is not None else None,
        "started_at": attempt.started_at.isoformat(),
        "ended_at": attempt.ended_at.isoformat(),
        "detail_json": attempt.detail_json(),
    }



def attempt_row_to_record(row: dict[str, Any]) -> AttemptRecord:
    """Convert a DB row dict from ``attempts`` table to an ``AttemptRecord``.

    Fail-closed: invalid rows (failure_cause_consistency violation, etc.)
    raise ``pydantic.ValidationError`` which propagates to the caller.

    Handles both backend representations of the date/JSON fields:
    - SQLite returns TEXT columns as ``str`` (ISO format / JSON literal)
    - Postgres returns ``TIMESTAMPTZ`` directly as ``datetime`` and
      ``JSONB`` directly as ``dict`` (psycopg dict_row auto-decode).
    """

    from datetime import datetime

    from agentkit.backend.core_types.attempt import AttemptOutcome as _AttemptOutcome
    from agentkit.backend.core_types.attempt import FailureCause as _FailureCause
    from agentkit.backend.pipeline_engine.phase_executor import PhaseName as _PhaseName
    from agentkit.backend.pipeline_engine.phase_executor.records import (
        AttemptRecord as _AttemptRecord,
    )

    started_raw = row["started_at"]
    ended_raw = row["ended_at"]
    started_at = (
        started_raw if isinstance(started_raw, datetime)
        else datetime.fromisoformat(str(started_raw))
    )
    ended_at = (
        ended_raw if isinstance(ended_raw, datetime)
        else datetime.fromisoformat(str(ended_raw))
    )

    detail_raw = row.get("detail_json")
    detail: dict[str, Any] | None
    if detail_raw is None:
        detail = None
    elif isinstance(detail_raw, dict):
        detail = detail_raw
    else:
        detail = load_json(str(detail_raw), None)

    failure_cause_raw = row.get("failure_cause")
    return _AttemptRecord(
        run_id=str(row["run_id"]),
        phase=_PhaseName(str(row["phase"])),
        attempt=int(row["attempt"]),
        outcome=_AttemptOutcome(str(row["outcome"])),
        failure_cause=(
            _FailureCause(str(failure_cause_raw))
            if failure_cause_raw is not None
            else None
        ),
        started_at=started_at,
        ended_at=ended_at,
        detail=detail,
    )



def skill_binding_to_row(binding: SkillBinding) -> dict[str, Any]:
    """Convert a ``SkillBinding`` to a DB-insertable row dict.

    ``target_path`` (``pathlib.Path``) is stored as TEXT; enums are persisted
    by their ``.value``. ``pinned_at`` is serialized tz-aware via ``isoformat``
    (FK-18 datetime pattern, analog ``attempt_record_to_row``).

    Args:
        binding: The ``SkillBinding`` to serialize.

    Returns:
        Row dict keyed by ``skill_bindings`` column names.
    """

    return {
        "binding_id": binding.binding_id,
        "project_key": binding.project_key,
        "skill_name": binding.skill_name,
        "bundle_id": binding.bundle_id,
        "bundle_version": binding.bundle_version,
        "target_path": str(binding.target_path),
        "binding_mode": binding.binding_mode.value,
        "status": binding.status.value,
        "pinned_at": binding.pinned_at.isoformat(),
    }



def skill_binding_row_to_record(row: dict[str, Any]) -> SkillBinding:
    """Convert a ``skill_bindings`` DB row dict to a ``SkillBinding``.

    Fail-closed: malformed rows (unknown enum value, missing column, invalid
    timestamp) raise ``pydantic.ValidationError`` / ``ValueError`` which
    propagates to the caller (NO ERROR BYPASSING).

    Handles both backend representations of the ``pinned_at`` column:
    SQLite returns TEXT (ISO string); Postgres returns ``TIMESTAMPTZ`` as a
    tz-aware ``datetime`` (psycopg dict_row auto-decode).

    Datetime handling mirrors ``attempt_row_to_record`` (FK-18 pattern):
    the parsed value is returned EXACTLY as stored — aware datetimes keep
    their original offset and tzinfo (no silent ``.astimezone(UTC)``
    coercion, which would mutate the serialized shape of a non-UTC offset
    such as ``+02:00``). A naive value (no tzinfo) is rejected fail-closed:
    the ``skill_bindings.pinned_at`` column is ``TIMESTAMPTZ NOT NULL`` and
    ``Skills.bind_skill`` always writes an aware UTC timestamp, so a naive
    value signals a corrupt/foreign write and must not be silently repaired
    (FAIL-CLOSED, NO ERROR BYPASSING).

    Args:
        row: A ``skill_bindings`` row dict.

    Returns:
        The reconstructed ``SkillBinding``.

    Raises:
        ValueError: When ``pinned_at`` parses to a naive (tz-unaware)
            datetime.
    """

    from datetime import datetime
    from pathlib import Path

    from agentkit.backend.skills.binding import (
        SkillBinding as _SkillBinding,
    )
    from agentkit.backend.skills.binding import (
        SkillBindingMode as _SkillBindingMode,
    )
    from agentkit.backend.skills.binding import (
        SkillLifecycleStatus as _SkillLifecycleStatus,
    )

    pinned_raw = row["pinned_at"]
    pinned_at = (
        pinned_raw
        if isinstance(pinned_raw, datetime)
        else datetime.fromisoformat(str(pinned_raw))
    )
    if pinned_at.tzinfo is None:
        msg = (
            "skill_bindings.pinned_at is tz-naive; expected an aware "
            "TIMESTAMPTZ value (fail-closed, FK-18)"
        )
        raise ValueError(msg)

    return _SkillBinding(
        binding_id=str(row["binding_id"]),
        project_key=str(row["project_key"]),
        skill_name=str(row["skill_name"]),
        bundle_id=str(row["bundle_id"]),
        bundle_version=str(row["bundle_version"]),
        target_path=Path(str(row["target_path"])),
        binding_mode=_SkillBindingMode(str(row["binding_mode"])),
        status=_SkillLifecycleStatus(str(row["status"])),
        pinned_at=pinned_at,
    )



def flow_execution_to_row(record: FlowExecution) -> dict[str, Any]:
    """Convert a ``FlowExecution`` to a DB-insertable row dict."""
    return {
        "story_id": record.story_id,
        "project_key": record.project_key,
        "run_id": record.run_id,
        "flow_id": record.flow_id,
        "level": record.level,
        "owner": record.owner,
        "parent_flow_id": record.parent_flow_id,
        "status": record.status,
        "current_node_id": record.current_node_id,
        "attempt_no": record.attempt_no,
        "started_at": record.started_at.isoformat(),
        "finished_at": record.finished_at.isoformat() if record.finished_at else None,
    }



def flow_execution_row_to_record(row: dict[str, Any]) -> FlowExecution:
    """Convert a DB row dict to a ``FlowExecution``."""
    from agentkit.backend.phase_state_store.models import FlowExecution as _FlowExecution

    return _FlowExecution(
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



def node_ledger_to_row(record: NodeExecutionLedger) -> dict[str, Any]:
    """Convert a ``NodeExecutionLedger`` to a DB-insertable row dict."""

    return {
        "story_id": record.story_id,
        "flow_id": record.flow_id,
        "node_id": record.node_id,
        "project_key": record.project_key,
        "run_id": record.run_id,
        "execution_count": record.execution_count,
        "success_count": record.success_count,
        "last_outcome": record.last_outcome,
        "last_attempt_no": record.last_attempt_no,
        "last_executed_at": (
            record.last_executed_at.isoformat()
            if record.last_executed_at is not None
            else None
        ),
    }



def node_ledger_row_to_record(row: dict[str, Any]) -> NodeExecutionLedger:
    """Convert a DB row dict to a ``NodeExecutionLedger``."""

    from datetime import datetime

    from agentkit.backend.phase_state_store.models import (
        NodeExecutionLedger as _NodeExecutionLedger,
    )

    return _NodeExecutionLedger(
        project_key=str(row["project_key"]),
        story_id=str(row["story_id"]),
        run_id=str(row["run_id"]),
        flow_id=str(row["flow_id"]),
        node_id=str(row["node_id"]),
        execution_count=int(row["execution_count"]),
        success_count=int(row["success_count"]),
        last_outcome=str(row["last_outcome"]) if row["last_outcome"] else None,
        last_attempt_no=(
            int(row["last_attempt_no"])
            if row["last_attempt_no"] is not None
            else None
        ),
        last_executed_at=(
            datetime.fromisoformat(str(row["last_executed_at"]))
            if row["last_executed_at"] is not None
            else None
        ),
    )



def override_record_to_row(record: OverrideRecord) -> dict[str, Any]:
    """Convert an ``OverrideRecord`` to a DB-insertable row dict."""

    return {
        "override_id": record.override_id,
        "story_id": record.story_id,
        "project_key": record.project_key,
        "run_id": record.run_id,
        "flow_id": record.flow_id,
        "target_node_id": record.target_node_id,
        "override_type": record.override_type.value,
        "actor_type": record.actor_type,
        "actor_id": record.actor_id,
        "reason": record.reason,
        "created_at": record.created_at.isoformat(),
        "consumed_at": record.consumed_at.isoformat() if record.consumed_at else None,
        # AG3-108: override->check correlation (FK-69 §69.11 rule 3, §69.15.6 rule 5).
        "check_id": record.check_id,
    }



def override_row_to_record(row: dict[str, Any]) -> OverrideRecord:
    """Convert a DB row dict to an ``OverrideRecord``."""

    from datetime import datetime

    from agentkit.backend.core_types.override import OverrideType
    from agentkit.backend.phase_state_store.models import OverrideRecord as _OverrideRecord

    raw_override_type = str(row["override_type"])
    try:
        override_type = OverrideType(raw_override_type)
    except ValueError as exc:
        raise CorruptStateError(
            f"override_records.override_type has unknown value "
            f"{raw_override_type!r}; fail-closed",
            detail={"override_type": raw_override_type},
        ) from exc

    return _OverrideRecord(
        override_id=str(row["override_id"]),
        project_key=str(row["project_key"]),
        story_id=str(row["story_id"]),
        run_id=str(row["run_id"]),
        flow_id=str(row["flow_id"]),
        target_node_id=(
            str(row["target_node_id"]) if row["target_node_id"] is not None else None
        ),
        override_type=override_type,
        actor_type=str(row["actor_type"]),
        actor_id=str(row["actor_id"]),
        reason=str(row["reason"]),
        created_at=datetime.fromisoformat(str(row["created_at"])),
        consumed_at=(
            datetime.fromisoformat(str(row["consumed_at"]))
            if row["consumed_at"] is not None
            else None
        ),
        # AG3-108: override->check correlation (FK-69 §69.11 rule 3, §69.15.6
        # rule 5). Legacy rows without the column return None (nullable).
        check_id=str(row["check_id"]) if row.get("check_id") is not None else None,
    )
