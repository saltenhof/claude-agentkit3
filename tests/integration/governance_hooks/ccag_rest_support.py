"""Shared real-edge setup for CCAG REST integration tests."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

from agentkit.backend.control_plane.models import (
    EdgeBundle,
    EdgePointer,
    SessionRunBindingView,
    StoryExecutionLockView,
)
from agentkit.backend.governance.guard_evaluation import HookEvent
from agentkit.harness_client.projectedge.client import LocalEdgePublisher

if TYPE_CHECKING:
    from pathlib import Path

PROJECT = "tenant-a"
STORY = "AG3-131-REST"
RUN = "13113113-1131-4131-8131-131131131131"
SESSION = "sess-131-rest"


def publish_story_binding(project_root: Path, worktree: str) -> None:
    """Publish a valid active story/run binding for a hook test."""
    now = datetime.now(UTC)
    LocalEdgePublisher(project_root=project_root).publish(
        EdgeBundle(
            current=EdgePointer(
                project_key=PROJECT,
                export_version="edge-131-rest",
                operating_mode="story_execution",
                bundle_dir="_temp/governance/bundles/edge-131-rest",
                sync_after=now + timedelta(minutes=5),
                freshness_class="guarded_read",
                generated_at=now,
            ),
            session=SessionRunBindingView(
                session_id=SESSION,
                project_key=PROJECT,
                story_id=STORY,
                run_id=RUN,
                principal_type="orchestrator",
                worktree_roots=[worktree],
                binding_version="bind-131-rest",
                operating_mode="story_execution",
            ),
            lock=StoryExecutionLockView(
                project_key=PROJECT,
                story_id=STORY,
                run_id=RUN,
                lock_type="story_execution",
                status="ACTIVE",
                worktree_roots=[worktree],
                binding_version="bind-131-rest",
                activated_at=now,
                updated_at=now,
            ),
            qa_lock=None,
        )
    )


def hook_event(worktree: str, *, operation: str) -> HookEvent:
    """Build a worker-attested hook event inside the active worktree."""
    is_read = operation == "file_read"
    operation_args: dict[str, object] = (
        {"file_path": f"{worktree}/context.json"} if is_read else {"todos": []}
    )
    operation_args["operating_mode"] = "story_execution"
    return HookEvent.model_validate(
        {
            "operation": operation,
            "freshness_class": "guarded_read" if is_read else "baseline_read",
            "cwd": worktree,
            "principal_kind": "subagent",
            "session_id": SESSION,
            "cli_args": ["--ak3-principal-attest", "worker"],
            "operation_args": operation_args,
        }
    )


__all__ = ["PROJECT", "RUN", "STORY", "hook_event", "publish_story_binding"]
