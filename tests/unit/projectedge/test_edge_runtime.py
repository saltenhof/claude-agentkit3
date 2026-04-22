from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

from agentkit.control_plane.models import (
    ControlPlaneMutationResult,
    EdgeBundle,
    EdgePointer,
    SessionRunBindingView,
    StoryExecutionLockView,
)
from agentkit.projectedge import ProjectEdgeResolver, build_project_edge_client
from agentkit.projectedge.client import LocalEdgePublisher


def _bundle(
    *,
    worktree_root: str,
    session_id: str = "sess-001",
    operating_mode: str = "story_execution",
    sync_after: datetime | None = None,
    lock_status: str = "ACTIVE",
) -> EdgeBundle:
    now = datetime(2026, 4, 22, 12, 0, tzinfo=UTC)
    return EdgeBundle(
        current=EdgePointer(
            project_key="tenant-a",
            export_version="edge-001",
            operating_mode=operating_mode,
            bundle_dir="_temp/governance/bundles/edge-001",
            sync_after=sync_after or now + timedelta(minutes=5),
            freshness_class="guarded_read",
            generated_at=now,
        ),
        session=SessionRunBindingView(
            session_id=session_id,
            project_key="tenant-a",
            story_id="AG3-100",
            run_id="run-100",
            principal_type="orchestrator",
            worktree_roots=[worktree_root],
            binding_version="bind-001",
            operating_mode=operating_mode,
        ),
        lock=StoryExecutionLockView(
            project_key="tenant-a",
            story_id="AG3-100",
            run_id="run-100",
            lock_type="story_execution",
            status=lock_status,
            worktree_roots=[worktree_root],
            binding_version="bind-001",
            activated_at=now,
            updated_at=now,
        ),
    )


class _FakeClient:
    def __init__(self, result: ControlPlaneMutationResult) -> None:
        self.calls: list[tuple[str, str]] = []
        self._result = result

    def sync(self, request) -> ControlPlaneMutationResult:  # noqa: ANN001
        self.calls.append((request.project_key, request.session_id))
        return self._result


def test_resolver_returns_story_execution_for_matching_bundle(tmp_path) -> None:
    worktree = tmp_path / "worktree"
    LocalEdgePublisher(project_root=tmp_path).publish(_bundle(worktree_root=str(worktree)))

    resolved = ProjectEdgeResolver(project_root=tmp_path).resolve(
        session_id="sess-001",
        cwd=worktree,
        freshness_class="guarded_read",
    )

    assert resolved.operating_mode == "story_execution"
    assert resolved.block_reason is None


def test_resolver_returns_binding_invalid_for_session_mismatch(tmp_path) -> None:
    worktree = tmp_path / "worktree"
    LocalEdgePublisher(project_root=tmp_path).publish(_bundle(worktree_root=str(worktree)))

    resolved = ProjectEdgeResolver(project_root=tmp_path).resolve(
        session_id="sess-other",
        cwd=worktree,
        freshness_class="guarded_read",
    )

    assert resolved.operating_mode == "binding_invalid"
    assert resolved.block_reason == "session_binding_mismatch"


def test_resolver_performs_bounded_sync_for_stale_bundle(tmp_path, monkeypatch) -> None:
    worktree = tmp_path / "worktree"
    stale_bundle = _bundle(
        worktree_root=str(worktree),
        sync_after=datetime(2026, 4, 22, 11, 0, tzinfo=UTC),
    )
    LocalEdgePublisher(project_root=tmp_path).publish(stale_bundle)
    control_plane_dir = tmp_path / ".agentkit" / "config"
    control_plane_dir.mkdir(parents=True, exist_ok=True)
    (control_plane_dir / "control-plane.json").write_text(
        json.dumps({"base_url": "https://127.0.0.1:9080", "ca_file": None}),
        encoding="utf-8",
    )
    (control_plane_dir / "project.yaml").write_text(
        (
            "project_key: tenant-a\n"
            "project_name: Tenant A\n"
            "repositories:\n"
            "  - name: app\n"
            "    path: .\n"
        ),
        encoding="utf-8",
    )

    fresh_result = ControlPlaneMutationResult(
        status="synced",
        op_id="op-sync-001",
        operation_kind="project_edge_sync",
        edge_bundle=_bundle(
            worktree_root=str(worktree),
            sync_after=datetime(2026, 4, 22, 13, 0, tzinfo=UTC),
        ),
    )
    fake_client = _FakeClient(fresh_result)
    resolver = ProjectEdgeResolver(
        project_root=tmp_path,
        client_factory=lambda project_root: fake_client,
        now_provider=lambda: datetime(2026, 4, 22, 12, 0, tzinfo=UTC),
    )

    resolved = resolver.resolve(
        session_id="sess-001",
        cwd=worktree,
        freshness_class="mutation",
    )

    assert resolved.operating_mode == "story_execution"
    assert resolved.synced is True
    assert fake_client.calls == [("tenant-a", "sess-001")]


def test_resolver_returns_ai_augmented_for_minimal_free_bundle(tmp_path) -> None:
    now = datetime(2026, 4, 22, 12, 0, tzinfo=UTC)
    bundle = EdgeBundle(
        current=EdgePointer(
            project_key="tenant-a",
            export_version="edge-free-001",
            operating_mode="ai_augmented",
            bundle_dir="_temp/governance/bundles/edge-free-001",
            sync_after=now + timedelta(minutes=5),
            freshness_class="guarded_read",
            generated_at=now,
        ),
        session=None,
        lock=StoryExecutionLockView(
            project_key="tenant-a",
            story_id="",
            run_id="",
            lock_type="story_execution",
            status="INACTIVE",
            worktree_roots=[],
            binding_version="bind-free-001",
            activated_at=now,
            updated_at=now,
            deactivated_at=now,
        ),
    )
    LocalEdgePublisher(project_root=tmp_path).publish(bundle)

    resolved = ProjectEdgeResolver(project_root=tmp_path).resolve(
        session_id=None,
        cwd=tmp_path,
        freshness_class="baseline_read",
    )

    assert resolved.operating_mode == "ai_augmented"
    assert resolved.bundle is not None
    assert resolved.bundle.session is None


def test_resolver_returns_binding_invalid_for_worktree_mismatch(tmp_path) -> None:
    worktree = tmp_path / "worktree"
    LocalEdgePublisher(project_root=tmp_path).publish(_bundle(worktree_root=str(worktree)))

    resolved = ProjectEdgeResolver(project_root=tmp_path).resolve(
        session_id="sess-001",
        cwd=tmp_path / "other",
        freshness_class="guarded_read",
    )

    assert resolved.operating_mode == "binding_invalid"
    assert resolved.block_reason == "worktree_root_mismatch"


def test_resolver_baseline_read_does_not_trigger_sync_without_bundle(tmp_path) -> None:
    resolver = ProjectEdgeResolver(project_root=tmp_path)

    resolved = resolver.resolve(
        session_id="sess-001",
        cwd=tmp_path,
        freshness_class="baseline_read",
    )

    assert resolved.operating_mode == "ai_augmented"
    assert resolved.synced is False


def test_build_project_edge_client_uses_local_control_plane_config(
    tmp_path,
    monkeypatch,
) -> None:
    config_dir = tmp_path / ".agentkit" / "config"
    config_dir.mkdir(parents=True, exist_ok=True)
    (config_dir / "control-plane.json").write_text(
        json.dumps({"base_url": "https://127.0.0.1:9443", "ca_file": None}),
        encoding="utf-8",
    )

    client = build_project_edge_client(tmp_path)

    transport = client._transport  # type: ignore[attr-defined]
    publisher = client._publisher  # type: ignore[attr-defined]
    assert transport._base_url == "https://127.0.0.1:9443"  # type: ignore[attr-defined]
    assert publisher._project_root == tmp_path  # type: ignore[attr-defined]
