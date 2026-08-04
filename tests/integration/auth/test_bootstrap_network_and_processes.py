from __future__ import annotations

import getpass
import json
import multiprocessing
import os
import socket
import ssl
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from contextlib import contextmanager
from http import HTTPStatus
from http.server import ThreadingHTTPServer
from pathlib import Path
from queue import Empty
from typing import TYPE_CHECKING, cast

import pytest
from tests.fixtures.third_party_preflight import FakeThirdPartyClientFactory
from tests.fixtures.vectordb_installer import wire_ready_vectordb

from agentkit.backend.auth.credentials import StrategistCredentialStore
from agentkit.backend.auth.errors import AuthFailedError, BootstrapAlreadyCompletedError
from agentkit.backend.auth.http.routes import AuthRoutes
from agentkit.backend.auth.middleware import AuthMiddleware
from agentkit.backend.auth.sessions import FileSessionStore
from agentkit.backend.cli.main import main
from agentkit.backend.control_plane.http import ControlPlaneApplication
from agentkit.backend.control_plane_http.app import (
    ControlPlaneApplicationRoutes,
    _build_handler,
    serve_control_plane,
)
from agentkit.backend.control_plane_http.third_party_validation_routes import (
    ThirdPartyValidationRoutes,
)
from agentkit.backend.installer.bounded_executor import BoundedThreadExecutor
from agentkit.backend.installer.third_party_clients import (
    EnvironmentSecretResolver,
    ThirdPartyClientFactory,
)
from agentkit.backend.installer.third_party_preflight import ThirdPartyPreflightService
from agentkit.backend.state_backend.operation_ledger import load_control_plane_operation_global
from agentkit.backend.state_backend.store.auth_repository import (
    StateBackendProjectApiTokenRepository,
)
from agentkit.backend.state_backend.store.inflight_idempotency_guard import (
    StateBackendInflightIdempotencyGuard,
)
from agentkit.harness_client.projectedge.auth_operator import (
    authenticate_strategist,
    provision_project_credentials,
    revoke_project_token,
)
from agentkit.harness_client.projectedge.client import HttpsJsonTransport
from agentkit.harness_client.projectedge.credentials import (
    load_active_project_credentials,
    load_reconciled_active_project_credentials,
    prepare_project_api_token,
    project_credentials_path,
    write_pending_project_credentials,
)

if TYPE_CHECKING:
    from collections.abc import Iterator
    from multiprocessing.queues import Queue
    from multiprocessing.synchronize import Event


def _bootstrap_process(
    auth_path: str,
    password: str,
    op_id: str,
    start: Event,
    results: Queue,
) -> None:
    del op_id
    start.wait(timeout=10)
    try:
        StrategistCredentialStore(Path(auth_path)).initialize_password(password)
        status = HTTPStatus.CREATED
    except BootstrapAlreadyCompletedError:
        status = HTTPStatus.CONFLICT
    results.put((password, status))


def _hold_bootstrap_lock(auth_path: str, locked: Event) -> None:
    store = StrategistCredentialStore(Path(auth_path))
    with store._mutation_lock():
        locked.set()
        multiprocessing.Event().wait(timeout=60)


def _create_cross_profile_session(
    auth_path: str,
    ready: Event,
    release: Event,
    results: Queue,
) -> None:
    sessions = FileSessionStore(StrategistCredentialStore(Path(auth_path)))
    session = sessions.create()
    results.put(("created", session.session_id))
    ready.set()
    if not release.wait(timeout=10):
        results.put(("release_timeout", session.session_id))
        return
    try:
        sessions.validate(session.session_id)
    except AuthFailedError:
        results.put(("revoked", session.session_id))
    else:
        results.put(("still_valid", session.session_id))


def _rotate_and_revoke_cross_profile_sessions(
    auth_path: str,
    ready: Event,
    results: Queue,
) -> None:
    if not ready.wait(timeout=10):
        results.put(("ready_timeout", ""))
        return
    credentials = StrategistCredentialStore(Path(auth_path))
    sessions = FileSessionStore(credentials)
    with credentials.transition_lock():
        credentials.rotate_password(
            "cross-profile-replacement",
            op_id="op-cross-profile-replacement",
        )
        sessions.revoke_all()
        session_path = Path(auth_path).with_name(
            f"{Path(auth_path).stem}.sessions{Path(auth_path).suffix}",
        )
        session_count = len(
            json.loads(session_path.read_text(encoding="utf-8"))["sessions"],
        )
    results.put(("session_count", str(session_count)))
    results.put(("rotated", ""))


def _serve_auth_process(
    auth_path: str,
    port: int,
    certfile: str,
    keyfile: str,
) -> None:
    os.environ["SONARQUBE_TOKEN"] = "backend-sonar-token"
    os.environ["JENKINS_TOKEN"] = "backend-jenkins-token"
    token_repository = StateBackendProjectApiTokenRepository(Path(auth_path).parent)
    routes = AuthRoutes(
        credential_store=StrategistCredentialStore(Path(auth_path)),
        token_repository=token_repository,
    )
    middleware = AuthMiddleware(
        session_store=routes.session_store,
        token_repository=token_repository,
    )
    third_party_service = ThirdPartyPreflightService(
        resolver=EnvironmentSecretResolver(),
        clients=cast("ThirdPartyClientFactory", FakeThirdPartyClientFactory()),
        guard=StateBackendInflightIdempotencyGuard(),
        operation_loader=load_control_plane_operation_global,
        executor=BoundedThreadExecutor(max_workers=1, max_queued=1),
    )
    app = ControlPlaneApplication(
        routes=ControlPlaneApplicationRoutes(
            auth_routes=routes,
            third_party_validation_routes=ThirdPartyValidationRoutes(third_party_service),
        ),
        auth_middleware=middleware,
    )
    serve_control_plane(
        host="127.0.0.1",
        port=port,
        certfile=Path(certfile),
        keyfile=Path(keyfile),
        app=app,
    )


class _ProcessTokenTransport:
    def __init__(self, entered: Queue, release: Event) -> None:
        self._entered = entered
        self._release = release

    def send(
        self,
        *,
        method: str,
        path: str,
        payload: dict[str, object] | None = None,
        headers: object = None,
        timeout: float | None = None,
    ) -> dict[str, object]:
        del method, path, headers, timeout
        assert payload is not None
        self._entered.put(dict(payload))
        if not self._release.wait(timeout=20):
            raise TimeoutError("credential concurrency test did not release transport")
        return {"status": "committed", "token": {"token_id": payload["token_id"]}}


class _ImmediateTokenTransport:
    def send(
        self,
        *,
        method: str,
        path: str,
        payload: dict[str, object] | None = None,
        headers: object = None,
        timeout: float | None = None,
    ) -> dict[str, object]:
        del method, path, headers, timeout
        assert payload is not None
        return {"status": "committed", "token": {"token_id": payload["token_id"]}}


def _issue_credential_process(
    project_root: str,
    start: Event,
    entered: Queue,
    release: Event,
    results: Queue,
    process_name: str,
) -> None:
    start.wait(timeout=20)
    try:
        result = provision_project_credentials(
            _ProcessTokenTransport(entered, release),
            project_root=Path(project_root),
            project_key="process-project",
            label=process_name,
            op_id=f"op-{process_name}",
            replace_active=True,
        )
    except Exception as exc:  # noqa: BLE001 - process boundary reports exact failure
        results.put(("error", type(exc).__name__, str(exc)))
        return
    results.put(("ok", result.token_id, ""))


def _publish_then_pause_credential_process(
    project_root: str,
    published: Event,
    release: Event,
    results: Queue,
) -> None:
    from agentkit.harness_client.projectedge import credentials as credentials_module

    original_remove = credentials_module._remove_activated_pending

    def pause_after_publication(pending_path: Path) -> None:
        published.set()
        if not release.wait(timeout=20):
            raise TimeoutError("runtime/operator lock test did not release publication")
        original_remove(pending_path)

    credentials_module._remove_activated_pending = pause_after_publication
    try:
        result = provision_project_credentials(
            _ImmediateTokenTransport(),
            project_root=Path(project_root),
            project_key="process-project",
            label="operator",
            op_id="op-runtime-operator",
        )
    except Exception as exc:  # noqa: BLE001 - process boundary reports exact failure
        results.put(("operator_error", type(exc).__name__, str(exc)))
        return
    results.put(("operator_ok", result.token_id, ""))


def _runtime_reconcile_process(
    project_root: str,
    published: Event,
    results: Queue,
) -> None:
    if not published.wait(timeout=20):
        results.put(("runtime_error", "TimeoutError", "active publication was not observed"))
        return
    try:
        credential = load_reconciled_active_project_credentials(
            project_credentials_path(Path(project_root)),
            project_key="process-project",
        )
    except Exception as exc:  # noqa: BLE001 - process boundary reports exact failure
        results.put(("runtime_error", type(exc).__name__, str(exc)))
        return
    results.put(("runtime_ok", credential.token_id, ""))


def _store_handed_off_token_process(
    project_root: str,
    base_url: str,
    ca_file: str,
    project_key: str,
    project_api_token: str,
    results: Queue,
) -> None:
    os.chdir(project_root)
    os.environ.pop("AGENTKIT_AUTH_CONFIG", None)
    for name in tuple(os.environ):
        if "STRATEGIST" in name.upper() or "ADMIN_PASSWORD" in name.upper():
            os.environ.pop(name, None)
    prompts: list[str] = []

    def _read_handed_off_token(prompt: str) -> str:
        prompts.append(prompt)
        if prompt != "Project API token: ":
            raise AssertionError(f"unexpected client-side secret prompt: {prompt}")
        return project_api_token

    getpass.getpass = _read_handed_off_token
    sys.stdin.isatty = lambda: True
    sys.stdout.isatty = lambda: True
    sys.stderr.isatty = lambda: True
    exit_code = main(
        [
            "auth",
            "store-token",
            "--base-url",
            base_url,
            "--ca-file",
            ca_file,
            "--project-key",
            project_key,
            "--project-root",
            project_root,
        ],
    )
    results.put(
        (
            exit_code,
            os.environ.get("AGENTKIT_AUTH_CONFIG"),
            any(
                "STRATEGIST" in name.upper() or "ADMIN_PASSWORD" in name.upper()
                for name in os.environ
            ),
            tuple(prompts),
        ),
    )


def _generate_loopback_certificate(directory: Path) -> tuple[Path, Path]:
    certfile = directory / "loopback-cert.pem"
    keyfile = directory / "loopback-key.pem"
    subprocess.run(
        [
            "openssl",
            "req",
            "-x509",
            "-newkey",
            "rsa:2048",
            "-nodes",
            "-keyout",
            str(keyfile),
            "-out",
            str(certfile),
            "-days",
            "1",
            "-subj",
            "/CN=127.0.0.1",
            "-addext",
            "subjectAltName=IP:127.0.0.1",
        ],
        check=True,
        capture_output=True,
        encoding="utf-8",
        text=True,
    )
    return certfile, keyfile


def _unused_loopback_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


def _local_non_loopback_address() -> str:
    candidates = {
        str(sockaddr[0])
        for _family, _type, _proto, _canonname, sockaddr in socket.getaddrinfo(
            socket.gethostname(),
            None,
            family=socket.AF_INET,
        )
    }
    return next(address for address in candidates if not address.startswith("127."))


def _wait_for_https_health(
    base_url: str,
    context: ssl.SSLContext,
    process: multiprocessing.Process,
) -> None:
    request = urllib.request.Request(f"{base_url}/healthz", method="GET")
    for _attempt in range(100):
        if process.exitcode is not None:
            raise AssertionError(f"Serve process exited before readiness: {process.exitcode}")
        try:
            with urllib.request.urlopen(request, context=context, timeout=1) as response:
                if response.status == HTTPStatus.OK:
                    return
        except (OSError, urllib.error.URLError):
            multiprocessing.Event().wait(timeout=0.1)
    raise AssertionError("Serve process did not become ready")


@contextmanager
def _live_https_serve(
    auth_path: Path,
    tls_directory: Path,
) -> Iterator[tuple[str, ssl.SSLContext, Path]]:
    certfile, keyfile = _generate_loopback_certificate(tls_directory)
    port = _unused_loopback_port()
    process = multiprocessing.get_context("spawn").Process(
        target=_serve_auth_process,
        args=(str(auth_path), port, str(certfile), str(keyfile)),
    )
    process.start()
    context = ssl.create_default_context(cafile=str(certfile))
    base_url = f"https://127.0.0.1:{port}"
    try:
        _wait_for_https_health(base_url, context, process)
        yield base_url, context, certfile
    finally:
        process.terminate()
        process.join(timeout=20)
        if process.is_alive():
            process.kill()
            process.join(timeout=20)


@contextmanager
def _live_http_app(
    app: ControlPlaneApplication,
    *,
    host: str,
) -> Iterator[tuple[str, int]]:
    server = ThreadingHTTPServer((host, 0), _build_handler(app))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    address, port = server.server_address[:2]
    try:
        yield str(address), int(port)
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=10)


def _auth_app(auth_path: Path) -> tuple[ControlPlaneApplication, AuthRoutes]:
    credentials = StrategistCredentialStore(auth_path)
    routes = AuthRoutes(credential_store=credentials)
    middleware = AuthMiddleware(
        session_store=routes.session_store,
        token_repository=routes.token_repository,
    )
    return (
        ControlPlaneApplication(
            routes=ControlPlaneApplicationRoutes(auth_routes=routes),
            auth_middleware=middleware,
        ),
        routes,
    )


def _post_status(
    url: str,
    payload: dict[str, object],
    *,
    headers: dict[str, str] | None = None,
) -> int:
    request_headers = {"Content-Type": "application/json"}
    request_headers.update(headers or {})
    request = urllib.request.Request(
        url,
        method="POST",
        data=json.dumps(payload).encode("utf-8"),
        headers=request_headers,
    )
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with opener.open(request, timeout=20) as response:
            return response.status
    except urllib.error.HTTPError as exc:
        status = exc.code
        exc.close()
        return status


def _bearer_get_status(
    url: str,
    *,
    token: str,
    project_key: str,
    context: ssl.SSLContext | None = None,
) -> int:
    request = urllib.request.Request(
        url,
        method="GET",
        headers={"Authorization": f"Bearer {token}", "X-Project-Key": project_key},
    )
    handlers: list[urllib.request.BaseHandler] = [urllib.request.ProxyHandler({})]
    if context is not None:
        handlers.append(urllib.request.HTTPSHandler(context=context))
    opener = urllib.request.build_opener(*handlers)
    try:
        with opener.open(request, timeout=20) as response:
            return response.status
    except urllib.error.HTTPError as exc:
        status = exc.code
        exc.close()
        return status


def _create_project_over_admin_surface(
    session: HttpsJsonTransport,
    *,
    project_key: str,
) -> None:
    response = session.send(
        method="POST",
        path="/v1/projects",
        payload={
            "key": project_key,
            "name": "Role-separated project",
            "story_id_prefix": "RSP",
            "configuration": {
                "repo_url": "",
                "default_branch": "main",
                "are_url": None,
                "default_worker_count": 1,
                "repositories": ["https://example.test/role-separated.git"],
            },
            "op_id": f"op-create-{project_key}",
        },
    )
    assert response.get("status") == "committed"


def _bootstrap_and_issue_token_via_admin_cli(
    *,
    auth_path: Path,
    base_url: str,
    tls_context: ssl.SSLContext,
    certfile: Path,
    project_key: str,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> str:
    admin_password = "backend-admin-only-secret"
    answers = iter((admin_password, admin_password, admin_password))
    monkeypatch.setattr("getpass.getpass", lambda _prompt: next(answers))
    assert main(["auth", "bootstrap", "--auth-config", str(auth_path)]) == 0
    session = authenticate_strategist(
        HttpsJsonTransport(base_url=base_url, ssl_context=tls_context),
        password=admin_password,
        project_key=project_key,
    )
    _create_project_over_admin_surface(session, project_key=project_key)
    capsys.readouterr()
    assert main(
        [
            "auth",
            "issue-token",
            "--base-url",
            base_url,
            "--ca-file",
            str(certfile),
            "--project-key",
            project_key,
        ],
    ) == 0
    output = capsys.readouterr()
    issued = json.loads(output.out.strip().splitlines()[-1])
    token = issued["project_api_token"]
    assert isinstance(token, str)
    assert output.out.count(token) == 1
    assert token not in output.err
    return token


def test_authenticated_non_loopback_request_finds_no_http_bootstrap_route(
    tmp_path: Path,
) -> None:
    auth_path = tmp_path / "auth.json"
    StrategistCredentialStore(auth_path).initialize_password("known-admin-password")
    app, routes = _auth_app(auth_path)
    session = routes.session_store.create()
    with _live_http_app(app, host="0.0.0.0") as (_host, port):
        status = _post_status(
            f"http://{_local_non_loopback_address()}:{port}/v1/auth/bootstrap",
            {"password": "nonlocal-secret", "op_id": "op-nonlocal"},
            headers={
                "Cookie": f"ak3_session={session.session_id}",
                "X-CSRF-Token": session.csrf_token,
                "X-Project-Key": "role-separated",
            },
        )
    assert status == HTTPStatus.NOT_FOUND


def test_production_route_sources_contain_no_http_bootstrap_contract() -> None:
    repo_root = Path(__file__).resolve().parents[3]
    production_root = repo_root / "src" / "agentkit"
    matches = [
        source
        for source in production_root.rglob("*.py")
        if "/v1/auth/bootstrap" in source.read_text(encoding="utf-8")
    ]
    assert matches == []


def test_ac1a_backend_admin_issues_token_without_core_credential_file(
    tmp_path: Path,
    postgres_isolated_schema: str,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    del postgres_isolated_schema
    core_root = tmp_path / "core-machine"
    core_root.mkdir()
    auth_path = core_root / "auth.json"
    project_key = "role-separated"
    token_repository = StateBackendProjectApiTokenRepository(core_root)
    monkeypatch.chdir(core_root)
    monkeypatch.setattr(sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr(sys.stdout, "isatty", lambda: True)
    monkeypatch.setattr(sys.stderr, "isatty", lambda: True)

    assert not auth_path.exists()
    assert token_repository.list_for_project(project_key) == []
    assert not project_credentials_path(core_root).exists()

    with _live_https_serve(auth_path, tmp_path) as (base_url, tls_context, certfile):
        token = _bootstrap_and_issue_token_via_admin_cli(
            auth_path=auth_path,
            base_url=base_url,
            tls_context=tls_context,
            certfile=certfile,
            project_key=project_key,
            monkeypatch=monkeypatch,
            capsys=capsys,
        )

    stored = token_repository.list_for_project(project_key)
    assert auth_path.is_file()
    assert len(stored) == 1
    assert stored[0].token_hash
    assert token not in stored[0].model_dump_json()
    assert not project_credentials_path(core_root).exists()


def test_ac1b_client_operator_stores_and_uses_handoff_without_admin_secret(
    tmp_path: Path,
    postgres_isolated_schema: str,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    del postgres_isolated_schema
    core_root = tmp_path / "core-machine"
    laptop_root = tmp_path / "client-laptop"
    core_root.mkdir()
    laptop_root.mkdir()
    auth_path = core_root / "auth.json"
    project_key = "role-separated"
    token_repository = StateBackendProjectApiTokenRepository(core_root)
    monkeypatch.setattr(sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr(sys.stdout, "isatty", lambda: True)
    monkeypatch.setattr(sys.stderr, "isatty", lambda: True)

    assert not auth_path.exists()
    assert token_repository.list_for_project(project_key) == []
    assert not project_credentials_path(laptop_root).exists()

    with _live_https_serve(auth_path, tmp_path) as (base_url, tls_context, certfile):
        handed_off_token = _bootstrap_and_issue_token_via_admin_cli(
            auth_path=auth_path,
            base_url=base_url,
            tls_context=tls_context,
            certfile=certfile,
            project_key=project_key,
            monkeypatch=monkeypatch,
            capsys=capsys,
        )
        process_context = multiprocessing.get_context("spawn")
        results = process_context.Queue()
        laptop = process_context.Process(
            target=_store_handed_off_token_process,
            args=(
                str(laptop_root),
                base_url,
                str(certfile),
                project_key,
                handed_off_token,
                results,
            ),
        )
        laptop.start()
        outcome = results.get(timeout=30)
        laptop.join(timeout=30)
        assert laptop.exitcode == 0
        assert outcome == (0, None, False, ("Project API token: ",))
        credential = load_active_project_credentials(
            project_credentials_path(laptop_root),
            project_key=project_key,
        )
        assert credential.project_api_token == handed_off_token
        assert _bearer_get_status(
            f"{base_url}/v1/projects/{project_key}/stories",
            token=credential.project_api_token,
            project_key=project_key,
            context=tls_context,
        ) == HTTPStatus.OK

    assert not (laptop_root / "auth.json").exists()
    assert not (laptop_root / ".config" / "agentkit" / "auth.json").exists()


def test_repeated_real_two_process_bootstrap_race_has_exactly_one_winner(
    tmp_path: Path,
) -> None:
    auth_path = tmp_path / "auth.json"
    process_context = multiprocessing.get_context("spawn")

    for round_number in range(10):
        auth_path.unlink(missing_ok=True)
        start = process_context.Event()
        results = process_context.Queue()
        passwords = (
            f"race-secret-{round_number}-a",
            f"race-secret-{round_number}-b",
        )
        processes = [
            process_context.Process(
                target=_bootstrap_process,
                args=(
                    str(auth_path),
                    password,
                    f"op-race-{round_number}-{index}",
                    start,
                    results,
                ),
            )
            for index, password in enumerate(passwords)
        ]
        for process in processes:
            process.start()
        start.set()
        outcomes = [results.get(timeout=30) for _process in processes]
        for process in processes:
            process.join(timeout=30)
            assert process.exitcode == 0

        statuses = sorted(status for _password, status in outcomes)
        assert statuses == [HTTPStatus.CREATED, HTTPStatus.CONFLICT]
        winner = next(password for password, status in outcomes if status == HTTPStatus.CREATED)
        loser = next(password for password, status in outcomes if status == HTTPStatus.CONFLICT)
        store = StrategistCredentialStore(auth_path)
        from agentkit.backend.auth.entities import StrategistCredentials

        store.verify(StrategistCredentials(username="admin", password=winner))
        with pytest.raises(AuthFailedError):
            store.verify(StrategistCredentials(username="admin", password=loser))


def test_real_profile_processes_share_session_revocation(tmp_path: Path) -> None:
    auth_path = tmp_path / "auth.json"
    StrategistCredentialStore(auth_path).initialize_password("initial-password")
    process_context = multiprocessing.get_context("spawn")
    ready = process_context.Event()
    release = process_context.Event()
    results = process_context.Queue()
    creator = process_context.Process(
        target=_create_cross_profile_session,
        args=(str(auth_path), ready, release, results),
    )
    rotator = process_context.Process(
        target=_rotate_and_revoke_cross_profile_sessions,
        args=(str(auth_path), ready, results),
    )
    creator.start()
    rotator.start()
    outcomes: list[tuple[str, str]] = []
    try:
        while {kind for kind, _value in outcomes}.isdisjoint({"rotated"}) or not any(
            kind == "session_count" for kind, _value in outcomes
        ):
            outcomes.append(results.get(timeout=30))
        release.set()
        outcomes.append(results.get(timeout=30))
    finally:
        release.set()
        for process in (creator, rotator):
            process.join(timeout=30)
            if process.is_alive():
                process.kill()
                process.join(timeout=10)

    assert creator.exitcode == 0
    assert rotator.exitcode == 0
    assert {kind for kind, _value in outcomes} == {
        "created",
        "rotated",
        "session_count",
        "revoked",
    }
    assert next(value for kind, value in outcomes if kind == "session_count") == "0"
    created_id = next(value for kind, value in outcomes if kind == "created")
    revoked_id = next(value for kind, value in outcomes if kind == "revoked")
    assert revoked_id == created_id


def test_bootstrap_process_lock_is_released_after_sigkill(tmp_path: Path) -> None:
    auth_path = tmp_path / "auth.json"
    process_context = multiprocessing.get_context("spawn")
    locked = process_context.Event()
    holder = process_context.Process(
        target=_hold_bootstrap_lock,
        args=(str(auth_path), locked),
    )
    holder.start()
    assert locked.wait(timeout=20)
    holder.kill()
    holder.join(timeout=20)
    assert holder.exitcode is not None and holder.exitcode != 0

    StrategistCredentialStore(auth_path).initialize_password("known-after-kill")
    assert auth_path.is_file()


def test_concurrent_real_process_token_issue_has_one_registration(
    tmp_path: Path,
) -> None:
    process_context = multiprocessing.get_context("spawn")
    start = process_context.Event()
    release = process_context.Event()
    entered = process_context.Queue()
    results = process_context.Queue()
    processes = [
        process_context.Process(
            target=_issue_credential_process,
            args=(
                str(tmp_path),
                start,
                entered,
                release,
                results,
                f"issuer-{index}",
            ),
        )
        for index in range(2)
    ]
    for process in processes:
        process.start()
    start.set()
    first_registration = entered.get(timeout=20)
    assert isinstance(first_registration, dict)

    early_result: tuple[str, str, str] | None = None
    second_registration: dict[str, object] | None = None
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline and early_result is None and second_registration is None:
        try:
            candidate = entered.get_nowait()
            if isinstance(candidate, dict):
                second_registration = candidate
        except Empty:
            pass
        try:
            candidate_result = results.get_nowait()
            if isinstance(candidate_result, tuple):
                early_result = candidate_result
        except Empty:
            pass
        if early_result is None and second_registration is None:
            release.wait(timeout=0.05)

    release.set()
    remaining_results: list[tuple[str, str, str]] = []
    if early_result is not None:
        remaining_results.append(early_result)
    while len(remaining_results) < 2:
        remaining_results.append(results.get(timeout=20))
    for process in processes:
        process.join(timeout=20)
        assert process.exitcode == 0

    assert second_registration is None
    assert sorted(result[0] for result in remaining_results) == ["error", "ok"]
    error = next(result for result in remaining_results if result[0] == "error")
    assert "already in progress" in error[2]
    assert load_active_project_credentials(
        project_credentials_path(tmp_path),
        project_key="process-project",
    ).token_id == next(result[1] for result in remaining_results if result[0] == "ok")


def test_runtime_cannot_reconcile_inside_an_operator_publication(
    tmp_path: Path,
) -> None:
    process_context = multiprocessing.get_context("spawn")
    published = process_context.Event()
    release = process_context.Event()
    results = process_context.Queue()
    operator = process_context.Process(
        target=_publish_then_pause_credential_process,
        args=(str(tmp_path), published, release, results),
    )
    runtime = process_context.Process(
        target=_runtime_reconcile_process,
        args=(str(tmp_path), published, results),
    )
    operator.start()
    assert published.wait(timeout=20)
    runtime.start()
    runtime_result = results.get(timeout=20)
    release.set()
    operator_result = results.get(timeout=20)
    assert runtime_result[0] == "runtime_error"
    assert runtime_result[1] == "PrivateFileLockBusyError"
    assert operator_result[0] == "operator_ok"
    for process in (operator, runtime):
        process.join(timeout=20)
        assert process.exitcode == 0

    credential = load_reconciled_active_project_credentials(
        project_credentials_path(tmp_path),
        project_key="process-project",
    )
    assert credential.token_id == operator_result[1]


def test_role_separated_public_flow_uses_handed_off_token_for_default_cp10d(
    tmp_path: Path,
    postgres_isolated_schema: str,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    request: pytest.FixtureRequest,
) -> None:
    """Prove the public handoff flow feeds CP 10d with the operator's token.

    Needs a working ``gh``: the flow runs the real ``register-project``
    installer, whose CP 2 probes the live GitHub repo. That is deliberate --
    weakening CP 2 or injecting a fake probe through the CLI would create the
    very production bypass the checkpoint exists to prevent.

    This test was briefly marked ``requires_gh`` on 2026-08-04 because the
    Jenkins image carried no ``gh`` binary, which took the CP 10d credential
    path out of CI entirely. The tool was procured instead of the proof being
    weakened (CLAUDE.md "FEHLENDES BESCHAFFEN STATT UMGEHEN"): ``gh`` plus a
    token now live in the shared CI image (``seu-ci-infrastructure``,
    ``jenkins/Dockerfile``), so the marker is gone and the path is proven where
    it counts.
    """
    del postgres_isolated_schema
    monkeypatch.chdir(tmp_path)
    wire_ready_vectordb(monkeypatch, request)
    auth_path = tmp_path / "core" / "auth.json"
    token_repository = StateBackendProjectApiTokenRepository(tmp_path)
    project_root = tmp_path / "fresh-project"
    project_root.mkdir()
    subprocess.run(
        ["git", "init", "--initial-branch", "main", str(project_root)],
        check=True,
        capture_output=True,
        encoding="utf-8",
        text=True,
    )

    assert not auth_path.exists()
    assert not project_credentials_path(project_root).exists()
    assert token_repository.list_for_project("fresh-project") == []

    with _live_https_serve(auth_path, tmp_path) as (base_url, tls_context, certfile):
        base = HttpsJsonTransport(base_url=base_url, ssl_context=tls_context)
        monkeypatch.setattr(sys.stdin, "isatty", lambda: True)
        monkeypatch.setattr(sys.stdout, "isatty", lambda: True)
        monkeypatch.setattr(sys.stderr, "isatty", lambda: True)
        admin_password = "operator-known-secret"
        handed_off_token: str | None = None

        def _read_role_secret(prompt: str) -> str:
            if prompt == "Project API token: ":
                assert handed_off_token is not None
                return handed_off_token
            return admin_password

        monkeypatch.setattr("getpass.getpass", _read_role_secret)
        assert main(
            [
                "auth",
                "bootstrap",
                "--auth-config",
                str(auth_path),
            ],
        ) == 0
        session = authenticate_strategist(
            base,
            password=admin_password,
            project_key="fresh-project",
        )
        _create_project_over_admin_surface(session, project_key="fresh-project")
        capsys.readouterr()
        assert main(
            [
                "auth",
                "issue-token",
                "--base-url",
                base_url,
                "--ca-file",
                str(certfile),
                "--project-key",
                "fresh-project",
            ],
        ) == 0
        issue_output = capsys.readouterr()
        issued_payload = json.loads(issue_output.out.strip().splitlines()[-1])
        handed_off_token = cast("str", issued_payload["project_api_token"])
        assert issue_output.out.count(handed_off_token) == 1
        assert handed_off_token not in issue_output.err
        assert main(
            [
                "auth",
                "store-token",
                "--base-url",
                base_url,
                "--ca-file",
                str(certfile),
                "--project-key",
                "fresh-project",
                "--project-root",
                str(project_root),
            ],
        ) == 0
        assert main(
            [
                "register-project",
                "--project-key",
                "fresh-project",
                "--project-name",
                "Fresh Project",
                "--project-root",
                str(project_root),
                "--github-owner",
                "openai",
                "--github-repo",
                "openai-python",
                "--weaviate-http-endpoint",
                "http://127.0.0.1:9903",
                "--weaviate-grpc-endpoint",
                "127.0.0.1:50051",
                "--control-plane-base-url",
                base_url,
                "--control-plane-ca-file",
                str(certfile),
            ],
        ) == 0
        first = load_active_project_credentials(
            project_credentials_path(project_root),
            project_key="fresh-project",
        )
        cli_output = capsys.readouterr()
        assert first.project_api_token == handed_off_token
        assert first.project_api_token not in cli_output.out + cli_output.err
        prepared = prepare_project_api_token(
            project_key="fresh-project",
            label="replacement-edge",
        )
        write_pending_project_credentials(
            project_credentials_path(project_root),
            project_key="fresh-project",
            prepared_token=prepared,
            issuance_op_id="op-token-replacement",
            superseded_token_id=first.token_id,
        )
        committed_before_response_loss = session.send(
            method="POST",
            path="/v1/projects/fresh-project/api-tokens",
            payload={
                "label": "replacement-edge",
                "op_id": "op-token-replacement",
                "token_id": prepared.record.token_id,
                "token_hash": prepared.record.token_hash,
            },
        )
        assert committed_before_response_loss.get("status") == "committed"

        recovered_session = authenticate_strategist(
            base,
            password="operator-known-secret",
            project_key="fresh-project",
        )
        replacement = provision_project_credentials(
            recovered_session,
            project_root=project_root,
            project_key="fresh-project",
            label="replacement-edge",
            op_id="op-token-retry-is-ignored-for-pending-state",
            replace_active=True,
        )
        second = load_active_project_credentials(
            project_credentials_path(project_root),
            project_key="fresh-project",
        )
        protected_url = f"{base_url}/v1/projects/fresh-project/stories"
        assert replacement.superseded_token_id == first.token_id
        assert _bearer_get_status(
            protected_url,
            token=first.project_api_token,
            project_key="fresh-project",
            context=tls_context,
        ) == HTTPStatus.OK
        assert _bearer_get_status(
            protected_url,
            token=second.project_api_token,
            project_key="fresh-project",
            context=tls_context,
        ) == HTTPStatus.OK
        revoke_project_token(
            recovered_session,
            project_key="fresh-project",
            token_id=first.token_id,
            op_id="op-token-revoke-superseded",
            credential_path=project_credentials_path(project_root),
        )
        assert _bearer_get_status(
            protected_url,
            token=first.project_api_token,
            project_key="fresh-project",
            context=tls_context,
        ) == HTTPStatus.UNAUTHORIZED
        assert _bearer_get_status(
            protected_url,
            token=second.project_api_token,
            project_key="fresh-project",
            context=tls_context,
        ) == HTTPStatus.OK
        rotation_payload = {
            "new_password": "operator-known-replacement",
            "op_id": "op-password-response-loss",
        }
        rotation = recovered_session.send(
            method="POST",
            path="/v1/auth/password",
            payload=rotation_payload,
        )
        replay_session = authenticate_strategist(
            base,
            password="operator-known-replacement",
            project_key="fresh-project",
        )
        replay = replay_session.send(
            method="POST",
            path="/v1/auth/password",
            payload=rotation_payload,
        )
        assert rotation["status"] == "rotated"
        assert replay == rotation

    credential = load_active_project_credentials(
        project_credentials_path(project_root),
        project_key="fresh-project",
    )
    stored = token_repository.get(credential.token_id)
    assert replacement.status == "active"
    assert stored is not None
    assert stored.token_hash
    assert credential.project_api_token not in stored.model_dump_json()
    assert credential.superseded_token_id is None
