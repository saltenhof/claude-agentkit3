"""Unit tests for :class:`CommitHook` (AG3-036 AC3)."""

from __future__ import annotations

from agentkit.backend.telemetry.emitters import MemoryEmitter
from agentkit.backend.telemetry.events import EventType
from agentkit.backend.telemetry.hooks.base import HookContext, HookTrigger
from agentkit.backend.telemetry.hooks.commit_hook import CommitHook


def _context(**overrides: object) -> HookContext:
    base: dict[str, object] = {
        "trigger": HookTrigger.POST_TOOL_USE,
        "story_id": "AG3-001",
        "run_id": "run-1",
        "project_key": "demo",
        "worker_id": "worker-1",
        "tool": "Bash",
        "command": "git commit -m 'work'",
    }
    base.update(overrides)
    return HookContext(**base)  # type: ignore[arg-type]


def test_increment_commit_emitted_on_git_commit() -> None:
    emitter = MemoryEmitter()
    hook = CommitHook(emitter)

    result = hook.evaluate(
        _context(
            payload={
                "commit_sha": "abc123",
                "repo_name": "demo-repo",
                "files_changed": 3,
            }
        )
    )
    hook.emit(result)

    assert result.triggered is True
    event = result.events[0]
    assert event.event_type is EventType.INCREMENT_COMMIT
    # Mandatory fields (AC3).
    assert event.payload["commit_sha"] == "abc123"
    assert event.payload["repo_name"] == "demo-repo"
    assert event.payload["story_id"] == "AG3-001"
    assert event.payload["worker_id"] == "worker-1"
    assert event.payload["files_changed"] == 3
    assert emitter.all_events[0].event_type is EventType.INCREMENT_COMMIT


def test_non_commit_bash_is_skipped() -> None:
    hook = CommitHook(MemoryEmitter())
    result = hook.evaluate(_context(command="git status"))
    assert result.triggered is False


def test_non_bash_tool_is_skipped() -> None:
    hook = CommitHook(MemoryEmitter())
    result = hook.evaluate(_context(tool="Write", command="git commit"))
    assert result.triggered is False


def test_files_changed_defaults_to_zero_for_bad_value() -> None:
    hook = CommitHook(MemoryEmitter())
    result = hook.evaluate(_context(payload={"files_changed": "not-a-number"}))
    assert result.events[0].payload["files_changed"] == 0
