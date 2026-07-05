"""Repository facade: selects the configured driver and applies mappers.

This module provides the canonical public API for state persistence.
All BC-Record <-> dict-row conversions happen here via ``mappers``.
Drivers (postgres_store, sqlite_store) only handle raw ``dict[str, Any]`` rows.
"""

from __future__ import annotations

import sys
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from functools import lru_cache
from typing import TYPE_CHECKING, Any, cast

from agentkit.backend.exceptions import CorruptStateError
from agentkit.backend.state_backend.config import (
    StateBackendKind,
    load_state_backend_config,
)
from agentkit.backend.state_backend.scope import (
    RuntimeStateScope,
    runtime_scope_from_state,
    scope_from_story_context,
)
from agentkit.backend.state_backend.store import mappers

if TYPE_CHECKING:
    from collections.abc import Iterator
    from datetime import datetime
    from pathlib import Path
    from types import ModuleType
    from uuid import UUID

    from agentkit.backend.auth.entities import ProjectApiToken
    from agentkit.backend.closure.execution_report.records import ExecutionReport
    from agentkit.backend.closure.post_merge_finalization.records import StoryMetricsRecord
    from agentkit.backend.control_plane.records import (
        BackendInstanceIdentityRecord,
        BindingDeleteScope,
        ControlPlaneOperationRecord,
        EdgeCommandRecord,
        ObjectMutationClaimRecord,
        RunOwnershipRecord,
        SessionRunBindingRecord,
        TakeoverTransferRecord,
    )
    from agentkit.backend.execution_planning.entities import (
        ParallelizationConfig,
        StoryDependency,
        StoryDependencyKind,
    )
    from agentkit.backend.governance.guard_system.records import StoryExecutionLockRecord
    from agentkit.backend.phase_state_store.models import (
        FlowExecution,
        NodeExecutionLedger,
        OverrideRecord,
    )
    from agentkit.backend.pipeline_engine.phase_executor.models import (
        PhaseSnapshot,
        PhaseState,
    )
    from agentkit.backend.pipeline_engine.phase_executor.records import AttemptRecord
    from agentkit.backend.project_management.entities import Project
    from agentkit.backend.prompt_runtime.execution_contract import (
        ExecutionContractDigestRecord,
    )
    from agentkit.backend.requirements_coverage.models import (
        StoryAreLink,
        StoryAreLinkKind,
    )
    from agentkit.backend.story_context_manager.models import StoryContext
    from agentkit.backend.telemetry.contract.records import ExecutionEventRecord
    from agentkit.backend.verify_system.policy_engine.engine import VerifyDecision
    from agentkit.backend.verify_system.protocols import LayerResult
    from agentkit.backend.verify_system.stage_registry.records import (
        QAFindingRecord,
        QAStageResultRecord,
    )

JsonRecord = dict[str, object]
_SESSION_BINDING_UNSUPPORTED = (
    "Global session binding storage is unsupported by the active backend"
)


@lru_cache(maxsize=1)
def _backend_module() -> ModuleType:
    config = load_state_backend_config()
    if config.backend is StateBackendKind.SQLITE:
        from agentkit.backend.state_backend import sqlite_store

        return sqlite_store

    from agentkit.backend.state_backend import postgres_store

    return postgres_store


def reset_backend_cache_for_tests() -> None:
    """Clear cached backend selection for test-time env switching."""

    _backend_module.cache_clear()
    postgres_store = sys.modules.get("agentkit.backend.state_backend.postgres_store")
    if postgres_store is not None:
        reset_schema_cache = getattr(
            postgres_store,
            "_reset_schema_bootstrap_cache_for_tests",
            None,
        )
        if callable(reset_schema_cache):
            reset_schema_cache()
    schema_bootstrap = sys.modules.get(
        "agentkit.backend.state_backend.schema_bootstrap",
    )
    if schema_bootstrap is not None:
        reset_versioned_schema_cache = getattr(
            schema_bootstrap,
            "_reset_versioned_schema_cache_for_tests",
            None,
        )
        if callable(reset_versioned_schema_cache):
            reset_versioned_schema_cache()


def active_backend_is_sqlite() -> bool:
    """Return ``True`` when the active backend is SQLite.

    Exposes the backend-kind discriminant at the sanctioned ``state_backend.store``
    surface so BCs that need to adapt their construction contract for SQLite
    (e.g. GovernanceObserver reader FIX C) can check without importing the
    restricted ``state_backend.config`` module (architecture conformance AC010/AC011).

    Returns:
        ``True`` iff the active configured backend is SQLite.
    """
    config = load_state_backend_config()
    return config.backend is StateBackendKind.SQLITE


def control_plane_backend_available() -> bool:
    """Whether the active backend provides the control-plane operation store (#3).

    The control-plane runtime store (operation/claim, session-binding and lock
    records) is Postgres-only by design (FK-22 §22.9). This reports whether the
    ACTIVE backend exposes the global control-plane operation row methods, so the
    control plane can fail closed CLEARLY (a non-Postgres backend has none) at the
    sanctioned ``state_backend.store`` surface -- without the control plane
    importing the raw ``state_backend.config`` driver module (architecture
    conformance AC010/AC011).

    Returns:
        ``True`` iff the active backend supports the control-plane store.
    """
    return hasattr(
        _backend_module(), "claim_control_plane_operation_global_row"
    )


def _require_control_plane_backend() -> None:
    """Fail closed with a ``ConfigError`` unless the Postgres control plane is active.

    AG3-137 (AK7, K5): the session-ownership tables (``run_ownership_records``,
    ``object_mutation_claims``, ``takeover_transfer_records``,
    ``backend_instance_identity``) are Postgres-only by design. AG3-145 reuses
    this SAME gate for the Edge-Command-Queue table (``edge_command_records``)
    -- one more Postgres-only table, the identical fail-closed contract. Access
    through a non-Postgres backend is a configuration error, surfaced explicitly
    at the sanctioned ``state_backend.store`` surface (the same fail-closed
    contract as ``control_plane.runtime._require_postgres_control_plane_backend``),
    never a silent no-op or a SQLite fallback.

    Raises:
        ConfigError: When the active backend does not provide the control-plane
            store.
    """
    if not control_plane_backend_available():
        from agentkit.backend.exceptions import ConfigError

        raise ConfigError(
            "The session-ownership store (run_ownership_records, "
            "object_mutation_claims, takeover_transfer_records, "
            "backend_instance_identity, edge_command_records) requires the "
            "Postgres state backend: these tables are Postgres-only (AG3-137 / "
            "AG3-145 K5) and have no SQLite implementation. Set "
            "AGENTKIT_STATE_BACKEND=postgres; fail-closed.",
        )


def _cast_json_record(value: object) -> JsonRecord | None:
    return cast("JsonRecord | None", value)


def load_json_safe(path: Path) -> JsonRecord | None:
    return _cast_json_record(_backend_module().load_json_safe(path))


def resolve_runtime_scope(story_dir: Path) -> RuntimeStateScope:
    """Resolve explicit canonical scope for one story and current run."""

    try:
        flow = load_flow_execution(story_dir)
    except CorruptStateError:
        flow = None
    if flow is not None:
        return RuntimeStateScope(
            project_key=flow.project_key,
            story_id=flow.story_id,
            story_dir=story_dir,
            run_id=flow.run_id,
            flow_id=flow.flow_id,
            attempt_no=flow.attempt_no,
        )

    try:
        ctx = load_story_context(story_dir)
    except CorruptStateError:
        ctx = None
    if ctx is not None:
        return runtime_scope_from_state(scope_from_story_context(story_dir, ctx))

    raise CorruptStateError(
        (
            "Cannot resolve runtime scope without canonical story context "
            "or flow execution"
        ),
        detail={
            "story_dir": str(story_dir),
            "story_id": story_dir.name,
        },
    )


# ---------------------------------------------------------------------------
# StoryContext
# ---------------------------------------------------------------------------


def save_story_context(story_dir: Path, ctx: StoryContext) -> None:
    row = mappers.story_context_to_row(ctx)
    _backend_module().save_story_context_row(story_dir, row)


def save_story_context_global(store_dir: Path | None, ctx: StoryContext) -> None:
    row = mappers.story_context_to_row(ctx)
    _backend_module().save_story_context_global_row(store_dir, row)


def load_story_context(story_dir: Path) -> StoryContext | None:
    row = _backend_module().load_story_context_row(story_dir)
    if row is None:
        return None
    return mappers.story_context_payload_to_record(
        str(row["payload_json"]),
        db_label=str(story_dir),
    )


def load_story_context_global(
    project_key: str,
    story_id: str,
    store_dir: Path | None = None,
) -> StoryContext | None:
    backend = _backend_module()
    if not hasattr(backend, "load_story_context_global_row"):
        raise RuntimeError(
            "Global story-context reads are unsupported by the active backend",
        )
    row = backend.load_story_context_global_row(store_dir, project_key, story_id)
    if row is None:
        return None
    return mappers.story_context_payload_to_record(
        str(row["payload_json"]),
        db_label="postgres",
    )


def load_story_context_by_story_number_global(
    store_dir: Path | None,
    project_key: str,
    story_number: int,
) -> StoryContext | None:
    row = _backend_module().load_story_context_by_story_number_row(
        store_dir,
        project_key,
        story_number,
    )
    if row is None:
        return None
    return mappers.story_context_payload_to_record(
        str(row["payload_json"]),
        db_label="story_contexts",
    )


def load_story_context_by_uuid_global(
    store_dir: Path | None,
    story_uuid: UUID,
) -> StoryContext | None:
    row = _backend_module().load_story_context_by_uuid_row(
        store_dir,
        str(story_uuid),
    )
    if row is None:
        return None
    return mappers.story_context_payload_to_record(
        str(row["payload_json"]),
        db_label="story_contexts",
    )


def load_story_contexts_global(
    project_key: str,
    store_dir: Path | None = None,
) -> list[StoryContext]:
    backend = _backend_module()
    if not hasattr(backend, "load_story_context_rows_global"):
        raise RuntimeError(
            "Global story-context reads are unsupported by the active backend",
        )
    rows = backend.load_story_context_rows_global(store_dir, project_key)
    result: list[StoryContext] = []
    for row in rows:
        result.append(
            mappers.story_context_payload_to_record(
                str(row["payload_json"]),
                db_label="postgres",
            )
        )
    return result


def read_story_context_record(story_dir: Path) -> StoryContext | None:
    return load_story_context(story_dir)


# ---------------------------------------------------------------------------
# Project
# ---------------------------------------------------------------------------


def save_project(project: Project, store_dir: Path | None = None) -> None:
    row = mappers.project_to_row(project)
    _backend_module().save_project_row(store_dir, row)


def load_project(key: str, store_dir: Path | None = None) -> Project | None:
    row = _backend_module().load_project_row(store_dir, key)
    if row is None:
        return None
    return mappers.project_row_to_entity(row)


def load_projects(
    store_dir: Path | None = None,
    *,
    include_archived: bool = False,
) -> list[Project]:
    rows = _backend_module().load_project_rows(
        store_dir,
        include_archived=include_archived,
    )
    return [mappers.project_row_to_entity(row) for row in rows]


def load_project_by_story_id_prefix(
    story_id_prefix: str,
    store_dir: Path | None = None,
) -> Project | None:
    row = _backend_module().load_project_row_by_story_id_prefix(
        store_dir,
        story_id_prefix,
    )
    if row is None:
        return None
    return mappers.project_row_to_entity(row)


# ---------------------------------------------------------------------------
# Project API tokens
# ---------------------------------------------------------------------------


def save_project_api_token(
    token: ProjectApiToken,
    store_dir: Path | None = None,
) -> None:
    row = mappers.project_api_token_to_row(token)
    _backend_module().save_project_api_token_row(store_dir, row)


def load_project_api_token(
    token_id: str,
    store_dir: Path | None = None,
) -> ProjectApiToken | None:
    row = _backend_module().load_project_api_token_row(store_dir, token_id)
    if row is None:
        return None
    return mappers.project_api_token_row_to_entity(row)


def load_project_api_token_by_hash(
    token_hash: str,
    store_dir: Path | None = None,
) -> ProjectApiToken | None:
    row = _backend_module().load_project_api_token_row_by_hash(store_dir, token_hash)
    if row is None:
        return None
    return mappers.project_api_token_row_to_entity(row)


def load_project_api_tokens_for_project(
    project_key: str,
    store_dir: Path | None = None,
) -> list[ProjectApiToken]:
    rows = _backend_module().load_project_api_token_rows_for_project(
        store_dir,
        project_key,
    )
    return [mappers.project_api_token_row_to_entity(row) for row in rows]


# ---------------------------------------------------------------------------
# Execution planning
# ---------------------------------------------------------------------------


def save_story_dependency(
    project_key: str,
    edge: StoryDependency,
    store_dir: Path | None = None,
) -> None:
    row = mappers.story_dependency_to_row(edge, project_key=project_key)
    _backend_module().save_story_dependency_row(store_dir, row)


def load_story_dependencies(
    project_key: str,
    store_dir: Path | None = None,
) -> list[StoryDependency]:
    rows = _backend_module().load_story_dependency_rows(store_dir, project_key)
    return [mappers.story_dependency_row_to_entity(row) for row in rows]


def load_story_dependency_rows_for_story(
    story_id: str,
    store_dir: Path | None = None,
) -> list[StoryDependency]:
    rows = _backend_module().load_story_dependency_rows_for_story(store_dir, story_id)
    return [mappers.story_dependency_row_to_entity(row) for row in rows]


def delete_story_dependency(
    story_id: str,
    depends_on_story_id: str,
    kind: StoryDependencyKind,
    store_dir: Path | None = None,
) -> int:
    return int(
        _backend_module().delete_story_dependency_row(
            store_dir,
            story_id,
            depends_on_story_id,
            kind.value,
        ),
    )


def load_parallelization_config(
    project_key: str,
    store_dir: Path | None = None,
) -> ParallelizationConfig | None:
    row = _backend_module().load_parallelization_config_row(store_dir, project_key)
    if row is None:
        return None
    return mappers.parallelization_config_row_to_entity(row)


def save_parallelization_config(
    config: ParallelizationConfig,
    store_dir: Path | None = None,
) -> None:
    row = mappers.parallelization_config_to_row(config)
    _backend_module().save_parallelization_config_row(store_dir, row)


# ---------------------------------------------------------------------------
# Requirements coverage
# ---------------------------------------------------------------------------


def save_story_are_link(
    link: StoryAreLink,
    store_dir: Path | None = None,
) -> None:
    row = mappers.story_are_link_to_row(link)
    _backend_module().save_story_are_link_row(store_dir, row)


def load_story_are_links(
    story_id: str,
    store_dir: Path | None = None,
) -> list[StoryAreLink]:
    rows = _backend_module().load_story_are_link_rows(store_dir, story_id)
    return [mappers.story_are_link_row_to_entity(row) for row in rows]


def update_story_are_link_kind(
    store_dir: Path | None,
    story_id: str,
    are_item_id: str,
    old_kind: StoryAreLinkKind,
    new_kind: StoryAreLinkKind,
) -> StoryAreLink | None:
    row = _backend_module().update_story_are_link_kind_row(
        store_dir,
        story_id,
        are_item_id,
        old_kind.value,
        new_kind.value,
    )
    if row is None:
        return None
    return mappers.story_are_link_row_to_entity(row)


def delete_story_are_link(
    store_dir: Path | None,
    story_id: str,
    are_item_id: str,
    kind: StoryAreLinkKind,
) -> int:
    return int(
        _backend_module().delete_story_are_link_row(
            store_dir,
            story_id,
            are_item_id,
            kind.value,
        ),
    )


# ---------------------------------------------------------------------------
# PhaseState
# ---------------------------------------------------------------------------


def save_phase_state(story_dir: Path, state: PhaseState) -> None:
    row = mappers.phase_state_to_row(state)
    _backend_module().save_phase_state_row(story_dir, row)


def load_phase_state(story_dir: Path) -> PhaseState | None:
    row = _backend_module().load_phase_state_row(story_dir)
    if row is None:
        return None
    return mappers.phase_state_payload_to_record(
        str(row["payload_json"]),
        db_label=str(story_dir),
    )


def load_phase_state_global(
    story_id: str,
    store_dir: Path | None = None,
) -> PhaseState | None:
    backend = _backend_module()
    if not hasattr(backend, "load_phase_state_global_row"):
        raise RuntimeError(
            "Global phase-state reads are unsupported by the active backend",
        )
    row = backend.load_phase_state_global_row(store_dir, story_id)
    if row is None:
        return None
    return mappers.phase_state_payload_to_record(
        str(row["payload_json"]),
        db_label="postgres",
    )


def read_phase_state_record(story_dir: Path) -> PhaseState | None:
    return load_phase_state(story_dir)


# ---------------------------------------------------------------------------
# PhaseSnapshot
# ---------------------------------------------------------------------------


def save_phase_snapshot(story_dir: Path, snapshot: PhaseSnapshot) -> None:
    row = mappers.phase_snapshot_to_row(snapshot)
    _backend_module().save_phase_snapshot_row(story_dir, row)


def load_phase_snapshot(story_dir: Path, phase: str) -> PhaseSnapshot | None:
    row = _backend_module().load_phase_snapshot_row(story_dir, phase)
    if row is None:
        return None
    return mappers.phase_snapshot_payload_to_record(
        str(row["payload_json"]),
        phase,
        db_label=str(story_dir),
    )


def read_phase_snapshot_record(
    story_dir: Path,
    phase: str,
) -> PhaseSnapshot | None:
    return load_phase_snapshot(story_dir, phase)


# ---------------------------------------------------------------------------
# AttemptRecord
# ---------------------------------------------------------------------------


def save_attempt(story_dir: Path, attempt: AttemptRecord) -> None:
    row = mappers.attempt_record_to_row(attempt)
    _backend_module().save_attempt_row(story_dir, row)


def load_attempts(
    story_dir: Path,
    phase: str,
    *,
    run_id: str | None = None,
) -> list[AttemptRecord]:
    """Load AttemptRecords for a story+phase, optionally narrowed to a run.

    Fail-closed: invalid DB rows (CHECK-constraint drift, schema mismatch
    between backend and mapper, corrupt JSON payloads) propagate
    ``pydantic.ValidationError`` / ``ValueError`` to the caller. An earlier
    ``except`` silently swallowed defective rows — that masked real
    inconsistencies (cf. AG3-025 re-review finding 1).
    """

    rows = _backend_module().load_attempt_rows(story_dir, phase, run_id=run_id)
    return [mappers.attempt_row_to_record(row) for row in rows]


# ---------------------------------------------------------------------------
# ExecutionEventRecord
# ---------------------------------------------------------------------------


def append_execution_event(story_dir: Path, event: ExecutionEventRecord) -> None:
    row = mappers.execution_event_to_row(event)
    _backend_module().append_execution_event_row(story_dir, row)


def append_execution_event_global(event: ExecutionEventRecord) -> None:
    backend = _backend_module()
    if not hasattr(backend, "append_execution_event_global_row"):
        raise RuntimeError(
            "Global execution-event append is unsupported by the active backend",
        )
    row = mappers.execution_event_to_row(event)
    backend.append_execution_event_global_row(row)


def load_execution_events(
    story_dir: Path,
    *,
    project_key: str | None = None,
    story_id: str | None = None,
    run_id: str | None = None,
    event_type: str | None = None,
    limit: int | None = None,
) -> list[ExecutionEventRecord]:
    rows = _backend_module().load_execution_event_rows(
        story_dir,
        project_key=project_key,
        story_id=story_id,
        run_id=run_id,
        event_type=event_type,
        limit=limit,
    )
    return [mappers.execution_event_row_to_record(row) for row in rows]


def load_execution_events_global(
    project_key: str,
    story_id: str,
    *,
    run_id: str | None = None,
    event_type: str | None = None,
    limit: int | None = None,
) -> list[ExecutionEventRecord]:
    backend = _backend_module()
    if not hasattr(backend, "load_execution_event_rows_global"):
        raise RuntimeError(
            "Global execution-event reads are unsupported by the active backend",
        )
    rows = backend.load_execution_event_rows_global(
        project_key,
        story_id,
        run_id=run_id,
        event_type=event_type,
        limit=limit,
    )
    return [mappers.execution_event_row_to_record(row) for row in rows]


def load_execution_events_for_project_global(
    project_key: str,
    *,
    limit: int | None = None,
) -> list[ExecutionEventRecord]:
    backend = _backend_module()
    if not hasattr(backend, "load_execution_event_rows_for_project_global"):
        raise RuntimeError(
            "Global project execution-event reads are unsupported by the active backend",
        )
    rows = backend.load_execution_event_rows_for_project_global(
        project_key,
        limit=limit,
    )
    return [mappers.execution_event_row_to_record(row) for row in rows]


def load_last_adjudication_ts(
    story_dir: Path,
    *,
    project_key: str,
    story_id: str,
    run_id: str,
    payload_signal_type: str,
) -> float | None:
    """Return the UNIX timestamp of the last ``governance_adjudication`` for the scope.

    Implements FK-35 §35.3.11: queries the EXACT ``(project_key, story_id,
    run_id, signal_type)`` tuple via a DB-side MAX(occurred_at) with exact
    JSON matching.  This avoids the bounded-scan + Python-max pattern that can
    miss same-signal adjudications when 200+ other-signal adjudications are newer.

    Both stores apply identical semantics (``payload_json`` is a ``TEXT``
    column in both schemas):
    - SQLite: ``json_extract(payload_json, '$.signal_type') = ?``
    - Postgres: ``(payload_json::jsonb)->>'signal_type' = ?`` (cast required
      because the ``->>`` operator does not apply to ``TEXT``).

    Neither uses LIKE (which could false-match substrings).

    Args:
        story_dir: Story directory (used by the SQLite driver; ignored by Postgres
            which derives the connection from the environment).
        project_key: Exact project scope.
        story_id: Exact story scope.
        run_id: Exact run scope.
        payload_signal_type: Exact ``signal_type`` wire value to match.

    Returns:
        UNIX float timestamp of the most-recent matching adjudication, or
        ``None`` when no such adjudication exists.
    """
    from datetime import UTC, datetime

    raw = _backend_module().max_adjudication_occurred_at(
        story_dir,
        project_key=project_key,
        story_id=story_id,
        run_id=run_id,
        payload_signal_type=payload_signal_type,
    )
    if raw is None:
        return None
    # occurred_at is stored as ISO-8601; parse and return as UNIX float.
    dt = datetime.fromisoformat(raw)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.timestamp()


# ---------------------------------------------------------------------------
# SessionRunBindingRecord
# ---------------------------------------------------------------------------


def save_session_run_binding_global(record: SessionRunBindingRecord) -> None:
    backend = _backend_module()
    if not hasattr(backend, "save_session_run_binding_global_row"):
        raise RuntimeError(_SESSION_BINDING_UNSUPPORTED)
    row = mappers.session_binding_to_row(record)
    backend.save_session_run_binding_global_row(row)


def load_session_run_binding_global(
    session_id: str,
) -> SessionRunBindingRecord | None:
    backend = _backend_module()
    if not hasattr(backend, "load_session_run_binding_global_row"):
        raise RuntimeError(_SESSION_BINDING_UNSUPPORTED)
    row = backend.load_session_run_binding_global_row(session_id)
    if row is None:
        return None
    return mappers.session_binding_row_to_record(row)


def delete_session_run_binding_global(session_id: str) -> None:
    backend = _backend_module()
    if not hasattr(backend, "delete_session_run_binding_global"):
        raise RuntimeError(_SESSION_BINDING_UNSUPPORTED)
    backend.delete_session_run_binding_global(session_id)


# ---------------------------------------------------------------------------
# RunOwnershipRecord (AG3-137, Postgres-only K5)
# ---------------------------------------------------------------------------


def insert_run_ownership_record_global(record: RunOwnershipRecord) -> None:
    """Strictly INSERT one run-ownership record (AG3-137).

    Fail-closed on a non-Postgres backend (``ConfigError``). The ``TRANSFERRED``
    status has no writer in this strand (AG3-137 scope §1): persisting it is
    rejected here at the write boundary, so no path (takeover/disown/recovery)
    can silently set it. A second active record for the same story is rejected by
    the persistence layer's partial-unique index (AK1).

    Raises:
        ConfigError: On a non-Postgres backend.
        ValueError: When ``status`` is ``TRANSFERRED`` (no writer, fail-closed).
    """
    from agentkit.backend.control_plane.ownership import OwnershipStatus

    if record.status is OwnershipStatus.TRANSFERRED:
        raise ValueError(
            "run-ownership status 'transferred' has no writer in this strand "
            "(AG3-137 scope §1): a run-continuing takeover is an in-place CAS "
            "that keeps status='active'; setting 'transferred' is fail-closed "
            "rejected until a normative concretisation exists.",
        )
    _require_control_plane_backend()
    backend = _backend_module()
    backend.insert_run_ownership_record_global_row(mappers.run_ownership_to_row(record))


def load_run_ownership_record_global(
    project_key: str,
    story_id: str,
    run_id: str,
) -> RunOwnershipRecord | None:
    """Load one run-ownership record by run identity, or ``None``."""
    _require_control_plane_backend()
    backend = _backend_module()
    row = backend.load_run_ownership_record_global_row(project_key, story_id, run_id)
    if row is None:
        return None
    return mappers.run_ownership_row_to_record(row)


def load_active_run_ownership_record_global(
    project_key: str,
    story_id: str,
) -> RunOwnershipRecord | None:
    """Load the single active run-ownership record for a story, or ``None``."""
    _require_control_plane_backend()
    backend = _backend_module()
    row = backend.load_active_run_ownership_record_global_row(project_key, story_id)
    if row is None:
        return None
    return mappers.run_ownership_row_to_record(row)


def resolve_ownership_fence_snapshot(
    project_key: str,
    story_id: str,
) -> tuple[str, int] | None:
    """Resolve the caller's early ownership-lease snapshot (AG3-144, FK-91 §91.1a Rule 15).

    Business-logic write paths (the implementation/closure phase handlers)
    call this ONCE, as early as feasible in their own execution, to capture
    the active ``run_ownership_records`` row's ``(owner_session_id,
    ownership_epoch)`` -- mirroring the control-plane's own admission
    snapshot (AG3-142). The snapshot is threaded into the later
    ``record_layer_artifacts`` / ``record_verify_decision`` /
    ``record_closure_report`` calls, which re-verify it AT COMMIT TIME, in
    the SAME transaction, under ``SELECT ... FOR UPDATE`` (no TOCTOU).

    K5 Postgres-only (Querschnitts-Auflagen): on a non-Postgres backend (the
    narrow SQLite unit-test path) this returns ``None`` -- explicit, not a
    silent skip -- so the caller falls back to inert placeholder values that
    the ``sqlite_store`` driver functions explicitly ignore. There is no
    fence mirroring on SQLite.

    Returns:
        ``(owner_session_id, ownership_epoch)`` on Postgres, or ``None`` on a
        non-Postgres backend.

    Raises:
        CorruptStateError: On Postgres, when no active ``run_ownership_records``
            row exists for ``(project_key, story_id)`` -- an in-flight phase
            execution without an active lease is a state-integrity fault, not
            a scenario to silently tolerate.
    """
    if load_state_backend_config().backend is not StateBackendKind.POSTGRES:
        return None
    active = load_active_run_ownership_record_global(project_key, story_id)
    if active is None:
        raise CorruptStateError(
            "No active run-ownership record found for an in-flight phase "
            "execution (AG3-142/AG3-144 no-lease-no-write precondition)",
            detail={"project_key": project_key, "story_id": story_id},
        )
    return (active.owner_session_id, active.ownership_epoch)


# ---------------------------------------------------------------------------
# OwnershipFenceScope (AG3-144 Codex round-2 remediation): a ContextVar-scoped
# lease binding for the artifact_envelopes / qa_check_outcomes write boundary.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class OwnershipFenceScope:
    """The caller's early-captured ownership-lease snapshot for ONE phase attempt.

    AG3-144 (Codex round-2, FK-91 §91.1a Rule 15): ``artifact_envelopes`` and
    ``qa_check_outcomes`` are written from many BCs (verify-system's QA-subflow
    layers, prompt-runtime materialization, the adversarial orchestrator,
    exploration drafting/review, the ARE-gate audit) through call graphs many
    frames deep. Threading ``owner_session_id`` / ``expected_ownership_epoch``
    as an explicit parameter through every one of those signatures
    (``ArtifactManager.write``, ``PromptRuntime.materialize_prompt``, the
    ``QALayer`` protocol, the exploration ``ChangeFrameSink`` /
    ``ReviewResultSink`` ports, ...) would multiply a single fence mechanism
    into dozens of unrelated public contracts -- the OPPOSITE of FIX THE MODEL.

    Instead, the phase handler that owns the admission-time snapshot
    (``resolve_ownership_fence_snapshot``, called ONCE, as early as feasible)
    binds it for the duration of its own mutating call via
    :func:`bind_ownership_fence_scope`; every ``state_backend`` Postgres write
    reachable from that call -- regardless of how many BC-internal layers
    separate it from the phase handler -- reads the SAME bound snapshot via
    :func:`require_ownership_fence_scope` and re-verifies it AT COMMIT TIME via
    the AG3-142 ``_enforce_ownership_fence_row`` (never a second fence
    predicate). This mirrors the existing per-attempt ``ContextVar`` precedent
    already used in this codebase
    (``verify_system.llm_evaluator.structured_evaluator._EVAL_DEADLINE_CV``).

    Attributes:
        project_key: Project key (fence scope).
        story_id: Story display id the scope is bound to; a write for a
            DIFFERENT story_id is rejected fail-closed (no cross-story reuse).
        run_id: The run correlation id THIS phase attempt is executing under
            (the fence's ``run_id`` predicate input) -- deliberately NOT
            necessarily the individual envelope's own ``run_id`` field, so a
            project-scoped audit artifact (e.g. the ARE-gate ``are_gate.json``)
            can keep its own domain identity while still being fenced against
            the REAL active run.
        owner_session_id: The caller's early-captured
            ``run_ownership_records.owner_session_id`` snapshot.
        expected_ownership_epoch: The caller's early-captured
            ``ownership_epoch`` snapshot.
    """

    project_key: str
    story_id: str
    run_id: str
    owner_session_id: str
    expected_ownership_epoch: int


_OWNERSHIP_FENCE_SCOPE_CV: ContextVar[OwnershipFenceScope | None] = ContextVar(
    "agentkit_ownership_fence_scope",
    default=None,
)


@contextmanager
def bind_ownership_fence_scope(
    *,
    project_key: str,
    story_id: str,
    run_id: str,
    owner_session_id: str,
    expected_ownership_epoch: int,
) -> Iterator[None]:
    """Bind the caller's early-captured lease snapshot for this call's duration.

    The phase handler that captured the admission-time snapshot (e.g.
    ``ImplementationPhaseHandler.on_enter``, ``ExplorationPhaseHandler.on_enter``)
    wraps its ENTIRE mutating execution (the QA-subflow, prompt materialization,
    the ARE-gate check, drafting/review persistence, ...) in this context
    manager, ONCE, using the SAME ``(owner_session_id, expected_ownership_epoch)``
    values it resolved via :func:`resolve_ownership_fence_snapshot` at admission
    time. Never nested in practice (a nested bind would indicate two
    overlapping phase-attempt scopes on one call stack, a modelling error);
    ``ContextVar.reset`` restores the outer value regardless, so a defensive
    nested bind still unwinds correctly.

    Args:
        project_key: Project key (fence scope).
        story_id: Story display id this call is executing for.
        run_id: The run correlation id this call is executing under.
        owner_session_id: The early-captured
            ``run_ownership_records.owner_session_id`` snapshot.
        expected_ownership_epoch: The early-captured ``ownership_epoch``
            snapshot.

    Yields:
        None.
    """
    scope = OwnershipFenceScope(
        project_key=project_key,
        story_id=story_id,
        run_id=run_id,
        owner_session_id=owner_session_id,
        expected_ownership_epoch=expected_ownership_epoch,
    )
    token = _OWNERSHIP_FENCE_SCOPE_CV.set(scope)
    try:
        yield
    finally:
        _OWNERSHIP_FENCE_SCOPE_CV.reset(token)


def require_ownership_fence_scope(*, story_id: str) -> OwnershipFenceScope:
    """Return the bound :class:`OwnershipFenceScope` (fail-closed).

    The state_backend Postgres write boundary (``StateBackendArtifactRepository``
    / ``FacadeQACheckOutcomesRepository``) calls this INSTEAD of accepting an
    ``owner_session_id`` / ``expected_ownership_epoch`` parameter directly -- a
    caller that reaches the write boundary with no bound scope is a hard
    runtime error, never a silent skip (AG3-144 Codex round-2, Rule 15).

    Args:
        story_id: The envelope's/record's own ``story_id`` -- cross-checked
            against the bound scope so a write can never be fenced against a
            DIFFERENT story's lease.

    Returns:
        The bound :class:`OwnershipFenceScope`.

    Raises:
        CorruptStateError: When no scope is bound, or the bound scope's
            ``story_id`` does not match ``story_id`` (fail-closed).
    """
    scope = _OWNERSHIP_FENCE_SCOPE_CV.get()
    if scope is None:
        raise CorruptStateError(
            "No OwnershipFenceScope is bound (AG3-144 Rule 15, no-lease-no-write): "
            "a mutating artifact_envelopes/qa_check_outcomes write was attempted "
            "outside bind_ownership_fence_scope. Every phase handler that writes "
            "a story projection must bind its early-captured "
            "resolve_ownership_fence_snapshot() result for the duration of its "
            "mutating call (fail-closed, no unfenced write path).",
            detail={"story_id": story_id},
        )
    if scope.story_id != story_id:
        raise CorruptStateError(
            "OwnershipFenceScope story_id mismatch: the bound scope belongs to "
            "a different story than the write being attempted (fail-closed, no "
            "cross-story fence reuse).",
            detail={"bound_story_id": scope.story_id, "write_story_id": story_id},
        )
    return scope


# ---------------------------------------------------------------------------
# EdgeCommandRecord (AG3-145, Postgres-only K5)
# ---------------------------------------------------------------------------


def insert_edge_command_record_global(record: EdgeCommandRecord) -> None:
    """Strictly INSERT one edge-command row (AG3-145 command creation).

    Fail-closed on a non-Postgres backend (``ConfigError``, K5).
    """
    _require_control_plane_backend()
    backend = _backend_module()
    backend.insert_edge_command_record_global_row(
        mappers.edge_command_record_to_row(record)
    )


def load_edge_command_record_global(command_id: str) -> EdgeCommandRecord | None:
    """Load one edge-command record by ``command_id``, or ``None`` (K5)."""
    _require_control_plane_backend()
    backend = _backend_module()
    row = backend.load_edge_command_record_global_row(command_id)
    if row is None:
        return None
    return mappers.edge_command_row_to_record(row)


def list_and_ack_open_edge_command_records_global(
    *,
    project_key: str,
    run_id: str,
    session_id: str,
    delivered_at: datetime,
) -> tuple[EdgeCommandRecord, ...]:
    """Return + ack the session's open commands (K5, FK-91 §91.1a Rule 13: no lock)."""
    _require_control_plane_backend()
    backend = _backend_module()
    rows = backend.list_and_ack_open_edge_command_records_global_row(
        project_key=project_key,
        run_id=run_id,
        session_id=session_id,
        delivered_at=delivered_at.isoformat(),
    )
    return tuple(mappers.edge_command_row_to_record(row) for row in rows)


def commit_edge_command_result_global(
    op_record: ControlPlaneOperationRecord,
    *,
    command_id: str,
    result_status: str,
    completed_at: datetime,
    result_op_id: str,
    result_type: str,
    result_payload: dict[str, object],
    expected_ownership_epoch: int,
) -> None:
    """Atomically commit the op-ledger row AND the command-result CAS (K5, AG3-145).

    Fail-closed on a non-Postgres backend (``ConfigError``, K5).

    Raises:
        ControlPlaneClaimCollisionError: On an op_id collision with a LIVE
            claimed row.
        OwnershipFenceViolationError: (AG3-142 reuse) When the story's active
            ownership record no longer admits this exact snapshot.
        EdgeCommandNotOpenError: When ``command_id`` is unknown or already
            terminal (double-completion) -- nothing committed.
    """
    _require_control_plane_backend()
    backend = _backend_module()
    backend.commit_edge_command_result_global_row(
        op_row=mappers.control_plane_op_to_row(op_record),
        command_id=command_id,
        result_row={
            "status": result_status,
            "completed_at": completed_at.isoformat(),
            "result_op_id": result_op_id,
            "result_type": result_type,
            "result_payload_json": mappers.dump_json(result_payload),
        },
        expected_ownership_epoch=expected_ownership_epoch,
    )


# ---------------------------------------------------------------------------
# ExecutionContractDigestRecord (AG3-143, Postgres-only K5)
# ---------------------------------------------------------------------------


def insert_execution_contract_digest_global(
    record: ExecutionContractDigestRecord,
) -> None:
    """Strictly INSERT one execution-contract-digest row (AG3-143).

    Standalone entrypoint (test seeding / backfill parity with
    ``insert_run_ownership_record_global``); the productive setup-start
    writer inserts atomically WITHIN the
    ``finalize_control_plane_start_phase_global_row`` transaction instead
    (see ``execution_contract_digest_row_to_insert``), never via this
    standalone call. Fail-closed on a non-Postgres backend (``ConfigError``,
    K5); a second row for the same ``(project_key, story_id, run_id)``
    identity is rejected by the persistence layer's primary key (read-only
    after insert, FK-44 §44.3a).
    """
    _require_control_plane_backend()
    backend = _backend_module()
    backend.insert_execution_contract_digest_global_row(
        mappers.execution_contract_digest_to_row(record),
    )


def load_execution_contract_digest_global(
    project_key: str,
    story_id: str,
    run_id: str,
) -> ExecutionContractDigestRecord | None:
    """Load the run's persisted ``execution_contract_digest`` row, or ``None``.

    Lock-free (FK-44 §44.3a: the digest fence predicate never takes a lock).
    """
    _require_control_plane_backend()
    backend = _backend_module()
    row = backend.load_execution_contract_digest_global_row(
        project_key, story_id, run_id,
    )
    if row is None:
        return None
    return mappers.execution_contract_digest_row_to_record(row)


# ---------------------------------------------------------------------------
# ObjectMutationClaimRecord (AG3-137, Postgres-only K5)
# ---------------------------------------------------------------------------


def insert_object_mutation_claim_global(record: ObjectMutationClaimRecord) -> None:
    """Strictly INSERT one object-mutation claim (AG3-137). Fail-closed off-Postgres."""
    _require_control_plane_backend()
    backend = _backend_module()
    backend.insert_object_mutation_claim_global_row(
        mappers.object_mutation_claim_to_row(record),
    )


def load_object_mutation_claim_global(
    project_key: str,
    serialization_scope: str,
    scope_key: str,
) -> ObjectMutationClaimRecord | None:
    """Load one object-mutation claim by claimed-object identity, or ``None``."""
    _require_control_plane_backend()
    backend = _backend_module()
    row = backend.load_object_mutation_claim_global_row(
        project_key, serialization_scope, scope_key,
    )
    if row is None:
        return None
    return mappers.object_mutation_claim_row_to_record(row)


def acquire_object_mutation_claim_global(
    *,
    project_key: str,
    serialization_scope: str,
    scope_key: str,
    op_id: str,
    backend_instance_id: str,
    instance_incarnation: int,
    acquired_at: datetime,
) -> bool:
    """Atomically acquire the per-Story object-mutation claim (AG3-141).

    An ``INSERT ... ON CONFLICT DO NOTHING`` on the object PK at the backend
    (:func:`agentkit.backend.state_backend.postgres_store.acquire_object_mutation_claim_global_row`)
    -- the PK collision IS the serialization. Fail-closed off-Postgres (K5).
    """
    _require_control_plane_backend()
    backend = _backend_module()
    return bool(
        backend.acquire_object_mutation_claim_global_row(
            {
                "project_key": project_key,
                "serialization_scope": serialization_scope,
                "scope_key": scope_key,
                "op_id": op_id,
                "backend_instance_id": backend_instance_id,
                "instance_incarnation": instance_incarnation,
                "acquired_at": acquired_at.isoformat(),
            },
        ),
    )


def delete_object_mutation_claim_global(
    project_key: str,
    serialization_scope: str,
    scope_key: str,
    op_id: str,
) -> bool:
    """Ownership-scoped (op_id-CAS) release of one object-mutation claim (AG3-141).

    Idempotent: a no-op (``False``) when the row is already gone or held by a
    different ``op_id``. Fail-closed off-Postgres.
    """
    _require_control_plane_backend()
    backend = _backend_module()
    return bool(
        backend.delete_object_mutation_claim_global(
            project_key, serialization_scope, scope_key, op_id,
        ),
    )


def list_orphaned_object_mutation_claims_global(
    backend_instance_id: str,
    before_incarnation: int,
) -> tuple[ObjectMutationClaimRecord, ...]:
    """List object-mutation claims orphaned by EARLIER incarnations of THIS instance.

    Startup reconciliation (AG3-141 Scope item 7): only claims stamped with the
    CALLING instance's own ``backend_instance_id`` from a strictly earlier
    ``instance_incarnation`` are returned -- never a foreign identity.
    """
    _require_control_plane_backend()
    backend = _backend_module()
    rows = backend.list_orphaned_object_mutation_claims_global_row(
        backend_instance_id=backend_instance_id,
        before_incarnation=before_incarnation,
    )
    return tuple(mappers.object_mutation_claim_row_to_record(row) for row in rows)


# ---------------------------------------------------------------------------
# TakeoverTransferRecord (AG3-137, Postgres-only K5)
# ---------------------------------------------------------------------------


def save_takeover_transfer_record_global(record: TakeoverTransferRecord) -> None:
    """Upsert one takeover-transfer record (AG3-137). Fail-closed off-Postgres."""
    _require_control_plane_backend()
    backend = _backend_module()
    backend.save_takeover_transfer_record_global_row(
        mappers.takeover_transfer_to_row(record),
    )


def load_takeover_transfer_record_global(
    project_key: str,
    story_id: str,
    run_id: str,
    ownership_epoch: int,
    repo_id: str,
) -> TakeoverTransferRecord | None:
    """Load one takeover-transfer record by per-repo identity, or ``None``."""
    _require_control_plane_backend()
    backend = _backend_module()
    row = backend.load_takeover_transfer_record_global_row(
        project_key, story_id, run_id, ownership_epoch, repo_id,
    )
    if row is None:
        return None
    return mappers.takeover_transfer_row_to_record(row)


# ---------------------------------------------------------------------------
# BackendInstanceIdentityRecord (AG3-137, Postgres-only K5)
# ---------------------------------------------------------------------------


def save_backend_instance_identity_global(
    record: BackendInstanceIdentityRecord,
) -> None:
    """Upsert the backend-instance-identity record (AG3-137). Fail-closed off-Postgres."""
    _require_control_plane_backend()
    backend = _backend_module()
    backend.save_backend_instance_identity_global_row(
        mappers.backend_instance_identity_to_row(record),
    )


def load_backend_instance_identity_global(
    backend_instance_id: str,
) -> BackendInstanceIdentityRecord | None:
    """Load the backend-instance-identity record, or ``None``."""
    _require_control_plane_backend()
    backend = _backend_module()
    row = backend.load_backend_instance_identity_global_row(backend_instance_id)
    if row is None:
        return None
    return mappers.backend_instance_identity_row_to_record(row)


def boot_backend_instance_identity_global(
    candidate_backend_instance_id: str,
    now: datetime,
) -> BackendInstanceIdentityRecord:
    """Atomically resolve the boot-time backend instance identity (AG3-138).

    First boot ever: persists ``candidate_backend_instance_id`` with
    ``instance_incarnation = 1``. Every later boot: keeps the EXISTING
    (stable) ``backend_instance_id`` and increments ``instance_incarnation`` by
    exactly 1 -- deterministic, no wall-clock input. Fail-closed off-Postgres.
    """
    _require_control_plane_backend()
    backend = _backend_module()
    row = backend.boot_backend_instance_identity_global_row(
        candidate_backend_instance_id=candidate_backend_instance_id,
        now=now.isoformat(),
    )
    return mappers.backend_instance_identity_row_to_record(row)


# ---------------------------------------------------------------------------
# StoryExecutionLockRecord
# ---------------------------------------------------------------------------


def save_story_execution_lock_global(record: StoryExecutionLockRecord) -> None:
    backend = _backend_module()
    if not hasattr(backend, "save_story_execution_lock_global_row"):
        raise RuntimeError(
            "Global story-execution locks are unsupported by the active backend",
        )
    row = mappers.execution_lock_to_row(record)
    backend.save_story_execution_lock_global_row(row)


def load_story_execution_lock_global(
    project_key: str,
    story_id: str,
    run_id: str,
    lock_type: str = "story_execution",
) -> StoryExecutionLockRecord | None:
    backend = _backend_module()
    if not hasattr(backend, "load_story_execution_lock_global_row"):
        raise RuntimeError(
            "Global story-execution locks are unsupported by the active backend",
        )
    row = backend.load_story_execution_lock_global_row(
        project_key,
        story_id,
        run_id,
        lock_type,
    )
    if row is None:
        return None
    return mappers.execution_lock_row_to_record(row)


# ---------------------------------------------------------------------------
# ControlPlaneOperationRecord
# ---------------------------------------------------------------------------


#: Raised when a backend does not implement the global control-plane operation
#: row surface (shared by every ``*_control_plane_operation_global`` facade).
_GLOBAL_CP_OP_UNSUPPORTED = (
    "Global control-plane operations are unsupported by the active backend"
)


def save_control_plane_operation_global(
    record: ControlPlaneOperationRecord,
) -> None:
    backend = _backend_module()
    if not hasattr(backend, "save_control_plane_operation_global_row"):
        raise RuntimeError(
            _GLOBAL_CP_OP_UNSUPPORTED,
        )
    row = mappers.control_plane_op_to_row(record)
    backend.save_control_plane_operation_global_row(row)


def claim_control_plane_operation_global(
    record: ControlPlaneOperationRecord,
) -> bool:
    """Atomically claim an op_id before dispatch (AG3-054 E4).

    Returns ``True`` iff this caller inserted the placeholder row (won the claim);
    ``False`` when the op_id already existed. The win/lose decision is made at the
    backend (``INSERT ... ON CONFLICT DO NOTHING``), so two concurrent callers of
    the same op_id cannot both run the dispatch side effects.
    """
    backend = _backend_module()
    if not hasattr(backend, "claim_control_plane_operation_global_row"):
        raise RuntimeError(
            "Atomic control-plane op claim is unsupported by the active backend",
        )
    row = mappers.control_plane_op_to_row(record)
    return bool(backend.claim_control_plane_operation_global_row(row))


def finalize_control_plane_operation_global(
    record: ControlPlaneOperationRecord,
    *,
    owner_token: str,
    owner_claimed_at: str | None = None,
    owner_operation_epoch: int | None = None,
) -> bool:
    """Ownership-scoped terminal write of a claimed op (AG3-054 owner-scoped claim).

    Writes the terminal result + clears ``claimed_by`` ONLY when the row is still
    ``claimed`` by ``owner_token``. Returns ``True`` iff this owner's terminal
    write applied; ``False`` when another owner (or an admin-abort) already
    resolved the row in between (the caller must then replay/reject, never
    overwrite).

    WARNING-4 fix (#4): when ``owner_claimed_at`` (the RAW claim instant the owner
    stamped) is given, the CAS also matches ``claimed_at`` so it scopes to THIS
    claim generation -- a stale owner whose token is reused cannot match a NEWER
    claim. ``None`` keeps the legacy owner-only CAS (direct administrative
    callers).

    AG3-138: when ``owner_operation_epoch`` is given, the CAS additionally
    requires the stored ``operation_epoch`` to be unchanged
    (``operation_finalize_requires_cas_on_operation_epoch``).
    """
    backend = _backend_module()
    if not hasattr(backend, "finalize_control_plane_operation_global_row"):
        raise RuntimeError(
            "Control-plane op finalize is unsupported by the active backend",
        )
    row = mappers.control_plane_op_to_row(record)
    return bool(
        backend.finalize_control_plane_operation_global_row(
            row,
            owner_token=owner_token,
            owner_claimed_at=owner_claimed_at,
            owner_operation_epoch=owner_operation_epoch,
        )
    )


# ---------------------------------------------------------------------------
# Unified inflight-operation-record row API (AG3-140)
#
# The generic in-flight idempotency guard (``inflight_idempotency_guard``) is
# story-agnostic: it consumes/produces plain row dicts in state-backend
# vocabulary (no ``ControlPlaneOperationRecord``, whose ``story_id`` is a
# control-plane-scoped non-null field). These thin wrappers forward a caller-
# built row straight to the same physical ``control_plane_operations`` driver
# functions the record-based control-plane path uses -- ONE record truth, one
# claim/finalize mechanism, without coupling the generic guard to the control-
# plane record type. Release reuses ``release_control_plane_operation_global``.
# ---------------------------------------------------------------------------


def claim_inflight_operation_row_global(row: dict[str, Any]) -> bool:
    """Atomically claim an op_id from a caller-built row (AG3-140).

    Returns ``True`` iff this caller inserted the ``claimed`` placeholder (won the
    claim); ``False`` when the op_id already existed (a concurrent/earlier caller
    owns it or it is terminal). Backed by ``INSERT ... ON CONFLICT DO NOTHING``.
    """
    backend = _backend_module()
    if not hasattr(backend, "claim_control_plane_operation_global_row"):
        raise RuntimeError(
            "Atomic control-plane op claim is unsupported by the active backend",
        )
    return bool(backend.claim_control_plane_operation_global_row(row))


def load_inflight_operation_row_global(op_id: str) -> dict[str, Any] | None:
    """Load the raw inflight-operation-record row for ``op_id``, or ``None`` (AG3-140)."""
    backend = _backend_module()
    if not hasattr(backend, "load_control_plane_operation_global_row"):
        raise RuntimeError(
            _GLOBAL_CP_OP_UNSUPPORTED,
        )
    row = backend.load_control_plane_operation_global_row(op_id)
    return dict(row) if row is not None else None


def finalize_inflight_operation_row_global(
    row: dict[str, Any],
    *,
    owner_token: str,
    owner_claimed_at: str | None = None,
) -> bool:
    """Ownership-scoped terminal write from a caller-built row (AG3-140).

    Writes the terminal ``status`` + ``response_json`` and clears ``claimed_by``
    ONLY when the row is still ``claimed`` by ``owner_token`` (and, when given,
    the same ``owner_claimed_at`` claim generation). Returns ``True`` iff applied.
    """
    backend = _backend_module()
    if not hasattr(backend, "finalize_control_plane_operation_global_row"):
        raise RuntimeError(
            "Control-plane op finalize is unsupported by the active backend",
        )
    return bool(
        backend.finalize_control_plane_operation_global_row(
            row,
            owner_token=owner_token,
            owner_claimed_at=owner_claimed_at,
        )
    )


def finalize_control_plane_start_phase_global(
    record: ControlPlaneOperationRecord,
    *,
    owner_token: str,
    owner_claimed_at: str | None = None,
    owner_operation_epoch: int | None = None,
    binding: SessionRunBindingRecord | None,
    locks: tuple[StoryExecutionLockRecord, ...],
    events: tuple[ExecutionEventRecord, ...],
    ownership_record_to_insert: RunOwnershipRecord | None = None,
    execution_contract_digest_to_insert: ExecutionContractDigestRecord | None = None,
    expected_ownership_epoch: int | None = None,
) -> bool:
    """Atomically CAS-finalize a start_phase and materialize side effects (#1).

    ERROR-1 fix (#1): the ownership CAS finalize of the claimed ``phase_start`` and
    its canonical side effects (session binding, story/QA locks, lifecycle events)
    are applied in ONE store transaction, gated on still owning the claim. A loser
    (its claim was finalized or admin-aborted by a concurrent process, AG3-138)
    writes NOTHING: the CAS affects zero rows and the whole transaction rolls
    back, so no duplicate / conflicting binding / lock / event is materialized.
    Records are converted to rows HERE (mapper boundary); the driver only sees
    row dicts.

    WARNING-4 fix (#4): when ``owner_claimed_at`` (the RAW claim instant the owner
    stamped) is given, the ownership CAS also matches ``claimed_at`` so it scopes
    to THIS claim generation. ``None`` keeps the legacy owner-only CAS.

    AG3-138: when ``owner_operation_epoch`` is given, the CAS additionally
    requires the stored ``operation_epoch`` to be unchanged
    (``operation_finalize_requires_cas_on_operation_epoch`` -- an
    ``admin_abort_inflight_operation`` bumps the epoch, fencing a late
    executor's finalize even when its owner token/claim instant still matches).

    Args:
        record: The terminal control-plane operation record (committed result).
        owner_token: This caller's owner token (the CAS scope).
        owner_claimed_at: This caller's RAW claim instant (CAS generation scope, #4).
        owner_operation_epoch: This caller's observed fencing epoch (AG3-138).
        binding: The session-run-binding to materialize, or ``None`` (fast story).
        locks: The story/QA lock records to materialize (empty for a fast story).
        events: The lifecycle event records to materialize (empty for fast).
        ownership_record_to_insert: (AG3-142, SOLL-015) The NEW active
            ``RunOwnershipRecord`` (``ownership_epoch=1``, ``acquired_via=setup``)
            to INSERT atomically in this SAME transaction -- a genuinely fresh
            setup start only. ``None`` for every other start/resume finalize.
        execution_contract_digest_to_insert: (AG3-143, FK-44 §44.3a) The run's
            NEW ``ExecutionContractDigestRecord`` to INSERT atomically in this
            SAME transaction -- mirrors ``ownership_record_to_insert`` exactly
            (a genuinely fresh setup start only; ``None`` for every other
            start/resume finalize). Read-only after insert: there is no
            update path.
        expected_ownership_epoch: (AG3-142) When given, re-verify at commit
            time, in this SAME transaction, that the story's active ownership
            record still matches this exact ``(record.run_id,
            record.session_id, expected_ownership_epoch)`` snapshot (no
            TOCTOU). Mutually exclusive in practice with
            ``ownership_record_to_insert`` (a fresh setup has nothing yet to
            fence against).

    Returns:
        ``True`` iff this owner finalized and materialized atomically; ``False``
        when the claim was lost (nothing written).

    Raises:
        OwnershipFenceViolationError: (``expected_ownership_epoch`` given) When
            the active ownership record no longer matches this run/session/epoch
            snapshot at commit time; nothing committed (AG3-142).
    """
    backend = _backend_module()
    if not hasattr(backend, "finalize_control_plane_start_phase_global_row"):
        raise RuntimeError(
            "Control-plane start-phase finalize is unsupported by the active backend",
        )
    return bool(
        backend.finalize_control_plane_start_phase_global_row(
            op_row=mappers.control_plane_op_to_row(record),
            owner_token=owner_token,
            owner_claimed_at=owner_claimed_at,
            owner_operation_epoch=owner_operation_epoch,
            binding_row=(
                mappers.session_binding_to_row(binding) if binding is not None else None
            ),
            lock_rows=tuple(mappers.execution_lock_to_row(lock) for lock in locks),
            event_rows=tuple(mappers.execution_event_to_row(event) for event in events),
            ownership_row_to_insert=(
                mappers.run_ownership_to_row(ownership_record_to_insert)
                if ownership_record_to_insert is not None
                else None
            ),
            execution_contract_digest_row_to_insert=(
                mappers.execution_contract_digest_to_row(
                    execution_contract_digest_to_insert
                )
                if execution_contract_digest_to_insert is not None
                else None
            ),
            expected_ownership_epoch=expected_ownership_epoch,
        )
    )


def commit_control_plane_operation_with_side_effects_global(
    record: ControlPlaneOperationRecord,
    *,
    binding_to_save: SessionRunBindingRecord | None,
    binding_to_delete: BindingDeleteScope | None,
    locks: tuple[StoryExecutionLockRecord, ...],
    events: tuple[ExecutionEventRecord, ...],
    expected_ownership_epoch: int | None = None,
) -> None:
    """Atomically commit a terminal op AND its side effects (AG3-054 ERROR-2, #2).

    ERROR-2 fix (#2): the conditional op-row upsert (which refuses to clobber a LIVE
    ``claimed`` start claim and raises :class:`ControlPlaneClaimCollisionError`) and
    the mutation's side effects (session-binding create/delete, story/QA lock
    records, lifecycle events) are applied in ONE store transaction, with the
    collision gate running FIRST. A collision rolls back the WHOLE transaction, so a
    complete/fail/closure that hits a live start's op_id leaves NO orphan binding /
    lock / event and the live claimed row intact (the prior code committed the side
    effects in separate transactions BEFORE the collision was detected). Records are
    converted to rows HERE (mapper boundary); the driver only sees row dicts.

    AG3-054 run-scoping sweep: the binding SAVE and DELETE are RUN-scoped at the
    store. ``binding_to_save`` is upserted only when the session is unbound or
    already bound to the SAME ``(project_key, story_id, run_id)``; ``binding_to_delete``
    removes the binding only when it matches the closing run. A binding that belongs
    to a DIFFERENT run (the session was rebound) is left untouched and raises
    :class:`ControlPlaneBindingCollisionError`, rolling back the whole transaction.

    Args:
        record: The terminal control-plane operation record (committed result).
        binding_to_save: A session-run-binding to run-scoped-upsert, or ``None``
            (the complete/fail standard path materializes one; closure never does).
        binding_to_delete: A run-scoped :class:`BindingDeleteScope` whose binding
            must be removed, or ``None`` (closure removes it; complete/fail never).
        locks: The story/QA lock records to upsert (empty when none apply).
        events: The lifecycle event records to append (empty for none).
        expected_ownership_epoch: (AG3-142) When given, re-verify at commit
            time, in this SAME transaction, that the story's active ownership
            record still matches this exact ``(record.run_id,
            record.session_id, expected_ownership_epoch)`` snapshot (no
            TOCTOU) -- used by ``complete_phase`` / ``fail_phase`` / closure.
            ``None`` (the default) skips the fence entirely -- preserved for
            ``story_split``'s reuse of this same primitive (FK-54 §54.8),
            which is fenced by its OWN entry-gate, not run-ownership.

    Raises:
        ControlPlaneClaimCollisionError: When ``record`` collides with a LIVE
            ``claimed`` row (nothing committed; the live claim is intact).
        ControlPlaneBindingCollisionError: When the binding save/delete would touch
            a FOREIGN run's live binding (nothing committed; the binding intact).
        OwnershipFenceViolationError: (``expected_ownership_epoch`` given) When
            the active ownership record no longer matches this run/session/epoch
            snapshot at commit time; nothing committed (AG3-142).
    """
    backend = _backend_module()
    if not hasattr(
        backend, "commit_control_plane_operation_with_side_effects_global_row"
    ):
        raise RuntimeError(
            "Atomic control-plane mutation commit is unsupported by the active backend",
        )
    backend.commit_control_plane_operation_with_side_effects_global_row(
        op_row=mappers.control_plane_op_to_row(record),
        binding_to_save=(
            mappers.session_binding_to_row(binding_to_save)
            if binding_to_save is not None
            else None
        ),
        binding_to_delete=(
            {
                "session_id": binding_to_delete.session_id,
                "project_key": binding_to_delete.project_key,
                "story_id": binding_to_delete.story_id,
                "run_id": binding_to_delete.run_id,
            }
            if binding_to_delete is not None
            else None
        ),
        expected_ownership_epoch=expected_ownership_epoch,
        lock_rows=tuple(mappers.execution_lock_to_row(lock) for lock in locks),
        event_rows=tuple(mappers.execution_event_to_row(event) for event in events),
    )


def release_control_plane_operation_global(
    op_id: str,
    *,
    owner_token: str,
    owner_claimed_at: str | None = None,
) -> None:
    """Ownership-scoped release of a claimed control-plane op (AG3-054 owner-scoped claim).

    Deletes the row ONLY when it is still ``claimed`` by ``owner_token``. NEVER an
    unconditional delete: a terminal row or another owner's claim is left intact.
    Idempotent.

    WARNING-4 fix (#4): when ``owner_claimed_at`` (the RAW claim instant the owner
    stamped) is given, the delete CAS also matches ``claimed_at`` so it scopes to
    THIS claim generation -- a stale owner (a reused token in DI/test wiring)
    cannot delete a NEWER claim. ``None`` keeps the legacy owner-only CAS.
    """
    backend = _backend_module()
    if not hasattr(backend, "release_control_plane_operation_global_row"):
        raise RuntimeError(
            "Control-plane op release is unsupported by the active backend",
        )
    backend.release_control_plane_operation_global_row(
        op_id, owner_token=owner_token, owner_claimed_at=owner_claimed_at
    )


# ---------------------------------------------------------------------------
# Startup reconciliation / admin-abort (AG3-138)
# ---------------------------------------------------------------------------


def list_orphaned_claimed_control_plane_operations_global(
    backend_instance_id: str,
    before_incarnation: int,
) -> tuple[ControlPlaneOperationRecord, ...]:
    """List claimed operations orphaned by EARLIER incarnations of THIS instance.

    Startup reconciliation (AG3-138): only claims stamped with the CALLING
    instance's own ``backend_instance_id`` from a strictly earlier
    ``instance_incarnation`` are returned -- never a foreign identity.
    """
    _require_control_plane_backend()
    backend = _backend_module()
    rows = backend.list_orphaned_claimed_control_plane_operations_global_row(
        backend_instance_id=backend_instance_id,
        before_incarnation=before_incarnation,
    )
    return tuple(mappers.control_plane_op_row_to_record(row) for row in rows)


def finalize_orphaned_control_plane_operation_global(
    *,
    op_id: str,
    backend_instance_id: str,
    status: str,
    response_payload: dict[str, object],
    now: datetime,
    owner_operation_epoch: int,
) -> bool:
    """CAS-finalize one orphaned claim during startup reconciliation (AG3-138).

    Fail-closed identity fence at the store: the CAS additionally matches
    ``backend_instance_id`` -- a claim whose identity is not the caller's own is
    never touched by this call. ``owner_operation_epoch`` (the ``operation_epoch``
    observed by the orphan scan) is MANDATORY and additionally fences the finalize on
    that epoch (AC4), so a row whose epoch moved between scan and finalize -- or a
    malformed ``NULL``-epoch row -- is left untouched
    (``operation_finalize_requires_cas_on_operation_epoch``). There is no identity-only
    (epoch-less) finalize path.
    """
    _require_control_plane_backend()
    backend = _backend_module()
    return bool(
        backend.finalize_orphaned_control_plane_operation_global_row(
            op_id=op_id,
            backend_instance_id=backend_instance_id,
            status=status,
            response_json=mappers.dump_json(response_payload),
            now=now.isoformat(),
            owner_operation_epoch=owner_operation_epoch,
        )
    )


def admin_abort_control_plane_operation_global(
    *,
    op_id: str,
    status: str,
    response_payload: dict[str, object],
    now: datetime,
) -> bool:
    """CAS-abort one in-flight claim via the admin-abort service path (AG3-138).

    Acts on ANY currently-``claimed`` operation (an explicit administrative
    override, FK-91 §91.1a ``admin_abort_inflight_operation``). Returns
    ``False`` when the row is no longer ``claimed`` (already resolved).
    """
    _require_control_plane_backend()
    backend = _backend_module()
    return bool(
        backend.admin_abort_control_plane_operation_global_row(
            op_id=op_id,
            status=status,
            response_json=mappers.dump_json(response_payload),
            now=now.isoformat(),
        )
    )


def resolve_repair_control_plane_operation_global(
    *,
    op_id: str,
    response_payload: dict[str, object],
    now: datetime,
) -> bool:
    """CAS-resolve one open ``repair`` operation to ``resolved`` (AG3-138, AC10).

    The productive end-way out of the repair mutation lock: transitions a
    ``status = 'repair'`` row to ``resolved`` so the story-scoped lock lifts. Returns
    ``False`` (caller surfaces 409) when the row is not currently in ``repair``.
    """
    _require_control_plane_backend()
    backend = _backend_module()
    return bool(
        backend.resolve_repair_control_plane_operation_global_row(
            op_id=op_id,
            response_json=mappers.dump_json(response_payload),
            now=now.isoformat(),
        )
    )


def has_engine_writes_since_control_plane_claim_global(
    story_id: str,
    since: datetime,
) -> bool:
    """Whether the engine persisted partial writes under a specific claim window.

    Deterministic partial-write detection (AG3-138, IMPL-005): compares ALREADY
    RECORDED timestamps against ``since`` (the claim's own ``claimed_at``) -- never
    the current wall clock. The detection is bound to the concrete operation through
    its claim window (``since``), not a ``run_id`` column: the engine persists an
    engine-internal ``flow_executions.run_id`` distinct from the control-plane
    operation ``run_id``, and ``phase_states`` has no ``run_id`` column, so the claim
    window is the sound operation-binding for both engine tables (see the row-level
    function for the full rationale).
    """
    _require_control_plane_backend()
    backend = _backend_module()
    return bool(
        backend.has_engine_writes_since_control_plane_claim_global_row(
            story_id=story_id,
            since=since.isoformat(),
        )
    )


def has_open_repair_control_plane_operation_for_story_global(
    project_key: str,
    story_id: str,
) -> bool:
    """Whether *story_id* has an open (unresolved) reconcile/repair state.

    Backs the AC10 fail-closed mutation lock at the dispatch-/operations-layer.
    """
    _require_control_plane_backend()
    backend = _backend_module()
    return bool(
        backend.has_open_repair_control_plane_operation_for_story_global_row(
            project_key=project_key,
            story_id=story_id,
        )
    )


def has_committed_control_plane_operation_for_run_global(
    project_key: str,
    story_id: str,
    run_id: str,
) -> bool:
    """Whether a committed control-plane op exists for THIS run (AG3-054 #3).

    Run-scoped admission evidence for complete/fail/closure: a prior COMMITTED
    op whose ``run_id`` matches this exact run.
    """
    backend = _backend_module()
    if not hasattr(
        backend, "has_committed_control_plane_operation_for_run_global_row"
    ):
        raise RuntimeError(
            "Control-plane run-admission probe is unsupported by the active backend",
        )
    return bool(
        backend.has_committed_control_plane_operation_for_run_global_row(
            project_key,
            story_id,
            run_id,
        )
    )


def has_committed_story_exit_operation_for_run_global(
    project_key: str,
    story_id: str,
    run_id: str,
) -> bool:
    """Whether a committed story-exit terminal marker exists for THIS run."""

    backend = _backend_module()
    if not hasattr(
        backend, "has_committed_story_exit_operation_for_run_global_row"
    ):
        raise RuntimeError(
            "Control-plane story-exit terminal probe is unsupported by the active "
            "backend"
        )
    return bool(
        backend.has_committed_story_exit_operation_for_run_global_row(
            project_key,
            story_id,
            run_id,
        )
    )


def delete_control_plane_operation_global(op_id: str) -> None:
    """Unconditional delete of a control-plane op row (administrative recovery).

    Deletes the op row by ``op_id`` regardless of ownership/status. The PRODUCTIVE
    release path is :func:`release_control_plane_operation_global` (ownership-
    scoped). Idempotent: deleting an absent op_id is a no-op.
    """
    backend = _backend_module()
    if not hasattr(backend, "delete_control_plane_operation_global_row"):
        raise RuntimeError(
            "Control-plane op deletion is unsupported by the active backend",
        )
    backend.delete_control_plane_operation_global_row(op_id)


def load_control_plane_operation_global(
    op_id: str,
) -> ControlPlaneOperationRecord | None:
    backend = _backend_module()
    if not hasattr(backend, "load_control_plane_operation_global_row"):
        raise RuntimeError(
            _GLOBAL_CP_OP_UNSUPPORTED,
        )
    row = backend.load_control_plane_operation_global_row(op_id)
    if row is None:
        return None
    return mappers.control_plane_op_row_to_record(row)


# ---------------------------------------------------------------------------
# FlowExecution
# ---------------------------------------------------------------------------


def save_flow_execution(story_dir: Path, record: FlowExecution) -> None:
    row = mappers.flow_execution_to_row(record)
    _backend_module().save_flow_execution_row(story_dir, row)


def load_flow_execution(story_dir: Path) -> FlowExecution | None:
    row = _backend_module().load_flow_execution_row(story_dir)
    if row is None:
        return None
    return mappers.flow_execution_row_to_record(row)


def load_flow_execution_global(
    project_key: str,
    story_id: str,
) -> FlowExecution | None:
    backend = _backend_module()
    if not hasattr(backend, "load_flow_execution_global_row"):
        raise RuntimeError(
            "Global flow-execution reads are unsupported by the active backend",
        )
    row = backend.load_flow_execution_global_row(project_key, story_id)
    if row is None:
        return None
    return mappers.flow_execution_row_to_record(row)


# ---------------------------------------------------------------------------
# NodeExecutionLedger
# ---------------------------------------------------------------------------


def save_node_execution_ledger(story_dir: Path, record: NodeExecutionLedger) -> None:
    row = mappers.node_ledger_to_row(record)
    _backend_module().save_node_execution_ledger_row(story_dir, row)


def load_node_execution_ledger(
    story_dir: Path,
    flow_id: str,
    node_id: str,
) -> NodeExecutionLedger | None:
    row = _backend_module().load_node_execution_ledger_row(story_dir, flow_id, node_id)
    if row is None:
        return None
    return mappers.node_ledger_row_to_record(row)


# ---------------------------------------------------------------------------
# OverrideRecord
# ---------------------------------------------------------------------------


def save_override_record(story_dir: Path, record: OverrideRecord) -> None:
    row = mappers.override_record_to_row(record)
    _backend_module().save_override_record_row(story_dir, row)


def load_override_records(story_dir: Path) -> list[OverrideRecord]:
    rows = _backend_module().load_override_record_rows(story_dir)
    return [mappers.override_row_to_record(row) for row in rows]


# ---------------------------------------------------------------------------
# Runtime-Execution per-owner purge (AG3-109, FK-53 §53.7.5)
# ---------------------------------------------------------------------------
#
# Owner-purge APIs for the Runtime-Execution core entities. SQL lives in the
# driver helper (``sqlite_store`` / ``postgres_store``); this facade is the
# canonical owner surface (next to ``save_*``/``load_*``). The coordinating
# ``RuntimeExecutionPurgePort`` calls THESE APIs — it issues no cross-BC SQL of
# its own (no God-Purge). Each call is idempotent (FK-53 §53.9.1).
#
# Physical §1.3 mapping (code is ground truth; phantom tables ``attempt_records``
# / ``node_executions`` / ``artifact_records`` are NEVER referenced). Canonical
# ``phase_states`` is purged here; the read-model ``phase_state_projection`` is
# out of scope (its own ``purge_run`` lives in ``projection_repositories``).
# Second-QA closure (2026-06-12): ``phase_snapshots`` and ``decision_records``
# are story-keyed runtime companions of §53.6.2 PhaseState / governance runtime
# and are purged too — leftover snapshots/verify decisions would influence a
# later restart/guard decision via story-keyed reads (§53.7.5 rule).


def purge_flow_executions(
    story_dir: Path, project_key: str, story_id: str, run_id: str
) -> int:
    """Delete flow_executions rows for the run scope; return deleted row count."""

    return int(
        _backend_module().purge_flow_executions_row(
            story_dir, project_key, story_id, run_id
        )
    )


def purge_node_execution_ledgers(
    story_dir: Path, project_key: str, story_id: str, run_id: str
) -> int:
    """Delete node_execution_ledgers rows for the run scope; return row count."""

    return int(
        _backend_module().purge_node_execution_ledgers_row(
            story_dir, project_key, story_id, run_id
        )
    )


def purge_attempts(story_dir: Path, story_id: str, run_id: str) -> int:
    """Delete attempts rows for (story_id, run_id); return deleted row count.

    The ``attempts`` table has no ``project_key`` column; project scope is
    validated at the coordinating port, not implied here.
    """

    return int(_backend_module().purge_attempts_row(story_dir, story_id, run_id))


def purge_override_records(
    story_dir: Path, project_key: str, story_id: str, run_id: str
) -> int:
    """Delete override_records rows for the run scope; return deleted row count."""

    return int(
        _backend_module().purge_override_records_row(
            story_dir, project_key, story_id, run_id
        )
    )


def purge_guard_decisions(
    story_dir: Path, project_key: str, story_id: str, run_id: str
) -> int:
    """Delete guard_decisions rows for the run scope; return deleted row count."""

    return int(
        _backend_module().purge_guard_decisions_row(
            story_dir, project_key, story_id, run_id
        )
    )


def purge_phase_states(story_dir: Path, story_id: str) -> int:
    """Delete the canonical phase_states row for story_id; return row count.

    Purges the canonical runtime PhaseState (keyed by ``story_id`` only), NOT the
    FK-39 read-model ``phase_state_projection`` (out of scope).
    """

    return int(_backend_module().purge_phase_states_row(story_dir, story_id))


def purge_phase_snapshots(story_dir: Path, story_id: str) -> int:
    """Delete all phase_snapshots rows for story_id; return deleted row count.

    Completed-phase snapshots are runtime PhaseState evidence keyed by
    ``(story_id, phase)`` — no ``run_id`` column. They feed guard/gate decisions
    story-keyed (``backend_has_completed_snapshot`` -> Integrity-Gate Dim 2), so
    a purged run's leftover snapshot would influence a later restart/guard
    decision (FK-53 §53.7.5 rule). Purged for the whole story.
    """

    return int(_backend_module().purge_phase_snapshots_row(story_dir, story_id))


def purge_decision_records(story_dir: Path, story_id: str) -> int:
    """Delete all decision_records rows for story_id; return deleted row count.

    Canonical verify decisions (governance runtime residue, FK-53 §53.7.5) are
    keyed ``(story_id, decision_kind, attempt_nr)`` in the canonical SQLite
    schema — attempt numbering restarts per run, and ``load_latest_verify_decision``
    selects ``MAX(attempt_nr)`` story-wide (Postgres falls back story-wide), so a
    purged run's leftover decision would SHADOW the next run's verify decision in
    the Integrity Gate. Purged for the whole story.
    """

    return int(_backend_module().purge_decision_records_row(story_dir, story_id))


def purge_execution_events(
    story_dir: Path, project_key: str, story_id: str, run_id: str
) -> int:
    """Delete execution_events rows for the run scope; return deleted row count."""

    return int(
        _backend_module().purge_execution_events_row(
            story_dir, project_key, story_id, run_id
        )
    )


def purge_run_bound_artifact_envelopes(
    story_dir: Path, story_id: str, run_id: str
) -> int:
    """Delete run-bound artifact_envelopes rows for (story_id, run_id).

    ``artifact_envelopes`` has no ``project_key`` column; every row is run-bound
    via ``run_id``. Other-run (across-run/durable) rows are left intact.
    """

    return int(
        _backend_module().purge_run_bound_artifact_envelopes_row(
            story_dir, story_id, run_id
        )
    )


def count_runtime_execution_residue(
    story_dir: Path, project_key: str, story_id: str, run_id: str
) -> dict[str, int]:
    """Return remaining Runtime-Execution rows per table for the run scope.

    Building block for the Runtime-Residue verify (FK-53 §53.7.5 / §53.10
    fragment); a non-zero count for any table means residue survived a purge.

    Fail-closed scoping: the residue COUNT is deliberately ``project_key``-
    agnostic (run-bound tables are counted by ``(story_id, run_id)``, the
    story-keyed tables by ``story_id``). The destructive purge keeps its narrow
    ``project_key`` predicate; a mis-scoped purge call (wrong-but-non-empty
    ``project_key``) therefore shows up HERE as residue instead of both sides
    sharing the same blind spot. ``project_key`` stays validated at the port.
    """

    return dict(
        _backend_module().count_runtime_execution_residue_row(
            story_dir, project_key, story_id, run_id
        )
    )


# ---------------------------------------------------------------------------
# StoryMetricsRecord
# ---------------------------------------------------------------------------


def upsert_story_metrics(story_dir: Path, metrics: StoryMetricsRecord) -> None:
    row = mappers.story_metrics_to_row(metrics)
    _backend_module().upsert_story_metrics_row(story_dir, row)


def load_story_metrics(
    story_dir: Path,
    *,
    project_key: str | None = None,
    story_id: str | None = None,
    run_id: str | None = None,
) -> list[StoryMetricsRecord]:
    rows = _backend_module().load_story_metrics_rows(
        story_dir,
        project_key=project_key,
        story_id=story_id,
        run_id=run_id,
    )
    return [mappers.story_metrics_row_to_record(row) for row in rows]


def load_story_metrics_for_scope(
    scope: RuntimeStateScope,
) -> list[StoryMetricsRecord]:
    return load_story_metrics(
        scope.story_dir,
        project_key=scope.project_key,
        story_id=scope.story_id,
        run_id=scope.run_id,
    )


def load_latest_story_metrics_global(
    project_key: str,
    story_id: str,
    store_dir: Path | None = None,
) -> StoryMetricsRecord | None:
    backend = _backend_module()
    if not hasattr(backend, "load_latest_story_metrics_global_row"):
        raise RuntimeError(
            "Global story-metrics reads are unsupported by the active backend",
        )
    row = backend.load_latest_story_metrics_global_row(store_dir, project_key, story_id)
    if row is None:
        return None
    return mappers.story_metrics_row_to_record(row)


# ---------------------------------------------------------------------------
# QA layer artifacts + verify decision
# ---------------------------------------------------------------------------


def record_layer_artifacts(
    story_dir: Path,
    *,
    layer_results: tuple[LayerResult, ...],
    attempt_nr: int,
    owner_session_id: str,
    expected_ownership_epoch: int,
    projection_dir: Path | None = None,
) -> tuple[str, ...]:
    """Serialize QA layer results and persist projection + FK-69 rows.

    Mapper converts BC-typed ``LayerResult`` objects to plain dicts;
    driver performs only SQL and filesystem I/O. ``artifact_envelopes``
    writes are owned by ``verify_system.artifacts`` — this facade does
    not know about ArtifactManager (no state_backend -> verify_system
    import).

    Args:
        owner_session_id: (AG3-144, FK-91 §91.1a Rule 15) The caller's
            early-captured active ``run_ownership_records.owner_session_id``
            (mirrors the AG3-142 regime-commit pattern). Re-verified at commit
            time, in the SAME transaction, under ``SELECT ... FOR UPDATE``.
        expected_ownership_epoch: The caller's early-captured
            ``ownership_epoch`` snapshot, re-verified the same way.

    Raises:
        OwnershipFenceViolationError: (AG3-142 reuse) When the story's active
            ownership record no longer admits this exact snapshot at commit
            time -- nothing written (no projection file, no QA rows).
    """
    from datetime import datetime

    from agentkit.backend.boundary.shared.time import now_iso
    from agentkit.backend.core_types.qa_artifact_names import LAYER_ARTIFACT_FILES

    # Need flow_row for FK-69 QA materialization (Postgres-specific)
    flow_row = _backend_module().load_flow_execution_row(story_dir)

    layer_payload_rows: list[dict[str, object]] = []
    for layer_result in layer_results:
        artifact_name = LAYER_ARTIFACT_FILES.get(layer_result.layer)
        if artifact_name is None:
            continue
        payload = mappers.serialize_layer_result_to_dict(
            layer_result,
            attempt_nr=attempt_nr,
        )
        producer_component = mappers.get_producer_component_for_layer(layer_result.layer)
        recorded_at = datetime.fromisoformat(now_iso())

        stage_row: dict[str, object] | None = None
        finding_rows: list[dict[str, object]] = []
        if flow_row is not None:
            stage_row = mappers.build_qa_stage_result_row(
                flow_row,
                layer_result,
                attempt_no=attempt_nr,
                artifact_id="",  # placeholder; driver replaces with real artifact_id
                recorded_at=recorded_at,
            )
            finding_rows = mappers.build_qa_finding_rows(
                flow_row,
                layer_result,
                attempt_no=attempt_nr,
                artifact_id="",  # placeholder
                recorded_at=recorded_at,
            )

        layer_payload_rows.append(
            {
                "layer": layer_result.layer,
                "artifact_name": artifact_name,
                "producer_component": producer_component,
                "payload": payload,
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


def record_verify_decision(
    story_dir: Path,
    *,
    decision: VerifyDecision,
    attempt_nr: int,
    owner_session_id: str,
    expected_ownership_epoch: int,
    projection_dir: Path | None = None,
) -> tuple[str, ...]:
    """Serialize a verify decision and persist via driver.

    Args:
        owner_session_id: (AG3-144, FK-91 §91.1a Rule 15) The caller's
            early-captured active ``run_ownership_records.owner_session_id``.
            Re-verified at commit time under ``SELECT ... FOR UPDATE``.
        expected_ownership_epoch: The caller's early-captured
            ``ownership_epoch`` snapshot, re-verified the same way.

    Raises:
        OwnershipFenceViolationError: (AG3-142 reuse) When the story's active
            ownership record no longer admits this exact snapshot at commit
            time -- nothing written.
    """

    canonical_payload = mappers.build_verify_decision_dict(
        decision,
        attempt_nr=attempt_nr,
    )
    flow_row = _backend_module().load_flow_execution_row(story_dir)
    return cast(
        "tuple[str, ...]",
        _backend_module().persist_verify_decision_row(
            story_dir,
            flow_row=flow_row,
            decision_row={
                "status": decision.status,
                "passed": decision.passed,
                "summary": decision.summary,
            },
            canonical_payload=canonical_payload,
            attempt_nr=attempt_nr,
            owner_session_id=owner_session_id,
            expected_ownership_epoch=expected_ownership_epoch,
            projection_dir=projection_dir,
        ),
    )


def load_latest_verify_decision(
    story_dir: Path,
) -> JsonRecord | None:
    return _cast_json_record(_backend_module().load_latest_verify_decision_payload(story_dir))


def load_latest_verify_decision_for_scope(
    scope: RuntimeStateScope,
) -> JsonRecord | None:
    return _cast_json_record(
        _backend_module().load_latest_verify_decision_payload_for_scope(scope),
    )


def read_latest_verify_decision_record(
    story_dir: Path,
) -> JsonRecord | None:
    return load_latest_verify_decision(story_dir)


def find_latest_qa_envelope(
    story_dir: Path,
    scope: RuntimeStateScope | None,
    stage: str,
) -> object | None:
    """Return the highest-attempt canonical QA ``ArtifactEnvelope`` for a stage.

    The canonical QA-artefact truth lives in ``artifact_envelopes``
    (``ArtifactClass.QA``); this resolves the latest envelope for one QA layer
    stage (e.g. ``qa-layer-structural`` / ``qa-policy-decision`` /
    ``qa-layer-adversarial``) so the IntegrityGate dimensions (FK-35 §35.2.4)
    can verify producer / status / payload depth against the real artefact.

    Args:
        story_dir: Story base directory (used to resolve the story_id/run_id
            when ``scope`` is ``None``).
        scope: Resolved runtime scope (narrows to one run_id when present).
        stage: The QA layer stage id.

    Returns:
        The latest :class:`ArtifactEnvelope` (typed ``object`` to keep the
        facade import-light), or ``None`` when absent.
    """
    from agentkit.backend.core_types import ArtifactClass
    from agentkit.backend.state_backend.store.artifact_repository import (
        StateBackendArtifactRepository,
    )

    if scope is not None:
        story_id, run_id = scope.story_id, scope.run_id
    else:
        try:
            resolved = resolve_runtime_scope(story_dir)
        except CorruptStateError:
            return None
        story_id, run_id = resolved.story_id, resolved.run_id
    repository = StateBackendArtifactRepository(story_dir)
    return repository.find_latest_envelope(
        story_id=story_id,
        run_id=run_id,
        artifact_class=ArtifactClass.QA,
        stage=stage,
    )


def find_prompt_audit_output_hashes(
    story_dir: Path,
    scope: RuntimeStateScope | None,
) -> frozenset[str]:
    """Return all prompt-audit ``output_sha256`` digests for the run scope.

    The canonical prompt-audit truth lives in ``artifact_envelopes``
    (``ArtifactClass.PROMPT_AUDIT``, FK-44 §44.6). Each record carries
    ``output_sha256`` -- the digest of the exact materialized prompt bytes,
    rendered from a manifest-pinned bundle template. The set of these digests is
    the FK-31 §31.7.4 Stage-3 baseline for the PromptIntegrityGuard: it is
    install-pinned, NOT spawn-controlled.

    Args:
        story_dir: Story base directory (used to resolve the story_id/run_id
            when ``scope`` is ``None``).
        scope: Resolved runtime scope (narrows to one run_id when present).

    Returns:
        The frozenset of all ``output_sha256`` digests for the (story, run)
        scope (empty when none materialized or the scope is unresolvable).
    """
    from agentkit.backend.state_backend.store.artifact_repository import (
        StateBackendArtifactRepository,
    )

    if scope is not None:
        story_id, run_id = scope.story_id, scope.run_id
    else:
        try:
            resolved = resolve_runtime_scope(story_dir)
        except CorruptStateError:
            return frozenset()
        story_id, run_id = resolved.story_id, resolved.run_id
    if not run_id:
        return frozenset()
    repository = StateBackendArtifactRepository(story_dir)
    return repository.find_prompt_audit_output_hashes(
        story_id=story_id,
        run_id=run_id,
    )


# ---------------------------------------------------------------------------
# Artifact records (raw JSON payload reads)
# ---------------------------------------------------------------------------


def load_artifact_record(
    story_dir: Path,
    artifact_kind: str,
) -> JsonRecord | None:
    return _cast_json_record(
        _backend_module().load_artifact_record_payload(story_dir, artifact_kind),
    )


def load_artifact_record_for_scope(
    scope: RuntimeStateScope,
    artifact_kind: str,
) -> JsonRecord | None:
    return _cast_json_record(
        _backend_module().load_artifact_record_payload_for_scope(scope, artifact_kind),
    )


def read_artifact_record(
    story_dir: Path,
    artifact_kind: str,
) -> JsonRecord | None:
    return load_artifact_record(story_dir, artifact_kind)


# ---------------------------------------------------------------------------
# Closure report
# ---------------------------------------------------------------------------


def record_closure_report(
    story_dir: Path,
    report: ExecutionReport,
    *,
    owner_session_id: str,
    expected_ownership_epoch: int,
    projection_dir: Path | None = None,
) -> Path:
    """Persist the closure report and its export projection.

    Args:
        owner_session_id: (AG3-144, FK-91 §91.1a Rule 15) The caller's
            early-captured active ``run_ownership_records.owner_session_id``.
            Re-verified at commit time under ``SELECT ... FOR UPDATE``.
        expected_ownership_epoch: The caller's early-captured
            ``ownership_epoch`` snapshot, re-verified the same way.

    Raises:
        OwnershipFenceViolationError: (AG3-142 reuse) When the story's active
            ownership record no longer admits this exact snapshot at commit
            time -- nothing written.
    """
    flow_row = _backend_module().load_flow_execution_row(story_dir)
    payload = report.to_dict()
    return cast(
        "Path",
        _backend_module().persist_closure_report_row(
            story_dir,
            flow_row=flow_row,
            report_row={
                "story_id": getattr(report, "story_id", story_dir.name),
                "status": report.status,
                "payload": payload,
            },
            owner_session_id=owner_session_id,
            expected_ownership_epoch=expected_ownership_epoch,
            projection_dir=projection_dir,
        ),
    )


# ---------------------------------------------------------------------------
# QAStageResultRecord / QAFindingRecord
# ---------------------------------------------------------------------------


def load_qa_stage_results(
    story_dir: Path,
    *,
    project_key: str | None = None,
    story_id: str | None = None,
    run_id: str | None = None,
    attempt_no: int | None = None,
    stage_id: str | None = None,
) -> list[QAStageResultRecord]:
    rows = _backend_module().load_qa_stage_result_rows(
        story_dir,
        project_key=project_key,
        story_id=story_id,
        run_id=run_id,
        attempt_no=attempt_no,
        stage_id=stage_id,
    )
    return [mappers.qa_stage_result_row_to_record(row) for row in rows]


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
    rows = _backend_module().load_qa_finding_rows(
        story_dir,
        project_key=project_key,
        story_id=story_id,
        run_id=run_id,
        attempt_no=attempt_no,
        stage_id=stage_id,
    )
    return [mappers.qa_finding_row_to_record(row) for row in rows]


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


# ---------------------------------------------------------------------------
# Backend predicate helpers
# ---------------------------------------------------------------------------


def backend_has_valid_context(story_dir: Path) -> bool:
    return load_story_context(story_dir) is not None


def backend_has_valid_phase_state(story_dir: Path) -> bool:
    return load_phase_state(story_dir) is not None


def backend_has_completed_snapshot(story_dir: Path, phase: str) -> bool:
    snapshot = load_phase_snapshot(story_dir, phase)
    return snapshot is not None and mappers.phase_snapshot_completed(snapshot)


def backend_has_structural_artifact(story_dir: Path) -> bool:
    record = load_artifact_record(story_dir, "structural")
    return record is not None


def backend_has_structural_artifact_for_scope(scope: RuntimeStateScope) -> bool:
    return backend_has_structural_artifact(scope.story_dir)


def backend_verify_decision_passed(story_dir: Path) -> bool:
    payload = load_latest_verify_decision(story_dir)
    if payload is None:
        return False
    status = payload.get("status")
    return (
        isinstance(status, str)
        and bool(payload.get("passed"))
        and status == "PASS"
    )


def backend_verify_decision_passed_for_scope(scope: RuntimeStateScope) -> bool:
    return backend_verify_decision_passed(scope.story_dir)
