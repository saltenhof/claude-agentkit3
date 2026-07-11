from __future__ import annotations

import json
from datetime import UTC, datetime
from email.message import Message
from io import BytesIO
from typing import TYPE_CHECKING, Any
from urllib.error import HTTPError

import pytest

from agentkit.backend.control_plane.models import (
    ClosureCompleteRequest,
    ControlPlaneMutationResult,
    EdgeBundle,
    EdgePointer,
    PhaseMutationRequest,
    ProjectEdgeSyncRequest,
    RecoveryRequest,
    SessionRunBindingView,
    StoryExecutionLockView,
    TakeoverReconcileWorktreeRequest,
    WorktreeReport,
)
from agentkit.harness_client.projectedge import (
    HttpsJsonTransport,
    LocalEdgePublisher,
    ProjectEdgeClient,
)

if TYPE_CHECKING:
    from pathlib import Path


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
            qa_lock=StoryExecutionLockView(
                project_key="tenant-a",
                story_id="AG3-100",
                run_id="run-100",
                lock_type="qa_artifact_write",
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

    def send(self, *, method: str, path: str, payload: object = None) -> dict[str, object]:
        self.calls.append((method, path))
        return self._result.model_dump(mode="json")


class _FakeResponse:
    def __init__(
        self, body: bytes, *, headers: dict[str, str] | None = None
    ) -> None:
        self._body = body
        #: Mirror the real urllib response ``.headers`` (an object with ``.get``).
        self.headers = headers or {}

    def __enter__(self) -> _FakeResponse:
        return self

    def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
        return None

    def read(self) -> bytes:
        return self._body


def test_local_edge_publisher_writes_current_bundle_and_worktree_export(
    tmp_path: Path,
) -> None:
    worktree = tmp_path / "worktree"
    bundle = _mutation_result(str(worktree)).edge_bundle

    publisher = LocalEdgePublisher(project_root=tmp_path)
    publisher.publish(bundle)

    current = json.loads(
        (tmp_path / "_temp" / "governance" / "current.json").read_text(),
    )
    qa_lock = json.loads(
        (
            tmp_path
            / "_temp"
            / "governance"
            / "bundles"
            / "edge-001"
            / "qa-lock.json"
        ).read_text(),
    )
    lock_export = json.loads((worktree / ".agent-guard" / "lock.json").read_text())
    freeze_export = json.loads(
        (worktree / ".agent-guard" / "freeze.json").read_text()
    )

    assert current["export_version"] == "edge-001"
    assert qa_lock["lock_type"] == "qa_artifact_write"
    assert lock_export["status"] == "ACTIVE"
    assert freeze_export == {"active_freezes": [], "state_readable": True}


def test_local_edge_publisher_can_fail_closed_until_authoritative_sync(
    tmp_path: Path,
) -> None:
    worktree = tmp_path / "worktree"
    bundle = _mutation_result(str(worktree)).edge_bundle
    publisher = LocalEdgePublisher(project_root=tmp_path)
    publisher.publish(bundle)

    publisher.publish_unreadable_freeze_state(worktree_roots=[worktree])

    expected = {"active_freezes": [], "state_readable": False}
    assert json.loads(
        (worktree / ".agent-guard" / "freeze.json").read_text()
    ) == expected
    assert json.loads(
        (
            tmp_path
            / "_temp"
            / "governance"
            / "bundles"
            / "edge-001"
            / "freeze.json"
        ).read_text()
    ) == expected


def test_project_edge_client_posts_official_takeover_reconcile_route(
    tmp_path: Path,
) -> None:
    result = _mutation_result(str(tmp_path / "worktree"))
    transport = _FakeTransport(result)
    client = ProjectEdgeClient(
        transport=transport,
        publisher=LocalEdgePublisher(project_root=tmp_path),
    )

    client.reconcile_takeover_worktree(
        run_id="run/100",
        request=TakeoverReconcileWorktreeRequest(
            project_key="tenant-a",
            story_id="AG3-100",
            session_id="sess-001",
            op_id="op-reconcile-client",
            results=[
                WorktreeReport(
                    repo_id="api",
                    outcome="no_op",
                    head_sha="a" * 40,
                    marker_present=True,
                )
            ],
        ),
    )

    assert transport.calls == [
        (
            "POST",
            "/v1/project-edge/story-runs/run%2F100/ownership/"
            "takeover-reconcile-worktree",
        )
    ]


def test_project_edge_client_recover_is_thin_official_transport(tmp_path: Path) -> None:
    result = _mutation_result(str(tmp_path / "worktree"))
    transport = _FakeTransport(result)
    client = ProjectEdgeClient(
        transport=transport,
        publisher=LocalEdgePublisher(project_root=tmp_path),
    )

    client.recover(
        run_id="run/old",
        request=RecoveryRequest(
            project_key="tenant-a",
            story_id="AG3-154",
            op_id="op-recovery-client",
            reason="operator confirmed crash recovery",
        ),
    )

    assert transport.calls == [
        ("POST", "/v1/project-edge/story-runs/run%2Fold/ownership/recover")
    ]


def test_project_edge_client_posts_and_publishes(tmp_path: Path) -> None:
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
            op_id="op-phase-start-client-001",
        ),
    )

    assert returned.operation_kind == "phase_start"
    assert transport.calls == [("POST", "/v1/story-runs/run-100/phases/setup/start")]
    assert (tmp_path / "_temp" / "governance" / "current.json").exists()


def test_project_edge_client_supports_all_mutation_paths(tmp_path: Path) -> None:
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
        op_id="op-phase-multi-001",
    )

    client.complete_phase(run_id="run-100", phase="setup", request=phase_request)
    client.fail_phase(run_id="run-100", phase="setup", request=phase_request)
    client.complete_closure(
        run_id="run-100",
        request=ClosureCompleteRequest(
            project_key="tenant-a",
            story_id="AG3-100",
            session_id="sess-001",
            op_id="op-closure-client-001",
        ),
    )
    client.sync(
        ProjectEdgeSyncRequest(
            project_key="tenant-a", session_id="sess-001", op_id="op-sync-client-001"
        )
    )
    client.reconcile_operation("op-client-001")

    assert transport.calls == [
        ("POST", "/v1/story-runs/run-100/phases/setup/complete"),
        ("POST", "/v1/story-runs/run-100/phases/setup/fail"),
        ("POST", "/v1/story-runs/run-100/closure/complete"),
        ("POST", "/v1/project-edge/sync"),
        ("GET", "/v1/project-edge/operations/op-client-001"),
    ]


def test_operator_run_phase_hits_project_scoped_route_without_publish(
    tmp_path: Path,
) -> None:
    """AG3-130: run_phase targets the canonical project-scoped route, no local publish."""
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
        principal_type="operator",
        worktree_roots=[str(tmp_path / "worktree")],
        op_id="op-run-phase-op-001",
    )

    returned = client.run_phase(
        project_key="tenant-a",
        run_id="run-100",
        phase="setup",
        request=phase_request,
    )

    assert returned.operation_kind == "phase_start"
    assert transport.calls == [
        ("POST", "/v1/projects/tenant-a/story-runs/run-100/phases/setup/start"),
    ]
    # Operator dispatch is a pure core call: no local governance bundle published.
    assert not (tmp_path / "_temp" / "governance" / "current.json").exists()


def test_operator_resume_phase_hits_project_scoped_resume_route(
    tmp_path: Path,
) -> None:
    """AG3-130: resume_phase targets ``.../phases/{phase}/resume`` (project-scoped)."""
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
        principal_type="operator",
        worktree_roots=[str(tmp_path / "worktree")],
        detail={"resume_trigger": "approval_received"},
        op_id="op-resume-phase-001",
    )

    client.resume_phase(
        project_key="tenant-a",
        run_id="run-100",
        phase="implementation",
        request=phase_request,
    )

    assert transport.calls == [
        ("POST", "/v1/projects/tenant-a/story-runs/run-100/phases/implementation/resume"),
    ]
    assert not (tmp_path / "_temp" / "governance" / "current.json").exists()


def test_operator_phase_route_url_encodes_project_key(tmp_path: Path) -> None:
    """A project key with reserved chars stays inside the path segment (AG3-130)."""
    result = _mutation_result(str(tmp_path / "worktree"))
    transport = _FakeTransport(result)
    client = ProjectEdgeClient(
        transport=transport,
        publisher=LocalEdgePublisher(project_root=tmp_path),
    )
    phase_request = PhaseMutationRequest(
        project_key="tenant/a b",
        story_id="AG3-100",
        session_id="sess-001",
        principal_type="operator",
        worktree_roots=[str(tmp_path / "worktree")],
        op_id="op-url-encode-001",
    )

    client.run_phase(
        project_key="tenant/a b",
        run_id="run-100",
        phase="setup",
        request=phase_request,
    )

    assert transport.calls == [
        ("POST", "/v1/projects/tenant%2Fa%20b/story-runs/run-100/phases/setup/start"),
    ]


def test_operator_phase_route_url_encodes_run_id_and_phase(tmp_path: Path) -> None:
    """A run_id/phase with reserved chars stays inside its path segment (Codex M1)."""
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
        principal_type="operator",
        worktree_roots=[str(tmp_path / "worktree")],
        op_id="op-run-id-encode-001",
    )

    # A ``run_id="run/evil"`` must not break out of the run-id path segment and
    # address a different route (e.g. ``.../story-runs/run/evil/phases/...``).
    client.run_phase(
        project_key="tenant-a",
        run_id="run/evil",
        phase="set up",
        request=phase_request,
    )

    assert transport.calls == [
        ("POST", "/v1/projects/tenant-a/story-runs/run%2Fevil/phases/set%20up/start"),
    ]


def test_local_edge_publisher_removes_tombstoned_lock_export(tmp_path: Path) -> None:
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


def test_https_json_transport_returns_object(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_urlopen(request: Any, context: Any = None) -> _FakeResponse:
        del request, context
        return _FakeResponse(b'{\"status\": \"ok\"}')

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)

    transport = HttpsJsonTransport(base_url="https://127.0.0.1:9080")

    assert transport.send(method="GET", path="/healthz") == {"status": "ok"}


def test_https_json_transport_raises_runtime_error_for_http_error(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_urlopen(request: Any, context: Any = None) -> _FakeResponse:
        del request, context
        raise HTTPError(
            url="https://127.0.0.1:9080/v1/project-edge/sync",
            code=503,
            msg="Service Unavailable",
            hdrs=Message(),
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


def test_https_json_transport_rejects_non_object_response(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_urlopen(request: Any, context: Any = None) -> _FakeResponse:
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


def _rejected_mutation_body() -> bytes:
    """A structured HTTP 409 rejected mutation result body (no edge bundle)."""
    return ControlPlaneMutationResult(
        status="rejected",
        op_id="op-reject-409",
        operation_kind="phase_start",
        run_id="run-100",
        phase="setup",
        edge_bundle=None,
    ).model_dump_json().encode("utf-8")


def _setup_request(tmp_path: Path) -> PhaseMutationRequest:
    return PhaseMutationRequest(
        project_key="tenant-a",
        story_id="AG3-100",
        session_id="sess-001",
        principal_type="orchestrator",
        worktree_roots=[str(tmp_path / "worktree")],
        op_id="op-phase-helper-001",
    )


def test_https_transport_returns_structured_rejection_for_409(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AG3-054 (FK-20 §20.8.2): a real HTTP 409 rejected body is RETURNED, not raised.

    The transport must parse the 409 body and return the structured rejected
    mutation result so the official client path (not only fake transports) sees
    the ``status == "rejected"`` outcome.
    """
    def fake_urlopen(request: Any, context: Any = None) -> _FakeResponse:
        del request, context
        raise HTTPError(
            url="https://127.0.0.1:9080/v1/story-runs/run-100/phases/setup/start",
            code=409,
            msg="Conflict",
            hdrs=Message(),
            fp=BytesIO(_rejected_mutation_body()),
        )

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)

    transport = HttpsJsonTransport(base_url="https://127.0.0.1:9080")
    body = transport.send(method="POST", path="/v1/story-runs/run-100/phases/setup/start")

    assert body["status"] == "rejected"
    assert body["edge_bundle"] is None


def test_client_returns_rejection_and_publishes_nothing_on_real_409(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """ERROR-4: a 409 rejection reaches the client and skips the local publish.

    The official ``ProjectEdgeClient.start_phase`` over the real
    ``HttpsJsonTransport`` must return the structured ``status == "rejected"``
    result and publish NO edge bundle (``edge_bundle is None`` publish-skip),
    proving the publish-skip path works on the production transport -- not only
    with fake transports.
    """
    def fake_urlopen(request: Any, context: Any = None) -> _FakeResponse:
        del request, context
        raise HTTPError(
            url="https://127.0.0.1:9080/v1/story-runs/run-100/phases/setup/start",
            code=409,
            msg="Conflict",
            hdrs=Message(),
            fp=BytesIO(_rejected_mutation_body()),
        )

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)

    client = ProjectEdgeClient(
        transport=HttpsJsonTransport(base_url="https://127.0.0.1:9080"),
        publisher=LocalEdgePublisher(project_root=tmp_path),
    )

    result = client.start_phase(
        run_id="run-100",
        phase="setup",
        request=_setup_request(tmp_path),
    )

    assert result.status == "rejected"
    assert result.edge_bundle is None
    # Publish-skip: nothing was written to the local governance edge.
    assert not (tmp_path / "_temp" / "governance" / "current.json").exists()


def test_client_still_raises_on_non_409_http_error(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """A non-409 HTTPError still raises (no silent fallback to schlechtere Daten)."""
    def fake_urlopen(request: Any, context: Any = None) -> _FakeResponse:
        del request, context
        raise HTTPError(
            url="https://127.0.0.1:9080/v1/story-runs/run-100/phases/setup/start",
            code=503,
            msg="Service Unavailable",
            hdrs=Message(),
            fp=BytesIO(b'{"error": "down"}'),
        )

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)

    client = ProjectEdgeClient(
        transport=HttpsJsonTransport(base_url="https://127.0.0.1:9080"),
        publisher=LocalEdgePublisher(project_root=tmp_path),
    )

    try:
        client.start_phase(
            run_id="run-100",
            phase="setup",
            request=_setup_request(tmp_path),
        )
    except RuntimeError as exc:
        assert "HTTP 503" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("Expected RuntimeError")


def _conflict_urlopen(body: bytes) -> Any:
    def fake_urlopen(request: Any, context: Any = None) -> Any:
        del request, context
        raise HTTPError(
            url="https://127.0.0.1:9080/v1/story-runs/run-100/phases/setup/start",
            code=409,
            msg="Conflict",
            hdrs=Message(),
            fp=BytesIO(body),
        )

    return fake_urlopen


def test_409_non_conforming_body_raises_not_returns(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """W8: a 409 body that is not a conforming rejected mutation RAISES, not returns.

    The 409 body is partly attacker-influenced. A body that has
    ``status == "rejected"`` but is NOT a valid ``ControlPlaneMutationResult``
    (here: it ALSO carries an edge_bundle, which the model forbids for a rejection)
    must NOT be returned as a bogus result -- it raises.
    """
    bogus = json.dumps(
        {
            "status": "rejected",
            "op_id": "op-x",
            "operation_kind": "phase_start",
            # A rejection must NOT carry an edge_bundle -> model_validate fails.
            "edge_bundle": {"current": {"project_key": "x"}},
        }
    ).encode("utf-8")
    monkeypatch.setattr("urllib.request.urlopen", _conflict_urlopen(bogus))

    transport = HttpsJsonTransport(base_url="https://127.0.0.1:9080")

    with pytest.raises(RuntimeError, match="HTTP 409"):
        transport.send(
            method="POST",
            path="/v1/story-runs/run-100/phases/setup/start",
        )


def test_409_malformed_json_raises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """W8: a 409 body that is not valid JSON raises (never a bogus result)."""
    monkeypatch.setattr(
        "urllib.request.urlopen", _conflict_urlopen(b"not json at all")
    )

    transport = HttpsJsonTransport(base_url="https://127.0.0.1:9080")

    with pytest.raises(RuntimeError, match="HTTP 409"):
        transport.send(
            method="POST",
            path="/v1/story-runs/run-100/phases/setup/start",
        )


def test_409_wrong_status_raises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """W8: a 409 body that validates but is not ``rejected`` raises."""
    # A committed result REQUIRES an edge_bundle, so to validate we craft one;
    # but a committed status on a 409 is not a rejection -> must raise.
    not_rejected = json.dumps(
        {
            "status": "synced",
            "op_id": "op-x",
            "operation_kind": "phase_start",
            "edge_bundle": None,
        }
    ).encode("utf-8")
    monkeypatch.setattr(
        "urllib.request.urlopen", _conflict_urlopen(not_rejected)
    )

    transport = HttpsJsonTransport(base_url="https://127.0.0.1:9080")

    with pytest.raises(RuntimeError, match="HTTP 409"):
        transport.send(
            method="POST",
            path="/v1/story-runs/run-100/phases/setup/start",
        )
