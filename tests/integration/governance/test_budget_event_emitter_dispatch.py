"""Integration: ``budget_event_emitter`` is REACHED through the REAL production
pre-dispatch — capability enforcement is NOT patched out (AG3-036 FIX-1).

FK-68 §68.6 / AG3-036 §2.1.6: the double-role BudgetEventEmitter owns the
``budget_event_emitter`` pre-hook. The runner resolves the story binding from the
local edge bundle and the AUTHORITATIVE story type from the LOCAL story context
(NOT a forgeable ``operation_args`` payload), builds the emitter over the
canonical state backend and returns its verdict. Only research stories are
budget-gated; a research web call over the hard budget emits ``web_call`` and
DENIES the PreToolUse WebFetch/WebSearch BEFORE it runs. A non-research story is
allowed (no limit).

NO CHEATING (FIX-1): earlier revisions monkeypatched ``_run_capability_enforcement``
to ``None`` so the budget guard could be reached — a FALSE proof that hid the fact
that a web call was hard-blocked as an ``unknown_tool`` UNKNOWN_PERMISSION BEFORE
the budget hook ran. This module runs the FULL ``run_hook`` pre-dispatch with the
capability layer LIVE. The fix that makes the budget guard genuinely reachable:
WebFetch / WebSearch are now a KNOWN, non-mutating READ (FK-55 §55.5 ``read`` /
FK-68 §68.6.1), so an ATTESTED worker (FK-55 §55.3a ``--ak3-principal-attest``)
issuing a research web read inside its story scope passes the hard capability
matrix (worker READ on ``codebase_story_scope``, §55.7.2) and reaches the budget
hook. ``test_capability_enforcement_is_not_patched_out`` asserts the proof is real.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

import pytest

from agentkit.control_plane.models import (
    EdgeBundle,
    EdgePointer,
    SessionRunBindingView,
    StoryExecutionLockView,
)
from agentkit.governance import runner as runner_mod
from agentkit.governance.guard_evaluation import HookEvent
from agentkit.governance.runner import PRE_HOOK_IDS, run_hook
from agentkit.projectedge.client import LocalEdgePublisher
from agentkit.state_backend.store import reset_backend_cache_for_tests
from agentkit.state_backend.store.story_repository import StateBackendStoryRepository
from agentkit.story_context_manager.story_model import Story, WireStoryType
from agentkit.telemetry.events import Event, EventType
from agentkit.telemetry.storage import StateBackendEmitter

if TYPE_CHECKING:
    from collections.abc import Generator
    from pathlib import Path

_PROJECT = "tenant-b"
_STORY = "AG3-200"
_RUN = "run-200"
_SESSION = "sess-002"
#: Structural worker attestation (FK-55 §55.3a). A sub-agent web read is only an
#: attested ``worker`` (matrix READ on story scope) with this CLI marker; without
#: it the resolver fails closed to ``llm_evaluator`` (no capability). Production
#: harness adapters inject this from the spawn context; the dispatch-level test
#: supplies it directly because it bypasses the adapter.
_WORKER_ATTEST = ["--ak3-principal-attest", "worker"]


@pytest.fixture(autouse=True)
def _sqlite_backend(monkeypatch: pytest.MonkeyPatch) -> Generator[None, None, None]:
    monkeypatch.setenv("AGENTKIT_STATE_BACKEND", "sqlite")
    monkeypatch.setenv("AGENTKIT_ALLOW_SQLITE", "1")
    monkeypatch.delenv("AGENTKIT_STATE_DATABASE_URL", raising=False)
    reset_backend_cache_for_tests()
    yield
    reset_backend_cache_for_tests()


def _save_story(project_root: Path, story_type: WireStoryType) -> None:
    """Persist a canonical Story record (the authoritative story-type source)."""
    StateBackendStoryRepository(project_root).save(
        Story(
            project_key=_PROJECT,
            story_number=200,
            story_display_id=_STORY,
            title="t",
            story_type=story_type,
            participating_repos=["repo"],
            created_at=datetime.now(UTC),
        ),
    )


def _publish_story_binding(project_root: Path, worktree: str) -> None:
    now = datetime(2026, 6, 2, 12, 0, tzinfo=UTC)
    bundle = EdgeBundle(
        current=EdgePointer(
            project_key=_PROJECT,
            export_version="edge-002",
            operating_mode="story_execution",
            bundle_dir="_temp/governance/bundles/edge-002",
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
            binding_version="bind-002",
            operating_mode="story_execution",
        ),
        lock=StoryExecutionLockView(
            project_key=_PROJECT,
            story_id=_STORY,
            run_id=_RUN,
            lock_type="story_execution",
            status="ACTIVE",
            worktree_roots=[worktree],
            binding_version="bind-002",
            activated_at=now,
            updated_at=now,
        ),
        qa_lock=None,
    )
    LocalEdgePublisher(project_root=project_root).publish(bundle)


def _web_event(worktree: str, *, tool_name: str = "WebFetch") -> HookEvent:
    """A worker-attested web call inside the story worktree (cwd = story scope)."""
    return HookEvent.model_validate(
        {
            "operation": "unknown_tool",
            "freshness_class": "guarded_read",
            "cwd": worktree,
            "session_id": _SESSION,
            "principal_kind": "subagent",
            "cli_args": _WORKER_ATTEST,
            "operation_args": {"tool_name": tool_name},
        }
    )


def test_budget_event_emitter_is_a_pre_hook() -> None:
    # FIX-3: budget_event_emitter is dispatched in production at PreToolUse.
    assert "budget_event_emitter" in PRE_HOOK_IDS


def test_capability_enforcement_is_not_patched_out() -> None:
    # FIX-1 anti-cheat guard: the genuine ``_run_capability_enforcement`` is the
    # one that runs in these tests (no monkeypatch shim). If a future change
    # re-introduces the patch, this assertion fails.
    assert (
        runner_mod._run_capability_enforcement.__module__
        == "agentkit.governance.runner"
    )
    assert runner_mod._run_capability_enforcement.__name__ == "_run_capability_enforcement"


def test_webfetch_passes_capability_enforcement_not_unknown_tool(
    tmp_path: Path,
) -> None:
    # FIX-1 (d): the SAME WebFetch must NOT be blocked by capability enforcement
    # as an unknown_tool. With WebFetch now a KNOWN READ and an attested worker in
    # story scope, capability enforcement returns None (ALLOW -> proceed).
    worktree = str(tmp_path / "worktree")
    _publish_story_binding(tmp_path, worktree)

    capability_block = runner_mod._run_capability_enforcement(
        _web_event(worktree), project_root=tmp_path
    )

    # None == matrix-permitted (worker READ on story scope). A non-None verdict
    # here would be the unknown_tool / matrix block that hid AC6 before FIX-1.
    assert capability_block is None


def test_research_under_budget_allows_and_emits_web_call(tmp_path: Path) -> None:
    # FIX-1 (a): under-budget research web call -> ALLOW + a web_call event,
    # reached through the LIVE capability layer (not a patched shim).
    worktree = str(tmp_path / "worktree")
    _save_story(tmp_path, WireStoryType.RESEARCH)
    _publish_story_binding(tmp_path, worktree)

    verdict = run_hook(
        "budget_event_emitter",
        _web_event(worktree),
        phase="pre",
        project_root=tmp_path,
    )

    assert verdict.allowed is True
    assert verdict.guard_name == "budget_event_emitter"
    # The web_call telemetry was actually emitted (AC6 observation).
    story_dir = tmp_path / "stories" / _STORY
    events = StateBackendEmitter(
        story_dir, default_project_key=_PROJECT
    ).query(_STORY, EventType.WEB_CALL)
    assert len(events) == 1


def test_research_over_budget_denies_web_call(tmp_path: Path) -> None:
    # FIX-1 (b): over-budget research -> DENY FROM THE BUDGET GUARD (not a
    # capability block). The DENY guard name proves which layer blocked.
    worktree = str(tmp_path / "worktree")
    _save_story(tmp_path, WireStoryType.RESEARCH)
    _publish_story_binding(tmp_path, worktree)

    # Seed the hard limit's worth of prior web calls (default hard limit 200).
    story_dir = tmp_path / "stories" / _STORY
    emitter = StateBackendEmitter(story_dir, default_project_key=_PROJECT)
    for i in range(200):
        emitter.emit(
            Event(
                story_id=_STORY,
                event_type=EventType.WEB_CALL,
                project_key=_PROJECT,
                run_id=_RUN,
                payload={"web_call_count": i + 1},
            )
        )

    verdict = run_hook(
        "budget_event_emitter",
        _web_event(worktree),
        phase="pre",
        project_root=tmp_path,
    )

    # 201 > 200 -> DENY blocks the WebFetch BEFORE it runs (fail-closed). The
    # guard name is the BUDGET guard, NOT principal_capability.
    assert verdict.allowed is False
    assert verdict.guard_name == "budget_event_emitter"
    assert "web_call_budget_exceeded" in (verdict.message or "")


def test_non_research_story_allows_web_call(tmp_path: Path) -> None:
    worktree = str(tmp_path / "worktree")
    _save_story(tmp_path, WireStoryType.IMPLEMENTATION)
    _publish_story_binding(tmp_path, worktree)

    verdict = run_hook(
        "budget_event_emitter",
        _web_event(worktree),
        phase="pre",
        project_root=tmp_path,
    )

    # Non-research story -> no limit applies (allow).
    assert verdict.allowed is True
    assert verdict.guard_name == "budget_event_emitter"


def test_unresolved_story_type_fails_closed_deny(tmp_path: Path) -> None:
    # FIX-1 (c): an ACTIVE binding whose story record is UNRESOLVED (binding
    # published but NO Story record saved -> missing record) must fail-closed DENY
    # on the web call FROM THE BUDGET GUARD, NOT downgrade to non-research/allow.
    worktree = str(tmp_path / "worktree")
    _publish_story_binding(tmp_path, worktree)  # no _save_story -> UNRESOLVED

    verdict = run_hook(
        "budget_event_emitter",
        _web_event(worktree),
        phase="pre",
        project_root=tmp_path,
    )

    assert verdict.allowed is False
    assert verdict.guard_name == "budget_event_emitter"
    assert "story_type_unresolved" in (verdict.message or "")


def test_websearch_alias_canonicalized_and_allowed(tmp_path: Path) -> None:
    # FIX-2: a ``web-search`` alias must canonicalize to WebSearch BEFORE the
    # _WEB_TOOLS gate, so an under-budget research call still ALLOWS + emits (it
    # is NOT silently waved past the budget guard as a non-web tool).
    worktree = str(tmp_path / "worktree")
    _save_story(tmp_path, WireStoryType.RESEARCH)
    _publish_story_binding(tmp_path, worktree)

    verdict = run_hook(
        "budget_event_emitter",
        _web_event(worktree, tool_name="web-search"),
        phase="pre",
        project_root=tmp_path,
    )

    assert verdict.allowed is True
    story_dir = tmp_path / "stories" / _STORY
    events = StateBackendEmitter(
        story_dir, default_project_key=_PROJECT
    ).query(_STORY, EventType.WEB_CALL)
    assert len(events) == 1
    assert events[0].payload["tool"] == "WebSearch"


def test_no_binding_allows(tmp_path: Path) -> None:
    verdict = run_hook(
        "budget_event_emitter",
        HookEvent.model_validate(
            {
                "operation": "unknown_tool",
                "freshness_class": "guarded_read",
                "cwd": str(tmp_path),
                "cli_args": _WORKER_ATTEST,
                "operation_args": {"tool_name": "WebFetch"},
            }
        ),
        phase="pre",
        project_root=tmp_path,
    )
    assert verdict.allowed is True
