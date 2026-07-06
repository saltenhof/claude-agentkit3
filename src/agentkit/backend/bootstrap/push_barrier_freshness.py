"""Final server-fresh aggregation for persisted push-barrier verdicts."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from agentkit.backend.control_plane import push_barrier_lifecycle

if TYPE_CHECKING:
    from collections.abc import Callable

    from agentkit.backend.control_plane.push_verification import PushBarrierEvidencePort


def barrier_sync_point_id(
    boundary_type: Any,
    boundary_id: str,
    boundary_epoch: int,
) -> str:
    """Return the edge-command correlation id for one boundary epoch."""

    return push_barrier_lifecycle.boundary_sync_point_id(boundary_type, boundary_id, boundary_epoch)


def verdicts_server_fresh(
    *,
    project_key: str,
    story_id: str,
    run_id: str,
    boundary_type: Any,
    boundary_id: str,
    verdicts: tuple[Any, ...],
    expected_repo_ids: tuple[str, ...],
    evidence_factory: Callable[[], PushBarrierEvidencePort],
) -> bool:
    """Aggregate persisted PASS verdicts with the required final server recheck."""

    if not verdicts or any(_status_value(v) != "passed" for v in verdicts):
        return False
    verdict_repos = {getattr(v, "repo_id", None) for v in verdicts}
    if verdict_repos != set(expected_repo_ids):
        return False
    try:
        evidence = evidence_factory()
    except Exception:  # noqa: BLE001 -- no server-fresh evidence -> fail closed
        return False
    for verdict in verdicts:
        expected_head_sha = getattr(verdict, "expected_head_sha", None)
        boundary_epoch = getattr(verdict, "boundary_epoch", None)
        repo_id = getattr(verdict, "repo_id", None)
        if (
            not isinstance(expected_head_sha, str)
            or not expected_head_sha
            or not isinstance(boundary_epoch, int)
            or not isinstance(repo_id, str)
            or not repo_id
        ):
            return False
        required = barrier_sync_point_id(boundary_type, boundary_id, boundary_epoch)
        try:
            inputs = evidence.collect_repo_inputs(
                project_key=project_key,
                story_id=story_id,
                run_id=run_id,
                required_sync_point_id=required,
            )
        except Exception:  # noqa: BLE001 -- server read unavailable -> fail closed
            return False
        server_resolved, server_head = _server_head_for_repo(inputs, repo_id)
        if not server_resolved or server_head != expected_head_sha:
            _mark_server_moved(verdict, server_head_sha=server_head)
            return False
    return True


def _status_value(verdict: Any) -> str | None:
    """Return a persisted verdict status value across real records and tests."""

    status = getattr(verdict, "status", None)
    value = getattr(status, "value", status)
    return value if isinstance(value, str) else None


def _server_head_for_repo(inputs: tuple[Any, ...], repo_id: str) -> tuple[bool, str | None]:
    """Return the current server head for one repo from collected inputs."""

    for inp in inputs:
        if inp.repo_id == repo_id:
            return inp.server_ref_resolved, inp.server_head_sha
    return False, None


def _mark_server_moved(verdict: Any, *, server_head_sha: str | None) -> None:
    """Fail closed a stale PASS verdict when the final server read moved."""

    try:
        from agentkit.backend.control_plane.push_sync import (
            PushBarrierVerdict,
            PushBarrierVerdictStatus,
        )
        from agentkit.backend.state_backend.store import facade

        now = datetime.now(tz=UTC)
        facade.upsert_push_barrier_verdict_global(
            PushBarrierVerdict(
                project_key=verdict.project_key,
                story_id=verdict.story_id,
                run_id=verdict.run_id,
                boundary_type=verdict.boundary_type,
                boundary_id=verdict.boundary_id,
                repo_id=verdict.repo_id,
                producer=verdict.producer,
                boundary_epoch=verdict.boundary_epoch,
                expected_head_sha=verdict.expected_head_sha,
                server_head_sha=server_head_sha,
                ownership_epoch=verdict.ownership_epoch,
                status=PushBarrierVerdictStatus.BLOCKED_BACKLOG,
                created_at=verdict.created_at,
                updated_at=now,
                resolved_at=now,
                status_detail="server_head_moved_after_pass",
            )
        )
    except Exception:  # noqa: BLE001 -- caller already fails closed
        return
