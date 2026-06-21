"""Unit tests for Stage 2b DesignChallengeRunner (AC5; FK-23 §23.5.3)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from tests.exploration_change_frame_fixture import example_change_frame
from tests.unit.exploration.review.scripted import (
    ScriptedLlmClient,
    build_real_sink,
    build_scripted_evaluator,
)

from agentkit.backend.artifacts.reference import ArtifactReference
from agentkit.backend.core_types import ArtifactClass, Severity
from agentkit.backend.exploration.review.design_challenge import (
    DesignChallengeResult,
    DesignChallengeRunner,
)
from agentkit.backend.exploration.review.design_review import DesignReviewResult
from agentkit.backend.exploration.review.doc_fidelity import DocFidelityResult
from agentkit.backend.verify_system.protocols import Finding, TrustClass

if TYPE_CHECKING:
    from pathlib import Path

    from agentkit.backend.story_context_manager.models import StoryContext


def _runner(
    ctx: StoryContext, story_dir: Path, verdict: str
) -> DesignChallengeRunner:
    client = ScriptedLlmClient(semantic_review=[verdict])
    return DesignChallengeRunner(
        build_scripted_evaluator(ctx, client), build_real_sink(story_dir)
    )


def _priors(
    *, prior_findings: tuple[Finding, ...] = ()
) -> tuple[DocFidelityResult, DesignReviewResult]:
    """Stage 1 + 2a priors.

    The PLACEHOLDER challenge (AG3-047 pending) folds these findings into the
    bundle CONTEXT for coherence, but as a fresh round-1 evaluation -- it does
    NOT mandate a finding-resolution contract against them.
    """
    ref = ArtifactReference(
        artifact_class=ArtifactClass.QA,
        story_id="AG3-045",
        run_id="11111111-1111-4111-8111-111111111111",
        record_key="prior",
    )
    doc = DocFidelityResult(
        status="pass", findings=prior_findings, evaluator_result_ref=ref
    )
    design = DesignReviewResult(
        status="pass",
        review_rounds=1,
        findings_per_round=((),),
        final_evaluator_result_ref=ref,
    )
    return doc, design


def test_challenge_pass(ctx: StoryContext, story_dir: Path) -> None:
    runner = _runner(ctx, story_dir, "PASS")

    result = runner.run(example_change_frame(), _priors())

    assert isinstance(result, DesignChallengeResult)
    assert result.status == "pass"
    assert result.addressed_issues == ()
    assert "passed" in result.challenge_summary
    assert result.evaluator_result_ref.artifact_class is ArtifactClass.QA


def test_challenge_fail(ctx: StoryContext, story_dir: Path) -> None:
    runner = _runner(ctx, story_dir, "FAIL")

    result = runner.run(example_change_frame(), _priors())

    assert result.status == "fail"
    assert len(result.addressed_issues) == 1


def test_challenge_passes_with_prior_findings_folded_as_context(
    ctx: StoryContext, story_dir: Path
) -> None:
    """Prior findings are folded into bundle context (placeholder coherence).

    They are context only: the challenge stays a fresh round-1 evaluation, so no
    finding_resolution_* contract is mandated and a clean PASS still passes (a
    single base check, not a remediation cover).
    """
    runner = _runner(ctx, story_dir, "PASS")
    prior = Finding(
        layer="doc_fidelity",
        check="impl_fidelity",
        severity=Severity.BLOCKING,
        message="prior stage finding",
        trust_class=TrustClass.VERIFIED_LLM,
    )

    result = runner.run(
        example_change_frame(), _priors(prior_findings=(prior,))
    )

    assert result.status == "pass"
