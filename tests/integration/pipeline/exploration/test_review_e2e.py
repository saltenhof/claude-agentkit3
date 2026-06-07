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

from typing import TYPE_CHECKING

import pytest
from tests.exploration_change_frame_fixture import persist_example_change_frame
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
from agentkit.process.language.guards import exploration_gate_approved
from agentkit.state_backend.config import ALLOW_SQLITE_ENV, STATE_BACKEND_ENV
from agentkit.state_backend.store import (
    reset_backend_cache_for_tests,
    save_flow_execution,
)
from agentkit.story_context_manager.models import (
    ExplorationPayload,
    PhaseName,
    PhaseState,
    PhaseStatus,
    StoryContext,
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
    return sd


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


def _state() -> PhaseState:
    return PhaseState(
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
        stage1_doc_fidelity=DocFidelityChecker(evaluator, sink),
        stage2a_design_review=DesignReviewRunner(evaluator, sink),
        stage2b_design_challenge=None,
        artifact_manager=build_artifact_manager(story_dir),
    )


def _run(
    story_dir: Path, ctx: StoryContext, review: ExplorationReview
) -> HandlerResult:
    persist_example_change_frame(
        build_artifact_manager(story_dir), story_dir=story_dir, run_id=_RUN_ID
    )
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
    """A wired Stage-2b FAIL (stage 1+2a passed) -> ESCALATED + gate REJECTED."""
    sd = _story_dir(tmp_path)
    _bind_flow(sd)
    ctx = _ctx(sd)
    client = ScriptedLlmClient(
        doc_fidelity=["PASS"], semantic_review=["PASS", "FAIL"]
    )
    evaluator = build_scripted_evaluator(ctx, client)
    sink = build_real_sink(sd)
    review = ExplorationReview(
        stage1_doc_fidelity=DocFidelityChecker(evaluator, sink),
        stage2a_design_review=DesignReviewRunner(evaluator, sink),
        stage2b_design_challenge=DesignChallengeRunner(evaluator, sink),
        artifact_manager=build_artifact_manager(sd),
    )

    result = _run(sd, ctx, review)

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
