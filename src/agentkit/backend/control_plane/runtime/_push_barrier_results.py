"""Push-barrier result mapping and merge-precondition projection."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from agentkit.backend.control_plane import (
    push_barrier_lifecycle,
)
from agentkit.backend.control_plane.push_sync import (
    BarrierVerdict,
    PushBarrierVerdict,
    PushBarrierVerdictStatus,
    RepoPushVerdict,
    SyncPointBarrierType,
)

# Deliberate RUNTIME re-import (not TYPE_CHECKING): this is the SSOT re-import of
# the canonical FK-56 operating-mode literal from its SINGLE foundation definition
# (``core_types.operating_mode``). It must be a runtime binding so the
# single-definition identity holds for consumers (and is assertable) -- moving it
# into a type-checking block would make ``control_plane.runtime.OperatingMode`` a
# different/absent object at runtime, defeating the AK2 SSOT consolidation.
from ._models import MergePrecondition

if TYPE_CHECKING:
    from datetime import datetime

    from agentkit.backend.control_plane.models import (
        EdgeCommandResultPayload,
    )
    from agentkit.backend.control_plane.records import (
        EdgeCommandRecord,
    )

logger = logging.getLogger(__name__)

def _sync_push_result_repo_id(existing: EdgeCommandRecord, result: object) -> str | None:
    """Resolve the repo id for a ``sync_push`` result/backlog projection."""
    result_repo_id = getattr(result, "repo_id", None)
    if isinstance(result_repo_id, str) and result_repo_id:
        return result_repo_id
    payload_repo_id = existing.payload.get("repo_id")
    if isinstance(payload_repo_id, str) and payload_repo_id:
        return payload_repo_id
    return None


def _sync_point_id_from_sync_push_command(command_id: str, *, run_id: str, repo_id: str) -> str | None:
    """Extract the boundary sync-point id from the deterministic command id."""
    from agentkit.backend.control_plane.push_sync import (
        sync_point_id_from_sync_push_command_id,
    )

    return sync_point_id_from_sync_push_command_id(command_id, run_id=run_id, repo_id=repo_id)


def _push_barrier_result_binding(
    existing: EdgeCommandRecord,
    result: EdgeCommandResultPayload,
) -> tuple[str, SyncPointBarrierType, str, int] | None:
    """Extract a typed boundary binding from an epoch-tagged ``sync_push`` result."""

    if existing.command_kind != "sync_push":
        return None
    repo_id = _sync_push_result_repo_id(existing, result)
    boundary_type = existing.payload.get("boundary_type")
    boundary_id = existing.payload.get("boundary_id")
    boundary_epoch = existing.payload.get("boundary_epoch")
    if not (repo_id and isinstance(boundary_type, str) and isinstance(boundary_id, str) and isinstance(boundary_epoch, int)):
        return None
    try:
        return repo_id, SyncPointBarrierType(boundary_type), boundary_id, boundary_epoch
    except ValueError:
        return None


def _push_barrier_result_is_fenced(
    current: PushBarrierVerdict,
    existing: EdgeCommandRecord,
    result: EdgeCommandResultPayload,
    *,
    command_boundary_epoch: int,
) -> bool:
    """Return true when a late/stale result must not resolve this verdict."""

    if current.status is not PushBarrierVerdictStatus.PENDING:
        return True
    if current.boundary_epoch != command_boundary_epoch:
        return True
    if current.ownership_epoch != existing.ownership_epoch:
        return True
    if result.result_type != "push_status_report":
        return False
    return (result.boundary_epoch is not None and result.boundary_epoch != current.boundary_epoch) or (
        result.ownership_epoch is not None and result.ownership_epoch != current.ownership_epoch
    )


def _sync_push_failed_barrier_verdict(current: PushBarrierVerdict, *, updated_at: datetime) -> PushBarrierVerdict:
    """Project a failed ``sync_push`` command into a fail-closed backlog verdict."""

    return push_barrier_lifecycle.replace_push_barrier_verdict(
        current,
        expected_head_sha=None,
        server_head_sha=None,
        status=PushBarrierVerdictStatus.BLOCKED_BACKLOG,
        updated_at=updated_at,
        resolved_at=updated_at,
        status_detail="sync_push_command_failed",
    )


def _barrier_from_repo_verdicts(
    barrier_type: SyncPointBarrierType,
    repo_verdicts: tuple[RepoPushVerdict, ...],
) -> BarrierVerdict:
    """Build an aggregate barrier verdict from persisted per-repo verdicts."""

    return BarrierVerdict(
        barrier_type=barrier_type,
        passed=bool(repo_verdicts) and all(v.verified for v in repo_verdicts),
        repo_verdicts=repo_verdicts,
    )


def _merge_precondition_from_barrier(verdict: BarrierVerdict) -> MergePrecondition:
    """Project a pre-merge push-barrier block into the SOLL-190 shape."""

    return MergePrecondition(
        satisfied=verdict.passed,
        blocking_repos=verdict.blocking_repos,
        detail=(
            "all participating repos server-verified as pushed"
            if verdict.passed
            else f"unverified repos: {verdict.blocking_summary()}"
        ),
    )
