"""Integration tests for the authoritative story-creation flow (AG3-068).

Proves that the deterministic reconciliation runtime is WIRED into the
authoritative create path (``StoryService.create_story``), not dead/isolated:

* AC1 / §21.4.3: a Weaviate outage BLOCKS create fail-closed via the real flow.
* AC5 / §21.12: a stage-2 ``FAIL`` + adaptation sets ``vectordb_conflict_resolved``
  ``True`` on the persisted story via the real flow.
* AC6 / §21.9: the repo-affinity result lands in ``participating_repos`` on the
  persisted story via the real flow.

Mocks live ONLY at the Weaviate adapter and LLM evaluator boundaries
(mocks exception). The StoryService, persistence (in-memory repo), idempotency,
threshold filter, flag rule, affinity derivation and telemetry run for real.
"""

from __future__ import annotations

import pytest

from agentkit.config.models import (
    SUPPORTED_CONFIG_VERSION,
    Features,
    PipelineConfig,
    ProjectConfig,
    RepositoryConfig,
    VectorDbConfig,
)
from agentkit.integrations.vectordb import StorySearchHit, VectorDbUnavailableError
from agentkit.project_management.entities import Project, ProjectConfiguration
from agentkit.story_context_manager.idempotency import (
    InMemoryIdempotencyKeyRepository,
)
from agentkit.story_context_manager.service import StoryService
from agentkit.story_context_manager.story_model import (
    CreateStoryInput,
    StoryStatus,
    WireStoryType,
)
from agentkit.story_context_manager.story_repository import InMemoryStoryRepository
from agentkit.story_creation.create_flow import StoryCreationReconciler
from agentkit.telemetry.emitters import MemoryEmitter
from agentkit.telemetry.events import EventType
from agentkit.verify_system.llm_evaluator.roles import LlmVerdict, ReviewerRole

# ---------------------------------------------------------------------------
# Boundary doubles (Weaviate adapter + LLM evaluator only)
# ---------------------------------------------------------------------------


class _FakeAdapter:
    """Weaviate adapter double; returns hits or raises a fail-closed outage."""

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
    """Structured-evaluator double over the role-based evaluate surface."""

    def __init__(self, verdict: LlmVerdict) -> None:
        self._verdict = verdict
        self.calls: list[ReviewerRole] = []

    def evaluate(
        self,
        role: ReviewerRole,
        bundle: object,
        previous_findings: object,
        qa_cycle_round: int,
    ) -> _FakeResult:
        del bundle, previous_findings, qa_cycle_round
        self.calls.append(role)
        return _FakeResult(self._verdict)


# ---------------------------------------------------------------------------
# Real StoryService + ProjectConfig fixtures
# ---------------------------------------------------------------------------

_PROJECT_REPOS = ["ak3-backend", "ak3-frontend"]


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
    """ProjectConfig whose repo NAMES match the Project allow-list but whose
    PATHS are distinct (so affinity genuinely exercises path-matching)."""
    return ProjectConfig(
        project_key="ak3",
        project_name="AgentKit 3",
        repositories=[
            RepositoryConfig(name="ak3-backend", path="services/api"),
            RepositoryConfig(name="ak3-frontend", path="apps/web"),
        ],
        # "concept" avoids the code-producing sonarqube-stanza requirement; the
        # affinity logic under test is story-type agnostic.
        story_types=["concept"],
        pipeline=PipelineConfig(
            config_version=SUPPORTED_CONFIG_VERSION,
            features=Features(multi_llm=False),
        ),  # type: ignore[call-arg]
    )


def _story_service() -> StoryService:
    return StoryService(
        story_repository=InMemoryStoryRepository(),
        project_repository=_InMemoryProjectRepository(),
        idempotency_repository=InMemoryIdempotencyKeyRepository(),
        event_emitter=lambda *_: None,
    )


def _reconciler(
    *,
    hits: list[StorySearchHit] | None = None,
    raise_search: bool = False,
    verdict: LlmVerdict = LlmVerdict.PASS,
    emitter: MemoryEmitter | None = None,
    service: StoryService | None = None,
) -> StoryCreationReconciler:
    return StoryCreationReconciler(
        story_service=service or _story_service(),
        adapter=_FakeAdapter(hits or [], raise_search=raise_search),  # type: ignore[arg-type]
        evaluator=_FakeEvaluator(verdict),
        vectordb_config=VectorDbConfig(similarity_threshold=0.7, max_llm_candidates=5),
        project_config=_project_config(),
        event_emitter=emitter,
    )


def _input(
    *, repos: list[str] | None = None, module: str = "services/api"
) -> CreateStoryInput:
    return CreateStoryInput(
        project_key="ak3",
        title="Add a runtime reconciliation",
        story_type=WireStoryType.IMPLEMENTATION,
        repos=repos or ["ak3-backend"],
        module=module,
    )


def _hit(story_id: str, score: float) -> StorySearchHit:
    return StorySearchHit(story_id=story_id, title=f"T-{story_id}", score=score, snippet="s")


# ---------------------------------------------------------------------------
# AC1: Weaviate outage blocks create fail-closed (via the real flow)
# ---------------------------------------------------------------------------


def test_weaviate_outage_blocks_create_via_real_flow() -> None:
    """NEGATIVE: a Weaviate outage propagates and NO story is persisted."""
    service = _story_service()
    reconciler = _reconciler(raise_search=True, service=service)
    with pytest.raises(VectorDbUnavailableError):
        reconciler.create_story(
            _input(),
            story_body="## Betroffene Dateien\n- services/api/x.py\n",
            op_id="op-down",
        )
    # Fail-closed: the create was blocked BEFORE any persistence.
    assert service.list_stories("ak3") == []


# ---------------------------------------------------------------------------
# AC5: stage-2 FAIL + adaptation sets the flag true (via the real flow)
# ---------------------------------------------------------------------------


def test_stage2_fail_and_adaptation_sets_flag_true_via_real_flow() -> None:
    body = "## Betroffene Dateien\n- services/api/main.py\n"
    reconciler = _reconciler(hits=[_hit("AK3-001", 0.95)], verdict=LlmVerdict.FAIL)
    outcome = reconciler.create_story(
        _input(),
        story_body=body,
        op_id="op-fail-adapted",
        story_was_adapted=True,
    )
    assert outcome.vectordb_conflict_resolved is True
    # The flag is persisted on the authoritative story record (no shadow field).
    assert outcome.story.vectordb_conflict_resolved is True
    assert outcome.story.status is StoryStatus.BACKLOG


def test_stage2_fail_without_adaptation_leaves_flag_false_via_real_flow() -> None:
    """NEGATIVE: a FAIL conflict NOT resolved by adapting leaves the flag False."""
    body = "## Betroffene Dateien\n- services/api/main.py\n"
    reconciler = _reconciler(hits=[_hit("AK3-001", 0.95)], verdict=LlmVerdict.FAIL)
    outcome = reconciler.create_story(
        _input(),
        story_body=body,
        op_id="op-fail-unadapted",
        story_was_adapted=False,
    )
    assert outcome.vectordb_conflict_resolved is False
    assert outcome.story.vectordb_conflict_resolved is False


def test_stage2_pass_leaves_flag_false_via_real_flow() -> None:
    body = "## Betroffene Dateien\n- services/api/main.py\n"
    reconciler = _reconciler(hits=[_hit("AK3-001", 0.95)], verdict=LlmVerdict.PASS)
    outcome = reconciler.create_story(
        _input(),
        story_body=body,
        op_id="op-pass",
        story_was_adapted=True,  # irrelevant on PASS
    )
    assert outcome.vectordb_conflict_resolved is False
    assert outcome.story.vectordb_conflict_resolved is False


# ---------------------------------------------------------------------------
# AC6: repo-affinity result lands in participating_repos (via the real flow)
# ---------------------------------------------------------------------------


def test_affinity_result_lands_in_participating_repos_via_real_flow() -> None:
    # Body lists files under BOTH configured repo path roots; affinity must
    # resolve them by NAME and feed participating_repos authoritatively.
    body = (
        "## Betroffene Dateien\n"
        "- services/api/main.py\n"
        "- services/api/util.py\n"
        "- apps/web/page.tsx\n"
    )
    # Caller supplies only one repo; affinity overrides with the derived set.
    reconciler = _reconciler()
    outcome = reconciler.create_story(
        _input(repos=["ak3-backend"]),
        story_body=body,
        op_id="op-affinity",
    )
    assert outcome.used_affinity_proposal is True
    # Hits: backend=2 (first), frontend=1 -> deterministic order.
    assert outcome.participating_repos == ("ak3-backend", "ak3-frontend")
    assert tuple(outcome.story.participating_repos) == ("ak3-backend", "ak3-frontend")


def test_no_affinity_evidence_honours_caller_repos_human_correction() -> None:
    """§21.9.2 human-correction: with no strong evidence, the caller-supplied
    repo set is honoured (no hard override)."""
    body = "# Story\n\nNo affected-files section.\n"
    reconciler = _reconciler()
    outcome = reconciler.create_story(
        # No strong-evidence paths AND a module that matches no repo path root
        # => no proposal => the caller-supplied repo set is honoured.
        _input(repos=["ak3-frontend"], module="unrelated/topic"),
        story_body=body,
        op_id="op-no-evidence",
    )
    assert outcome.used_affinity_proposal is False
    assert tuple(outcome.story.participating_repos) == ("ak3-frontend",)


def test_reconciler_produces_route_consumable_evidence() -> None:
    """AG3-068 FIX-1: the reconciler is the PRODUCER of the reconciliation
    evidence that the agent-facing create boundary requires. The produced
    evidence mirrors the reconciliation outcome (counters, grounded flag,
    affinity) so the route and the reconciler share one model (FIX-THE-MODEL)."""
    body = (
        "## Betroffene Dateien\n"
        "- services/api/main.py\n"
        "- apps/web/page.tsx\n"
    )
    reconciler = _reconciler(hits=[_hit("AK3-001", 0.95)], verdict=LlmVerdict.FAIL)
    outcome = reconciler.create_story(
        _input(),
        story_body=body,
        op_id="op-evidence",
        story_was_adapted=True,
    )
    evidence = outcome.evidence
    assert evidence.weaviate_ready is True
    assert evidence.verdict is LlmVerdict.FAIL
    assert evidence.hits_classified_conflict == 1
    # Grounded flag matches the outcome and the persisted story.
    assert evidence.vectordb_conflict_resolved is True
    assert outcome.story.vectordb_conflict_resolved is True
    # Affinity carried in the evidence matches the persisted participating_repos.
    assert evidence.participating_repos == tuple(outcome.story.participating_repos)
    # The evidence wire payload re-validates (route-consumable round-trip).
    from agentkit.story_creation.reconciliation_evidence import ReconciliationEvidence

    assert (
        ReconciliationEvidence.model_validate(evidence.model_dump())
        .vectordb_conflict_resolved
        is True
    )


def test_real_flow_emits_single_vectordb_search_event() -> None:
    """AC9 end-to-end: the wired flow emits exactly the mandatory payload."""
    emitter = MemoryEmitter()
    body = "## Betroffene Dateien\n- services/api/main.py\n"
    reconciler = _reconciler(
        hits=[_hit("AK3-001", 0.95), _hit("AK3-002", 0.4)],
        verdict=LlmVerdict.FAIL,
        emitter=emitter,
    )
    outcome = reconciler.create_story(
        _input(),
        story_body=body,
        op_id="op-telemetry",
        story_display_id="AK3-009",
    )
    events = emitter.query("AK3-009", EventType.VECTORDB_SEARCH)
    assert len(events) == 1
    assert set(events[0].payload) == {
        "total_hits",
        "hits_above_threshold",
        "hits_classified_conflict",
        "threshold_value",
    }
    assert outcome.reconciliation.total_hits == 2
