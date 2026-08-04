from __future__ import annotations

import json
from datetime import UTC, datetime
from http import HTTPStatus
from threading import Event, Thread
from typing import TYPE_CHECKING

from argon2 import PasswordHasher
from argon2.low_level import Type

from agentkit.backend.auth.credentials import StrategistCredentialStore
from agentkit.backend.auth.entities import ProjectApiToken, StrategistCredentials
from agentkit.backend.auth.http.routes import AuthRoutes
from agentkit.backend.auth.middleware import AuthMiddleware
from agentkit.backend.auth.sessions import FileSessionStore, InMemorySessionStore
from agentkit.backend.control_plane.http import ControlPlaneApplication, HttpResponse
from agentkit.backend.control_plane_http.app import ControlPlaneApplicationRoutes
from agentkit.backend.state_backend.store.inflight_idempotency_guard import (
    IdempotencyRequest,
    InFlightOutcome,
    InMemoryInflightIdempotencyGuard,
    compute_body_hash,
)
from agentkit.harness_client.projectedge.credentials import prepare_project_api_token

if TYPE_CHECKING:
    from pathlib import Path

    import pytest


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

    def insert(self, token: ProjectApiToken) -> None:
        self.save_count += 1
        if token.token_id in self.tokens:
            raise ValueError("duplicate token id")
        self.tokens[token.token_id] = token

    def mark_used(self, token_id: str, *, used_at: object) -> None:
        self.tokens[token_id] = self.tokens[token_id].model_copy(
            update={"last_used_at": used_at},
        )

    def revoke(self, project_key: str, token_id: str) -> None:
        self.revoke_count += 1
        token = self.tokens.get(token_id)
        if token is None or token.project_key != project_key:
            from agentkit.backend.auth.errors import TokenNotFoundError

            raise TokenNotFoundError("Project API token not found")
        self.tokens[token_id] = token.model_copy(update={"revoked_at": token.created_at})


class _PausingRecoveryGuard(InMemoryInflightIdempotencyGuard):
    """Expose the exact recovery-finalize window to a deterministic test."""

    def __init__(self) -> None:
        super().__init__()
        self.recover_entered = Event()
        self.allow_recover = Event()

    def recover(
        self,
        request: IdempotencyRequest,
        result_payload: dict[str, object],
    ) -> bool:
        self.recover_entered.set()
        assert self.allow_recover.wait(timeout=5)
        return super().recover(request, result_payload)


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
    credentials.initialize_password("secret")
    sessions = InMemorySessionStore()
    tokens = _InMemoryTokenRepository()
    routes = AuthRoutes(
        credential_store=credentials,
        session_store=sessions,
        token_repository=tokens,
        idempotency_guard=guard or InMemoryInflightIdempotencyGuard(),
    )
    middleware = AuthMiddleware(session_store=sessions, token_repository=tokens)
    return ControlPlaneApplication(
        routes=ControlPlaneApplicationRoutes(auth_routes=routes),
        auth_middleware=middleware,
        tenant_scope_middleware=_NoopTenantScopeMiddleware(),  # type: ignore[arg-type]
    ), tokens


def _file_session_app(
    tmp_path: Path,
    *,
    guard: InMemoryInflightIdempotencyGuard,
) -> tuple[
    ControlPlaneApplication,
    StrategistCredentialStore,
    FileSessionStore,
]:
    credentials = StrategistCredentialStore(tmp_path / "auth.json")
    credentials.initialize_password("secret")
    sessions = FileSessionStore(credentials)
    tokens = _InMemoryTokenRepository()
    routes = AuthRoutes(
        credential_store=credentials,
        session_store=sessions,
        token_repository=tokens,
        idempotency_guard=guard,
    )
    middleware = AuthMiddleware(session_store=sessions, token_repository=tokens)
    return (
        ControlPlaneApplication(
            routes=ControlPlaneApplicationRoutes(auth_routes=routes),
            auth_middleware=middleware,
            tenant_scope_middleware=_NoopTenantScopeMiddleware(),  # type: ignore[arg-type]
        ),
        credentials,
        sessions,
    )


def _auth_headers(
    app: ControlPlaneApplication,
    correlation_id: str,
    *,
    password: str = "secret",
    username: str = "admin",
    project_key: str = "tenant-a",
) -> dict[str, str]:
    """Log in and return the cookie + CSRF + correlation headers for a mutation."""
    login = app.handle_request(
        method="POST",
        path="/v1/auth/login",
        body=json.dumps({"username": username, "password": password}).encode("utf-8"),
    )
    csrf = str(_json_body(login)["csrf_token"])
    cookie = _header(login, "Set-Cookie").split(";", maxsplit=1)[0]
    return {
        "Cookie": cookie,
        "X-CSRF-Token": csrf,
        "X-Correlation-Id": correlation_id,
        "X-Project-Key": project_key,
    }


def test_login_sets_session_cookie_and_returns_csrf(tmp_path: Path) -> None:
    app, _tokens = _app(tmp_path)

    response = app.handle_request(
        method="POST",
        path="/v1/auth/login",
        body=json.dumps(
            {"username": "admin", "password": "secret"},
        ).encode("utf-8"),
        request_headers={"X-Correlation-Id": "req-login"},
    )

    body = _json_body(response)
    assert response.status_code == HTTPStatus.OK
    assert body["status"] == "authenticated"
    assert isinstance(body["csrf_token"], str)
    assert _header(response, "Set-Cookie").startswith("ak3_session=")


def test_login_maps_a_malformed_persisted_password_hash_to_opaque_unauthorized(
    tmp_path: Path,
) -> None:
    app, _tokens = _app(tmp_path)
    auth_path = tmp_path / "auth.json"
    valid_argon2id = PasswordHasher().hash("submitted-secret")
    valid_argon2i = PasswordHasher(type=Type.I).hash("submitted-secret")
    malformed_documents = (
        {
            "username": "admin",
            "password_hash": "invalid-phc-must-not-escape",
            "hash_algorithm": "argon2id",
        },
        {
            "password_hash": valid_argon2id,
            "hash_algorithm": "argon2id",
        },
        {
            "username": None,
            "password_hash": valid_argon2id,
            "hash_algorithm": "argon2id",
        },
        {
            "username": "admin",
            "password_hash": valid_argon2id,
            "hash_algorithm": "argon2i",
        },
        {
            "username": "admin",
            "password_hash": valid_argon2i,
            "hash_algorithm": "argon2id",
        },
        {
            "username": "admin",
            "password_hash": valid_argon2id,
            "hash_algorithm": "argon2id",
            "unexpected": True,
        },
    )

    for document in malformed_documents:
        auth_path.write_text(json.dumps(document), encoding="utf-8")
        response = app.handle_request(
            method="POST",
            path="/v1/auth/login",
            body=json.dumps(
                {"username": "admin", "password": "submitted-secret"},
            ).encode("utf-8"),
        )

        assert response.status_code == HTTPStatus.UNAUTHORIZED
        body = _json_body(response)
        assert body["error_code"] == "unauthorized"
        rendered = response.body.decode("utf-8")
        assert "invalid-phc" not in rendered
        assert "submitted-secret" not in rendered


def test_logout_replay_without_a_remaining_session_is_successful(tmp_path: Path) -> None:
    app, _tokens = _app(tmp_path)
    headers = _auth_headers(app, "req-logout-first")

    first = app.handle_request(
        method="POST",
        path="/v1/auth/logout",
        body=b"{}",
        request_headers=headers,
    )
    replay = app.handle_request(
        method="POST",
        path="/v1/auth/logout",
        body=b"{}",
        request_headers={"X-Correlation-Id": "req-logout-replay"},
    )

    assert first.status_code == HTTPStatus.OK
    assert replay.status_code == HTTPStatus.OK
    assert _json_body(first)["status"] == "logged_out"
    assert _json_body(replay)["status"] == "logged_out"


def test_project_api_token_lifecycle_routes(tmp_path: Path) -> None:
    app, tokens = _app(tmp_path, guard=InMemoryInflightIdempotencyGuard())
    login = app.handle_request(
        method="POST",
        path="/v1/auth/login",
        body=json.dumps(
            {"username": "admin", "password": "secret"},
        ).encode("utf-8"),
    )
    csrf = str(_json_body(login)["csrf_token"])
    cookie = _header(login, "Set-Cookie").split(";", maxsplit=1)[0]
    headers = {"Cookie": cookie, "X-CSRF-Token": csrf}
    prepared = prepare_project_api_token(project_key="tenant-a", label="edge-client")

    created = app.handle_request(
        method="POST",
        path="/v1/projects/tenant-a/api-tokens",
        body=json.dumps(
            {
                "label": "edge-client",
                "op_id": "op-token-create",
                "token_id": prepared.record.token_id,
                "token_hash": prepared.record.token_hash,
            },
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
    rejected = app.handle_request(
        method="GET",
        path="/v1/projects/tenant-a/stories",
        body=b"",
        request_headers={"Authorization": f"Bearer {prepared.plaintext_token}"},
    )

    create_body = _json_body(created)
    assert created.status_code == HTTPStatus.CREATED
    assert create_body["op_id"] == "op-token-create"
    assert "plaintext_token" not in create_body
    assert listed.status_code == HTTPStatus.OK
    assert _json_body(listed)["tokens"]
    assert deleted.status_code == HTTPStatus.OK
    assert tokens.tokens[token.token_id].revoked_at is not None
    assert rejected.status_code == HTTPStatus.UNAUTHORIZED


def test_project_token_cannot_administer_strategist_or_project_tokens(tmp_path: Path) -> None:
    app, tokens = _app(tmp_path, guard=InMemoryInflightIdempotencyGuard())
    strategist_headers = _auth_headers(app, "corr-create-owner-token")
    owner_token = prepare_project_api_token(project_key="tenant-a", label="edge")
    created = app.handle_request(
        method="POST",
        path="/v1/projects/tenant-a/api-tokens",
        body=json.dumps(
            {
                "label": "edge",
                "op_id": "op-create-owner-token",
                "token_id": owner_token.record.token_id,
                "token_hash": owner_token.record.token_hash,
            },
        ).encode("utf-8"),
        request_headers=strategist_headers,
    )
    assert created.status_code == HTTPStatus.CREATED
    bearer_headers = {
        "Authorization": f"Bearer {owner_token.plaintext_token}",
        "X-Project-Key": "tenant-a",
    }
    replacement = prepare_project_api_token(project_key="tenant-a", label="replacement")
    attempts = (
        ("GET", "/v1/projects/tenant-a/api-tokens", b""),
        (
            "POST",
            "/v1/projects/tenant-a/api-tokens",
            json.dumps(
                {
                    "label": "replacement",
                    "op_id": "op-forbidden-create",
                    "token_id": replacement.record.token_id,
                    "token_hash": replacement.record.token_hash,
                },
            ).encode("utf-8"),
        ),
        (
            "DELETE",
            f"/v1/projects/tenant-a/api-tokens/{owner_token.record.token_id}",
            json.dumps({"op_id": "op-forbidden-revoke"}).encode("utf-8"),
        ),
        (
            "POST",
            "/v1/auth/password",
            json.dumps(
                {"new_password": "attacker-selected", "op_id": "op-forbidden-password"},
            ).encode("utf-8"),
        ),
        ("POST", "/v1/auth/logout", b"{}"),
    )

    for method, path, body in attempts:
        response = app.handle_request(
            method=method,
            path=path,
            body=body,
            request_headers=bearer_headers,
        )
        assert response.status_code == HTTPStatus.FORBIDDEN
        assert _json_body(response)["error_code"] == "strategist_session_required"

    assert replacement.record.token_id not in tokens.tokens
    assert tokens.tokens[owner_token.record.token_id].revoked_at is None
    assert app.handle_request(
        method="POST",
        path="/v1/auth/login",
        body=json.dumps({"username": "admin", "password": "secret"}).encode("utf-8"),
    ).status_code == HTTPStatus.OK


def test_password_validation_error_never_echoes_request_input(tmp_path: Path) -> None:
    app, _tokens = _app(tmp_path, guard=InMemoryInflightIdempotencyGuard())
    secret = "LEAK-ME-NEVER"
    response = app.handle_request(
        method="POST",
        path="/v1/auth/password",
        body=json.dumps({"new_password": secret}).encode("utf-8"),
        request_headers=_auth_headers(app, "corr-password-validation"),
    )

    assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY
    rendered = response.body.decode("utf-8")
    assert secret not in rendered
    assert '"input"' not in rendered


def test_password_rotation_invalidates_sessions_and_changes_login_secret(
    tmp_path: Path,
) -> None:
    app, _tokens = _app(tmp_path)
    headers = _auth_headers(app, "req-password-rotate")

    rotated = app.handle_request(
        method="POST",
        path="/v1/auth/password",
        body=json.dumps(
            {"new_password": "replacement-secret", "op_id": "op-password-rotate"},
        ).encode("utf-8"),
        request_headers=headers,
    )
    stale_session = app.handle_request(
        method="GET",
        path="/v1/projects/tenant-a/api-tokens",
        body=b"",
        request_headers={"Cookie": headers["Cookie"]},
    )
    old_login = app.handle_request(
        method="POST",
        path="/v1/auth/login",
        body=json.dumps({"username": "admin", "password": "secret"}).encode("utf-8"),
    )
    new_login = app.handle_request(
        method="POST",
        path="/v1/auth/login",
        body=json.dumps(
            {"username": "admin", "password": "replacement-secret"},
        ).encode("utf-8"),
    )

    assert rotated.status_code == HTTPStatus.OK
    assert stale_session.status_code == HTTPStatus.UNAUTHORIZED
    assert old_login.status_code == HTTPStatus.UNAUTHORIZED
    assert new_login.status_code == HTTPStatus.OK


def test_password_rotation_replays_after_login_with_new_password(tmp_path: Path) -> None:
    guard = InMemoryInflightIdempotencyGuard()
    app, _tokens = _app(tmp_path, guard=guard)
    request_body = json.dumps(
        {"new_password": "replacement-secret", "op_id": "op-password-replay"},
    ).encode("utf-8")

    first = app.handle_request(
        method="POST",
        path="/v1/auth/password",
        body=request_body,
        request_headers=_auth_headers(app, "req-password-first"),
    )
    replay = app.handle_request(
        method="POST",
        path="/v1/auth/password",
        body=request_body,
        request_headers=_auth_headers(
            app,
            "req-password-replay",
            password="replacement-secret",
            username="admin",
        ),
    )

    assert first.status_code == HTTPStatus.OK
    assert replay.status_code == HTTPStatus.OK
    assert _json_body(replay) == _json_body(first)


def test_password_rotation_rejects_op_id_reuse_with_another_password(tmp_path: Path) -> None:
    guard = InMemoryInflightIdempotencyGuard()
    app, _tokens = _app(tmp_path, guard=guard)
    first = app.handle_request(
        method="POST",
        path="/v1/auth/password",
        body=json.dumps(
            {"new_password": "replacement-secret", "op_id": "op-password-mismatch"},
        ).encode("utf-8"),
        request_headers=_auth_headers(app, "req-password-first"),
    )
    mismatch = app.handle_request(
        method="POST",
        path="/v1/auth/password",
        body=json.dumps(
            {"new_password": "different-secret", "op_id": "op-password-mismatch"},
        ).encode("utf-8"),
        request_headers=_auth_headers(
            app,
            "req-password-mismatch",
            password="replacement-secret",
            username="admin",
        ),
    )

    assert first.status_code == HTTPStatus.OK
    assert mismatch.status_code == HTTPStatus.CONFLICT
    assert _json_body(mismatch)["error_code"] == "idempotency_mismatch"


def test_password_rotation_rejects_cross_project_op_id_replay(tmp_path: Path) -> None:
    guard = InMemoryInflightIdempotencyGuard()
    app, _tokens = _app(tmp_path, guard=guard)
    body = json.dumps(
        {"new_password": "replacement-secret", "op_id": "op-project-bound"},
    ).encode("utf-8")
    first = app.handle_request(
        method="POST",
        path="/v1/auth/password",
        body=body,
        request_headers=_auth_headers(
            app,
            "req-project-a",
            project_key="project-a",
        ),
    )
    cross_project = app.handle_request(
        method="POST",
        path="/v1/auth/password",
        body=body,
        request_headers=_auth_headers(
            app,
            "req-project-b",
            password="replacement-secret",
            username="admin",
            project_key="project-b",
        ),
    )

    assert first.status_code == HTTPStatus.OK
    assert cross_project.status_code == HTTPStatus.CONFLICT
    assert _json_body(cross_project)["error_code"] == "idempotency_mismatch"


def test_parallel_old_password_login_cannot_survive_rotation(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    credentials = StrategistCredentialStore(tmp_path / "auth.json")
    credentials.initialize_password("secret")
    sessions = InMemorySessionStore()
    tokens = _InMemoryTokenRepository()
    routes = AuthRoutes(
        credential_store=credentials,
        session_store=sessions,
        token_repository=tokens,
        idempotency_guard=InMemoryInflightIdempotencyGuard(),
    )
    app = ControlPlaneApplication(
        routes=ControlPlaneApplicationRoutes(auth_routes=routes),
        auth_middleware=AuthMiddleware(session_store=sessions, token_repository=tokens),
        tenant_scope_middleware=_NoopTenantScopeMiddleware(),  # type: ignore[arg-type]
    )
    rotation_headers = _auth_headers(app, "req-existing-session")
    verification_entered = Event()
    allow_verification = Event()
    rotation_finished = Event()
    original_verify = credentials.verify

    def paused_verify(candidate: StrategistCredentials) -> object:
        result = original_verify(candidate)
        if candidate.password == "secret":
            verification_entered.set()
            assert allow_verification.wait(timeout=5)
        return result

    monkeypatch.setattr(credentials, "verify", paused_verify)
    login_responses: list[HttpResponse] = []
    rotation_responses: list[HttpResponse] = []
    login = Thread(
        target=lambda: login_responses.append(
            app.handle_request(
                method="POST",
                path="/v1/auth/login",
                body=json.dumps(
                    {"username": "admin", "password": "secret"},
                ).encode("utf-8"),
            ),
        ),
    )
    rotation = Thread(
        target=lambda: (
            rotation_responses.append(
                app.handle_request(
                    method="POST",
                    path="/v1/auth/password",
                    body=json.dumps(
                        {"new_password": "replacement", "op_id": "op-race"},
                    ).encode("utf-8"),
                    request_headers=rotation_headers,
                ),
            ),
            rotation_finished.set(),
        ),
    )
    login.start()
    assert verification_entered.wait(timeout=5)
    rotation.start()
    assert not rotation_finished.wait(timeout=0.1)
    allow_verification.set()
    login.join(timeout=5)
    rotation.join(timeout=5)

    assert login_responses[0].status_code == HTTPStatus.OK
    assert rotation_responses[0].status_code == HTTPStatus.OK
    stale_cookie = _header(login_responses[0], "Set-Cookie").split(";", maxsplit=1)[0]
    stale = app.handle_request(
        method="GET",
        path="/v1/auth/tokens",
        body=b"",
        request_headers={"Cookie": stale_cookie, "X-Project-Key": "tenant-a"},
    )
    assert stale.status_code == HTTPStatus.UNAUTHORIZED


def test_password_rotation_in_flight_is_rejected_without_changing_secret(
    tmp_path: Path,
) -> None:
    guard = InMemoryInflightIdempotencyGuard()
    app, _tokens = _app(tmp_path, guard=guard)
    payload = {
        "new_password": "must-not-become-active",
        "op_id": "op-password-inflight",
    }
    headers = _auth_headers(app, "req-password-inflight")
    guard.claim(
        IdempotencyRequest(
            op_id="op-password-inflight",
            operation_kind="strategist_password_rotate",
            body_hash=compute_body_hash(payload),
            project_key="tenant-a",
        ),
    )

    response = app.handle_request(
        method="POST",
        path="/v1/auth/password",
        body=json.dumps(payload).encode("utf-8"),
        request_headers=headers,
    )
    old_login = app.handle_request(
        method="POST",
        path="/v1/auth/login",
        body=json.dumps({"username": "admin", "password": "secret"}).encode("utf-8"),
    )
    new_login = app.handle_request(
        method="POST",
        path="/v1/auth/login",
        body=json.dumps(
            {"username": "admin", "password": "must-not-become-active"},
        ).encode("utf-8"),
    )

    assert response.status_code == HTTPStatus.CONFLICT
    assert _json_body(response)["error_code"] == "operation_in_flight"
    assert old_login.status_code == HTTPStatus.OK
    assert new_login.status_code == HTTPStatus.UNAUTHORIZED


def test_same_as_current_password_cannot_terminalize_a_live_rotation_claim(
    tmp_path: Path,
) -> None:
    guard = InMemoryInflightIdempotencyGuard()
    app, _tokens = _app(tmp_path, guard=guard)
    payload = {"new_password": "secret", "op_id": "op-live-same-password"}
    request = IdempotencyRequest(
        op_id="op-live-same-password",
        operation_kind="strategist_password_rotate",
        body_hash=compute_body_hash(payload),
        project_key="tenant-a",
    )
    guard.claim(request)

    response = app.handle_request(
        method="POST",
        path="/v1/auth/password",
        body=json.dumps(payload).encode("utf-8"),
        request_headers=_auth_headers(app, "req-live-same-password"),
    )

    assert response.status_code == HTTPStatus.CONFLICT
    assert _json_body(response)["error_code"] == "operation_in_flight"
    assert isinstance(guard.classify(request), InFlightOutcome)


def test_password_rotation_recovers_crash_after_hash_publish_before_finalize(
    tmp_path: Path,
) -> None:
    guard = InMemoryInflightIdempotencyGuard()
    app, _tokens = _app(tmp_path, guard=guard)
    payload = {
        "new_password": "published-before-crash",
        "op_id": "op-password-orphan",
    }
    headers = _auth_headers(app, "req-password-orphan")
    guard.claim(
        IdempotencyRequest(
            op_id="op-password-orphan",
            operation_kind="strategist_password_rotate",
            body_hash=compute_body_hash(payload),
            project_key="tenant-a",
        ),
    )
    StrategistCredentialStore(tmp_path / "auth.json").rotate_password(
        "published-before-crash",
        op_id="op-password-orphan",
    )

    recovered = app.handle_request(
        method="POST",
        path="/v1/auth/password",
        body=json.dumps(payload).encode("utf-8"),
        request_headers=headers,
    )
    replay = app.handle_request(
        method="POST",
        path="/v1/auth/password",
        body=json.dumps(payload).encode("utf-8"),
        request_headers=_auth_headers(
            app,
            "req-password-orphan-replay",
            password="published-before-crash",
            username="admin",
        ),
    )

    assert recovered.status_code == HTTPStatus.OK
    assert replay.status_code == HTTPStatus.OK
    assert _json_body(replay) == _json_body(recovered)


def test_password_recovery_holds_credential_lock_through_claim_finalization(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    guard = _PausingRecoveryGuard()
    app, _tokens = _app(tmp_path, guard=guard)
    payload = {
        "new_password": "published-before-recovery",
        "op_id": "op-password-atomic-recovery",
    }
    request = IdempotencyRequest(
        op_id="op-password-atomic-recovery",
        operation_kind="strategist_password_rotate",
        body_hash=compute_body_hash(payload),
        project_key="tenant-a",
    )
    headers = _auth_headers(app, "req-password-atomic-recovery")
    guard.claim(request)
    StrategistCredentialStore(tmp_path / "auth.json").rotate_password(
        "published-before-recovery",
        op_id=request.op_id,
    )
    recovered: list[HttpResponse] = []
    later_store = StrategistCredentialStore(tmp_path / "auth.json")
    later_write_entered = Event()
    later_rotation_finished = Event()

    def observe_later_write(
        password: str,
        *,
        last_rotation_op_id: str | None = None,
    ) -> None:
        del password, last_rotation_op_id
        later_write_entered.set()

    monkeypatch.setattr(later_store, "_write_password", observe_later_write)

    recovery = Thread(
        target=lambda: recovered.append(
            app.handle_request(
                method="POST",
                path="/v1/auth/password",
                body=json.dumps(payload).encode("utf-8"),
                request_headers=headers,
            ),
        ),
    )

    def rotate_later() -> None:
        later_store.rotate_password(
            "later-password",
            op_id="op-later-password",
        )
        later_rotation_finished.set()

    later_rotation = Thread(target=rotate_later)
    recovery.start()
    assert guard.recover_entered.wait(timeout=5)
    later_rotation.start()
    later_rotation_was_blocked = not later_write_entered.wait(timeout=0.1)
    guard.allow_recover.set()
    recovery.join(timeout=5)
    later_rotation.join(timeout=5)

    assert not recovery.is_alive()
    assert not later_rotation.is_alive()
    assert later_rotation_was_blocked
    assert later_write_entered.is_set()
    assert later_rotation_finished.is_set()
    assert recovered[0].status_code == HTTPStatus.OK


def test_password_rotation_cleanup_failure_preserves_claim_and_revokes_generation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    guard = InMemoryInflightIdempotencyGuard()
    app, _credentials, sessions = _file_session_app(tmp_path, guard=guard)
    payload = {
        "new_password": "published-before-cleanup-failure",
        "op_id": "op-password-cleanup-failure",
    }
    request = IdempotencyRequest(
        op_id="op-password-cleanup-failure",
        operation_kind="strategist_password_rotate",
        body_hash=compute_body_hash(payload),
        project_key="tenant-a",
    )
    old_headers = _auth_headers(app, "req-password-cleanup-failure")
    original_persist = sessions._persist_sessions

    def fail_cleanup(persisted_sessions: object) -> None:
        if not persisted_sessions:
            raise OSError("session cleanup unavailable")
        original_persist(persisted_sessions)  # type: ignore[arg-type]

    monkeypatch.setattr(sessions, "_persist_sessions", fail_cleanup)
    failed = app.handle_request(
        method="POST",
        path="/v1/auth/password",
        body=json.dumps(payload).encode("utf-8"),
        request_headers=old_headers,
    )
    claim_after_failure = guard.classify(request)
    claim_was_preserved = request.op_id in guard._rows  # noqa: SLF001
    monkeypatch.setattr(sessions, "_persist_sessions", original_persist)

    stale_session = app.handle_request(
        method="GET",
        path="/v1/projects/tenant-a/api-tokens",
        body=b"",
        request_headers=old_headers,
    )
    retry = app.handle_request(
        method="POST",
        path="/v1/auth/password",
        body=json.dumps(payload).encode("utf-8"),
        request_headers=_auth_headers(
            app,
            "req-password-cleanup-retry",
            password="published-before-cleanup-failure",
        ),
    )

    assert failed.status_code == HTTPStatus.INTERNAL_SERVER_ERROR
    assert _json_body(failed)["error_code"] == "operation_completion_failed"
    assert isinstance(claim_after_failure, InFlightOutcome)
    assert claim_was_preserved
    assert stale_session.status_code == HTTPStatus.UNAUTHORIZED
    assert retry.status_code == HTTPStatus.OK
    assert not isinstance(guard.classify(request), InFlightOutcome)


def test_create_token_recovers_crash_after_insert_before_finalize(tmp_path: Path) -> None:
    guard = InMemoryInflightIdempotencyGuard()
    app, tokens = _app(tmp_path, guard=guard)
    headers = _auth_headers(app, "req-token-orphan")
    payload = {
        "label": "edge-client",
        "op_id": "op-token-orphan",
        "token_id": "a" * 32,
        "token_hash": "b" * 64,
    }
    guard.claim(
        IdempotencyRequest(
            op_id="op-token-orphan",
            operation_kind="project_api_token_create",
            body_hash=compute_body_hash(
                {**payload, "target_project_key": "tenant-a"},
            ),
            project_key="tenant-a",
        ),
    )
    tokens.insert(
        ProjectApiToken(
            token_id="a" * 32,
            project_key="tenant-a",
            label="edge-client",
            token_hash="b" * 64,
            created_at=datetime.now(UTC),
        ),
    )

    recovered = _create_token(
        app,
        headers,
        op_id="op-token-orphan",
        token_id="a" * 32,
        token_hash="b" * 64,
    )
    replay = _create_token(
        app,
        headers,
        op_id="op-token-orphan",
        token_id="a" * 32,
        token_hash="b" * 64,
    )

    assert recovered.status_code == HTTPStatus.CREATED
    assert replay.status_code == HTTPStatus.CREATED
    assert _json_body(replay) == _json_body(recovered)
    assert tokens.save_count == 1


# ---------------------------------------------------------------------------
# AG3-140 / FK-91 §91.1a Rule 5 — unified idempotency contract on auth mutations
# ---------------------------------------------------------------------------


def _create_token(
    app: ControlPlaneApplication,
    headers: dict[str, str],
    *,
    project_key: str = "tenant-a",
    label: str = "edge-client",
    op_id: str = "op-create",
    token_id: str = "1" * 32,
    token_hash: str = "2" * 64,
) -> HttpResponse:
    return app.handle_request(
        method="POST",
        path=f"/v1/projects/{project_key}/api-tokens",
        body=json.dumps(
            {
                "label": label,
                "op_id": op_id,
                "token_id": token_id,
                "token_hash": token_hash,
            },
        ).encode("utf-8"),
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
    assert first_body["token"] == second_body["token"]
    assert "plaintext_token" not in first_body
    # Registration ran exactly once (one save, one stored hash-only token).
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
