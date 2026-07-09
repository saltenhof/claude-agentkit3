"""Governance runtime-lock and ownership-fence persistence store."""

from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from typing import TYPE_CHECKING

from agentkit.backend.exceptions import CorruptStateError
from agentkit.backend.state_backend.state_backend_connection_manager import (
    _backend_module,
    control_plane_backend_available,
)

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

    from agentkit.backend.governance.guard_system.records import (
        StoryExecutionLockRecord,
    )


def save_story_execution_lock_global(record: StoryExecutionLockRecord) -> None:
    """Persist one story-execution lock record."""
    from agentkit.backend.state_backend import persistence_mappers as mappers

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
    """Load one story-execution lock record."""
    from agentkit.backend.state_backend import persistence_mappers as mappers

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


def purge_guard_decisions(
    story_dir: Path,
    project_key: str,
    story_id: str,
    run_id: str,
) -> int:
    """Delete guard_decisions rows for the run scope."""
    return int(
        _backend_module().purge_guard_decisions_row(
            story_dir,
            project_key,
            story_id,
            run_id,
        )
    )


def resolve_ownership_fence_snapshot(
    project_key: str,
    story_id: str,
) -> tuple[str, int] | None:
    """Resolve the caller's early ownership-lease snapshot."""
    from agentkit.backend.state_backend import persistence_mappers as mappers

    if not control_plane_backend_available():
        return None
    backend = _backend_module()
    row = backend.load_active_run_ownership_record_global_row(project_key, story_id)
    if row is None:
        raise CorruptStateError(
            "No active run-ownership record found for an in-flight phase "
            "execution (AG3-142/AG3-144 no-lease-no-write precondition)",
            detail={"project_key": project_key, "story_id": story_id},
        )
    active = mappers.run_ownership_row_to_record(row)
    return (active.owner_session_id, active.ownership_epoch)


@dataclass(frozen=True)
class OwnershipFenceScope:
    """The caller's early-captured ownership-lease snapshot for one phase attempt."""

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
    """Bind the caller's early-captured lease snapshot for this call's duration."""
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
    """Return the bound ownership-fence scope, failing closed if absent."""
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


__all__ = [
    "save_story_execution_lock_global",
    "load_story_execution_lock_global",
    "purge_guard_decisions",
    "resolve_ownership_fence_snapshot",
    "OwnershipFenceScope",
    "bind_ownership_fence_scope",
    "require_ownership_fence_scope",
]
