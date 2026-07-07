"""Unit tests for the AG3-147 push-barrier lifecycle owner."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from agentkit.backend.control_plane.push_barrier_lifecycle import (
    aggregate_persisted_push_barrier,
    bind_push_boundary,
    boundary_sync_point_id,
    commission_sync_push_commands,
    next_boundary_binding,
    open_command_timed_out,
    replace_push_barrier_verdict,
    timed_out_open_command_verdict,
)
from agentkit.backend.control_plane.push_sync import (
    PushBarrierBlockCode,
    PushBarrierVerdict,
    PushBarrierVerdictStatus,
    SyncPointBarrierType,
)
from agentkit.backend.control_plane.records import EdgeCommandRecord

_PROJECT = "tenant-a"
_STORY = "AG3-147"
_RUN = "run-147"
_BOUNDARY = SyncPointBarrierType.PHASE_COMPLETION
_BOUNDARY_ID = "complete-1"
_NOW = datetime(2026, 7, 7, 10, 0, tzinfo=UTC)


def _verdict(
    repo_id: str = "api",
    *,
    status: PushBarrierVerdictStatus = PushBarrierVerdictStatus.PENDING,
    epoch: int = 1,
    expected: str | None = None,
    server: str | None = None,
    detail: str | None = None,
) -> PushBarrierVerdict:
    return PushBarrierVerdict(
        project_key=_PROJECT,
        story_id=_STORY,
        run_id=_RUN,
        boundary_type=_BOUNDARY,
        boundary_id=_BOUNDARY_ID,
        repo_id=repo_id,
        producer="control_plane.push_barrier",
        boundary_epoch=epoch,
        expected_head_sha=expected,
        server_head_sha=server,
        ownership_epoch=7,
        status=status,
        created_at=_NOW - timedelta(minutes=1),
        updated_at=_NOW - timedelta(minutes=1),
        resolved_at=None,
        status_detail=detail,
    )


def _edge_command(
    command_id: str,
    *,
    status: str,
    created_at: datetime,
    delivered_at: datetime | None = None,
) -> EdgeCommandRecord:
    return EdgeCommandRecord(
        command_id=command_id,
        project_key=_PROJECT,
        story_id=_STORY,
        run_id=_RUN,
        session_id="session-1",
        command_kind="sync_push",
        payload={},
        status=status,
        ownership_epoch=7,
        created_at=created_at,
        delivered_at=delivered_at,
    )


def test_next_boundary_binding_reuses_live_rows_and_retries_backlog() -> None:
    pending = _verdict(status=PushBarrierVerdictStatus.PENDING)
    passed = _verdict(status=PushBarrierVerdictStatus.PASSED, expected="a" * 40)
    backlog = _verdict(status=PushBarrierVerdictStatus.BLOCKED_BACKLOG, epoch=3, expected="b" * 40, server="c" * 40)
    superseded = _verdict(status=PushBarrierVerdictStatus.SUPERSEDED, epoch=4, expected="d" * 40)

    new = next_boundary_binding(
        None,
        project_key=_PROJECT,
        story_id=_STORY,
        run_id=_RUN,
        boundary_type=_BOUNDARY,
        boundary_id=_BOUNDARY_ID,
        repo_id="api",
        ownership_epoch=7,
        now=_NOW,
    )
    assert new.boundary_epoch == 1
    assert new.status is PushBarrierVerdictStatus.PENDING
    assert next_boundary_binding(
        pending,
        project_key=_PROJECT,
        story_id=_STORY,
        run_id=_RUN,
        boundary_type=_BOUNDARY,
        boundary_id=_BOUNDARY_ID,
        repo_id="api",
        ownership_epoch=8,
        now=_NOW,
    ) is pending
    assert next_boundary_binding(
        passed,
        project_key=_PROJECT,
        story_id=_STORY,
        run_id=_RUN,
        boundary_type=_BOUNDARY,
        boundary_id=_BOUNDARY_ID,
        repo_id="api",
        ownership_epoch=8,
        now=_NOW,
    ) is passed

    rebound = next_boundary_binding(
        superseded,
        project_key=_PROJECT,
        story_id=_STORY,
        run_id=_RUN,
        boundary_type=_BOUNDARY,
        boundary_id=_BOUNDARY_ID,
        repo_id="api",
        ownership_epoch=8,
        now=_NOW,
    )
    assert rebound.boundary_epoch == 4
    assert rebound.expected_head_sha == "d" * 40
    assert rebound.status_detail == "boundary_rebound_after_supersede"

    retry = next_boundary_binding(
        backlog,
        project_key=_PROJECT,
        story_id=_STORY,
        run_id=_RUN,
        boundary_type=_BOUNDARY,
        boundary_id=_BOUNDARY_ID,
        repo_id="api",
        ownership_epoch=8,
        now=_NOW,
    )
    assert retry.boundary_epoch == 4
    assert retry.expected_head_sha is None
    assert retry.server_head_sha is None
    assert retry.status_detail == "boundary_retry_after_backlog"


def test_bind_push_boundary_persists_only_changed_records() -> None:
    existing = _verdict(repo_id="api")
    persisted: list[PushBarrierVerdict] = []

    bound = bind_push_boundary(
        project_key=_PROJECT,
        story_id=_STORY,
        run_id=_RUN,
        boundary_type=_BOUNDARY,
        boundary_id=_BOUNDARY_ID,
        repo_ids=("api", "web"),
        ownership_epoch=7,
        load_verdict=lambda **kwargs: existing if kwargs["repo_id"] == "api" else None,
        persist_verdict=persisted.append,
        now=_NOW,
    )

    assert bound[0] is existing
    assert bound[1].repo_id == "web"
    assert persisted == [bound[1]]


def test_commission_sync_push_commands_skips_passed_and_blocks_timed_out_open_commands() -> None:
    passed = _verdict(repo_id="api", status=PushBarrierVerdictStatus.PASSED, expected="a" * 40)
    pending = _verdict(repo_id="web")
    stale = _verdict(repo_id="worker")
    stale_sync = boundary_sync_point_id(_BOUNDARY, _BOUNDARY_ID, stale.boundary_epoch)
    stale_command_id = f"{_RUN}::sync_push::{stale_sync}::worker"
    commands: dict[str, EdgeCommandRecord] = {
        stale_command_id: _edge_command(
            stale_command_id,
            status="delivered",
            created_at=_NOW - timedelta(minutes=20),
            delivered_at=_NOW - timedelta(minutes=20),
        )
    }
    commissioned: list[EdgeCommandRecord] = []
    blocked: list[PushBarrierVerdict] = []
    superseded: list[dict[str, object]] = []

    commission_sync_push_commands(
        project_key=_PROJECT,
        story_id=_STORY,
        run_id=_RUN,
        owner_session_id="session-1",
        ownership_epoch=7,
        boundary_type=_BOUNDARY,
        boundary_id=_BOUNDARY_ID,
        verdicts=(passed, pending, stale),
        load_command=lambda command_id: commands.get(command_id),
        commission_command=commissioned.append,
        persist_blocked_verdict=blocked.append,
        supersede_open_command=lambda **kwargs: superseded.append(kwargs),
        now=_NOW,
    )

    assert [command.payload["repo_id"] for command in commissioned] == ["web"]
    assert commissioned[0].payload["branch"] == "story/AG3-147"
    assert commissioned[0].payload["boundary_epoch"] == 1
    assert blocked[0].repo_id == "worker"
    assert blocked[0].status is PushBarrierVerdictStatus.BLOCKED_BACKLOG
    assert superseded[0]["command_id"] == stale_command_id


def test_open_command_timeout_uses_created_or_delivered_timestamps() -> None:
    fresh = _edge_command("cmd-1", status="created", created_at=_NOW - timedelta(minutes=1))
    old_created = _edge_command("cmd-2", status="created", created_at=_NOW - timedelta(minutes=20))
    old_delivered = _edge_command(
        "cmd-3",
        status="delivered",
        created_at=_NOW,
        delivered_at=_NOW - timedelta(minutes=20),
    )
    completed = _edge_command("cmd-4", status="completed", created_at=_NOW - timedelta(minutes=20))

    assert open_command_timed_out(fresh, now=_NOW) is False
    assert open_command_timed_out(old_created, now=_NOW) is True
    assert open_command_timed_out(old_delivered, now=_NOW) is True
    assert open_command_timed_out(completed, now=_NOW) is False
    assert open_command_timed_out(object(), now=_NOW) is False
    assert timed_out_open_command_verdict(_verdict(), updated_at=_NOW).status_detail == "sync_push_command_timed_out"


def test_aggregate_persisted_push_barrier_confirms_server_head_and_blocks_stale_passes() -> None:
    good = _verdict(repo_id="api", status=PushBarrierVerdictStatus.PASSED, expected="a" * 40)
    missing_expected = _verdict(repo_id="web", status=PushBarrierVerdictStatus.PASSED)
    moved = _verdict(repo_id="worker", status=PushBarrierVerdictStatus.PASSED, expected="b" * 40)
    blocked: list[PushBarrierVerdict] = []

    verdict = aggregate_persisted_push_barrier(
        _BOUNDARY,
        (good, missing_expected, moved),
        expected_repo_ids=("api", "web", "worker", "docs"),
        server_head_for_verdict=lambda row: {
            "api": "a" * 40,
            "web": "a" * 40,
            "worker": "c" * 40,
        }.get(row.repo_id),
        persist_blocked_verdict=blocked.append,
        now=_NOW,
    )

    assert verdict.passed is False
    assert verdict.repo_verdicts[0].verified is True
    assert verdict.repo_verdicts[1].block_code is PushBarrierBlockCode.EDGE_REPORTS_BACKLOG
    assert verdict.repo_verdicts[1].detail == "passed_verdict_missing_expected_head"
    assert verdict.repo_verdicts[2].detail == "server_head_moved_after_pass"
    assert verdict.repo_verdicts[3].block_code is PushBarrierBlockCode.NO_EDGE_PUSH_REPORT
    assert [row.repo_id for row in blocked] == ["web", "worker"]


def test_aggregate_persisted_push_barrier_blocks_empty_participation() -> None:
    verdict = aggregate_persisted_push_barrier(
        _BOUNDARY,
        (),
        expected_repo_ids=(),
        server_head_for_verdict=lambda _row: None,
        persist_blocked_verdict=lambda _row: None,
        now=_NOW,
    )

    assert verdict.passed is False
    assert verdict.repo_verdicts[0].block_code is PushBarrierBlockCode.NO_PARTICIPATING_REPOS


def test_replace_push_barrier_verdict_preserves_identity_fields() -> None:
    original = _verdict(status=PushBarrierVerdictStatus.PASSED, expected="a" * 40, server="a" * 40)

    updated = replace_push_barrier_verdict(
        original,
        boundary_epoch=2,
        expected_head_sha=object(),
        server_head_sha="b" * 40,
        ownership_epoch=9,
        status=PushBarrierVerdictStatus.BLOCKED_BACKLOG,
        updated_at=_NOW,
        resolved_at=_NOW,
        status_detail="blocked",
    )

    assert updated.project_key == original.project_key
    assert updated.story_id == original.story_id
    assert updated.run_id == original.run_id
    assert updated.repo_id == original.repo_id
    assert updated.created_at == original.created_at
    assert updated.boundary_epoch == 2
    assert updated.expected_head_sha is None
    assert updated.server_head_sha == "b" * 40
    assert updated.ownership_epoch == 9
