"""PolicyEngine stage-registry binding tests (AG3-042, FK-33 §33.7).

Covers the per-story-type MAJOR threshold model (replacing the v2
``max_high_findings`` scalar) and the fail-closed missing-artifact check over
a traversed layer.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime

import pytest

from agentkit.backend.core_types import PolicyVerdict, Severity
from agentkit.backend.phase_state_store.models import FlowExecution
from agentkit.backend.story_context_manager.types import StoryType
from agentkit.backend.verify_system.policy_engine.engine import (
    DEFAULT_MAJOR_THRESHOLD,
    PolicyEngine,
)
from agentkit.backend.verify_system.protocols import Finding, LayerResult, TrustClass
from agentkit.backend.verify_system.qa_read_models import build_qa_stage_result
from agentkit.backend.verify_system.stage_registry import StageRegistry


def _finding(severity: Severity, layer: str = "structural") -> Finding:
    return Finding(
        layer=layer,
        check="c",
        severity=severity,
        message=f"{severity.value}",
        trust_class=TrustClass.SYSTEM,
    )


def _structural(
    passed: bool,
    findings: tuple[Finding, ...] = (),
    *,
    story_type: StoryType = StoryType.IMPLEMENTATION,
) -> LayerResult:
    registry = StageRegistry()
    return LayerResult(
        layer="structural",
        passed=passed,
        findings=findings,
        metadata={"stage_ids": tuple(stage.stage_id for stage in registry.layer1_stages_for(story_type, are_enabled=False))},
    )


def _sonarqube(passed: bool = True) -> LayerResult:
    return LayerResult(layer="sonarqube_gate", passed=passed)


class TestPerStoryTypeThreshold:
    def test_default_threshold_is_three(self) -> None:
        engine = PolicyEngine()
        assert engine.threshold_for(StoryType.IMPLEMENTATION) == DEFAULT_MAJOR_THRESHOLD
        assert engine.threshold_for(StoryType.BUGFIX) == DEFAULT_MAJOR_THRESHOLD

    def test_three_majors_pass_at_default_threshold(self) -> None:
        """FK-33 §33.7.3: major_failures <= 3 (default) -> PASS."""
        engine = PolicyEngine()
        majors = tuple(_finding(Severity.MAJOR) for _ in range(3))
        result = engine.decide(
            [_structural(passed=True, findings=majors), _sonarqube()],
            story_type=StoryType.IMPLEMENTATION,
            traversed_layers=frozenset({1, 4}),
        )
        assert result.verdict is PolicyVerdict.PASS
        assert result.max_major_findings == DEFAULT_MAJOR_THRESHOLD

    def test_four_majors_fail_at_default_threshold(self) -> None:
        """FK-33 §33.7.3: major_failures > 3 -> FAIL even without BLOCKING."""
        engine = PolicyEngine()
        majors = tuple(_finding(Severity.MAJOR) for _ in range(4))
        result = engine.decide(
            [_structural(passed=True, findings=majors), _sonarqube()],
            story_type=StoryType.IMPLEMENTATION,
            traversed_layers=frozenset({1, 4}),
        )
        assert result.verdict is PolicyVerdict.FAIL

    def test_custom_per_type_threshold(self) -> None:
        engine = PolicyEngine(max_major_findings_per_story_type={StoryType.BUGFIX: 0})
        result = engine.decide(
            [
                _structural(
                    passed=True,
                    findings=(_finding(Severity.MAJOR),),
                    story_type=StoryType.BUGFIX,
                ),
                _sonarqube(),
            ],
            story_type=StoryType.BUGFIX,
            traversed_layers=frozenset({1, 4}),
        )
        assert result.verdict is PolicyVerdict.FAIL

    def test_missing_story_type_threshold_fails_closed(self) -> None:
        """AC3: an incomplete story-type threshold model cannot judge."""
        engine = PolicyEngine(max_major_findings_per_story_type={StoryType.BUGFIX: 0})

        with pytest.raises(ValueError, match="story_type 'implementation'"):
            engine.decide(
                [_structural(passed=True)],
                story_type=StoryType.IMPLEMENTATION,
                traversed_layers=frozenset({4}),
            )


class TestFailClosedMissingArtifact:
    def test_traversed_layers_is_required(self) -> None:
        """The policy engine never infers traversal from produced results."""
        with pytest.raises(TypeError, match="traversed_layers"):
            PolicyEngine().decide([], story_type=StoryType.IMPLEMENTATION)

    @pytest.mark.parametrize(
        ("route", "reason"),
        [
            (frozenset(), "must not be empty"),
            (frozenset({1}), "mandatory policy layer 4"),
            (frozenset({4, 5}), "unknown layer"),
        ],
    )
    def test_invalid_route_evidence_fails_closed_before_verdict(self, route: frozenset[int], reason: str) -> None:
        """Empty, incomplete, and unknown routes cannot produce a verdict."""
        with pytest.raises(ValueError, match=reason):
            PolicyEngine().decide(
                [],
                story_type=StoryType.IMPLEMENTATION,
                traversed_layers=route,
            )

    def test_missing_traversed_layer1_result_fails_closed(self) -> None:
        """FK-33 §33.7: layer 1 traversed but NO result -> fail-closed FAIL."""
        engine = PolicyEngine()
        result = engine.decide(
            [],  # no LayerResult at all
            story_type=StoryType.IMPLEMENTATION,
            traversed_layers=frozenset({1, 4}),
        )
        assert result.verdict is PolicyVerdict.FAIL
        assert any(f.severity is Severity.BLOCKING and f.layer == "policy" for f in result.all_findings)

    def test_present_structural_and_sonarqube_results_no_missing_finding(self) -> None:
        """Stage-id results satisfy the required Layer-1 stages."""
        engine = PolicyEngine()
        result = engine.decide(
            [_structural(passed=True), _sonarqube()],
            story_type=StoryType.IMPLEMENTATION,
            traversed_layers=frozenset({1, 4}),
        )
        assert result.verdict is PolicyVerdict.PASS

    def test_known_foreign_stage_claim_is_rejected_by_productive_policy_caller(
        self,
    ) -> None:
        """A result cannot claim another registered result's missing stage."""
        forged = LayerResult(
            layer="qa_review",
            passed=True,
            metadata={
                "executed_check_ids": ("qa_review",),
                "stage_ids": ("semantic_review",),
            },
        )

        with pytest.raises(ValueError, match="does not match registry and execution plan"):
            PolicyEngine().decide(
                [forged],
                story_type=StoryType.IMPLEMENTATION,
                traversed_layers=frozenset({2, 4}),
            )


class TestContextSufficiencyWarnings:
    def test_missing_context_sufficiency_has_no_warning(self) -> None:
        result = PolicyEngine().decide(
            [],
            story_type=StoryType.CONCEPT,
            traversed_layers=frozenset({4}),
            context_sufficiency_artifact=None,
        )
        assert result.verdict is PolicyVerdict.PASS
        assert result.warnings == ()

    def test_sufficient_context_sufficiency_has_no_warning(self) -> None:
        result = PolicyEngine().decide(
            [],
            story_type=StoryType.CONCEPT,
            traversed_layers=frozenset({4}),
            context_sufficiency_artifact={"sufficiency": "sufficient"},
        )
        assert result.verdict is PolicyVerdict.PASS
        assert result.warnings == ()

    def test_partial_context_sufficiency_adds_warning_without_fail(self) -> None:
        result = PolicyEngine().decide(
            [],
            story_type=StoryType.CONCEPT,
            traversed_layers=frozenset({4}),
            context_sufficiency_artifact={
                "sufficiency": "partial",
                "gaps": ["missing design"],
            },
        )
        assert result.verdict is PolicyVerdict.PASS
        assert len(result.warnings) == 1
        assert result.warnings[0].stage_id == "context_sufficiency"
        assert result.warnings[0].source_artifact == "context_sufficiency.json"

    def test_malformed_context_sufficiency_has_no_warning_or_fail(self) -> None:
        result = PolicyEngine().decide(
            [],
            story_type=StoryType.CONCEPT,
            traversed_layers=frozenset({4}),
            context_sufficiency_artifact={"sufficiency": 123},
        )
        assert result.verdict is PolicyVerdict.PASS
        assert result.warnings == ()
        assert not any(f.layer == "policy" for f in result.all_findings)

    def test_structural_result_does_not_mask_missing_sonarqube_gate(self) -> None:
        """Regression: structural cannot stand in for sonarqube_gate."""
        engine = PolicyEngine()
        result = engine.decide(
            [_structural(passed=True)],
            story_type=StoryType.IMPLEMENTATION,
            traversed_layers=frozenset({1, 4}),
        )
        assert result.verdict is PolicyVerdict.FAIL
        assert any(f.check == "sonarqube_gate" for f in result.all_findings)

    def test_untraversed_deeper_layer_not_required(self) -> None:
        """FK-33 §33.7.2: a layer never reached is NOT required (no fail)."""
        engine = PolicyEngine()
        # Only layer 1 traversed; layer 2/3 stages must not be demanded.
        result = engine.decide(
            [_structural(passed=True), _sonarqube()],
            story_type=StoryType.IMPLEMENTATION,
            traversed_layers=frozenset({1, 4}),
        )
        assert result.verdict is PolicyVerdict.PASS

    def test_concept_story_has_no_traversed_layer1_stages(self) -> None:
        """Concept aggregate stage is Layer 2, so Layer 1 traversal is empty."""
        engine = PolicyEngine()
        result = engine.decide([], story_type=StoryType.CONCEPT, traversed_layers=frozenset({1, 4}))
        assert result.verdict is PolicyVerdict.PASS

    def test_non_contiguous_exploration_route_does_not_require_layer1(self) -> None:
        """Regression: route {2, 4} does not demand structural or Sonar."""
        engine = PolicyEngine()
        result = engine.decide(
            [
                LayerResult(layer="qa_review", passed=True),
                LayerResult(layer="semantic_review", passed=True),
                LayerResult(layer="doc_fidelity", passed=True),
            ],
            story_type=StoryType.IMPLEMENTATION,
            traversed_layers=frozenset({2, 4}),
        )
        assert result.verdict is PolicyVerdict.PASS
        assert not any(f.check in {"artifact.protocol", "sonarqube_gate"} for f in result.all_findings)


def test_policy_and_projection_use_same_bound_result_name_mapping() -> None:
    """AC2: two productive consumers resolve one injected registry mapping."""
    canonical = StageRegistry()
    stages = tuple(
        replace(stage, layer_result_name="mapped_qa_review") if stage.stage_id == "qa_review" else stage
        for stage in canonical.stages
    )
    registry = StageRegistry(stages=stages)
    result = LayerResult(
        layer="mapped_qa_review",
        passed=True,
        metadata={"executed_check_ids": ("qa_review",)},
    )

    decision = PolicyEngine(stage_registry=registry).decide(
        [
            result,
            LayerResult(layer="semantic_review", passed=True),
            LayerResult(layer="doc_fidelity", passed=True),
        ],
        story_type=StoryType.IMPLEMENTATION,
        traversed_layers=frozenset({2, 4}),
    )
    projected = build_qa_stage_result(
        FlowExecution(
            project_key="project",
            story_id="AG3-191",
            run_id="run-1",
            flow_id="implementation",
            level="story",
            owner="pipeline_engine",
            status="IN_PROGRESS",
        ),
        result,
        attempt_no=1,
        artifact_id="qa_review.json",
        recorded_at=datetime(2026, 8, 4, tzinfo=UTC),
        stage_registry=registry,
    )

    assert decision.verdict is PolicyVerdict.PASS
    assert not any(finding.check == "qa_review" for finding in decision.all_findings)
    assert projected.stage_id == "qa_review"
