"""Operator-CLI run-phase/resume over REST -> real control-plane route (AG3-130).

Drives the PRODUCTIVE operator entrypoint ``agentkit run-phase`` / ``agentkit
resume`` end-to-end over a real socket into the REAL
:class:`ControlPlaneApplication` route (the same ``BaseHTTPRequestHandler`` the
HTTPS server uses), reached by the CLI's own ``ProjectEdgeClient`` transport
(urllib) over ``http://``. There is NO mock of the vermittlung (routing / runtime
service): the CLI validates locally and delegates the phase EXECUTION to the core
over REST (FK-10 §10.1.0 I3), which drives the deterministic single-phase
dispatcher + pipeline engine. Only the leaf phase handlers are NoOp/scripted at
the external boundary (they would otherwise spawn workers / touch git), exactly
as the AG3-054 dispatch contract test does.

The served app is wired handshake-gated (``VersionHandshakeMiddleware``) exactly
like the production listener (FK-91 §91.1a Rule 11), so the CLI must carry the
version handshake (``X-AK3-Client`` + ``X-AK3-Skill-Bundle``) or the mutation is
refused with HTTP 426 (Codex B2c).

Proves:

* ``run-phase`` reaches the canonical project-scoped ``.../phases/{phase}/start``
  route through the handshake and the core commits the dispatch.
* ``resume`` reaches the NEW ``.../phases/{phase}/resume`` route and the core
  drives ``PipelineEngine.resume_phase`` server-side for a real PAUSED phase.
* A resume for an unadmitted run is a fail-closed core rejection mapped onto a
  non-zero CLI exit (no in-process fallback).
* B1: the resume reserves the op_id via a leased claim BEFORE the engine resume
  runs (a live foreign claim / a replay never dispatches on_resume twice).
* M3: an invalid resume trigger stores NO operation and materializes NO binding /
  lock side effects.
"""

from __future__ import annotations

import json
import threading
from datetime import UTC, datetime
from http.server import HTTPServer
from typing import TYPE_CHECKING

import pytest
from tests.fixtures.git_repo import ensure_git_repo

from agentkit.backend.cli.main import main
from agentkit.backend.control_plane.dispatch import PhaseDispatcher, PreStartGuard
from agentkit.backend.control_plane.models import PhaseMutationRequest
from agentkit.backend.control_plane.records import BackendInstanceIdentityRecord
from agentkit.backend.control_plane.runtime import (
    ControlPlaneRuntimeService,
    _build_claim_placeholder,
)
from agentkit.backend.control_plane.workspace_locator import (
    build_story_workspace_locator,
)
from agentkit.backend.control_plane_http.app import (
    ControlPlaneApplication,
    _build_handler,
)
from agentkit.backend.control_plane_http.version_handshake import (
    VersionHandshakeMiddleware,
)
from agentkit.backend.installer import InstallConfig, install_agentkit
from agentkit.backend.installer.paths import story_dir as resolve_story_dir
from agentkit.backend.pipeline_engine.engine import PipelineEngine
from agentkit.backend.pipeline_engine.lifecycle import (
    HandlerResult,
    NoOpHandler,
    PhaseHandlerRegistry,
)
from agentkit.backend.pipeline_engine.phase_executor import PhaseStatus
from agentkit.backend.process.language.definitions import resolve_workflow
from agentkit.backend.state_backend.story_lifecycle_store import save_story_context
from agentkit.backend.state_backend.telemetry_event_store import load_execution_events_for_project_global
from agentkit.backend.story_context_manager.models import StoryContext
from agentkit.backend.story_context_manager.types import StoryMode, StoryType
from agentkit.backend.telemetry.events import EventType
from agentkit.harness_client.projectedge.client import HttpsJsonTransport

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

    from agentkit.backend.control_plane.workspace_locator import StoryWorkspace
    from agentkit.backend.pipeline_engine.phase_envelope.envelope import PhaseEnvelope


# ---------------------------------------------------------------------------
# Boundary handlers / guard (only the leaf handlers are scripted)
# ---------------------------------------------------------------------------


class _AllowApproval:
    def is_approved(self, project_key: str, story_display_id: str) -> bool:
        del project_key, story_display_id
        return True


class _AllowScheduling:
    def is_ready_and_admitted(self, project_key: str, story_display_id: str) -> bool:
        del project_key, story_display_id
        return True


class _PauseThenCompleteHandler:
    """Pauses on first entry, completes on resume; counts on_resume calls (B1)."""

    def __init__(self) -> None:
        self.resume_calls = 0

    def on_enter(self, ctx: StoryContext, envelope: PhaseEnvelope) -> HandlerResult:
        del ctx, envelope
        return HandlerResult(
            status=PhaseStatus.PAUSED, yield_status="awaiting_design_review"
        )

    def on_exit(self, ctx: StoryContext, envelope: PhaseEnvelope) -> None:
        del ctx, envelope

    def on_resume(
        self, ctx: StoryContext, envelope: PhaseEnvelope, trigger: str
    ) -> HandlerResult:
        del ctx, envelope, trigger
        self.resume_calls += 1
        return HandlerResult(status=PhaseStatus.COMPLETED)


class _PauseThenFailHandler(_PauseThenCompleteHandler):
    """Pauses on entry, then FAILS on resume (valid trigger, real on_resume work)."""

    def on_resume(
        self, ctx: StoryContext, envelope: PhaseEnvelope, trigger: str
    ) -> HandlerResult:
        del ctx, envelope, trigger
        self.resume_calls += 1
        return HandlerResult(status=PhaseStatus.FAILED, errors=("resume work failed",))


def _count_events(
    project_key: str, run_id: str, event_type: EventType
) -> int:
    """Count committed lifecycle events of ``event_type`` for a run (read-only)."""
    events = load_execution_events_for_project_global(project_key, limit=None)
    return sum(
        1
        for e in events
        if getattr(e, "run_id", None) == run_id
        and str(getattr(e, "event_type", "")) == event_type.value
    )


def _install_project(project_dir: Path) -> None:
    ensure_git_repo(project_dir)
    result = install_agentkit(
        InstallConfig(
        weaviate_host="weaviate.test.local",
        weaviate_http_port=19903,
        weaviate_grpc_port=50051,
            project_key=project_dir.name,
            project_name=project_dir.name,
            project_root=project_dir,
            github_owner="acme",
            github_repo="demo",
            sonarqube_available=False,
            ci_available=False,
        )
    )
    assert result.success
    # The version handshake needs the bound skill-bundle version; the install
    # writes the project's prompt-bundle lock (CP 8). Assert it so a handshake
    # 426 is diagnosed here rather than deep in the CLI call (Codex B2c).
    lock = project_dir / ".agentkit" / "config" / "prompt-bundle.lock.json"
    assert lock.is_file(), "install must write the prompt-bundle lock for the handshake"


def _persist_ctx(project_dir: Path, story_id: str, *, route: StoryMode) -> None:
    s_dir = resolve_story_dir(project_dir, story_id)
    s_dir.mkdir(parents=True, exist_ok=True)
    ctx = StoryContext(
        project_key=project_dir.name,
        story_id=story_id,
        story_type=StoryType.IMPLEMENTATION,
        execution_route=route,
        project_root=project_dir,
    )
    save_story_context(s_dir, ctx)


def _boundary_dispatcher(
    *, overrides: dict[str, object] | None = None
) -> PhaseDispatcher:
    # Keep the SAME dict by reference (an empty dict is falsy -> ``or {}`` would
    # rebind to a fresh dict and drop the fixture's later mutations).
    overrides = {} if overrides is None else overrides
    guard = PreStartGuard(
        approval_reader=_AllowApproval(),
        scheduling_reader=_AllowScheduling(),
    )

    def _factory(ctx: StoryContext, workspace: StoryWorkspace) -> PipelineEngine:
        workflow = resolve_workflow(ctx.story_type)
        registry = PhaseHandlerRegistry()
        for name in workflow.phase_names:
            registry.register(name, overrides.get(name, NoOpHandler()))  # type: ignore[arg-type]
        return PipelineEngine(workflow, registry, workspace.story_dir)

    return PhaseDispatcher(
        workspace_locator=build_story_workspace_locator(),
        engine_factory=_factory,
        guard_factory=lambda workspace: guard,
    )


def _serve(service: ControlPlaneRuntimeService) -> tuple[HTTPServer, str]:
    """Serve the REAL handshake-gated control-plane app on a localhost socket."""
    app = ControlPlaneApplication(
        runtime_service=service,
        # Production-accurate: the real listener is handshake-gated (FK-91 §91.1a
        # Rule 11). run-phase/resume must carry the version handshake or 426.
        version_handshake_middleware=VersionHandshakeMiddleware(),
    )
    app.ensure_version_handshake()
    server = HTTPServer(("127.0.0.1", 0), _build_handler(app))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    host, port = server.server_address
    return server, f"http://{host}:{port}"


@pytest.fixture()
def served_service() -> Iterator[
    tuple[ControlPlaneRuntimeService, str, dict[str, object]]
]:
    """Yield (service, base_url, overrides-holder). Overrides set per test before use."""
    overrides: dict[str, object] = {}
    service = ControlPlaneRuntimeService(
        phase_dispatcher=_boundary_dispatcher(overrides=overrides)
    )
    server, base_url = _serve(service)
    try:
        yield service, base_url, overrides
    finally:
        server.shutdown()
        server.server_close()


def _base_argv(
    verb: str,
    phase: str,
    project_dir: Path,
    story_id: str,
    base_url: str,
) -> list[str]:
    return [
        verb,
        phase,
        "--story", story_id,
        "--run", "run-1",
        "--session", "sess-1",
        "--principal", "operator",
        "--worktree", str(project_dir),
        "--project", project_dir.name,
        # The handshake reads the bound skill-bundle version from this project root.
        "--project-root", str(project_dir),
        "--base-url", base_url,
    ]


def _req(
    project_dir: Path, story_id: str, op_suffix: str, **extra: object
) -> PhaseMutationRequest:
    return PhaseMutationRequest(
        project_key=project_dir.name,
        story_id=story_id,
        session_id="sess-1",
        principal_type="operator",
        worktree_roots=[str(project_dir)],
        op_id=f"op-{story_id}-{op_suffix}",
        **extra,  # type: ignore[arg-type]
    )


def _arrange_paused_exploration(
    service: ControlPlaneRuntimeService, project_dir: Path, story_id: str
) -> None:
    """Drive setup + a paused exploration via the SAME core (real PAUSED state)."""
    setup = service.start_phase(
        run_id="run-1", phase="setup", request=_req(project_dir, story_id, "setup")
    )
    assert setup.status == "committed"
    paused = service.start_phase(
        run_id="run-1",
        phase="exploration",
        request=_req(project_dir, story_id, "explore"),
    )
    assert paused.phase_dispatch is not None
    assert paused.phase_dispatch.status == "yielded"


@pytest.mark.integration
class TestOperatorCliPhaseRest:
    """CLI run-phase/resume drive the REAL handshake-gated route over REST (AG3-130)."""

    def test_run_phase_setup_commits_over_real_rest_route(
        self,
        tmp_path: Path,
        served_service: tuple[ControlPlaneRuntimeService, str, dict[str, object]],
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """run-phase setup passes the handshake and the CORE commits the dispatch."""
        _service, base_url, _overrides = served_service
        project_dir = tmp_path / "proj"
        project_dir.mkdir()
        _install_project(project_dir)
        story_id = "CLIREST-001"
        _persist_ctx(project_dir, story_id, route=StoryMode.EXECUTION)

        code = main(_base_argv("run-phase", "setup", project_dir, story_id, base_url))

        out = capsys.readouterr().out
        assert code == 0, out
        payload = json.loads(out)
        assert payload["status"] == "committed"
        # The phase_dispatch only exists because the CORE dispatched server-side.
        assert payload["phase_dispatch"]["phase"] == "setup"
        assert payload["phase_dispatch"]["status"] == "phase_completed"

    def test_resume_drives_core_resume_over_real_rest_route(
        self,
        tmp_path: Path,
        served_service: tuple[ControlPlaneRuntimeService, str, dict[str, object]],
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """resume passes the handshake, reaches the resume route and resumes a PAUSED phase."""
        service, base_url, overrides = served_service
        overrides["exploration"] = _PauseThenCompleteHandler()
        project_dir = tmp_path / "proj"
        project_dir.mkdir()
        _install_project(project_dir)
        story_id = "CLIREST-002"
        _persist_ctx(project_dir, story_id, route=StoryMode.EXPLORATION)
        _arrange_paused_exploration(service, project_dir, story_id)

        code = main(
            _base_argv("resume", "exploration", project_dir, story_id, base_url)
            + ["--trigger", "design_approved"]
        )

        out = capsys.readouterr().out
        assert code == 0, out
        payload = json.loads(out)
        assert payload["status"] == "committed"
        assert payload["operation_kind"] == "phase_resume"
        assert payload["phase_dispatch"]["phase"] == "exploration"
        assert payload["phase_dispatch"]["status"] == "phase_completed"

    def test_resume_unadmitted_run_is_core_rejected_nonzero(
        self,
        tmp_path: Path,
        served_service: tuple[ControlPlaneRuntimeService, str, dict[str, object]],
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """A resume for a run with no admitted start is a fail-closed core rejection."""
        _service, base_url, overrides = served_service
        overrides["exploration"] = _PauseThenCompleteHandler()
        project_dir = tmp_path / "proj"
        project_dir.mkdir()
        _install_project(project_dir)
        story_id = "CLIREST-003"
        _persist_ctx(project_dir, story_id, route=StoryMode.EXPLORATION)

        # No prior setup start -> the run was never admitted -> core rejects,
        # surfaced fail-closed as a non-zero CLI exit (no in-process fallback).
        code = main(
            _base_argv("resume", "exploration", project_dir, story_id, base_url)
            + ["--trigger", "design_approved"]
        )

        out = capsys.readouterr().out
        assert code != 0
        payload = json.loads(out)
        assert payload["status"] == "rejected"
        assert payload["operation_kind"] == "phase_resume"


@pytest.mark.integration
class TestResumeClaimAndSideEffects:
    """B1 (claim-before-dispatch) + M3 (failed resume stores nothing) at the core."""

    def test_resume_replays_same_op_id_without_second_dispatch(
        self,
        tmp_path: Path,
        served_service: tuple[ControlPlaneRuntimeService, str, dict[str, object]],
    ) -> None:
        """Two resumes with the SAME op_id: the second replays, on_resume runs once (B1)."""
        service, _base_url, overrides = served_service
        handler = _PauseThenCompleteHandler()
        overrides["exploration"] = handler
        project_dir = tmp_path / "proj"
        project_dir.mkdir()
        _install_project(project_dir)
        story_id = "CLIREST-004"
        _persist_ctx(project_dir, story_id, route=StoryMode.EXPLORATION)
        _arrange_paused_exploration(service, project_dir, story_id)

        req = _req(
            project_dir, story_id, "resume", detail={"resume_trigger": "design_approved"}
        )
        first = service.resume_phase(run_id="run-1", phase="exploration", request=req)
        replay = service.resume_phase(run_id="run-1", phase="exploration", request=req)

        assert first.status == "committed"
        assert first.operation_kind == "phase_resume"
        assert replay.status == "replayed"
        # The side-effecting engine resume ran EXACTLY once (claim gates dispatch).
        assert handler.resume_calls == 1

    def test_resume_loses_live_foreign_claim_and_never_dispatches(
        self,
        tmp_path: Path,
        served_service: tuple[ControlPlaneRuntimeService, str, dict[str, object]],
    ) -> None:
        """A live foreign claim on the op_id blocks the resume BEFORE on_resume (B1)."""
        service, _base_url, overrides = served_service
        handler = _PauseThenCompleteHandler()
        overrides["exploration"] = handler
        project_dir = tmp_path / "proj"
        project_dir.mkdir()
        _install_project(project_dir)
        story_id = "CLIREST-005"
        _persist_ctx(project_dir, story_id, route=StoryMode.EXPLORATION)
        _arrange_paused_exploration(service, project_dir, story_id)

        req = _req(
            project_dir, story_id, "resume", detail={"resume_trigger": "design_approved"}
        )
        # Simulate a concurrent in-flight owner: reserve the op_id with a FRESH
        # (non-expired) foreign claim before our resume runs. AG3-138 AC3: every
        # claim placeholder is stamped with a backend instance identity; this
        # foreign in-flight owner carries a distinct (foreign) identity.
        foreign_identity = BackendInstanceIdentityRecord(
            backend_instance_id="foreign-backend",
            instance_incarnation=1,
            updated_at=datetime.now(tz=UTC),
        )
        placeholder = _build_claim_placeholder(
            req,
            run_id="run-1",
            phase="exploration",
            owner_token="owner-00000000000000000000000000000000",
            now=datetime.now(tz=UTC),
            instance_identity=foreign_identity,
            operation_kind="phase_resume",
        )
        assert service._repo.claim_operation(placeholder) is True

        result = service.resume_phase(run_id="run-1", phase="exploration", request=req)

        assert result.status == "rejected"
        # The dispatch (engine resume / on_resume) NEVER ran: the claim gated it.
        assert handler.resume_calls == 0

    def test_invalid_resume_trigger_stores_no_operation_or_side_effects(
        self,
        tmp_path: Path,
        served_service: tuple[ControlPlaneRuntimeService, str, dict[str, object]],
    ) -> None:
        """PAUSED + invalid trigger -> rejected, NO stored op, on_resume not run (M3)."""
        service, _base_url, overrides = served_service
        handler = _PauseThenCompleteHandler()
        overrides["exploration"] = handler
        project_dir = tmp_path / "proj"
        project_dir.mkdir()
        _install_project(project_dir)
        story_id = "CLIREST-006"
        _persist_ctx(project_dir, story_id, route=StoryMode.EXPLORATION)
        _arrange_paused_exploration(service, project_dir, story_id)

        req = _req(
            project_dir,
            story_id,
            "resume",
            detail={"resume_trigger": "typo-not-a-trigger"},
        )
        result = service.resume_phase(run_id="run-1", phase="exploration", request=req)

        assert result.status == "rejected"
        assert result.operation_kind == "phase_resume"
        assert result.edge_bundle is None
        # No terminal operation was stored for the invalid-trigger resume (the
        # claim was released; a retry re-evaluates).
        # AG3-140: _load_existing_operation now takes (request, operation_kind,
        # phase); assert "no stored operation" directly against the repository (a
        # released/rejected claim leaves NO row).
        assert service._repo.load_operation(req.op_id) is None
        # The invalid trigger is caught by the engine BEFORE on_resume runs.
        assert handler.resume_calls == 0

    def test_failed_resume_after_on_resume_stores_no_operation(
        self,
        tmp_path: Path,
        served_service: tuple[ControlPlaneRuntimeService, str, dict[str, object]],
    ) -> None:
        """Valid trigger but on_resume FAILS -> rejected, no stored op (M3, post-handler)."""
        service, _base_url, overrides = served_service
        handler = _PauseThenFailHandler()
        overrides["exploration"] = handler
        project_dir = tmp_path / "proj"
        project_dir.mkdir()
        _install_project(project_dir)
        story_id = "CLIREST-007"
        _persist_ctx(project_dir, story_id, route=StoryMode.EXPLORATION)
        _arrange_paused_exploration(service, project_dir, story_id)

        req = _req(
            project_dir, story_id, "resume", detail={"resume_trigger": "design_approved"}
        )
        result = service.resume_phase(run_id="run-1", phase="exploration", request=req)

        assert result.status == "rejected"
        assert result.operation_kind == "phase_resume"
        assert result.edge_bundle is None
        # A failed resume is not a committed control-plane operation.
        # AG3-140: _load_existing_operation now takes (request, operation_kind,
        # phase); assert "no stored operation" directly against the repository (a
        # released/rejected claim leaves NO row).
        assert service._repo.load_operation(req.op_id) is None
        # on_resume DID run this time (valid trigger), unlike the invalid-trigger case.
        assert handler.resume_calls == 1

    def test_successful_resume_does_not_rematerialize_start_side_effects(
        self,
        tmp_path: Path,
        served_service: tuple[ControlPlaneRuntimeService, str, dict[str, object]],
    ) -> None:
        """A successful resume commits ONE phase_resume op but NO new binding/lock/events (N1)."""
        service, _base_url, overrides = served_service
        handler = _PauseThenCompleteHandler()
        overrides["exploration"] = handler
        project_dir = tmp_path / "proj"
        project_dir.mkdir()
        _install_project(project_dir)
        story_id = "CLIREST-008"
        _persist_ctx(project_dir, story_id, route=StoryMode.EXPLORATION)
        _arrange_paused_exploration(service, project_dir, story_id)

        project_key = project_dir.name
        # Snapshot the run's guard regime + activation-event counts BEFORE resume.
        lock_before = service._repo.load_lock(
            project_key, story_id, "run-1", "story_execution"
        )
        binding_before = service._repo.load_binding("sess-1")
        assert lock_before is not None and lock_before.status == "ACTIVE"
        assert binding_before is not None
        created_before = _count_events(
            project_key, "run-1", EventType.SESSION_RUN_BINDING_CREATED
        )
        activated_before = _count_events(
            project_key, "run-1", EventType.STORY_EXECUTION_REGIME_ACTIVATED
        )

        req = _req(
            project_dir, story_id, "resume", detail={"resume_trigger": "design_approved"}
        )
        result = service.resume_phase(run_id="run-1", phase="exploration", request=req)

        # (a) exactly one committed phase_resume op is persisted (op_id record).
        assert result.status == "committed"
        assert result.operation_kind == "phase_resume"
        stored = service._repo.load_operation(req.op_id)
        assert stored is not None and stored.operation_kind == "phase_resume"
        # The bundle MIRRORS the still-ACTIVE story-execution regime (read, no write).
        assert result.edge_bundle is not None
        assert result.edge_bundle.session is not None
        assert result.edge_bundle.lock is not None
        assert result.edge_bundle.lock.status == "ACTIVE"

        # (b) NO new binding / lock reactivation and NO new activation events.
        lock_after = service._repo.load_lock(
            project_key, story_id, "run-1", "story_execution"
        )
        binding_after = service._repo.load_binding("sess-1")
        assert lock_after is not None
        assert lock_after.activated_at == lock_before.activated_at
        assert lock_after.binding_version == lock_before.binding_version
        assert binding_after is not None
        assert binding_after.binding_version == binding_before.binding_version
        assert (
            _count_events(project_key, "run-1", EventType.SESSION_RUN_BINDING_CREATED)
            == created_before
        )
        assert (
            _count_events(project_key, "run-1", EventType.STORY_EXECUTION_REGIME_ACTIVATED)
            == activated_before
        )


@pytest.mark.integration
class TestResumeHandshakeServerPath:
    """N2: the NEW resume server path is handshake-gated (426 without, 2xx with)."""

    def test_resume_route_without_handshake_header_is_426(
        self,
        tmp_path: Path,
        served_service: tuple[ControlPlaneRuntimeService, str, dict[str, object]],
    ) -> None:
        """A resume POST without the version handshake fails closed 426 at the route."""
        from agentkit.backend.exceptions import ControlPlaneApiError

        _service, base_url, _overrides = served_service
        project_dir = tmp_path / "proj"
        project_dir.mkdir()
        _install_project(project_dir)
        story_id = "CLIREST-009"
        _persist_ctx(project_dir, story_id, route=StoryMode.EXPLORATION)

        # A transport with NO bound skill-bundle omits ``X-AK3-Skill-Bundle`` -> the
        # handshake middleware refuses the mutation with 426 BEFORE routing.
        transport = HttpsJsonTransport(base_url=base_url, skill_bundle_version=None)
        req = _req(
            project_dir, story_id, "resume", detail={"resume_trigger": "design_approved"}
        )
        with pytest.raises(ControlPlaneApiError) as exc_info:
            transport.send(
                method="POST",
                path=f"/v1/projects/{project_dir.name}/story-runs/run-1/phases/exploration/resume",
                payload=req.model_dump(mode="json"),
            )
        assert exc_info.value.http_status == 426
        assert exc_info.value.error_code == "upgrade_required"
