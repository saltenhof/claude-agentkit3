"""PolicyEngine stage-registry binding tests (AG3-042, FK-33 §33.7).

Covers the per-story-type MAJOR threshold model (replacing the v2
``max_high_findings`` scalar) and the fail-closed missing-artifact check over
a traversed layer.
"""

from __future__ import annotations

from agentkit.core_types import PolicyVerdict, Severity
from agentkit.story_context_manager.types import StoryType
from agentkit.verify_system.policy_engine.engine import (
    DEFAULT_MAJOR_THRESHOLD,
    PolicyEngine,
)
from agentkit.verify_system.protocols import Finding, LayerResult, TrustClass
from agentkit.verify_system.stage_registry import StageRegistry


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
        metadata={
            "stage_ids": tuple(
                stage.stage_id
                for stage in registry.layer1_stages_for(
                    story_type, are_enabled=False
                )
            )
        },
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
            max_layer_reached=1,
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
            max_layer_reached=1,
        )
        assert result.verdict is PolicyVerdict.FAIL

    def test_custom_per_type_threshold(self) -> None:
        engine = PolicyEngine(
            max_major_findings_per_story_type={StoryType.BUGFIX: 0}
        )
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
            max_layer_reached=1,
        )
        assert result.verdict is PolicyVerdict.FAIL

    def test_scalar_fallback_without_story_type(self) -> None:
        """Without story_type the legacy scalar is used (backward-compatible)."""
        engine = PolicyEngine(max_major_findings=0)
        result = engine.decide(
            [_structural(passed=True, findings=(_finding(Severity.MAJOR),))]
        )
        assert result.verdict is PolicyVerdict.FAIL


class TestFailClosedMissingArtifact:
    def test_missing_traversed_layer1_result_fails_closed(self) -> None:
        """FK-33 §33.7: layer 1 traversed but NO result -> fail-closed FAIL."""
        engine = PolicyEngine()
        result = engine.decide(
            [],  # no LayerResult at all
            story_type=StoryType.IMPLEMENTATION,
            max_layer_reached=1,
        )
        assert result.verdict is PolicyVerdict.FAIL
        assert any(
            f.severity is Severity.BLOCKING and f.layer == "policy"
            for f in result.all_findings
        )

    def test_present_structural_and_sonarqube_results_no_missing_finding(self) -> None:
        """Stage-id results satisfy the required Layer-1 stages."""
        engine = PolicyEngine()
        result = engine.decide(
            [_structural(passed=True), _sonarqube()],
            story_type=StoryType.IMPLEMENTATION,
            max_layer_reached=1,
        )
        assert result.verdict is PolicyVerdict.PASS


class TestContextSufficiencyWarnings:
    def test_missing_context_sufficiency_has_no_warning(self) -> None:
        result = PolicyEngine().decide([], context_sufficiency_artifact=None)
        assert result.verdict is PolicyVerdict.PASS
        assert result.warnings == ()

    def test_sufficient_context_sufficiency_has_no_warning(self) -> None:
        result = PolicyEngine().decide(
            [], context_sufficiency_artifact={"sufficiency": "sufficient"}
        )
        assert result.verdict is PolicyVerdict.PASS
        assert result.warnings == ()

    def test_partial_context_sufficiency_adds_warning_without_fail(self) -> None:
        result = PolicyEngine().decide(
            [],
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
            [], context_sufficiency_artifact={"sufficiency": 123}
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
            max_layer_reached=1,
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
            max_layer_reached=1,
        )
        assert result.verdict is PolicyVerdict.PASS

    def test_no_missing_check_without_story_type(self) -> None:
        """Backward-compat: no story_type -> no missing-artifact check at all."""
        engine = PolicyEngine()
        result = engine.decide([])
        assert result.verdict is PolicyVerdict.PASS

    def test_concept_story_has_no_traversed_layer1_stages(self) -> None:
        """Concept aggregate stage is Layer 2, so Layer 1 traversal is empty."""
        engine = PolicyEngine()
        result = engine.decide(
            [], story_type=StoryType.CONCEPT, max_layer_reached=1
        )
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
