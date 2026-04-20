"""Unit tests for llm_evaluator namespace exports."""

from agentkit.llm_evaluator import SemanticReviewer
from agentkit.llm_evaluator import reviewer as reviewer_module
from agentkit.qa.evaluators.reviewer import SemanticReviewer as CanonicalReviewer


def test_llm_evaluator_namespace_reexports_canonical_reviewer() -> None:
    assert SemanticReviewer is CanonicalReviewer
    assert reviewer_module.SemanticReviewer is CanonicalReviewer
