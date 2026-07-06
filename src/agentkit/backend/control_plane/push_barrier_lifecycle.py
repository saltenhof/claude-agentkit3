"""Shared push-barrier lifecycle helpers.

This module owns the non-I/O state transitions for AG3-147 boundary verdicts so
runtime consumers and bootstrap adapters do not grow divergent state machines.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any, cast

from agentkit.backend.control_plane.push_sync import (
    BarrierVerdict,
    PushBarrierBlockCode,
    PushBarrierVerdict,
    PushBarrierVerdictStatus,
    RepoPushVerdict,
    SyncPointBarrierType,
)

if TYPE_CHECKING:
    from collections.abc import Iterable


OPEN_SYNC_PUSH_TIMEOUT = timedelta(minutes=10)
_KEEP_FIELD = object()


def boundary_sync_point_id(
    boundary_type: SyncPointBarrierType,
    boundary_id: str,
    boundary_epoch: int,
) -> str:
    """Return the edge-command correlation id for one boundary epoch."""

    return f"{boundary_type.value}:{boundary_id}:epoch-{boundary_epoch}"


def next_boundary_binding(
    current: PushBarrierVerdict | None,
    *,
    project_key: str,
    story_id: str,
    run_id: str,
    boundary_type: SyncPointBarrierType,
    boundary_id: str,
    repo_id: str,
    ownership_epoch: int,
    now: datetime,
) -> PushBarrierVerdict:
    """Return the verdict row representing the current boundary epoch."""

    if current is None:
        return PushBarrierVerdict(
            project_key=project_key,
            story_id=story_id,
            run_id=run_id,
            boundary_type=boundary_type,
            boundary_id=boundary_id,
            repo_id=repo_id,
            producer="control_plane.push_barrier",
            boundary_epoch=1,
            expected_head_sha=None,
            server_head_sha=None,
            ownership_epoch=ownership_epoch,
            status=PushBarrierVerdictStatus.PENDING,
            created_at=now,
            updated_at=now,
            resolved_at=None,
            status_detail="boundary_bound",
        )
    if current.status in (
        PushBarrierVerdictStatus.PENDING,
        PushBarrierVerdictStatus.PASSED,
    ):
        return current
    if current.status is PushBarrierVerdictStatus.SUPERSEDED:
        return replace_push_barrier_verdict(
            current,
            status=PushBarrierVerdictStatus.PENDING,
            ownership_epoch=ownership_epoch,
            updated_at=now,
            resolved_at=None,
            status_detail="boundary_rebound_after_supersede",
        )
    return replace_push_barrier_verdict(
        current,
        boundary_epoch=current.boundary_epoch + 1,
        expected_head_sha=None,
        server_head_sha=None,
        ownership_epoch=ownership_epoch,
        status=PushBarrierVerdictStatus.PENDING,
        updated_at=now,
        resolved_at=None,
        status_detail="boundary_retry_after_backlog",
    )


def timed_out_open_command_verdict(verdict: PushBarrierVerdict, *, updated_at: datetime) -> PushBarrierVerdict:
    """Mark a pending verdict blocked when its commissioned command timed out."""

    return replace_push_barrier_verdict(
        verdict,
        expected_head_sha=None,
        server_head_sha=None,
        status=PushBarrierVerdictStatus.BLOCKED_BACKLOG,
        updated_at=updated_at,
        resolved_at=updated_at,
        status_detail="sync_push_command_timed_out",
    )


def block_timed_out_open_command(
    *,
    command: Any,
    verdict: PushBarrierVerdict,
    now: datetime,
    persist_blocked_verdict: Any,
    supersede_open_command: Any,
) -> bool:
    """Escalate a stale open command and terminalize it as superseded."""

    if not open_command_timed_out(command, now=now):
        return False
    blocked = timed_out_open_command_verdict(verdict, updated_at=now)
    persist_blocked_verdict(blocked)
    command_id = getattr(command, "command_id", None)
    if isinstance(command_id, str) and command_id:
        supersede_open_command(
            command_id=command_id,
            completed_at=now,
            result_payload=_superseded_command_payload(verdict),
        )
    return True


def open_command_timed_out(
    command: Any,
    *,
    now: datetime,
    timeout: timedelta | None = None,
) -> bool:
    """Return whether an open edge command crossed the boundary wait limit."""

    status = getattr(command, "status", None)
    if status not in {"created", "delivered"}:
        return False
    started_at = getattr(command, "delivered_at", None) or getattr(command, "created_at", None)
    if not isinstance(started_at, datetime):
        return False
    return now - started_at >= (timeout or OPEN_SYNC_PUSH_TIMEOUT)


def aggregate_persisted_push_barrier(
    barrier_type: SyncPointBarrierType,
    verdicts: tuple[PushBarrierVerdict, ...],
    *,
    expected_repo_ids: Iterable[str],
    server_head_for_verdict: Any,
    persist_blocked_verdict: Any,
    now: datetime,
) -> BarrierVerdict:
    """Aggregate verdict rows as a hard AND over the participating repo set."""

    verdict_by_repo = {v.repo_id: v for v in verdicts}
    repo_verdicts: list[RepoPushVerdict] = []
    for repo_id in tuple(expected_repo_ids):
        verdict = verdict_by_repo.get(repo_id)
        if verdict is None:
            repo_verdicts.append(_missing_repo_verdict(repo_id))
            continue
        if verdict.status is not PushBarrierVerdictStatus.PASSED:
            repo_verdicts.append(repo_verdict_from_persisted(verdict))
            continue
        if not _non_empty_sha(verdict.expected_head_sha):
            blocked = replace_push_barrier_verdict(
                verdict,
                status=PushBarrierVerdictStatus.BLOCKED_BACKLOG,
                server_head_sha=None,
                updated_at=now,
                resolved_at=now,
                status_detail="passed_verdict_missing_expected_head",
            )
            persist_blocked_verdict(blocked)
            repo_verdicts.append(repo_verdict_from_persisted(blocked))
            continue
        server_head = server_head_for_verdict(verdict)
        if _non_empty_sha(server_head) and server_head == verdict.expected_head_sha:
            repo_verdicts.append(
                RepoPushVerdict(
                    repo_id=verdict.repo_id,
                    verified=True,
                    block_code=None,
                    detail=(f"persisted push-barrier verdict passed and server still confirms {server_head}"),
                )
            )
            continue
        blocked = replace_push_barrier_verdict(
            verdict,
            status=PushBarrierVerdictStatus.BLOCKED_BACKLOG,
            server_head_sha=server_head,
            updated_at=now,
            resolved_at=now,
            status_detail="server_head_moved_after_pass",
        )
        persist_blocked_verdict(blocked)
        repo_verdicts.append(repo_verdict_from_persisted(blocked))
    if not repo_verdicts:
        repo_verdicts.append(
            RepoPushVerdict(
                repo_id="",
                verified=False,
                block_code=PushBarrierBlockCode.NO_PARTICIPATING_REPOS,
                detail="no participating repos supplied to the push barrier",
            )
        )
    return BarrierVerdict(
        barrier_type,
        passed=all(v.verified for v in repo_verdicts),
        repo_verdicts=tuple(repo_verdicts),
    )


def repo_verdict_from_persisted(verdict: PushBarrierVerdict) -> RepoPushVerdict:
    """Map a persisted non-passing verdict to the public repo verdict shape."""

    detail = verdict.status_detail or f"push barrier status {verdict.status.value}"
    code = (
        PushBarrierBlockCode.EDGE_REPORTS_BACKLOG
        if verdict.status is PushBarrierVerdictStatus.BLOCKED_BACKLOG
        else PushBarrierBlockCode.NO_EDGE_PUSH_REPORT
    )
    return RepoPushVerdict(
        repo_id=verdict.repo_id,
        verified=False,
        block_code=code,
        detail=detail,
    )


def replace_push_barrier_verdict(
    verdict: PushBarrierVerdict,
    *,
    updated_at: datetime,
    resolved_at: datetime | None,
    status_detail: str | None,
    boundary_epoch: int | None = None,
    expected_head_sha: str | None | object = _KEEP_FIELD,
    server_head_sha: str | None | object = _KEEP_FIELD,
    ownership_epoch: int | None = None,
    status: PushBarrierVerdictStatus | None = None,
) -> PushBarrierVerdict:
    """Return a copy of a verdict with lifecycle fields replaced."""

    return replace(
        verdict,
        boundary_epoch=(boundary_epoch if boundary_epoch is not None else verdict.boundary_epoch),
        expected_head_sha=(
            verdict.expected_head_sha if expected_head_sha is _KEEP_FIELD else cast("str | None", expected_head_sha)
        ),
        server_head_sha=(verdict.server_head_sha if server_head_sha is _KEEP_FIELD else cast("str | None", server_head_sha)),
        ownership_epoch=(ownership_epoch if ownership_epoch is not None else verdict.ownership_epoch),
        status=status or verdict.status,
        updated_at=updated_at,
        resolved_at=resolved_at,
        status_detail=status_detail,
    )


def _missing_repo_verdict(repo_id: str) -> RepoPushVerdict:
    return RepoPushVerdict(
        repo_id=repo_id,
        verified=False,
        block_code=PushBarrierBlockCode.NO_EDGE_PUSH_REPORT,
        detail="no push-barrier verdict row exists for this participating repo",
    )


def _non_empty_sha(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _superseded_command_payload(verdict: PushBarrierVerdict) -> dict[str, object]:
    return {
        "reason": "sync_push_command_timed_out",
        "project_key": verdict.project_key,
        "story_id": verdict.story_id,
        "run_id": verdict.run_id,
        "boundary_type": verdict.boundary_type.value,
        "boundary_id": verdict.boundary_id,
        "boundary_epoch": verdict.boundary_epoch,
        "repo_id": verdict.repo_id,
    }
