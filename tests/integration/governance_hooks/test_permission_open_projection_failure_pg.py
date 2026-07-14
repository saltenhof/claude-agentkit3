"""Regression proof for projection failure after a central permission open."""

from __future__ import annotations

from typing import TYPE_CHECKING

from tests.integration.governance_hooks.ccag_rest_support import (
    PROJECT,
    RUN,
    STORY,
    hook_event,
    publish_story_binding,
)
from tests.integration.governance_hooks.conftest import write_control_plane_config

from agentkit.backend.governance.runner import run_hook
from agentkit.backend.state_backend.store.permission_request_repository import (
    StateBackendPermissionRequestRepository,
)

if TYPE_CHECKING:
    from pathlib import Path


def test_projection_failure_keeps_central_request_id_and_does_not_trigger_retry(
    tmp_path: Path,
    control_plane_base_url: str,
    postgres_isolated_schema: str,
) -> None:
    """A failed local projection never reclassifies a successful central POST."""
    del postgres_isolated_schema
    worktree = str(tmp_path / "worktree")
    (tmp_path / "worktree").mkdir()
    publish_story_binding(tmp_path, worktree)
    write_control_plane_config(tmp_path, control_plane_base_url)
    (tmp_path / ".agent-guard").write_text("not-a-directory", encoding="utf-8")

    first = run_hook(
        "ccag_gatekeeper",
        hook_event(worktree, operation="unknown_tool"),
        phase="pre",
        project_root=tmp_path,
    )
    retry = None
    if first.detail and first.detail.get("permission_request_persist_failed"):
        retry = run_hook(
            "ccag_gatekeeper",
            hook_event(worktree, operation="unknown_tool"),
            phase="pre",
            project_root=tmp_path,
        )

    assert first.detail is not None
    assert first.detail["permission_request_opened"] is True
    assert "permission_request_persist_failed" not in first.detail
    request_id = str(first.detail["permission_request_id"])
    assert retry is None
    requests = StateBackendPermissionRequestRepository().list_for_run(
        PROJECT, STORY, RUN
    )
    assert tuple(item.request_id for item in requests) == (request_id,)
