"""Integration: AG3-147 hard push barriers at REAL phase boundaries (AC1/AC2/AC3).

Drives the PUBLIC :class:`ControlPlaneRuntimeService` API against real Postgres
with pipeline state produced by a REAL predecessor path (a genuine
``start_phase(setup)`` mints the active ownership the boundary then requires) --
never hand-assembled. The two-stage barrier evidence is supplied by an injected
:class:`PushBarrierEvidencePort` fake carrying prepared per-repo inputs, so the
test controls exactly the (edge-report, server-ref-read) pair the A-core
aggregates. Covers:

* AC1 -- both single negative paths: (a) edge reports pushed but the server head
  SHA mismatches, (b) the server head resolves but there is NO edge report. The
  Edge report alone is never sufficient.
* AC2 -- the phase-completion AND the closure-entry boundary types, each a hard
  fail-closed barrier on a real boundary.
* AC3 -- multi-repo: one un-verified repo blocks even when all others are verified.

``tests/integration/control_plane/`` is NOT auto-attached to the Postgres
fixture, so this module requests it explicitly.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

import pytest

from agentkit.backend.control_plane.models import (
    ClosureCompleteRequest,
    CommandErrorResult,
    EdgeCommandResultRequest,
    PhaseMutationRequest,
    PushStatusReport,
)
from agentkit.backend.control_plane.push_sync import (
    PushBarrierVerdict,
    PushBarrierVerdictStatus,
    RepoPushVerificationInput,
    SyncPointBarrierType,
)
from agentkit.backend.control_plane.runtime import ControlPlaneRuntimeService
from agentkit.backend.state_backend.store import (
    append_execution_event_global,
    boot_backend_instance_identity_global,
    load_edge_command_record_global,
    load_push_barrier_verdict_global,
    save_story_context_global,
    upsert_push_barrier_verdict_global,
)
from agentkit.backend.story_context_manager.models import StoryContext
from agentkit.backend.story_context_manager.types import StoryMode, StoryType
from agentkit.backend.telemetry.contract.records import ExecutionEventRecord

if TYPE_CHECKING:
    from pathlib import Path

pytestmark = pytest.mark.integration

_T0 = datetime(2026, 7, 6, 10, 0, tzinfo=UTC)
_PROJECT = "tenant-a"
_SHA_X = "x" * 40
_SHA_Y = "y" * 40


@pytest.fixture(autouse=True)
def _isolated_postgres(postgres_isolated_schema: object) -> None:
    del postgres_isolated_schema


@dataclass(frozen=True)
class _FakeBarrierPort:
    inputs: tuple[RepoPushVerificationInput, ...]

    def collect_repo_inputs(
        self,
        *,
        project_key: str,
        story_id: str,
        run_id: str,
        required_sync_point_id: str | None = None,
    ) -> tuple[RepoPushVerificationInput, ...]:
        del project_key, story_id, run_id
        return tuple(
            replace(
                inp,
                edge_report_sync_point_id=(inp.edge_report_sync_point_id or required_sync_point_id),
                required_sync_point_id=required_sync_point_id,
            )
            for inp in self.inputs
        )


class _AdmittedDispatcher:
    def dispatch(
        self,
        *,
        ctx: object,
        phase: str,
        run_id: str,
        run_admitted: bool,
        detail: dict[str, object] | None = None,
    ) -> object:
        from agentkit.backend.control_plane.models import PhaseDispatchResult

        del ctx, run_id, run_admitted, detail
        return PhaseDispatchResult(
            phase=phase,
            status="phase_completed",
            reaction="advance",
            dispatched=True,
            next_phase="implementation",
        )


class _YieldingDispatcher:
    """A dispatcher whose resume RE-PAUSES the phase (yields to the worker)."""

    def dispatch(
        self,
        *,
        ctx: object,
        phase: str,
        run_id: str,
        run_admitted: bool,
        detail: dict[str, object] | None = None,
    ) -> object:
        from agentkit.backend.control_plane.models import PhaseDispatchResult

        del ctx, run_id, run_admitted, detail
        return PhaseDispatchResult(
            phase=phase,
            status="yielded",
            reaction="run_worker",
            dispatched=True,
        )


class _FailingCommissionRepo:
    def commission_command(self, record: object) -> bool:
        del record
        raise RuntimeError("commission boom")


@dataclass
class _MutableBarrierPort:
    inputs: tuple[RepoPushVerificationInput, ...]

    def collect_repo_inputs(
        self,
        *,
        project_key: str,
        story_id: str,
        run_id: str,
        required_sync_point_id: str | None = None,
    ) -> tuple[RepoPushVerificationInput, ...]:
        return _FakeBarrierPort(self.inputs).collect_repo_inputs(
            project_key=project_key,
            story_id=story_id,
            run_id=run_id,
            required_sync_point_id=required_sync_point_id,
        )


def _verified(repo_id: str) -> RepoPushVerificationInput:
    return RepoPushVerificationInput(
        repo_id=repo_id,
        edge_report_present=True,
        edge_reported_pushed=True,
        edge_reported_head_sha=_SHA_X,
        server_ref_resolved=True,
        server_head_sha=_SHA_X,
    )


def _server_mismatch(repo_id: str) -> RepoPushVerificationInput:
    return RepoPushVerificationInput(
        repo_id=repo_id,
        edge_report_present=True,
        edge_reported_pushed=True,
        edge_reported_head_sha=_SHA_X,
        server_ref_resolved=True,
        server_head_sha=_SHA_Y,  # server does not confirm the edge-reported head
    )


def _no_edge_report(repo_id: str) -> RepoPushVerificationInput:
    return RepoPushVerificationInput(
        repo_id=repo_id,
        edge_report_present=False,  # server would pass, but NO edge report
        edge_reported_pushed=False,
        edge_reported_head_sha=None,
        server_ref_resolved=True,
        server_head_sha=_SHA_X,
    )


def _seed_story_context(tmp_path: Path, story_id: str, *, participating_repos: list[str] | None = None) -> None:
    project_root = tmp_path / _PROJECT
    (project_root / "stories" / story_id).mkdir(parents=True, exist_ok=True)
    save_story_context_global(
        None,
        StoryContext(
            project_key=_PROJECT,
            story_id=story_id,
            story_type=StoryType.IMPLEMENTATION,
            execution_route=StoryMode.EXECUTION,
            project_root=project_root,
            participating_repos=participating_repos or ["api"],
        ),
    )


def _request(*, story_id: str, op_id: str, session_id: str = "sess-A") -> PhaseMutationRequest:
    return PhaseMutationRequest(
        project_key=_PROJECT,
        story_id=story_id,
        session_id=session_id,
        op_id=op_id,
        principal_type="orchestrator",
        worktree_roots=[f"T:/worktrees/{story_id}"],
    )


def _service(
    inputs: tuple[RepoPushVerificationInput, ...],
    *,
    ident: str,
    edge_command_repository: object | None = None,
) -> ControlPlaneRuntimeService:
    identity = boot_backend_instance_identity_global(ident, _T0)
    return ControlPlaneRuntimeService(
        phase_dispatcher=_AdmittedDispatcher(),  # type: ignore[arg-type]
        now_fn=lambda: _T0,
        instance_identity=identity,
        edge_command_repository=edge_command_repository,  # type: ignore[arg-type]
        push_barrier_evidence=_FakeBarrierPort(inputs),  # type: ignore[arg-type]
    )


def _service_with_mutable_barrier(barrier: _MutableBarrierPort, *, ident: str) -> ControlPlaneRuntimeService:
    identity = boot_backend_instance_identity_global(ident, _T0)
    return ControlPlaneRuntimeService(
        phase_dispatcher=_AdmittedDispatcher(),  # type: ignore[arg-type]
        now_fn=lambda: _T0,
        instance_identity=identity,
        push_barrier_evidence=barrier,  # type: ignore[arg-type]
    )


def _admit_run(service: ControlPlaneRuntimeService, *, story_id: str, run_id: str) -> None:
    """Mint the active ownership via a REAL setup start (not hand-assembled)."""
    result = service.start_phase(
        run_id=run_id,
        phase="setup",
        request=_request(story_id=story_id, op_id=f"op-setup-{story_id}"),
    )
    assert result.status == "committed"


def _command_error_request(*, story_id: str, op_id: str) -> EdgeCommandResultRequest:
    return EdgeCommandResultRequest(
        project_key=_PROJECT,
        story_id=story_id,
        session_id="sess-A",
        op_id=op_id,
        result=CommandErrorResult(
            error_code="sync_push_failed",
            message="sync_push failed: transient remote error",
        ),
    )


def _push_result_request(*, story_id: str, op_id: str) -> EdgeCommandResultRequest:
    return EdgeCommandResultRequest(
        project_key=_PROJECT,
        story_id=story_id,
        session_id="sess-A",
        op_id=op_id,
        result=PushStatusReport(
            repo_id="api",
            push_outcome="pushed",
            head_sha=_SHA_X,
        ),
    )


# ---------------------------------------------------------------------------
# AC1 / AC2 phase-completion barrier
# ---------------------------------------------------------------------------


def test_phase_completion_barrier_blocks_when_server_head_mismatches_edge(tmp_path: Path) -> None:
    """AC1(a): edge reports a push but the server ref-read does not confirm it."""
    story_id, run_id = "AG3-901", "run-901"
    _seed_story_context(tmp_path, story_id)
    service = _service((_server_mismatch("api"),), ident="inst-901")
    _admit_run(service, story_id=story_id, run_id=run_id)

    result = service.complete_phase(
        run_id=run_id,
        phase="implementation",
        request=_request(story_id=story_id, op_id="op-complete-901"),
    )

    assert result.status == "rejected"
    assert result.phase_dispatch is not None
    assert "push_barrier_unverified" in (result.phase_dispatch.rejection_reason or "")


def test_phase_completion_barrier_blocks_when_no_edge_report(tmp_path: Path) -> None:
    """AC1(b): the server head resolves but there is NO edge report -> block."""
    story_id, run_id = "AG3-902", "run-902"
    _seed_story_context(tmp_path, story_id)
    service = _service((_no_edge_report("api"),), ident="inst-902")
    _admit_run(service, story_id=story_id, run_id=run_id)

    result = service.complete_phase(
        run_id=run_id,
        phase="implementation",
        request=_request(story_id=story_id, op_id="op-complete-902"),
    )

    assert result.status == "rejected"
    assert "push_barrier_unverified" in (result.phase_dispatch.rejection_reason or "")


def test_phase_completion_barrier_blocks_stale_edge_report(tmp_path: Path) -> None:
    """Regression: stale running-latest freshness is ignored by the verdict SSOT."""
    story_id, run_id = "AG3-905", "run-905"
    _seed_story_context(tmp_path, story_id)
    stale = replace(_verified("api"), edge_report_sync_point_id="phase_completion:old")
    service = _service((stale,), ident="inst-905")
    _admit_run(service, story_id=story_id, run_id=run_id)

    result = service.complete_phase(
        run_id=run_id,
        phase="implementation",
        request=_request(story_id=story_id, op_id="op-complete-905"),
    )

    assert result.status == "rejected"
    reason = result.phase_dispatch.rejection_reason if result.phase_dispatch else ""
    assert "no_edge_push_report" in (reason or "")


def test_phase_completion_commissions_sync_push_before_block(tmp_path: Path) -> None:
    """M1: the hard boundary queues ``sync_push`` so the barrier has a producer."""
    story_id, run_id = "AG3-912", "run-912"
    _seed_story_context(tmp_path, story_id, participating_repos=["api"])
    service = _service((_no_edge_report("api"),), ident="inst-912")
    _admit_run(service, story_id=story_id, run_id=run_id)

    result = service.complete_phase(
        run_id=run_id,
        phase="implementation",
        request=_request(story_id=story_id, op_id="op-complete-912"),
    )

    assert result.status == "rejected"
    command = load_edge_command_record_global("run-912::sync_push::phase_completion:run-912:epoch-1::api")
    assert command is not None
    assert command.command_kind == "sync_push"
    assert command.payload["repo_id"] == "api"


def test_phase_completion_commission_failure_warns_and_still_blocks(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    """Best-effort commission exceptions do not escape or open the boundary."""
    story_id, run_id = "AG3-913", "run-913"
    _seed_story_context(tmp_path, story_id, participating_repos=["api"])
    service = _service(
        (_no_edge_report("api"),),
        ident="inst-913",
        edge_command_repository=_FailingCommissionRepo(),
    )
    _admit_run(service, story_id=story_id, run_id=run_id)

    with caplog.at_level(logging.WARNING):
        result = service.complete_phase(
            run_id=run_id,
            phase="implementation",
            request=_request(story_id=story_id, op_id="op-complete-913"),
        )

    assert result.status == "rejected"
    assert "push_barrier_unverified" in (result.phase_dispatch.rejection_reason or "")
    assert "sync_push commissioning failed before barrier" in caplog.text


def test_phase_completion_retry_after_failed_sync_push_eventually_passes(
    tmp_path: Path,
) -> None:
    """R4: a terminal failed ``sync_push`` does not deadlock the same boundary."""
    story_id, run_id = "AG3-914", "run-914"
    _seed_story_context(tmp_path, story_id, participating_repos=["api"])
    barrier = _MutableBarrierPort((_no_edge_report("api"),))
    service = _service_with_mutable_barrier(barrier, ident="inst-914")
    _admit_run(service, story_id=story_id, run_id=run_id)
    request = _request(story_id=story_id, op_id="op-complete-914")
    base_command_id = "run-914::sync_push::phase_completion:run-914:epoch-1::api"

    first = service.complete_phase(run_id=run_id, phase="implementation", request=request)
    assert first.status == "rejected"
    assert load_edge_command_record_global(base_command_id) is not None

    failed = service.submit_command_result(
        base_command_id,
        _command_error_request(story_id=story_id, op_id="edge-op-failed-914"),
    )
    assert failed.status == "completed"
    second = service.complete_phase(run_id=run_id, phase="implementation", request=request)
    assert second.status == "rejected"
    retry_command_id = "run-914::sync_push::phase_completion:run-914:epoch-2::api"
    assert load_edge_command_record_global(retry_command_id) is not None

    pushed = service.submit_command_result(
        retry_command_id,
        _push_result_request(story_id=story_id, op_id="edge-op-pushed-914"),
    )
    assert pushed.status == "completed"
    barrier.inputs = (_verified("api"),)

    third = service.complete_phase(run_id=run_id, phase="implementation", request=request)
    assert third.status == "committed"


def test_phase_completion_open_sync_push_timeout_rebinds_boundary_epoch(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A stale open sync_push command is escalated and superseded by a retry epoch."""
    from agentkit.backend.control_plane import push_barrier_lifecycle

    story_id, run_id = "AG3-925", "run-925"
    _seed_story_context(tmp_path, story_id, participating_repos=["api"])
    service = _service((_no_edge_report("api"),), ident="inst-925")
    _admit_run(service, story_id=story_id, run_id=run_id)
    request = _request(story_id=story_id, op_id="op-complete-925")
    monkeypatch.setattr(push_barrier_lifecycle, "OPEN_SYNC_PUSH_TIMEOUT", timedelta(seconds=0))

    first = service.complete_phase(run_id=run_id, phase="implementation", request=request)
    assert first.status == "rejected"
    base_command_id = "run-925::sync_push::phase_completion:run-925:epoch-1::api"
    assert load_edge_command_record_global(base_command_id) is not None

    second = service.complete_phase(
        run_id=run_id,
        phase="implementation",
        request=_request(story_id=story_id, op_id="op-complete-925-timeout"),
    )
    assert second.status == "rejected"
    blocked = load_push_barrier_verdict_global(
        project_key=_PROJECT,
        story_id=story_id,
        run_id=run_id,
        boundary_type=SyncPointBarrierType.PHASE_COMPLETION,
        boundary_id=run_id,
        repo_id="api",
    )
    assert blocked is not None
    assert blocked.status is PushBarrierVerdictStatus.BLOCKED_BACKLOG
    assert blocked.status_detail == "sync_push_command_timed_out"
    superseded_command = load_edge_command_record_global(base_command_id)
    assert superseded_command is not None
    assert superseded_command.status == "superseded"
    assert superseded_command.result_type == "command_superseded"

    third = service.complete_phase(
        run_id=run_id,
        phase="implementation",
        request=_request(story_id=story_id, op_id="op-complete-925-retry"),
    )
    assert third.status == "rejected"
    retry_command_id = "run-925::sync_push::phase_completion:run-925:epoch-2::api"
    assert load_edge_command_record_global(retry_command_id) is not None


def test_phase_completion_malformed_passed_without_expected_head_blocks(
    tmp_path: Path,
) -> None:
    """Regression: nullable expected_head_sha on PASSED cannot pass as None == None."""
    story_id, run_id = "AG3-927", "run-927"
    _seed_story_context(tmp_path, story_id, participating_repos=["api"])
    service = _service((_no_edge_report("api"),), ident="inst-927")
    _admit_run(service, story_id=story_id, run_id=run_id)
    upsert_push_barrier_verdict_global(
        PushBarrierVerdict(
            project_key=_PROJECT,
            story_id=story_id,
            run_id=run_id,
            boundary_type=SyncPointBarrierType.PHASE_COMPLETION,
            boundary_id=run_id,
            repo_id="api",
            producer="control_plane.push_barrier",
            boundary_epoch=1,
            expected_head_sha=None,
            server_head_sha=None,
            ownership_epoch=1,
            status=PushBarrierVerdictStatus.PASSED,
            created_at=_T0,
            updated_at=_T0,
            resolved_at=_T0,
            status_detail="malformed_test_fixture",
        )
    )

    result = service.complete_phase(
        run_id=run_id,
        phase="implementation",
        request=_request(story_id=story_id, op_id="op-complete-927"),
    )

    assert result.status == "rejected"
    blocked = load_push_barrier_verdict_global(
        project_key=_PROJECT,
        story_id=story_id,
        run_id=run_id,
        boundary_type=SyncPointBarrierType.PHASE_COMPLETION,
        boundary_id=run_id,
        repo_id="api",
    )
    assert blocked is not None
    assert blocked.status is PushBarrierVerdictStatus.BLOCKED_BACKLOG
    assert blocked.status_detail == "passed_verdict_missing_expected_head"


def test_registered_commit_invalidates_pending_boundary_epoch(tmp_path: Path) -> None:
    """A productive AK3 commit supersedes pending verdicts mechanically."""
    story_id, run_id = "AG3-921", "run-921"
    _seed_story_context(tmp_path, story_id, participating_repos=["api"])
    service = _service((_verified("api"),), ident="inst-921")
    _admit_run(service, story_id=story_id, run_id=run_id)

    first = service.complete_phase(
        run_id=run_id,
        phase="implementation",
        request=_request(story_id=story_id, op_id="op-complete-921"),
    )
    assert first.status == "rejected"

    append_execution_event_global(
        ExecutionEventRecord(
            project_key=_PROJECT,
            story_id=story_id,
            run_id=run_id,
            event_id="commit-921",
            event_type="increment_commit",
            occurred_at=_T0,
            source_component="commit_hook",
            severity="info",
            phase="implementation",
            payload={"repo_name": "api", "commit_sha": _SHA_Y},
        )
    )
    superseded = load_push_barrier_verdict_global(
        project_key=_PROJECT,
        story_id=story_id,
        run_id=run_id,
        boundary_type=SyncPointBarrierType.PHASE_COMPLETION,
        boundary_id=run_id,
        repo_id="api",
    )
    assert superseded is not None
    assert superseded.status is PushBarrierVerdictStatus.SUPERSEDED
    assert superseded.boundary_epoch == 2
    assert superseded.expected_head_sha == _SHA_Y

    stale = service.submit_command_result(
        "run-921::sync_push::phase_completion:run-921:epoch-1::api",
        _push_result_request(story_id=story_id, op_id="edge-op-stale-921"),
    )
    assert stale.status == "completed"
    still_superseded = load_push_barrier_verdict_global(
        project_key=_PROJECT,
        story_id=story_id,
        run_id=run_id,
        boundary_type=SyncPointBarrierType.PHASE_COMPLETION,
        boundary_id=run_id,
        repo_id="api",
    )
    assert still_superseded is not None
    assert still_superseded.status is PushBarrierVerdictStatus.SUPERSEDED


def test_registered_commit_invalidates_passed_boundary_epoch(tmp_path: Path) -> None:
    """Regression: productive commits supersede stale PASS verdicts too."""
    story_id, run_id = "AG3-924", "run-924"
    _seed_story_context(tmp_path, story_id, participating_repos=["api"])
    service = _service((_verified("api"),), ident="inst-924")
    _admit_run(service, story_id=story_id, run_id=run_id)
    first = service.complete_phase(
        run_id=run_id,
        phase="implementation",
        request=_request(story_id=story_id, op_id="op-complete-924"),
    )
    assert first.status == "rejected"
    pushed = service.submit_command_result(
        "run-924::sync_push::phase_completion:run-924:epoch-1::api",
        _push_result_request(story_id=story_id, op_id="edge-op-pushed-924"),
    )
    assert pushed.status == "completed"
    passed = load_push_barrier_verdict_global(
        project_key=_PROJECT,
        story_id=story_id,
        run_id=run_id,
        boundary_type=SyncPointBarrierType.PHASE_COMPLETION,
        boundary_id=run_id,
        repo_id="api",
    )
    assert passed is not None
    assert passed.status is PushBarrierVerdictStatus.PASSED

    append_execution_event_global(
        ExecutionEventRecord(
            project_key=_PROJECT,
            story_id=story_id,
            run_id=run_id,
            event_id="commit-924",
            event_type="increment_commit",
            occurred_at=_T0,
            source_component="commit_hook",
            severity="info",
            phase="implementation",
            payload={"repo_name": "api", "commit_sha": _SHA_Y},
        )
    )

    superseded = load_push_barrier_verdict_global(
        project_key=_PROJECT,
        story_id=story_id,
        run_id=run_id,
        boundary_type=SyncPointBarrierType.PHASE_COMPLETION,
        boundary_id=run_id,
        repo_id="api",
    )
    assert superseded is not None
    assert superseded.status is PushBarrierVerdictStatus.SUPERSEDED
    assert superseded.boundary_epoch == 2
    assert superseded.expected_head_sha == _SHA_Y


def test_registered_commit_with_missing_metadata_invalidates_all_live_boundaries(
    tmp_path: Path,
) -> None:
    """Missing hook metadata degrades fail-closed instead of leaving PASS usable."""
    story_id, run_id = "AG3-926", "run-926"
    _seed_story_context(tmp_path, story_id, participating_repos=["api", "web"])
    service = _service((_verified("api"), _verified("web")), ident="inst-926")
    _admit_run(service, story_id=story_id, run_id=run_id)

    first = service.complete_phase(
        run_id=run_id,
        phase="implementation",
        request=_request(story_id=story_id, op_id="op-complete-926"),
    )
    assert first.status == "rejected"
    for repo in ("api", "web"):
        pushed = service.submit_command_result(
            f"run-926::sync_push::phase_completion:run-926:epoch-1::{repo}",
            EdgeCommandResultRequest(
                project_key=_PROJECT,
                story_id=story_id,
                session_id="sess-A",
                op_id=f"edge-op-{repo}-926",
                result=PushStatusReport(
                    repo_id=repo,
                    push_outcome="pushed",
                    head_sha=_SHA_X,
                ),
            ),
        )
        assert pushed.status == "completed"
    committed = service.complete_phase(
        run_id=run_id,
        phase="implementation",
        request=_request(story_id=story_id, op_id="op-complete-926-pass"),
    )
    assert committed.status == "committed"

    append_execution_event_global(
        ExecutionEventRecord(
            project_key=_PROJECT,
            story_id=story_id,
            run_id=run_id,
            event_id="commit-926",
            event_type="increment_commit",
            occurred_at=_T0,
            source_component="commit_hook",
            severity="info",
            phase="implementation",
            payload={},
        )
    )

    for repo in ("api", "web"):
        superseded = load_push_barrier_verdict_global(
            project_key=_PROJECT,
            story_id=story_id,
            run_id=run_id,
            boundary_type=SyncPointBarrierType.PHASE_COMPLETION,
            boundary_id=run_id,
            repo_id=repo,
        )
        assert superseded is not None
        assert superseded.status is PushBarrierVerdictStatus.SUPERSEDED
        assert superseded.boundary_epoch == 2
        assert superseded.expected_head_sha is None


def test_late_result_with_stale_ownership_epoch_is_fenced(tmp_path: Path) -> None:
    """A result tagged with a stale ownership epoch cannot satisfy the boundary."""
    story_id, run_id = "AG3-922", "run-922"
    _seed_story_context(tmp_path, story_id, participating_repos=["api"])
    service = _service((_verified("api"),), ident="inst-922")
    _admit_run(service, story_id=story_id, run_id=run_id)
    first = service.complete_phase(
        run_id=run_id,
        phase="implementation",
        request=_request(story_id=story_id, op_id="op-complete-922"),
    )
    assert first.status == "rejected"

    result = service.submit_command_result(
        "run-922::sync_push::phase_completion:run-922:epoch-1::api",
        EdgeCommandResultRequest(
            project_key=_PROJECT,
            story_id=story_id,
            session_id="sess-A",
            op_id="edge-op-stale-owner-922",
            result=PushStatusReport(
                repo_id="api",
                push_outcome="pushed",
                head_sha=_SHA_X,
                boundary_type="phase_completion",
                boundary_id=run_id,
                boundary_epoch=1,
                ownership_epoch=999,
            ),
        ),
    )
    assert result.status == "completed"
    verdict = load_push_barrier_verdict_global(
        project_key=_PROJECT,
        story_id=story_id,
        run_id=run_id,
        boundary_type=SyncPointBarrierType.PHASE_COMPLETION,
        boundary_id=run_id,
        repo_id="api",
    )
    assert verdict is not None
    assert verdict.status is PushBarrierVerdictStatus.PENDING


def test_phase_completion_barrier_passes_when_verified(tmp_path: Path) -> None:
    """The barrier passes (commits) when the repo is server-verified-pushed."""
    story_id, run_id = "AG3-903", "run-903"
    _seed_story_context(tmp_path, story_id)
    service = _service((_verified("api"),), ident="inst-903")
    _admit_run(service, story_id=story_id, run_id=run_id)

    result = service.complete_phase(
        run_id=run_id,
        phase="implementation",
        request=_request(story_id=story_id, op_id="op-complete-903"),
    )

    assert result.status == "rejected"
    command_id = "run-903::sync_push::phase_completion:run-903:epoch-1::api"
    still_waiting = service.complete_phase(
        run_id=run_id,
        phase="implementation",
        request=_request(story_id=story_id, op_id="op-complete-903-still-waiting"),
    )
    assert still_waiting.status == "rejected"
    pending = load_push_barrier_verdict_global(
        project_key=_PROJECT,
        story_id=story_id,
        run_id=run_id,
        boundary_type=SyncPointBarrierType.PHASE_COMPLETION,
        boundary_id=run_id,
        repo_id="api",
    )
    assert pending is not None
    assert pending.status is PushBarrierVerdictStatus.PENDING
    pushed = service.submit_command_result(
        command_id,
        _push_result_request(story_id=story_id, op_id="edge-op-pushed-903"),
    )
    assert pushed.status == "completed"
    result = service.complete_phase(
        run_id=run_id,
        phase="implementation",
        request=_request(story_id=story_id, op_id="op-complete-903-retry"),
    )

    assert result.status == "committed"


def test_setup_completion_is_not_gated_by_the_push_barrier(tmp_path: Path) -> None:
    """The barrier is scoped to the code-bearing implementation phase: a setup
    completion (nothing pushed yet) is NOT fail-closed-blocked."""
    story_id, run_id = "AG3-904", "run-904"
    _seed_story_context(tmp_path, story_id)
    # Blocking evidence, yet a setup completion must pass (not a gated phase).
    service = _service((_no_edge_report("api"),), ident="inst-904")
    _admit_run(service, story_id=story_id, run_id=run_id)

    result = service.complete_phase(
        run_id=run_id,
        phase="setup",
        request=_request(story_id=story_id, op_id="op-complete-setup-904"),
    )

    assert result.status == "committed"


# ---------------------------------------------------------------------------
# AC3 multi-repo teildivergenz
# ---------------------------------------------------------------------------


def test_phase_completion_barrier_blocks_on_one_unverified_repo(tmp_path: Path) -> None:
    """AC3: one un-verified repo blocks even when every other repo is verified."""
    story_id, run_id = "AG3-905", "run-905"
    _seed_story_context(tmp_path, story_id, participating_repos=["api", "web", "infra"])
    service = _service(
        (_verified("api"), _server_mismatch("web"), _verified("infra")),
        ident="inst-905",
    )
    _admit_run(service, story_id=story_id, run_id=run_id)

    result = service.complete_phase(
        run_id=run_id,
        phase="implementation",
        request=_request(story_id=story_id, op_id="op-complete-905"),
    )

    assert result.status == "rejected"
    for repo, op in (("api", "edge-op-api-905"), ("web", "edge-op-web-905"), ("infra", "edge-op-infra-905")):
        pushed = service.submit_command_result(
            f"run-905::sync_push::phase_completion:run-905:epoch-1::{repo}",
            EdgeCommandResultRequest(
                project_key=_PROJECT,
                story_id=story_id,
                session_id="sess-A",
                op_id=op,
                result=PushStatusReport(
                    repo_id=repo,
                    push_outcome="pushed",
                    head_sha=_SHA_X,
                ),
            ),
        )
        assert pushed.status == "completed"
    result = service.complete_phase(
        run_id=run_id,
        phase="implementation",
        request=_request(story_id=story_id, op_id="op-complete-905-retry"),
    )

    assert result.status == "rejected"
    reason = result.phase_dispatch.rejection_reason or ""
    assert "push_barrier_unverified" in reason
    assert "web" in reason  # the blocking repo is named


# ---------------------------------------------------------------------------
# AC2 / AC12 closure-entry barrier
# ---------------------------------------------------------------------------


def _closure_request(*, story_id: str, op_id: str) -> ClosureCompleteRequest:
    return ClosureCompleteRequest(
        project_key=_PROJECT,
        story_id=story_id,
        session_id="sess-A",
        op_id=op_id,
    )


def test_closure_entry_barrier_blocks_unverified_push(tmp_path: Path) -> None:
    """AC2/AC12: closure entry is fail-closed-blocked when the story branch is
    not server-verified-pushed in a participating repo (SOLL-190)."""
    story_id, run_id = "AG3-906", "run-906"
    _seed_story_context(tmp_path, story_id)
    service = _service((_server_mismatch("api"),), ident="inst-906")
    _admit_run(service, story_id=story_id, run_id=run_id)

    result = service.complete_closure(
        run_id=run_id,
        request=_closure_request(story_id=story_id, op_id="op-closure-906"),
    )

    assert result.status == "rejected"
    assert "push_barrier_unverified" in (result.phase_dispatch.rejection_reason or "")


def test_closure_entry_barrier_blocks_when_no_edge_report(tmp_path: Path) -> None:
    """AC1(b)/AC2: closure entry blocks when only the server ref-read is present."""
    story_id, run_id = "AG3-916", "run-916"
    _seed_story_context(tmp_path, story_id)
    service = _service((_no_edge_report("api"),), ident="inst-916")
    _admit_run(service, story_id=story_id, run_id=run_id)

    result = service.complete_closure(
        run_id=run_id,
        request=_closure_request(story_id=story_id, op_id="op-closure-916"),
    )

    assert result.status == "rejected"
    reason = result.phase_dispatch.rejection_reason or ""
    assert "push_barrier_unverified" in reason
    assert "no_edge_push_report" in reason


def test_closure_entry_barrier_passes_when_verified(tmp_path: Path) -> None:
    """Closure proceeds past the barrier when every repo is server-verified-pushed."""
    story_id, run_id = "AG3-907", "run-907"
    _seed_story_context(tmp_path, story_id)
    service = _service((_verified("api"),), ident="inst-907")
    _admit_run(service, story_id=story_id, run_id=run_id)

    result = service.complete_closure(
        run_id=run_id,
        request=_closure_request(story_id=story_id, op_id="op-closure-907"),
    )

    assert result.status == "rejected"
    command_id = "run-907::sync_push::closure_entry:run-907:epoch-1::api"
    pushed = service.submit_command_result(
        command_id,
        _push_result_request(story_id=story_id, op_id="edge-op-pushed-907"),
    )
    assert pushed.status == "completed"
    result = service.complete_closure(
        run_id=run_id,
        request=_closure_request(story_id=story_id, op_id="op-closure-907"),
    )

    assert result.status == "committed"


def test_phase_completion_verdict_does_not_satisfy_closure_entry_boundary(
    tmp_path: Path,
) -> None:
    """Phase-completion and closure-entry are distinct boundary verdicts."""
    story_id, run_id = "AG3-923", "run-923"
    _seed_story_context(tmp_path, story_id, participating_repos=["api"])
    service = _service((_verified("api"),), ident="inst-923")
    _admit_run(service, story_id=story_id, run_id=run_id)
    upsert_push_barrier_verdict_global(
        PushBarrierVerdict(
            project_key=_PROJECT,
            story_id=story_id,
            run_id=run_id,
            boundary_type=SyncPointBarrierType.PHASE_COMPLETION,
            boundary_id=run_id,
            repo_id="api",
            producer="test",
            boundary_epoch=1,
            expected_head_sha=_SHA_X,
            server_head_sha=_SHA_X,
            ownership_epoch=1,
            status=PushBarrierVerdictStatus.PASSED,
            created_at=_T0,
            updated_at=_T0,
            resolved_at=_T0,
            status_detail="phase-completion only",
        )
    )

    result = service.complete_closure(
        run_id=run_id,
        request=_closure_request(story_id=story_id, op_id="op-closure-923"),
    )

    assert result.status == "rejected"
    reason = result.phase_dispatch.rejection_reason if result.phase_dispatch else ""
    assert "push_barrier_unverified" in (reason or "")


# ---------------------------------------------------------------------------
# AC2 yield-point barrier (a phase that RE-PAUSES/yields to the worker)
# ---------------------------------------------------------------------------


def test_yield_point_barrier_blocks_unverified_push(tmp_path: Path) -> None:
    """AC2: a resume that yields (re-pauses) is fail-closed-blocked until the
    current state is server-verified-pushed -- a takeover during the yield can
    never lose unpushed work."""
    story_id, run_id = "AG3-908", "run-908"
    _seed_story_context(tmp_path, story_id)
    identity = boot_backend_instance_identity_global("inst-908", _T0)
    setup = ControlPlaneRuntimeService(
        phase_dispatcher=_AdmittedDispatcher(),  # type: ignore[arg-type]
        now_fn=lambda: _T0,
        instance_identity=identity,
    )
    _admit_run(setup, story_id=story_id, run_id=run_id)
    resume_svc = ControlPlaneRuntimeService(
        phase_dispatcher=_YieldingDispatcher(),  # type: ignore[arg-type]
        now_fn=lambda: _T0,
        instance_identity=identity,
        push_barrier_evidence=_FakeBarrierPort((_server_mismatch("api"),)),  # type: ignore[arg-type]
    )

    result = resume_svc.resume_phase(
        run_id=run_id,
        phase="implementation",
        request=_request(story_id=story_id, op_id="op-resume-908"),
    )

    assert result.status == "rejected"
    assert result.phase_dispatch is not None
    assert "push_barrier_unverified" in (result.phase_dispatch.rejection_reason or "")


def test_yield_point_barrier_blocks_when_no_edge_report(tmp_path: Path) -> None:
    """AC1(b)/AC2: yield-point blocks when the Edge report is absent."""
    story_id, run_id = "AG3-918", "run-918"
    _seed_story_context(tmp_path, story_id)
    identity = boot_backend_instance_identity_global("inst-918", _T0)
    setup = ControlPlaneRuntimeService(
        phase_dispatcher=_AdmittedDispatcher(),  # type: ignore[arg-type]
        now_fn=lambda: _T0,
        instance_identity=identity,
    )
    _admit_run(setup, story_id=story_id, run_id=run_id)
    resume_svc = ControlPlaneRuntimeService(
        phase_dispatcher=_YieldingDispatcher(),  # type: ignore[arg-type]
        now_fn=lambda: _T0,
        instance_identity=identity,
        push_barrier_evidence=_FakeBarrierPort((_no_edge_report("api"),)),  # type: ignore[arg-type]
    )

    result = resume_svc.resume_phase(
        run_id=run_id,
        phase="implementation",
        request=_request(story_id=story_id, op_id="op-resume-918"),
    )

    assert result.status == "rejected"
    reason = result.phase_dispatch.rejection_reason or ""
    assert "push_barrier_unverified" in reason
    assert "no_edge_push_report" in reason


def test_yield_point_barrier_passes_when_verified(tmp_path: Path) -> None:
    """A verified push lets the phase yield (re-pause) normally."""
    story_id, run_id = "AG3-909", "run-909"
    _seed_story_context(tmp_path, story_id)
    identity = boot_backend_instance_identity_global("inst-909", _T0)
    setup = ControlPlaneRuntimeService(
        phase_dispatcher=_AdmittedDispatcher(),  # type: ignore[arg-type]
        now_fn=lambda: _T0,
        instance_identity=identity,
    )
    _admit_run(setup, story_id=story_id, run_id=run_id)
    resume_svc = ControlPlaneRuntimeService(
        phase_dispatcher=_YieldingDispatcher(),  # type: ignore[arg-type]
        now_fn=lambda: _T0,
        instance_identity=identity,
        push_barrier_evidence=_FakeBarrierPort((_verified("api"),)),  # type: ignore[arg-type]
    )

    result = resume_svc.resume_phase(
        run_id=run_id,
        phase="implementation",
        request=_request(story_id=story_id, op_id="op-resume-909"),
    )

    assert result.status == "rejected"
    command_id = "run-909::sync_push::yield_point:run-909:implementation:epoch-1::api"
    pushed = resume_svc.submit_command_result(
        command_id,
        _push_result_request(story_id=story_id, op_id="edge-op-pushed-909"),
    )
    assert pushed.status == "completed"
    result = resume_svc.resume_phase(
        run_id=run_id,
        phase="implementation",
        request=_request(story_id=story_id, op_id="op-resume-909"),
    )

    assert result.status == "committed"
