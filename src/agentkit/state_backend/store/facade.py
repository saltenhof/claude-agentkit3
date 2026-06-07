"""Repository facade: selects the configured driver and applies mappers.

This module provides the canonical public API for state persistence.
All BC-Record <-> dict-row conversions happen here via ``mappers``.
Drivers (postgres_store, sqlite_store) only handle raw ``dict[str, Any]`` rows.
"""

from __future__ import annotations

from functools import lru_cache
from typing import TYPE_CHECKING, cast

from agentkit.exceptions import CorruptStateError
from agentkit.state_backend.config import (
    StateBackendKind,
    load_state_backend_config,
)
from agentkit.state_backend.scope import (
    RuntimeStateScope,
    runtime_scope_from_state,
    scope_from_story_context,
)
from agentkit.state_backend.store import mappers

if TYPE_CHECKING:
    from pathlib import Path
    from types import ModuleType
    from uuid import UUID

    from agentkit.auth.entities import ProjectApiToken
    from agentkit.closure.execution_report.records import ExecutionReport
    from agentkit.closure.post_merge_finalization.records import StoryMetricsRecord
    from agentkit.control_plane.records import (
        BindingDeleteScope,
        ControlPlaneOperationRecord,
        SessionRunBindingRecord,
    )
    from agentkit.execution_planning.entities import (
        ParallelizationConfig,
        StoryDependency,
        StoryDependencyKind,
    )
    from agentkit.governance.guard_system.records import StoryExecutionLockRecord
    from agentkit.phase_state_store.models import (
        FlowExecution,
        NodeExecutionLedger,
        OverrideRecord,
    )
    from agentkit.pipeline_engine.phase_executor.records import AttemptRecord
    from agentkit.project_management.entities import Project
    from agentkit.requirements_coverage.models import (
        StoryAreLink,
        StoryAreLinkKind,
    )
    from agentkit.story_context_manager.models import (
        PhaseSnapshot,
        PhaseState,
        StoryContext,
    )
    from agentkit.telemetry.contract.records import ExecutionEventRecord
    from agentkit.verify_system.policy_engine.engine import VerifyDecision
    from agentkit.verify_system.protocols import LayerResult
    from agentkit.verify_system.stage_registry.records import (
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
        from agentkit.state_backend import sqlite_store

        return sqlite_store

    from agentkit.state_backend import postgres_store

    return postgres_store


def reset_backend_cache_for_tests() -> None:
    """Clear cached backend selection for test-time env switching."""

    _backend_module.cache_clear()


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

    Fail-closed: invalide DB-Zeilen (CHECK-Constraint-Drift,
    Schema-Mismatch zwischen Backend und Mapper, korrupte JSON-Payloads)
    propagieren ``pydantic.ValidationError`` / ``ValueError`` an den
    Aufrufer. Frueher hat ein ``except`` defective rows still
    geschluckt — das maskierte echte Inkonsistenzen
    (vgl. AG3-025 Re-Review Befund 1).
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
) -> list[ExecutionEventRecord]:
    rows = _backend_module().load_execution_event_rows(
        story_dir,
        project_key=project_key,
        story_id=story_id,
        run_id=run_id,
        event_type=event_type,
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


def save_control_plane_operation_global(
    record: ControlPlaneOperationRecord,
) -> None:
    backend = _backend_module()
    if not hasattr(backend, "save_control_plane_operation_global_row"):
        raise RuntimeError(
            "Global control-plane operations are unsupported by the active backend",
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


def takeover_control_plane_operation_global(
    record: ControlPlaneOperationRecord,
    *,
    observed_claimed_by: str | None,
    observed_claimed_at: str | None,
) -> bool:
    """CAS-take over an EXPIRED claim (AG3-054 leased claim).

    Re-stamps the lease to ``record``'s owner ONLY if the row is still the exact
    ``claimed`` placeholder observed (same owner + lease instant). Returns ``True``
    iff this caller took over the expired claim; ``False`` when a concurrent
    winner already changed the row (the caller then loses the takeover race).

    ERROR-2 fix (AG3-054): ``observed_claimed_at`` is the RAW stored ``claimed_at``
    column TEXT (``ControlPlaneOperationRecord.claimed_at_raw``), passed through
    UNCHANGED so the CAS matches the raw column like-for-like. It is NOT the
    normalized aware instant: a naive/legacy/malformed row (e.g. stored as
    ``'2026-06-07T09:00:00'`` without offset) would otherwise never CAS-match the
    normalized ``'...+00:00'`` value and the op_id would be permanently poisoned.
    """
    backend = _backend_module()
    if not hasattr(backend, "takeover_control_plane_operation_global_row"):
        raise RuntimeError(
            "Control-plane op takeover is unsupported by the active backend",
        )
    row = mappers.control_plane_op_to_row(record)
    return bool(
        backend.takeover_control_plane_operation_global_row(
            row,
            observed_claimed_by=observed_claimed_by,
            observed_claimed_at=observed_claimed_at,
        )
    )


def finalize_control_plane_operation_global(
    record: ControlPlaneOperationRecord,
    *,
    owner_token: str,
    owner_claimed_at: str | None = None,
) -> bool:
    """Ownership-scoped terminal write of a claimed op (AG3-054 leased claim).

    Writes the terminal result + clears ``claimed_by`` ONLY when the row is still
    ``claimed`` by ``owner_token``. Returns ``True`` iff this owner's terminal
    write applied; ``False`` when another owner finalized/took over in between (the
    caller must then replay/reject, never overwrite).

    WARNING-4 fix (#4): when ``owner_claimed_at`` (the RAW lease epoch the owner
    stamped) is given, the CAS also matches ``claimed_at`` so it scopes to THIS
    lease generation -- a stale owner whose token is reused or after an
    expiry-takeover cannot match a NEWER lease. ``None`` keeps the legacy
    owner-only CAS (direct administrative callers).
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
        )
    )


def finalize_control_plane_start_phase_global(
    record: ControlPlaneOperationRecord,
    *,
    owner_token: str,
    owner_claimed_at: str | None = None,
    binding: SessionRunBindingRecord | None,
    locks: tuple[StoryExecutionLockRecord, ...],
    events: tuple[ExecutionEventRecord, ...],
) -> bool:
    """Atomically CAS-finalize a start_phase and materialize side effects (#1).

    ERROR-1 fix (#1): the ownership CAS finalize of the claimed ``phase_start`` and
    its canonical side effects (session binding, story/QA locks, lifecycle events)
    are applied in ONE store transaction, gated on still owning the claim. A loser
    (its lease expired and was taken over + finalized by a concurrent owner) writes
    NOTHING: the CAS affects zero rows and the whole transaction rolls back, so no
    duplicate / conflicting binding / lock / event is materialized. Records are
    converted to rows HERE (mapper boundary); the driver only sees row dicts.

    WARNING-4 fix (#4): when ``owner_claimed_at`` (the RAW lease epoch the owner
    stamped) is given, the ownership CAS also matches ``claimed_at`` so it scopes
    to THIS lease generation. ``None`` keeps the legacy owner-only CAS.

    Args:
        record: The terminal control-plane operation record (committed result).
        owner_token: This caller's lease owner token (the CAS scope).
        owner_claimed_at: This caller's RAW lease epoch (CAS epoch scope, #4).
        binding: The session-run-binding to materialize, or ``None`` (fast story).
        locks: The story/QA lock records to materialize (empty for a fast story).
        events: The lifecycle event records to materialize (empty for fast).

    Returns:
        ``True`` iff this owner finalized and materialized atomically; ``False``
        when the claim was lost (nothing written).
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
            binding_row=(
                mappers.session_binding_to_row(binding) if binding is not None else None
            ),
            lock_rows=tuple(mappers.execution_lock_to_row(lock) for lock in locks),
            event_rows=tuple(mappers.execution_event_to_row(event) for event in events),
        )
    )


def commit_control_plane_operation_with_side_effects_global(
    record: ControlPlaneOperationRecord,
    *,
    binding_to_save: SessionRunBindingRecord | None,
    binding_to_delete: BindingDeleteScope | None,
    locks: tuple[StoryExecutionLockRecord, ...],
    events: tuple[ExecutionEventRecord, ...],
) -> None:
    """Atomically commit a terminal op AND its side effects (AG3-054 ERROR-2, #2).

    ERROR-2 fix (#2): the conditional op-row upsert (which refuses to clobber a LIVE
    ``claimed`` start lease and raises :class:`ControlPlaneClaimCollisionError`) and
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

    Raises:
        ControlPlaneClaimCollisionError: When ``record`` collides with a LIVE
            ``claimed`` lease (nothing committed; the live claim is intact).
        ControlPlaneBindingCollisionError: When the binding save/delete would touch
            a FOREIGN run's live binding (nothing committed; the binding intact).
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
        lock_rows=tuple(mappers.execution_lock_to_row(lock) for lock in locks),
        event_rows=tuple(mappers.execution_event_to_row(event) for event in events),
    )


def release_control_plane_operation_global(
    op_id: str,
    *,
    owner_token: str,
    owner_claimed_at: str | None = None,
) -> None:
    """Ownership-scoped release of a claimed control-plane op (AG3-054 leased claim).

    Deletes the row ONLY when it is still ``claimed`` by ``owner_token``. NEVER an
    unconditional delete: a terminal row or another owner's claim is left intact.
    Idempotent.

    WARNING-4 fix (#4): when ``owner_claimed_at`` (the RAW lease epoch the owner
    stamped) is given, the delete CAS also matches ``claimed_at`` so it scopes to
    THIS lease generation -- a stale owner (reused token / post-takeover) cannot
    delete a NEWER lease. ``None`` keeps the legacy owner-only CAS.
    """
    backend = _backend_module()
    if not hasattr(backend, "release_control_plane_operation_global_row"):
        raise RuntimeError(
            "Control-plane op release is unsupported by the active backend",
        )
    backend.release_control_plane_operation_global_row(
        op_id, owner_token=owner_token, owner_claimed_at=owner_claimed_at
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
            "Global control-plane operations are unsupported by the active backend",
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
    projection_dir: Path | None = None,
) -> tuple[str, ...]:
    """Serialize QA layer results and persist projection + FK-69 rows.

    Mapper converts BC-typed ``LayerResult`` objects to plain dicts;
    driver performs only SQL and filesystem I/O. ``artifact_envelopes``
    writes are owned by ``verify_system.artifacts`` — this facade does
    not know about ArtifactManager (no state_backend -> verify_system
    import).
    """
    from datetime import datetime

    from agentkit.boundary.shared.time import now_iso
    from agentkit.core_types.qa_artifact_names import LAYER_ARTIFACT_FILES

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
            projection_dir=projection_dir,
        ),
    )


def record_verify_decision(
    story_dir: Path,
    *,
    decision: VerifyDecision,
    attempt_nr: int,
    projection_dir: Path | None = None,
) -> tuple[str, ...]:
    """Serialize a verify decision and persist via driver."""

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
    from agentkit.core_types import ArtifactClass
    from agentkit.state_backend.store.artifact_repository import (
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
    projection_dir: Path | None = None,
) -> Path:
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
