from __future__ import annotations

import json
from http import HTTPStatus
from typing import TYPE_CHECKING

from agentkit.backend.auth.credentials import StrategistCredentialStore
from agentkit.backend.auth.http.routes import AuthRoutes
from agentkit.backend.auth.middleware import AuthMiddleware
from agentkit.backend.auth.sessions import InMemorySessionStore
from agentkit.backend.control_plane.http import ControlPlaneApplication, HttpResponse
from agentkit.backend.control_plane_http.app import ControlPlaneApplicationRoutes
from agentkit.backend.state_backend.store.inflight_idempotency_guard import (
    IdempotencyRequest,
    InMemoryInflightIdempotencyGuard,
)

if TYPE_CHECKING:
    from pathlib import Path

    from agentkit.backend.auth.entities import ProjectApiToken


class _InMemoryTokenRepository:
    def __init__(self) -> None:
        self.tokens: dict[str, ProjectApiToken] = {}
        #: AG3-140 evidence counters: a replay must NOT re-invoke the repository.
        self.save_count = 0
        self.revoke_count = 0

    def get(self, token_id: str) -> ProjectApiToken | None:
        return self.tokens.get(token_id)

    def get_by_hash(self, token_hash: str) -> ProjectApiToken | None:
        for token in self.tokens.values():
            if token.token_hash == token_hash:
                return token
        return None

    def list_for_project(self, project_key: str) -> list[ProjectApiToken]:
        return [token for token in self.tokens.values() if token.project_key == project_key]

    def save(self, token: ProjectApiToken) -> None:
        self.save_count += 1
        self.tokens[token.token_id] = token

    def revoke(self, project_key: str, token_id: str) -> None:
        self.revoke_count += 1
        token = self.tokens.get(token_id)
        if token is None or token.project_key != project_key:
            from agentkit.backend.auth.errors import TokenNotFoundError

            raise TokenNotFoundError("Project API token not found")
        self.tokens[token_id] = token.model_copy(update={"revoked_at": token.created_at})


def _json_body(response: HttpResponse) -> dict[str, object]:
    body = json.loads(response.body)
    assert isinstance(body, dict)
    return body


def _header(response: HttpResponse, name: str) -> str:
    for key, value in response.headers:
        if key == name:
            return value
    raise AssertionError(f"Missing header {name}")


class _NoopTenantScopeMiddleware:
    """Passthrough stub: all project-scoped paths pass without DB access (AG3-090)."""

    def validate(self, *, method: str, route_path: str, correlation_id: str) -> None:
        return None


def _app(
    tmp_path: Path,
    *,
    guard: InMemoryInflightIdempotencyGuard | None = None,
) -> tuple[ControlPlaneApplication, _InMemoryTokenRepository]:
    credentials = StrategistCredentialStore(tmp_path / "auth.json")
    credentials.set_password("secret", username="strategist")
    sessions = InMemorySessionStore()
    tokens = _InMemoryTokenRepository()
    routes = AuthRoutes(
        credential_store=credentials,
        session_store=sessions,
        token_repository=tokens,
        idempotency_guard=guard,
    )
    middleware = AuthMiddleware(session_store=sessions, token_repository=tokens)
    return ControlPlaneApplication(
        routes=ControlPlaneApplicationRoutes(auth_routes=routes),
        auth_middleware=middleware,
        tenant_scope_middleware=_NoopTenantScopeMiddleware(),  # type: ignore[arg-type]
    ), tokens


def _auth_headers(app: ControlPlaneApplication, correlation_id: str) -> dict[str, str]:
    """Log in and return the cookie + CSRF + correlation headers for a mutation."""
    login = app.handle_request(
        method="POST",
        path="/v1/auth/login",
        body=json.dumps({"username": "strategist", "password": "secret"}).encode("utf-8"),
    )
    csrf = str(_json_body(login)["csrf_token"])
    cookie = _header(login, "Set-Cookie").split(";", maxsplit=1)[0]
    return {"Cookie": cookie, "X-CSRF-Token": csrf, "X-Correlation-Id": correlation_id}


def test_login_sets_session_cookie_and_returns_csrf(tmp_path: Path) -> None:
    app, _tokens = _app(tmp_path)

    response = app.handle_request(
        method="POST",
        path="/v1/auth/login",
        body=json.dumps(
            {"username": "strategist", "password": "secret"},
        ).encode("utf-8"),
        request_headers={"X-Correlation-Id": "req-login"},
    )

    body = _json_body(response)
    assert response.status_code == HTTPStatus.OK
    assert body["status"] == "authenticated"
    assert isinstance(body["csrf_token"], str)
    assert _header(response, "Set-Cookie").startswith("ak3_session=")


def test_project_api_token_lifecycle_routes(tmp_path: Path) -> None:
    app, tokens = _app(tmp_path, guard=InMemoryInflightIdempotencyGuard())
    login = app.handle_request(
        method="POST",
        path="/v1/auth/login",
        body=json.dumps(
            {"username": "strategist", "password": "secret"},
        ).encode("utf-8"),
    )
    csrf = str(_json_body(login)["csrf_token"])
    cookie = _header(login, "Set-Cookie").split(";", maxsplit=1)[0]
    headers = {"Cookie": cookie, "X-CSRF-Token": csrf}

    created = app.handle_request(
        method="POST",
        path="/v1/projects/tenant-a/api-tokens",
        body=json.dumps(
            {"label": "edge-client", "op_id": "op-token-create"},
        ).encode("utf-8"),
        request_headers=headers,
    )
    listed = app.handle_request(
        method="GET",
        path="/v1/projects/tenant-a/api-tokens",
        body=b"",
        request_headers={"Cookie": cookie},
    )
    token = next(iter(tokens.tokens.values()))
    deleted = app.handle_request(
        method="DELETE",
        path=f"/v1/projects/tenant-a/api-tokens/{token.token_id}",
        body=json.dumps({"op_id": "op-token-revoke"}).encode("utf-8"),
        request_headers=headers,
    )

    create_body = _json_body(created)
    assert created.status_code == HTTPStatus.CREATED
    assert create_body["op_id"] == "op-token-create"
    assert "plaintext_token" in create_body
    assert listed.status_code == HTTPStatus.OK
    assert _json_body(listed)["tokens"]
    assert deleted.status_code == HTTPStatus.OK
    assert tokens.tokens[token.token_id].revoked_at is not None


# ---------------------------------------------------------------------------
# AG3-140 / FK-91 §91.1a Regel 5 — unified idempotency contract on auth mutations
# ---------------------------------------------------------------------------


def _create_token(
    app: ControlPlaneApplication,
    headers: dict[str, str],
    *,
    project_key: str = "tenant-a",
    label: str = "edge-client",
    op_id: str = "op-create",
) -> HttpResponse:
    return app.handle_request(
        method="POST",
        path=f"/v1/projects/{project_key}/api-tokens",
        body=json.dumps({"label": label, "op_id": op_id}).encode("utf-8"),
        request_headers=headers,
    )


def _revoke_token(
    app: ControlPlaneApplication,
    headers: dict[str, str],
    *,
    project_key: str = "tenant-a",
    token_id: str,
    op_id: str = "op-revoke",
) -> HttpResponse:
    return app.handle_request(
        method="DELETE",
        path=f"/v1/projects/{project_key}/api-tokens/{token_id}",
        body=json.dumps({"op_id": op_id}).encode("utf-8"),
        request_headers=headers,
    )


def test_create_token_missing_op_id_returns_422(tmp_path: Path) -> None:
    app, _tokens = _app(tmp_path, guard=InMemoryInflightIdempotencyGuard())
    headers = _auth_headers(app, "req-c-422")

    response = app.handle_request(
        method="POST",
        path="/v1/projects/tenant-a/api-tokens",
        body=json.dumps({"label": "edge-client"}).encode("utf-8"),
        request_headers=headers,
    )

    assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY
    assert _json_body(response)["error_code"] == "invalid_project_api_token_payload"


def test_revoke_token_missing_op_id_returns_422(tmp_path: Path) -> None:
    app, _tokens = _app(tmp_path, guard=InMemoryInflightIdempotencyGuard())
    headers = _auth_headers(app, "req-r-422")

    response = app.handle_request(
        method="DELETE",
        path="/v1/projects/tenant-a/api-tokens/tok-1",
        body=json.dumps({}).encode("utf-8"),
        request_headers=headers,
    )

    assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY
    assert _json_body(response)["error_code"] == "invalid_project_api_token_revoke_payload"


def test_create_token_replay_returns_same_token_and_issues_once(tmp_path: Path) -> None:
    # Codex's exact scenario: two identical POSTs with the same op_id must replay
    # ONE minted token, not mint two different plaintext tokens.
    guard = InMemoryInflightIdempotencyGuard()
    app, tokens = _app(tmp_path, guard=guard)
    headers = _auth_headers(app, "req-replay")

    first = _create_token(app, headers, op_id="op-dup")
    second = _create_token(app, headers, op_id="op-dup")

    first_body = _json_body(first)
    second_body = _json_body(second)
    assert first.status_code == HTTPStatus.CREATED
    assert second.status_code == HTTPStatus.CREATED
    # The KEY FIX: the replay returns the SAME plaintext token.
    assert first_body["plaintext_token"] == second_body["plaintext_token"]
    assert first_body["token"] == second_body["token"]
    # issue_project_api_token ran exactly once (one save, one stored token).
    assert tokens.save_count == 1
    assert len(tokens.tokens) == 1


def test_create_token_body_mismatch_returns_409(tmp_path: Path) -> None:
    guard = InMemoryInflightIdempotencyGuard()
    app, tokens = _app(tmp_path, guard=guard)
    headers = _auth_headers(app, "req-mismatch")

    first = _create_token(app, headers, op_id="op-x", label="label-a")
    # Same op_id, DIFFERENT label -> fail-closed 409 idempotency_mismatch.
    second = _create_token(app, headers, op_id="op-x", label="label-b")

    assert first.status_code == HTTPStatus.CREATED
    assert second.status_code == HTTPStatus.CONFLICT
    body = _json_body(second)
    assert body["error_code"] == "idempotency_mismatch"
    # The second request never re-minted a token.
    assert tokens.save_count == 1


def test_create_token_cross_project_mismatch_returns_409(tmp_path: Path) -> None:
    # Same op_id + same body fields, DIFFERENT project_key -> the target project is
    # folded into the body-hash, so this is a 409 mismatch, not a wrong replay.
    guard = InMemoryInflightIdempotencyGuard()
    app, tokens = _app(tmp_path, guard=guard)
    headers = _auth_headers(app, "req-cross")

    first = _create_token(app, headers, project_key="tenant-a", op_id="op-cross")
    second = _create_token(app, headers, project_key="tenant-b", op_id="op-cross")

    assert first.status_code == HTTPStatus.CREATED
    assert second.status_code == HTTPStatus.CONFLICT
    assert _json_body(second)["error_code"] == "idempotency_mismatch"
    assert tokens.save_count == 1


def test_create_token_in_flight_returns_409(tmp_path: Path) -> None:
    # Pre-claim the op_id on the shared guard (a concurrent caller holds it) so the
    # real request loses the claim and is rejected 409 operation_in_flight.
    guard = InMemoryInflightIdempotencyGuard()
    app, tokens = _app(tmp_path, guard=guard)
    headers = _auth_headers(app, "req-inflight")
    guard.claim(
        IdempotencyRequest(
            op_id="op-parallel",
            operation_kind="project_api_token_create",
            body_hash="pre-claim-hash",
            project_key="tenant-a",
        )
    )

    response = _create_token(app, headers, op_id="op-parallel")

    assert response.status_code == HTTPStatus.CONFLICT
    body = _json_body(response)
    assert body["error_code"] == "operation_in_flight"
    # The in-flight rejection never minted a token.
    assert tokens.save_count == 0


def test_revoke_token_in_flight_returns_409(tmp_path: Path) -> None:
    guard = InMemoryInflightIdempotencyGuard()
    app, tokens = _app(tmp_path, guard=guard)
    headers = _auth_headers(app, "req-r-inflight")
    guard.claim(
        IdempotencyRequest(
            op_id="op-r-parallel",
            operation_kind="project_api_token_revoke",
            body_hash="pre-claim-hash",
            project_key="tenant-a",
        )
    )

    response = _revoke_token(app, headers, token_id="tok-1", op_id="op-r-parallel")

    assert response.status_code == HTTPStatus.CONFLICT
    assert _json_body(response)["error_code"] == "operation_in_flight"
    assert tokens.revoke_count == 0


def test_revoke_token_replay_returns_same_success_and_revokes_once(tmp_path: Path) -> None:
    guard = InMemoryInflightIdempotencyGuard()
    app, tokens = _app(tmp_path, guard=guard)
    headers = _auth_headers(app, "req-r-replay")
    created = _create_token(app, headers, op_id="op-r-seed")
    assert created.status_code == HTTPStatus.CREATED
    token_id = next(iter(tokens.tokens.values())).token_id

    first = _revoke_token(app, headers, token_id=token_id, op_id="op-r-dup")
    second = _revoke_token(app, headers, token_id=token_id, op_id="op-r-dup")

    assert first.status_code == HTTPStatus.OK
    assert second.status_code == HTTPStatus.OK
    assert _json_body(first) == _json_body(second)
    # revoke ran exactly once; the replay never re-entered the repository.
    assert tokens.revoke_count == 1


def test_revoke_token_replay_after_not_found_returns_same_404(tmp_path: Path) -> None:
    # A deterministic 404 is a business outcome (<500): it is finalized, so a
    # replay of the same op_id returns the SAME 404 and revoke ran exactly once.
    guard = InMemoryInflightIdempotencyGuard()
    app, tokens = _app(tmp_path, guard=guard)
    headers = _auth_headers(app, "req-r-404")

    first = _revoke_token(app, headers, token_id="missing-tok", op_id="op-r-404")
    second = _revoke_token(app, headers, token_id="missing-tok", op_id="op-r-404")

    assert first.status_code == HTTPStatus.NOT_FOUND
    assert second.status_code == HTTPStatus.NOT_FOUND
    assert _json_body(first)["error_code"] == "project_api_token_not_found"
    assert _json_body(first) == _json_body(second)
    # revoke was attempted once; the replay did not re-invoke the repository.
    assert tokens.revoke_count == 1


def test_revoke_token_cross_token_mismatch_returns_409(tmp_path: Path) -> None:
    # Same op_id reused against a DIFFERENT token_id -> the target token is folded
    # into the body-hash, so this is a 409 mismatch (never a wrong-target replay).
    guard = InMemoryInflightIdempotencyGuard()
    app, tokens = _app(tmp_path, guard=guard)
    headers = _auth_headers(app, "req-r-cross")

    first = _revoke_token(app, headers, token_id="missing-a", op_id="op-r-cross")
    second = _revoke_token(app, headers, token_id="missing-b", op_id="op-r-cross")

    assert first.status_code == HTTPStatus.NOT_FOUND
    assert second.status_code == HTTPStatus.CONFLICT
    assert _json_body(second)["error_code"] == "idempotency_mismatch"
