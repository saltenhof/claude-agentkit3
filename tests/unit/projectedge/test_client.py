from __future__ import annotations

import json
from datetime import UTC, datetime
from io import BytesIO
from urllib.error import HTTPError

from agentkit.control_plane.models import (
    ClosureCompleteRequest,
    ControlPlaneMutationResult,
    EdgeBundle,
    EdgePointer,
    PhaseMutationRequest,
    ProjectEdgeSyncRequest,
    SessionRunBindingView,
    StoryExecutionLockView,
)
from agentkit.projectedge import (
    HttpsJsonTransport,
    LocalEdgePublisher,
    ProjectEdgeClient,
)


def _mutation_result(worktree_root: str) -> ControlPlaneMutationResult:
    now = datetime(2026, 4, 22, 10, 0, tzinfo=UTC)
    return ControlPlaneMutationResult(
        status="committed",
        op_id="op-client-001",
        operation_kind="phase_start",
        run_id="run-100",
        phase="setup",
        edge_bundle=EdgeBundle(
            current=EdgePointer(
                project_key="tenant-a",
                export_version="edge-001",
                operating_mode="story_execution",
                bundle_dir="_temp/governance/bundles/edge-001",
                sync_after=now,
                freshness_class="mutation",
                generated_at=now,
            ),
            session=SessionRunBindingView(
                session_id="sess-001",
                project_key="tenant-a",
                story_id="AG3-100",
                run_id="run-100",
                principal_type="orchestrator",
                worktree_roots=[worktree_root],
                binding_version="bind-001",
                operating_mode="story_execution",
            ),
            lock=StoryExecutionLockView(
                project_key="tenant-a",
                story_id="AG3-100",
                run_id="run-100",
                lock_type="story_execution",
                status="ACTIVE",
                worktree_roots=[worktree_root],
                binding_version="bind-001",
                activated_at=now,
                updated_at=now,
            ),
        ),
    )


class _FakeTransport:
    def __init__(self, result: ControlPlaneMutationResult) -> None:
        self.calls: list[tuple[str, str]] = []
        self._result = result

    def send(self, *, method: str, path: str, payload=None) -> dict[str, object]:
        self.calls.append((method, path))
        return self._result.model_dump(mode="json")


class _FakeResponse:
    def __init__(self, body: bytes) -> None:
        self._body = body

    def __enter__(self) -> _FakeResponse:
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        return None

    def read(self) -> bytes:
        return self._body


def test_local_edge_publisher_writes_current_bundle_and_worktree_export(
    tmp_path,
) -> None:
    worktree = tmp_path / "worktree"
    bundle = _mutation_result(str(worktree)).edge_bundle

    publisher = LocalEdgePublisher(project_root=tmp_path)
    publisher.publish(bundle)

    current = json.loads(
        (tmp_path / "_temp" / "governance" / "current.json").read_text(),
    )
    lock_export = json.loads((worktree / ".agent-guard" / "lock.json").read_text())

    assert current["export_version"] == "edge-001"
    assert lock_export["status"] == "ACTIVE"


def test_project_edge_client_posts_and_publishes(tmp_path) -> None:
    worktree = tmp_path / "worktree"
    result = _mutation_result(str(worktree))
    transport = _FakeTransport(result)
    client = ProjectEdgeClient(
        transport=transport,
        publisher=LocalEdgePublisher(project_root=tmp_path),
    )

    returned = client.start_phase(
        run_id="run-100",
        phase="setup",
        request=PhaseMutationRequest(
            project_key="tenant-a",
            story_id="AG3-100",
            session_id="sess-001",
            principal_type="orchestrator",
            worktree_roots=[str(worktree)],
        ),
    )

    assert returned.operation_kind == "phase_start"
    assert transport.calls == [("POST", "/v1/story-runs/run-100/phases/setup/start")]
    assert (tmp_path / "_temp" / "governance" / "current.json").exists()


def test_project_edge_client_supports_all_mutation_paths(tmp_path) -> None:
    result = _mutation_result(str(tmp_path / "worktree"))
    transport = _FakeTransport(result)
    client = ProjectEdgeClient(
        transport=transport,
        publisher=LocalEdgePublisher(project_root=tmp_path),
    )
    phase_request = PhaseMutationRequest(
        project_key="tenant-a",
        story_id="AG3-100",
        session_id="sess-001",
        principal_type="orchestrator",
        worktree_roots=[str(tmp_path / "worktree")],
    )

    client.complete_phase(run_id="run-100", phase="setup", request=phase_request)
    client.fail_phase(run_id="run-100", phase="setup", request=phase_request)
    client.complete_closure(
        run_id="run-100",
        request=ClosureCompleteRequest(
            project_key="tenant-a",
            story_id="AG3-100",
            session_id="sess-001",
        ),
    )
    client.sync(ProjectEdgeSyncRequest(project_key="tenant-a", session_id="sess-001"))
    client.reconcile_operation("op-client-001")

    assert transport.calls == [
        ("POST", "/v1/story-runs/run-100/phases/setup/complete"),
        ("POST", "/v1/story-runs/run-100/phases/setup/fail"),
        ("POST", "/v1/story-runs/run-100/closure/complete"),
        ("POST", "/v1/project-edge/sync"),
        ("GET", "/v1/project-edge/operations/op-client-001"),
    ]


def test_local_edge_publisher_removes_tombstoned_lock_export(tmp_path) -> None:
    worktree = tmp_path / "worktree"
    lock_path = worktree / ".agent-guard" / "lock.json"
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    lock_path.write_text("{}", encoding="utf-8")
    now = datetime(2026, 4, 22, 10, 0, tzinfo=UTC)
    bundle = EdgeBundle(
        current=EdgePointer(
            project_key="tenant-a",
            export_version="edge-free-001",
            operating_mode="ai_augmented",
            bundle_dir="_temp/governance/bundles/edge-free-001",
            sync_after=now,
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
        tombstone_worktree_roots=[str(worktree)],
    )

    LocalEdgePublisher(project_root=tmp_path).publish(bundle)

    session_payload = json.loads(
        (
            tmp_path
            / "_temp"
            / "governance"
            / "bundles"
            / "edge-free-001"
            / "session.json"
        ).read_text(),
    )
    assert session_payload["operating_mode"] == "ai_augmented"
    assert not lock_path.exists()


def test_https_json_transport_returns_object(monkeypatch) -> None:
    def fake_urlopen(request, context=None):  # noqa: ANN001
        del request, context
        return _FakeResponse(b'{\"status\": \"ok\"}')

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)

    transport = HttpsJsonTransport(base_url="https://127.0.0.1:9080")

    assert transport.send(method="GET", path="/healthz") == {"status": "ok"}


def test_https_json_transport_raises_runtime_error_for_http_error(monkeypatch) -> None:
    def fake_urlopen(request, context=None):  # noqa: ANN001
        del request, context
        raise HTTPError(
            url="https://127.0.0.1:9080/v1/project-edge/sync",
            code=503,
            msg="Service Unavailable",
            hdrs=None,
            fp=BytesIO(b"{\"error\": \"down\"}"),
        )

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)

    transport = HttpsJsonTransport(base_url="https://127.0.0.1:9080")

    try:
        transport.send(method="GET", path="/healthz")
    except RuntimeError as exc:
        assert "HTTP 503" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("Expected RuntimeError")


def test_https_json_transport_rejects_non_object_response(monkeypatch) -> None:
    def fake_urlopen(request, context=None):  # noqa: ANN001
        del request, context
        return _FakeResponse(b"[]")

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)

    transport = HttpsJsonTransport(base_url="https://127.0.0.1:9080")

    try:
        transport.send(method="GET", path="/healthz")
    except RuntimeError as exc:
        assert "JSON object" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("Expected RuntimeError")
