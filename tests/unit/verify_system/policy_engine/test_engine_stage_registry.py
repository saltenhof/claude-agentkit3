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


def _finding(severity: Severity, layer: str = "structural") -> Finding:
    return Finding(
        layer=layer,
        check="c",
        severity=severity,
        message=f"{severity.value}",
        trust_class=TrustClass.SYSTEM,
    )


def _structural(passed: bool, findings: tuple[Finding, ...] = ()) -> LayerResult:
    return LayerResult(layer="structural", passed=passed, findings=findings)


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
            [_structural(passed=True, findings=majors)],
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
            [_structural(passed=True, findings=majors)],
            story_type=StoryType.IMPLEMENTATION,
            max_layer_reached=1,
        )
        assert result.verdict is PolicyVerdict.FAIL

    def test_custom_per_type_threshold(self) -> None:
        engine = PolicyEngine(
            max_major_findings_per_story_type={StoryType.BUGFIX: 0}
        )
        result = engine.decide(
            [_structural(passed=True, findings=(_finding(Severity.MAJOR),))],
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

    def test_present_structural_result_no_missing_finding(self) -> None:
        """A present (passing) structural result satisfies the layer-1 stages."""
        engine = PolicyEngine()
        result = engine.decide(
            [_structural(passed=True)],
            story_type=StoryType.IMPLEMENTATION,
            max_layer_reached=1,
        )
        assert result.verdict is PolicyVerdict.PASS
        assert not any(f.layer == "policy" for f in result.all_findings)

    def test_untraversed_deeper_layer_not_required(self) -> None:
        """FK-33 §33.7.2: a layer never reached is NOT required (no fail)."""
        engine = PolicyEngine()
        # Only layer 1 traversed; layer 2/3 stages must not be demanded.
        result = engine.decide(
            [_structural(passed=True)],
            story_type=StoryType.IMPLEMENTATION,
            max_layer_reached=1,
        )
        assert result.verdict is PolicyVerdict.PASS

    def test_no_missing_check_without_story_type(self) -> None:
        """Backward-compat: no story_type -> no missing-artifact check at all."""
        engine = PolicyEngine()
        result = engine.decide([])
        assert result.verdict is PolicyVerdict.PASS

    def test_concept_story_has_no_required_layer1_stages(self) -> None:
        """Concept stories carry no Layer-1 stages (FK-33 §33.2.4) -> no fail."""
        engine = PolicyEngine()
        result = engine.decide(
            [], story_type=StoryType.CONCEPT, max_layer_reached=1
        )
        assert result.verdict is PolicyVerdict.PASS
