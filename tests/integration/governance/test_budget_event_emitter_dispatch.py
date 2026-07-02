"""Integration: the ``budget`` guard-hook blocks at PreToolUse via the single
governance block owner WebCallBudgetGuard; the observational ``web_call`` counter
is the PostToolUse ``budget`` emitter (AG3-086 migration of FK-30 §30.5.1a).

AG3-086 migration (FK-30 §30.5.1a / FK-68 §68.6.0): the previous double-role
``budget_event_emitter`` PreToolUse BLOCK (AG3-036 §2.1.6) is gone. The runner
now:

- dispatches the PreToolUse ``budget`` guard-hook to
  :class:`agentkit.backend.governance.guard_system.WebCallBudgetGuard` — the SINGLE block
  owner (no double blockade, no wrong owner). A research web call at/above the
  hard budget, AND an UNRESOLVED story type on a web call, are fail-closed BLOCKS
  from the GOVERNANCE owner that emit an ``integrity_violation`` block audit.
- dispatches the PostToolUse ``budget`` hook to the OBSERVATIONAL
  :class:`agentkit.backend.telemetry.hooks.budget_event_emitter.BudgetEventEmitter`,
  which emits the ``web_call`` counter and NEVER blocks.

NO CHEATING: the capability layer runs LIVE (no monkeypatched shim). WebFetch /
WebSearch are a KNOWN, non-mutating READ (FK-55 §55.5), so an ATTESTED worker
issuing a research web read in story scope passes the hard matrix and reaches the
budget guard. ``test_capability_enforcement_is_not_patched_out`` asserts the
proof is real.
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
from agentkit.backend.governance.runner import POST_HOOK_IDS, PRE_HOOK_IDS, run_hook
from agentkit.backend.state_backend.store import reset_backend_cache_for_tests
from agentkit.backend.state_backend.store.story_repository import StateBackendStoryRepository
from agentkit.backend.story_context_manager.story_model import Story, WireStoryType
from agentkit.backend.telemetry.events import Event, EventType, validate_event_payload
from agentkit.backend.telemetry.storage import StateBackendEmitter
from agentkit.harness_client.projectedge.client import LocalEdgePublisher

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
    """Persist the canonical story-type source (Story + StoryContext).

    AG3-129: the hook resolves the story type via the server-mediated story
    detail read (StoryReadPort -> ``load_story_context``), so a StoryContext is
    seeded alongside the Story record the setup path uses.
    """
    from agentkit.backend.state_backend.store.story_context_repository import (
        StateBackendStoryContextRepository,
    )
    from agentkit.backend.story_context_manager.models import StoryContext

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
    _code_types = {WireStoryType.IMPLEMENTATION, WireStoryType.BUGFIX}
    StateBackendStoryContextRepository(project_root).save(
        StoryContext(
            project_key=_PROJECT,
            story_id=_STORY,
            story_type=story_type.value,
            execution_route="execution" if story_type in _code_types else None,
            participating_repos=["repo"],
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


def _query(project_root: Path, event_type: EventType) -> list[Event]:
    story_dir = project_root / "stories" / _STORY
    return StateBackendEmitter(
        story_dir, default_project_key=_PROJECT
    ).query(_STORY, event_type)


# ---------------------------------------------------------------------------
# Hook-id registration (AG3-086): ``budget`` is the PreToolUse block owner and a
# PostToolUse observational emitter; ``budget_event_emitter`` is no longer a
# hook id.
# ---------------------------------------------------------------------------


def test_budget_is_a_pre_and_post_hook() -> None:
    assert "budget" in PRE_HOOK_IDS
    assert "budget" in POST_HOOK_IDS


def test_legacy_budget_event_emitter_is_not_a_hook_id() -> None:
    # The old double-role PreToolUse identifier is removed by the migration.
    assert "budget_event_emitter" not in PRE_HOOK_IDS
    assert "budget_event_emitter" not in POST_HOOK_IDS


def test_capability_enforcement_is_not_patched_out() -> None:
    # Anti-cheat guard: the genuine ``_run_capability_enforcement`` runs here.
    assert (
        runner_mod._run_capability_enforcement.__module__
        == "agentkit.backend.governance.runner"
    )
    assert runner_mod._run_capability_enforcement.__name__ == "_run_capability_enforcement"


def test_webfetch_passes_capability_enforcement_not_unknown_tool(
    tmp_path: Path,
) -> None:
    worktree = str(tmp_path / "worktree")
    _publish_story_binding(tmp_path, worktree)

    capability_block = runner_mod._run_capability_enforcement(
        _web_event(worktree), project_root=tmp_path
    )
    assert capability_block is None


# ---------------------------------------------------------------------------
# PreToolUse ``budget`` -> WebCallBudgetGuard (block owner)
# ---------------------------------------------------------------------------


def test_research_under_budget_allows(tmp_path: Path) -> None:
    worktree = str(tmp_path / "worktree")
    _save_story(tmp_path, WireStoryType.RESEARCH)
    _publish_story_binding(tmp_path, worktree)

    verdict = run_hook("budget", _web_event(worktree), phase="pre", project_root=tmp_path)

    assert verdict.allowed is True
    assert verdict.guard_name == "web_call_budget_guard"
    # The PreToolUse guard writes NO web_call counter (telemetry owns that).
    assert _query(tmp_path, EventType.WEB_CALL) == []
    # An allow path emits NO integrity_violation block audit.
    assert _query(tmp_path, EventType.INTEGRITY_VIOLATION) == []


def test_research_over_budget_denies_from_governance_owner(tmp_path: Path) -> None:
    # AC1b: a single over-budget web call -> EXACTLY ONE block, from the
    # GOVERNANCE owner WebCallBudgetGuard (not the emitter, not the capability
    # layer). The block emits an integrity_violation block audit (AC5b).
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

    verdict = run_hook("budget", _web_event(worktree), phase="pre", project_root=tmp_path)

    assert verdict.allowed is False
    assert verdict.guard_name == "web_call_budget_guard"
    assert "web_call_budget_exceeded" in (verdict.message or "")

    # AC5b: exactly one integrity_violation block audit, guard="web_call_budget_guard",
    # WITHOUT stage, validates green; NO new web_call counter (that is observational).
    violations = _query(tmp_path, EventType.INTEGRITY_VIOLATION)
    assert len(violations) == 1
    assert violations[0].payload["guard"] == "web_call_budget_guard"
    assert "stage" not in violations[0].payload
    validate_event_payload(EventType.INTEGRITY_VIOLATION, violations[0].payload)
    assert len(_query(tmp_path, EventType.WEB_CALL)) == 200  # unchanged by the guard


def test_research_warning_threshold_surfaces_warning_through_dispatch(
    tmp_path: Path,
) -> None:
    # AC1 (SEVERITY-SEMANTIK): a research web call at/above the warning threshold
    # (warning 180 <= count < hard limit 200) ALLOWS but must SURFACE a WARNING
    # through the productive ``run_hook`` dispatch — the warning must not be
    # swallowed. Before the FIX the dispatch returned only ``decision.verdict`` and
    # dropped the warning the guard recorded.
    worktree = str(tmp_path / "worktree")
    _save_story(tmp_path, WireStoryType.RESEARCH)
    _publish_story_binding(tmp_path, worktree)

    story_dir = tmp_path / "stories" / _STORY
    emitter = StateBackendEmitter(story_dir, default_project_key=_PROJECT)
    # 180 prior web calls -> the current (181st) is >= warning (180), < limit (200).
    for i in range(180):
        emitter.emit(
            Event(
                story_id=_STORY,
                event_type=EventType.WEB_CALL,
                project_key=_PROJECT,
                run_id=_RUN,
                payload={"web_call_count": i + 1},
            )
        )

    verdict = run_hook("budget", _web_event(worktree), phase="pre", project_root=tmp_path)

    # The call is ALLOWED (a warning is not a block).
    assert verdict.allowed is True
    assert verdict.guard_name == "web_call_budget_guard"
    # The WARNING is surfaced on the allow verdict (not dropped).
    assert verdict.warning is not None
    assert "web_call_budget_warning" in verdict.warning
    assert verdict.detail is not None
    assert verdict.detail["web_call_count"] == 181
    assert verdict.detail["web_call_warning"] == 180
    assert verdict.detail["web_call_limit"] == 200
    # No block audit on a warning-allow (integrity_violation is for exit-2 blocks).
    assert _query(tmp_path, EventType.INTEGRITY_VIOLATION) == []


def test_research_below_warning_has_no_warning(tmp_path: Path) -> None:
    # The clean under-budget allow carries NO warning (verdict.warning is None).
    worktree = str(tmp_path / "worktree")
    _save_story(tmp_path, WireStoryType.RESEARCH)
    _publish_story_binding(tmp_path, worktree)

    verdict = run_hook("budget", _web_event(worktree), phase="pre", project_root=tmp_path)

    assert verdict.allowed is True
    assert verdict.warning is None


def test_no_double_block_single_over_budget_call(tmp_path: Path) -> None:
    # AC1b: the over-budget call produces exactly ONE block audit (no double
    # blockade from a residual emitter block path).
    worktree = str(tmp_path / "worktree")
    _save_story(tmp_path, WireStoryType.RESEARCH)
    _publish_story_binding(tmp_path, worktree)
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

    run_hook("budget", _web_event(worktree), phase="pre", project_root=tmp_path)

    assert len(_query(tmp_path, EventType.INTEGRITY_VIOLATION)) == 1


def test_non_research_story_allows_web_call(tmp_path: Path) -> None:
    worktree = str(tmp_path / "worktree")
    _save_story(tmp_path, WireStoryType.IMPLEMENTATION)
    _publish_story_binding(tmp_path, worktree)

    verdict = run_hook("budget", _web_event(worktree), phase="pre", project_root=tmp_path)

    assert verdict.allowed is True
    assert verdict.guard_name == "web_call_budget_guard"
    assert _query(tmp_path, EventType.INTEGRITY_VIOLATION) == []


def test_unresolved_story_type_blocks_from_governance_owner(tmp_path: Path) -> None:
    # AC1c: an ACTIVE binding whose story record is UNRESOLVED (binding published
    # but NO Story record saved -> missing record) must fail-closed DENY on the
    # web call FROM the GOVERNANCE owner WebCallBudgetGuard, NOT downgrade to
    # non-research/allow. The behaviour migrated unchanged; only the owner changed.
    worktree = str(tmp_path / "worktree")
    _publish_story_binding(tmp_path, worktree)  # no _save_story -> UNRESOLVED

    verdict = run_hook("budget", _web_event(worktree), phase="pre", project_root=tmp_path)

    assert verdict.allowed is False
    assert verdict.guard_name == "web_call_budget_guard"
    assert "story_type_unresolved" in (verdict.message or "")
    # The unresolved block also emits an integrity_violation audit (AC5b).
    violations = _query(tmp_path, EventType.INTEGRITY_VIOLATION)
    assert len(violations) == 1
    assert violations[0].payload["guard"] == "web_call_budget_guard"
    validate_event_payload(EventType.INTEGRITY_VIOLATION, violations[0].payload)


def test_no_binding_allows(tmp_path: Path) -> None:
    verdict = run_hook(
        "budget",
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


# ---------------------------------------------------------------------------
# PostToolUse ``budget`` -> observational web_call emitter (no block)
# ---------------------------------------------------------------------------


def test_post_budget_emits_web_call_observationally(tmp_path: Path) -> None:
    worktree = str(tmp_path / "worktree")
    _save_story(tmp_path, WireStoryType.RESEARCH)
    _publish_story_binding(tmp_path, worktree)

    verdict = run_hook(
        "budget", _web_event(worktree), phase="post", project_root=tmp_path
    )

    # The observational emitter NEVER blocks.
    assert verdict.allowed is True
    # It emits the web_call counter event (AC1 separation: counter stays here).
    events = _query(tmp_path, EventType.WEB_CALL)
    assert len(events) == 1
    assert events[0].payload["tool"] == "WebFetch"
    # No integrity_violation from the observational path.
    assert _query(tmp_path, EventType.INTEGRITY_VIOLATION) == []


def test_post_budget_websearch_alias_canonicalized(tmp_path: Path) -> None:
    # A ``web-search`` alias canonicalizes to WebSearch BEFORE the _WEB_TOOLS
    # gate, so the observational emitter still records it.
    worktree = str(tmp_path / "worktree")
    _save_story(tmp_path, WireStoryType.RESEARCH)
    _publish_story_binding(tmp_path, worktree)

    run_hook(
        "budget",
        _web_event(worktree, tool_name="web-search"),
        phase="post",
        project_root=tmp_path,
    )

    events = _query(tmp_path, EventType.WEB_CALL)
    assert len(events) == 1
    assert events[0].payload["tool"] == "WebSearch"
