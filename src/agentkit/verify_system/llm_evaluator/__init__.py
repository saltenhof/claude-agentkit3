"""Evaluators QA layer -- LLM-based semantic review (FK-27 §27.5 / FK-34).

Re-exports the Layer-2 LLM-evaluation surface introduced in AG3-043:
``StructuredEvaluator`` (one fail-closed role), ``ParallelEvalRunner`` (three
roles in parallel, FK-27 §27.5.1), the ``ReviewBundle`` input, the ``LlmClient``
port, and the supporting enums / errors. The legacy top-level shim
``agentkit.llm_evaluator`` (verify-system.C4) was removed; the canonical path
is ``agentkit.verify_system.llm_evaluator``.

AG3-065 additions: ``HubLlmClient`` (concrete Hub adapter, injectable),
``LoginRequiredError`` (distinct error with operator_hint), ``RolePoolResolver``
(port protocol), per-operation timeout constants, and ``DialogueRunner`` /
``DialogueTurn`` / ``DialogueResult`` (FK-11 §11.5.2 multi-turn dialogue).
"""

from __future__ import annotations

from agentkit.verify_system.llm_evaluator.bundle import (  # noqa: F401
    BUNDLE_TOKEN_LIMIT,
    ReviewBundle,
    build_review_bundle,
)
from agentkit.verify_system.llm_evaluator.context_sufficiency import (  # noqa: F401
    CONTEXT_SUFFICIENCY_FILE,
    ContextSufficiencyArtifact,
    ContextSufficiencyBuilder,
    ContextSufficiencyResult,
    SufficiencyLevel,
)
from agentkit.verify_system.llm_evaluator.dialogue_runner import (  # noqa: F401
    DialogueResult,
    DialogueRunner,
    DialogueTurn,
)
from agentkit.verify_system.llm_evaluator.inputs import (  # noqa: F401
    Layer2InputMissingError,
    Layer2ReviewInput,
)
from agentkit.verify_system.llm_evaluator.llm_client import (  # noqa: F401
    ACQUIRE_TIMEOUT_SECONDS,
    MAX_ACQUIRE_RETRIES,
    RELEASE_TIMEOUT_SECONDS,
    SEND_TIMEOUT_SECONDS,
    TOTAL_TIMEOUT_SECONDS,
    FailClosedLlmClient,
    HubLlmClient,
    LlmClient,
    LlmClientError,
    LoginRequiredError,
    RolePoolResolver,
)
from agentkit.verify_system.llm_evaluator.parallel_runner import (  # noqa: F401
    ParallelEvalError,
    ParallelEvalRunner,
)
from agentkit.verify_system.llm_evaluator.prompt_materializer import (  # noqa: F401
    PromptRuntimeMaterializer,
)
from agentkit.verify_system.llm_evaluator.structured_evaluator import (  # noqa: F401
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
    "ACQUIRE_TIMEOUT_SECONDS",
    "BUNDLE_TOKEN_LIMIT",
    "CONTEXT_SUFFICIENCY_FILE",
    "DOC_FIDELITY_CHECK_IDS",
    "MAX_ACQUIRE_RETRIES",
    "QA_REVIEW_CHECK_IDS",
    "RELEASE_TIMEOUT_SECONDS",
    "SEMANTIC_REVIEW_CHECK_IDS",
    "SEND_TIMEOUT_SECONDS",
    "TOTAL_TIMEOUT_SECONDS",
    "CheckResult",
    "ContextSufficiencyArtifact",
    "ContextSufficiencyBuilder",
    "ContextSufficiencyResult",
    "DialogueResult",
    "DialogueRunner",
    "DialogueTurn",
    "FailClosedLlmClient",
    "HubLlmClient",
    "Layer2InputMissingError",
    "Layer2ReviewInput",
    "LlmClient",
    "LlmClientError",
    "LlmEvaluatorResponse",
    "LlmVerdict",
    "LoginRequiredError",
    "ParallelEvalError",
    "ParallelEvalRunner",
    "PromptRuntimeMaterializer",
    "ReviewBundle",
    "ReviewerRole",
    "RolePoolResolver",
    "StructuredEvaluator",
    "StructuredEvaluatorError",
    "StructuredEvaluatorResult",
    "SufficiencyLevel",
    "build_review_bundle",
    "template_name_for_role",
]
