"""Integration test: ExplorationPhaseHandler.on_enter full mandate flow (AG3-047).

Drives the PRODUCTIVE ``build_exploration_phase_handler`` (real mandate
classification + scope detector + impact checker + fine-design skeleton + design
freeze + telemetry + the state-backed DeclaredImpactReader) against a real sqlite
backend and the productive ``ArtifactManager`` for all four mandate-class paths:

* SCOPE_EXPLOSION -> ESCALATED (recommend story split), no freeze;
* IMPACT_ESCALATION -> ESCALATED (architecture review), no freeze;
* FINE_DESIGN (converged) + TRIVIAL -> review -> APPROVED -> freeze -> COMPLETED.

The ONLY doubled seam is the LLM transport inside the injected review
(``ScriptedLlmClient`` -- the LLM grenze); the declared change_impact is read
from a REAL persisted ``Story`` so the composition-root DeclaredImpactReader
wiring is exercised end-to-end.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import pytest
from tests.exploration_change_frame_fixture import (
    EXAMPLE_CREATED_AT,
    example_change_frame,
)
from tests.phase_state_factory import make_phase_state
from tests.unit.exploration.review.scripted import (
    ScriptedLlmClient,
    build_real_sink,
    build_scripted_evaluator,
)

from agentkit.artifacts import (
    ArtifactEnvelope,
    EnvelopeStatus,
    Producer,
    ProducerId,
    ProducerType,
)
from agentkit.bootstrap.composition_root import (
    build_artifact_manager,
    build_exploration_phase_handler,
)
from agentkit.core_types import ArtifactClass
from agentkit.core_types.qa_artifact_names import CHANGE_FRAME_FILE
from agentkit.exploration.change_frame import (
    AffectedBuildingBlocks,
    ChangeFrame,
    ContractChanges,
    OpenPoints,
)
from agentkit.exploration.register import (
    EXPLORATION_ENTWURF_PRODUCER,
    EXPLORATION_ENTWURF_STAGE,
)
from agentkit.exploration.review.design_review import DesignReviewRunner
from agentkit.exploration.review.doc_fidelity import DocFidelityChecker
from agentkit.exploration.review.review import ExplorationReview
from agentkit.installer.paths import resolve_qa_story_dir
from agentkit.phase_state_store.models import FlowExecution
from agentkit.pipeline_engine.phase_envelope.store import PhaseEnvelopeStore
from agentkit.pipeline_engine.phase_executor import (
    ExplorationPayload,
    PhaseState,
    PhaseStatus,
)
from agentkit.state_backend.config import ALLOW_SQLITE_ENV, STATE_BACKEND_ENV
from agentkit.state_backend.store import (
    load_execution_events,
    reset_backend_cache_for_tests,
    save_flow_execution,
)
from agentkit.state_backend.store.exploration_change_frame_repository import (
    StateBackendExplorationChangeFrameAdapter,
)
from agentkit.state_backend.store.story_repository import StateBackendStoryRepository
from agentkit.story_context_manager.models import StoryContext
from agentkit.story_context_manager.story_model import (
    ChangeImpact,
    Story,
    WireStoryType,
)
from agentkit.story_context_manager.types import StoryMode, StoryType
from agentkit.telemetry.events import EventType

if TYPE_CHECKING:
    from collections.abc import Generator
    from pathlib import Path

_STORY_ID = "AG3-047"
_RUN_ID = "55555555-5555-4555-8555-555555555555"


@pytest.fixture(autouse=True)
def sqlite_backend_env(
    monkeypatch: pytest.MonkeyPatch,
) -> Generator[None, None, None]:
    monkeypatch.setenv(STATE_BACKEND_ENV, "sqlite")
    monkeypatch.setenv(ALLOW_SQLITE_ENV, "1")
    reset_backend_cache_for_tests()
    yield
    reset_backend_cache_for_tests()


def _story_dir(tmp_path: Path) -> Path:
    story_dir = tmp_path / "stories" / _STORY_ID
    story_dir.mkdir(parents=True, exist_ok=True)
    _write_manifest_index(tmp_path)
    return story_dir


def _write_manifest_index(project_root: Path) -> None:
    guardrails = project_root / "_guardrails"
    docs = project_root / "concepts"
    guardrails.mkdir(parents=True, exist_ok=True)
    docs.mkdir(parents=True, exist_ok=True)
    (docs / "trading-architecture.md").write_text(
        "# Trading Architecture\nAdapter pattern is allowed.\n",
        encoding="utf-8",
    )
    (guardrails / "manifest-index.json").write_text(
        json.dumps(
            {
                "documents": [
                    {
                        "path": "concepts/trading-architecture.md",
                        "scope": "architecture",
                        "modules": ["*", "one"],
                        "story_types": ["implementation"],
                        "tags": ["design", "*"],
                    }
                ]
            },
            sort_keys=True,
        ),
        encoding="utf-8",
    )


def _ctx(story_dir: Path) -> StoryContext:
    return StoryContext(
        project_key="test-project",
        story_id=_STORY_ID,
        story_type=StoryType.IMPLEMENTATION,
        execution_route=StoryMode.EXPLORATION,
        title="Mandate classification flow",
        project_root=story_dir.parent.parent,
    )


def _bind_flow(story_dir: Path) -> None:
    save_flow_execution(
        story_dir,
        FlowExecution(
            project_key="test-project",
            story_id=_STORY_ID,
            run_id=_RUN_ID,
            flow_id="exploration",
            level="story",
            owner="pipeline_engine",
            status="IN_PROGRESS",
        ),
    )


def _save_story(story_dir: Path, *, declared: ChangeImpact) -> None:
    StateBackendStoryRepository(story_dir).save(
        Story(
            project_key="test-project",
            story_number=47,
            story_display_id=_STORY_ID,
            title="Mandate classification flow",
            story_type=WireStoryType.IMPLEMENTATION,
            participating_repos=["repo-a"],
            change_impact=declared,
        )
    )


def _persist_frame(manager: object, story_dir: Path, frame: ChangeFrame) -> None:
    """Persist an arbitrary change-frame the way the AG3-055 worker would."""
    envelope = ArtifactEnvelope(
        schema_version="3.0",
        story_id=_STORY_ID,
        run_id=_RUN_ID,
        stage=EXPLORATION_ENTWURF_STAGE,
        attempt=1,
        producer=Producer(
            type=ProducerType.WORKER,
            name=EXPLORATION_ENTWURF_PRODUCER,
            id=ProducerId(f"{EXPLORATION_ENTWURF_PRODUCER}-{_RUN_ID}"),
        ),
        started_at=EXAMPLE_CREATED_AT,
        finished_at=EXAMPLE_CREATED_AT,
        status=EnvelopeStatus.PASS,
        artifact_class=ArtifactClass.ENTWURF,
        payload=frame.model_dump(mode="json"),
    )
    manager.write(envelope)  # type: ignore[attr-defined]
    StateBackendExplorationChangeFrameAdapter(manager).write_change_frame_file(  # type: ignore[arg-type]
        story_dir, story_id=_STORY_ID, run_id=_RUN_ID, frame=frame
    )


def _state() -> PhaseState:
    return make_phase_state(
        story_id=_STORY_ID,
        phase="exploration",
        status=PhaseStatus.IN_PROGRESS,
        payload=ExplorationPayload(),
    )


def _passing_review(ctx: StoryContext, story_dir: Path) -> ExplorationReview:
    """Build a REAL ExplorationReview with a scripted (PASS) LLM transport."""
    client = ScriptedLlmClient(doc_fidelity=["PASS"], semantic_review=["PASS"])
    evaluator = build_scripted_evaluator(ctx, client)
    sink = build_real_sink(story_dir)
    return ExplorationReview(
        stage1_doc_fidelity=DocFidelityChecker(evaluator, sink, story_context=ctx),
        stage2a_design_review=DesignReviewRunner(evaluator, sink),
        stage2b_design_challenge=None,
        artifact_manager=build_artifact_manager(story_dir),
    )


def _trivial_frame() -> ChangeFrame:
    return example_change_frame(story_id=_STORY_ID, run_id=_RUN_ID).model_copy(
        update={
            "affected_building_blocks": AffectedBuildingBlocks(affected=["one"]),
            "open_points": OpenPoints(
                decided=["adapter pattern"], assumptions=[], approval_needed=[]
            ),
        }
    )


def _fine_design_frame() -> ChangeFrame:
    return example_change_frame(story_id=_STORY_ID, run_id=_RUN_ID).model_copy(
        update={
            "affected_building_blocks": AffectedBuildingBlocks(affected=["one"]),
            "open_points": OpenPoints(
                decided=[],
                assumptions=[],
                approval_needed=["broker streaming contract unresolved"],
            ),
        }
    )


def _exploding_frame() -> ChangeFrame:
    return example_change_frame(story_id=_STORY_ID, run_id=_RUN_ID).model_copy(
        update={
            "affected_building_blocks": AffectedBuildingBlocks(
                affected=[f"m{i}" for i in range(8)],
            ),
            "contract_changes": ContractChanges(
                interfaces=["a", "b"],
                data_model=["c", "d"],
                events=["e"],
                external_integrations=["f"],
            ),
        }
    )


def _impact_frame() -> ChangeFrame:
    return example_change_frame(story_id=_STORY_ID, run_id=_RUN_ID).model_copy(
        update={
            "affected_building_blocks": AffectedBuildingBlocks(
                affected=["m1", "m2", "m3", "m4"],
            ),
            "contract_changes": ContractChanges(
                interfaces=["a", "b"], data_model=["c"], events=["d"]
            ),
        }
    )


def _frozen_file_exists(story_dir: Path) -> bool:
    path = resolve_qa_story_dir(story_dir, story_id=_STORY_ID) / CHANGE_FRAME_FILE
    if not path.is_file():
        return False
    return bool(json.loads(path.read_text(encoding="utf-8")).get("frozen"))


def test_scope_explosion_escalates(tmp_path: Path) -> None:
    """Klasse 3 -> ESCALATED with the story-split reaction; no freeze."""
    story_dir = _story_dir(tmp_path)
    _bind_flow(story_dir)
    _save_story(story_dir, declared=ChangeImpact.ARCHITECTURE_IMPACT)
    manager = build_artifact_manager(story_dir)
    _persist_frame(manager, story_dir, _exploding_frame())
    ctx = _ctx(story_dir)
    handler = build_exploration_phase_handler(
        story_dir, review=_passing_review(ctx, story_dir)
    )

    result = handler.on_enter(ctx, PhaseEnvelopeStore.make_fresh_envelope(_state()))

    assert result.status is PhaseStatus.ESCALATED
    assert result.suggested_reaction == "scope_explosion_detected: recommend story split"
    assert _frozen_file_exists(story_dir) is False
    events = {
        e.event_type for e in load_execution_events(story_dir, story_id=_STORY_ID)
    }
    assert EventType.MANDATE_CLASSIFICATION in events
    assert EventType.SCOPE_EXPLOSION_CHECK in events
    assert EventType.IMPACT_EXCEEDANCE_CHECK in events


def test_impact_escalation_escalates(tmp_path: Path) -> None:
    """Klasse 4 -> ESCALATED with the architecture-review reaction; no freeze."""
    story_dir = _story_dir(tmp_path)
    _bind_flow(story_dir)
    _save_story(story_dir, declared=ChangeImpact.LOCAL)
    manager = build_artifact_manager(story_dir)
    _persist_frame(manager, story_dir, _impact_frame())
    ctx = _ctx(story_dir)
    handler = build_exploration_phase_handler(
        story_dir, review=_passing_review(ctx, story_dir)
    )

    result = handler.on_enter(ctx, PhaseEnvelopeStore.make_fresh_envelope(_state()))

    assert result.status is PhaseStatus.ESCALATED
    assert result.suggested_reaction == "impact_exceedance: architecture review needed"
    assert _frozen_file_exists(story_dir) is False


def test_trivial_approves_and_freezes(tmp_path: Path) -> None:
    """Klasse 1 (trivial) -> review APPROVED -> freeze -> COMPLETED."""
    story_dir = _story_dir(tmp_path)
    _bind_flow(story_dir)
    _save_story(story_dir, declared=ChangeImpact.ARCHITECTURE_IMPACT)
    manager = build_artifact_manager(story_dir)
    _persist_frame(manager, story_dir, _trivial_frame())
    ctx = _ctx(story_dir)
    handler = build_exploration_phase_handler(
        story_dir, review=_passing_review(ctx, story_dir)
    )

    result = handler.on_enter(ctx, PhaseEnvelopeStore.make_fresh_envelope(_state()))

    assert result.status is PhaseStatus.COMPLETED
    assert _frozen_file_exists(story_dir) is True


def test_fine_design_non_reachability_fails_closed_no_freeze(tmp_path: Path) -> None:
    """Klasse 2 (fine-design) non-reachability -> FAILED (D4), no freeze.

    D4-Override (FK-25 §25.5.4 Z. 642-650): non-reachability is an OPERATIONAL
    error, NOT a pause. Here the fail-closed :class:`_UnavailableFineDesignEvaluator`
    is INJECTED explicitly via ``fine_design_evaluator`` (the justified hub-absent
    config) so the test stays deterministic + offline; after the bounded retry a
    class-2 frame ends ``status: FAILED`` (cause recorded in
    AttemptRecord.failure_cause by the engine) -- NOT ESCALATED, NOT PAUSED, NO
    infra_unavailable triple. The change-frame is NOT frozen (NO ERROR BYPASSING).
    """
    from agentkit.bootstrap.composition_root import _UnavailableFineDesignEvaluator
    from agentkit.exploration.mandate.fine_design import FineDesignSubprocess

    story_dir = _story_dir(tmp_path)
    _bind_flow(story_dir)
    _save_story(story_dir, declared=ChangeImpact.ARCHITECTURE_IMPACT)
    manager = build_artifact_manager(story_dir)
    _persist_frame(manager, story_dir, _fine_design_frame())
    ctx = _ctx(story_dir)
    handler = build_exploration_phase_handler(
        story_dir,
        review=_passing_review(ctx, story_dir),
        fine_design_evaluator=_UnavailableFineDesignEvaluator(),
    )
    # The injected hub-absent stand-in is what the shell drives.
    assert isinstance(
        handler._fine_design,  # noqa: SLF001 -- assert the wired evaluator
        FineDesignSubprocess,
    )

    result = handler.on_enter(ctx, PhaseEnvelopeStore.make_fresh_envelope(_state()))

    assert result.status is PhaseStatus.FAILED
    # D4: no infra_unavailable / PAUSED / escalation_class anywhere.
    assert result.yield_status is None
    assert result.suggested_reaction is None
    assert any("fine_design_quorum_unreachable" in err for err in result.errors)
    assert _frozen_file_exists(story_dir) is False
    # The mandate classification telemetry still fired before the failure.
    events = {
        e.event_type for e in load_execution_events(story_dir, story_id=_STORY_ID)
    }
    assert EventType.MANDATE_CLASSIFICATION in events


def test_productive_wiring_uses_hub_fine_design_evaluator_by_default(
    tmp_path: Path,
) -> None:
    """ANTI-DEAD-PATH (AG3-097 review Blocker #1): the REAL build path uses the hub.

    The canonical productive ``build_exploration_phase_handler`` (no injected
    evaluator) MUST assemble the concrete :class:`HubFineDesignEvaluator` over the
    real :class:`HubClient` transport -- NOT the ``_UnavailableFineDesignEvaluator``
    stand-in. Without this guard the hub fine-design would be dead code in
    production (the AG3-072 dead-path failure mode). Asserts the assembled
    handler's fine-design evaluator IS the hub evaluator wired with the real hub
    client + the productive prompt builder + the LLM-delegating convergence judge.
    """
    from agentkit.bootstrap.composition_root import _UnavailableFineDesignEvaluator
    from agentkit.exploration.mandate.hub_fine_design import HubFineDesignEvaluator
    from agentkit.exploration.mandate.hub_fine_design_wiring import (
        ChangeFrameFineDesignPromptBuilder,
        LlmConvergenceJudge,
    )
    from agentkit.multi_llm_hub.client import HubClient

    story_dir = _story_dir(tmp_path)
    ctx = _ctx(story_dir)
    handler = build_exploration_phase_handler(
        story_dir, review=_passing_review(ctx, story_dir)
    )

    evaluator = handler._fine_design._evaluator  # noqa: SLF001 -- anti-dead-path
    assert isinstance(evaluator, HubFineDesignEvaluator)
    assert not isinstance(evaluator, _UnavailableFineDesignEvaluator)
    # The hub-backed evaluator drives the REAL transport + productive collaborators.
    assert isinstance(evaluator._client, HubClient)  # noqa: SLF001
    assert isinstance(  # noqa: SLF001
        evaluator._prompt_builder, ChangeFrameFineDesignPromptBuilder
    )
    assert isinstance(evaluator._judge, LlmConvergenceJudge)  # noqa: SLF001


def test_productive_hub_fine_design_run_drives_the_hub_path(tmp_path: Path) -> None:
    """The hub-backed evaluator REALLY drives the hub on a class-2 frame run.

    Asserts the anti-dead-path end-to-end: the productive handler's hub evaluator
    is exercised over a fake-but-production-faithful hub (boundary-only double).
    The discussion acquires ChatGPT + a mandatory second advisor and SENDS the
    real round prompt over the hub -- proving the build path drives the hub, not a
    placeholder that never touches it. The convergence judge here is wired to the
    default fail-closed LLM client, so the run ends FAILED (D4) -- but only AFTER
    the hub advisors were really acquired + sent to.
    """
    from tests.unit.exploration.mandate.test_hub_fine_design import _FakeHub

    from agentkit.bootstrap.composition_root import build_hub_fine_design_evaluator

    story_dir = _story_dir(tmp_path)
    _bind_flow(story_dir)
    _save_story(story_dir, declared=ChangeImpact.ARCHITECTURE_IMPACT)
    manager = build_artifact_manager(story_dir)
    _persist_frame(manager, story_dir, _fine_design_frame())
    ctx = _ctx(story_dir)

    hub = _FakeHub(available=("chatgpt", "qwen"))
    # Real productive hub-evaluator builder, only the hub transport boundary is a
    # production-faithful fake (MOCKS exception). The judge defaults to the
    # fail-closed LLM client -> the run drives the hub then fails closed (D4).
    evaluator = build_hub_fine_design_evaluator(story_dir, hub_client=hub)
    handler = build_exploration_phase_handler(
        story_dir,
        review=_passing_review(ctx, story_dir),
        fine_design_evaluator=evaluator,
    )

    result = handler.on_enter(ctx, PhaseEnvelopeStore.make_fresh_envelope(_state()))

    # The hub WAS driven: the mandatory advisors were acquired AND a real send
    # happened over the hub (>= 1 send per advisor) before the verdict failed closed.
    assert hub.granted == ("chatgpt", "qwen")
    assert all(
        hub.send_counts.get(advisor, 0) >= 1 for advisor in ("chatgpt", "qwen")
    )
    # The verdict failed closed (no FK-11 pool) -> D4 FAILED, no fabricated freeze.
    assert result.status is PhaseStatus.FAILED
    assert result.yield_status is None
    assert _frozen_file_exists(story_dir) is False
