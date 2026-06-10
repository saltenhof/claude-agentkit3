"""Unit tests for Stage 1 DocFidelityChecker (AC2; FK-23 §23.5.1)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from tests.exploration_change_frame_fixture import example_change_frame
from tests.unit.exploration.review.scripted import (
    ScriptedLlmClient,
    build_real_sink,
    build_scripted_evaluator,
)

from agentkit.core_types import ArtifactClass
from agentkit.exploration.review.doc_fidelity import (
    DocFidelityChecker,
    DocFidelityResult,
)
from agentkit.verify_system.llm_evaluator.structured_evaluator import ReviewerRole

if TYPE_CHECKING:
    from pathlib import Path

    from agentkit.story_context_manager.models import StoryContext


def _checker(
    ctx: StoryContext, story_dir: Path, verdict: str
) -> tuple[DocFidelityChecker, ScriptedLlmClient]:
    client = ScriptedLlmClient(doc_fidelity=[verdict])
    checker = DocFidelityChecker(
        build_scripted_evaluator(ctx, client),
        build_real_sink(story_dir),
        story_context=ctx,
    )
    return checker, client


def test_doc_fidelity_pass(ctx: StoryContext, story_dir: Path) -> None:
    checker, client = _checker(ctx, story_dir, "PASS")

    result = checker.check(example_change_frame())

    assert isinstance(result, DocFidelityResult)
    assert result.status == "pass"
    assert result.findings == ()
    # AC2: DOC_FIDELITY role was actually invoked.
    assert client.calls == [ReviewerRole.DOC_FIDELITY.value]
    # The reference is a real persisted QA artifact (not fabricated).
    assert result.evaluator_result_ref.artifact_class is ArtifactClass.QA
    assert result.evaluator_result_ref.story_id == "AG3-045"


def test_doc_fidelity_fail(ctx: StoryContext, story_dir: Path) -> None:
    checker, _ = _checker(ctx, story_dir, "FAIL")

    result = checker.check(example_change_frame())

    assert result.status == "fail"
    assert len(result.findings) == 1
    assert result.evaluator_result_ref.artifact_class is ArtifactClass.QA


def test_doc_fidelity_concerns_is_fail(ctx: StoryContext, story_dir: Path) -> None:
    """Stage 1 is binary fail-closed: PASS_WITH_CONCERNS is NOT a pass."""
    checker, _ = _checker(ctx, story_dir, "PASS_WITH_CONCERNS")

    result = checker.check(example_change_frame())

    assert result.status == "fail"
