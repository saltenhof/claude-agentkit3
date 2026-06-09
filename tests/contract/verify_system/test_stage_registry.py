"""Contract test: pin every Layer-1 stage definition + severity (FK-27 §27.4).

This test is the executable grounding of AG3-042: it pins each
``StageDefinition`` (stage_id, layer, severity, applicability, escalation,
ARE-gating) against FK-27 §27.4.1/§27.4.2/§27.4.3/§27.4.4 VERBATIM. Where the
AG3-042 story summary table disagreed with FK-27, FK-27 wins (see
``data.py``); this test pins the FK-27 truth so any drift breaks the contract.
"""

from __future__ import annotations

from agentkit.core_types import Severity
from agentkit.story_context_manager.types import StoryType
from agentkit.verify_system.stage_registry import (
    LAYER_1_STAGES,
    ExecutionPolicy,
    StageRegistry,
)

#: The canonical FK-27 §27.4 Layer-1 stage -> severity contract.
#: artifact (§27.4.1, all BLOCKING) / structural+build+test+hygiene+impact
#: (§27.4.2) / recurring guards (§27.4.3) / ARE (§27.4.4).
_EXPECTED_SEVERITY: dict[str, Severity] = {
    # §27.4.1 Artefakt-Pruefung (all BLOCKING)
    "artifact.protocol": Severity.BLOCKING,
    "artifact.worker_manifest": Severity.BLOCKING,
    "artifact.manifest_claims": Severity.BLOCKING,
    "artifact.handover": Severity.BLOCKING,
    # §27.4.2 Branch & Completion (all BLOCKING)
    "branch.story": Severity.BLOCKING,
    "branch.commit_trailers": Severity.BLOCKING,
    "completion.commit": Severity.BLOCKING,
    "completion.push": Severity.BLOCKING,
    # §27.4.2 Security
    "security.secrets": Severity.BLOCKING,
    "security.secrets_content": Severity.BLOCKING,
    # §27.4.2 Build & Test
    "build.compile": Severity.BLOCKING,
    "build.test_execution": Severity.BLOCKING,
    "test.count": Severity.MAJOR,
    "test.coverage": Severity.MAJOR,
    # §27.4.2 Code-Hygiene (all MINOR per FK-27 §27.4.2)
    "hygiene.todo_fixme": Severity.MINOR,
    "hygiene.disabled_tests": Severity.MINOR,
    "hygiene.commented_code": Severity.MINOR,
    # §27.4.3 Recurring Guards (REF-036: llm_reviews + multi_llm BLOCKING)
    "guard.llm_reviews": Severity.BLOCKING,
    "guard.review_compliance": Severity.MAJOR,
    "guard.no_violations": Severity.BLOCKING,
    "guard.multi_llm": Severity.BLOCKING,
    # §27.4.4 ARE-Gate
    "are.gate": Severity.BLOCKING,
    # §27.4.2 Impact (BLOCKING; routes to ESCALATED per §27.4.5)
    "impact.violation": Severity.BLOCKING,
    # Bugfix-only evidence gates
    "bugfix.reproducer_manifest": Severity.BLOCKING,
    "bugfix.red_evidence": Severity.BLOCKING,
    "bugfix.green_evidence": Severity.BLOCKING,
    "bugfix.suite_evidence": Severity.BLOCKING,
    "bugfix.red_green_consistency": Severity.BLOCKING,
}


def test_at_least_19_stages() -> None:
    """AG3-042 AC2: at least 19 Layer-1 stage definitions exist."""
    assert len(LAYER_1_STAGES) >= 19


def test_stage_ids_match_fk27_catalogue() -> None:
    """Every stage id is exactly the FK-27 §27.4 catalogue (no extras/missing)."""
    actual = {s.stage_id for s in LAYER_1_STAGES}
    assert actual == set(_EXPECTED_SEVERITY)


def test_every_stage_severity_matches_fk27() -> None:
    """AG3-042 AC2: each stage carries the FK-27 §27.4.2 severity verbatim."""
    for stage in LAYER_1_STAGES:
        assert stage.severity is _EXPECTED_SEVERITY[stage.stage_id], (
            f"{stage.stage_id} severity drift: {stage.severity} != "
            f"{_EXPECTED_SEVERITY[stage.stage_id]}"
        )


def test_all_stages_are_layer_1() -> None:
    """The Layer-1 catalogue carries only ``layer == 1`` stages."""
    assert all(s.layer == 1 for s in LAYER_1_STAGES)


def test_llm_review_gates_are_two_separate_blocking_stages() -> None:
    """AG3-042 AC4 / REF-036: llm_reviews and multi_llm are SEPARATE BLOCKING."""
    by_id = {s.stage_id: s for s in LAYER_1_STAGES}
    assert by_id["guard.llm_reviews"].severity is Severity.BLOCKING
    assert by_id["guard.multi_llm"].severity is Severity.BLOCKING
    assert by_id["guard.llm_reviews"] is not by_id["guard.multi_llm"]


def test_impact_violation_is_escalated() -> None:
    """AG3-042 AC8 / FK-27 §27.4.5: impact.violation routes to ESCALATED."""
    by_id = {s.stage_id: s for s in LAYER_1_STAGES}
    assert by_id["impact.violation"].escalated is True
    assert by_id["impact.violation"].severity is Severity.BLOCKING
    # It is the ONLY escalating stage.
    escalating = [s.stage_id for s in LAYER_1_STAGES if s.escalated]
    assert escalating == ["impact.violation"]


def test_are_gate_is_feature_gated() -> None:
    """AG3-042 AC7 / FK-27 §27.4.4: are.gate is the only feature-gated stage."""
    feature_gated = [s.stage_id for s in LAYER_1_STAGES if s.feature_gated_are]
    assert feature_gated == ["are.gate"]


def test_code_producing_applicability() -> None:
    """General stages apply to implementation+bugfix; bugfix gates only to bugfix."""
    for stage in LAYER_1_STAGES:
        if stage.stage_id.startswith("bugfix."):
            assert stage.applies_to == frozenset((StoryType.BUGFIX,))
        else:
            assert stage.applies_to == frozenset(
                (StoryType.IMPLEMENTATION, StoryType.BUGFIX)
            )


def test_registry_stages_for_concept_research_are_story_type_specific() -> None:
    """Concept/research stages stay scoped to their own story types."""
    registry = StageRegistry()
    assert [stage.stage_id for stage in registry.stages_for(StoryType.CONCEPT)] == [
        "concept_feedback"
    ]
    assert registry.layer1_stages_for(StoryType.CONCEPT, are_enabled=False) == []
    assert [stage.stage_id for stage in registry.stages_for(StoryType.RESEARCH)] == [
        "research_quality"
    ]
    assert [
        stage.stage_id
        for stage in registry.layer1_stages_for(
            StoryType.RESEARCH, are_enabled=False
        )
    ] == ["research_quality"]


def test_registry_layer1_are_gating() -> None:
    """FK-27 §27.4.4: are.gate is included only when ARE is enabled."""
    registry = StageRegistry()
    off = {
        s.stage_id
        for s in registry.layer1_stages_for(
            StoryType.IMPLEMENTATION, are_enabled=False
        )
    }
    on = {
        s.stage_id
        for s in registry.layer1_stages_for(
            StoryType.IMPLEMENTATION, are_enabled=True
        )
    }
    assert "are.gate" not in off
    assert "are.gate" in on
    assert on - off == {"are.gate"}


def test_default_execution_policy_is_always_for_artifact_and_guards() -> None:
    """FK-33 §33.2.2: deterministic stages default to ALWAYS execution policy."""
    by_id = {s.stage_id: s for s in LAYER_1_STAGES}
    assert by_id["artifact.protocol"].execution_policy is ExecutionPolicy.ALWAYS
    assert by_id["guard.llm_reviews"].execution_policy is ExecutionPolicy.ALWAYS
