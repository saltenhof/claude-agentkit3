"""Layer-2 evaluator roles and check-id whitelists."""

from __future__ import annotations

from enum import StrEnum
from typing import Final

from agentkit.verify_system.protocols import Severity


class LlmVerdict(StrEnum):
    """LLM-domain verdict of a single evaluation role (FK-34 §34.2)."""

    PASS = "PASS"
    FAIL = "FAIL"
    PASS_WITH_CONCERNS = "PASS_WITH_CONCERNS"


class ReviewerRole(StrEnum):
    """The Layer-2 evaluation roles (FK-27 §27.5 / FK-34 §34.2).

    The three QA-subflow roles (``qa_review`` / ``semantic_review`` /
    ``doc_fidelity``) plus the story-creation conflict-assessment role
    (``story_creation_review``, FK-11 §11.5.1 / FK-21 §21.4.1). The latter
    reuses the SAME evaluator transport -- it is NOT a second LLM-evaluator
    path; it only adds its role / check / template to the shared maps.
    """

    QA_REVIEW = "qa_review"
    SEMANTIC_REVIEW = "semantic_review"
    DOC_FIDELITY = "doc_fidelity"
    STORY_CREATION_REVIEW = "story_creation_review"


QA_REVIEW_CHECK_IDS: Final[frozenset[str]] = frozenset({
    "ac_fulfilled",
    "impl_fidelity",
    "scope_compliance",
    "impact_violation",
    "arch_conformity",
    "proportionality",
    "error_handling",
    "authz_logic",
    "silent_data_loss",
    "backward_compat",
    "observability",
    "doc_impact",
})

SEMANTIC_REVIEW_CHECK_IDS: Final[frozenset[str]] = frozenset({"systemic_adequacy"})
DOC_FIDELITY_CHECK_IDS: Final[frozenset[str]] = frozenset({"impl_fidelity"})
#: Single conflict-assessment check for the story-creation reconciliation
#: (FK-11 §11.5.1 / FK-21 §21.4.1: 1 check, duplicate / overlap).
STORY_CREATION_REVIEW_CHECK_IDS: Final[frozenset[str]] = frozenset({"conflict_assessment"})

ROLE_CHECK_IDS: Final[dict[ReviewerRole, frozenset[str]]] = {
    ReviewerRole.QA_REVIEW: QA_REVIEW_CHECK_IDS,
    ReviewerRole.SEMANTIC_REVIEW: SEMANTIC_REVIEW_CHECK_IDS,
    ReviewerRole.DOC_FIDELITY: DOC_FIDELITY_CHECK_IDS,
    ReviewerRole.STORY_CREATION_REVIEW: STORY_CREATION_REVIEW_CHECK_IDS,
}

ROLE_TEMPLATE: Final[dict[ReviewerRole, str]] = {
    ReviewerRole.QA_REVIEW: "qa-review",
    ReviewerRole.SEMANTIC_REVIEW: "qa-semantic-review",
    ReviewerRole.DOC_FIDELITY: "qa-doc-fidelity",
    ReviewerRole.STORY_CREATION_REVIEW: "vectordb-conflict",
}

STATUS_SEVERITY: Final[dict[LlmVerdict, Severity]] = {
    LlmVerdict.FAIL: Severity.BLOCKING,
    LlmVerdict.PASS_WITH_CONCERNS: Severity.MINOR,
}


__all__ = [
    "DOC_FIDELITY_CHECK_IDS",
    "QA_REVIEW_CHECK_IDS",
    "ROLE_CHECK_IDS",
    "ROLE_TEMPLATE",
    "SEMANTIC_REVIEW_CHECK_IDS",
    "STATUS_SEVERITY",
    "STORY_CREATION_REVIEW_CHECK_IDS",
    "LlmVerdict",
    "ReviewerRole",
]
