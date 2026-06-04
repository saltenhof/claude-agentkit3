"""Evaluators QA layer -- LLM-based semantic review (FK-27 §27.5 / FK-34).

Re-exports the Layer-2 LLM-evaluation surface introduced in AG3-043:
``StructuredEvaluator`` (one fail-closed role), ``ParallelEvalRunner`` (three
roles in parallel, FK-27 §27.5.1), the ``ReviewBundle`` input, the ``LlmClient``
port, and the supporting enums / errors. The legacy top-level shim
``agentkit.llm_evaluator`` (verify-system.C4) was removed; the canonical path
is ``agentkit.verify_system.llm_evaluator``.
"""

from __future__ import annotations

from agentkit.verify_system.llm_evaluator.bundle import (
    MAX_BUNDLE_TOTAL_BYTES,
    MAX_DIFF_CONTENT_BYTES,
    ReviewBundle,
    build_review_bundle,
)
from agentkit.verify_system.llm_evaluator.inputs import (
    Layer2InputMissingError,
    Layer2ReviewInput,
)
from agentkit.verify_system.llm_evaluator.llm_client import (
    FailClosedLlmClient,
    LlmClient,
    LlmClientError,
)
from agentkit.verify_system.llm_evaluator.parallel_runner import (
    ParallelEvalError,
    ParallelEvalRunner,
)
from agentkit.verify_system.llm_evaluator.prompt_materializer import (
    PromptRuntimeMaterializer,
)
from agentkit.verify_system.llm_evaluator.structured_evaluator import (
    DOC_FIDELITY_CHECK_IDS,
    QA_REVIEW_CHECK_IDS,
    SEMANTIC_REVIEW_CHECK_IDS,
    CheckResult,
    LlmEvaluatorResponse,
    LlmVerdict,
    ReviewerRole,
    StructuredEvaluator,
    StructuredEvaluatorError,
    StructuredEvaluatorResult,
    template_name_for_role,
)

__all__ = [
    "DOC_FIDELITY_CHECK_IDS",
    "MAX_BUNDLE_TOTAL_BYTES",
    "MAX_DIFF_CONTENT_BYTES",
    "QA_REVIEW_CHECK_IDS",
    "SEMANTIC_REVIEW_CHECK_IDS",
    "CheckResult",
    "FailClosedLlmClient",
    "Layer2InputMissingError",
    "Layer2ReviewInput",
    "LlmClient",
    "LlmClientError",
    "LlmEvaluatorResponse",
    "LlmVerdict",
    "ParallelEvalError",
    "ParallelEvalRunner",
    "PromptRuntimeMaterializer",
    "ReviewBundle",
    "ReviewerRole",
    "StructuredEvaluator",
    "StructuredEvaluatorError",
    "StructuredEvaluatorResult",
    "build_review_bundle",
    "template_name_for_role",
]
