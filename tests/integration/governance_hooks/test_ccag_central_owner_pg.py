"""Real Postgres and HTTP coverage for the central CCAG permission owner."""

from __future__ import annotations

import threading
from contextlib import contextmanager
from datetime import UTC, datetime
from http.server import HTTPServer
from typing import TYPE_CHECKING

import pytest
from tests.integration.governance.test_capability_pipeline import _publish_story_binding
from tests.integration.governance_hooks.conftest import write_control_plane_config

from agentkit.backend.auth.middleware import AuthMiddleware
from agentkit.backend.auth.tokens import issue_project_api_token
from agentkit.backend.control_plane.models import (
    PermissionLeaseGrantRequest,
    PermissionRequestOpenRequest,
    PermissionRequestResolveRequest,
)
from agentkit.backend.control_plane_http.app import ControlPlaneApplication, _build_handler
from agentkit.backend.exceptions import ControlPlaneApiError
from agentkit.backend.governance.ccag.permission_commands import OpenPermissionRequestCommand
from agentkit.backend.governance.ccag.permission_service import PermissionService
from agentkit.backend.governance.guard_evaluation import HookEvent
from agentkit.backend.governance.runner import run_hook
from agentkit.backend.state_backend.store.mode_lock_repository import (
    ModeLockConflictError,
    ModeLockRepository,
)
from agentkit.backend.state_backend.store.permission_lease_repository import (
    StateBackendPermissionLeaseRepository,
)
from agentkit.backend.state_backend.store.permission_request_repository import (
    StateBackendPermissionRequestRepository,
)
from agentkit.harness_client.projectedge.client import HttpsJsonTransport
from agentkit.harness_client.projectedge.governance_client import GovernanceEdgeClient

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

    from agentkit.backend.auth.entities import ProjectApiToken

_PROJECT = "tenant-a"
_STORY = "AG3-131"
_RUN = "run-131"


class _TokenRepository:
    """Concrete in-memory auth repository; permission state remains real PG."""

    def __init__(self) -> None:
        self.rows: dict[str, ProjectApiToken] = {}

    def get(self, token_id: str) -> ProjectApiToken | None:
        return self.rows.get(token_id)

    def get_by_hash(self, token_hash: str) -> ProjectApiToken | None:
        return next((row for row in self.rows.values() if row.token_hash == token_hash), None)

    def list_for_project(self, project_key: str) -> list[ProjectApiToken]:
        return [row for row in self.rows.values() if row.project_key == project_key]

    def save(self, token: ProjectApiToken) -> None:
        self.rows[token.token_id] = token

    def revoke(self, project_key: str, token_id: str) -> None:
        row = self.rows[token_id]
        assert row.project_key == project_key
        self.save(row.model_copy(update={"revoked_at": datetime.now(UTC)}))


@contextmanager
def _server(app: ControlPlaneApplication) -> Iterator[str]:
    server = HTTPServer(("127.0.0.1", 0), _build_handler(app))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    host, port = server.server_address
    try:
        yield f"http://{host}:{port}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def _service() -> PermissionService:
    return PermissionService(
        StateBackendPermissionRequestRepository(),
        StateBackendPermissionLeaseRepository(),
    )


def _request(request_id: str, *, ttl_seconds: int = 1800) -> PermissionRequestOpenRequest:
    return PermissionRequestOpenRequest(
        request_id=request_id,
        project_key=_PROJECT,
        story_id=_STORY,
        run_id=_RUN,
        principal_type="worker",
        tool_name="Bash",
        operation_class="execute",
        path_classes=("codebase_story_scope",),
        request_fingerprint=f"fingerprint-{request_id}",
        ttl_seconds=ttl_seconds,
    )


def test_request_lease_lifecycle_is_server_mediated_on_real_postgres(
    postgres_isolated_schema: str,
) -> None:
    """Open/read/approve/grant/consume uses HTTP plus canonical Postgres."""
    del postgres_isolated_schema
    tokens = _TokenRepository()
    issued = issue_project_api_token(project_key=_PROJECT, label="hook", repository=tokens)
    auth = AuthMiddleware(token_repository=tokens)
    app = ControlPlaneApplication(auth_middleware=auth)
    session = auth.session_store.create()
    with _server(app) as base_url:
        hook_transport = HttpsJsonTransport(
            base_url=base_url, bearer_token=issued.plaintext_token, project_key=_PROJECT
        )
        hook = GovernanceEdgeClient(transport=hook_transport)
        opened = hook.open_permission_request(_request("request-http"))
        assert opened.status == "pending"
        assert hook.read_permission_requests(
            project_key=_PROJECT, story_id=_STORY, run_id=_RUN
        ).requests == (opened,)

        human = HttpsJsonTransport(
            base_url=base_url,
            project_key=_PROJECT,
            strategist_headers={
                "Cookie": f"{AuthMiddleware.session_cookie_name()}={session.session_id}",
                AuthMiddleware.csrf_header_name(): session.csrf_token,
            },
        )
        strategist = GovernanceEdgeClient(transport=human)
        resolved = strategist.resolve_permission_request(
            PermissionRequestResolveRequest(
                request_id=opened.request_id,
                resolution="approved",
                decision_note="approved in integration test",
            )
        )
        assert resolved.status == "approved"
        lease = strategist.grant_permission_lease(
            PermissionLeaseGrantRequest(
                lease_id="lease-http",
                request_ref=opened.request_id,
                max_uses=2,
                ttl_seconds=1800,
            )
        )
        assert lease.max_uses == 2
        assert hook.consume_permission_lease("lease-http").consumed == 1
        assert hook.consume_permission_lease("lease-http").consumed == 2
        with pytest.raises(ControlPlaneApiError, match="exhausted") as exhausted:
            hook.consume_permission_lease("lease-http")
        assert exhausted.value.error_code == "permission_lease_exhausted"


def test_hook_token_cannot_resolve_or_grant_before_mutation(
    postgres_isolated_schema: str,
) -> None:
    """Project-token attempts are rejected before request/lease writes."""
    del postgres_isolated_schema
    tokens = _TokenRepository()
    issued = issue_project_api_token(project_key=_PROJECT, label="hook", repository=tokens)
    auth = AuthMiddleware(token_repository=tokens)
    app = ControlPlaneApplication(auth_middleware=auth)
    service = _service()
    with _server(app) as base_url:
        transport = HttpsJsonTransport(
            base_url=base_url, bearer_token=issued.plaintext_token, project_key=_PROJECT
        )
        hook = GovernanceEdgeClient(transport=transport)
        opened = hook.open_permission_request(_request("request-auth"))
        with pytest.raises(ControlPlaneApiError, match="human BFF session"):
            transport.send(
                method="POST",
                path="/v1/governance/permission-requests",
                payload={
                    "operation": "resolve",
                    "request_id": opened.request_id,
                    "resolution": "approved",
                },
            )
        assert service.read(opened.request_id).status == "pending"  # type: ignore[union-attr]
        with pytest.raises(ControlPlaneApiError, match="human BFF session"):
            transport.send(
                method="POST",
                path="/v1/governance/permission-leases",
                payload={
                    "operation": "grant",
                    "lease_id": "forged-lease",
                    "request_ref": opened.request_id,
                },
            )
        assert service.read_lease("forged-lease") is None


def test_expired_request_is_lazily_materialized_as_denied(
    postgres_isolated_schema: str,
) -> None:
    """The next canonical read deterministically persists expiry/denial."""
    del postgres_isolated_schema
    old = datetime(2020, 1, 1, tzinfo=UTC)
    service = PermissionService(
        StateBackendPermissionRequestRepository(),
        StateBackendPermissionLeaseRepository(),
        clock=lambda: old,
    )
    service.open(OpenPermissionRequestCommand.model_validate(_request("request-expired").model_dump(exclude={"operation"})))
    expired = _service().read("request-expired")
    assert expired is not None
    assert expired.status == "expired"
    assert expired.resolution == "denied"
    assert expired.decided_at == expired.expires_at


def test_real_hook_opens_request_through_http_and_postgres(
    tmp_path: Path,
    postgres_isolated_schema: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The real guard runner uses its REST seam and writes no local database."""
    del postgres_isolated_schema
    tokens = _TokenRepository()
    issued = issue_project_api_token(project_key=_PROJECT, label="hook", repository=tokens)
    app = ControlPlaneApplication(auth_middleware=AuthMiddleware(token_repository=tokens))
    worktree = str(tmp_path / "worktree")
    _publish_story_binding(tmp_path, worktree)
    monkeypatch.setenv("AGENTKIT_PROJECT_API_TOKEN", issued.plaintext_token)
    with _server(app) as base_url:
        write_control_plane_config(tmp_path, base_url)
        verdict = run_hook(
            "ccag_gatekeeper",
            HookEvent.model_validate(
                {
                    "operation": "unknown_tool",
                    "freshness_class": "baseline_read",
                    "cwd": worktree,
                    "principal_kind": "subagent",
                    "session_id": "sess-001",
                    "cli_args": ["--ak3-principal-attest", "worker"],
                    "operation_args": {"todos": []},
                }
            ),
            phase="pre",
            project_root=tmp_path,
        )
    assert verdict.allowed is False
    assert verdict.detail is not None
    assert verdict.detail["permission_request_opened"] is True
    request_id = str(verdict.detail["permission_request_id"])
    assert _service().read(request_id) is not None
    assert not (tmp_path / ".agentkit" / "ccag" / "ccag_requests.db").exists()


def test_real_hook_rest_failure_is_visibly_fail_closed(
    tmp_path: Path,
    unreachable_base_url: str,
    postgres_isolated_schema: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A failed central open is a named fault and never a silent false flag."""
    del postgres_isolated_schema
    worktree = str(tmp_path / "worktree")
    _publish_story_binding(tmp_path, worktree)
    write_control_plane_config(tmp_path, unreachable_base_url)
    monkeypatch.setenv("AGENTKIT_PROJECT_API_TOKEN", "unreachable-token")
    verdict = run_hook(
        "ccag_gatekeeper",
        HookEvent.model_validate(
            {
                "operation": "unknown_tool",
                "freshness_class": "baseline_read",
                "cwd": worktree,
                "principal_kind": "subagent",
                "session_id": "sess-001",
                "cli_args": ["--ak3-principal-attest", "worker"],
                "operation_args": {"todos": []},
            }
        ),
        phase="pre",
        project_root=tmp_path,
    )
    assert verdict.allowed is False
    assert verdict.detail is not None
    assert verdict.detail["permission_request_persist_failed"] is True
    assert verdict.detail["fault_class"]
    assert "permission_request_opened" not in verdict.detail


def test_mode_lock_holder_identity_and_reentry_use_real_postgres(
    postgres_isolated_schema: str,
) -> None:
    """Central holder identity is the recovery truth and re-entry is idempotent."""
    del postgres_isolated_schema
    repo = ModeLockRepository()
    first = repo.acquire(_PROJECT, _STORY, _RUN, "fast")
    second = repo.acquire(_PROJECT, _STORY, _RUN, "fast")
    holder = repo.read_holder(_PROJECT, _STORY, _RUN)
    assert holder is not None
    assert holder.mode == "fast"
    assert first.holder_count == second.holder_count == 1
    assert repo.list_holders(_PROJECT) == (holder,)
    released = repo.release(_PROJECT, _STORY, _RUN)
    assert released.active_mode is None
    assert released.holder_count == 0
    assert repo.read_holder(_PROJECT, _STORY, _RUN) is None


def test_mode_lock_opposite_concurrency_has_one_postgres_winner(
    postgres_isolated_schema: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The Postgres advisory-lock CAS prevents opposite-mode dual acquisition."""
    del postgres_isolated_schema
    from agentkit.backend.state_backend.persistence_test_support import (
        reset_backend_cache_for_tests,
    )

    monkeypatch.setenv("AGENTKIT_STATE_POOL_MAX_SIZE", "2")
    reset_backend_cache_for_tests()
    barrier = threading.Barrier(2)
    outcomes: list[str] = []

    def acquire(story_id: str, run_id: str, mode: str) -> None:
        barrier.wait()
        try:
            ModeLockRepository().acquire(_PROJECT, story_id, run_id, mode)
            outcomes.append("ok")
        except ModeLockConflictError:
            outcomes.append("conflict")

    threads = [
        threading.Thread(target=acquire, args=("AG3-131-A", "run-a", "fast")),
        threading.Thread(target=acquire, args=("AG3-131-B", "run-b", "standard")),
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert sorted(outcomes) == ["conflict", "ok"]
    assert ModeLockRepository().read_lock(_PROJECT).holder_count == 1  # type: ignore[union-attr]
