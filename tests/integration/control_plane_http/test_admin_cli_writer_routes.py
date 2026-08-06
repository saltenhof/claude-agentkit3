"""Productive CLI-to-writer proofs for AG3-214 administrative mutations."""

from __future__ import annotations

import json
import socket
import ssl
import subprocess
from contextlib import contextmanager
from datetime import UTC, datetime
from http import HTTPStatus
from http.server import ThreadingHTTPServer
from threading import Event, Thread
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any, Never, cast

import psycopg
import pytest
from pydantic import ValidationError

from agentkit.backend.auth.credentials import StrategistCredentialStore
from agentkit.backend.auth.http.routes import AuthRoutes
from agentkit.backend.auth.middleware import AuthMiddleware, AuthResult
from agentkit.backend.cli.main import main
from agentkit.backend.control_plane.records import ControlPlaneOperationRecord
from agentkit.backend.control_plane.repository import ControlPlaneRuntimeRepository
from agentkit.backend.control_plane.runtime import ControlPlaneRuntimeService
from agentkit.backend.control_plane.third_party_models import (
    BranchPluginSelfTestOperation,
    BranchPluginSelfTestRequest,
)
from agentkit.backend.control_plane.writer_lease import ControlPlaneWriterLeaseLostError
from agentkit.backend.control_plane_http.app import (
    ControlPlaneApplication,
    ControlPlaneSurface,
    _build_handler,
    serve_control_plane,
)
from agentkit.backend.control_plane_http.default_routes import (
    _build_default_installer_writer_routes,
)
from agentkit.backend.control_plane_http.failure_corpus_routes import FailureCorpusRoutes
from agentkit.backend.control_plane_http.installer_writer_routes import (
    InstallerWriterRoutes,
)
from agentkit.backend.control_plane_http.routes_config import ControlPlaneApplicationRoutes
from agentkit.backend.control_plane_http.story_admin_routes import StoryAdminRoutes
from agentkit.backend.control_plane_http.story_split_routes import StorySplitRoutes
from agentkit.backend.control_plane_http.third_party_validation_routes import (
    ThirdPartyValidationRoutes,
)
from agentkit.backend.core_types import CheckStatus, CheckType, PatternStatus
from agentkit.backend.exceptions import ControlPlaneApiError
from agentkit.backend.failure_corpus.check_factory import CheckFactory
from agentkit.backend.failure_corpus.check_proposal import (
    CheckProposalRecord,
    FalsePositiveRisk,
)
from agentkit.backend.failure_corpus.effectiveness import CheckEffectivenessTracker
from agentkit.backend.failure_corpus.mutation_idempotency import (
    FailureCorpusMutationCoordinator,
)
from agentkit.backend.failure_corpus.pattern import (
    FailureCategory,
    FailurePatternRecord,
    PatternRiskLevel,
    PromotionRule,
)
from agentkit.backend.failure_corpus.story_creation_adapter import (
    AK3StoryCreationAdapter,
)
from agentkit.backend.failure_corpus.types import CheckId, IncidentId
from agentkit.backend.governance.hook_registration import (
    HookDefinition,
    HookEventName,
    RegistrationResult,
)
from agentkit.backend.installer.bounded_executor import BoundedThreadExecutor
from agentkit.backend.installer.mutation_idempotency import (
    InstallerMutationCoordinator,
)
from agentkit.backend.installer.registration import (
    ProjectRegistration,
    RuntimeProfile,
)
from agentkit.backend.installer.third_party_preflight import ThirdPartyPreflightService
from agentkit.backend.installer.writer_client import InstallerWriterClient
from agentkit.backend.installer.writer_service import InstallerWriterService
from agentkit.backend.project_management.entities import Project, ProjectConfiguration
from agentkit.backend.skills.binding import (
    SkillBinding,
    SkillBindingMode,
    SkillLifecycleStatus,
)
from agentkit.backend.state_backend.config import load_state_backend_config
from agentkit.backend.state_backend.operation_ledger import (
    claim_control_plane_operation_global,
    load_control_plane_operation_global,
)
from agentkit.backend.state_backend.store.control_plane_writer_lease import (
    load_bound_control_plane_writer_identity,
)
from agentkit.backend.state_backend.store.fc_check_proposal_repository import (
    StateBackendFcCheckProposalRepository,
)
from agentkit.backend.state_backend.store.fc_pattern_repository import (
    StateBackendFcPatternRepository,
)
from agentkit.backend.state_backend.store.governance_hook_repository import (
    StateBackendHookRegistrationRepository,
)
from agentkit.backend.state_backend.store.inflight_idempotency_guard import (
    FreshClaim,
    IdempotencyRequest,
    InMemoryInflightIdempotencyGuard,
    StateBackendInflightIdempotencyGuard,
    compute_body_hash,
)
from agentkit.backend.state_backend.store.project_management_repository import (
    StateBackendProjectRepository,
)
from agentkit.backend.state_backend.store.project_registration_repository import (
    StateBackendProjectRegistrationRepository,
)
from agentkit.backend.state_backend.store.skill_binding_repository import (
    StateBackendSkillBindingRepository,
)
from agentkit.backend.story_context_manager.terminal_state import ExitClass, TerminalState
from agentkit.backend.story_split.models import SplitStatus, StorySplitRecord
from agentkit.backend.story_split.rebinding import RebindingPlan
from agentkit.backend.story_split.service import StorySplitRequest, StorySplitResult
from agentkit.harness_client.projectedge.client import HttpsJsonTransport
from agentkit.harness_client.projectedge.credentials import (
    activate_project_credentials,
    prepare_project_api_token,
    project_credentials_path,
    write_pending_project_credentials,
)

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator
    from concurrent.futures import Future
    from pathlib import Path

    from agentkit.backend.auth.entities import ProjectApiToken
    from agentkit.backend.installer.repository import ProjectRegistrationRepository
    from agentkit.backend.installer.upgrade.hook_migration import HookRegistrationSurface
    from agentkit.backend.skills import Skills
pytestmark = pytest.mark.integration

_PROJECT = "tenant-a"


@pytest.fixture(autouse=True)
def _isolated_postgres(postgres_isolated_schema: object) -> None:
    del postgres_isolated_schema


class _SuccessfulSplitService:
    """Real result shape at the route's domain-service boundary."""

    def __init__(self) -> None:
        self.requests: list[StorySplitRequest] = []

    def split_story(self, request: StorySplitRequest) -> StorySplitResult:
        self.requests.append(request)
        successor_ids = tuple(item.story_id for item in request.plan.successors)
        record = StorySplitRecord(
            split_id="split-live-writer",
            project_key=request.project_key,
            source_story_id=request.source_story_id,
            requested_by=request.requested_by,
            reason=request.reason,
            plan_ref="plan-ref-live-writer",
            status=SplitStatus.COMMITTED,
            successor_ids=successor_ids,
            superseded_by=successor_ids,
            terminal_state=TerminalState.CANCELLED,
            exit_class=ExitClass.SCOPE_SPLIT,
            created_at=datetime.now(UTC),
        )
        return StorySplitResult(
            split_id=record.split_id,
            record=record,
            successor_ids=successor_ids,
            rebinding_plan=RebindingPlan(removals=(), additions=()),
            resumed=False,
        )


class _SuccessfulFailureCorpus:
    """Record calls made after the authenticated request entered the writer."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, object]] = []

    def record_incident(self, candidate: object) -> IncidentId:
        self.calls.append(("add-incident", candidate))
        return IncidentId("FC-2026-0001")

    def confirm_pattern(
        self,
        pattern_id: object,
        decision: object,
        **_kwargs: object,
    ) -> object:
        self.calls.append(("review-patterns", decision))
        return SimpleNamespace(pattern_id=pattern_id)

    def approve_check(
        self,
        check_id: object,
        decision: object,
        **_kwargs: object,
    ) -> object:
        self.calls.append(("review-checks", decision))
        return SimpleNamespace(check_id=check_id)

    def report_effectiveness(self, window_days: int = 90) -> object:
        self.calls.append(("effectiveness-report", window_days))
        return SimpleNamespace(
            window_days=window_days,
            updated_count=3,
            deactivated_count=1,
        )


class _CompletionTrackingExecutor:
    """Expose completion of real executor work after its finalization attempt."""

    def __init__(self) -> None:
        self._delegate = BoundedThreadExecutor(max_workers=1, max_queued=1)
        self.completed = Event()

    def submit(self, fn: object) -> Future[None]:
        future = self._delegate.submit(cast("Any", fn))
        future.add_done_callback(lambda _future: self.completed.set())
        return future

    def shutdown(self, *, wait: bool, cancel_futures: bool) -> None:
        self._delegate.shutdown(wait=wait, cancel_futures=cancel_futures)


def _application(
    tmp_path: Path,
    *,
    story_split_routes: StorySplitRoutes | None = None,
    third_party_routes: ThirdPartyValidationRoutes | None = None,
    story_admin_routes: StoryAdminRoutes | None = None,
    failure_corpus_routes: FailureCorpusRoutes | None = None,
    installer_writer_routes: InstallerWriterRoutes | None = None,
    project_token: ProjectApiToken | None = None,
) -> ControlPlaneApplication:
    credentials = StrategistCredentialStore(tmp_path / "strategist.json")
    credentials.initialize_password("secret")
    auth = AuthMiddleware()
    if project_token is not None:
        auth.token_repository.insert(project_token)
    routes = ControlPlaneApplicationRoutes(
        auth_routes=AuthRoutes(
            credential_store=credentials,
            session_store=auth.session_store,
            token_repository=auth.token_repository,
        ),
        story_split_routes=story_split_routes,
        third_party_validation_routes=third_party_routes,
        story_admin_routes=story_admin_routes,
        failure_corpus_routes=failure_corpus_routes,
        installer_writer_routes=installer_writer_routes,
    )
    return ControlPlaneApplication(
        routes=routes,
        runtime_service=ControlPlaneRuntimeService(),
        auth_middleware=auth,
        auth_middlewares={ControlPlaneSurface.PROJECT_API: auth},
        writer_lease_required=True,
    )


@contextmanager
def _live_https_writer(
    app: ControlPlaneApplication,
    directory: Path,
) -> Iterator[tuple[str, Path]]:
    certfile = directory / "control-plane-cert.pem"
    keyfile = directory / "control-plane-key.pem"
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
    server = ThreadingHTTPServer(
        ("127.0.0.1", 0),
        _build_handler(app, ControlPlaneSurface.PROJECT_API),
    )
    server_context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    server_context.load_cert_chain(certfile=certfile, keyfile=keyfile)
    server.socket = server_context.wrap_socket(server.socket, server_side=True)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        host, port = server.server_address
        yield f"https://{host}:{port}", certfile
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def _activate_project_token(project_root: Path) -> object:
    prepared = prepare_project_api_token(project_key=_PROJECT, label="installer")
    credential_path = project_credentials_path(project_root)
    write_pending_project_credentials(
        credential_path,
        project_key=_PROJECT,
        prepared_token=prepared,
        issuance_op_id="op-installer-credential",
    )
    activate_project_credentials(credential_path)
    return prepared


def test_cp7_second_write_failure_same_op_retry_converges_through_real_writer(
    tmp_path: Path,
) -> None:
    """CP7 rolls back its first write when visible-project persistence fails."""

    op_id = "op-register-project-live-writer"
    payload = {
        "op_id": op_id,
        "project_name": "Tenant A",
        "project_root": str(tmp_path),
        "github_owner": "openai",
        "github_repo": "agentkit",
        "runtime_profile": "core",
        "project_yaml": {
            "project_key": _PROJECT,
            "project_name": "Tenant A",
            "repositories": [{"name": "main", "path": "."}],
        },
    }
    auth = AuthResult(
        auth_kind="project_api_token",
        project_key=_PROJECT,
        token_id="token-cp7-atomic",
    )
    project_repository = _FailOnceProjectRepository()
    installer_routes = InstallerWriterRoutes(
        owner=InstallerWriterService(
            registration_repository=StateBackendProjectRegistrationRepository,
            project_repository=lambda: project_repository,
            skill_binding_repository=StateBackendSkillBindingRepository,
            hook_repository=StateBackendHookRegistrationRepository,
        ),
        mutation_coordinator=InstallerMutationCoordinator(
            StateBackendInflightIdempotencyGuard(),
        ),
    )
    app = _application(tmp_path)
    app.run_pre_serve_startup_hook()
    try:
        first = installer_routes.handle_post(
            f"/v1/projects/{_PROJECT}/installation/register-project",
            payload,
            "corr-cp7-first",
            auth,
        )
        assert first is not None and first.status_code == HTTPStatus.SERVICE_UNAVAILABLE
        assert StateBackendProjectRegistrationRepository().get(_PROJECT) is None
        assert StateBackendProjectRepository().get(_PROJECT) is None
        assert load_control_plane_operation_global(op_id) is None

        retry = installer_routes.handle_post(
            f"/v1/projects/{_PROJECT}/installation/register-project",
            payload,
            "corr-cp7-retry",
            auth,
        )
        assert retry is not None and retry.status_code == HTTPStatus.OK
    finally:
        app.release_writer_lease()

    registration = StateBackendProjectRegistrationRepository().get(_PROJECT)
    assert registration is not None
    assert registration.github_owner == "openai"
    assert StateBackendProjectRepository().get(_PROJECT) is not None
    committed = load_control_plane_operation_global(op_id)
    assert committed is not None and committed.status == "committed"


class _FailOnceProjectRepository:
    """Enter CP7's registry-written/project-not-written window exactly once."""

    def __init__(self) -> None:
        self._delegate = StateBackendProjectRepository()
        self._failed = False

    def get(self, key: str) -> Project | None:
        return self._delegate.get(key)

    def list(self, *, include_archived: bool = False) -> list[Project]:
        return self._delegate.list(include_archived=include_archived)

    def save(self, project: Project) -> None:
        if not self._failed:
            self._failed = True
            raise RuntimeError("injected CP7 visible-project write failure")
        self._delegate.save(project)


def test_writer_session_loss_after_cp7_domain_window_same_op_converges(
    tmp_path: Path,
) -> None:
    """Kill the reserved session after both CP7 writes but before claim finalize."""

    op_id = "op-cp7-session-loss-window"
    payload = {
        "op_id": op_id,
        "project_name": "Tenant A",
        "project_root": str(tmp_path),
        "github_owner": "openai",
        "github_repo": "agentkit",
        "runtime_profile": "core",
        "project_yaml": {
            "project_key": _PROJECT,
            "project_name": "Tenant A",
            "repositories": [{"name": "main", "path": "."}],
        },
    }
    auth = AuthResult(
        auth_kind="project_api_token",
        project_key=_PROJECT,
        token_id="token-session-loss",
    )
    first_app = _application(tmp_path)
    first_app.run_pre_serve_startup_hook()
    killing_repository = _KillSessionAfterProjectSave(first_app)
    first_routes = InstallerWriterRoutes(
        owner=InstallerWriterService(
            registration_repository=StateBackendProjectRegistrationRepository,
            project_repository=lambda: killing_repository,
            skill_binding_repository=StateBackendSkillBindingRepository,
            hook_repository=StateBackendHookRegistrationRepository,
        ),
        mutation_coordinator=InstallerMutationCoordinator(
            StateBackendInflightIdempotencyGuard(),
        ),
    )

    try:
        response = first_routes.handle_post(
            f"/v1/projects/{_PROJECT}/installation/register-project",
            payload,
            "corr-session-loss",
            auth,
        )
        assert response is not None
        assert response.status_code == HTTPStatus.SERVICE_UNAVAILABLE
    finally:
        first_app.release_writer_lease()

    claimed = load_control_plane_operation_global(op_id)
    assert claimed is not None and claimed.status == "claimed"
    assert claimed.story_id is None
    assert StateBackendProjectRegistrationRepository().get(_PROJECT) is None
    assert StateBackendProjectRepository().get(_PROJECT) is None

    second_app = _application(tmp_path / "second-writer")
    second_app.run_pre_serve_startup_hook()
    try:
        assert load_control_plane_operation_global(op_id) is None
        response = _build_default_installer_writer_routes().handle_post(
            f"/v1/projects/{_PROJECT}/installation/register-project",
            payload,
            "corr-session-retry",
            auth,
        )
        assert response is not None and response.status_code == HTTPStatus.OK
    finally:
        second_app.release_writer_lease()

    assert StateBackendProjectRegistrationRepository().get(_PROJECT) is not None
    assert StateBackendProjectRepository().get(_PROJECT) is not None
    committed = load_control_plane_operation_global(op_id)
    assert committed is not None and committed.status == "committed"


class _KillSessionAfterProjectSave:
    """Terminate the exact writer session in the former save/finalize gap."""

    def __init__(self, app: ControlPlaneApplication) -> None:
        self._app = app
        self._delegate = StateBackendProjectRepository()

    def get(self, key: str) -> Project | None:
        return self._delegate.get(key)

    def list(self, *, include_archived: bool = False) -> list[Project]:
        return self._delegate.list(include_archived=include_archived)

    def save(self, project: Project) -> None:
        self._delegate.save(project)
        lease = vars(self._app)["_writer_lease"]
        assert lease is not None
        row = lease.delegate.connection.execute(
            "SELECT pg_backend_pid() AS pid",
        ).fetchone()
        assert row is not None
        database_url = load_state_backend_config().database_url
        assert database_url is not None
        with psycopg.connect(database_url) as killer:
            terminated = killer.execute(
                "SELECT pg_terminate_backend(%s)",
                (int(row["pid"]),),
            ).fetchone()
        assert terminated is not None and terminated[0] is True


def test_upgrade_project_public_cli_migrates_hooks_through_real_writer(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Z2: UP04 hook persistence crosses the authenticated leased route."""

    prepared = _activate_project_token(tmp_path)
    _save_project()
    StateBackendProjectRegistrationRepository().save(
        ProjectRegistration(
            project_key=_PROJECT,
            project_root=tmp_path,
            github_owner="openai",
            github_repo="agentkit",
            runtime_profile=RuntimeProfile.CORE,
            config_version="3.0",
            config_digest="b" * 64,
            registered_at=datetime.now(UTC),
        )
    )
    app = _application(
        tmp_path,
        installer_writer_routes=_build_default_installer_writer_routes(),
        project_token=prepared.record,
    )
    app.run_pre_serve_startup_hook()
    definition = HookDefinition(
        hook_event_name=HookEventName.PRE_TOOL_USE,
        matcher="Bash",
        command="agentkit-hook-claude pre branch_guard",
    )

    def _run_up04(project_root: Path, **kwargs: object) -> object:
        governance = cast("HookRegistrationSurface", kwargs["governance"])
        registration_repo = cast(
            "ProjectRegistrationRepository",
            kwargs["registration_repo"],
        )
        skills = cast("Skills", kwargs["skills"])
        assert registration_repo.get(_PROJECT) is not None
        assert skills.list_bound_skills(project_root) == []
        outcome = governance.register_hooks([definition])
        assert outcome.errors == []
        return SimpleNamespace(
            failed=False,
            failed_checkpoints=(),
            detail="UP04 completed through the writer",
            scenario=SimpleNamespace(scenario=SimpleNamespace(value="in_place")),
        )

    monkeypatch.setattr(
        "agentkit.backend.installer.upgrade.entry.run_checkpoint_upgrade",
        _run_up04,
    )
    try:
        with _live_https_writer(app, tmp_path) as (base_url, certfile):
            arguments = [
                "upgrade-project",
                "--project-key",
                _PROJECT,
                "--project-root",
                str(tmp_path),
                "--github-owner",
                "openai",
                "--github-repo",
                "agentkit",
                "--target-config-version",
                "4.0",
                "--op-id",
                "op-upgrade-project-live-writer",
                "--control-plane-base-url",
                base_url,
                "--control-plane-ca-file",
                str(certfile),
            ]
            assert main(arguments) == 0
            assert main(arguments) == 0
    finally:
        app.release_writer_lease()

    from agentkit.backend.state_backend.store.governance_hook_repository import (
        StateBackendHookRegistrationRepository,
    )

    assert StateBackendHookRegistrationRepository().list_for_project(_PROJECT) == [
        definition,
    ]


@pytest.mark.parametrize("ambiguous_response", ["transport_loss", "malformed_success"])
def test_cp8_ambiguous_response_same_op_retry_converges_through_real_writer(
    tmp_path: Path,
    ambiguous_response: str,
) -> None:
    """CP8 retains committed state for transport and response-shape ambiguity."""

    prepared = _activate_project_token(tmp_path)
    _save_project()
    app = _application(
        tmp_path,
        installer_writer_routes=_build_default_installer_writer_routes(),
        project_token=prepared.record,
    )
    app.run_pre_serve_startup_hook()

    class _LoseVerifiedResponse:
        def __init__(self, delegate: HttpsJsonTransport) -> None:
            self._delegate = delegate
            self.lost = False

        def send(self, **kwargs: object) -> dict[str, object]:
            result = self._delegate.send(**cast("Any", kwargs))
            payload = kwargs.get("payload")
            if (
                not self.lost
                and isinstance(payload, dict)
                and payload.get("status") == SkillLifecycleStatus.VERIFIED.value
            ):
                self.lost = True
                if ambiguous_response == "transport_loss":
                    raise OSError("simulated response loss after writer commit")
                return {"malformed": "success payload after writer commit"}
            return result

    now = datetime.now(UTC)
    base_binding = {
        "binding_id": "binding-execute",
        "project_key": _PROJECT,
        "skill_name": "execute",
        "bundle_id": "execute-userstory-core",
        "bundle_version": "4.1.0",
        "content_digest": "a" * 64,
        "target_path": tmp_path / ".claude" / "skills" / "execute",
        "binding_mode": SkillBindingMode.JUNCTION,
        "pinned_at": now,
    }
    bound = SkillBinding.model_validate(
        {**base_binding, "status": SkillLifecycleStatus.BOUND}
    )
    verified = SkillBinding.model_validate(
        {**base_binding, "status": SkillLifecycleStatus.VERIFIED}
    )
    try:
        with _live_https_writer(app, tmp_path) as (base_url, certfile):
            ssl_context = ssl.create_default_context(cafile=str(certfile))
            transport = HttpsJsonTransport(
                base_url=base_url,
                ssl_context=ssl_context,
                skill_bundle_version="0.1.0",
                bearer_token=prepared.plaintext_token,
                project_key=_PROJECT,
            )
            first = InstallerWriterClient(
                cast("Any", _LoseVerifiedResponse(transport)),
                project_key=_PROJECT,
                op_id="op-cp8-response-loss",
            ).skill_binding_repository()
            first.save(bound)
            if ambiguous_response == "transport_loss":
                with pytest.raises(OSError, match="response loss"):
                    first.save(verified)
            else:
                with pytest.raises(ValidationError):
                    first.save(verified)
            with pytest.raises(RuntimeError, match="retaining canonical writer state"):
                first.delete(_PROJECT, "execute")

            retry = InstallerWriterClient(
                transport,
                project_key=_PROJECT,
                op_id="op-cp8-response-loss",
            ).skill_binding_repository()
            retry.save(bound)
            retry.save(verified)
            replayed = retry.list_for_project(_PROJECT)
            assert len(replayed) == 1
            assert replayed[0].model_dump(exclude={"pinned_at"}) == verified.model_dump(
                exclude={"pinned_at"}
            )
    finally:
        app.release_writer_lease()

    stored = StateBackendSkillBindingRepository().load(_PROJECT, "execute")
    assert stored is not None
    assert stored.model_dump(exclude={"pinned_at"}) == verified.model_dump(
        exclude={"pinned_at"}
    )


def test_cp8_in_flight_same_op_retry_converges_through_real_writer(
    tmp_path: Path,
) -> None:
    """An in-flight response is ambiguous and must not trigger compensation."""

    prepared = _activate_project_token(tmp_path)
    _save_project()
    app = _application(
        tmp_path,
        installer_writer_routes=_build_default_installer_writer_routes(),
        project_token=prepared.record,
    )
    app.run_pre_serve_startup_hook()

    class _ReportInFlightAfterVerifiedCommit:
        def __init__(self, delegate: HttpsJsonTransport) -> None:
            self._delegate = delegate
            self.reported = False

        def send(self, **kwargs: object) -> dict[str, object]:
            result = self._delegate.send(**cast("Any", kwargs))
            payload = kwargs.get("payload")
            if (
                not self.reported
                and isinstance(payload, dict)
                and payload.get("status") == SkillLifecycleStatus.VERIFIED.value
            ):
                self.reported = True
                raise ControlPlaneApiError(
                    "same operation is still in flight",
                    error_code="operation_in_flight",
                    correlation_id="corr-in-flight",
                    http_status=409,
                )
            return result

    now = datetime.now(UTC)
    binding_data = {
        "binding_id": "binding-review",
        "project_key": _PROJECT,
        "skill_name": "review",
        "bundle_id": "review-userstory-core",
        "bundle_version": "4.1.0",
        "content_digest": "c" * 64,
        "target_path": tmp_path / ".claude" / "skills" / "review",
        "binding_mode": SkillBindingMode.JUNCTION,
        "pinned_at": now,
    }
    bound = SkillBinding.model_validate(
        {**binding_data, "status": SkillLifecycleStatus.BOUND}
    )
    verified = SkillBinding.model_validate(
        {**binding_data, "status": SkillLifecycleStatus.VERIFIED}
    )
    try:
        with _live_https_writer(app, tmp_path) as (base_url, certfile):
            transport = HttpsJsonTransport(
                base_url=base_url,
                ssl_context=ssl.create_default_context(cafile=str(certfile)),
                skill_bundle_version="0.1.0",
                bearer_token=prepared.plaintext_token,
                project_key=_PROJECT,
            )
            first = InstallerWriterClient(
                cast("Any", _ReportInFlightAfterVerifiedCommit(transport)),
                project_key=_PROJECT,
                op_id="op-cp8-in-flight",
            ).skill_binding_repository()
            first.save(bound)
            with pytest.raises(ControlPlaneApiError) as captured:
                first.save(verified)
            assert captured.value.error_code == "operation_in_flight"
            with pytest.raises(RuntimeError, match="retaining canonical writer state"):
                first.delete(_PROJECT, "review")

            retry = InstallerWriterClient(
                transport,
                project_key=_PROJECT,
                op_id="op-cp8-in-flight",
            ).skill_binding_repository()
            retry.save(bound)
            retry.save(verified)
            replayed = retry.load(_PROJECT, "review")
            assert replayed is not None
            assert replayed.model_dump(exclude={"pinned_at"}) == verified.model_dump(
                exclude={"pinned_at"}
            )
    finally:
        app.release_writer_lease()

    stored = StateBackendSkillBindingRepository().load(_PROJECT, "review")
    assert stored is not None
    assert stored.model_dump(exclude={"pinned_at"}) == verified.model_dump(
        exclude={"pinned_at"}
    )


def test_installer_writer_route_enforces_replay_mismatch_and_in_flight() -> None:
    """Both installer verbs inherit the shared claim/replay/in-flight contract."""

    class _Hooks:
        def __init__(self) -> None:
            self.calls = 0

        def register(
            self,
            project_key: str,
            definitions: list[HookDefinition],
        ) -> RegistrationResult:
            assert project_key == _PROJECT
            self.calls += 1
            return RegistrationResult(
                registered=[definition.matcher for definition in definitions],
            )

        def list_for_project(self, project_key: str) -> list[HookDefinition]:
            assert project_key == _PROJECT
            return []

        def clear_for_project(self, project_key: str) -> None:
            assert project_key == _PROJECT

    hooks = _Hooks()
    guard = InMemoryInflightIdempotencyGuard()

    def _unused_repository() -> Never:
        raise AssertionError("unrelated installer repository was accessed")

    routes = InstallerWriterRoutes(
        owner=InstallerWriterService(
            registration_repository=_unused_repository,
            project_repository=_unused_repository,
            skill_binding_repository=_unused_repository,
            hook_repository=lambda: hooks,
        ),
        mutation_coordinator=InstallerMutationCoordinator(guard),
    )
    auth = AuthResult(
        auth_kind="project_api_token",
        project_key=_PROJECT,
        token_id="token-installer",
    )
    path = f"/v1/projects/{_PROJECT}/installation/governance-hooks"
    payload = {
        "op_id": "op-installer-replay",
        "hook_definitions": [
            {
                "hook_event_name": "PreToolUse",
                "matcher": "Bash",
                "command": "agentkit-hook-claude pre branch_guard",
            },
        ],
    }

    first = routes.handle_post(path, payload, "corr-first", auth)
    replay = routes.handle_post(path, payload, "corr-replay", auth)
    mismatch = routes.handle_post(
        path,
        {
            **payload,
            "hook_definitions": [
                {
                    "hook_event_name": "PreToolUse",
                    "matcher": "Write",
                    "command": "agentkit-hook-claude pre self_protection",
                },
            ],
        },
        "corr-mismatch",
        auth,
    )

    assert first is not None and first.status_code == 200
    assert replay is not None and json.loads(replay.body) == json.loads(first.body)
    assert mismatch is not None and mismatch.status_code == 409
    assert json.loads(mismatch.body)["error_code"] == "idempotency_mismatch"
    assert hooks.calls == 1

    in_flight_payload = {**payload, "op_id": "op-installer-in-flight"}
    identity = {**in_flight_payload, "project_key": _PROJECT}
    claimed = guard.claim(
        IdempotencyRequest(
            op_id="op-installer-in-flight",
            operation_kind="installer_governance_hooks_register",
            body_hash=compute_body_hash(identity),
            project_key=_PROJECT,
            session_id="token-installer",
        ),
    )
    assert isinstance(claimed, FreshClaim)
    in_flight = routes.handle_post(
        path,
        in_flight_payload,
        "corr-in-flight",
        auth,
    )
    assert in_flight is not None and in_flight.status_code == 409
    assert json.loads(in_flight.body)["error_code"] == "operation_in_flight"
    assert hooks.calls == 1


def test_split_story_public_cli_reaches_the_real_lease_holding_writer(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    service = _SuccessfulSplitService()

    def build_service(**_kwargs: object) -> _SuccessfulSplitService:
        assert load_bound_control_plane_writer_identity() is not None
        return service

    app = _application(
        tmp_path,
        story_split_routes=StorySplitRoutes(service_builder=build_service),
    )
    app.run_pre_serve_startup_hook()
    StateBackendProjectRepository().save(
        Project(
            key=_PROJECT,
            name="Tenant A",
            story_id_prefix="AG3",
            configuration=ProjectConfiguration(
                repo_url="",
                default_branch="main",
                are_url=None,
                default_worker_count=1,
                repositories=["https://example.test/repo.git"],
            ),
            archived_at=None,
        ),
    )
    plan_path = tmp_path / "split-plan.json"
    plan_path.write_text(
        json.dumps(
            {
                "project_key": _PROJECT,
                "source_story_id": "AG3-214",
                "reason": "scope_explosion",
                "successors": [
                    {
                        "story_id": "AG3-215",
                        "title": "First slice",
                        "scope_slice": "writer route",
                    },
                ],
            },
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "agentkit.backend.cli.story_commands.getpass.getpass",
        lambda _prompt: "secret",
    )
    try:
        with _live_https_writer(app, tmp_path) as (base_url, certfile):
            exit_code = main(
                [
                    "split-story",
                    "--story",
                    "AG3-214",
                    "--plan",
                    str(plan_path),
                    "--reason",
                    "scope explosion",
                    "--project",
                    _PROJECT,
                    "--run",
                    "run-ag3-214",
                    "--project-root",
                    str(tmp_path),
                    "--base-url",
                    base_url,
                    "--ca-file",
                    str(certfile),
                ],
            )
    finally:
        app.release_writer_lease()

    assert exit_code == 0
    assert json.loads(capsys.readouterr().out)["split_id"] == "split-live-writer"
    assert len(service.requests) == 1
    assert service.requests[0].principal.value == "human_cli"
    assert service.requests[0].requested_by != "strategist_session"


def test_admin_abort_public_cli_authenticates_and_aborts_through_the_writer(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    app = _application(tmp_path)
    app.run_pre_serve_startup_hook()
    identity = load_bound_control_plane_writer_identity()
    assert identity is not None
    now = datetime.now(UTC)
    operation = ControlPlaneOperationRecord(
        op_id="op-live-admin-abort",
        project_key=_PROJECT,
        story_id="AG3-214",
        run_id="run-ag3-214",
        session_id="session-worker",
        operation_kind="phase_start",
        phase="implementation",
        status="claimed",
        response_payload={},
        created_at=now,
        updated_at=now,
        claimed_by="writer-owner",
        claimed_at=now,
        operation_epoch=1,
        backend_instance_id=identity.backend_instance_id,
        instance_incarnation=identity.instance_incarnation,
        declared_serialization_scope=f"{_PROJECT}:AG3-214",
    )
    assert claim_control_plane_operation_global(operation)
    monkeypatch.setattr(
        "agentkit.backend.cli._operator_recovery_admin.getpass.getpass",
        lambda _prompt: "secret",
    )
    try:
        with _live_https_writer(app, tmp_path) as (base_url, certfile):
            exit_code = main(
                [
                    "admin-abort",
                    operation.op_id,
                    "--session",
                    "untrusted-cli-session",
                    "--principal",
                    "operator",
                    "--reason",
                    "hung executor; operator decision",
                    "--project",
                    _PROJECT,
                    "--project-root",
                    str(tmp_path),
                    "--base-url",
                    base_url,
                    "--ca-file",
                    str(certfile),
                ],
            )
    finally:
        app.release_writer_lease()

    assert exit_code == 0
    assert json.loads(capsys.readouterr().out)["status"] == "aborted"
    stored = load_control_plane_operation_global(operation.op_id)
    assert stored is not None and stored.status == "aborted"


def test_reset_story_public_cli_reaches_authenticated_writer_route(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    requests: list[object] = []

    class _ResetService:
        def request_reset(self, request: object) -> object:
            requests.append(request)
            return SimpleNamespace(reset_id=request.reset_id)

        def execute_reset(self, reset_id: str) -> object:
            return SimpleNamespace(
                reset_id=reset_id,
                record=SimpleNamespace(
                    status=SimpleNamespace(value="completed"),
                    story_id="AG3-214",
                    purge_summary={"runtime_execution": 2},
                ),
                clean_state=SimpleNamespace(run_id="run-reset", is_clean=True),
                resumed=False,
            )

    def build_reset(**_kwargs: object) -> object:
        assert load_bound_control_plane_writer_identity() is not None
        return _ResetService()

    app = _application(
        tmp_path,
        story_admin_routes=StoryAdminRoutes(reset_service_builder=build_reset),
    )
    app.run_pre_serve_startup_hook()
    _save_project()
    monkeypatch.setattr(
        "agentkit.backend.cli.story_commands.getpass.getpass",
        lambda _prompt: "secret",
    )
    try:
        with _live_https_writer(app, tmp_path) as (base_url, certfile):
            exit_code = main(
                [
                    "reset-story",
                    "--story",
                    "AG3-214",
                    "--reason",
                    "irreparable execution",
                    "--force",
                    "--project",
                    _PROJECT,
                    "--project-root",
                    str(tmp_path),
                    "--base-url",
                    base_url,
                    "--ca-file",
                    str(certfile),
                ],
            )
    finally:
        app.release_writer_lease()

    assert exit_code == 0
    assert json.loads(capsys.readouterr().out)["status"] == "completed"
    assert len(requests) == 1
    assert requests[0].requested_by != "human_cli"


def test_exit_story_public_cli_uses_writer_resolved_run_session(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    requests: list[object] = []

    class _ExitService:
        def exit_story(self, request: object) -> object:
            requests.append(request)
            return SimpleNamespace(
                exit_id=request.exit_id,
                record=SimpleNamespace(story_id=request.story_id),
                operating_mode="binding_invalid",
                artifact_dir=tmp_path / "var" / "story_exit",
            )

    repository = ControlPlaneRuntimeRepository(
        load_active_ownership=lambda _project, _story: SimpleNamespace(
            run_id="run-exit",
            owner_session_id="worker-session-from-writer",
        ),
    )

    def build_exit(**_kwargs: object) -> object:
        assert load_bound_control_plane_writer_identity() is not None
        return _ExitService()

    app = _application(
        tmp_path,
        story_admin_routes=StoryAdminRoutes(
            exit_service_builder=build_exit,
            repository=repository,
        ),
    )
    app.run_pre_serve_startup_hook()
    _save_project()
    monkeypatch.delenv("AGENTKIT_SESSION_ID", raising=False)
    monkeypatch.setattr(
        "agentkit.backend.cli.story_commands.getpass.getpass",
        lambda _prompt: "secret",
    )
    try:
        with _live_https_writer(app, tmp_path) as (base_url, certfile):
            exit_code = main(
                [
                    "exit-story",
                    "--story",
                    "AG3-214",
                    "--reason",
                    "solution_viability_requires_human_design",
                    "--project",
                    _PROJECT,
                    "--run",
                    "run-exit",
                    "--project-root",
                    str(tmp_path),
                    "--base-url",
                    base_url,
                    "--ca-file",
                    str(certfile),
                ],
            )
    finally:
        app.release_writer_lease()

    assert exit_code == 0
    assert json.loads(capsys.readouterr().out)["status"] == "committed"
    assert len(requests) == 1
    assert requests[0].session_id == "worker-session-from-writer"
    assert requests[0].principal.value == "human_cli"


@pytest.mark.parametrize(
    ("verb", "arguments", "expected_output"),
    [
        (
            "add-incident",
            [
                "--story-id", "AG3-214",
                "--run-id", "run-ag3-214",
                "--category", "scope_drift",
                "--severity", "high",
                "--phase", "implementation",
                "--role", "worker",
                "--model", "test-model",
                "--symptom", "scope exceeded",
                "--merge-blocked",
            ],
            "Incident recorded: FC-2026-0001",
        ),
        (
            "review-patterns",
            ["--pattern-id", "FP-0001", "--decision", "rejected"],
            "Pattern FP-0001: decision=rejected",
        ),
        (
            "review-checks",
            ["--check-id", "CHK-0001", "--decision", "rejected"],
            "Check CHK-0001: decision=rejected",
        ),
        (
            "effectiveness-report",
            ["--window-days", "30"],
            "Effectiveness report (window=30d): updated=3 deactivated=1",
        ),
    ],
)
def test_failure_corpus_mutating_cli_reaches_the_lease_holding_writer(
    verb: str,
    arguments: list[str],
    expected_output: str,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    corpus = _SuccessfulFailureCorpus()

    def build_corpus(project_key: str) -> object:
        assert project_key == _PROJECT
        assert load_bound_control_plane_writer_identity() is not None
        return corpus

    app = _application(
        tmp_path,
        failure_corpus_routes=FailureCorpusRoutes(corpus_builder=build_corpus),
    )
    app.run_pre_serve_startup_hook()
    _save_project()
    monkeypatch.setattr(
        "agentkit.backend.failure_corpus.cli.getpass.getpass",
        lambda _prompt: "secret",
    )
    try:
        with _live_https_writer(app, tmp_path) as (base_url, certfile):
            exit_code = main(
                [
                    "failure-corpus",
                    verb,
                    "--project-key",
                    _PROJECT,
                    *arguments,
                    "--project-root",
                    str(tmp_path),
                    "--base-url",
                    base_url,
                    "--ca-file",
                    str(certfile),
                ],
            )
    finally:
        app.release_writer_lease()

    assert exit_code == 0
    assert expected_output in capsys.readouterr().out
    assert [call[0] for call in corpus.calls] == [verb]


@pytest.mark.parametrize(
    ("route_path", "payload", "verb"),
    [
        (
            f"/v1/projects/{_PROJECT}/failure-corpus/incidents",
            {
                "op_id": "fc-replay-incident",
                "story_id": "AG3-214",
                "run_id": "run-ag3-214",
                "category": "scope_drift",
                "severity": "high",
                "phase": "implementation",
                "role": "worker",
                "model": "test-model",
                "symptom": "scope exceeded",
                "evidence": [],
                "merge_blocked": True,
            },
            "add-incident",
        ),
        (
            f"/v1/projects/{_PROJECT}/failure-corpus/patterns/FP-0001/review",
            {"op_id": "fc-replay-pattern", "decision": "rejected"},
            "review-patterns",
        ),
        (
            f"/v1/projects/{_PROJECT}/failure-corpus/checks/CHK-0001/review",
            {"op_id": "fc-replay-check", "decision": "rejected"},
            "review-checks",
        ),
        (
            f"/v1/projects/{_PROJECT}/failure-corpus/effectiveness-report",
            {"op_id": "fc-replay-effectiveness", "window_days": 30},
            "effectiveness-report",
        ),
    ],
)
def test_failure_corpus_mutations_replay_without_a_second_write(
    route_path: str,
    payload: dict[str, object],
    verb: str,
) -> None:
    corpus = _SuccessfulFailureCorpus()
    routes = FailureCorpusRoutes(
        corpus_builder=lambda _project_key: corpus,
        mutation_coordinator=FailureCorpusMutationCoordinator(
            InMemoryInflightIdempotencyGuard(),
        ),
    )
    auth = AuthResult(auth_kind="strategist_session", session_id="strategist-1")

    first = routes.handle_post(route_path, payload, "corr-first", auth)
    replay = routes.handle_post(route_path, payload, "corr-replay", auth)

    assert first is not None and first.status_code == 200
    assert replay is not None and replay.status_code == 200
    assert json.loads(replay.body) == json.loads(first.body)
    assert [call[0] for call in corpus.calls] == [verb]


def test_failure_corpus_reused_op_id_with_changed_body_is_rejected() -> None:
    corpus = _SuccessfulFailureCorpus()
    routes = FailureCorpusRoutes(
        corpus_builder=lambda _project_key: corpus,
        mutation_coordinator=FailureCorpusMutationCoordinator(
            InMemoryInflightIdempotencyGuard(),
        ),
    )
    auth = AuthResult(auth_kind="strategist_session", session_id="strategist-1")
    route_path = f"/v1/projects/{_PROJECT}/failure-corpus/incidents"
    payload = _incident_payload("fc-mismatch", symptom="first symptom")

    first = routes.handle_post(route_path, payload, "corr-first", auth)
    mismatch = routes.handle_post(
        route_path,
        _incident_payload("fc-mismatch", symptom="changed symptom"),
        "corr-mismatch",
        auth,
    )

    assert first is not None and first.status_code == 200
    assert mismatch is not None and mismatch.status_code == 409
    assert json.loads(mismatch.body)["error_code"] == "idempotency_mismatch"
    assert [call[0] for call in corpus.calls] == ["add-incident"]


def test_failure_corpus_parallel_same_op_id_is_rejected_in_flight() -> None:
    corpus = _SuccessfulFailureCorpus()
    guard = InMemoryInflightIdempotencyGuard()
    routes = FailureCorpusRoutes(
        corpus_builder=lambda _project_key: corpus,
        mutation_coordinator=FailureCorpusMutationCoordinator(guard),
    )
    auth = AuthResult(auth_kind="strategist_session", session_id="strategist-1")
    route_path = f"/v1/projects/{_PROJECT}/failure-corpus/incidents"
    payload = _incident_payload("fc-in-flight", symptom="held mutation")
    hash_payload = {**payload, "project_key": _PROJECT}
    claimed = guard.claim(
        IdempotencyRequest(
            op_id="fc-in-flight",
            operation_kind="failure_corpus_add_incident",
            body_hash=compute_body_hash(hash_payload),
            project_key=_PROJECT,
            session_id="strategist-1",
        ),
    )
    assert isinstance(claimed, FreshClaim)

    response = routes.handle_post(route_path, payload, "corr-in-flight", auth)

    assert response is not None and response.status_code == 409
    assert json.loads(response.body)["error_code"] == "operation_in_flight"
    assert corpus.calls == []


def test_failure_corpus_approved_story_and_active_save_are_atomic(
    tmp_path: Path,
) -> None:
    """Enter the story-created/check-not-ACTIVE window, then retry the same op."""

    _save_project()
    pattern_repo, base_check_repo = _seed_failure_corpus_checks(1)
    check_repo = _FailingCheckRepository(
        base_check_repo,
        fail_when=lambda proposal: proposal.status is CheckStatus.ACTIVE,
    )
    factory = CheckFactory(
        pattern_repo=pattern_repo,
        check_repo=check_repo,
        project_key=_PROJECT,
        story_creation=AK3StoryCreationAdapter(_PROJECT),
    )
    routes = _failure_corpus_check_routes(
        _CheckFactoryCorpus(factory),
    )
    app = _application(tmp_path)
    app.run_pre_serve_startup_hook()
    auth = AuthResult(auth_kind="strategist_session", session_id="strategist-atomic")
    path = f"/v1/projects/{_PROJECT}/failure-corpus/checks/CHK-0001/review"
    payload = {"op_id": "fc-approved-atomic-window", "decision": "approved"}
    try:
        first = routes.handle_post(path, payload, "corr-approved-first", auth)
        assert first is not None and first.status_code == HTTPStatus.SERVICE_UNAVAILABLE
        assert base_check_repo.load("CHK-0001").status is CheckStatus.DRAFT  # type: ignore[union-attr]
        from agentkit.backend.story_context_manager.service import StoryService

        assert StoryService().list_stories(_PROJECT) == []
        assert load_control_plane_operation_global("fc-approved-atomic-window") is None

        check_repo.disarm()
        retry = routes.handle_post(path, payload, "corr-approved-retry", auth)
        assert retry is not None and retry.status_code == HTTPStatus.OK
        assert base_check_repo.load("CHK-0001").status is CheckStatus.ACTIVE  # type: ignore[union-attr]
        stories = StoryService().list_stories(_PROJECT)
        assert len(stories) == 1
    finally:
        app.release_writer_lease()


def test_failure_corpus_revise_two_saves_are_atomic(tmp_path: Path) -> None:
    """Enter the old-REJECTED/new-DRAFT-missing window, then retry same op."""

    pattern_repo, base_check_repo = _seed_failure_corpus_checks(1)
    check_repo = _FailingCheckRepository(
        base_check_repo,
        fail_when=lambda proposal: proposal.check_id != "CHK-0001",
    )
    factory = CheckFactory(
        pattern_repo=pattern_repo,
        check_repo=check_repo,
        project_key=_PROJECT,
    )
    routes = _failure_corpus_check_routes(_CheckFactoryCorpus(factory))
    app = _application(tmp_path)
    app.run_pre_serve_startup_hook()
    auth = AuthResult(auth_kind="strategist_session", session_id="strategist-atomic")
    path = f"/v1/projects/{_PROJECT}/failure-corpus/checks/CHK-0001/review"
    payload = {"op_id": "fc-revise-atomic-window", "decision": "revise"}
    try:
        first = routes.handle_post(path, payload, "corr-revise-first", auth)
        assert first is not None and first.status_code == HTTPStatus.SERVICE_UNAVAILABLE
        original = base_check_repo.load("CHK-0001")
        assert original is not None and original.status is CheckStatus.DRAFT
        assert base_check_repo.list_for_project(_PROJECT) == [original]

        check_repo.disarm()
        retry = routes.handle_post(path, payload, "corr-revise-retry", auth)
        assert retry is not None and retry.status_code == HTTPStatus.OK
        records = base_check_repo.list_for_project(_PROJECT)
        assert [record.status for record in records] == [
            CheckStatus.REJECTED,
            CheckStatus.DRAFT,
        ]
    finally:
        app.release_writer_lease()


def test_failure_corpus_effectiveness_batch_and_claim_are_atomic(
    tmp_path: Path,
) -> None:
    """Enter the first-check-updated/later-check-failed window, then retry."""

    pattern_repo, base_check_repo = _seed_failure_corpus_checks(2, active=True)
    check_repo = _FailingCheckRepository(
        base_check_repo,
        fail_on_save_number=2,
    )
    from agentkit.backend.bootstrap.composition_root import build_projection_accessor

    tracker = CheckEffectivenessTracker(
        build_projection_accessor(),
        check_repo,
        pattern_repo,
        _PROJECT,
    )
    routes = FailureCorpusRoutes(
        corpus_builder=lambda _project_key: _EffectivenessCorpus(tracker),
        mutation_coordinator=FailureCorpusMutationCoordinator(
            StateBackendInflightIdempotencyGuard(),
        ),
    )
    app = _application(tmp_path)
    app.run_pre_serve_startup_hook()
    auth = AuthResult(auth_kind="strategist_session", session_id="strategist-atomic")
    path = f"/v1/projects/{_PROJECT}/failure-corpus/effectiveness-report"
    payload = {"op_id": "fc-effectiveness-atomic-window", "window_days": 30}
    try:
        first = routes.handle_post(path, payload, "corr-effect-first", auth)
        assert first is not None and first.status_code == HTTPStatus.SERVICE_UNAVAILABLE
        assert all(
            record.effectiveness_last_checked_at is None
            for record in base_check_repo.list_for_project(_PROJECT)
        )

        check_repo.disarm()
        retry = routes.handle_post(path, payload, "corr-effect-retry", auth)
        assert retry is not None and retry.status_code == HTTPStatus.OK
        assert all(
            record.effectiveness_last_checked_at is not None
            for record in base_check_repo.list_for_project(_PROJECT)
        )
    finally:
        app.release_writer_lease()


class _FailingCheckRepository:
    """Delegate to the real repository and fail at a selected multi-write step."""

    def __init__(
        self,
        delegate: StateBackendFcCheckProposalRepository,
        *,
        fail_when: Callable[[CheckProposalRecord], bool] | None = None,
        fail_on_save_number: int | None = None,
    ) -> None:
        self._delegate = delegate
        self._fail_when = fail_when
        self._fail_on_save_number = fail_on_save_number
        self._armed = True
        self._save_count = 0

    def disarm(self) -> None:
        self._armed = False

    def save(self, proposal: CheckProposalRecord) -> None:
        self._save_count += 1
        selected = (
            self._fail_when is not None and self._fail_when(proposal)
        ) or self._save_count == self._fail_on_save_number
        if self._armed and selected:
            raise RuntimeError("injected failure-corpus multi-write failure")
        self._delegate.save(proposal)

    def load(self, check_id: str) -> CheckProposalRecord | None:
        return self._delegate.load(check_id)

    def list_for_pattern(self, pattern_ref: str) -> list[CheckProposalRecord]:
        return self._delegate.list_for_pattern(pattern_ref)

    def list_for_project(self, project_key: str) -> list[CheckProposalRecord]:
        return self._delegate.list_for_project(project_key)

    def max_check_seq(self) -> int:
        return self._delegate.max_check_seq()


class _CheckFactoryCorpus:
    def __init__(self, factory: CheckFactory) -> None:
        self._factory = factory

    def approve_check(self, check_id: CheckId, decision: object, **kwargs: object) -> object:
        result = self._factory.approve_check(
            check_id,
            cast("Any", decision),
            rejected_reason=cast("str | None", kwargs.get("rejected_reason")),
        )
        return SimpleNamespace(check_id=result)


class _EffectivenessCorpus:
    def __init__(self, tracker: CheckEffectivenessTracker) -> None:
        self._tracker = tracker

    def report_effectiveness(self, window_days: int = 90) -> object:
        return self._tracker.report_effectiveness(window_days=window_days)


def _failure_corpus_check_routes(corpus: object) -> FailureCorpusRoutes:
    return FailureCorpusRoutes(
        corpus_builder=lambda _project_key: corpus,
        mutation_coordinator=FailureCorpusMutationCoordinator(
            StateBackendInflightIdempotencyGuard(),
        ),
    )


def _seed_failure_corpus_checks(
    count: int,
    *,
    active: bool = False,
) -> tuple[StateBackendFcPatternRepository, StateBackendFcCheckProposalRepository]:
    pattern_repo = StateBackendFcPatternRepository()
    check_repo = StateBackendFcCheckProposalRepository()
    pattern_repo.save(
        FailurePatternRecord(
            pattern_id="FP-0001",
            project_key=_PROJECT,
            status=PatternStatus.ACCEPTED,
            category=FailureCategory.SCOPE_DRIFT,
            promotion_rule=PromotionRule.HIGH_SEVERITY,
            invariant="Atomic failure-corpus invariant",
            risk_level=PatternRiskLevel.MEDIUM,
            confirmed_by="human",
            incident_refs=[],
            incident_count=0,
        ),
    )
    for index in range(1, count + 1):
        check_repo.save(
            CheckProposalRecord(
                check_id=f"CHK-{index:04d}",
                project_key=_PROJECT,
                status=CheckStatus.ACTIVE if active else CheckStatus.DRAFT,
                pattern_ref="FP-0001",
                invariant=f"Atomic check {index}",
                check_type=CheckType.CHANGED_FILE_POLICY,
                pipeline_stage="structural",
                pipeline_layer=1,
                owner="failure-corpus",
                false_positive_risk=FalsePositiveRisk.LOW,
                positive_fixtures=[],
                negative_fixtures=[],
                created_at=datetime.now(UTC),
                approved_at=datetime.now(UTC) if active else None,
                approved_by="human" if active else None,
            ),
        )
    return pattern_repo, check_repo


def _incident_payload(op_id: str, *, symptom: str) -> dict[str, object]:
    return {
        "op_id": op_id,
        "story_id": "AG3-214",
        "run_id": "run-ag3-214",
        "category": "scope_drift",
        "severity": "high",
        "phase": "implementation",
        "role": "worker",
        "model": "test-model",
        "symptom": symptom,
        "evidence": [],
        "merge_blocked": True,
    }


def test_failure_corpus_add_incident_without_writer_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _assert_failure_corpus_mutation_needs_writer(
        monkeypatch,
        tmp_path,
        capsys,
        "add-incident",
        [
            "--story-id", "AG3-214",
            "--run-id", "run-ag3-214",
            "--category", "scope_drift",
            "--severity", "high",
            "--phase", "implementation",
            "--role", "worker",
            "--model", "test-model",
            "--symptom", "scope exceeded",
            "--merge-blocked",
        ],
    )


def test_failure_corpus_review_patterns_without_writer_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _assert_failure_corpus_mutation_needs_writer(
        monkeypatch,
        tmp_path,
        capsys,
        "review-patterns",
        ["--pattern-id", "FP-0001", "--decision", "rejected"],
    )


def test_failure_corpus_review_checks_without_writer_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _assert_failure_corpus_mutation_needs_writer(
        monkeypatch,
        tmp_path,
        capsys,
        "review-checks",
        ["--check-id", "CHK-0001", "--decision", "rejected"],
    )


def test_failure_corpus_effectiveness_report_without_writer_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _assert_failure_corpus_mutation_needs_writer(
        monkeypatch,
        tmp_path,
        capsys,
        "effectiveness-report",
        ["--window-days", "30"],
    )


def _assert_failure_corpus_mutation_needs_writer(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    verb: str,
    arguments: list[str],
) -> None:
    def forbidden_local_repository(*_args: object, **_kwargs: object) -> object:
        raise AssertionError("mutating failure-corpus CLI built a local repository")

    monkeypatch.setattr(
        "agentkit.backend.bootstrap.composition_root.build_projection_accessor",
        forbidden_local_repository,
    )
    monkeypatch.setattr(
        "agentkit.backend.bootstrap.composition_root.build_failure_corpus",
        forbidden_local_repository,
    )
    monkeypatch.setattr(
        "agentkit.backend.failure_corpus.cli.getpass.getpass",
        lambda _prompt: "secret",
    )
    exit_code = main(
        [
            "failure-corpus",
            verb,
            "--project-key",
            _PROJECT,
            *arguments,
            "--project-root",
            str(tmp_path),
            "--base-url",
            f"https://127.0.0.1:{_unused_port()}",
        ],
    )
    captured = capsys.readouterr()
    assert exit_code == 1
    assert "BackendUnreachable" in captured.err
    assert "local repository" not in captured.err


def test_productive_split_composition_uses_the_already_bound_writer_identity(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from agentkit.backend.bootstrap import composition_project
    from agentkit.backend.story_creation import weaviate_index
    from agentkit.backend.story_split.service import SplitSourceState, StorySplitService
    from agentkit.backend.vectordb import wait_for_weaviate
    from agentkit.integration_clients import vectordb

    app = _application(tmp_path)
    app.run_pre_serve_startup_hook()
    identity_before = load_bound_control_plane_writer_identity()
    assert identity_before is not None
    monkeypatch.setattr(
        composition_project,
        "resolve_split_export_project_id",
        lambda _project_root: "TENANT",
    )
    monkeypatch.setattr(
        wait_for_weaviate,
        "resolve_adapter_endpoints",
        lambda _project_root: {},
    )
    monkeypatch.setattr(
        vectordb.WeaviateStoryAdapter,
        "connect",
        staticmethod(lambda **_kwargs: object()),
    )
    monkeypatch.setattr(
        weaviate_index,
        "WeaviateStoryIndex",
        lambda _adapter, **_kwargs: object(),
    )
    try:
        service = composition_project.build_story_split_service(
            project_key=_PROJECT,
            stories_root=tmp_path / "stories",
            project_root=str(tmp_path),
            source_state_loader=lambda _request: SplitSourceState(
                scope_explosion_established=True,
                paused_with_scope_explosion=True,
                competing_admin_operation_active=False,
            ),
        )
        identity_after = load_bound_control_plane_writer_identity()
    finally:
        app.release_writer_lease()

    assert isinstance(service, StorySplitService)
    assert identity_after == identity_before


def test_idle_writer_session_termination_closes_both_listeners_and_fails_serve(
    tmp_path: Path,
) -> None:
    """L1: the application monitor detects a real server-side session kill."""

    certfile = tmp_path / "monitor-cert.pem"
    keyfile = tmp_path / "monitor-key.pem"
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
        ],
        check=True,
        capture_output=True,
        encoding="utf-8",
        text=True,
    )
    ui_port = _unused_port()
    project_api_port = _unused_port()
    app = _application(tmp_path)
    errors: list[BaseException] = []

    def run_server() -> None:
        try:
            serve_control_plane(
                ui_host="127.0.0.1",
                ui_port=ui_port,
                project_api_host="127.0.0.1",
                project_api_port=project_api_port,
                certfile=certfile,
                keyfile=keyfile,
                app=app,
            )
        except BaseException as exc:  # test captures the thread's fatal result
            errors.append(exc)

    thread = Thread(target=run_server)
    thread.start()
    for _ in range(100):
        lease = vars(app)["_writer_lease"]
        if lease is not None:
            break
        thread.join(timeout=0.05)
    else:
        pytest.fail("writer lease was not acquired")
    assert lease is not None
    row = lease.delegate.connection.execute("SELECT pg_backend_pid() AS pid").fetchone()
    assert row is not None
    database_url = load_state_backend_config().database_url
    assert database_url is not None
    with psycopg.connect(database_url) as killer:
        terminated = killer.execute(
            "SELECT pg_terminate_backend(%s)",
            (int(row["pid"]),),
        ).fetchone()
    assert terminated is not None and terminated[0] is True

    thread.join(timeout=10)
    assert not thread.is_alive()
    assert len(errors) == 1
    assert isinstance(errors[0], ControlPlaneWriterLeaseLostError)
    assert app.writer_lease_loss_reason is not None
    for port in (ui_port, project_api_port):
        with pytest.raises(OSError), socket.create_connection(("127.0.0.1", port), timeout=0.2):
            pass


def test_shutdown_drains_blocked_self_test_before_writer_unlock(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """L2: orderly shutdown waits for real queued writer work to finalize."""

    entered = Event()
    proceed = Event()

    def blocked_self_test(*_args: object) -> BranchPluginSelfTestOperation:
        entered.set()
        assert proceed.wait(timeout=5)
        return BranchPluginSelfTestOperation(
            op_id="shutdown-self-test",
            status="succeeded",
            detail="completed before unlock",
        )

    monkeypatch.setattr(
        "agentkit.backend.installer.third_party_self_test.execute_branch_plugin_self_test",
        blocked_self_test,
    )
    service = _preflight_service()
    app = _application(
        tmp_path,
        third_party_routes=ThirdPartyValidationRoutes(service),
    )
    app.run_pre_serve_startup_hook()
    service.start_self_test(_PROJECT, _self_test_request("shutdown-self-test"))
    assert entered.wait(timeout=5)
    released = Event()

    def release() -> None:
        app.release_writer_lease()
        released.set()

    thread = Thread(target=release)
    thread.start()
    assert not released.wait(timeout=0.2)
    proceed.set()
    thread.join(timeout=5)
    assert released.is_set()
    stored = load_control_plane_operation_global("shutdown-self-test")
    assert stored is not None and stored.status == "committed"


def test_session_loss_aborts_blocked_self_test_without_late_pool_commit(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """L2: a real session kill prevents finalization after blocked work returns."""

    entered = Event()
    proceed = Event()

    def blocked_self_test(*_args: object) -> BranchPluginSelfTestOperation:
        entered.set()
        assert proceed.wait(timeout=5)
        return BranchPluginSelfTestOperation(
            op_id="lost-lease-self-test",
            status="succeeded",
            detail="must not be committed",
        )

    monkeypatch.setattr(
        "agentkit.backend.installer.third_party_self_test.execute_branch_plugin_self_test",
        blocked_self_test,
    )
    executor = _CompletionTrackingExecutor()
    service = _preflight_service(executor=executor)
    app = _application(
        tmp_path,
        third_party_routes=ThirdPartyValidationRoutes(service),
    )
    app.run_pre_serve_startup_hook()
    service.start_self_test(_PROJECT, _self_test_request("lost-lease-self-test"))
    assert entered.wait(timeout=5)
    monitor = Thread(target=app.wait_for_writer_lease_loss)
    monitor.start()
    lease = vars(app)["_writer_lease"]
    assert lease is not None
    row = lease.delegate.connection.execute("SELECT pg_backend_pid() AS pid").fetchone()
    assert row is not None
    database_url = load_state_backend_config().database_url
    assert database_url is not None
    with psycopg.connect(database_url) as killer:
        killer.execute("SELECT pg_terminate_backend(%s)", (int(row["pid"]),)).fetchone()
    monitor.join(timeout=5)
    assert app.writer_lease_loss_reason is not None
    proceed.set()
    app.release_writer_lease()
    assert executor.completed.wait(timeout=5)
    stored = load_control_plane_operation_global("lost-lease-self-test")
    assert stored is not None
    assert stored.status == "claimed"
    assert stored.finalized_at is None


def _preflight_service(
    *,
    executor: object | None = None,
) -> ThirdPartyPreflightService:
    return ThirdPartyPreflightService(
        resolver=cast("Any", object()),
        clients=cast("Any", object()),
        guard=StateBackendInflightIdempotencyGuard(),
        operation_loader=load_control_plane_operation_global,
        executor=cast(
            "Any",
            executor or BoundedThreadExecutor(max_workers=1, max_queued=1),
        ),
    )


def _self_test_request(op_id: str) -> BranchPluginSelfTestRequest:
    return BranchPluginSelfTestRequest.model_validate(
        {
            "op_id": op_id,
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
        },
    )


def _unused_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


def _save_project() -> None:
    StateBackendProjectRepository().save(
        Project(
            key=_PROJECT,
            name="Tenant A",
            story_id_prefix="AG3",
            configuration=ProjectConfiguration(
                repo_url="",
                default_branch="main",
                are_url=None,
                default_worker_count=1,
                repositories=["https://example.test/repo.git"],
            ),
            archived_at=None,
        ),
    )
