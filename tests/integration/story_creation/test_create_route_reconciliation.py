"""FIX-1: the AUTHORITATIVE production create path enforces reconciliation.

These tests drive the REAL production entry — the ``StoryContextRoutes`` HTTP
adapter on top of a real ``StoryService`` with real (in-memory) persistence and
idempotency — NOT the standalone reconciler. They prove that POST /v1/stories is
NON-BYPASSABLE (FK-21 §21.4 / §21.12 / §21.13):

* AC1 / §21.4.3: a Weaviate outage during the skill reconciliation means no
  ``weaviate_ready`` evidence can be produced; the create is BLOCKED fail-closed
  and NOTHING is persisted.
* A bare create with NO reconciliation evidence is rejected fail-closed (422),
  so a story can never be created here while silently skipping the Weaviate
  check / affinity feed. The route has NO in-body escape hatch (AG3-068 round-3):
  the Zone-2/admin exemption (FK-21 §21.13.2) calls ``StoryService`` in-process,
  not this agent-facing route.
* AC6 / §21.9: the repo-affinity ``participating_repos`` carried by the evidence
  lands on the persisted story via the production route.
* AC5 / §21.12: the grounded ``vectordb_conflict_resolved`` flag is derived from
  the evidence (a free caller value cannot override a non-conflict outcome).

Mocks/doubles are limited to the Weaviate adapter + LLM evaluator boundaries
(mocks exception); the StoryService, persistence, idempotency, the route's
fail-closed gate, the flag rule and the affinity derivation run for real.
"""

from __future__ import annotations

import json
from http import HTTPStatus

import pytest

from agentkit.backend.config.models import (
    SUPPORTED_CONFIG_VERSION,
    Features,
    PipelineConfig,
    ProjectConfig,
    RepositoryConfig,
    VectorDbConfig,
)
from agentkit.backend.project_management.entities import Project, ProjectConfiguration
from agentkit.backend.story_context_manager.http.routes import (
    StoryContextRoutes,
    StoryRouteResponse,
)
from agentkit.backend.story_context_manager.idempotency import (
    InMemoryIdempotencyKeyRepository,
)
from agentkit.backend.story_context_manager.service import StoryService
from agentkit.backend.story_context_manager.story_repository import InMemoryStoryRepository
from agentkit.backend.story_creation.create_flow import StoryCreationReconciler
from agentkit.backend.verify_system.llm_evaluator.roles import LlmVerdict, ReviewerRole
from agentkit.integration_clients.vectordb import StorySearchHit, VectorDbUnavailableError

CORR = "corr-fix1"
_PROJECT_REPOS = ["ak3-backend", "ak3-frontend"]


# ---------------------------------------------------------------------------
# Real StoryService wired behind the real route adapter
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


def _service() -> StoryService:
    return StoryService(
        story_repository=InMemoryStoryRepository(),
        project_repository=_InMemoryProjectRepository(),
        idempotency_repository=InMemoryIdempotencyKeyRepository(),
        event_emitter=lambda *_: None,
    )


def _routes(svc: StoryService) -> StoryContextRoutes:
    return StoryContextRoutes(story_service=svc)


def _body(resp: StoryRouteResponse | None) -> dict[str, object]:
    assert resp is not None
    result = json.loads(resp.body)
    assert isinstance(result, dict)
    return result


# ---------------------------------------------------------------------------
# Boundary doubles (Weaviate adapter + LLM evaluator only)
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
    def __init__(self, verdict: LlmVerdict) -> None:
        self._verdict = verdict

    def evaluate(
        self,
        role: ReviewerRole,
        bundle: object,
        previous_findings: object,
        qa_cycle_round: int,
    ) -> _FakeResult:
        del role, bundle, previous_findings, qa_cycle_round
        return _FakeResult(self._verdict)


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
        ),  # type: ignore[call-arg]
    )


def _reconciler(
    svc: StoryService,
    *,
    hits: list[StorySearchHit] | None = None,
    raise_search: bool = False,
    verdict: LlmVerdict = LlmVerdict.PASS,
) -> StoryCreationReconciler:
    return StoryCreationReconciler(
        story_service=svc,
        adapter=_FakeAdapter(hits or [], raise_search=raise_search),  # type: ignore[arg-type]
        evaluator=_FakeEvaluator(verdict),
        vectordb_config=VectorDbConfig(similarity_threshold=0.7, max_llm_candidates=5),
        project_config=_project_config(),
    )


def _hit(story_id: str, score: float) -> StorySearchHit:
    return StorySearchHit(
        story_id=story_id, title=f"T-{story_id}", score=score, snippet="s"
    )


def _create_body(**overrides: object) -> dict[str, object]:
    body: dict[str, object] = {
        "op_id": "op-create",
        "project_key": "ak3",
        "title": "Add a runtime reconciliation",
        "type": "implementation",
        "repos": ["ak3-backend"],
    }
    body.update(overrides)
    return body


# ---------------------------------------------------------------------------
# AC1 / §21.13: bare create with NO evidence is fail-closed (NON-BYPASSABLE)
# ---------------------------------------------------------------------------


def test_production_route_blocks_bare_create_without_reconciliation() -> None:
    """NEGATIVE: POST /v1/stories without evidence/grant is rejected 422 and
    persists NOTHING — the route cannot create while skipping reconciliation."""
    svc = _service()
    routes = _routes(svc)
    resp = routes.handle_post("/v1/stories", _create_body(), CORR)
    assert resp is not None
    assert resp.status_code == HTTPStatus.UNPROCESSABLE_ENTITY
    assert _body(resp)["error_code"] == "reconciliation_evidence_missing"
    # Fail-closed: no story persisted.
    assert svc.list_stories("ak3") == []


def test_production_route_blocks_weaviate_outage_via_real_flow() -> None:
    """AC1/§21.4.3: a Weaviate outage means the reconciler cannot produce
    evidence; the create raises and NOTHING is persisted (production flow)."""
    svc = _service()
    reconciler = _reconciler(svc, raise_search=True)
    with pytest.raises(VectorDbUnavailableError):
        reconciler.create_story(
            _input_for_reconciler(),
            story_body="## Betroffene Dateien\n- services/api/x.py\n",
            op_id="op-down",
        )
    assert svc.list_stories("ak3") == []


def test_production_route_rejects_invalid_evidence_weaviate_not_ready() -> None:
    """NEGATIVE: an attestation claiming weaviate_ready=False is rejected
    fail-closed (a Weaviate outage cannot be attested as a successful create)."""
    svc = _service()
    routes = _routes(svc)
    bad_evidence = {
        "weaviate_ready": False,
        "total_hits": 0,
        "hits_above_threshold": 0,
        "hits_classified_conflict": 0,
        "threshold_value": 0.7,
        "verdict": "PASS",
    }
    resp = routes.handle_post(
        "/v1/stories", _create_body(reconciliation=bad_evidence), CORR
    )
    assert resp is not None
    assert resp.status_code == HTTPStatus.UNPROCESSABLE_ENTITY
    assert _body(resp)["error_code"] == "reconciliation_evidence_missing"
    assert svc.list_stories("ak3") == []


def test_production_route_rejects_non_object_reconciliation() -> None:
    """NEGATIVE: a 'reconciliation' that is not a JSON object is rejected
    fail-closed (defensive type check before model validation)."""
    svc = _service()
    routes = _routes(svc)
    resp = routes.handle_post(
        "/v1/stories", _create_body(reconciliation="not-an-object"), CORR
    )
    assert resp is not None
    assert resp.status_code == HTTPStatus.UNPROCESSABLE_ENTITY
    assert _body(resp)["error_code"] == "reconciliation_evidence_missing"
    assert svc.list_stories("ak3") == []


def test_production_route_rejects_inconsistent_conflict_counter() -> None:
    """NEGATIVE: a FAIL verdict that claims 0 classified conflicts is rejected
    (the evidence model is self-validating)."""
    svc = _service()
    routes = _routes(svc)
    inconsistent = {
        "weaviate_ready": True,
        "total_hits": 5,
        "hits_above_threshold": 3,
        "hits_classified_conflict": 0,  # inconsistent with FAIL
        "threshold_value": 0.7,
        "verdict": "FAIL",
    }
    resp = routes.handle_post(
        "/v1/stories", _create_body(reconciliation=inconsistent), CORR
    )
    assert resp is not None
    assert resp.status_code == HTTPStatus.UNPROCESSABLE_ENTITY
    assert _body(resp)["error_code"] == "reconciliation_evidence_missing"


# ---------------------------------------------------------------------------
# AC6 / §21.9: affinity lands in participating_repos via the production route
# ---------------------------------------------------------------------------


def test_production_route_creates_with_evidence_and_affinity() -> None:
    """POSITIVE: a valid evidence block (carrying the repo-affinity result)
    creates the story and lands participating_repos on the persisted record."""
    svc = _service()
    routes = _routes(svc)
    evidence = {
        "weaviate_ready": True,
        "total_hits": 4,
        "hits_above_threshold": 2,
        "hits_classified_conflict": 0,
        "threshold_value": 0.7,
        "verdict": "PASS",
        "participating_repos": ["ak3-backend", "ak3-frontend"],
    }
    resp = routes.handle_post(
        "/v1/stories",
        _create_body(repos=["ak3-backend"], reconciliation=evidence),
        CORR,
    )
    assert resp is not None
    assert resp.status_code == HTTPStatus.CREATED
    stories = svc.list_stories("ak3")
    assert len(stories) == 1
    # Affinity from the evidence overrides the caller-supplied single repo.
    assert stories[0].participating_repos == ["ak3-backend", "ak3-frontend"]
    assert stories[0].vectordb_conflict_resolved is False


# ---------------------------------------------------------------------------
# AC5 / §21.12: the grounded flag is derived from the evidence (not free input)
# ---------------------------------------------------------------------------


def test_production_route_grounds_conflict_flag_true_on_adapted_fail() -> None:
    """A FAIL conflict that was adapted sets vectordb_conflict_resolved=True on
    the persisted story via the production route."""
    svc = _service()
    routes = _routes(svc)
    evidence = {
        "weaviate_ready": True,
        "total_hits": 3,
        "hits_above_threshold": 1,
        "hits_classified_conflict": 1,
        "threshold_value": 0.7,
        "verdict": "FAIL",
        "story_was_adapted": True,
    }
    resp = routes.handle_post(
        "/v1/stories", _create_body(reconciliation=evidence), CORR
    )
    assert resp is not None
    assert resp.status_code == HTTPStatus.CREATED
    stories = svc.list_stories("ak3")
    assert len(stories) == 1
    assert stories[0].vectordb_conflict_resolved is True


def test_production_route_free_flag_cannot_override_pass_outcome() -> None:
    """A caller cannot set vectordb_conflict_resolved=True without a grounded
    FAIL+adaptation: the route projects the flag from the evidence (PASS=>False),
    overriding the free body value."""
    svc = _service()
    routes = _routes(svc)
    evidence = {
        "weaviate_ready": True,
        "total_hits": 2,
        "hits_above_threshold": 1,
        "hits_classified_conflict": 0,
        "threshold_value": 0.7,
        "verdict": "PASS",
        "story_was_adapted": True,  # irrelevant on PASS
    }
    resp = routes.handle_post(
        "/v1/stories",
        # Free body asserts True; the grounded evidence (PASS) wins -> False.
        _create_body(reconciliation=evidence, vectordb_conflict_resolved=True),
        CORR,
    )
    assert resp is not None
    assert resp.status_code == HTTPStatus.CREATED
    stories = svc.list_stories("ak3")
    assert stories[0].vectordb_conflict_resolved is False


# ---------------------------------------------------------------------------
# §21.13.2: the route has NO in-body escape hatch (design A — non-bypassable)
# ---------------------------------------------------------------------------


def test_production_route_has_no_magic_string_bypass() -> None:
    """NEGATIVE / REGRESSION (AG3-068 round-3): the agent-facing route exposes no
    in-body authorization escape hatch. A body field whose value is the old grant
    marker is plain story content, NOT an authorization — without reconciliation
    evidence the create is still blocked fail-closed and nothing is persisted.

    FK-21 §21.13.2 routes the Zone-2/admin exemption to a DIFFERENT entry: those
    callers invoke ``StoryService`` / ``StoryCreationReconciler`` in-process, not
    this route. A body-settable token is never acceptable authorization here.
    """
    svc = _service()
    routes = _routes(svc)
    resp = routes.handle_post(
        "/v1/stories",
        # Even the exact former magic string carries zero authority now: it is
        # just an unknown body field, the create is gated on evidence only.
        _create_body(direct_create_grant="create-userstory-direct"),
        CORR,
    )
    assert resp is not None
    assert resp.status_code == HTTPStatus.UNPROCESSABLE_ENTITY
    assert _body(resp)["error_code"] == "reconciliation_evidence_missing"
    assert svc.list_stories("ak3") == []


def test_production_route_zone2_admin_uses_service_directly_not_this_route() -> None:
    """POSITIVE (FK-21 §21.13.2): the Zone-2/admin direct-create exemption goes
    through the authoritative ``StoryService`` IN-PROCESS, bypassing the
    agent-facing HTTP reconciliation gate entirely — the route is not its entry.

    This is the design-A counterpart to the bypass-free route: there is a real,
    separate, code-level path for the documented exemption, so removing the HTTP
    escape hatch does not strand any legitimate caller.
    """
    svc = _service()
    # No HTTP route, no reconciliation evidence, no grant string: the admin/Zone-2
    # caller holds the StoryService directly and persists the story.
    from agentkit.backend.story_context_manager.story_model import (
        CreateStoryInput,
        WireStoryType,
    )

    story = svc.create_story(
        CreateStoryInput(
            project_key="ak3",
            title="Zone-2 follow-up story",
            story_type=WireStoryType.IMPLEMENTATION,
            repos=["ak3-backend"],
        ),
        op_id="op-zone2-direct",
        correlation_id=CORR,
    )
    assert story is not None
    assert len(svc.list_stories("ak3")) == 1


# ---------------------------------------------------------------------------
# Helper: build a reconciler CreateStoryInput (for the outage-via-flow test)
# ---------------------------------------------------------------------------


def _input_for_reconciler() -> object:
    from agentkit.backend.story_context_manager.story_model import (
        CreateStoryInput,
        WireStoryType,
    )

    return CreateStoryInput(
        project_key="ak3",
        title="Add a runtime reconciliation",
        story_type=WireStoryType.IMPLEMENTATION,
        repos=["ak3-backend"],
        module="services/api",
    )
