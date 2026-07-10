"""Local-only AG3-149 ex-owner quarantine tests."""

from __future__ import annotations

import ast
import errno
import inspect
import json
import os
from datetime import UTC, datetime
from pathlib import Path

import pytest

import agentkit.harness_client.projectedge.quarantine as quarantine_module
from agentkit.backend.control_plane.models import (
    EdgeBundle,
    EdgePointer,
    ProjectEdgeSyncRequest,
    SessionRunBindingView,
    StoryExecutionLockView,
)
from agentkit.harness_client.projectedge.client import LocalEdgePublisher
from agentkit.harness_client.projectedge.quarantine import quarantine_worktree

NOW = datetime(2026, 7, 10, 12, tzinfo=UTC)


def test_quarantine_moves_whole_local_tree_and_writes_only_local_audit(
    tmp_path: Path,
) -> None:
    source = tmp_path / "worktree"
    source.mkdir()
    (source / "unpushed.txt").write_text("local-only", encoding="utf-8")
    store = tmp_path / "quarantine"

    result = quarantine_worktree(
        source_root=source,
        quarantine_store=store,
        reason="ownership_transferred",
        now=NOW,
    )

    assert result is not None
    assert not source.exists()
    destination = Path(result.quarantine_root)
    assert (destination / "unpushed.txt").read_text(encoding="utf-8") == "local-only"
    audit = json.loads((store / "audit" / f"{result.event_id}.json").read_text("utf-8"))
    assert audit["reason"] == "ownership_transferred"


def test_quarantine_code_has_no_git_or_upload_process_path() -> None:
    tree = ast.parse(inspect.getsource(quarantine_module))
    imported = {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    }
    assert "subprocess" not in imported
    assert "git" not in imported


def test_quarantine_cross_device_fallback_copies_then_removes_source(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "cross-device-worktree"
    source.mkdir()
    (source / "unpushed.txt").write_text("preserved", encoding="utf-8")
    real_replace = os.replace
    calls = 0

    def _replace_with_first_cross_device_error(src: object, dst: object) -> None:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise OSError(errno.EXDEV, "cross-device test")
        real_replace(src, dst)  # type: ignore[arg-type]

    monkeypatch.setattr(quarantine_module.os, "replace", _replace_with_first_cross_device_error)

    result = quarantine_worktree(
        source_root=source,
        quarantine_store=tmp_path / "quarantine",
        reason="ownership_transferred",
        now=NOW,
    )

    assert result is not None
    assert not source.exists()
    assert Path(result.quarantine_root, "unpushed.txt").read_text("utf-8") == "preserved"


def test_quarantine_absent_source_converges_and_invalid_sources_fail_closed(
    tmp_path: Path,
) -> None:
    assert quarantine_worktree(
        source_root=tmp_path / "absent",
        quarantine_store=tmp_path / "quarantine",
        reason="ownership_transferred",
        now=NOW,
    ) is None

    file_source = tmp_path / "file.txt"
    file_source.write_text("not a directory", encoding="utf-8")
    with pytest.raises(ValueError, match="must be a directory"):
        quarantine_worktree(
            source_root=file_source,
            quarantine_store=tmp_path / "quarantine",
            reason="ownership_transferred",
            now=NOW,
        )

    directory = tmp_path / "directory"
    directory.mkdir()
    with pytest.raises(ValueError, match="outside"):
        quarantine_worktree(
            source_root=directory,
            quarantine_store=directory / "nested-store",
            reason="ownership_transferred",
            now=NOW,
        )


def test_revoked_transfer_bundle_quarantines_on_publish_and_sync_payload_is_clean(
    tmp_path: Path,
) -> None:
    project_root = tmp_path / "project"
    project_root.mkdir()
    worktree = tmp_path / "old-worktree"
    worktree.mkdir()
    (worktree / "delta.txt").write_text("delta", encoding="utf-8")
    bundle = EdgeBundle(
        current=EdgePointer(
            project_key="ak3",
            export_version="edge-disowned",
            operating_mode="binding_invalid",
            bundle_dir="_temp/governance/bundles/edge-disowned",
            sync_after=NOW,
            freshness_class="mutation",
            generated_at=NOW,
        ),
        session=SessionRunBindingView(
            session_id="session-a",
            project_key="ak3",
            story_id="AG3-149",
            run_id="run-a",
            principal_type="orchestrator",
            worktree_roots=[str(worktree)],
            binding_version="2",
            operating_mode="binding_invalid",
            status="revoked",
            revocation_reason="ownership_transferred",
        ),
        lock=StoryExecutionLockView(
            project_key="ak3",
            story_id="AG3-149",
            run_id="run-a",
            lock_type="story_execution",
            status="INACTIVE",
            worktree_roots=[str(worktree)],
            binding_version="2",
            activated_at=NOW,
            updated_at=NOW,
            deactivated_at=NOW,
        ),
        tombstone_worktree_roots=[str(worktree)],
    )

    LocalEdgePublisher(project_root=project_root).publish(bundle)

    assert not worktree.exists()
    quarantine_store = tmp_path / ".agentkit-quarantine" / "project"
    assert list(quarantine_store.glob("old-worktree-quarantine-*"))
    payload = ProjectEdgeSyncRequest(
        project_key="ak3",
        session_id="session-a",
        op_id="sync-a",
    ).model_dump(mode="json")
    assert "quarantine" not in json.dumps(payload).lower()
