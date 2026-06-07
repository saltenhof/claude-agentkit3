"""Unit tests for Stage 2a DesignReviewRunner (AC3/AC4; FK-23 §23.5.2)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from tests.exploration_change_frame_fixture import example_change_frame
from tests.unit.exploration.review.scripted import (
    ResolutionScriptedLlmClient,
    ScriptedLlmClient,
    build_real_sink,
    build_scripted_evaluator,
)

from agentkit.exploration.review.design_review import (
    DesignReviewResult,
    DesignReviewRunner,
)
from agentkit.verify_system.llm_evaluator.structured_evaluator import ReviewerRole

if TYPE_CHECKING:
    from pathlib import Path

    from agentkit.exploration.change_frame import ChangeFrame
    from agentkit.story_context_manager.models import StoryContext
    from agentkit.verify_system.protocols import Finding


class _RecordingReviser:
    """A ``ChangeFrameReviser`` double yielding a genuinely revised frame.

    It records its calls and returns a re-drafted change-frame (here: the same
    fixture with a mutated goal) so the runner continues the loop over a CHANGED
    frame, never the unchanged one. Returns ``None`` once exhausted so the loop
    cannot spin forever.
    """

    def __init__(self, revisions: list[ChangeFrame | None]) -> None:
        self._revisions = list(revisions)
        self.calls: list[tuple[str, int]] = []

    def revise(
        self,
        change_frame: ChangeFrame,
        findings: tuple[Finding, ...],
        *,
        next_round: int,
    ) -> ChangeFrame | None:
        del findings
        self.calls.append((change_frame.story_id, next_round))
        if not self._revisions:
            return None
        return self._revisions.pop(0)


def _revised_frame(suffix: str = " (re-drafted)") -> ChangeFrame:
    """A genuinely revised change-frame (distinct from the unchanged fixture).

    ``suffix`` lets a multi-round test produce DISTINCT revised frames per round
    (the runner fail-closes if a reviser returns a frame unchanged from the prior
    round, so successive rounds must each get a genuinely different frame).
    """
    base = example_change_frame()
    return base.model_copy(
        update={
            "goal_and_scope": base.goal_and_scope.model_copy(
                update={"changes": base.goal_and_scope.changes + suffix}
            )
        }
    )


def _runner(
    ctx: StoryContext, story_dir: Path, verdicts: list[str], max_rounds: int = 3
) -> tuple[DesignReviewRunner, ScriptedLlmClient]:
    client = ScriptedLlmClient(semantic_review=verdicts)
    runner = DesignReviewRunner(
        build_scripted_evaluator(ctx, client),
        build_real_sink(story_dir),
        max_rounds=max_rounds,
    )
    return runner, client


def test_pass_first_round(ctx: StoryContext, story_dir: Path) -> None:
    runner, client = _runner(ctx, story_dir, ["PASS"])

    result = runner.run(example_change_frame(), [])

    assert isinstance(result, DesignReviewResult)
    assert result.status == "pass"
    assert result.review_rounds == 1
    # AC3: SEMANTIC_REVIEW role used.
    assert client.calls == [ReviewerRole.SEMANTIC_REVIEW.value]
    assert result.suggested_reaction is None


def test_fail_without_reviser_escalates_no_same_frame_rerun(
    ctx: StoryContext, story_dir: Path
) -> None:
    """FAIL below the ceiling with NO reviser fails CLOSED to escalation.

    Negative core (NO ERROR BYPASSING): the identical, already-failed frame is
    NOT re-evaluated, so a flaky FAIL-then-PASS over the SAME frame can never be
    accepted. The runner escalates on the first FAIL because no re-draft source
    is wired (the AG3-046 state; re-drafting is AG3-054). The second scripted
    PASS is therefore never consumed -- proving the same frame is not re-run.
    """
    runner, client = _runner(ctx, story_dir, ["FAIL", "PASS"])

    result = runner.run(example_change_frame(), [])

    assert result.status == "escalated"
    assert result.review_rounds == 1
    # Only ONE evaluation ran: the same frame was never re-evaluated.
    assert len(client.calls) == 1
    assert result.suggested_reaction is not None
    assert "no re-draft source" in result.suggested_reaction


def test_fail_then_pass_with_reviser_continues_on_revised_frame(
    ctx: StoryContext, story_dir: Path
) -> None:
    """With a reviser, a FAIL continues over a REVISED frame; resolution mandated.

    FK-23 §23.5.2 / FK-34 §34.9: round 1 FAILs, the reviser yields a genuinely
    re-drafted frame, and round 2 must carry the prior finding's resolution
    (``finding_resolution_semantic_review:systemic_adequacy = fully_resolved``)
    before its PASS is accepted. The resolution check is mandatory: omit it and
    the real StructuredEvaluator would reject the round (covered by the evaluator
    completeness tests). Here it is supplied -> the gate passes.
    """
    client = ResolutionScriptedLlmClient(
        [("FAIL", None), ("PASS", "fully_resolved")]
    )
    reviser = _RecordingReviser([_revised_frame()])
    runner = DesignReviewRunner(
        build_scripted_evaluator(ctx, client),
        build_real_sink(story_dir),
        reviser=reviser,
    )

    result = runner.run(example_change_frame(), [])

    assert result.status == "pass"
    assert result.review_rounds == 2
    assert len(client.calls) == 2
    # The reviser was asked exactly once, for the round-2 frame.
    assert reviser.calls == [(example_change_frame().story_id, 2)]


def test_reviser_returning_none_escalates(
    ctx: StoryContext, story_dir: Path
) -> None:
    """A reviser that cannot re-draft (returns ``None``) escalates fail-closed."""
    client = ScriptedLlmClient(semantic_review=["FAIL"])
    reviser = _RecordingReviser([None])
    runner = DesignReviewRunner(
        build_scripted_evaluator(ctx, client),
        build_real_sink(story_dir),
        reviser=reviser,
    )

    result = runner.run(example_change_frame(), [])

    assert result.status == "escalated"
    assert result.review_rounds == 1
    assert len(client.calls) == 1
    assert result.suggested_reaction is not None
    assert "no re-draft source" in result.suggested_reaction


def test_reviser_returning_unchanged_frame_escalates(
    ctx: StoryContext, story_dir: Path
) -> None:
    """A reviser that returns an UNCHANGED frame escalates (no same-frame approval).

    Defense against a miswired reviser: an "unchanged" revision is no revision.
    Round 1 FAILs, the reviser returns a frame deep-equal to the failed one, so
    the runner fails closed to escalation BEFORE re-evaluating it -- the second
    scripted PASS is never consumed (NO ERROR BYPASSING).
    """
    client = ScriptedLlmClient(semantic_review=["FAIL", "PASS"])
    reviser = _RecordingReviser([example_change_frame()])
    runner = DesignReviewRunner(
        build_scripted_evaluator(ctx, client),
        build_real_sink(story_dir),
        reviser=reviser,
    )

    result = runner.run(example_change_frame(), [])

    assert result.status == "escalated"
    assert result.review_rounds == 1
    # The identical frame was NOT re-evaluated: the second PASS is never consumed.
    assert len(client.calls) == 1
    assert result.suggested_reaction is not None
    assert "already evaluated and failed" in result.suggested_reaction


def test_reviser_cycling_to_a_prior_failed_frame_escalates(
    ctx: StoryContext, story_dir: Path
) -> None:
    """A reviser cycling back to an EARLIER already-failed frame escalates.

    A -> FAIL -> B -> FAIL -> A again. Frame A already failed in round 1, so
    re-surfacing it is no revision even though A != the immediately prior frame B
    (the runner checks the FULL history, not just the previous frame). The runner
    fails closed before re-evaluating A; the third scripted PASS is not consumed.
    """
    frame_a = example_change_frame()
    frame_b = _revised_frame(" (b)")
    client = ResolutionScriptedLlmClient(
        [("FAIL", None), ("FAIL", "not_resolved"), ("PASS", "fully_resolved")]
    )
    reviser = _RecordingReviser([frame_b, frame_a])
    runner = DesignReviewRunner(
        build_scripted_evaluator(ctx, client),
        build_real_sink(story_dir),
        reviser=reviser,
    )

    result = runner.run(frame_a, [])

    assert result.status == "escalated"
    # Round 1 evaluated A, round 2 evaluated B; the round-3 re-surfacing of A is
    # refused, so only two evaluations ran and the scripted PASS is never consumed.
    assert result.review_rounds == 2
    assert len(client.calls) == 2
    assert "already evaluated and failed" in result.suggested_reaction


def test_escalation_after_round_three(ctx: StoryContext, story_dir: Path) -> None:
    """AC4: FAIL after round 3 -> escalated (round limit, FK-23 §23.5.2).

    With a reviser wired, each FAIL re-drafts and runs another round; the loop
    reaches the round-3 ceiling and escalates on the round-limit. Rounds 2/3 are
    remediation rounds over revised frames, so each must carry the prior
    finding's resolution check (here ``not_resolved``) -- proving the resolution
    contract is exercised on the revised path even when the frame keeps failing.
    """
    client = ResolutionScriptedLlmClient(
        [("FAIL", None), ("FAIL", "not_resolved"), ("FAIL", "not_resolved")]
    )
    # Distinct revised frames per round: a reviser returning an unchanged frame
    # would (correctly) fail-close, so the ceiling test must supply real revisions.
    reviser = _RecordingReviser([_revised_frame(" (r2)"), _revised_frame(" (r3)")])
    runner = DesignReviewRunner(
        build_scripted_evaluator(ctx, client),
        build_real_sink(story_dir),
        reviser=reviser,
    )

    result = runner.run(example_change_frame(), [])

    assert result.status == "escalated"
    assert result.review_rounds == 3
    assert len(client.calls) == 3
    # AC9: a suggested_reaction is carried for the handler escalation.
    assert result.suggested_reaction is not None
    assert "round 3" in result.suggested_reaction
    assert "round limit" in result.suggested_reaction


def test_custom_max_rounds_escalates_earlier(
    ctx: StoryContext, story_dir: Path
) -> None:
    """With max_rounds=1 a single FAIL escalates on the round-limit (with reviser)."""
    client = ScriptedLlmClient(semantic_review=["FAIL"])
    reviser = _RecordingReviser([_revised_frame()])
    runner = DesignReviewRunner(
        build_scripted_evaluator(ctx, client),
        build_real_sink(story_dir),
        max_rounds=1,
        reviser=reviser,
    )

    result = runner.run(example_change_frame(), [])

    assert result.status == "escalated"
    assert result.review_rounds == 1
    # The ceiling is hit before the reviser is consulted (round-limit escalation).
    assert reviser.calls == []
