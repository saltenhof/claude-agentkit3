"""Pure contract mapping tests for AG3-152 edge merge results."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from agentkit.backend.closure import edge_merge
from agentkit.backend.closure.edge_merge import (
    EdgeCandidateEvidence,
    EdgeMergeState,
    QueueMergeLocalCommandPort,
    apply_merge_local_report,
)
from agentkit.backend.control_plane.models import (
    MergeLocalRepoReport,
    MergeLocalReport,
    PushStatusReport,
    WorktreeReport,
)
from agentkit.backend.control_plane.push_barrier_lifecycle import (
    boundary_sync_point_id,
)
from agentkit.backend.control_plane.push_sync import (
    PushBarrierVerdict,
    PushBarrierVerdictStatus,
    PushFreshnessRecord,
    SyncPointBarrierType,
)
from agentkit.backend.control_plane.records import EdgeCommandRecord
from agentkit.backend.control_plane.repository import EdgeCommandRepository
from agentkit.backend.pipeline_engine.phase_executor import ClosureProgress

if TYPE_CHECKING:
    from pytest import MonkeyPatch


def test_success_report_advances_the_existing_progress_contract() -> None:
    progress = ClosureProgress(story_branch_pushed=True, integrity_passed=True)
    report = MergeLocalReport(
        outcome="already_merged",
        escalated=False,
        merged_main_sha="a" * 40,
        repositories=[
            MergeLocalRepoReport(
                repo_id="api",
                outcome="already_merged",
                merged=True,
                merged_main_sha="a" * 40,
            )
        ],
    )

    updated, multi_repo = apply_merge_local_report(progress, report)

    assert updated.merge_done is True
    assert multi_repo.merged_repos == ["api"]
    assert multi_repo.failed_repo is None


def test_escalated_report_preserves_merge_checkpoint_and_rollback_audit() -> None:
    progress = ClosureProgress(story_branch_pushed=True, integrity_passed=True)
    report = MergeLocalReport(
        outcome="escalated",
        escalated=True,
        failure_code="cas_contention",
        repositories=[
            MergeLocalRepoReport(
                repo_id="api",
                outcome="rolled_back",
                rolled_back=True,
                locked_sha="a" * 40,
                pre_merge_sha="a" * 40,
            )
        ],
    )

    updated, multi_repo = apply_merge_local_report(progress, report)

    assert updated.merge_done is False
    assert multi_repo.rolled_back_repos == ["api"]


def test_candidate_is_bound_to_the_passed_closure_entry_verdict(
    monkeypatch: MonkeyPatch,
) -> None:
    now = datetime.now(tz=UTC)
    sha = "a" * 40
    sync_point = boundary_sync_point_id(
        SyncPointBarrierType.CLOSURE_ENTRY, "run-1", 3
    )
    freshness = PushFreshnessRecord(
        project_key="project",
        story_id="AG3-152",
        run_id="run-1",
        repo_id="api",
        last_reported_head_sha=sha,
        last_pushed_head_sha=sha,
        last_reported_at=now,
        last_sync_point_id=sync_point,
        last_command_id="push-1",
        backlog=False,
        backlog_detail=None,
    )
    verdict = PushBarrierVerdict(
        project_key="project",
        story_id="AG3-152",
        run_id="run-1",
        boundary_type=SyncPointBarrierType.CLOSURE_ENTRY,
        boundary_id="run-1",
        repo_id="api",
        producer="test",
        boundary_epoch=3,
        expected_head_sha=sha,
        server_head_sha=sha,
        ownership_epoch=2,
        status=PushBarrierVerdictStatus.PASSED,
        created_at=now,
        updated_at=now,
    )
    command = _command(
        "push-1",
        "sync_push",
        status="completed",
        result=PushStatusReport(
            repo_id="api",
            push_outcome="pushed",
            head_sha=sha,
            tree_hash="b" * 40,
            worktree_clean=True,
            base_ancestor=True,
        ).model_dump(mode="json"),
    )
    monkeypatch.setattr(
        "agentkit.backend.state_backend.story_closure_store.load_push_freshness_record_global",
        lambda *_args: freshness,
    )
    monkeypatch.setattr(
        "agentkit.backend.state_backend.story_closure_store.load_push_barrier_verdict_global",
        lambda **_kwargs: verdict,
    )
    port = QueueMergeLocalCommandPort(
        EdgeCommandRepository(load_command=lambda _command_id: command)
    )

    assert port.candidate(
        project_key="project", story_id="AG3-152", run_id="run-1", repo_id="api"
    ) == EdgeCandidateEvidence("api", sha, "b" * 40, True, True)

    mismatched = replace(verdict, server_head_sha="c" * 40)
    monkeypatch.setattr(
        "agentkit.backend.state_backend.story_closure_store.load_push_barrier_verdict_global",
        lambda **_kwargs: mismatched,
    )
    assert (
        port.candidate(
            project_key="project",
            story_id="AG3-152",
            run_id="run-1",
            repo_id="api",
        )
        is None
    )


def test_cross_resume_reprovisions_before_commissioning_merge(
    monkeypatch: MonkeyPatch,
) -> None:
    records: dict[str, EdgeCommandRecord] = {}

    def commission(record: EdgeCommandRecord) -> bool:
        records.setdefault(record.command_id, record)
        return True

    repository = EdgeCommandRepository(
        commission_command=commission,
        load_command=lambda command_id: records.get(command_id),
    )
    monkeypatch.setattr(edge_merge, "_active_owner", lambda *_args: ("session-2", 7))
    port = QueueMergeLocalCommandPort(repository)
    kwargs = {
        "project_key": "project",
        "story_id": "AG3-152",
        "run_id": "run-1",
        "repo_ids": ("api",),
        "candidate": EdgeCandidateEvidence("api", "a" * 40, "b" * 40, True, True),
        "mode": "standard",
    }

    assert port.execute(**kwargs).state is EdgeMergeState.PENDING
    provision_id = next(iter(records))
    assert records[provision_id].command_kind == "provision_worktree"
    assert all(record.command_kind != "merge_local" for record in records.values())

    records[provision_id] = replace(
        records[provision_id],
        status="completed",
        result_payload=WorktreeReport(
            outcome="provisioned", repo_id="api", worktree_root="C:/edge/worktree"
        ).model_dump(mode="json"),
    )
    assert port.execute(**kwargs).state is EdgeMergeState.PENDING
    merge_id = next(
        command_id
        for command_id, record in records.items()
        if record.command_kind == "merge_local"
    )
    assert records[merge_id].session_id == "session-2"
    assert records[merge_id].ownership_epoch == 7

    records[merge_id] = replace(
        records[merge_id],
        status="completed",
        result_payload=MergeLocalReport(
            outcome="already_merged",
            escalated=False,
            merged_main_sha="a" * 40,
            repositories=[
                MergeLocalRepoReport(
                    repo_id="api", outcome="already_merged", merged=True
                )
            ],
        ).model_dump(mode="json"),
    )
    assert port.execute(**kwargs).state is EdgeMergeState.MERGED


def _command(
    command_id: str,
    command_kind: str,
    *,
    status: str,
    result: dict[str, object],
) -> EdgeCommandRecord:
    return EdgeCommandRecord(
        command_id=command_id,
        project_key="project",
        story_id="AG3-152",
        run_id="run-1",
        session_id="session-1",
        command_kind=command_kind,
        payload={},
        status=status,
        ownership_epoch=1,
        created_at=datetime.now(tz=UTC),
        result_payload=result,
    )
