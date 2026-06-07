"""Integration: the change-frame freeze guard via the REAL productive hook path.

ERROR-2 fix (FK-23 §23.4.3 / AG3-047): proves the productive
``evaluate_pre_tool_use`` path -- NOT a direct ``ArtifactGuard.evaluate`` call --
keys the exploration change-frame protection on the PERSISTED freeze state.

The guard-context builder resolves the freeze signals from the on-disk
``_temp/qa/{story_id}/change_frame.json`` (via the ``projectedge`` R-boundary
read). This test drives the full ``evaluate_pre_tool_use`` against a real
published edge bundle and a real change-frame file and proves:

* (i)   a PRE-FREEZE sub-agent write to ``change_frame.json`` is ALLOWED (the
        persisted frame is known + not frozen -- editable, FK-25 §25.4.2);
* (ii)  a POST-FREEZE write is BLOCKED (known + frozen);
* (iii) an UNREADABLE / corrupt freeze-state file still blocks fail-closed
        (unknown freeze state is never read as "not frozen", ARCH-48 default deny).
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

from agentkit.control_plane.models import (
    EdgeBundle,
    EdgePointer,
    SessionRunBindingView,
    StoryExecutionLockView,
)
from agentkit.core_types.qa_artifact_names import CHANGE_FRAME_FILE
from agentkit.governance.guard_evaluation import HookEvent, evaluate_pre_tool_use
from agentkit.governance.protocols import ViolationType
from agentkit.installer.paths import qa_story_dir
from agentkit.projectedge.client import LocalEdgePublisher

if TYPE_CHECKING:
    from pathlib import Path

_STORY_ID = "AG3-100"


def _bundle(*, worktree_root: str) -> EdgeBundle:
    now = datetime(2026, 6, 7, 12, 0, tzinfo=UTC)
    return EdgeBundle(
        current=EdgePointer(
            project_key="tenant-a",
            export_version="edge-001",
            operating_mode="story_execution",
            bundle_dir="_temp/governance/bundles/edge-001",
            sync_after=now + timedelta(minutes=5),
            freshness_class="guarded_read",
            generated_at=now,
        ),
        session=SessionRunBindingView(
            session_id="sess-001",
            project_key="tenant-a",
            story_id=_STORY_ID,
            run_id="run-100",
            principal_type="orchestrator",
            worktree_roots=[worktree_root],
            binding_version="bind-001",
            operating_mode="story_execution",
        ),
        lock=StoryExecutionLockView(
            project_key="tenant-a",
            story_id=_STORY_ID,
            run_id="run-100",
            lock_type="story_execution",
            status="ACTIVE",
            worktree_roots=[worktree_root],
            binding_version="bind-001",
            activated_at=now,
            updated_at=now,
        ),
        qa_lock=StoryExecutionLockView(
            project_key="tenant-a",
            story_id=_STORY_ID,
            run_id="run-100",
            lock_type="qa_artifact_write",
            status="ACTIVE",
            worktree_roots=[worktree_root],
            binding_version="bind-001",
            activated_at=now,
            updated_at=now,
        ),
    )


def _change_frame_path(project_root: Path) -> Path:
    path = qa_story_dir(project_root, _STORY_ID) / CHANGE_FRAME_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def _subagent_write_event(project_root: Path, worktree: Path) -> HookEvent:
    return HookEvent(
        operation="file_write",
        operation_args={
            "file_path": str(qa_story_dir(project_root, _STORY_ID) / CHANGE_FRAME_FILE)
        },
        freshness_class="mutation",
        cwd=str(worktree),
        session_id="sess-001",
        principal_kind="subagent",
    )


def test_pre_freeze_subagent_write_is_allowed(tmp_path: Path) -> None:
    """(i) Pre-freeze (persisted frame not frozen) -> sub-agent write ALLOWED."""
    worktree = tmp_path / "worktree"
    LocalEdgePublisher(project_root=tmp_path).publish(
        _bundle(worktree_root=str(worktree))
    )
    _change_frame_path(tmp_path).write_text(
        json.dumps({"frozen": False}), encoding="utf-8"
    )

    verdict = evaluate_pre_tool_use(
        _subagent_write_event(tmp_path, worktree), project_root=tmp_path
    )

    assert verdict.allowed is True


def test_post_freeze_subagent_write_is_blocked(tmp_path: Path) -> None:
    """(ii) Post-freeze (persisted frame frozen) -> sub-agent write BLOCKED."""
    worktree = tmp_path / "worktree"
    LocalEdgePublisher(project_root=tmp_path).publish(
        _bundle(worktree_root=str(worktree))
    )
    _change_frame_path(tmp_path).write_text(
        json.dumps({"frozen": True}), encoding="utf-8"
    )

    verdict = evaluate_pre_tool_use(
        _subagent_write_event(tmp_path, worktree), project_root=tmp_path
    )

    assert verdict.allowed is False
    assert verdict.guard_name == "artifact_guard"
    assert verdict.violation_type is ViolationType.ARTIFACT_TAMPERING


def test_unreadable_freeze_state_blocks_fail_closed(tmp_path: Path) -> None:
    """(iii) Corrupt/unreadable freeze-state file -> BLOCKED fail-closed."""
    worktree = tmp_path / "worktree"
    LocalEdgePublisher(project_root=tmp_path).publish(
        _bundle(worktree_root=str(worktree))
    )
    # Present but not valid JSON -> "unreadable" -> freeze_known unset -> block.
    _change_frame_path(tmp_path).write_text("{ not json", encoding="utf-8")

    verdict = evaluate_pre_tool_use(
        _subagent_write_event(tmp_path, worktree), project_root=tmp_path
    )

    assert verdict.allowed is False
    assert verdict.guard_name == "artifact_guard"
    assert verdict.violation_type is ViolationType.ARTIFACT_TAMPERING
