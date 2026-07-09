"""Story-lifecycle persistence store."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from agentkit.backend.state_backend.state_backend_connection_manager import (
    _backend_module,
    _require_control_plane_backend,
)

if TYPE_CHECKING:
    from pathlib import Path
    from uuid import UUID

    from agentkit.backend.story_context_manager.models import StoryContext

_SESSION_BINDING_UNSUPPORTED = (
    "Global session binding storage is unsupported by the active backend"
)
_OWNERSHIP_STATUS_TRANSFERRED = "transferred"


def _status_value(record: Any) -> str:
    status = record.status
    value = getattr(status, "value", status)
    return str(value)


def save_story_context(story_dir: Path, ctx: StoryContext) -> None:
    """Persist one local story context."""
    from agentkit.backend.state_backend import persistence_mappers as mappers

    row = mappers.story_context_to_row(ctx)
    _backend_module().save_story_context_row(story_dir, row)


def save_story_context_global(store_dir: Path | None, ctx: StoryContext) -> None:
    """Persist one global story context."""
    from agentkit.backend.state_backend import persistence_mappers as mappers

    row = mappers.story_context_to_row(ctx)
    _backend_module().save_story_context_global_row(store_dir, row)


def load_story_context(story_dir: Path) -> StoryContext | None:
    """Load one local story context."""
    from agentkit.backend.state_backend import persistence_mappers as mappers

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
    """Load one global story context."""
    from agentkit.backend.state_backend import persistence_mappers as mappers

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
    """Load one global story context by numeric story identity."""
    from agentkit.backend.state_backend import persistence_mappers as mappers

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
    """Load one global story context by immutable story UUID."""
    from agentkit.backend.state_backend import persistence_mappers as mappers

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
    """Load global story contexts for one project."""
    from agentkit.backend.state_backend import persistence_mappers as mappers

    backend = _backend_module()
    if not hasattr(backend, "load_story_context_rows_global"):
        raise RuntimeError(
            "Global story-context reads are unsupported by the active backend",
        )
    rows = backend.load_story_context_rows_global(store_dir, project_key)
    return [
        mappers.story_context_payload_to_record(
            str(row["payload_json"]),
            db_label="postgres",
        )
        for row in rows
    ]


def read_story_context_record(story_dir: Path) -> StoryContext | None:
    """Compatibility alias for ``load_story_context``."""
    return load_story_context(story_dir)


def save_session_run_binding_global(record: Any) -> None:
    """Persist the session-to-run binding projection."""
    from agentkit.backend.state_backend import persistence_mappers as mappers

    backend = _backend_module()
    if not hasattr(backend, "save_session_run_binding_global_row"):
        raise RuntimeError(_SESSION_BINDING_UNSUPPORTED)
    row = mappers.session_binding_to_row(record)
    backend.save_session_run_binding_global_row(row)


def load_session_run_binding_global(session_id: str) -> Any | None:
    """Load one session-to-run binding projection."""
    from agentkit.backend.state_backend import persistence_mappers as mappers

    backend = _backend_module()
    if not hasattr(backend, "load_session_run_binding_global_row"):
        raise RuntimeError(_SESSION_BINDING_UNSUPPORTED)
    row = backend.load_session_run_binding_global_row(session_id)
    if row is None:
        return None
    return mappers.session_binding_row_to_record(row)


def delete_session_run_binding_global(session_id: str) -> None:
    """Delete one session-to-run binding projection."""
    backend = _backend_module()
    if not hasattr(backend, "delete_session_run_binding_global"):
        raise RuntimeError(_SESSION_BINDING_UNSUPPORTED)
    backend.delete_session_run_binding_global(session_id)


def insert_run_ownership_record_global(record: Any) -> None:
    """Strictly insert one run-ownership record."""
    from agentkit.backend.state_backend import persistence_mappers as mappers

    if _status_value(record) == _OWNERSHIP_STATUS_TRANSFERRED:
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
) -> Any | None:
    """Load one run-ownership record by run identity."""
    from agentkit.backend.state_backend import persistence_mappers as mappers

    _require_control_plane_backend()
    backend = _backend_module()
    row = backend.load_run_ownership_record_global_row(project_key, story_id, run_id)
    if row is None:
        return None
    return mappers.run_ownership_row_to_record(row)


def load_active_run_ownership_record_global(
    project_key: str,
    story_id: str,
) -> Any | None:
    """Load the single active run-ownership record for one story."""
    from agentkit.backend.state_backend import persistence_mappers as mappers

    _require_control_plane_backend()
    backend = _backend_module()
    row = backend.load_active_run_ownership_record_global_row(project_key, story_id)
    if row is None:
        return None
    return mappers.run_ownership_row_to_record(row)


def save_takeover_transfer_record_global(record: Any) -> None:
    """Upsert one takeover-transfer record."""
    from agentkit.backend.state_backend import persistence_mappers as mappers

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
) -> Any | None:
    """Load one takeover-transfer record by per-repo identity."""
    from agentkit.backend.state_backend import persistence_mappers as mappers

    _require_control_plane_backend()
    backend = _backend_module()
    row = backend.load_takeover_transfer_record_global_row(
        project_key,
        story_id,
        run_id,
        ownership_epoch,
        repo_id,
    )
    if row is None:
        return None
    return mappers.takeover_transfer_row_to_record(row)


def insert_takeover_approval_global(record: Any) -> None:
    """Insert one persistent takeover approval request."""
    from agentkit.backend.state_backend import persistence_mappers as mappers

    _require_control_plane_backend()
    backend = _backend_module()
    backend.insert_takeover_approval_global_row(mappers.takeover_approval_to_row(record))


def load_takeover_approval_global(approval_id: str) -> Any | None:
    """Load one takeover approval request."""
    from agentkit.backend.state_backend import persistence_mappers as mappers

    _require_control_plane_backend()
    backend = _backend_module()
    row = backend.load_takeover_approval_global_row(approval_id)
    if row is None:
        return None
    return mappers.takeover_approval_row_to_record(row)


def update_takeover_approval_status_global(record: Any) -> bool:
    """CAS-update one takeover approval status from its current record state."""
    from agentkit.backend.state_backend import persistence_mappers as mappers

    _require_control_plane_backend()
    backend = _backend_module()
    return bool(backend.update_takeover_approval_status_global_row(mappers.takeover_approval_to_row(record)))


def list_pending_takeover_approvals_global(
    project_key: str | None = None,
) -> tuple[Any, ...]:
    """List pending takeover approvals, optionally scoped to one project."""
    from agentkit.backend.state_backend import persistence_mappers as mappers

    _require_control_plane_backend()
    backend = _backend_module()
    rows = backend.list_pending_takeover_approval_rows_global(project_key)
    return tuple(mappers.takeover_approval_row_to_record(row) for row in rows)


def backend_has_valid_context(story_dir: Path) -> bool:
    """Return whether the story has a readable canonical context."""
    return load_story_context(story_dir) is not None


__all__ = [
    "save_story_context",
    "save_story_context_global",
    "load_story_context",
    "load_story_context_global",
    "load_story_context_by_story_number_global",
    "load_story_context_by_uuid_global",
    "load_story_contexts_global",
    "read_story_context_record",
    "save_session_run_binding_global",
    "load_session_run_binding_global",
    "delete_session_run_binding_global",
    "insert_run_ownership_record_global",
    "load_run_ownership_record_global",
    "load_active_run_ownership_record_global",
    "save_takeover_transfer_record_global",
    "load_takeover_transfer_record_global",
    "insert_takeover_approval_global",
    "load_takeover_approval_global",
    "update_takeover_approval_status_global",
    "list_pending_takeover_approvals_global",
    "backend_has_valid_context",
]
