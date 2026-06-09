"""Contract pinning for the IntegrityGate dimensions and preflight checks.

Pins the canonical FK-35 §35.2.4 dimension IDs/FAIL-codes (AG3-034 T1), the
§35.2.3 mandatory pre-stage list + pre-stage FAIL-codes, the code-only routing
(§2.1.4), the Dim-9 / green-main applicability geltung (FK-33 §33.6.5) and the
ten preflight check IDs (FK-22 §22.3.1).  A change to any of these wire
contracts must be a conscious, reviewed edit (FK-71 / Tests-Konzepttreue).
"""

from __future__ import annotations

from agentkit.governance.integrity_gate.dim9_sonar import SONAR_NOT_GREEN
from agentkit.governance.integrity_gate.dimensions import (
    CODE_ONLY_DIMENSIONS,
    MANDATORY_DIMENSIONS,
    MISSING_PRESTAGE_CODE,
    IntegrityDimension,
    dimensions_for,
    mandatory_dimensions_for,
)
from agentkit.governance.setup_preflight_gate.preflight import (
    PreflightCheckId,
    PreflightStatus,
)
from agentkit.story_context_manager.types import StoryType


def test_integrity_dimension_ids_are_canonical_fk35_plus_fk55() -> None:
    # FK-35 §35.2.4 canonical IDs plus FK-55 conflict-freeze proof.
    assert [d.value for d in IntegrityDimension] == [
        "NO_QA_ARTIFACTS",
        "CONTEXT_INVALID",
        "STRUCTURAL_SHALLOW",
        "DECISION_INVALID",
        "NO_LLM_REVIEW",
        "NO_ADVERSARIAL",
        "NO_VERIFY",
        "TIMESTAMP_INVERSION",
        "CONFLICT_FREEZE_PROOF",
        "SONARQUBE_GREEN",
    ]


def test_dim9_fail_code_is_sonar_not_green() -> None:
    assert SONAR_NOT_GREEN == "SONAR_NOT_GREEN"


def test_mandatory_prestage_fail_codes_are_pinned() -> None:
    # §35.2.3 pre-stage codes stay distinct from the §35.2.4 dimension IDs.
    assert MISSING_PRESTAGE_CODE == {
        IntegrityDimension.NO_QA_ARTIFACTS: "MISSING_STRUCTURAL",
        IntegrityDimension.CONTEXT_INVALID: "MISSING_CONTEXT",
        IntegrityDimension.DECISION_INVALID: "MISSING_DECISION",
    }


def test_mandatory_prestage_dimensions_are_pinned() -> None:
    assert MANDATORY_DIMENSIONS == (
        IntegrityDimension.NO_QA_ARTIFACTS,
        IntegrityDimension.DECISION_INVALID,
        IntegrityDimension.CONTEXT_INVALID,
    )


def test_code_only_dimensions_are_dim5_and_dim6() -> None:
    assert CODE_ONLY_DIMENSIONS == (
        IntegrityDimension.NO_LLM_REVIEW,
        IntegrityDimension.NO_ADVERSARIAL,
    )


def test_mandatory_dimensions_for_noncode_is_context_only() -> None:
    for story_type in (StoryType.CONCEPT, StoryType.RESEARCH):
        assert mandatory_dimensions_for(story_type) == (
            IntegrityDimension.CONTEXT_INVALID,
        )
    for story_type in (StoryType.IMPLEMENTATION, StoryType.BUGFIX):
        assert mandatory_dimensions_for(story_type) == MANDATORY_DIMENSIONS


def test_dimensions_for_code_applicable_is_full_nine() -> None:
    # APPLICABLE impl/bugfix -> Dim 9 included (post-mandatory set).
    assert dimensions_for(
        StoryType.IMPLEMENTATION, sonar_applicable=True
    ) == (
        IntegrityDimension.STRUCTURAL_SHALLOW,
        IntegrityDimension.NO_LLM_REVIEW,
        IntegrityDimension.NO_ADVERSARIAL,
        IntegrityDimension.NO_VERIFY,
        IntegrityDimension.TIMESTAMP_INVERSION,
        IntegrityDimension.CONFLICT_FREEZE_PROOF,
        IntegrityDimension.SONARQUBE_GREEN,
    )


def test_dimensions_for_code_not_applicable_drops_dim9() -> None:
    # NOT_APPLICABLE (available==false / fast) -> Dim 9 omitted, no FAIL.
    assert (
        IntegrityDimension.SONARQUBE_GREEN
        not in dimensions_for(StoryType.IMPLEMENTATION, sonar_applicable=False)
    )


def test_dimensions_for_noncode_drops_code_only_and_dim9() -> None:
    # Concept/research never evaluate Dim 3/5/6/7/9 (the structural-artifact,
    # LLM/adversarial, verify and Sonar dimensions are code-only — concept/
    # research have no structural QA layer).  Universal timestamp causality and
    # FK-55 conflict-freeze proof remain post-mandatory.
    dims = dimensions_for(StoryType.CONCEPT, sonar_applicable=True)
    assert dims == (
        IntegrityDimension.TIMESTAMP_INVERSION,
        IntegrityDimension.CONFLICT_FREEZE_PROOF,
    )
    assert IntegrityDimension.SONARQUBE_GREEN not in dims
    assert IntegrityDimension.STRUCTURAL_SHALLOW not in dims


def test_ten_preflight_check_ids_are_pinned() -> None:
    assert [c.value for c in PreflightCheckId] == [
        "story_exists",
        "story_attributes_consistent",
        "status_approved",
        "dependencies_done",
        "no_execution_artifacts",
        "no_active_runtime_residue",
        "no_story_branch",
        "no_stale_worktree",
        "no_scope_overlap",
        "no_competing_story_mode_active",
    ]


def test_preflight_status_values_are_pinned() -> None:
    assert [s.value for s in PreflightStatus] == ["PASS", "FAIL"]
