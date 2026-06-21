"""Unit tests for ExplorationReview orchestration (AC1/AC8; FK-23 §23.5)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from tests.exploration_change_frame_fixture import example_change_frame
from tests.unit.exploration.review.scripted import (
    ScriptedLlmClient,
    build_real_sink,
    build_scripted_evaluator,
)

from agentkit.backend.core_types import ExplorationGateStatus
from agentkit.backend.exploration.review.design_challenge import DesignChallengeRunner
from agentkit.backend.exploration.review.design_review import DesignReviewRunner
from agentkit.backend.exploration.review.doc_fidelity import DocFidelityChecker
from agentkit.backend.exploration.review.review import ExplorationGateResult, ExplorationReview
from agentkit.backend.verify_system.llm_evaluator.structured_evaluator import ReviewerRole

if TYPE_CHECKING:
    from pathlib import Path

    from agentkit.backend.exploration.review.design_challenge import (
        DesignChallengeRunner as _ChallengeRunner,
    )
    from agentkit.backend.story_context_manager.models import StoryContext

from agentkit.backend.bootstrap.composition_root import build_artifact_manager


def _review(
    ctx: StoryContext,
    story_dir: Path,
    *,
    doc_fidelity: list[str],
    semantic_review: list[str],
    challenge: _ChallengeRunner | None = None,
) -> tuple[ExplorationReview, ScriptedLlmClient]:
    client = ScriptedLlmClient(
        doc_fidelity=doc_fidelity, semantic_review=semantic_review
    )
    evaluator = build_scripted_evaluator(ctx, client)
    sink = build_real_sink(story_dir)
    manager = build_artifact_manager(story_dir)
    review = ExplorationReview(
        stage1_doc_fidelity=DocFidelityChecker(evaluator, sink, story_context=ctx),
        stage2a_design_review=DesignReviewRunner(evaluator, sink),
        stage2b_design_challenge=challenge,
        artifact_manager=manager,
    )
    return review, client


def test_approved_runs_stage1_then_stage2a(
    ctx: StoryContext, story_dir: Path
) -> None:
    """AC1/AC8: Stage 1 -> Stage 2a in order; all PASS -> APPROVED."""
    review, client = _review(
        ctx, story_dir, doc_fidelity=["PASS"], semantic_review=["PASS"]
    )

    result = review.run(example_change_frame())

    assert isinstance(result, ExplorationGateResult)
    assert result.overall_status is ExplorationGateStatus.APPROVED
    # Concept-normative order: doc_fidelity BEFORE semantic_review.
    assert client.calls == [
        ReviewerRole.DOC_FIDELITY.value,
        ReviewerRole.SEMANTIC_REVIEW.value,
    ]
    assert result.stage2a_result is not None
    assert result.stage2b_result is None


def test_stage1_fail_short_circuits_no_stage2a(
    ctx: StoryContext, story_dir: Path
) -> None:
    """NO ERROR BYPASSING: a Stage-1 FAIL -> REJECTED, Stage 2a never runs."""
    review, client = _review(
        ctx, story_dir, doc_fidelity=["FAIL"], semantic_review=[]
    )

    result = review.run(example_change_frame())

    assert result.overall_status is ExplorationGateStatus.REJECTED
    assert result.stage2a_result is None
    assert result.review_rounds == 0
    # Stage 2a (semantic_review) was NEVER invoked.
    assert client.calls == [ReviewerRole.DOC_FIDELITY.value]


def test_stage2a_escalation_is_pending(ctx: StoryContext, story_dir: Path) -> None:
    """Stage-2a round-limit escalation -> PENDING (not REJECTED) + reason."""
    review, _ = _review(
        ctx,
        story_dir,
        doc_fidelity=["PASS"],
        semantic_review=["FAIL", "FAIL", "FAIL"],
    )

    result = review.run(example_change_frame())

    assert result.overall_status is ExplorationGateStatus.PENDING
    assert result.is_escalated is True
    assert result.escalation_reason is not None


def test_optional_stage2b_runs_when_wired(
    ctx: StoryContext, story_dir: Path
) -> None:
    """When Stage 2b is wired and all stages PASS -> APPROVED with 2b result."""
    client = ScriptedLlmClient(
        doc_fidelity=["PASS"], semantic_review=["PASS", "PASS"]
    )
    evaluator = build_scripted_evaluator(ctx, client)
    sink = build_real_sink(story_dir)
    review = ExplorationReview(
        stage1_doc_fidelity=DocFidelityChecker(evaluator, sink, story_context=ctx),
        stage2a_design_review=DesignReviewRunner(evaluator, sink),
        stage2b_design_challenge=DesignChallengeRunner(evaluator, sink),
        artifact_manager=build_artifact_manager(story_dir),
    )

    result = review.run(example_change_frame())

    assert result.overall_status is ExplorationGateStatus.APPROVED
    assert result.stage2b_result is not None
    assert result.stage2b_result.status == "pass"


def test_stage2b_fail_rejects(ctx: StoryContext, story_dir: Path) -> None:
    client = ScriptedLlmClient(
        doc_fidelity=["PASS"], semantic_review=["PASS", "FAIL"]
    )
    evaluator = build_scripted_evaluator(ctx, client)
    sink = build_real_sink(story_dir)
    review = ExplorationReview(
        stage1_doc_fidelity=DocFidelityChecker(evaluator, sink, story_context=ctx),
        stage2a_design_review=DesignReviewRunner(evaluator, sink),
        stage2b_design_challenge=DesignChallengeRunner(evaluator, sink),
        artifact_manager=build_artifact_manager(story_dir),
    )

    result = review.run(example_change_frame())

    assert result.overall_status is ExplorationGateStatus.REJECTED
    assert result.stage2b_result is not None
    assert result.stage2b_result.status == "fail"


def _wired_challenge_review(
    ctx: StoryContext,
    story_dir: Path,
    *,
    doc_fidelity: list[str],
    semantic_review: list[str],
) -> tuple[ExplorationReview, ScriptedLlmClient]:
    """A review with a WIRED Stage-2b design challenge (for the gating tests)."""
    client = ScriptedLlmClient(
        doc_fidelity=doc_fidelity, semantic_review=semantic_review
    )
    evaluator = build_scripted_evaluator(ctx, client)
    sink = build_real_sink(story_dir)
    review = ExplorationReview(
        stage1_doc_fidelity=DocFidelityChecker(evaluator, sink, story_context=ctx),
        stage2a_design_review=DesignReviewRunner(evaluator, sink),
        stage2b_design_challenge=DesignChallengeRunner(evaluator, sink),
        artifact_manager=build_artifact_manager(story_dir),
    )
    return review, client


def test_gating_off_suppresses_wired_stage2b(
    ctx: StoryContext, story_dir: Path
) -> None:
    """WARNING-4 (a): run_design_challenge=False suppresses a WIRED Stage 2b.

    Even with a Stage-2b runner wired, ``run_design_challenge=False`` skips the
    optional adversarial pass; Stage 1 and Stage 2a still run, so an all-PASS
    run is APPROVED without ever invoking the challenge LLM.
    """
    review, client = _wired_challenge_review(
        ctx, story_dir, doc_fidelity=["PASS"], semantic_review=["PASS"]
    )

    result = review.run(example_change_frame(), run_design_challenge=False)

    assert result.overall_status is ExplorationGateStatus.APPROVED
    assert result.stage2b_result is None
    # Only Stage 1 + Stage 2a ran; the challenge LLM was NEVER invoked.
    assert client.calls == [
        ReviewerRole.DOC_FIDELITY.value,
        ReviewerRole.SEMANTIC_REVIEW.value,
    ]


def test_gating_off_cannot_bypass_stage1_fail(
    ctx: StoryContext, story_dir: Path
) -> None:
    """WARNING-4 (a): suppressing Stage 2b cannot bypass a Stage-1 FAIL.

    ``run_design_challenge=False`` only gates the OPTIONAL Stage 2b. It is no
    route to APPROVED: a Stage-1 FAIL still REJECTS the gate (NO ERROR BYPASSING).
    """
    review, _ = _wired_challenge_review(
        ctx, story_dir, doc_fidelity=["FAIL"], semantic_review=[]
    )

    result = review.run(example_change_frame(), run_design_challenge=False)

    assert result.overall_status is ExplorationGateStatus.REJECTED
    assert result.stage2a_result is None
    assert result.stage2b_result is None


def test_gating_on_forces_wired_stage2b_fail(
    ctx: StoryContext, story_dir: Path
) -> None:
    """WARNING-4 (b): run_design_challenge=True cannot skip a wired Stage 2b.

    A class that warrants the challenge (fine-design / escalating) forces Stage 2b
    when one is wired; a Stage-2b FAIL then REJECTS the gate.
    """
    review, _ = _wired_challenge_review(
        ctx, story_dir, doc_fidelity=["PASS"], semantic_review=["PASS", "FAIL"]
    )

    result = review.run(example_change_frame(), run_design_challenge=True)

    assert result.overall_status is ExplorationGateStatus.REJECTED
    assert result.stage2b_result is not None
    assert result.stage2b_result.status == "fail"
