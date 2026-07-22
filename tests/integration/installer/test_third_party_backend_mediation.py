"""Real register-to-control-plane mediation for AG3-132."""

from __future__ import annotations

import argparse
import json
import threading
import urllib.request
from http import HTTPStatus
from http.server import HTTPServer
from importlib.metadata import version
from typing import TYPE_CHECKING, cast

import pytest
import yaml
from tests.fixtures.git_repo import ensure_git_repo
from tests.fixtures.third_party_preflight import FakeThirdPartyClientFactory

from agentkit.backend.auth.middleware import AuthMiddleware
from agentkit.backend.auth.tokens import issue_project_api_token
from agentkit.backend.control_plane.third_party_models import BranchPluginSelfTestRequest
from agentkit.backend.control_plane_http.app import ControlPlaneApplication, _build_handler
from agentkit.backend.control_plane_http.routes_config import ControlPlaneApplicationRoutes
from agentkit.backend.control_plane_http.third_party_validation_routes import (
    ThirdPartyValidationRoutes,
)
from agentkit.backend.control_plane_http.version_handshake import VersionHandshakeMiddleware
from agentkit.backend.exceptions import InstallationError
from agentkit.backend.installer.bootstrap_checkpoints.orchestrator import (
    run_checkpoint_install,
)
from agentkit.backend.installer.bounded_executor import BoundedThreadExecutor
from agentkit.backend.installer.checkpoint_engine.execution_mode import ExecutionMode
from agentkit.backend.installer.checkpoint_engine.node_ids import (
    CP_10D_SONARQUBE,
    CP_11_GIT_HOOKS_AND_CLAUDE,
    CP_12_VERIFY_REGISTRATION,
)
from agentkit.backend.installer.registration import CheckpointStatus
from agentkit.backend.installer.runner import (
    MANDATORY_SKILLS,
    InstallConfig,
    _third_party_validation_request,
    install_agentkit,
)
from agentkit.backend.installer.third_party_clients import (
    EnvironmentSecretResolver,
    ThirdPartyClientFactory,
)
from agentkit.backend.installer.third_party_preflight import ThirdPartyPreflightService
from agentkit.backend.skills import Skills
from agentkit.backend.skills.bundle_store import SkillBundle, SkillBundleStore
from agentkit.backend.state_backend.operation_ledger import (
    load_control_plane_operation_global,
)
from agentkit.backend.state_backend.store.inflight_idempotency_guard import (
    StateBackendInflightIdempotencyGuard,
)
from agentkit.backend.state_backend.store.skill_binding_repository import (
    StateBackendSkillBindingRepository,
)
from agentkit.harness_client.projectedge.client import (
    HttpsJsonTransport,
    LocalEdgePublisher,
    ProjectEdgeClient,
)

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

    from agentkit.backend.auth.entities import ProjectApiToken


class _TokenRepository:
    """In-memory auth storage; authentication itself runs for real."""

    def __init__(self) -> None:
        self.rows: dict[str, ProjectApiToken] = {}

    def get(self, token_id: str) -> ProjectApiToken | None:
        return self.rows.get(token_id)

    def get_by_hash(self, token_hash: str) -> ProjectApiToken | None:
        return next(
            (row for row in self.rows.values() if row.token_hash == token_hash), None
        )

    def list_for_project(self, project_key: str) -> list[ProjectApiToken]:
        return [row for row in self.rows.values() if row.project_key == project_key]

    def save(self, token: ProjectApiToken) -> None:
        self.rows[token.token_id] = token

    def revoke(self, project_key: str, token_id: str) -> None:
        del project_key
        self.rows.pop(token_id, None)


def _bundle_store(root: Path) -> SkillBundleStore:
    store = SkillBundleStore(store_root=root / "skill-bundles")
    for name in MANDATORY_SKILLS:
        bundle_root = root / "skill-bundles" / f"{name}-core" / "4.0.0"
        bundle_root.mkdir(parents=True, exist_ok=True)
        (bundle_root / "SKILL.md").write_text(f"# {name}\n", encoding="utf-8")
        store.register_bundle(
            SkillBundle(
                bundle_id=f"{name}-core",
                bundle_version="4.0.0",
                bundle_root=bundle_root,
                manifest_digest="0" * 64,
            )
        )
    return store


def _default_profile(root: Path) -> None:
    profile = root / "bundles" / "target_project" / "sonar" / "ak3-default-gate.json"
    profile.parent.mkdir(parents=True, exist_ok=True)
    profile.write_text("{}", encoding="utf-8")


@pytest.fixture()
def mediated_control_plane(
    postgres_isolated_schema: str,
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[tuple[str, str, FakeThirdPartyClientFactory]]:
    """Serve the real route/service/ledger with only third systems faked."""
    del postgres_isolated_schema
    monkeypatch.setenv("SONAR_BACKEND_TOKEN", "backend-sonar-token")
    monkeypatch.setenv("JENKINS_BACKEND_TOKEN", "backend-jenkins-token")
    tokens = _TokenRepository()
    issued = issue_project_api_token(
        project_key="tenant-a", label="ag3-132", repository=tokens
    )
    guard = StateBackendInflightIdempotencyGuard()
    clients = FakeThirdPartyClientFactory()
    executor = BoundedThreadExecutor(max_workers=1, max_queued=1)
    service = ThirdPartyPreflightService(
        resolver=EnvironmentSecretResolver(),
        clients=cast("ThirdPartyClientFactory", clients),
        guard=guard,
        operation_loader=load_control_plane_operation_global,
        executor=executor,
    )
    routes = ControlPlaneApplicationRoutes(
        third_party_validation_routes=ThirdPartyValidationRoutes(service)
    )
    app = ControlPlaneApplication(
        routes=routes,
        auth_middleware=AuthMiddleware(token_repository=tokens),
        version_handshake_middleware=VersionHandshakeMiddleware(),
    )
    server = HTTPServer(("127.0.0.1", 0), _build_handler(app))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    host, port = server.server_address
    try:
        yield f"http://{host}:{port}", issued.plaintext_token, clients
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def _project_edge(root: Path, base_url: str, token: str) -> ProjectEdgeClient:
    return ProjectEdgeClient(
        transport=HttpsJsonTransport(
            base_url=base_url,
            skill_bundle_version="4.0.0",
            bearer_token=token,
            project_key="tenant-a",
        ),
        publisher=LocalEdgePublisher(project_root=root),
    )


def _install_config(
    root: Path, store: SkillBundleStore, client: ProjectEdgeClient, base_url: str
) -> InstallConfig:
    skills = Skills(
        bundle_store=store,
        binding_repo=StateBackendSkillBindingRepository(root),
    )
    return InstallConfig(
        weaviate_host="weaviate.test.local",
        weaviate_http_port=19903,
        weaviate_grpc_port=50051,
        project_key="tenant-a",
        project_name="Tenant A",
        project_root=root,
        github_owner="openai",
        github_repo="tenant-a",
        skills=skills,
        skill_bundle_store=store,
        skill_bundle_ids={name: f"{name}-core" for name in MANDATORY_SKILLS},
        project_edge_client=client,
        control_plane_base_url=base_url,
        sonarqube_token_env="SONAR_BACKEND_TOKEN",
        ci_token_env="JENKINS_BACKEND_TOKEN",
    )


@pytest.mark.integration
def test_register_project_reaches_real_route_and_backend_preflight(
    tmp_path: Path,
    mediated_control_plane: tuple[str, str, FakeThirdPartyClientFactory],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The engine constructs third-system clients only behind the backend route."""

    def _forbidden(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("the installer engine constructed a dev-side client")

    monkeypatch.setattr(
        "agentkit.integration_clients.sonar.SonarClient.__init__", _forbidden
    )
    monkeypatch.setattr(
        "agentkit.integration_clients.jenkins.JenkinsClient.__init__", _forbidden
    )
    base_url, token, clients = mediated_control_plane
    root = tmp_path / "tenant-a"
    root.mkdir()
    ensure_git_repo(root)
    _default_profile(root)
    store = _bundle_store(tmp_path)
    config = _install_config(root, store, _project_edge(root, base_url, token), base_url)

    result = install_agentkit(config)

    assert result.success is True
    cp10d = next(
        item
        for item in result.checkpoint_results or ()
        if item.checkpoint == CP_10D_SONARQUBE
    )
    assert cp10d.status is CheckpointStatus.PASS
    assert clients.sonar_constructions == 1
    assert clients.jenkins_constructions == 1
    assert clients.jenkins_client.triggered == []
    yaml_data = yaml.safe_load(
        (root / ".agentkit" / "config" / "project.yaml").read_text(encoding="utf-8")
    )
    request = _third_party_validation_request(config, yaml_data)
    record = load_control_plane_operation_global(request.op_id)
    assert record is None, "read-only validation must release its in-flight claim"


@pytest.mark.integration
def test_verify_reprobes_when_external_state_flips_from_pass_to_unreachable(
    tmp_path: Path,
    mediated_control_plane: tuple[str, str, FakeThirdPartyClientFactory],
) -> None:
    """A later verify observes live Sonar state instead of replaying register PASS."""
    base_url, token, clients = mediated_control_plane
    root = tmp_path / "tenant-a"
    root.mkdir()
    ensure_git_repo(root)
    _default_profile(root)
    store = _bundle_store(tmp_path)
    config = _install_config(root, store, _project_edge(root, base_url, token), base_url)
    assert install_agentkit(config).success

    clients.sonar_client.reachable = False
    verified = run_checkpoint_install(config, mode=ExecutionMode.VERIFY)

    cp10d = next(
        item
        for item in verified.checkpoint_results or ()
        if item.checkpoint == CP_10D_SONARQUBE
    )
    assert verified.success is False
    assert cp10d.status is CheckpointStatus.FAILED
    assert "sonar_unreachable" in (cp10d.detail or "")
    assert clients.sonar_constructions == 2


@pytest.mark.integration
def test_register_retry_reprobes_after_failed_external_state_is_fixed(
    tmp_path: Path,
    mediated_control_plane: tuple[str, str, FakeThirdPartyClientFactory],
) -> None:
    """A failed register verdict cannot permanently brick identical config."""
    base_url, token, clients = mediated_control_plane
    clients.sonar_client.reachable = False
    root = tmp_path / "tenant-a"
    root.mkdir()
    ensure_git_repo(root)
    _default_profile(root)
    store = _bundle_store(tmp_path)
    config = _install_config(root, store, _project_edge(root, base_url, token), base_url)

    with pytest.raises(InstallationError, match="sonar_unreachable"):
        install_agentkit(config)
    clients.sonar_client.reachable = True

    retried = install_agentkit(config)

    assert retried.success is True
    assert clients.sonar_constructions == 2


@pytest.mark.integration
def test_verify_collects_failed_third_party_verdict_and_later_checkpoints(
    tmp_path: Path,
    mediated_control_plane: tuple[str, str, FakeThirdPartyClientFactory],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Verify reports later checkpoints and exits nonzero after failed CP10d."""
    from agentkit.backend.cli.installer_commands import _cmd_verify_project

    base_url, token, clients = mediated_control_plane
    root = tmp_path / "tenant-a"
    root.mkdir()
    ensure_git_repo(root)
    _default_profile(root)
    store = _bundle_store(tmp_path)
    config = _install_config(root, store, _project_edge(root, base_url, token), base_url)
    assert install_agentkit(config).success
    clients.sonar_client.reachable = False
    monkeypatch.setattr(
        "agentkit.backend.cli.installer_commands._build_engine_config",
        lambda _args: config,
    )

    exit_code = _cmd_verify_project(argparse.Namespace(project_root=str(root)))

    output = capsys.readouterr().out
    assert exit_code != 0
    assert f"{CP_10D_SONARQUBE}: failed" in output
    assert CP_11_GIT_HOOKS_AND_CLAUDE in output
    assert CP_12_VERIFY_REGISTRATION in output
    assert clients.sonar_constructions == 2


@pytest.mark.integration
def test_system_unreachable_verdict_passes_through_real_route_fail_closed(
    tmp_path: Path,
    mediated_control_plane: tuple[str, str, FakeThirdPartyClientFactory],
) -> None:
    """A real register aborts on the backend's structured Sonar failure."""
    base_url, token, clients = mediated_control_plane
    clients.sonar_client.reachable = False
    root = tmp_path / "tenant-a"
    root.mkdir()
    ensure_git_repo(root)
    _default_profile(root)
    store = _bundle_store(tmp_path)
    config = _install_config(root, store, _project_edge(root, base_url, token), base_url)

    with pytest.raises(InstallationError, match="sonar_unreachable"):
        install_agentkit(config)
    yaml_data = yaml.safe_load(
        (root / ".agentkit" / "config" / "project.yaml").read_text(encoding="utf-8")
    )
    request = _third_party_validation_request(config, yaml_data)
    record = load_control_plane_operation_global(request.op_id)
    assert record is None, "failed read-only validation must also release its claim"


def _self_test_request() -> BranchPluginSelfTestRequest:
    return BranchPluginSelfTestRequest.model_validate(
        {
            "op_id": "branch-self-test-1",
            "sonar": {
                "available": True,
                "enabled": True,
                "base_url": "https://sonar.example",
                "token_env": "SONAR_BACKEND_TOKEN",
                "scanner_version": "5.0.1",
            },
            "ci": {
                "available": True,
                "enabled": True,
                "base_url": "https://jenkins.example",
                "token_env": "JENKINS_BACKEND_TOKEN",
                "pipeline": "pre-merge",
            },
        }
    )


def _raw_start(
    base_url: str, token: str, request: BranchPluginSelfTestRequest
) -> tuple[int, dict[str, object]]:
    body = json.dumps(request.model_dump(mode="json")).encode()
    http_request = urllib.request.Request(
        f"{base_url}/v1/projects/tenant-a/installation/branch-plugin-self-test",
        data=body,
        method="POST",
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "X-AK3-Client": version("agentkit"),
            "X-AK3-Skill-Bundle": "4.0.0",
            "X-AK3-Project": "tenant-a",
            "X-Correlation-Id": "ag3-132-self-test",
        },
    )
    with urllib.request.urlopen(http_request) as response:
        return int(response.status), json.loads(response.read())


@pytest.mark.integration
def test_heavy_self_test_is_202_pollable_idempotent_and_persisted(
    tmp_path: Path,
    mediated_control_plane: tuple[str, str, FakeThirdPartyClientFactory],
) -> None:
    """The explicit operation runs real conformance logic and FK-91 lifecycle."""
    base_url, token, clients = mediated_control_plane
    root = tmp_path / "tenant-a"
    root.mkdir()
    ensure_git_repo(root)
    _default_profile(root)
    store = _bundle_store(tmp_path)
    edge = _project_edge(root, base_url, token)
    assert install_agentkit(_install_config(root, store, edge, base_url)).success
    request = _self_test_request()

    status, accepted = _raw_start(base_url, token, request)
    terminal = edge.poll_branch_plugin_self_test(
        request.op_id, timeout_seconds=5, poll_interval_seconds=0.01
    )
    replay = edge.start_branch_plugin_self_test(
        project_key="tenant-a", request=request
    )

    assert status == HTTPStatus.ACCEPTED
    assert accepted["op_id"] == request.op_id
    assert accepted["status"] == "accepted"
    assert terminal.status == "succeeded"
    assert replay == terminal
    assert len(clients.jenkins_client.triggered) == 2
    record = load_control_plane_operation_global(request.op_id)
    assert record is not None
    assert record.operation_kind == "branch_plugin_conformance_self_test"
    assert record.status == "committed"
    assert record.request_body_hash is not None
    assert record.response_payload["status"] == "succeeded"
