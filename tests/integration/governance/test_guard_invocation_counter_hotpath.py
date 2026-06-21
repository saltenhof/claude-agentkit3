"""Integration: the guard-invocation counter hot-path (FK-61 §61.4.3, AG3-081 AC5).

``governance.runner.run_hook`` is the ONE shared collection point through which
EVERY PreToolUse guard invocation flows. AG3-081 records ONE
``guard_invocation_counters`` UPSERT around the pre-hook dispatch so EVERY branch
is counted — both the generic ``evaluate_pre_tool_use`` fallback AND the dedicated
early-returning branches (capability enforcement, review_guard, self_protection,
...). A placement inside ``evaluate_pre_tool_use`` alone would miss the dedicated
paths (the "every guard-hook" rule). The counter is the volume-KPI numerator; the
audit trail (``integrity_violation`` events) is unaffected.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

import pytest

from agentkit.backend.control_plane.models import (
    EdgeBundle,
    EdgePointer,
    SessionRunBindingView,
    StoryExecutionLockView,
)
from agentkit.backend.governance import runner as runner_mod
from agentkit.backend.governance.guard_evaluation import HookEvent
from agentkit.backend.governance.runner import run_hook
from agentkit.backend.state_backend.store import reset_backend_cache_for_tests
from agentkit.backend.state_backend.store.guard_counter_repository import (
    StateBackendGuardCounterRepository,
)
from agentkit.harness_client.projectedge.client import LocalEdgePublisher

if TYPE_CHECKING:
    from collections.abc import Generator
    from pathlib import Path

    from agentkit.backend.kpi_analytics.fact_store.models import GuardInvocationCounter

_PROJECT = "tenant-a"
_STORY = "AG3-200"
_RUN = "run-200"
_SESSION = "sess-200"


@pytest.fixture(autouse=True)
def _sqlite_backend(monkeypatch: pytest.MonkeyPatch) -> Generator[None, None, None]:
    monkeypatch.setenv("AGENTKIT_STATE_BACKEND", "sqlite")
    monkeypatch.setenv("AGENTKIT_ALLOW_SQLITE", "1")
    monkeypatch.delenv("AGENTKIT_STATE_DATABASE_URL", raising=False)
    reset_backend_cache_for_tests()
    yield
    reset_backend_cache_for_tests()


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


def _commit_event(worktree: str) -> HookEvent:
    return HookEvent.model_validate(
        {
            "operation": "bash_command",
            "freshness_class": "guarded_read",
            "cwd": worktree,
            "session_id": _SESSION,
            "principal_kind": "subagent",
            "operation_args": {"command": "git commit -m 'inc'"},
        }
    )


def _counters(project_root: Path) -> list[GuardInvocationCounter]:
    return StateBackendGuardCounterRepository(project_root).read_counters_for_story(
        _PROJECT, _STORY
    )


def _counter_for(project_root: Path, guard_key: str) -> GuardInvocationCounter | None:
    for row in _counters(project_root):
        if row.guard_key == guard_key:
            return row
    return None


# ---------------------------------------------------------------------------
# AC5 (a): a generic guard via evaluate_pre_tool_use -> invocation count
# ---------------------------------------------------------------------------


def test_generic_pre_hook_records_invocation(
    tmp_path: Path, _capability_allows: None
) -> None:
    worktree = str(tmp_path / "worktree")
    _publish_story_binding(tmp_path, worktree)

    # ``orchestrator_guard`` flows through the generic evaluate_pre_tool_use path.
    run_hook("orchestrator_guard", _read_event(worktree), project_root=tmp_path)

    row = _counter_for(tmp_path, "orchestrator_guard")
    assert row is not None
    assert row.invocations == 1
    assert row.blocks == 0


# ---------------------------------------------------------------------------
# AC5 (b): dedicated early-returning branches each record an invocation
# ---------------------------------------------------------------------------


def test_dedicated_review_guard_branch_records_invocation(
    tmp_path: Path, _capability_allows: None
) -> None:
    worktree = str(tmp_path / "worktree")
    _publish_story_binding(tmp_path, worktree)

    # ``review_guard`` is a dedicated early-returning branch that bypasses
    # evaluate_pre_tool_use; it must still be counted ("Jeder Guard-Hook").
    run_hook("review_guard", _commit_event(worktree), project_root=tmp_path)

    row = _counter_for(tmp_path, "review_guard")
    assert row is not None
    assert row.invocations == 1


def test_dedicated_self_protection_branch_records_invocation(
    tmp_path: Path, _capability_allows: None
) -> None:
    worktree = str(tmp_path / "worktree")
    _publish_story_binding(tmp_path, worktree)

    run_hook("self_protection", _read_event(worktree), project_root=tmp_path)

    row = _counter_for(tmp_path, "self_protection")
    assert row is not None
    assert row.invocations == 1


# ---------------------------------------------------------------------------
# AC5 (c): two different guards -> two counter rows
# ---------------------------------------------------------------------------


def test_two_different_guards_record_two_counters(
    tmp_path: Path, _capability_allows: None
) -> None:
    worktree = str(tmp_path / "worktree")
    _publish_story_binding(tmp_path, worktree)

    run_hook("orchestrator_guard", _read_event(worktree), project_root=tmp_path)
    run_hook("self_protection", _read_event(worktree), project_root=tmp_path)

    keys = {row.guard_key for row in _counters(tmp_path)}
    assert "orchestrator_guard" in keys
    assert "self_protection" in keys


def test_same_guard_twice_increments_invocations(
    tmp_path: Path, _capability_allows: None
) -> None:
    worktree = str(tmp_path / "worktree")
    _publish_story_binding(tmp_path, worktree)

    run_hook("orchestrator_guard", _read_event(worktree), project_root=tmp_path)
    run_hook("orchestrator_guard", _read_event(worktree), project_root=tmp_path)

    row = _counter_for(tmp_path, "orchestrator_guard")
    assert row is not None
    assert row.invocations == 2


# ---------------------------------------------------------------------------
# AC5 (d): a BLOCK verdict -> blocks += 1
# ---------------------------------------------------------------------------


def test_capability_block_records_block(tmp_path: Path) -> None:
    # Capability enforcement is NOT bypassed here: a synthetic worktree default-
    # denies the dedicated branch, producing a BLOCK verdict -> blocks += 1.
    worktree = str(tmp_path / "worktree")
    _publish_story_binding(tmp_path, worktree)

    verdict = run_hook("review_guard", _commit_event(worktree), project_root=tmp_path)

    assert not verdict.allowed  # capability DENY blocked the commit
    rows = _counters(tmp_path)
    assert rows, "a blocked pre-hook must still be counted"
    assert sum(r.blocks for r in rows) >= 1


def test_no_binding_records_no_counter(tmp_path: Path, _capability_allows: None) -> None:
    # FK-61 §61.4.3: the scratchpad is story/run-scoped. With no published story
    # binding (ai_augmented / no run) a pre-hook records no counter row.
    worktree = str(tmp_path / "worktree")
    run_hook("orchestrator_guard", _read_event(worktree), project_root=tmp_path)

    assert _counters(tmp_path) == []


# ---------------------------------------------------------------------------
# AC5 Trigger 3 (Housekeeping): the operational PostToolUse health-monitor tick
# sweeps guard counters older than 24h without update (aborted/escalating
# stories), while leaving fresh counters live.
# ---------------------------------------------------------------------------


def _health_post_event(worktree: str) -> HookEvent:
    return HookEvent.model_validate(
        {
            "operation": "file_read",
            "freshness_class": "guarded_read",
            "cwd": worktree,
            "session_id": _SESSION,
            "principal_kind": "subagent",
            "operation_args": {"story_id": _STORY, "file_path": "src/agentkit/backend/x.py"},
            "post_tool_outcome": {"exit_code": 0, "stdout": "", "stderr": ""},
        }
    )


def test_health_monitor_post_hook_sweeps_stale_counters(tmp_path: Path) -> None:
    from agentkit.backend.kpi_analytics.fact_store.guard_counter import (
        HOUSEKEEPING_MAX_AGE,
        GuardCounterService,
    )

    worktree = str(tmp_path / "worktree")
    _publish_story_binding(tmp_path, worktree)
    repo = StateBackendGuardCounterRepository(tmp_path)
    service = GuardCounterService(repo)
    # The operational sweep uses the real wall clock for its cutoff, so seed
    # relative to ``now(UTC)`` (not a fixed instant) to stay deterministic.
    now = datetime.now(UTC)

    # A stale counter (>24h) of a stranded/escalated story that never reached
    # Closure, plus a FRESH counter of an active story.
    service.record_invocation(
        project_key=_PROJECT,
        story_id="STRANDED-001",
        guard_key="self_protection",
        blocked=False,
        now=now - HOUSEKEEPING_MAX_AGE - timedelta(hours=1),
    )
    service.record_invocation(
        project_key=_PROJECT,
        story_id="ACTIVE-002",
        guard_key="self_protection",
        blocked=False,
        now=now,
    )
    assert len(repo.read_counters_for_story(_PROJECT, "STRANDED-001")) == 1
    assert len(repo.read_counters_for_story(_PROJECT, "ACTIVE-002")) == 1

    # The operational PostToolUse health-monitor tick runs the Housekeeping sweep.
    verdict = run_hook(
        "health_monitor", _health_post_event(worktree), phase="post", project_root=tmp_path
    )

    assert verdict.allowed  # observational tick, never a block
    # Stale counter swept; fresh counter survives.
    assert repo.read_counters_for_story(_PROJECT, "STRANDED-001") == []
    assert len(repo.read_counters_for_story(_PROJECT, "ACTIVE-002")) == 1
