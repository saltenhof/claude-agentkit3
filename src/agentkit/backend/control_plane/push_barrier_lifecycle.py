"""Shared push-barrier lifecycle helpers.

This module owns the non-I/O state transitions for AG3-147 boundary verdicts so
runtime consumers and bootstrap adapters do not grow divergent state machines.
"""

from __future__ import annotations

from dataclasses import is_dataclass, replace
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any, cast

from agentkit.backend.control_plane.models import SyncPushCommandPayload
from agentkit.backend.control_plane.push_sync import (
    BarrierVerdict,
    PushBarrierBlockCode,
    PushBarrierVerdict,
    PushBarrierVerdictStatus,
    RepoPushVerdict,
    SyncPointBarrierType,
    next_sync_push_command_id,
    official_story_ref,
    open_sync_push_command,
)
from agentkit.backend.control_plane.records import EdgeCommandRecord

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


def bind_push_boundary(
    *,
    project_key: str,
    story_id: str,
    run_id: str,
    boundary_type: SyncPointBarrierType,
    boundary_id: str,
    repo_ids: Iterable[str],
    ownership_epoch: int,
    load_verdict: Any,
    persist_verdict: Any,
    now: datetime,
) -> tuple[PushBarrierVerdict, ...]:
    """Bind one boundary instance and return its current per-repo verdict rows."""

    bound: list[PushBarrierVerdict] = []
    for repo_id in tuple(repo_ids):
        current = load_verdict(
            project_key=project_key,
            story_id=story_id,
            run_id=run_id,
            boundary_type=boundary_type,
            boundary_id=boundary_id,
            repo_id=repo_id,
        )
        next_record = next_boundary_binding(
            current,
            project_key=project_key,
            story_id=story_id,
            run_id=run_id,
            boundary_type=boundary_type,
            boundary_id=boundary_id,
            repo_id=repo_id,
            ownership_epoch=ownership_epoch,
            now=now,
        )
        if next_record != current:
            persist_verdict(next_record)
        bound.append(next_record)
    return tuple(bound)


def commission_sync_push_commands(
    *,
    project_key: str,
    story_id: str,
    run_id: str,
    owner_session_id: str,
    ownership_epoch: int,
    boundary_type: SyncPointBarrierType,
    boundary_id: str,
    verdicts: Iterable[PushBarrierVerdict],
    load_command: Any,
    commission_command: Any,
    persist_blocked_verdict: Any,
    supersede_open_command: Any,
    now: datetime,
) -> None:
    """Commission ``sync_push`` commands for all non-passed boundary verdicts."""

    branch = official_story_ref(story_id)
    for verdict in tuple(verdicts):
        if _status_value(verdict) == PushBarrierVerdictStatus.PASSED.value:
            continue
        sync_point_id = boundary_sync_point_id(
            boundary_type,
            boundary_id,
            verdict.boundary_epoch,
        )
        command_id = next_sync_push_command_id(
            run_id=run_id,
            sync_point_id=sync_point_id,
            repo_id=verdict.repo_id,
            load_command=load_command,
        )
        if command_id is None:
            open_command = open_sync_push_command(
                run_id=run_id,
                sync_point_id=sync_point_id,
                repo_id=verdict.repo_id,
                load_command=load_command,
            )
            if open_command is not None:
                block_timed_out_open_command(
                    command=open_command,
                    verdict=verdict,
                    now=now,
                    persist_blocked_verdict=persist_blocked_verdict,
                    supersede_open_command=supersede_open_command,
                )
            continue
        commission_command(
            EdgeCommandRecord(
                command_id=command_id,
                project_key=project_key,
                story_id=story_id,
                run_id=run_id,
                session_id=owner_session_id,
                command_kind="sync_push",
                payload=SyncPushCommandPayload(
                    story_id=story_id,
                    project_key=project_key,
                    run_id=run_id,
                    repo_id=verdict.repo_id,
                    branch=branch,
                    boundary_type=boundary_type.value,
                    boundary_id=boundary_id,
                    boundary_epoch=verdict.boundary_epoch,
                    ownership_epoch=ownership_epoch,
                ).model_dump(mode="json"),
                status="created",
                ownership_epoch=ownership_epoch,
                created_at=now,
            )
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
        repo_verdicts.append(
            _aggregate_repo_verdict(
                verdict_by_repo.get(repo_id),
                repo_id=repo_id,
                server_head_for_verdict=server_head_for_verdict,
                persist_blocked_verdict=persist_blocked_verdict,
                now=now,
            )
        )
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


def _aggregate_repo_verdict(
    verdict: PushBarrierVerdict | None,
    *,
    repo_id: str,
    server_head_for_verdict: Any,
    persist_blocked_verdict: Any,
    now: datetime,
) -> RepoPushVerdict:
    if verdict is None:
        return _missing_repo_verdict(repo_id)
    if _status_value(verdict) != PushBarrierVerdictStatus.PASSED.value:
        return repo_verdict_from_persisted(verdict)
    if not _non_empty_sha(verdict.expected_head_sha):
        return _block_persisted_verdict(
            verdict,
            server_head_sha=None,
            detail="passed_verdict_missing_expected_head",
            persist_blocked_verdict=persist_blocked_verdict,
            now=now,
        )
    server_head = server_head_for_verdict(verdict)
    if _non_empty_sha(server_head) and server_head == verdict.expected_head_sha:
        return RepoPushVerdict(
            repo_id=verdict.repo_id,
            verified=True,
            block_code=None,
            detail=f"persisted push-barrier verdict passed and server still confirms {server_head}",
        )
    return _block_persisted_verdict(
        verdict,
        server_head_sha=server_head,
        detail="server_head_moved_after_pass",
        persist_blocked_verdict=persist_blocked_verdict,
        now=now,
    )


def _block_persisted_verdict(
    verdict: PushBarrierVerdict,
    *,
    server_head_sha: str | None,
    detail: str,
    persist_blocked_verdict: Any,
    now: datetime,
) -> RepoPushVerdict:
    if not is_dataclass(verdict):
        return _blocked_repo_verdict(verdict.repo_id, detail=detail)
    blocked = replace_push_barrier_verdict(
        verdict,
        status=PushBarrierVerdictStatus.BLOCKED_BACKLOG,
        server_head_sha=server_head_sha,
        updated_at=now,
        resolved_at=now,
        status_detail=detail,
    )
    persist_blocked_verdict(blocked)
    return repo_verdict_from_persisted(blocked)


def repo_verdict_from_persisted(verdict: PushBarrierVerdict) -> RepoPushVerdict:
    """Map a persisted non-passing verdict to the public repo verdict shape."""

    status_value = _status_value(verdict) or "unknown"
    detail = getattr(verdict, "status_detail", None) or f"push barrier status {status_value}"
    code = (
        PushBarrierBlockCode.EDGE_REPORTS_BACKLOG
        if status_value == PushBarrierVerdictStatus.BLOCKED_BACKLOG.value
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

    updated: PushBarrierVerdict = replace(
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
    return updated


def _missing_repo_verdict(repo_id: str) -> RepoPushVerdict:
    return RepoPushVerdict(
        repo_id=repo_id,
        verified=False,
        block_code=PushBarrierBlockCode.NO_EDGE_PUSH_REPORT,
        detail="no push-barrier verdict row exists for this participating repo",
    )


def _blocked_repo_verdict(repo_id: str, *, detail: str) -> RepoPushVerdict:
    return RepoPushVerdict(
        repo_id=repo_id,
        verified=False,
        block_code=PushBarrierBlockCode.EDGE_REPORTS_BACKLOG,
        detail=detail,
    )


def _non_empty_sha(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _status_value(verdict: object) -> str | None:
    status = getattr(verdict, "status", None)
    value = getattr(status, "value", status)
    return value if isinstance(value, str) else None


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
