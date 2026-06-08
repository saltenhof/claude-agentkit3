"""BC-Record <-> dict-row mapper layer for state_backend drivers.

All conversions between typed BC-Records and raw dict rows live here.
Drivers (postgres_store, sqlite_store) receive and return only dicts;
this module is the single point of contact between BC types and the
persistence layer.

Projection helpers that previously lived in BC-A modules (qa.policy_engine.projections,
verify_system.qa_read_models) are also orchestrated here so that drivers
do not need to import BC-A modules directly.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import TYPE_CHECKING, Any

from agentkit.exceptions import CorruptStateError

_log = logging.getLogger(__name__)

if TYPE_CHECKING:
    from agentkit.auth.entities import ProjectApiToken
    from agentkit.closure.post_merge_finalization.records import StoryMetricsRecord
    from agentkit.control_plane.records import (
        ControlPlaneOperationRecord,
        SessionRunBindingRecord,
    )
    from agentkit.execution_planning.entities import (
        ParallelizationConfig,
        StoryDependency,
    )
    from agentkit.governance.guard_system.records import StoryExecutionLockRecord
    from agentkit.phase_state_store.models import (
        FlowExecution,
        NodeExecutionLedger,
        OverrideRecord,
    )
    from agentkit.pipeline_engine.phase_executor.models import (
        PhaseSnapshot,
        PhaseState,
    )
    from agentkit.pipeline_engine.phase_executor.records import AttemptRecord
    from agentkit.project_management.entities import Project
    from agentkit.requirements_coverage.models import StoryAreLink
    from agentkit.skills.binding import SkillBinding
    from agentkit.story_context_manager.models import StoryContext
    from agentkit.telemetry.contract.records import ExecutionEventRecord
    from agentkit.verify_system.policy_engine.engine import VerifyDecision
    from agentkit.verify_system.protocols import LayerResult
    from agentkit.verify_system.stage_registry.records import (
        QAFindingRecord,
        QAStageResultRecord,
    )

_JsonRecord = dict[str, object]
_OptionalString = str | None

# ---------------------------------------------------------------------------
# JSON helpers
# ---------------------------------------------------------------------------


def dump_json(data: object) -> str:
    """Serialize data to a canonical JSON string."""

    return json.dumps(data, sort_keys=True, default=str)


def load_json(data: str | None, default: Any) -> Any:
    """Deserialize a JSON string, returning *default* if *data* is None."""

    if data is None:
        return default
    return json.loads(data)


def cast_json_record(value: object) -> _JsonRecord:
    """Cast an opaque value to ``dict[str, object]`` without allocation."""

    from typing import cast

    return cast("_JsonRecord", value)


# ---------------------------------------------------------------------------
# Project
# ---------------------------------------------------------------------------


def project_to_row(project: Project) -> dict[str, Any]:
    """Convert a project entity to a DB-insertable row dict."""

    return {
        "key": project.key,
        "name": project.name,
        "story_id_prefix": project.story_id_prefix,
        "configuration_json": dump_json(project.configuration.model_dump(mode="json")),
        "archived_at": (
            project.archived_at.isoformat() if project.archived_at is not None else None
        ),
    }


def _backfill_legacy_project_configuration_payload(
    payload: dict[str, Any],
    *,
    project_key: str,
) -> dict[str, Any]:
    """Forward-compat: derive ``repositories`` for legacy/empty DB rows.

    The strict ``ProjectConfiguration`` schema requires ``repositories`` with
    at least one entry.  Two read-side cases must be handled here at the
    boundary so the schema can stay strict on writes:

    - ``repositories`` key absent      (legacy row pre-AG3-020)
    - ``repositories`` present but ``[]`` (legacy bootstrap fallback)

    Both trigger the same conservative fallback:

    - ``repo_url`` set and non-empty -> ``repositories = [repo_url]``
    - else                            -> ``repositories = [project_key]``
      (the project_key is guaranteed to exist; operator MUST replace it).

    A WARNING is logged for every legacy row encountered so the operator
    can correct the project record explicitly.

    Args:
        payload: Raw configuration dict as it came out of the JSON column.
        project_key: The project key this payload belongs to (for log context
            and last-resort fallback).

    Returns:
        A new dict with ``repositories`` populated, or the original dict
        unchanged when ``repositories`` was already present and non-empty.
    """

    existing = payload.get("repositories")
    if isinstance(existing, list) and existing:
        # Already populated, schema-acceptable — pass through unchanged.
        return payload
    repo_url = payload.get("repo_url", "")
    if isinstance(repo_url, str) and repo_url.strip():
        _log.warning(
            "Legacy project configuration for %r without usable 'repositories'; "
            "deriving [%r] from repo_url. Update the project record.",
            project_key,
            repo_url,
        )
        return {**payload, "repositories": [repo_url]}
    _log.warning(
        "Legacy project configuration for %r without usable 'repositories' and "
        "without a usable repo_url; falling back to [%r]. Operator MUST replace.",
        project_key,
        project_key,
    )
    return {**payload, "repositories": [project_key]}


def project_row_to_entity(row: dict[str, Any]) -> Project:
    """Convert a project DB row dict to a project entity."""

    from agentkit.project_management.entities import (
        Project as _Project,
    )
    from agentkit.project_management.entities import (
        ProjectConfiguration as _ProjectConfiguration,
    )

    configuration_raw = row.get("configuration_json", row.get("configuration"))
    configuration_payload = (
        json.loads(configuration_raw)
        if isinstance(configuration_raw, str)
        else configuration_raw
    )
    if not isinstance(configuration_payload, dict):
        raise CorruptStateError(
            f"project configuration for {row.get('key')!r} is not a dict; "
            f"got {type(configuration_payload).__name__}",
        )

    configuration_payload = _backfill_legacy_project_configuration_payload(
        configuration_payload,
        project_key=str(row["key"]),
    )

    archived_at_raw = row.get("archived_at")
    archived_at = (
        datetime.fromisoformat(archived_at_raw)
        if isinstance(archived_at_raw, str)
        else archived_at_raw
    )

    return _Project(
        key=str(row["key"]),
        name=str(row["name"]),
        story_id_prefix=str(row["story_id_prefix"]),
        configuration=_ProjectConfiguration.model_validate(configuration_payload),
        archived_at=archived_at,
    )


# ---------------------------------------------------------------------------
# Project API tokens
# ---------------------------------------------------------------------------


def project_api_token_to_row(token: ProjectApiToken) -> dict[str, Any]:
    """Convert a project API token to a DB row."""

    return {
        "token_id": token.token_id,
        "project_key": token.project_key,
        "label": token.label,
        "token_hash": token.token_hash,
        "created_at": token.created_at.isoformat(),
        "revoked_at": (
            token.revoked_at.isoformat() if token.revoked_at is not None else None
        ),
        "last_used_at": (
            token.last_used_at.isoformat() if token.last_used_at is not None else None
        ),
    }


def project_api_token_row_to_entity(row: dict[str, Any]) -> ProjectApiToken:
    """Convert a DB row to a project API token."""

    from agentkit.auth.entities import ProjectApiToken as _ProjectApiToken

    def _datetime_from_row(key: str) -> datetime | None:
        value = row.get(key)
        if value is None:
            return None
        if isinstance(value, datetime):
            return value
        return datetime.fromisoformat(str(value))

    created_at = _datetime_from_row("created_at")
    if created_at is None:
        raise CorruptStateError("project_api_tokens.created_at is required")
    return _ProjectApiToken(
        token_id=str(row["token_id"]),
        project_key=str(row["project_key"]),
        label=str(row["label"]),
        token_hash=str(row["token_hash"]),
        created_at=created_at,
        revoked_at=_datetime_from_row("revoked_at"),
        last_used_at=_datetime_from_row("last_used_at"),
    )


# ---------------------------------------------------------------------------
# StoryContext
# ---------------------------------------------------------------------------


def story_context_to_row(ctx: StoryContext) -> dict[str, Any]:
    """Convert a ``StoryContext`` to a DB-insertable row dict."""

    return {
        "story_uuid": str(ctx.story_uuid),
        "project_key": ctx.project_key,
        "story_number": ctx.story_number,
        "story_id": ctx.story_id,
        "story_type": ctx.story_type.value,
        "execution_route": (
            ctx.execution_route.value
            if ctx.execution_route is not None
            else None
        ),
        "implementation_contract": (
            ctx.implementation_contract.value
            if ctx.implementation_contract is not None
            else None
        ),
        "issue_nr": ctx.issue_nr,
        "title": ctx.title,
        "payload_json": dump_json(ctx.model_dump(mode="json")),
    }


def story_context_payload_to_record(
    payload_json: str,
    db_label: str = "unknown",
) -> StoryContext:
    """Deserialize a ``StoryContext`` from its JSON payload."""

    from agentkit.story_context_manager.models import StoryContext as _StoryContext

    try:
        return _StoryContext.model_validate(json.loads(payload_json))
    except Exception as exc:  # noqa: BLE001
        raise CorruptStateError(
            f"story_contexts payload is invalid in {db_label}: {exc}",
        ) from exc


# ---------------------------------------------------------------------------
# Execution planning
# ---------------------------------------------------------------------------


def story_dependency_to_row(
    edge: StoryDependency,
    *,
    project_key: str,
) -> dict[str, Any]:
    """Convert a story dependency edge to a DB row."""

    return {
        "project_key": project_key,
        "story_id": edge.story_id,
        "depends_on_story_id": edge.depends_on_story_id,
        "kind": edge.kind.value,
        "created_at": edge.created_at.isoformat(),
    }


def story_dependency_row_to_entity(row: dict[str, Any]) -> StoryDependency:
    """Convert a DB row to a story dependency edge."""

    from agentkit.execution_planning.entities import (
        StoryDependency as _StoryDependency,
    )
    from agentkit.execution_planning.entities import (
        StoryDependencyKind as _StoryDependencyKind,
    )

    created_at_raw = row["created_at"]
    created_at = (
        datetime.fromisoformat(created_at_raw)
        if isinstance(created_at_raw, str)
        else created_at_raw
    )
    return _StoryDependency(
        story_id=str(row["story_id"]),
        depends_on_story_id=str(row["depends_on_story_id"]),
        kind=_StoryDependencyKind(str(row["kind"])),
        created_at=created_at,
    )


def parallelization_config_to_row(config: ParallelizationConfig) -> dict[str, Any]:
    """Convert a parallelization config to a DB row."""

    return {
        "project_key": config.project_key,
        "max_parallel_stories": config.max_parallel_stories,
        "max_parallel_stories_per_repo": config.max_parallel_stories_per_repo,
        "extra_config_json": dump_json({}),
    }


def parallelization_config_row_to_entity(
    row: dict[str, Any],
) -> ParallelizationConfig:
    """Convert a DB row to a parallelization config."""

    from agentkit.execution_planning.entities import (
        ParallelizationConfig as _ParallelizationConfig,
    )

    max_parallel_stories_per_repo = row.get("max_parallel_stories_per_repo")
    return _ParallelizationConfig(
        project_key=str(row["project_key"]),
        max_parallel_stories=int(row["max_parallel_stories"]),
        max_parallel_stories_per_repo=(
            int(max_parallel_stories_per_repo)
            if max_parallel_stories_per_repo is not None
            else None
        ),
    )


# ---------------------------------------------------------------------------
# Requirements coverage
# ---------------------------------------------------------------------------


def story_are_link_to_row(link: StoryAreLink) -> dict[str, Any]:
    """Convert a StoryAreLink edge to a DB row."""

    return {
        "story_id": link.story_id,
        "are_item_id": link.are_item_id,
        "kind": link.kind.value,
    }


def story_are_link_row_to_entity(row: dict[str, Any]) -> StoryAreLink:
    """Convert a DB row to a StoryAreLink edge."""

    from agentkit.requirements_coverage.models import (
        StoryAreLink as _StoryAreLink,
    )
    from agentkit.requirements_coverage.models import (
        StoryAreLinkKind as _StoryAreLinkKind,
    )

    return _StoryAreLink(
        story_id=str(row["story_id"]),
        are_item_id=str(row["are_item_id"]),
        kind=_StoryAreLinkKind(str(row["kind"])),
    )


# ---------------------------------------------------------------------------
# PhaseState
# ---------------------------------------------------------------------------


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

    from agentkit.pipeline_engine.phase_executor import PhaseState as _PhaseState

    try:
        return _PhaseState.model_validate(json.loads(payload_json))
    except Exception as exc:  # noqa: BLE001
        raise CorruptStateError(
            f"phase_states payload is invalid in {db_label}: {exc}",
        ) from exc


# ---------------------------------------------------------------------------
# PhaseSnapshot
# ---------------------------------------------------------------------------


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

    from agentkit.pipeline_engine.phase_executor import PhaseSnapshot as _PhaseSnapshot

    try:
        return _PhaseSnapshot.model_validate(json.loads(payload_json))
    except Exception as exc:  # noqa: BLE001
        raise CorruptStateError(
            f"phase_snapshots payload is invalid in {db_label} "
            f"for phase {phase!r}: {exc}",
        ) from exc


def phase_snapshot_completed(snapshot: PhaseSnapshot) -> bool:
    """Return True if the snapshot's status is COMPLETED."""

    from agentkit.pipeline_engine.phase_executor import PhaseStatus as _PhaseStatus

    return snapshot.status == _PhaseStatus.COMPLETED


# ---------------------------------------------------------------------------
# AttemptRecord
# ---------------------------------------------------------------------------


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

    Handhabt beide Backend-Repraesentationen der Datums-/JSON-Felder:
    - SQLite liefert TEXT-Spalten als ``str`` (ISO-Format / JSON-Literal)
    - Postgres liefert ``TIMESTAMPTZ`` direkt als ``datetime`` und
      ``JSONB`` direkt als ``dict`` (psycopg dict_row auto-decode).
    """

    from datetime import datetime

    from agentkit.core_types.attempt import AttemptOutcome as _AttemptOutcome
    from agentkit.core_types.attempt import FailureCause as _FailureCause
    from agentkit.pipeline_engine.phase_executor import PhaseName as _PhaseName
    from agentkit.pipeline_engine.phase_executor.records import (
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


# ---------------------------------------------------------------------------
# SkillBinding (AG3-048, FK-43 §43.4.1, bc-cut-decisions.md §BC 11)
# ---------------------------------------------------------------------------


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

    from agentkit.skills.binding import (
        SkillBinding as _SkillBinding,
    )
    from agentkit.skills.binding import (
        SkillBindingMode as _SkillBindingMode,
    )
    from agentkit.skills.binding import (
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


# ---------------------------------------------------------------------------
# FlowExecution
# ---------------------------------------------------------------------------


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

    from datetime import datetime

    from agentkit.phase_state_store.models import FlowExecution as _FlowExecution

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


# ---------------------------------------------------------------------------
# NodeExecutionLedger
# ---------------------------------------------------------------------------


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

    from agentkit.phase_state_store.models import (
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


# ---------------------------------------------------------------------------
# OverrideRecord
# ---------------------------------------------------------------------------


def override_record_to_row(record: OverrideRecord) -> dict[str, Any]:
    """Convert an ``OverrideRecord`` to a DB-insertable row dict."""

    return {
        "override_id": record.override_id,
        "story_id": record.story_id,
        "project_key": record.project_key,
        "run_id": record.run_id,
        "flow_id": record.flow_id,
        "target_node_id": record.target_node_id,
        "override_type": record.override_type,
        "actor_type": record.actor_type,
        "actor_id": record.actor_id,
        "reason": record.reason,
        "created_at": record.created_at.isoformat(),
        "consumed_at": record.consumed_at.isoformat() if record.consumed_at else None,
    }


def override_row_to_record(row: dict[str, Any]) -> OverrideRecord:
    """Convert a DB row dict to an ``OverrideRecord``."""

    from datetime import datetime

    from agentkit.phase_state_store.models import OverrideRecord as _OverrideRecord

    return _OverrideRecord(
        override_id=str(row["override_id"]),
        project_key=str(row["project_key"]),
        story_id=str(row["story_id"]),
        run_id=str(row["run_id"]),
        flow_id=str(row["flow_id"]),
        target_node_id=(
            str(row["target_node_id"]) if row["target_node_id"] is not None else None
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


# ---------------------------------------------------------------------------
# StoryMetricsRecord
# ---------------------------------------------------------------------------


def story_metrics_to_row(metrics: StoryMetricsRecord) -> dict[str, Any]:
    """Convert a ``StoryMetricsRecord`` to a DB-insertable row dict."""

    return {
        "project_key": metrics.project_key,
        "story_id": metrics.story_id,
        "run_id": metrics.run_id,
        "story_type": metrics.story_type,
        "story_size": metrics.story_size,
        "mode": metrics.mode,
        "processing_time_min": metrics.processing_time_min,
        "qa_rounds": metrics.qa_rounds,
        "increments": metrics.increments,
        "final_status": metrics.final_status,
        "completed_at": metrics.completed_at,
        "adversarial_findings": metrics.adversarial_findings,
        "adversarial_tests_created": metrics.adversarial_tests_created,
        "files_changed": metrics.files_changed,
        "agentkit_version": metrics.agentkit_version,
        "agentkit_commit": metrics.agentkit_commit,
        "config_version": metrics.config_version,
        "llm_roles_json": dump_json(list(metrics.llm_roles)),
    }


def story_metrics_row_to_record(row: dict[str, Any]) -> StoryMetricsRecord:
    """Convert a DB row dict to a ``StoryMetricsRecord``."""

    from agentkit.closure.post_merge_finalization.records import (
        StoryMetricsRecord as _StoryMetricsRecord,
    )

    llm_roles = load_json(str(row["llm_roles_json"]), [])
    return _StoryMetricsRecord(
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
            int(row["files_changed"]) if row["files_changed"] is not None else None
        ),
        agentkit_version=(
            str(row["agentkit_version"])
            if row["agentkit_version"] is not None
            else None
        ),
        agentkit_commit=(
            str(row["agentkit_commit"]) if row["agentkit_commit"] is not None else None
        ),
        config_version=(
            str(row["config_version"]) if row["config_version"] is not None else None
        ),
        llm_roles=tuple(str(role) for role in llm_roles if isinstance(role, str)),
    )


# ---------------------------------------------------------------------------
# ExecutionEventRecord
# ---------------------------------------------------------------------------


def execution_event_to_row(event: ExecutionEventRecord) -> dict[str, Any]:
    """Convert an ``ExecutionEventRecord`` to a DB-insertable row dict."""

    return {
        "project_key": event.project_key,
        "story_id": event.story_id,
        "run_id": event.run_id,
        "event_id": event.event_id,
        "event_type": event.event_type,
        "occurred_at": event.occurred_at.isoformat(),
        "source_component": event.source_component,
        "severity": event.severity,
        "phase": event.phase,
        "flow_id": event.flow_id,
        "node_id": event.node_id,
        "payload_json": dump_json(event.payload),
    }


def execution_event_row_to_record(row: dict[str, Any]) -> ExecutionEventRecord:
    """Convert a DB row dict to an ``ExecutionEventRecord``."""

    from datetime import datetime

    from agentkit.telemetry.contract.records import (
        ExecutionEventRecord as _ExecutionEventRecord,
    )

    return _ExecutionEventRecord(
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
        payload=cast_json_record(load_json(str(row["payload_json"]), {})),
    )


# ---------------------------------------------------------------------------
# StoryExecutionLockRecord
# ---------------------------------------------------------------------------


def execution_lock_to_row(record: StoryExecutionLockRecord) -> dict[str, Any]:
    """Convert a ``StoryExecutionLockRecord`` to a DB-insertable row dict."""

    return {
        "project_key": record.project_key,
        "story_id": record.story_id,
        "run_id": record.run_id,
        "lock_type": record.lock_type,
        "status": record.status,
        "worktree_roots_json": dump_json(list(record.worktree_roots)),
        "binding_version": record.binding_version,
        "activated_at": record.activated_at.isoformat(),
        "updated_at": record.updated_at.isoformat(),
        "deactivated_at": (
            record.deactivated_at.isoformat()
            if record.deactivated_at is not None
            else None
        ),
    }


def execution_lock_row_to_record(row: dict[str, Any]) -> StoryExecutionLockRecord:
    """Convert a DB row dict to a ``StoryExecutionLockRecord``."""

    from datetime import datetime

    from agentkit.governance.guard_system.records import (
        StoryExecutionLockRecord as _StoryExecutionLockRecord,
    )

    deactivated_at_raw = row["deactivated_at"]
    return _StoryExecutionLockRecord(
        project_key=str(row["project_key"]),
        story_id=str(row["story_id"]),
        run_id=str(row["run_id"]),
        lock_type=str(row["lock_type"]),
        status=str(row["status"]),
        worktree_roots=tuple(load_json(row["worktree_roots_json"], [])),
        binding_version=str(row["binding_version"]),
        activated_at=datetime.fromisoformat(str(row["activated_at"])),
        updated_at=datetime.fromisoformat(str(row["updated_at"])),
        deactivated_at=(
            datetime.fromisoformat(str(deactivated_at_raw))
            if deactivated_at_raw is not None
            else None
        ),
    )


# ---------------------------------------------------------------------------
# SessionRunBindingRecord
# ---------------------------------------------------------------------------


def session_binding_to_row(record: SessionRunBindingRecord) -> dict[str, Any]:
    """Convert a ``SessionRunBindingRecord`` to a DB-insertable row dict."""

    return {
        "session_id": record.session_id,
        "project_key": record.project_key,
        "story_id": record.story_id,
        "run_id": record.run_id,
        "principal_type": record.principal_type,
        "worktree_roots_json": dump_json(list(record.worktree_roots)),
        "binding_version": record.binding_version,
        "updated_at": record.updated_at.isoformat(),
    }


def session_binding_row_to_record(row: dict[str, Any]) -> SessionRunBindingRecord:
    """Convert a DB row dict to a ``SessionRunBindingRecord``."""

    from datetime import datetime

    from agentkit.control_plane.records import (
        SessionRunBindingRecord as _SessionRunBindingRecord,
    )

    return _SessionRunBindingRecord(
        session_id=str(row["session_id"]),
        project_key=str(row["project_key"]),
        story_id=str(row["story_id"]),
        run_id=str(row["run_id"]),
        principal_type=str(row["principal_type"]),
        worktree_roots=tuple(load_json(row["worktree_roots_json"], [])),
        binding_version=str(row["binding_version"]),
        updated_at=datetime.fromisoformat(str(row["updated_at"])),
    )


# ---------------------------------------------------------------------------
# ControlPlaneOperationRecord
# ---------------------------------------------------------------------------


def control_plane_op_to_row(record: ControlPlaneOperationRecord) -> dict[str, Any]:
    """Convert a ``ControlPlaneOperationRecord`` to a DB-insertable row dict."""

    return {
        "op_id": record.op_id,
        "project_key": record.project_key,
        "story_id": record.story_id,
        "run_id": record.run_id,
        "session_id": record.session_id,
        "operation_kind": record.operation_kind,
        "phase": record.phase,
        "status": record.status,
        "response_json": dump_json(record.response_payload),
        "created_at": record.created_at.isoformat(),
        "updated_at": record.updated_at.isoformat(),
        # AG3-054 leased claim: ``claimed_at`` is stored as ISO-8601 TEXT so the
        # lease-expiry compare and the CAS exact-match roundtrip through plain
        # text (matching the table's created_at/updated_at convention).
        "claimed_by": record.claimed_by,
        "claimed_at": (
            record.claimed_at.isoformat() if record.claimed_at is not None else None
        ),
    }


def control_plane_op_row_to_record(
    row: dict[str, Any],
) -> ControlPlaneOperationRecord:
    """Convert a DB row dict to a ``ControlPlaneOperationRecord``."""

    from datetime import datetime
    from typing import cast

    from agentkit.control_plane.records import (
        ControlPlaneOperationRecord as _ControlPlaneOperationRecord,
    )

    return _ControlPlaneOperationRecord(
        op_id=str(row["op_id"]),
        project_key=str(row["project_key"]),
        story_id=str(row["story_id"]),
        run_id=cast("_OptionalString", row["run_id"]),
        session_id=cast("_OptionalString", row["session_id"]),
        operation_kind=str(row["operation_kind"]),
        phase=cast("_OptionalString", row["phase"]),
        status=str(row["status"]),
        response_payload=cast_json_record(load_json(row["response_json"], {})),
        created_at=datetime.fromisoformat(str(row["created_at"])),
        updated_at=datetime.fromisoformat(str(row["updated_at"])),
        claimed_by=cast("_OptionalString", row.get("claimed_by")),
        claimed_at=_parse_aware_claimed_at(row.get("claimed_at")),
        # ERROR-2 fix (AG3-054): preserve the EXACT raw column value so the
        # takeover CAS matches the raw stored ``claimed_at`` like-for-like. A
        # naive/legacy/malformed row would never CAS-match against the normalized
        # ``claimed_at`` (the op_id would be permanently poisoned).
        claimed_at_raw=_raw_claimed_at_text(row.get("claimed_at")),
    )


def _raw_claimed_at_text(claimed_at_raw: object) -> str | None:
    """Return the raw ``claimed_at`` column value as TEXT (ERROR-2, AG3-054).

    The takeover CAS compares against the RAW ``claimed_at`` TEXT column, so the
    observed match value must be the raw stored text -- not the normalized aware
    instant. ``None`` (no lease) stays ``None``; a ``datetime`` column (a backend
    that hands back native instants) is rendered via ``isoformat`` to match how the
    writer stamps the column; any other value is stringified.
    """
    from datetime import datetime

    if claimed_at_raw is None:
        return None
    if isinstance(claimed_at_raw, datetime):
        return claimed_at_raw.isoformat()
    return str(claimed_at_raw)


def _parse_aware_claimed_at(claimed_at_raw: object) -> datetime | None:
    """Normalize a stored ``claimed_at`` to an aware-UTC datetime (AG3-054 #4).

    WARNING-4 fix (#4): the lease-expiry compare in the runtime is ``aware_now -
    claimed_at``; a NAIVE (tz-unaware) ``claimed_at`` would raise ``TypeError`` and
    crash the retry before any takeover could reclaim the op_id. The lease ownership
    record is therefore normalized to aware UTC at THIS mapper boundary: a value
    already aware is converted to UTC; a NAIVE value is assumed UTC (the productive
    writer always stamps aware UTC via ``isoformat``, so a naive value is a
    legacy/foreign write and the only safe, fail-closed reading is UTC).

    A ``None`` value (a terminal row, or a legacy claim with no lease) maps to
    ``None`` -- the runtime's ``_claim_is_expired`` already treats that as EXPIRED
    (reclaimable). An UNPARSEABLE / malformed value also maps to ``None`` so the
    op_id is reclaimable (fail-closed) instead of crashing the takeover path.

    Args:
        claimed_at_raw: The raw ``claimed_at`` column value (TEXT / ``datetime`` /
            ``None``).

    Returns:
        The aware-UTC lease instant, or ``None`` when absent or malformed (both
        treated as EXPIRED downstream).
    """
    from datetime import UTC, datetime

    if claimed_at_raw is None:
        return None
    parsed: datetime
    if isinstance(claimed_at_raw, datetime):
        parsed = claimed_at_raw
    else:
        try:
            parsed = datetime.fromisoformat(str(claimed_at_raw))
        except ValueError:
            # Malformed lease instant: fail-closed reclaimable (treated as EXPIRED
            # downstream) rather than crashing the takeover compare with a raise.
            _log.warning(
                "control_plane_operations.claimed_at is unparseable (%r); "
                "treating the claim as EXPIRED (reclaimable, AG3-054 #4)",
                claimed_at_raw,
            )
            return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


# ---------------------------------------------------------------------------
# QAStageResultRecord
# ---------------------------------------------------------------------------


def qa_stage_result_row_to_record(row: dict[str, Any]) -> QAStageResultRecord:
    """Convert a DB row dict to a ``QAStageResultRecord``."""

    from datetime import datetime

    from agentkit.verify_system.stage_registry.records import (
        QAStageResultRecord as _QAStageResultRecord,
    )

    return _QAStageResultRecord(
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


# ---------------------------------------------------------------------------
# QAFindingRecord
# ---------------------------------------------------------------------------


def qa_finding_row_to_record(row: dict[str, Any]) -> QAFindingRecord:
    """Convert a DB row dict to a ``QAFindingRecord``."""

    from datetime import datetime

    from agentkit.verify_system.stage_registry.records import (
        QAFindingRecord as _QAFindingRecord,
    )

    return _QAFindingRecord(
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
        metadata=cast_json_record(load_json(str(row["metadata_json"]), {})),
    )


# ---------------------------------------------------------------------------
# QA layer artifact / verify decision serialization helpers
# (moved from BC-A modules so drivers need not import them directly)
# ---------------------------------------------------------------------------


def serialize_layer_result_to_dict(
    layer_result: LayerResult,
    *,
    attempt_nr: int,
) -> dict[str, object]:
    """Serialize a ``LayerResult`` to the canonical artifact payload dict."""

    from agentkit.verify_system.policy_engine.projections import (
        serialize_layer_result as _serialize_layer_result,
    )

    return _serialize_layer_result(layer_result, attempt_nr=attempt_nr)


def build_verify_decision_dict(
    decision: VerifyDecision,
    *,
    attempt_nr: int,
) -> dict[str, object]:
    """Build the canonical verify-decision artifact dict."""

    from agentkit.verify_system.policy_engine.projections import (
        build_verify_decision_artifact as _build_verify_decision_artifact,
    )

    return _build_verify_decision_artifact(decision, attempt_nr=attempt_nr)


def get_producer_component_for_layer(layer: str) -> str:
    """Return the canonical producer component name for a QA layer."""

    from agentkit.verify_system.qa_read_models import (
        producer_component_for_layer as _producer_component_for_layer,
    )

    return _producer_component_for_layer(layer)


def build_qa_stage_result_row(
    flow_row: dict[str, Any],
    layer_result: LayerResult,
    *,
    attempt_no: int,
    artifact_id: str,
    recorded_at: datetime,
) -> dict[str, Any]:
    """Build a ``qa_stage_results`` insert-row from a flow row and layer result."""

    from agentkit.verify_system.qa_read_models import (
        build_qa_stage_result as _build_qa_stage_result,
    )

    flow = flow_execution_row_to_record(flow_row)
    stage_record = _build_qa_stage_result(
        flow,
        layer_result,
        attempt_no=attempt_no,
        artifact_id=artifact_id,
        recorded_at=recorded_at,
    )
    return {
        "project_key": stage_record.project_key,
        "story_id": stage_record.story_id,
        "run_id": stage_record.run_id,
        "attempt_no": stage_record.attempt_no,
        "stage_id": stage_record.stage_id,
        "layer": stage_record.layer,
        "producer_component": stage_record.producer_component,
        "status": stage_record.status,
        "blocking": 1 if stage_record.blocking else 0,
        "total_checks": stage_record.total_checks,
        "failed_checks": stage_record.failed_checks,
        "warning_checks": stage_record.warning_checks,
        "artifact_id": stage_record.artifact_id,
        "recorded_at": stage_record.recorded_at.isoformat(),
    }


def build_qa_finding_rows(
    flow_row: dict[str, Any],
    layer_result: LayerResult,
    *,
    attempt_no: int,
    artifact_id: str,
    recorded_at: datetime,
) -> list[dict[str, Any]]:
    """Build ``qa_findings`` insert-rows from a flow row and layer result."""

    from agentkit.verify_system.qa_read_models import (
        build_qa_findings as _build_qa_findings,
    )

    flow = flow_execution_row_to_record(flow_row)
    finding_records = _build_qa_findings(
        flow,
        layer_result,
        attempt_no=attempt_no,
        artifact_id=artifact_id,
        recorded_at=recorded_at,
    )
    return [
        {
            "project_key": r.project_key,
            "story_id": r.story_id,
            "run_id": r.run_id,
            "attempt_no": r.attempt_no,
            "stage_id": r.stage_id,
            "finding_id": r.finding_id,
            "check_id": r.check_id,
            "status": r.status,
            "severity": r.severity,
            "blocking": 1 if r.blocking else 0,
            "source_component": r.source_component,
            "artifact_id": r.artifact_id,
            "occurred_at": r.occurred_at.isoformat(),
            "category": r.category,
            "reason": r.reason,
            "description": r.description,
            "detail": r.detail,
            "metadata_json": dump_json(r.metadata),
        }
        for r in finding_records
    ]
