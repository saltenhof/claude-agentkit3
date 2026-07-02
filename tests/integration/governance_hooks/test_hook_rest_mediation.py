"""Integration: the hook mediates canonical state over backend REST (AG3-129).

FK-10 §10.1.0 I1/I3: the short-lived hook process is a REST requester at the
core, never a direct-DB writer. These tests drive the REAL hook path over a REAL
plain-HTTP control-plane server bound to a REAL Postgres test schema (no route
mock) and assert:

* AC2 guard-counter record -> persisted server-side via REST;
* AC3 worker-health write+read (pre/post) -> server-mediated;
* AC4 telemetry emit -> lands server-mediated; query round-trips;
* AC5 fail-closed / non-blocking negative paths when the core is unreachable,
  with NO direct-DB fallback.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

import pytest
from tests.integration.governance_hooks.conftest import write_control_plane_config

from agentkit.backend.control_plane.models import (
    EdgeBundle,
    EdgePointer,
    GuardCounterMutationRequest,
    SessionRunBindingView,
    StoryExecutionLockView,
)
from agentkit.backend.governance import runner as runner_mod
from agentkit.backend.governance.guard_evaluation import HookEvent
from agentkit.backend.governance.runner import _resolve_local_story_type, run_hook
from agentkit.backend.state_backend.store import load_execution_events_global
from agentkit.backend.state_backend.store.guard_counter_repository import (
    StateBackendGuardCounterRepository,
)
from agentkit.backend.state_backend.store.worker_health_repository import (
    StateBackendWorkerHealthRepository,
)
from agentkit.backend.telemetry.events import Event, EventType
from agentkit.backend.telemetry.rest_emitter import RestEventEmitter
from agentkit.harness_client.projectedge.client import LocalEdgePublisher
from agentkit.harness_client.projectedge.governance_client import (
    build_governance_edge_client,
)

if TYPE_CHECKING:
    from pathlib import Path

_PROJECT = "tenant-a"
_STORY = "AG3-129"
_RUN = "run-129"
_SESSION = "sess-129"


@pytest.fixture()
def _capability_allows(monkeypatch: pytest.MonkeyPatch) -> None:
    """Let capability enforcement ALLOW so the dedicated branch verdict surfaces."""
    monkeypatch.setattr(
        runner_mod,
        "_run_capability_enforcement",
        lambda event, *, project_root: None,
    )


def _publish_story_binding(project_root: Path, worktree: str) -> None:
    now = datetime(2026, 6, 2, 12, 0, tzinfo=UTC)
    bundle = EdgeBundle(
        current=EdgePointer(
            project_key=_PROJECT,
            export_version="edge-001",
            operating_mode="story_execution",
            bundle_dir="_temp/governance/bundles/edge-001",
            sync_after=now + timedelta(minutes=5),
            freshness_class="guarded_read",
            generated_at=now,
        ),
        session=SessionRunBindingView(
            session_id=_SESSION,
            project_key=_PROJECT,
            story_id=_STORY,
            run_id=_RUN,
            principal_type="worker",
            worktree_roots=[worktree],
            binding_version="bind-001",
            operating_mode="story_execution",
        ),
        lock=StoryExecutionLockView(
            project_key=_PROJECT,
            story_id=_STORY,
            run_id=_RUN,
            lock_type="story_execution",
            status="ACTIVE",
            worktree_roots=[worktree],
            binding_version="bind-001",
            activated_at=now,
            updated_at=now,
        ),
        qa_lock=None,
    )
    LocalEdgePublisher(project_root=project_root).publish(bundle)


def _read_event(worktree: str) -> HookEvent:
    return HookEvent.model_validate(
        {
            "operation": "file_read",
            "freshness_class": "guarded_read",
            "cwd": worktree,
            "session_id": _SESSION,
            "principal_kind": "subagent",
            "operation_args": {"file_path": "src/agentkit/backend/x.py"},
        }
    )


def _health_pre_event(worktree: str) -> HookEvent:
    return HookEvent.model_validate(
        {
            "operation": "file_read",
            "freshness_class": "guarded_read",
            "cwd": worktree,
            "session_id": _SESSION,
            "principal_kind": "subagent",
            "operation_args": {"story_id": _STORY, "file_path": "src/x.py"},
        }
    )


def _health_post_event(worktree: str) -> HookEvent:
    return HookEvent.model_validate(
        {
            "operation": "file_read",
            "freshness_class": "guarded_read",
            "cwd": worktree,
            "session_id": _SESSION,
            "principal_kind": "subagent",
            "operation_args": {
                "story_id": _STORY,
                "file_path": "src/agentkit/backend/x.py",
            },
            "post_tool_outcome": {"exit_code": 0, "stdout": "", "stderr": ""},
        }
    )


# ---------------------------------------------------------------------------
# AC2 -- guard-counter record persisted server-side via REST
# ---------------------------------------------------------------------------


def test_guard_counter_record_persisted_via_rest(
    tmp_path: Path,
    control_plane_base_url: str,
    _capability_allows: None,
) -> None:
    worktree = str(tmp_path / "worktree")
    _publish_story_binding(tmp_path, worktree)
    write_control_plane_config(tmp_path, control_plane_base_url)

    run_hook("orchestrator_guard", _read_event(worktree), project_root=tmp_path)

    rows = StateBackendGuardCounterRepository().read_counters_for_story(
        _PROJECT, _STORY
    )
    row = next(r for r in rows if r.guard_key == "orchestrator_guard")
    assert row.invocations == 1
    assert row.blocks == 0


# ---------------------------------------------------------------------------
# AC3 -- worker-health write + read (pre/post) server-mediated via REST
# ---------------------------------------------------------------------------


def test_worker_health_write_and_read_via_rest(
    tmp_path: Path,
    control_plane_base_url: str,
) -> None:
    worktree = str(tmp_path / "worktree")
    _publish_story_binding(tmp_path, worktree)
    write_control_plane_config(tmp_path, control_plane_base_url)

    # First post: server-mediated load (None) + save (create).
    first = run_hook(
        "health_monitor",
        _health_post_event(worktree),
        phase="post",
        project_root=tmp_path,
    )
    assert first.allowed
    # Second post: proves the server-mediated READ of the prior state (the count
    # increments only if the previously-saved state was loaded via REST).
    second = run_hook(
        "health_monitor",
        _health_post_event(worktree),
        phase="post",
        project_root=tmp_path,
    )
    assert second.allowed

    state = StateBackendWorkerHealthRepository().load(
        story_id=_STORY, worker_id=_SESSION
    )
    assert state is not None
    assert state.tool_call_count == 2


def test_worker_health_pre_reads_seeded_state_via_rest(
    tmp_path: Path,
    control_plane_base_url: str,
    _capability_allows: None,
) -> None:
    worktree = str(tmp_path / "worktree")
    _publish_story_binding(tmp_path, worktree)
    write_control_plane_config(tmp_path, control_plane_base_url)

    # Seed a low-score state directly in the (server-side) backend; the PreToolUse
    # intervention gate must READ it via REST and allow (score below threshold),
    # proving the read round-trip.
    from agentkit.backend.implementation.worker_health.models import AgentHealthState

    seeded = AgentHealthState(
        worker_id=_SESSION, story_id=_STORY, project_key=_PROJECT, total_score=0
    )
    StateBackendWorkerHealthRepository().save(seeded)

    verdict = run_hook(
        "health_monitor",
        _health_pre_event(worktree),
        phase="pre",
        project_root=tmp_path,
    )
    assert verdict.allowed


# ---------------------------------------------------------------------------
# AC4 -- telemetry emit lands server-mediated; query round-trips
# ---------------------------------------------------------------------------


def test_telemetry_emit_and_query_via_rest(
    tmp_path: Path,
    control_plane_base_url: str,
) -> None:
    write_control_plane_config(tmp_path, control_plane_base_url)
    emitter = RestEventEmitter(
        build_governance_edge_client(tmp_path),
        project_key=_PROJECT,
        run_id=_RUN,
    )
    event = Event(
        story_id=_STORY,
        event_type=EventType.INCREMENT_COMMIT,
        project_key=_PROJECT,
        run_id=_RUN,
        payload={"marker": "ag3-129"},
    )

    emitter.emit(event)

    # Server-mediated persistence (canonical global execution-event stream).
    records = load_execution_events_global(_PROJECT, _STORY)
    assert len(records) == 1
    assert records[0].event_type == EventType.INCREMENT_COMMIT.value

    # Server-mediated read (the guard-facing query path).
    events = emitter.query(_STORY, EventType.INCREMENT_COMMIT)
    assert len(events) == 1
    assert events[0].payload == {"marker": "ag3-129"}


# ---------------------------------------------------------------------------
# AC5 -- fail-closed / non-blocking negatives when the core is unreachable
# ---------------------------------------------------------------------------


def test_guard_counter_unreachable_is_non_blocking_no_db_fallback(
    tmp_path: Path,
    unreachable_base_url: str,
    _capability_allows: None,
) -> None:
    worktree = str(tmp_path / "worktree")
    _publish_story_binding(tmp_path, worktree)
    write_control_plane_config(tmp_path, unreachable_base_url)

    # The counter is the pure volume KPI: an unreachable core must NOT block the
    # tool call and must NOT be persisted via a direct-DB back door.
    verdict = run_hook(
        "orchestrator_guard", _read_event(worktree), project_root=tmp_path
    )
    assert verdict.allowed
    assert (
        StateBackendGuardCounterRepository().read_counters_for_story(
            _PROJECT, _STORY
        )
        == []
    )


def test_worker_health_pre_unreachable_fails_closed(
    tmp_path: Path,
    unreachable_base_url: str,
    _capability_allows: None,
) -> None:
    worktree = str(tmp_path / "worktree")
    _publish_story_binding(tmp_path, worktree)
    write_control_plane_config(tmp_path, unreachable_base_url)

    verdict = run_hook(
        "health_monitor",
        _health_pre_event(worktree),
        phase="pre",
        project_root=tmp_path,
    )
    assert not verdict.allowed
    assert "worker_health_unavailable" in (verdict.message or "")


def test_worker_health_post_unreachable_fails_closed(
    tmp_path: Path,
    unreachable_base_url: str,
) -> None:
    worktree = str(tmp_path / "worktree")
    _publish_story_binding(tmp_path, worktree)
    write_control_plane_config(tmp_path, unreachable_base_url)

    verdict = run_hook(
        "health_monitor",
        _health_post_event(worktree),
        phase="post",
        project_root=tmp_path,
    )
    assert not verdict.allowed
    assert "worker_health_unavailable" in (verdict.message or "")


# ---------------------------------------------------------------------------
# Round-3 FUND 1 -- story-type resolved over the REAL story-detail route
# ---------------------------------------------------------------------------


def _seed_project_and_story(story_type: str) -> None:
    """Seed a project + StoryContext in the (server-side) state backend."""
    from agentkit.backend.project_management.entities import ProjectConfiguration
    from agentkit.backend.project_management.lifecycle import create_project
    from agentkit.backend.state_backend.store.project_management_repository import (
        StateBackendProjectRepository,
    )
    from agentkit.backend.state_backend.store.story_context_repository import (
        StateBackendStoryContextRepository,
    )
    from agentkit.backend.story_context_manager.models import StoryContext

    config = ProjectConfiguration(
        repo_url="",
        default_branch="main",
        default_worker_count=1,
        repositories=["repo-a"],
    )
    StateBackendProjectRepository().save(
        create_project(_PROJECT, "Tenant A", "AG3", config, repositories=["repo-a"])
    )
    StateBackendStoryContextRepository().save(
        StoryContext(
            project_key=_PROJECT,
            story_id=_STORY,
            story_type=story_type,
            # StorySummary (the read model behind GET /stories/{id}) requires a
            # non-null execution_route; seed a valid one.
            execution_route="execution",
        )
    )


def test_story_type_resolved_via_real_story_detail_route(
    tmp_path: Path,
    control_plane_base_url: str,
) -> None:
    # FUND 1: the hook resolves the story type over the ACTUAL
    # GET /v1/projects/{key}/stories/{id} route (real backend, no client mock),
    # pinning the ``story_type`` wire key.
    _seed_project_and_story("implementation")
    write_control_plane_config(tmp_path, control_plane_base_url)

    resolution = _resolve_local_story_type(
        _STORY, project_key=_PROJECT, project_root=tmp_path
    )
    assert resolution.resolved is True
    assert resolution.story_type == "implementation"


def test_story_type_missing_record_is_unresolved_via_real_route(
    tmp_path: Path,
    control_plane_base_url: str,
) -> None:
    # FUND 1 (fail-closed): a project that exists but has NO such story record ->
    # 404 story_not_found over the real route -> UNRESOLVED (never a story type).
    _seed_project_and_story("implementation")  # seeds _STORY; we query a missing id
    write_control_plane_config(tmp_path, control_plane_base_url)

    resolution = _resolve_local_story_type(
        "AG3-999", project_key=_PROJECT, project_root=tmp_path
    )
    assert resolution.resolved is False
    assert resolution.story_type == ""


# ---------------------------------------------------------------------------
# Round-3 FUND 2 -- op_id idempotency: a replay does NOT double-count
# ---------------------------------------------------------------------------


def test_guard_counter_replayed_op_id_counts_once_via_rest(
    tmp_path: Path,
    control_plane_base_url: str,
) -> None:
    # FK-91 §91.1a Regel 5: two POSTs with the SAME op_id over the real route +
    # real idempotency_keys store increment the counter EXACTLY once.
    write_control_plane_config(tmp_path, control_plane_base_url)
    client = build_governance_edge_client(tmp_path)
    request = GuardCounterMutationRequest(
        operation="record",
        occurred_at=datetime(2026, 6, 2, 12, 0, tzinfo=UTC),
        op_id="op-replay-1",
        project_key=_PROJECT,
        story_id=_STORY,
        guard_key="orchestrator_guard",
        blocked=False,
    )

    client.mutate_guard_counter(request)
    client.mutate_guard_counter(request)  # replay with the same op_id

    rows = StateBackendGuardCounterRepository().read_counters_for_story(
        _PROJECT, _STORY
    )
    row = next(r for r in rows if r.guard_key == "orchestrator_guard")
    assert row.invocations == 1


def test_guard_counter_op_id_mismatch_conflicts_via_rest(
    tmp_path: Path,
    control_plane_base_url: str,
) -> None:
    # FUND 1: reusing an op_id with a DIFFERENT body over the real route is a
    # fail-closed 409 idempotency_mismatch, not a silent replay of the old result.
    from agentkit.backend.exceptions import ControlPlaneApiError

    write_control_plane_config(tmp_path, control_plane_base_url)
    client = build_governance_edge_client(tmp_path)
    occurred = datetime(2026, 6, 2, 12, 0, tzinfo=UTC)
    client.mutate_guard_counter(
        GuardCounterMutationRequest(
            operation="record", occurred_at=occurred, op_id="op-mismatch-1",
            project_key=_PROJECT, story_id=_STORY, guard_key="orchestrator_guard",
            blocked=True,
        )
    )
    with pytest.raises(ControlPlaneApiError) as exc_info:
        client.mutate_guard_counter(
            GuardCounterMutationRequest(
                operation="record", occurred_at=occurred, op_id="op-mismatch-1",
                project_key=_PROJECT, story_id=_STORY,
                guard_key="orchestrator_guard", blocked=False,  # body differs
            )
        )
    assert exc_info.value.error_code == "idempotency_mismatch"


def test_guard_counter_record_is_atomic_rolls_back_on_key_save_failure(
    postgres_isolated_schema: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # FUND 2: the counter increment and the idempotency key commit in ONE
    # transaction. A failure AT the key-save (after the counter upsert) rolls the
    # WHOLE transaction back -> no counted-but-unkeyed row -> the next clean retry
    # counts EXACTLY once (no double-count, no lost increment).
    _ = postgres_isolated_schema
    from agentkit.backend.state_backend.store.guard_counter_repository import (
        StateBackendGuardCounterRepository,
    )

    repo = StateBackendGuardCounterRepository()
    now = datetime(2026, 6, 2, 12, 0, tzinfo=UTC)
    call_kwargs = {
        "op_id": "op-atomic-1",
        "body_hash": "hash-1",
        "result_payload": {"status": "accepted", "operation": "record", "drained": 0},
        "project_key": _PROJECT,
        "story_id": _STORY,
        "guard_key": "orchestrator_guard",
        "week_start": "2026-06-01",
        "blocked": False,
        "updated_at": now,
        "created_at": now,
    }
    original = StateBackendGuardCounterRepository._insert_idempotency_row

    def _boom(conn: object, **_kw: object) -> None:
        raise RuntimeError("simulated crash before the idempotency key is saved")

    monkeypatch.setattr(
        StateBackendGuardCounterRepository,
        "_insert_idempotency_row",
        staticmethod(_boom),
    )
    with pytest.raises(RuntimeError, match="simulated crash"):
        repo.record_invocation_idempotent(**call_kwargs)  # type: ignore[arg-type]

    # Rolled back: the counter upsert did NOT persist.
    assert repo.read_counters_for_story(_PROJECT, _STORY) == []

    # Restore the real key-save and retry the SAME op_id: counts exactly once.
    monkeypatch.setattr(
        StateBackendGuardCounterRepository,
        "_insert_idempotency_row",
        staticmethod(original),
    )
    outcome = repo.record_invocation_idempotent(**call_kwargs)  # type: ignore[arg-type]
    assert outcome.status == "recorded"
    rows = repo.read_counters_for_story(_PROJECT, _STORY)
    assert sum(r.invocations for r in rows) == 1


def _gc_repo() -> object:
    from agentkit.backend.state_backend.store.guard_counter_repository import (
        StateBackendGuardCounterRepository,
    )

    return StateBackendGuardCounterRepository()


def _gc_record(
    repo: object, *, op_id: str, body_hash: str, week_start: str, now: datetime
) -> object:
    return repo.record_invocation_idempotent(  # type: ignore[attr-defined]
        op_id=op_id,
        body_hash=body_hash,
        result_payload={"status": "accepted", "operation": "record", "drained": 0},
        project_key=_PROJECT,
        story_id=_STORY,
        guard_key="orchestrator_guard",
        week_start=week_start,
        blocked=False,
        updated_at=now,
        created_at=now,
    )


def _current_week(now: datetime) -> str:
    from agentkit.backend.kpi_analytics.fact_store.guard_counter import week_start_for

    return week_start_for(now)


def _invocations_for_week(repo: object, week: str) -> int:
    rows = repo.read_counters_for_story(_PROJECT, _STORY)  # type: ignore[attr-defined]
    return sum(r.invocations for r in rows if r.week_start == week)


def _has_week(repo: object, week: str) -> bool:
    rows = repo.read_counters_for_story(_PROJECT, _STORY)  # type: ignore[attr-defined]
    return any(r.week_start == week for r in rows)


def test_guard_counter_duplicate_op_id_hits_unique_gate_and_replays(
    postgres_isolated_schema: str,
) -> None:
    # FUND 1 (c): a second record with the SAME op_id hits the real unique
    # constraint on op_id -> the transaction rolls back and resolves to a REPLAY,
    # NOT a silent DO-NOTHING that leaves the counter double-counted.
    _ = postgres_isolated_schema
    repo = _gc_repo()
    now = datetime(2026, 6, 2, 12, 0, tzinfo=UTC)
    week = _current_week(now)

    first = _gc_record(repo, op_id="op-dup-1", body_hash="hA", week_start=week, now=now)
    second = _gc_record(repo, op_id="op-dup-1", body_hash="hA", week_start=week, now=now)

    assert first.status == "recorded"  # type: ignore[attr-defined]
    assert second.status == "replayed"  # type: ignore[attr-defined]
    assert _invocations_for_week(repo, week) == 1  # counted exactly once


def test_guard_counter_replay_has_no_drain_or_recount(
    postgres_isolated_schema: str,
) -> None:
    # FUND 2 (b): a replayed op_id neither re-increments the counter NOR drains
    # older-week buckets (zero counter side effect).
    _ = postgres_isolated_schema
    repo = _gc_repo()
    now = datetime(2026, 6, 2, 12, 0, tzinfo=UTC)
    week = _current_week(now)
    old_week = "2026-05-18"

    _gc_record(repo, op_id="op-rep-1", body_hash="hA", week_start=week, now=now)
    # Seed a fresh older-week bucket AFTER the first record; a replay must NOT drain it.
    repo.upsert_invocation(  # type: ignore[attr-defined]
        project_key=_PROJECT, story_id=_STORY, guard_key="orchestrator_guard",
        week_start=old_week, blocked=False, updated_at=now,
    )

    replay = _gc_record(repo, op_id="op-rep-1", body_hash="hA", week_start=week, now=now)

    assert replay.status == "replayed"  # type: ignore[attr-defined]
    assert _invocations_for_week(repo, week) == 1  # no re-count
    assert _has_week(repo, old_week)  # older bucket NOT drained by the replay


def test_guard_counter_mismatch_has_no_drain_or_count(
    postgres_isolated_schema: str,
) -> None:
    # FUND 2 (a): a 409 mismatch (same op_id, different body) has zero counter
    # side effect -- no drain of older buckets, no increment.
    _ = postgres_isolated_schema
    repo = _gc_repo()
    now = datetime(2026, 6, 2, 12, 0, tzinfo=UTC)
    week = _current_week(now)
    old_week = "2026-05-18"

    _gc_record(repo, op_id="op-mm-1", body_hash="hA", week_start=week, now=now)
    repo.upsert_invocation(  # type: ignore[attr-defined]
        project_key=_PROJECT, story_id=_STORY, guard_key="orchestrator_guard",
        week_start=old_week, blocked=False, updated_at=now,
    )

    mismatch = _gc_record(repo, op_id="op-mm-1", body_hash="hB", week_start=week, now=now)

    assert mismatch.status == "mismatch"  # type: ignore[attr-defined]
    assert _invocations_for_week(repo, week) == 1  # no extra count
    assert _has_week(repo, old_week)  # older bucket NOT drained by the mismatch
