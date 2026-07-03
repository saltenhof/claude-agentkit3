"""E2E NO-STUB for the native ``create-story`` agent surface (AG3-114, AC3+AC4).

This is the AG3-114 core criterion. It drives the REAL deployed target-project
tool (``bundles/target_project/tools/agentkit/projectedge.py``) ``create-story``
subcommand end-to-end THROUGH the production HTTP router:

    tool create-story
      -> REAL StoryCreationReconciler.reconcile_only_from_inputs (FK-21 §21.4)
      -> self-validating ReconciliationEvidence
      -> REAL ProjectEdgeClient.create_story (real HttpsJsonTransport over a
         real localhost socket)
      -> REAL ControlPlaneApplication router (real BaseHTTPRequestHandler) +
         TenantScopeMiddleware on the tenant-scoped route
         POST /v1/projects/{project_key}/stories
      -> REAL StoryContextRoutes + StoryService + the non-bypassable fail-closed
         evidence enforcement
      -> a story persisted as the canonical truth with a BACKEND-allocated id.

Codex R2 finding #1: the create path now genuinely routes THROUGH the production
``ControlPlaneApplication`` (the real router + the real ``BaseHTTPRequestHandler``
on a real socket, reached by the real ``HttpsJsonTransport`` — exactly like the
correlation-transport test), NOT a direct ``StoryContextRoutes.handle_post()``
call. The bare ``/v1/stories`` route is intentionally NOT exposed by the
production app (it 404s); the client targets the tenant-scoped
``/v1/projects/{project_key}/stories`` route that the app actually dispatches.

NOTHING in the create path is a mock of the boundary, the router, the
reconciliation or the evidence: the socket, the handler, the router, the
tenant-scope middleware, the route, the service, in-memory persistence +
idempotency, the fail-closed reconciliation gate, the evidence model and the
affinity derivation all run for real. Fakes live ONLY at the genuine external
edge (the Weaviate adapter + the LLM evaluator) — the mocks-exception of
CLAUDE.md.

Covered:
* AC3/AC4 positive: a real create-story run creates a story (backend-allocated
  id, canonical truth) THROUGH the real router with NO GitHub call.
* AC4 idempotency: a repeat with the same op_id returns the SAME story (no
  duplicate) — the service-side Regel #5 replay over the real router.
* A real CONFLICT candidate adjudicated: PASS proceeds / FAIL blocks-and-records.
* Regel #7: the SAME correlation id is adopted+echoed on success AND on error.
* AC2/AC4 negative: a Weaviate outage during reconciliation fails closed (stable
  error contract on stderr, non-zero exit) and persists NOTHING.
* Missing-evidence route negative (a forged body without the reconciliation
  block) is rejected fail-closed by the REAL route gate through the real router.
* Malformed-LLM-output negative: the create-time adjudicator fails closed with
  ``conflict_adjudication_unavailable`` (no traceback, no dummy verdict).
* AC5: no ``gh issue create`` / ``gh project`` / ``gh api graphql`` in the path.
"""

from __future__ import annotations

import importlib.util
import json
import sys
import threading
from http import HTTPStatus
from http.server import HTTPServer
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from agentkit.backend.config.models import (
    SUPPORTED_CONFIG_VERSION,
    Features,
    PipelineConfig,
    ProjectConfig,
    RepositoryConfig,
    VectorDbConfig,
)
from agentkit.backend.control_plane_http.app import (
    ControlPlaneApplication,
    ControlPlaneApplicationRoutes,
    _build_handler,
)
from agentkit.backend.control_plane_http.tenant_scope import TenantScopeMiddleware
from agentkit.backend.exceptions import ControlPlaneApiError
from agentkit.backend.project_management.entities import Project, ProjectConfiguration
from agentkit.backend.state_backend.store.inflight_idempotency_guard import (
    InMemoryInflightIdempotencyGuard,
)
from agentkit.backend.story_context_manager.errors import (
    ForbiddenError,
    IdempotencyMismatchError,
    ReconciliationEvidenceMissingError,
    StoryProjectNotFoundError,
    StoryValidationError,
)
from agentkit.backend.story_context_manager.http.routes import StoryContextRoutes
from agentkit.backend.story_context_manager.service import StoryService
from agentkit.backend.story_context_manager.story_repository import InMemoryStoryRepository
from agentkit.backend.story_creation.create_flow import StoryCreationReconciler
from agentkit.backend.verify_system.llm_evaluator.roles import LlmVerdict, ReviewerRole
from agentkit.backend.verify_system.llm_evaluator.structured_evaluator import (
    StructuredEvaluatorError,
)
from agentkit.harness_client.projectedge import (
    HttpsJsonTransport,
    LocalEdgePublisher,
    ProjectEdgeClient,
)
from agentkit.integration_clients.vectordb import StorySearchHit, VectorDbUnavailableError

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping
    from types import ModuleType

_TOOL_PATH = (
    Path(__file__).resolve().parents[3]
    / "src"
    / "agentkit"
    / "bundles"
    / "target_project"
    / "tools"
    / "agentkit"
    / "projectedge.py"
)
_PROJECT_REPOS = ["ak3-backend", "ak3-frontend"]


def _load_tool() -> ModuleType:
    """Load the REAL deployed tool module from its on-disk resource path."""
    spec = importlib.util.spec_from_file_location(
        "ak3_create_story_tool_under_test", _TOOL_PATH
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


# ---------------------------------------------------------------------------
# External-edge fakes ONLY (Weaviate adapter + LLM evaluator)
# ---------------------------------------------------------------------------


class _FakeAdapter:
    def __init__(
        self, hits: list[StorySearchHit], *, raise_search: bool = False
    ) -> None:
        self._hits = hits
        self._raise = raise_search

    def story_search(
        self,
        query: str,
        *,
        search_mode: str = "hybrid",
        project_id: str,
        limit: int = 20,
    ) -> list[StorySearchHit]:
        del query, search_mode, project_id, limit
        if self._raise:
            raise VectorDbUnavailableError("weaviate down")
        return self._hits


class _FakeResult:
    def __init__(self, verdict: LlmVerdict) -> None:
        self.verdict = verdict


class _FakeEvaluator:
    """Fake stage-2 evaluator at the genuine LLM edge (mocks exception).

    When ``raise_malformed`` is set it raises the SAME
    :class:`StructuredEvaluatorError` the real ``StructuredEvaluator`` raises for
    malformed / schema-invalid model output, so the adjudicator's fail-closed
    wrapping is exercised end-to-end.
    """

    def __init__(
        self, verdict: LlmVerdict, *, raise_malformed: bool = False
    ) -> None:
        self._verdict = verdict
        self._raise_malformed = raise_malformed

    def evaluate(
        self,
        role: ReviewerRole,
        bundle: object,
        previous_findings: object,
        qa_cycle_round: int,
        *,
        run_id: str | None = None,
    ) -> _FakeResult:
        # ``run_id`` is accepted (the real ``StructuredEvaluator.evaluate`` takes it
        # as a keyword) so this fake can stand in BOTH as the reconciler's direct
        # ``ConflictEvaluatorPort`` (called without ``run_id``) AND as the
        # adjudicator's internal ``StructuredEvaluator`` (called with ``run_id``).
        del role, bundle, previous_findings, qa_cycle_round, run_id
        if self._raise_malformed:
            raise StructuredEvaluatorError(
                "LLM response unparseable after 2 attempts (FK-11 §11.4.4)"
            )
        return _FakeResult(self._verdict)


# ---------------------------------------------------------------------------
# Real StoryService + project repo behind the real router
# ---------------------------------------------------------------------------


class _InMemoryProjectRepository:
    def __init__(self) -> None:
        self._projects = {
            "ak3": Project(
                key="ak3",
                name="AgentKit 3",
                story_id_prefix="AK3",
                configuration=ProjectConfiguration(
                    repo_url="",
                    default_branch="main",
                    default_worker_count=2,
                    repositories=list(_PROJECT_REPOS),
                ),
            ),
        }

    def get(self, key: str) -> Project | None:
        return self._projects.get(key)

    def list(self, *, include_archived: bool = False) -> list[Project]:
        del include_archived
        return list(self._projects.values())

    def save(self, project: Project) -> None:
        self._projects[project.key] = project


def _project_config() -> ProjectConfig:
    return ProjectConfig(
        project_key="ak3",
        project_name="AgentKit 3",
        repositories=[
            RepositoryConfig(name="ak3-backend", path="services/api"),
            RepositoryConfig(name="ak3-frontend", path="apps/web"),
        ],
        story_types=["concept"],
        pipeline=PipelineConfig(
            config_version=SUPPORTED_CONFIG_VERSION,
            features=Features(multi_llm=False),
            # host/port present so the (unused-in-test) real factory branch is
            # satisfiable; the test injects a reconciler with a fake adapter.
            vectordb=VectorDbConfig(host="weaviate.local", port=8080),
        ),  # type: ignore[call-arg]
    )


def _service() -> StoryService:
    return StoryService(
        story_repository=InMemoryStoryRepository(),
        project_repository=_InMemoryProjectRepository(),
        idempotency_guard=InMemoryInflightIdempotencyGuard(),
        event_emitter=lambda *_: None,
    )


def _build_app(svc: StoryService) -> ControlPlaneApplication:
    """Build the REAL ControlPlaneApplication wired to the in-memory service.

    The story routes are wired to ``svc`` (in-memory persistence + idempotency)
    and the tenant-scope middleware to the in-memory project repo, so the
    production router + middleware run for real WITHOUT a state backend. Nothing
    in the router/route/service/middleware is stubbed.
    """
    return ControlPlaneApplication(
        routes=ControlPlaneApplicationRoutes(
            story_routes=StoryContextRoutes(story_service=svc),
        ),
        story_service=svc,
        tenant_scope_middleware=TenantScopeMiddleware(
            repository=_InMemoryProjectRepository(),  # type: ignore[arg-type]
        ),
    )


class _RecordingTransport:
    """Records (sent, echoed) X-Correlation-Id while delegating to the REAL one.

    This is NOT a stub of the transport: every ``send`` is forwarded to the real
    :class:`HttpsJsonTransport` over the real socket; the wrapper only OBSERVES the
    sent header and the echoed ``correlation_id`` so the test can assert Regel #7
    (the SAME id is adopted+echoed on success AND error).
    """

    def __init__(self, base_url: str) -> None:
        self._inner = HttpsJsonTransport(base_url=base_url)
        #: (sent X-Correlation-Id, echoed correlation_id) per call.
        self.correlation_exchange: list[tuple[str | None, str | None]] = []

    def send(
        self,
        *,
        method: str,
        path: str,
        payload: Mapping[str, object] | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> dict[str, object]:
        sent = headers.get("X-Correlation-Id") if headers else None
        try:
            data = self._inner.send(
                method=method, path=path, payload=payload, headers=headers
            )
        except ControlPlaneApiError as exc:
            self.correlation_exchange.append((sent, exc.correlation_id))
            raise
        self.correlation_exchange.append(
            (sent, str(data.get("correlation_id")) if data.get("correlation_id") else None)
        )
        return data


@pytest.fixture()
def booted_app(
    request: pytest.FixtureRequest,
) -> tuple[str, StoryService, list[_RecordingTransport]]:
    """Boot the REAL ControlPlaneApplication on a localhost HTTP socket.

    Returns the base URL, the shared in-memory ``StoryService`` (so the test can
    assert the canonical truth) and a sink collecting the recording transports
    the client factory builds (for the Regel #7 correlation assertions).
    """
    svc = _service()
    app = _build_app(svc)
    server = HTTPServer(("127.0.0.1", 0), _build_handler(app))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    host, port = server.server_address
    base_url = f"http://{host}:{port}"

    def _shutdown() -> None:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)

    request.addfinalizer(_shutdown)
    return base_url, svc, []


def _reconciler_factory(
    *,
    raise_search: bool = False,
    hits: list[StorySearchHit] | None = None,
    verdict: LlmVerdict = LlmVerdict.PASS,
    raise_malformed: bool = False,
) -> Callable[[ProjectConfig], StoryCreationReconciler]:
    def factory(project_config: ProjectConfig) -> StoryCreationReconciler:
        return StoryCreationReconciler(
            adapter=_FakeAdapter(hits or [], raise_search=raise_search),  # type: ignore[arg-type]
            evaluator=_FakeEvaluator(verdict, raise_malformed=raise_malformed),  # type: ignore[arg-type]
            vectordb_config=VectorDbConfig(
                similarity_threshold=0.7, max_llm_candidates=5
            ),
            project_config=project_config,
        )

    return factory


def _client_factory(
    base_url: str,
    *,
    transport_sink: list[_RecordingTransport],
) -> Callable[[Path], ProjectEdgeClient]:
    def factory(project_root: Path) -> ProjectEdgeClient:
        transport = _RecordingTransport(base_url)
        transport_sink.append(transport)
        return ProjectEdgeClient(
            transport=transport,  # type: ignore[arg-type]
            publisher=LocalEdgePublisher(project_root=project_root),
        )

    return factory


def _write_project_config(project_root: Path) -> None:
    """Write a minimal real project config the tool's ``load_project_config`` reads."""
    config_dir = project_root / ".agentkit" / "config"
    config_dir.mkdir(parents=True, exist_ok=True)
    cfg = _project_config().model_dump(mode="json")
    (config_dir / "project.yaml").write_text(json.dumps(cfg), encoding="utf-8")


def _argv(
    project_root: Path, *, op_id: str, title: str = "Add native create"
) -> list[str]:
    return [
        "--project-root",
        str(project_root),
        "create-story",
        "--project-key",
        "ak3",
        "--title",
        title,
        "--type",
        "implementation",
        "--repo",
        "ak3-backend",
        "--story-body",
        "## Betroffene Dateien\n- services/api/x.py\n",
        "--op-id",
        op_id,
    ]


# ---------------------------------------------------------------------------
# AC3 / AC4 positive: real create-story creates a backend-allocated story
# ---------------------------------------------------------------------------


def test_create_story_tool_creates_story_via_real_router_no_github(
    booted_app: tuple[str, StoryService, list[_RecordingTransport]],
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """AC4 NO-STUB: tool -> reconcile -> evidence -> real router (tenant-scoped
    POST /v1/projects/ak3/stories) creates a canonical story with NO GitHub."""
    base_url, svc, transports = booted_app
    tool = _load_tool()
    _write_project_config(tmp_path)

    exit_code = tool.main(
        _argv(tmp_path, op_id="op-e2e-1"),
        client_factory=_client_factory(base_url, transport_sink=transports),
        reconciler_factory=_reconciler_factory(),
    )

    assert exit_code == 0
    out = capsys.readouterr()
    summary = json.loads(out.out)
    # Backend-allocated canonical id (never client-assigned).
    assert summary["story_id"] == "AK3-001"
    assert summary["status"] == "Backlog"
    assert summary["project_key"] == "ak3"
    assert summary["correlation_id"].startswith("corr-")
    assert summary["op_id"] == "op-e2e-1"
    # Regel #7: the real router ADOPTED and ECHOED the same X-Correlation-Id the
    # client sent on success (no divergent server-minted req-<uuid>).
    sent, echoed = transports[0].correlation_exchange[0]
    assert sent == summary["correlation_id"]
    assert echoed == sent
    # The story is the canonical truth in the control plane.
    stories = svc.list_stories("ak3")
    assert len(stories) == 1
    assert stories[0].story_display_id == "AK3-001"
    # NO GitHub anywhere in the create path.
    assert "gh issue" not in out.out
    assert "gh project" not in out.out


def test_create_story_tool_bare_v1_stories_is_not_exposed(
    booted_app: tuple[str, StoryService, list[_RecordingTransport]],
) -> None:
    """The bare /v1/stories POST is NOT exposed by the production app (404).

    This pins the route correction (Codex finding #1): only the tenant-scoped
    /v1/projects/{key}/stories dispatches story POSTs; a bare /v1/stories POST is
    a 404 through the real router, so the client MUST target the tenant-scoped
    route (which it now does).
    """
    base_url, svc, _ = booted_app
    transport = HttpsJsonTransport(base_url=base_url)

    with pytest.raises(ControlPlaneApiError) as exc_info:
        transport.send(
            method="POST",
            path="/v1/stories",
            payload={"project_key": "ak3", "title": "x"},
            headers={"X-Correlation-Id": "corr-bare"},
        )

    assert exc_info.value.http_status == HTTPStatus.NOT_FOUND
    assert svc.list_stories("ak3") == []


# ---------------------------------------------------------------------------
# A real CONFLICT candidate adjudicated: PASS proceeds / FAIL records
# ---------------------------------------------------------------------------


def test_create_story_tool_above_threshold_conflict_pass_proceeds(
    booted_app: tuple[str, StoryService, list[_RecordingTransport]],
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The wired adjudicator's PASS over an above-threshold candidate PROCEEDS."""
    base_url, svc, transports = booted_app
    tool = _load_tool()
    _write_project_config(tmp_path)
    hits = [StorySearchHit(story_id="AK3-009", title="prior", score=0.92, snippet="x")]

    exit_code = tool.main(
        _argv(tmp_path, op_id="op-conflict-pass"),
        client_factory=_client_factory(base_url, transport_sink=transports),
        reconciler_factory=_reconciler_factory(hits=hits, verdict=LlmVerdict.PASS),
    )

    assert exit_code == 0
    out = json.loads(capsys.readouterr().out)
    assert out["story_id"] == "AK3-001"
    recon = out["reconciliation"]
    assert recon["total_hits"] == 1
    assert recon["above_threshold"] == 1
    assert recon["sent_to_llm"] == 1
    assert recon["llm_conflicts"] == 0
    assert recon["search_mode"] == "hybrid"
    assert len(svc.list_stories("ak3")) == 1


def test_create_story_tool_above_threshold_conflict_fail_records_conflict(
    booted_app: tuple[str, StoryService, list[_RecordingTransport]],
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The wired adjudicator's FAIL over an above-threshold candidate is HONOURED."""
    base_url, svc, transports = booted_app
    tool = _load_tool()
    _write_project_config(tmp_path)
    hits = [StorySearchHit(story_id="AK3-009", title="dup", score=0.95, snippet="x")]

    exit_code = tool.main(
        _argv(tmp_path, op_id="op-conflict-fail"),
        client_factory=_client_factory(base_url, transport_sink=transports),
        reconciler_factory=_reconciler_factory(hits=hits, verdict=LlmVerdict.FAIL),
    )

    assert exit_code == 0
    out = json.loads(capsys.readouterr().out)
    recon = out["reconciliation"]
    assert recon["above_threshold"] == 1
    assert recon["sent_to_llm"] == 1
    # The adjudicator's FAIL is honoured (recorded), NOT a blanket fail-close.
    assert recon["llm_conflicts"] == 1
    assert len(svc.list_stories("ak3")) == 1


def test_create_story_tool_no_pool_configured_fails_closed_truthfully(
    booted_app: tuple[str, StoryService, list[_RecordingTransport]],
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """No create-time pool + above-threshold candidate => truthful fail-closed.

    The factory falls back to the ``FailClosedConflictEvaluator``; an above-
    threshold candidate is BLOCKED with the TRUTHFUL
    ``conflict_adjudication_unavailable`` (NOT a VectorDB outage), persisting
    NOTHING. This drives the REAL runtime-factory fallback.
    """
    from agentkit.backend.story_creation.runtime_factory import (
        FailClosedConflictEvaluator,
    )

    base_url, svc, transports = booted_app
    tool = _load_tool()
    _write_project_config(tmp_path)
    hits = [StorySearchHit(story_id="AK3-009", title="dup", score=0.95, snippet="x")]

    def factory(project_config: ProjectConfig) -> StoryCreationReconciler:
        return StoryCreationReconciler(
            adapter=_FakeAdapter(hits),  # type: ignore[arg-type]
            evaluator=FailClosedConflictEvaluator(),
            vectordb_config=VectorDbConfig(
                similarity_threshold=0.7, max_llm_candidates=5
            ),
            project_config=project_config,
        )

    exit_code = tool.main(
        _argv(tmp_path, op_id="op-no-pool"),
        client_factory=_client_factory(base_url, transport_sink=transports),
        reconciler_factory=factory,
    )

    assert exit_code == tool._CREATE_FAILCLOSED_EXIT
    err = json.loads(capsys.readouterr().err)
    assert err["error_code"] == "conflict_adjudication_unavailable"
    assert svc.list_stories("ak3") == []


def test_create_story_tool_malformed_llm_output_fails_closed(
    booted_app: tuple[str, StoryService, list[_RecordingTransport]],
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Malformed LLM output => fail-closed ``conflict_adjudication_unavailable``.

    Codex finding #3: a real above-threshold candidate reaches stage 2, where the
    create-time LLM returns malformed / schema-invalid output (the evaluator
    raises ``StructuredEvaluatorError``). The adjudicator wraps it in
    ``CreateTimeConflictAdjudicationError`` (fail-closed), the tool maps it to the
    stable ``conflict_adjudication_unavailable`` code with a NON-zero exit — NEVER
    a traceback and NEVER a dummy/PASS verdict. NOTHING is persisted.

    This wires the REAL ``CreateTimeConflictAdjudicator`` over a fake LLM evaluator
    (the genuine LLM edge) that raises the SAME ``StructuredEvaluatorError`` the
    real ``StructuredEvaluator`` raises for unparseable output.
    """
    from agentkit.backend.story_creation.conflict_adjudicator import (
        CreateTimeConflictAdjudicator,
    )

    base_url, svc, transports = booted_app
    tool = _load_tool()
    _write_project_config(tmp_path)
    hits = [StorySearchHit(story_id="AK3-009", title="dup", score=0.95, snippet="x")]

    # Wire the REAL adjudicator; replace ONLY its internal StructuredEvaluator with
    # a fake at the genuine LLM edge that raises the malformed-output error, so the
    # adjudicator's fail-closed wrapping runs for real.
    def factory(project_config: ProjectConfig) -> StoryCreationReconciler:
        adjudicator = CreateTimeConflictAdjudicator.__new__(
            CreateTimeConflictAdjudicator
        )
        adjudicator._evaluator = _FakeEvaluator(  # type: ignore[attr-defined]
            LlmVerdict.PASS, raise_malformed=True
        )
        return StoryCreationReconciler(
            adapter=_FakeAdapter(hits),  # type: ignore[arg-type]
            evaluator=adjudicator,
            vectordb_config=VectorDbConfig(
                similarity_threshold=0.7, max_llm_candidates=5
            ),
            project_config=project_config,
        )

    exit_code = tool.main(
        _argv(tmp_path, op_id="op-malformed"),
        client_factory=_client_factory(base_url, transport_sink=transports),
        reconciler_factory=factory,
    )

    assert exit_code == tool._CREATE_FAILCLOSED_EXIT
    err = json.loads(capsys.readouterr().err)
    assert err["error_code"] == "conflict_adjudication_unavailable"
    # Truthful: the message names the malformed-output cause, not a VectorDB outage.
    assert "malformed" in err["error"].lower()
    assert svc.list_stories("ak3") == []


# ---------------------------------------------------------------------------
# AC4 idempotency: repeat with the same op_id => same story, no duplicate
# ---------------------------------------------------------------------------


def test_create_story_tool_op_id_idempotent_no_duplicate(
    booted_app: tuple[str, StoryService, list[_RecordingTransport]],
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """AC4: a repeat with the SAME op_id returns the SAME story (Regel #5)."""
    base_url, svc, transports = booted_app
    tool = _load_tool()
    _write_project_config(tmp_path)
    client_factory = _client_factory(base_url, transport_sink=transports)
    reconciler_factory = _reconciler_factory()

    first_code = tool.main(
        _argv(tmp_path, op_id="op-dup"),
        client_factory=client_factory,
        reconciler_factory=reconciler_factory,
    )
    first = json.loads(capsys.readouterr().out)
    second_code = tool.main(
        _argv(tmp_path, op_id="op-dup"),
        client_factory=client_factory,
        reconciler_factory=reconciler_factory,
    )
    second = json.loads(capsys.readouterr().out)

    assert first_code == 0
    assert second_code == 0
    assert first["story_id"] == second["story_id"]
    # No duplicate: exactly one canonical story.
    assert len(svc.list_stories("ak3")) == 1


# ---------------------------------------------------------------------------
# AC2 / AC4 negative: Weaviate outage fails closed, persists nothing
# ---------------------------------------------------------------------------


def test_create_story_tool_weaviate_outage_fails_closed(
    booted_app: tuple[str, StoryService, list[_RecordingTransport]],
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """AC2/AC4: a Weaviate outage blocks creation fail-closed with a stable error
    contract on stderr and a non-zero exit; NOTHING is persisted."""
    base_url, svc, transports = booted_app
    tool = _load_tool()
    _write_project_config(tmp_path)

    exit_code = tool.main(
        _argv(tmp_path, op_id="op-down"),
        client_factory=_client_factory(base_url, transport_sink=transports),
        reconciler_factory=_reconciler_factory(raise_search=True),
    )

    assert exit_code == tool._CREATE_FAILCLOSED_EXIT
    err = capsys.readouterr().err
    error = json.loads(err)
    assert error["error_code"] == "vectordb_unavailable"
    assert "correlation_id" in error
    # Fail-closed: no story reached the canonical store.
    assert svc.list_stories("ak3") == []


def test_create_story_tool_unknown_project_rejected_through_router(
    booted_app: tuple[str, StoryService, list[_RecordingTransport]],
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """AC4 negative: an UNKNOWN project key is rejected through the REAL router.

    The tenant-scope middleware (project does not exist) returns a 404
    ``project_not_found`` BEFORE the story route, so NOTHING is persisted and the
    SAME correlation id is echoed on the error response (Regel #7).
    """
    base_url, svc, transports = booted_app
    tool = _load_tool()
    _write_project_config(tmp_path)

    argv = _argv(tmp_path, op_id="op-unknown-project")
    idx = argv.index("--project-key")
    argv[idx + 1] = "does-not-exist"

    exit_code = tool.main(
        argv,
        client_factory=_client_factory(base_url, transport_sink=transports),
        reconciler_factory=_reconciler_factory(),
    )

    assert exit_code == tool._CREATE_FAILCLOSED_EXIT
    err = json.loads(capsys.readouterr().err)
    assert err["error_code"] == "project_not_found"
    assert err["op_id"] == "op-unknown-project"
    # Regel #7: the router echoed the SAME X-Correlation-Id on the ERROR response.
    sent, echoed = transports[0].correlation_exchange[0]
    assert echoed == sent
    assert err["correlation_id"] == sent
    assert svc.list_stories("ak3") == []


def test_create_story_route_rejects_missing_reconciliation_block(
    booted_app: tuple[str, StoryService, list[_RecordingTransport]],
) -> None:
    """AC2/AC5 NO-STUB: a raw POST WITHOUT a ``reconciliation`` block is rejected
    fail-closed by the REAL route gate THROUGH the real router (422
    ``reconciliation_evidence_missing``); NOTHING is persisted.

    This pins the non-bypassable evidence enforcement on the tenant-scoped route,
    over the real socket/router, without going through the client (which always
    attaches real evidence). A caller-forged body that simply omits the evidence
    must never persist a story.
    """
    base_url, svc, _ = booted_app
    transport = HttpsJsonTransport(base_url=base_url)

    raw_body_without_evidence = {
        "op_id": "op-no-evidence",
        "project_key": "ak3",
        "title": "no evidence supplied",
        "type": "implementation",
        "repos": ["ak3-backend"],
        # NO ``reconciliation`` key at all.
    }

    with pytest.raises(ControlPlaneApiError) as exc_info:
        transport.send(
            method="POST",
            path="/v1/projects/ak3/stories",
            payload=raw_body_without_evidence,
            headers={"X-Correlation-Id": "corr-no-evidence"},
        )

    assert exc_info.value.http_status == HTTPStatus.UNPROCESSABLE_ENTITY
    assert exc_info.value.error_code == "reconciliation_evidence_missing"
    # Fail-closed BEFORE persistence: no story reached the canonical store.
    assert svc.list_stories("ak3") == []


# ---------------------------------------------------------------------------
# AC5: no GitHub create surface is imported/used by the tool create path
# ---------------------------------------------------------------------------


def test_create_story_tool_source_has_no_github_create_calls() -> None:
    """AC5 assertion: the deployed tool invokes no GitHub create surface."""
    import ast

    tree = ast.parse(_TOOL_PATH.read_text(encoding="utf-8"))
    string_consts = [
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant) and isinstance(node.value, str)
    ]
    docstrings = {
        ast.get_docstring(node, clean=False)
        for node in ast.walk(tree)
        if isinstance(
            node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)
        )
    }
    executable_strings = [s for s in string_consts if s not in docstrings]
    joined = "\n".join(executable_strings)
    assert "gh issue create" not in joined
    assert "gh project" not in joined
    assert "gh api graphql" not in joined
    imported = {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    } | {
        node.module
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module is not None
    }
    assert "subprocess" not in imported
    assert not any("github" in (mod or "") for mod in imported)


def test_route_maps_service_exceptions_to_stable_error_codes() -> None:
    """AC4 contract: each fail-closed exception maps to its stable wire error_code."""
    from agentkit.backend.story_context_manager.http.routes import _ERROR_CODE_MAP

    expected: dict[type[Exception], tuple[HTTPStatus, str]] = {
        ReconciliationEvidenceMissingError: (
            HTTPStatus.UNPROCESSABLE_ENTITY,
            "reconciliation_evidence_missing",
        ),
        StoryValidationError: (HTTPStatus.BAD_REQUEST, "validation_failed"),
        StoryProjectNotFoundError: (HTTPStatus.BAD_REQUEST, "validation_failed"),
        ForbiddenError: (HTTPStatus.FORBIDDEN, "forbidden"),
        IdempotencyMismatchError: (HTTPStatus.CONFLICT, "idempotency_mismatch"),
    }
    for exc_type, (status, code) in expected.items():
        assert _ERROR_CODE_MAP[exc_type] == (status, code)
