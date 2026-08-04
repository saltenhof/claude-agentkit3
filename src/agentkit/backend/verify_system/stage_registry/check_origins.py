"""Canonical provenance entries for native verify-system checks."""

from __future__ import annotations

from types import MappingProxyType
from typing import TYPE_CHECKING, Final

if TYPE_CHECKING:
    from collections.abc import Mapping

QA_REVIEW_CHECK_IDS: Final[frozenset[str]] = frozenset(
    {
        "ac_fulfilled",
        "arch_conformity",
        "authz_logic",
        "backward_compat",
        "doc_impact",
        "error_handling",
        "impact_violation",
        "impl_fidelity",
        "observability",
        "proportionality",
        "scope_compliance",
        "silent_data_loss",
    }
)
SEMANTIC_REVIEW_CHECK_IDS: Final[frozenset[str]] = frozenset(
    {"systemic_adequacy"}
)
DOC_FIDELITY_CHECK_IDS: Final[frozenset[str]] = frozenset({"impl_fidelity"})
STORY_CREATION_REVIEW_CHECK_IDS: Final[frozenset[str]] = frozenset(
    {"conflict_assessment"}
)

_ROLE_CHECK_IDS = (
    QA_REVIEW_CHECK_IDS
    | SEMANTIC_REVIEW_CHECK_IDS
    | DOC_FIDELITY_CHECK_IDS
    | STORY_CREATION_REVIEW_CHECK_IDS
)

_BUILTIN_NATIVE_CHECK_IDS: frozenset[str] = frozenset(
    {
        "adversarial_runtime",
        "context_exists",
        "context_valid",
        "doc_fidelity.missing_docstring",
        "doc_fidelity.no_concept_anchor",
        "doc_fidelity.pydantic_config_missing",
        "fast_tests_green",
        "implementation_evidence.required_after_exploration",
        "layer2_input.missing",
        "layer2_llm.failure",
        "layer_execution",
        "no_corrupt_state",
        "no_test_executed",
        "phase_snapshots",
        "proven_finding",
        "qa_review.coverage_unknown",
        "qa_review.edge_cases_thin",
        "qa_review.no_tests",
        "semantic.dangling_concept_ref",
        "semantic.naming_violation",
        "semantic.todo_in_production",
        "sonarqube_green_gate",
        "sparring_missing",
    }
)

#: Explicit registry evidence that these built-in checks have no FC origin.
#: Unknown check IDs are intentionally absent and therefore fail closed at the
#: outcome-emission boundary.
NATIVE_CHECK_ORIGIN_REFS: Final[Mapping[str, str | None]] = (
    MappingProxyType(
        {
            check_id: None
            for check_id in _BUILTIN_NATIVE_CHECK_IDS | _ROLE_CHECK_IDS
        }
    )
)

__all__ = [
    "DOC_FIDELITY_CHECK_IDS",
    "NATIVE_CHECK_ORIGIN_REFS",
    "QA_REVIEW_CHECK_IDS",
    "SEMANTIC_REVIEW_CHECK_IDS",
    "STORY_CREATION_REVIEW_CHECK_IDS",
]
