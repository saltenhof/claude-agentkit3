"""End-to-end worker-lifecycle telemetry integration test (AG3-036 §2.1.10).

Drives the seven hooks over a simulated worker run against the real SQLite state
backend, then exports the audit bundle and asserts the six files are produced.
No mocks -- real :class:`StateBackendEmitter`, real :class:`ProjectionAccessor`,
real export, ``tmp_path``.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest

from agentkit.closure.post_merge_finalization.records import StoryMetricsRecord
from agentkit.phase_state_store.models import FlowExecution
from agentkit.state_backend.store import (
    reset_backend_cache_for_tests,
    save_flow_execution,
    save_story_context,
)
from agentkit.state_backend.store.projection_repositories import (
    build_projection_repositories,
)
from agentkit.story_context_manager.models import StoryContext
from agentkit.story_context_manager.types import StoryMode, StoryType
from agentkit.telemetry.audit_bundle import AuditBundleExporter
from agentkit.telemetry.events import EventType
from agentkit.telemetry.hooks import (
    AgentLifecycleHook,
    BudgetEventEmitter,
    CommitHook,
    DivergenceHook,
    DriftCheckHook,
    ReviewGuard,
    ReviewSentinelHook,
)
from agentkit.telemetry.hooks.base import HookContext, HookTrigger
from agentkit.telemetry.projection_accessor import ProjectionAccessor, ProjectionKind
from agentkit.telemetry.storage import StateBackendEmitter

if TYPE_CHECKING:
    from collections.abc import Generator
    from pathlib import Path

_PROJECT = "wl-proj"
_STORY = "AG3-950"
_RUN = "run-950"


@pytest.fixture()
def story_dir(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> Generator[Path, None, None]:
    monkeypatch.setenv("AGENTKIT_STATE_BACKEND", "sqlite")
    monkeypatch.setenv("AGENTKIT_ALLOW_SQLITE", "1")
    reset_backend_cache_for_tests()
    story_dir = tmp_path / "stories" / _STORY
    story_dir.mkdir(parents=True, exist_ok=True)
    save_story_context(
        story_dir,
        StoryContext(
            project_key=_PROJECT,
            story_id=_STORY,
            story_type=StoryType.IMPLEMENTATION,
            execution_route=StoryMode.EXECUTION,
            project_root=tmp_path / _PROJECT,
        ),
    )
    save_flow_execution(
        story_dir,
        FlowExecution(
            project_key=_PROJECT,
            story_id=_STORY,
            run_id=_RUN,
            flow_id="implementation",
            level="story",
            owner="pipeline_engine",
            status="COMPLETED",
        ),
    )
    yield story_dir
    reset_backend_cache_for_tests()


def _ctx(trigger: HookTrigger, **overrides: object) -> HookContext:
    base: dict[str, object] = {
        "trigger": trigger,
        "story_id": _STORY,
        "run_id": _RUN,
        "project_key": _PROJECT,
        "worker_id": "worker-1",
    }
    base.update(overrides)
    return HookContext(**base)  # type: ignore[arg-type]


def test_simulated_worker_run_emits_events_and_exports_bundle(
    story_dir: Path, tmp_path: Path
) -> None:
    emitter = StateBackendEmitter(story_dir, default_project_key=_PROJECT)
    project_root = tmp_path / _PROJECT

    lifecycle = AgentLifecycleHook(emitter)
    sentinel = ReviewSentinelHook(emitter)
    review_guard = ReviewGuard(emitter, required_roles=("qa",))
    commit = CommitHook(emitter)
    drift = DriftCheckHook(emitter, project_root=project_root)
    divergence = DivergenceHook(emitter)
    budget = BudgetEventEmitter(emitter, web_call_limit=200)

    # 1) Worker spawn.
    lifecycle.emit(lifecycle.evaluate(_ctx(HookTrigger.PRE_TOOL_USE, tool="Agent")))

    # 2) Two reviewers respond (divergence) + compliance for qa.
    sentinel.emit(
        sentinel.evaluate(
            _ctx(
                HookTrigger.POST_TOOL_USE,
                tool="chatgpt_send",
                payload={
                    "review_stage": "response",
                    "reviewer_role": "qa",
                    "review_round": 1,
                    "template_name": "qa-v1",
                    "verdict": "PASS",
                },
            )
        )
    )
    divergence.emit(
        divergence.evaluate(
            _ctx(
                HookTrigger.POST_TOOL_USE,
                tool="gemini_send",
                payload={
                    "review_stage": "response",
                    "reviewer_role": "security",
                    "review_round": 1,
                    "verdict": "FAIL",
                },
            )
        )
    )
    sentinel.emit(
        sentinel.evaluate(
            _ctx(
                HookTrigger.POST_TOOL_USE,
                tool="chatgpt_send",
                payload={
                    "review_stage": "compliant",
                    "reviewer_role": "qa",
                    "review_round": 1,
                    "template_name": "qa-v1",
                },
            )
        )
    )

    # 3) ReviewGuard allows the commit (qa compliant since last commit).
    guard_result = review_guard.evaluate(
        _ctx(HookTrigger.PRE_TOOL_USE, tool="Bash", command="git commit -m x")
    )
    review_guard.emit(guard_result)
    assert guard_result.verdict is not None
    assert guard_result.verdict.allowed is True

    # 4) Increment commit + drift check (fail-closed: no design artifact).
    commit.emit(
        commit.evaluate(
            _ctx(
                HookTrigger.POST_TOOL_USE,
                tool="Bash",
                command="git commit -m x",
                payload={"commit_sha": "deadbeef", "files_changed": 2},
            )
        )
    )
    drift.emit(
        drift.evaluate(
            _ctx(HookTrigger.POST_TOOL_USE, tool="Bash", command="git commit -m x")
        )
    )

    # 5) A non-research web call: BudgetEventEmitter stays silent.
    budget_result = budget.evaluate(
        _ctx(HookTrigger.POST_TOOL_USE, tool="WebFetch", story_type="implementation")
    )
    assert budget_result.triggered is False

    # 6) Worker session end.
    lifecycle.emit(
        lifecycle.evaluate(_ctx(HookTrigger.POST_SESSION, outcome="success"))
    )

    # Assert the expected events were persisted.
    emitted_types = {e.event_type for e in emitter.query(_STORY)}
    assert {
        EventType.AGENT_START,
        EventType.AGENT_END,
        EventType.REVIEW_RESPONSE,
        EventType.REVIEW_COMPLIANT,
        EventType.REVIEW_DIVERGENCE,
        EventType.INCREMENT_COMMIT,
        EventType.DRIFT_CHECK,
    } <= emitted_types
    # No web_call for the non-research story (budget hook skipped).
    assert EventType.WEB_CALL not in emitted_types

    drift_events = emitter.query(_STORY, EventType.DRIFT_CHECK)
    assert drift_events[0].payload["reason"] == "no_design_artifact"
    assert drift_events[0].payload["drift_detected"] is False

    # Materialise a completed run + projections, then export the audit bundle.
    accessor = ProjectionAccessor(build_projection_repositories(story_dir))
    accessor.write_projection(
        ProjectionKind.STORY_METRICS,
        StoryMetricsRecord(
            project_key=_PROJECT,
            story_id=_STORY,
            run_id=_RUN,
            story_type="IMPLEMENTATION",
            story_size="M",
            mode="standard",
            processing_time_min=8.0,
            qa_rounds=1,
            increments=1,
            final_status="COMPLETED",
            completed_at=datetime.now(UTC).isoformat(),
        ),
    )

    out_dir = story_dir / "audit-bundle"
    bundle = AuditBundleExporter(accessor, emitter).export(_STORY, _RUN, out_dir)

    produced = {f.name for f in bundle.files} | {bundle.manifest_path.name}
    assert produced == {
        "events.jsonl",
        "qa_stage_results.jsonl",
        "qa_findings.jsonl",
        "story_metrics.json",
        "phase_states.jsonl",
        "manifest.json",
    }

    # The exported events.jsonl contains the worker-lifecycle events.
    event_rows = [
        json.loads(line)
        for line in (out_dir / "events.jsonl")
        .read_text(encoding="utf-8")
        .strip()
        .splitlines()
    ]
    exported_types = {row["event_type"] for row in event_rows}
    assert "agent_start" in exported_types
    assert "agent_end" in exported_types
    assert "review_divergence" in exported_types
