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

LAYER2_INPUT_MISSING_CHECK_ID: Final = "layer2_input.missing"
QA_REVIEW_NO_TESTS_CHECK_ID: Final = "qa_review.no_tests"
QA_REVIEW_COVERAGE_UNKNOWN_CHECK_ID: Final = "qa_review.coverage_unknown"
QA_REVIEW_EDGE_CASES_THIN_CHECK_ID: Final = "qa_review.edge_cases_thin"
SEMANTIC_TODO_IN_PRODUCTION_CHECK_ID: Final = "semantic.todo_in_production"
SEMANTIC_DANGLING_CONCEPT_REF_CHECK_ID: Final = "semantic.dangling_concept_ref"
SEMANTIC_NAMING_VIOLATION_CHECK_ID: Final = "semantic.naming_violation"

PHASE_SNAPSHOT_CHECK_IDS: Final[Mapping[str, str]] = MappingProxyType(
    {
        "setup": "phase_snapshots.setup",
        "exploration": "phase_snapshots.exploration",
        "implementation": "phase_snapshots.implementation",
        "closure": "phase_snapshots.closure",
    }
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
        LAYER2_INPUT_MISSING_CHECK_ID,
        "layer2_llm.failure",
        "layer_execution",
        "no_corrupt_state",
        "no_test_executed",
        "proven_finding",
        QA_REVIEW_COVERAGE_UNKNOWN_CHECK_ID,
        QA_REVIEW_EDGE_CASES_THIN_CHECK_ID,
        QA_REVIEW_NO_TESTS_CHECK_ID,
        SEMANTIC_DANGLING_CONCEPT_REF_CHECK_ID,
        SEMANTIC_NAMING_VIOLATION_CHECK_ID,
        SEMANTIC_TODO_IN_PRODUCTION_CHECK_ID,
        "sonarqube_green_gate",
        "sparring_missing",
    }
)

#: Explicit registry evidence that these built-in checks have no FC origin.
#: Unknown check IDs are intentionally absent and therefore fail closed at the
#: outcome-emission boundary.
NATIVE_CHECK_ORIGIN_REFS: Final[Mapping[str, str | None]] = (
    MappingProxyType(
        dict.fromkeys(
            _BUILTIN_NATIVE_CHECK_IDS
            | _ROLE_CHECK_IDS
            | frozenset(PHASE_SNAPSHOT_CHECK_IDS.values())
        )
    )
)


def phase_snapshot_check_id(phase: str) -> str:
    """Return the registered check identity for one canonical phase."""
    try:
        return PHASE_SNAPSHOT_CHECK_IDS[phase]
    except KeyError as exc:
        raise ValueError(f"unknown phase snapshot check phase: {phase!r}") from exc

__all__ = [
    "DOC_FIDELITY_CHECK_IDS",
    "LAYER2_INPUT_MISSING_CHECK_ID",
    "NATIVE_CHECK_ORIGIN_REFS",
    "PHASE_SNAPSHOT_CHECK_IDS",
    "QA_REVIEW_COVERAGE_UNKNOWN_CHECK_ID",
    "QA_REVIEW_CHECK_IDS",
    "QA_REVIEW_EDGE_CASES_THIN_CHECK_ID",
    "QA_REVIEW_NO_TESTS_CHECK_ID",
    "SEMANTIC_DANGLING_CONCEPT_REF_CHECK_ID",
    "SEMANTIC_NAMING_VIOLATION_CHECK_ID",
    "SEMANTIC_REVIEW_CHECK_IDS",
    "SEMANTIC_TODO_IN_PRODUCTION_CHECK_ID",
    "STORY_CREATION_REVIEW_CHECK_IDS",
    "phase_snapshot_check_id",
]
