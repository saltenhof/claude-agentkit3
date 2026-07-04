from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Literal

from agentkit.backend.control_plane.models import (
    ControlPlaneMutationResult,
    EdgeBundle,
    EdgePointer,
    ProjectEdgeSyncRequest,
    SessionRunBindingView,
    StoryExecutionLockView,
)
from agentkit.harness_client.projectedge import ProjectEdgeResolver, build_project_edge_client
from agentkit.harness_client.projectedge.client import (
    HttpsJsonTransport,
    LocalEdgePublisher,
)

if TYPE_CHECKING:
    from pathlib import Path

    import pytest

    # Canonical FK-56 operating-mode literal -- the SINGLE foundation definition
    # (``core_types.operating_mode``). Annotation-only here (PEP 563 deferred), so
    # it lives in the type-checking block; no inline literal redeclaration.
    from agentkit.backend.core_types.operating_mode import OperatingMode


def _bundle(
    *,
    worktree_root: str,
    session_id: str = "sess-001",
    operating_mode: OperatingMode = "story_execution",
    sync_after: datetime | None = None,
    lock_status: Literal["ACTIVE", "INACTIVE", "INVALID"] = "ACTIVE",
    qa_lock_status: Literal["ACTIVE", "INACTIVE", "INVALID"] = "ACTIVE",
    binding_status: str = "active",
    revocation_reason: str | None = None,
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
            status=binding_status,
            revocation_reason=revocation_reason,
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
        qa_lock=StoryExecutionLockView(
            project_key="tenant-a",
            story_id="AG3-100",
            run_id="run-100",
            lock_type="qa_artifact_write",
            status=qa_lock_status,
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

    def sync(self, request: ProjectEdgeSyncRequest) -> ControlPlaneMutationResult:
        self.calls.append((request.project_key, request.session_id))
        return self._result


def test_resolver_returns_story_execution_for_matching_bundle(tmp_path: Path) -> None:
    worktree = tmp_path / "worktree"
    LocalEdgePublisher(project_root=tmp_path).publish(_bundle(worktree_root=str(worktree)))

    resolved = ProjectEdgeResolver(project_root=tmp_path).resolve(
        session_id="sess-001",
        cwd=worktree,
        freshness_class="guarded_read",
    )

    assert resolved.operating_mode == "story_execution"
    assert resolved.block_reason is None
    assert resolved.bundle is not None
    assert resolved.bundle.qa_lock is not None
    assert resolved.bundle.qa_lock.lock_type == "qa_artifact_write"


def test_resolver_returns_binding_invalid_for_session_mismatch(tmp_path: Path) -> None:
    worktree = tmp_path / "worktree"
    LocalEdgePublisher(project_root=tmp_path).publish(_bundle(worktree_root=str(worktree)))

    resolved = ProjectEdgeResolver(project_root=tmp_path).resolve(
        session_id="sess-other",
        cwd=worktree,
        freshness_class="guarded_read",
    )

    assert resolved.operating_mode == "binding_invalid"
    assert resolved.block_reason == "session_binding_mismatch"


def test_resolver_returns_binding_invalid_for_ownership_transferred(tmp_path: Path) -> None:
    """AG3-142 (SOLL-034 behaviour, FK-56 §56.7a/§56.13c): a revoked binding with
    reason ``ownership_transferred`` is deterministically ``binding_invalid`` --
    even though the CALLING session_id still matches the bundle's own
    ``session_id`` (the ex-owner asking about their OWN now-revoked binding).
    No silent fall-back to ``ai_augmented``.
    """
    worktree = tmp_path / "worktree"
    LocalEdgePublisher(project_root=tmp_path).publish(
        _bundle(
            worktree_root=str(worktree),
            binding_status="revoked",
            revocation_reason="ownership_transferred",
        ),
    )

    resolved = ProjectEdgeResolver(project_root=tmp_path).resolve(
        session_id="sess-001",
        cwd=worktree,
        freshness_class="guarded_read",
    )

    assert resolved.operating_mode == "binding_invalid"
    assert resolved.block_reason == "ownership_transferred"


def test_resolver_revoked_binding_with_missing_reason_stays_fail_closed(
    tmp_path: Path,
) -> None:
    """AG3-142 (AC8): a revoked binding with a missing/unknown reason still
    fails closed to ``binding_invalid`` -- NEVER silently treated as "not
    revoked" and NEVER a fall-back to ``ai_augmented``, even though the
    reason string itself is not the specific ``ownership_transferred`` value.
    """
    worktree = tmp_path / "worktree"
    LocalEdgePublisher(project_root=tmp_path).publish(
        _bundle(
            worktree_root=str(worktree),
            binding_status="revoked",
            revocation_reason=None,
        ),
    )

    resolved = ProjectEdgeResolver(project_root=tmp_path).resolve(
        session_id="sess-001",
        cwd=worktree,
        freshness_class="guarded_read",
    )

    assert resolved.operating_mode == "binding_invalid"
    assert resolved.block_reason is not None
    assert resolved.block_reason != "ownership_transferred"


def test_resolver_performs_bounded_sync_for_stale_bundle(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
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
            # FK-03 §3.2.1: config_version is mandatory (fail-closed).
            # AG3-052 E6 / AG3-056: code-producing default story_types =>
            # declare the sonarqube + ci stanzas explicitly (opt-outs).
            "pipeline:\n"
            "  config_version: '3.0'\n"
            "  features:\n"
            "    multi_llm: false\n"
            "  sonarqube:\n"
            "    available: false\n"
            "    enabled: false\n"
            "  ci:\n"
            "    available: false\n"
            "    enabled: false\n"
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
    from typing import cast as _cast

    from agentkit.harness_client.projectedge.client import ProjectEdgeClient as _ProjectEdgeClient
    fake_client = _FakeClient(fresh_result)
    resolver = ProjectEdgeResolver(
        project_root=tmp_path,
        client_factory=lambda project_root: _cast("_ProjectEdgeClient", fake_client),  # test double
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


def test_resolver_returns_ai_augmented_for_minimal_free_bundle(tmp_path: Path) -> None:
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


def test_resolver_bound_session_without_lock_is_binding_invalid(tmp_path: Path) -> None:
    """AG3-018 FIX-1: a bound session whose lock.json is missing must fail closed.

    ``invalid_bound_session_must_not_fall_back_to_free_mode``: deleting lock.json
    from a session-bound bundle must yield ``binding_invalid`` -- NOT a silent
    downgrade to ``ai_augmented`` (the previous fail-open).
    """
    worktree = tmp_path / "worktree"
    bundle = _bundle(worktree_root=str(worktree))
    LocalEdgePublisher(project_root=tmp_path).publish(bundle)
    lock_path = tmp_path / bundle.current.bundle_dir / "lock.json"
    lock_path.unlink()

    resolved = ProjectEdgeResolver(project_root=tmp_path).resolve(
        session_id="sess-001",
        cwd=worktree,
        freshness_class="baseline_read",
    )

    assert resolved.operating_mode == "binding_invalid"
    assert resolved.block_reason == "inactive_story_execution_lock"
    assert resolved.bundle is not None
    assert resolved.bundle.session is not None
    assert resolved.bundle.lock is None


def test_resolver_fast_bundle_without_session_or_lock_is_ai_augmented(
    tmp_path: Path,
) -> None:
    """AG3-018 FIX-1: a fast bundle (no session, no lock.json) stays ai_augmented.

    The intended FAST bundle has neither a bound session nor a lock.json. After
    the FIX-1 change the missing lock.json must NOT block this path: with no bound
    session it still resolves to ``ai_augmented``.
    """
    now = datetime(2026, 4, 22, 12, 0, tzinfo=UTC)
    fast_bundle = EdgeBundle(
        current=EdgePointer(
            project_key="tenant-a",
            export_version="edge-fast-001",
            operating_mode="ai_augmented",
            bundle_dir="_temp/governance/bundles/edge-fast-001",
            sync_after=now + timedelta(minutes=5),
            freshness_class="guarded_read",
            generated_at=now,
        ),
        session=None,
        lock=None,
        qa_lock=None,
    )
    LocalEdgePublisher(project_root=tmp_path).publish(fast_bundle)
    # The publisher writes a session.json stub (no session_id) and NO lock.json.
    assert not (tmp_path / fast_bundle.current.bundle_dir / "lock.json").exists()

    resolved = ProjectEdgeResolver(project_root=tmp_path).resolve(
        session_id=None,
        cwd=tmp_path,
        freshness_class="baseline_read",
    )

    assert resolved.operating_mode == "ai_augmented"
    assert resolved.bundle is not None
    assert resolved.bundle.session is None
    assert resolved.bundle.lock is None


def test_resolver_returns_binding_invalid_for_worktree_mismatch(tmp_path: Path) -> None:
    worktree = tmp_path / "worktree"
    LocalEdgePublisher(project_root=tmp_path).publish(_bundle(worktree_root=str(worktree)))

    resolved = ProjectEdgeResolver(project_root=tmp_path).resolve(
        session_id="sess-001",
        cwd=tmp_path / "other",
        freshness_class="guarded_read",
    )

    assert resolved.operating_mode == "binding_invalid"
    assert resolved.block_reason == "worktree_root_mismatch"


def test_resolver_baseline_read_does_not_trigger_sync_without_bundle(tmp_path: Path) -> None:
    resolver = ProjectEdgeResolver(project_root=tmp_path)

    resolved = resolver.resolve(
        session_id="sess-001",
        cwd=tmp_path,
        freshness_class="baseline_read",
    )

    assert resolved.operating_mode == "ai_augmented"
    assert resolved.synced is False


def test_build_project_edge_client_uses_local_control_plane_config(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config_dir = tmp_path / ".agentkit" / "config"
    config_dir.mkdir(parents=True, exist_ok=True)
    (config_dir / "control-plane.json").write_text(
        json.dumps({"base_url": "https://127.0.0.1:9443", "ca_file": None}),
        encoding="utf-8",
    )

    client = build_project_edge_client(tmp_path)

    # Cast private attrs to their concrete types to verify internal wiring.
    from typing import cast
    transport = cast("HttpsJsonTransport", client._transport)
    publisher = client._publisher
    assert transport._base_url == "https://127.0.0.1:9443"
    assert publisher._project_root == tmp_path


# --- read_change_frame_freeze_state (FK-23 §23.4.3, AG3-047) ----------------
# Fail-closed reader: only an ABSENT file is editable-by-default; every present
# but ambiguous state is "unreadable" so the guard blocks (NO ERROR BYPASSING).


def test_freeze_state_absent_when_no_file(tmp_path: Path) -> None:
    from agentkit.harness_client.projectedge.runtime import read_change_frame_freeze_state

    assert read_change_frame_freeze_state(tmp_path / "change_frame.json") == "absent"


def test_freeze_state_frozen_true(tmp_path: Path) -> None:
    from agentkit.harness_client.projectedge.runtime import read_change_frame_freeze_state

    path = tmp_path / "change_frame.json"
    path.write_text(json.dumps({"frozen": True}), encoding="utf-8")
    assert read_change_frame_freeze_state(path) == "frozen"


def test_freeze_state_frozen_false_is_editable(tmp_path: Path) -> None:
    from agentkit.harness_client.projectedge.runtime import read_change_frame_freeze_state

    path = tmp_path / "change_frame.json"
    path.write_text(json.dumps({"frozen": False}), encoding="utf-8")
    assert read_change_frame_freeze_state(path) == "editable"


def test_freeze_state_missing_flag_is_unreadable(tmp_path: Path) -> None:
    """``{}`` has no freeze decision -> unknown -> fail-closed (not editable)."""
    from agentkit.harness_client.projectedge.runtime import read_change_frame_freeze_state

    path = tmp_path / "change_frame.json"
    path.write_text(json.dumps({}), encoding="utf-8")
    assert read_change_frame_freeze_state(path) == "unreadable"


def test_freeze_state_non_bool_flag_is_unreadable(tmp_path: Path) -> None:
    """A truthy-but-not-True flag (``"true"`` / ``null``) must NOT read editable."""
    from agentkit.harness_client.projectedge.runtime import read_change_frame_freeze_state

    for raw in ('{"frozen": "true"}', '{"frozen": null}', '{"frozen": 1}'):
        path = tmp_path / "change_frame.json"
        path.write_text(raw, encoding="utf-8")
        assert read_change_frame_freeze_state(path) == "unreadable"


def test_freeze_state_non_object_json_is_unreadable(tmp_path: Path) -> None:
    from agentkit.harness_client.projectedge.runtime import read_change_frame_freeze_state

    path = tmp_path / "change_frame.json"
    path.write_text("[1, 2, 3]", encoding="utf-8")
    assert read_change_frame_freeze_state(path) == "unreadable"


def test_freeze_state_garbage_json_is_unreadable(tmp_path: Path) -> None:
    from agentkit.harness_client.projectedge.runtime import read_change_frame_freeze_state

    path = tmp_path / "change_frame.json"
    path.write_text("{not json", encoding="utf-8")
    assert read_change_frame_freeze_state(path) == "unreadable"


def test_freeze_state_directory_at_path_is_unreadable(tmp_path: Path) -> None:
    """A directory at the change-frame path is present-but-not-a-file -> unknown."""
    from agentkit.harness_client.projectedge.runtime import read_change_frame_freeze_state

    path = tmp_path / "change_frame.json"
    path.mkdir()
    assert read_change_frame_freeze_state(path) == "unreadable"
