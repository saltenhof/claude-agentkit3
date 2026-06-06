"""Unit tests for :class:`DriftCheckHook` (AG3-036 AC7, fail-closed)."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from agentkit.telemetry.emitters import MemoryEmitter
from agentkit.telemetry.events import EventType
from agentkit.telemetry.hooks.base import HookContext, HookTrigger
from agentkit.telemetry.hooks.drift_check_hook import DriftCheckHook

if TYPE_CHECKING:
    from pathlib import Path


def _context(**overrides: object) -> HookContext:
    base: dict[str, object] = {
        "trigger": HookTrigger.POST_TOOL_USE,
        "story_id": "AG3-001",
        "run_id": "run-1",
        "project_key": "demo",
        "tool": "Bash",
        "command": "git commit -m 'inc'",
    }
    base.update(overrides)
    return HookContext(**base)  # type: ignore[arg-type]


def _write_design_artifact(project_root: Path, story_id: str) -> None:
    artifact_dir = project_root / "_temp" / "qa" / story_id
    artifact_dir.mkdir(parents=True, exist_ok=True)
    (artifact_dir / "entwurfsartefakt.json").write_text(
        json.dumps({"change_frame": {}}), encoding="utf-8"
    )


def test_drift_detected_true_with_artifact_and_payload(tmp_path: Path) -> None:
    _write_design_artifact(tmp_path, "AG3-001")
    emitter = MemoryEmitter()
    hook = DriftCheckHook(emitter, project_root=tmp_path)

    result = hook.evaluate(_context(payload={"drift_detected": True}))
    hook.emit(result)

    assert result.events[0].event_type is EventType.DRIFT_CHECK
    assert result.events[0].payload["drift_detected"] is True
    assert emitter.all_events[0].event_type is EventType.DRIFT_CHECK


def test_no_drift_with_artifact(tmp_path: Path) -> None:
    _write_design_artifact(tmp_path, "AG3-001")
    hook = DriftCheckHook(MemoryEmitter(), project_root=tmp_path)
    result = hook.evaluate(_context(payload={"drift_detected": False}))
    assert result.events[0].payload["drift_detected"] is False


def test_missing_artifact_is_fail_closed_not_silent(tmp_path: Path) -> None:
    # No design artifact written -> fail-closed event, NOT a silent pass.
    hook = DriftCheckHook(MemoryEmitter(), project_root=tmp_path)
    result = hook.evaluate(_context(payload={"drift_detected": True}))

    assert result.triggered is True
    event = result.events[0]
    assert event.event_type is EventType.DRIFT_CHECK
    assert event.payload["drift_detected"] is False
    assert event.payload["reason"] == "no_design_artifact"


def test_non_commit_is_skipped(tmp_path: Path) -> None:
    hook = DriftCheckHook(MemoryEmitter(), project_root=tmp_path)
    result = hook.evaluate(_context(command="git status"))
    assert result.triggered is False
