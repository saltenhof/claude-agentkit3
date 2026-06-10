"""Integration: ExplorationPhaseHandler.on_enter drives the exit-gate (AG3-046).

End-to-end over a real sqlite backend and the productive ``ArtifactManager``:
the AG3-055 worker analogue persists the FK-23 fixture change-frame, then the
handler CONSUMES it and runs the three-stage :class:`ExplorationReview`. Only the
LLM transport is doubled (``ScriptedLlmClient``); the orchestration, the
persistence and the guard are real.

Proves:
* all stages PASS -> ``COMPLETED`` + gate ``APPROVED`` (implementation released);
* Stage-2a round-limit escalation -> ``ESCALATED`` with ``suggested_reaction``,
  gate ``PENDING``, PhaseState stays ``EXPLORATION`` (no IMPLEMENTATION
  transition) -- fail-closed;
* Stage-1 FAIL -> ``ESCALATED`` + gate ``REJECTED`` -> the implementation guard
  ``exploration_gate_approved`` denies (Implementation not released).
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import pytest
from tests.exploration_change_frame_fixture import (
    EXAMPLE_RUN_ID,
    example_change_frame,
    persist_example_change_frame,
)
from tests.phase_state_factory import make_phase_state
from tests.unit.exploration.review.scripted import (
    ScriptedLlmClient,
    build_real_sink,
    build_scripted_evaluator,
)

from agentkit.bootstrap.composition_root import (
    build_artifact_manager,
    build_exploration_phase_handler,
)
from agentkit.core_types import ExplorationGateStatus, PauseReason
from agentkit.exploration.review.design_challenge import DesignChallengeRunner
from agentkit.exploration.review.design_review import DesignReviewRunner
from agentkit.exploration.review.doc_fidelity import DocFidelityChecker
from agentkit.exploration.review.review import ExplorationReview
from agentkit.phase_state_store.models import FlowExecution
from agentkit.pipeline_engine.phase_envelope.store import PhaseEnvelopeStore
from agentkit.pipeline_engine.phase_executor import (
    ExplorationPayload,
    PhaseName,
    PhaseState,
    PhaseStatus,
)
from agentkit.process.language.guards import exploration_gate_approved
from agentkit.state_backend.config import ALLOW_SQLITE_ENV, STATE_BACKEND_ENV
from agentkit.state_backend.store import (
    reset_backend_cache_for_tests,
    save_flow_execution,
)
from agentkit.state_backend.store.story_repository import StateBackendStoryRepository
from agentkit.story_context_manager.models import StoryContext
from agentkit.story_context_manager.story_model import (
    ChangeImpact,
    Story,
    WireStoryType,
)
from agentkit.story_context_manager.types import StoryMode, StoryType

if TYPE_CHECKING:
    from collections.abc import Generator
    from pathlib import Path

    from agentkit.pipeline_engine.lifecycle import HandlerResult

#: FK-02 §2.3.1: ``run_id`` is a UUID; this must match the fixture frame run id.
_RUN_ID = "11111111-1111-4111-8111-111111111111"


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
    sd = tmp_path / "stories" / "AG3-045"
    sd.mkdir(parents=True, exist_ok=True)
    _write_manifest_index(tmp_path)
    return sd


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
                        "modules": ["trading-engine", "*"],
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
        story_id="AG3-045",
        story_type=StoryType.IMPLEMENTATION,
        execution_route=StoryMode.EXPLORATION,
        title="Exploration review e2e",
        project_root=story_dir.parent.parent,
    )


def _bind_flow(story_dir: Path) -> None:
    save_flow_execution(
        story_dir,
        FlowExecution(
            project_key="test-project",
            story_id="AG3-045",
            run_id=_RUN_ID,
            flow_id="exploration",
            level="story",
            owner="pipeline_engine",
            status="IN_PROGRESS",
        ),
    )
    # AG3-047: the handler now classifies the mandate before the gate and reads
    # the story's declared change_impact (fail-closed). Persist the story with a
    # high declared impact so the Klasse-4 check never escalates -- these AG3-046
    # tests assert the GATE outcomes, not the mandate routing. The frame used by
    # ``_run`` is the TRIVIAL variant (no ``approval_needed`` open point) so the
    # mandate classifies TRIVIAL and the flow reaches the review (the productive
    # fine-design evaluator is fail-closed -- ERROR-1 -- and would otherwise
    # escalate a fine-design frame before the gate).
    StateBackendStoryRepository(story_dir).save(
        Story(
            project_key="test-project",
            story_number=45,
            story_display_id="AG3-045",
            title="Exploration review e2e",
            story_type=WireStoryType.IMPLEMENTATION,
            participating_repos=["repo-a"],
            change_impact=ChangeImpact.ARCHITECTURE_IMPACT,
        )
    )


def _state() -> PhaseState:
    return make_phase_state(
        story_id="AG3-045",
        phase="exploration",
        status=PhaseStatus.IN_PROGRESS,
        payload=ExplorationPayload(),
    )


def _review(
    ctx: StoryContext, story_dir: Path, *, doc: list[str], design: list[str]
) -> ExplorationReview:
    client = ScriptedLlmClient(doc_fidelity=doc, semantic_review=design)
    evaluator = build_scripted_evaluator(ctx, client)
    sink = build_real_sink(story_dir)
    return ExplorationReview(
        stage1_doc_fidelity=DocFidelityChecker(evaluator, sink, story_context=ctx),
        stage2a_design_review=DesignReviewRunner(evaluator, sink),
        stage2b_design_challenge=None,
        artifact_manager=build_artifact_manager(story_dir),
    )


def _persist_trivial_frame(story_dir: Path) -> None:
    """Persist a TRIVIAL variant of the example frame (no approval_needed).

    A frame with no ``open_points.approval_needed`` classifies as TRIVIAL, so the
    mandate flow proceeds straight to the review -- letting these tests assert the
    GATE outcomes without the (fail-closed) productive fine-design evaluator
    escalating first (ERROR-1).
    """
    from agentkit.artifacts import (
        ArtifactEnvelope,
        EnvelopeStatus,
        Producer,
        ProducerId,
        ProducerType,
    )
    from agentkit.core_types import ArtifactClass
    from agentkit.exploration.change_frame import OpenPoints
    from agentkit.exploration.register import (
        EXPLORATION_ENTWURF_PRODUCER,
        EXPLORATION_ENTWURF_STAGE,
    )
    from agentkit.state_backend.store.exploration_change_frame_repository import (
        StateBackendExplorationChangeFrameAdapter,
    )

    frame = example_change_frame(story_id="AG3-045", run_id=EXAMPLE_RUN_ID).model_copy(
        update={
            "open_points": OpenPoints(
                decided=["Adapter pattern instead of direct integration."],
                assumptions=["Broker API supports WebSocket streaming."],
                approval_needed=[],
            )
        }
    )
    manager = build_artifact_manager(story_dir)
    manager.write(
        ArtifactEnvelope(
            schema_version="3.0",
            story_id="AG3-045",
            run_id=_RUN_ID,
            stage=EXPLORATION_ENTWURF_STAGE,
            attempt=1,
            producer=Producer(
                type=ProducerType.WORKER,
                name=EXPLORATION_ENTWURF_PRODUCER,
                id=ProducerId(f"{EXPLORATION_ENTWURF_PRODUCER}-{_RUN_ID}"),
            ),
            started_at=frame.created_at,
            finished_at=frame.created_at,
            status=EnvelopeStatus.PASS,
            artifact_class=ArtifactClass.ENTWURF,
            payload=frame.model_dump(mode="json"),
        )
    )
    StateBackendExplorationChangeFrameAdapter(manager).write_change_frame_file(
        story_dir, story_id="AG3-045", run_id=_RUN_ID, frame=frame
    )


def _run(
    story_dir: Path, ctx: StoryContext, review: ExplorationReview
) -> HandlerResult:
    _persist_trivial_frame(story_dir)
    handler = build_exploration_phase_handler(story_dir, review=review)
    return handler.on_enter(ctx, PhaseEnvelopeStore.make_fresh_envelope(_state()))


def test_all_pass_completes_and_releases_gate(tmp_path: Path) -> None:
    sd = _story_dir(tmp_path)
    _bind_flow(sd)
    ctx = _ctx(sd)
    review = _review(ctx, sd, doc=["PASS"], design=["PASS"])

    result = _run(sd, ctx, review)

    assert result.status is PhaseStatus.COMPLETED
    payload = result.updated_state.payload
    assert isinstance(payload, ExplorationPayload)
    assert payload.gate_status is ExplorationGateStatus.APPROVED
    # The implementation guard now RELEASES (only when COMPLETED + APPROVED).
    assert exploration_gate_approved(ctx, result.updated_state).passed is True


def test_stage2a_escalation_stays_in_exploration(tmp_path: Path) -> None:
    """Escalation -> ESCALATED, gate PENDING, phase STAYS exploration."""
    sd = _story_dir(tmp_path)
    _bind_flow(sd)
    ctx = _ctx(sd)
    review = _review(ctx, sd, doc=["PASS"], design=["FAIL", "FAIL", "FAIL"])

    result = _run(sd, ctx, review)

    assert result.status is PhaseStatus.ESCALATED
    assert result.yield_status == PauseReason.AWAITING_DESIGN_REVIEW.value
    # AC9: the typed suggested_reaction carries the escalation reaction.
    assert result.suggested_reaction is not None
    state = result.updated_state
    # The story STAYS in the exploration phase -- no transition to implementation.
    assert state.phase == PhaseName.EXPLORATION
    payload = state.payload
    assert isinstance(payload, ExplorationPayload)
    assert payload.gate_status is ExplorationGateStatus.PENDING
    # The implementation guard denies (Implementation not released).
    assert exploration_gate_approved(ctx, state).passed is False


def test_stage1_fail_rejects_and_blocks_implementation(tmp_path: Path) -> None:
    """AC10: Stage-1 FAIL -> gate REJECTED -> implementation guard denies."""
    sd = _story_dir(tmp_path)
    _bind_flow(sd)
    ctx = _ctx(sd)
    review = _review(ctx, sd, doc=["FAIL"], design=[])

    result = _run(sd, ctx, review)

    assert result.status is PhaseStatus.ESCALATED
    payload = result.updated_state.payload
    assert isinstance(payload, ExplorationPayload)
    assert payload.gate_status is ExplorationGateStatus.REJECTED
    assert exploration_gate_approved(ctx, result.updated_state).passed is False


def test_stage2b_fail_rejects_and_blocks_implementation(tmp_path: Path) -> None:
    """A wired Stage-2b FAIL (stage 1+2a passed) -> ESCALATED + gate REJECTED.

    This is a pure AG3-046 GATE test: it isolates the Stage-2b challenge by
    building the handler WITHOUT the mandate classifier, so
    ``run_design_challenge`` defaults to ``True`` and Stage 2b runs (the
    mandate-gating of Stage 2b is covered by the AG3-047 mandate tests).
    """
    from agentkit.exploration.phase import (
        ExplorationConfig,
        ExplorationPhaseHandler,
    )
    from agentkit.state_backend.store.exploration_change_frame_repository import (
        StateBackendExplorationChangeFrameAdapter,
    )

    sd = _story_dir(tmp_path)
    _bind_flow(sd)
    ctx = _ctx(sd)
    client = ScriptedLlmClient(
        doc_fidelity=["PASS"], semantic_review=["PASS", "FAIL"]
    )
    evaluator = build_scripted_evaluator(ctx, client)
    sink = build_real_sink(sd)
    review = ExplorationReview(
        stage1_doc_fidelity=DocFidelityChecker(evaluator, sink, story_context=ctx),
        stage2a_design_review=DesignReviewRunner(evaluator, sink),
        stage2b_design_challenge=DesignChallengeRunner(evaluator, sink),
        artifact_manager=build_artifact_manager(sd),
    )
    _persist_trivial_frame(sd)
    adapter = StateBackendExplorationChangeFrameAdapter(build_artifact_manager(sd))
    handler = ExplorationPhaseHandler(
        change_frame_reader=adapter,
        run_scope_resolver=adapter,
        review=review,
        config=ExplorationConfig(story_dir=sd),
    )

    result = handler.on_enter(ctx, PhaseEnvelopeStore.make_fresh_envelope(_state()))

    assert result.status is PhaseStatus.ESCALATED
    payload = result.updated_state.payload
    assert isinstance(payload, ExplorationPayload)
    assert payload.gate_status is ExplorationGateStatus.REJECTED
    assert any("design_review_rejected" in e for e in result.errors)
    assert exploration_gate_approved(ctx, result.updated_state).passed is False


def test_no_review_wired_fails_closed(tmp_path: Path) -> None:
    """Fail-closed: a valid frame but no review wired -> FAILED (never APPROVE)."""
    sd = _story_dir(tmp_path)
    _bind_flow(sd)
    ctx = _ctx(sd)
    persist_example_change_frame(
        build_artifact_manager(sd), story_dir=sd, run_id=_RUN_ID
    )
    handler = build_exploration_phase_handler(sd)  # review=None

    result = handler.on_enter(ctx, PhaseEnvelopeStore.make_fresh_envelope(_state()))

    assert result.status is PhaseStatus.FAILED
    assert exploration_gate_approved(ctx, result.updated_state).passed is False
