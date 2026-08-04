"""Unit tests for StageRegistry.stages_for / layer1_stages_for (FK-33 §33.2.4)."""

from __future__ import annotations

import pytest

from agentkit.backend.core_types import Severity
from agentkit.backend.core_types.qa_artifact_names import (
    ADVERSARIAL_PRODUCER,
    BUGFIX_GREEN_EVIDENCE_PRODUCER,
    BUGFIX_RED_EVIDENCE_PRODUCER,
    BUGFIX_RED_GREEN_CONSISTENCY_PRODUCER,
    BUGFIX_REPRODUCER_MANIFEST_PRODUCER,
    BUGFIX_SUITE_EVIDENCE_PRODUCER,
    CONCEPT_FEEDBACK_PRODUCER,
    CONTEXT_SUFFICIENCY_PRODUCER,
    DOC_FIDELITY_PRODUCER,
    POLICY_PRODUCER,
    QA_REVIEW_PRODUCER,
    RESEARCH_QUALITY_PRODUCER,
    SEMANTIC_REVIEW_PRODUCER,
    SONARQUBE_GATE_PRODUCER,
)
from agentkit.backend.story_context_manager.types import StoryType
from agentkit.backend.verify_system.protocols import TrustClass
from agentkit.backend.verify_system.stage_registry import (
    ExecutionPolicy,
    StageDefinition,
    StageKind,
    StageOverridePolicy,
    StageRegistry,
)


def _stage(stage_id: str, layer: int, types: set[StoryType]) -> StageDefinition:
    return StageDefinition(
        stage_id=stage_id,
        layer=layer,
        severity=Severity.BLOCKING,
        applies_to=frozenset(types),
        execution_policy=ExecutionPolicy.ALWAYS,
    )


class TestStagesFor:
    def test_default_registry_returns_all_for_implementation(self) -> None:
        registry = StageRegistry()
        impl = registry.stages_for(StoryType.IMPLEMENTATION)
        assert len(impl) >= 19
        assert all(StoryType.IMPLEMENTATION in s.applies_to for s in impl)

    def test_default_registry_returns_all_for_bugfix(self) -> None:
        registry = StageRegistry()
        bug = registry.stages_for(StoryType.BUGFIX)
        assert len(bug) >= 19

    def test_concept_and_research_get_aggregate_stages(self) -> None:
        registry = StageRegistry()
        assert [s.stage_id for s in registry.stages_for(StoryType.CONCEPT)] == ["concept_feedback"]
        assert [s.stage_id for s in registry.stages_for(StoryType.RESEARCH)] == ["research_quality"]

    def test_filters_by_applies_to(self) -> None:
        registry = StageRegistry(
            stages=(
                _stage("a.one", 1, {StoryType.IMPLEMENTATION}),
                _stage("a.two", 1, {StoryType.BUGFIX}),
            )
        )
        impl = [s.stage_id for s in registry.stages_for(StoryType.IMPLEMENTATION)]
        bug = [s.stage_id for s in registry.stages_for(StoryType.BUGFIX)]
        assert impl == ["a.one"]
        assert bug == ["a.two"]

    def test_preserves_registry_order(self) -> None:
        registry = StageRegistry(
            stages=(
                _stage("z.first", 1, {StoryType.IMPLEMENTATION}),
                _stage("a.second", 1, {StoryType.IMPLEMENTATION}),
            )
        )
        ids = [s.stage_id for s in registry.stages_for(StoryType.IMPLEMENTATION)]
        assert ids == ["z.first", "a.second"]


class TestLayer1StagesFor:
    def test_filters_to_layer_1(self) -> None:
        registry = StageRegistry(
            stages=(
                _stage("l1", 1, {StoryType.IMPLEMENTATION}),
                _stage("l2", 2, {StoryType.IMPLEMENTATION}),
            )
        )
        ids = [s.stage_id for s in registry.layer1_stages_for(StoryType.IMPLEMENTATION, are_enabled=False)]
        assert ids == ["l1"]

    def test_are_stage_excluded_when_disabled(self) -> None:
        registry = StageRegistry()
        off = {s.stage_id for s in registry.layer1_stages_for(StoryType.IMPLEMENTATION, are_enabled=False)}
        assert "are.gate" not in off

    def test_are_stage_included_when_enabled(self) -> None:
        registry = StageRegistry()
        on = {s.stage_id for s in registry.layer1_stages_for(StoryType.IMPLEMENTATION, are_enabled=True)}
        assert "are.gate" in on


_CODE_TYPES = {StoryType.IMPLEMENTATION, StoryType.BUGFIX}


def _row(
    layer: int,
    kind: StageKind,
    trust: TrustClass,
    producer: str,
    blocking: bool,
    override_policy: StageOverridePolicy,
    applies_to: set[StoryType],
) -> tuple[int, StageKind, TrustClass, str, bool, StageOverridePolicy, set[StoryType]]:
    return (layer, kind, trust, producer, blocking, override_policy, applies_to)


EXPECTED_STAGES = {
    "qa_review": _row(
        2,
        StageKind.LLM_EVALUATION,
        TrustClass.VERIFIED_LLM,
        QA_REVIEW_PRODUCER,
        True,
        StageOverridePolicy.BLOCKING_ONLY,
        _CODE_TYPES,
    ),
    "semantic_review": _row(
        2,
        StageKind.LLM_EVALUATION,
        TrustClass.VERIFIED_LLM,
        SEMANTIC_REVIEW_PRODUCER,
        True,
        StageOverridePolicy.BLOCKING_ONLY,
        _CODE_TYPES,
    ),
    "doc_fidelity_impl": _row(
        2,
        StageKind.LLM_EVALUATION,
        TrustClass.VERIFIED_LLM,
        DOC_FIDELITY_PRODUCER,
        True,
        StageOverridePolicy.BLOCKING_ONLY,
        _CODE_TYPES,
    ),
    "context_sufficiency": _row(
        2,
        StageKind.DETERMINISTIC,
        TrustClass.SYSTEM,
        CONTEXT_SUFFICIENCY_PRODUCER,
        False,
        StageOverridePolicy.NONE,
        _CODE_TYPES,
    ),
    "adversarial": _row(
        3,
        StageKind.AGENT,
        TrustClass.VERIFIED_LLM,
        ADVERSARIAL_PRODUCER,
        True,
        StageOverridePolicy.BLOCKING_ONLY,
        _CODE_TYPES,
    ),
    "sonarqube_gate": _row(
        1,
        StageKind.DETERMINISTIC,
        TrustClass.SYSTEM,
        SONARQUBE_GATE_PRODUCER,
        True,
        StageOverridePolicy.BLOCKING_ONLY,
        _CODE_TYPES,
    ),
    "policy": _row(
        4,
        StageKind.POLICY,
        TrustClass.SYSTEM,
        POLICY_PRODUCER,
        True,
        StageOverridePolicy.NONE,
        _CODE_TYPES,
    ),
    "concept_feedback": _row(
        2,
        StageKind.LLM_EVALUATION,
        TrustClass.VERIFIED_LLM,
        CONCEPT_FEEDBACK_PRODUCER,
        True,
        StageOverridePolicy.BLOCKING_ONLY,
        {StoryType.CONCEPT},
    ),
    "research_quality": _row(
        1,
        StageKind.DETERMINISTIC,
        TrustClass.SYSTEM,
        RESEARCH_QUALITY_PRODUCER,
        False,
        StageOverridePolicy.BLOCKING_ONLY,
        {StoryType.RESEARCH},
    ),
    "bugfix.reproducer_manifest": _row(
        1,
        StageKind.DETERMINISTIC,
        TrustClass.SYSTEM,
        BUGFIX_REPRODUCER_MANIFEST_PRODUCER,
        True,
        StageOverridePolicy.NONE,
        {StoryType.BUGFIX},
    ),
    "bugfix.red_evidence": _row(
        1,
        StageKind.DETERMINISTIC,
        TrustClass.SYSTEM,
        BUGFIX_RED_EVIDENCE_PRODUCER,
        True,
        StageOverridePolicy.NONE,
        {StoryType.BUGFIX},
    ),
    "bugfix.green_evidence": _row(
        1,
        StageKind.DETERMINISTIC,
        TrustClass.SYSTEM,
        BUGFIX_GREEN_EVIDENCE_PRODUCER,
        True,
        StageOverridePolicy.NONE,
        {StoryType.BUGFIX},
    ),
    "bugfix.suite_evidence": _row(
        1,
        StageKind.DETERMINISTIC,
        TrustClass.SYSTEM,
        BUGFIX_SUITE_EVIDENCE_PRODUCER,
        True,
        StageOverridePolicy.NONE,
        {StoryType.BUGFIX},
    ),
    "bugfix.red_green_consistency": _row(
        1,
        StageKind.DETERMINISTIC,
        TrustClass.SYSTEM,
        BUGFIX_RED_GREEN_CONSISTENCY_PRODUCER,
        True,
        StageOverridePolicy.NONE,
        {StoryType.BUGFIX},
    ),
}


class TestStandardStageTable:
    def test_expected_stage_fields_match_soll_table(self) -> None:
        registry = StageRegistry()
        by_id = {stage.stage_id: stage for stage in registry.stages}
        for stage_id, expected in EXPECTED_STAGES.items():
            layer, kind, trust, producer, blocking, override_policy, applies_to = expected
            stage = by_id[stage_id]
            assert stage.id == stage.stage_id
            assert stage.layer == layer
            assert stage.kind is kind
            assert stage.trust_class is trust
            assert stage.producer == producer
            assert stage.default_blocking is blocking
            assert stage.override_policy is override_policy
            assert stage.applies_to == frozenset(applies_to)

    def test_default_blocking_matches_severity_invariant(self) -> None:
        for stage in StageRegistry().stages:
            assert stage.default_blocking is (stage.severity is Severity.BLOCKING)

    def test_result_name_resolves_to_canonical_stage_id(self) -> None:
        registry = StageRegistry()

        assert registry.canonical_stage_id_for_result_name("doc_fidelity") == "doc_fidelity_impl"
        assert registry.canonical_stage_id_for_result_name("qa_review") == "qa_review"

    def test_check_origin_resolution_requires_registry_evidence(self) -> None:
        proposal_stage = StageDefinition(
            stage_id="proposal.check",
            layer=2,
            severity=Severity.BLOCKING,
            applies_to=frozenset((StoryType.IMPLEMENTATION,)),
            origin_check_ref="CHK-0042",
            layer_result_name="proposal_review",
        )
        registry = StageRegistry(stages=(*StageRegistry().stages, proposal_stage))

        assert registry.resolve_check_origin_refs(
            [
                "artifact.protocol",
                "context_exists",
                "proposal.check",
                "proposal_review.proposal.check",
                "unknown.check",
            ]
        ) == {
            "artifact.protocol": None,
            "context_exists": None,
            "proposal.check": "CHK-0042",
            "proposal_review.proposal.check": "CHK-0042",
        }

    def test_bugfix_stages_apply_only_to_bugfix(self) -> None:
        registry = StageRegistry()
        bugfix_ids = {
            stage.stage_id
            for stage in registry.layer1_stages_for(StoryType.BUGFIX, are_enabled=False)
            if stage.stage_id.startswith("bugfix.")
        }
        impl_ids = {stage.stage_id for stage in registry.layer1_stages_for(StoryType.IMPLEMENTATION, are_enabled=False)}
        assert bugfix_ids == {
            "bugfix.reproducer_manifest",
            "bugfix.red_evidence",
            "bugfix.green_evidence",
            "bugfix.suite_evidence",
            "bugfix.red_green_consistency",
        }
        assert not bugfix_ids.intersection(impl_ids)

    def test_trust_c_blocking_rejected_definition_time(self) -> None:
        with pytest.raises(ValueError, match="Trust-C"):
            StageRegistry(
                stages=(
                    StageDefinition(
                        stage_id="worker.claim",
                        layer=1,
                        severity=Severity.BLOCKING,
                        applies_to=frozenset((StoryType.IMPLEMENTATION,)),
                        trust_class=TrustClass.WORKER_ASSERTION,
                    ),
                )
            )

    def test_trust_c_blocking_rejected_after_override(self) -> None:
        stage = StageDefinition(
            stage_id="worker.claim",
            layer=1,
            severity=Severity.MINOR,
            applies_to=frozenset((StoryType.IMPLEMENTATION,)),
            trust_class=TrustClass.WORKER_ASSERTION,
        )
        assert StageRegistry(stages=(stage,)).stages[0].effective_blocking is False
        with pytest.raises(ValueError, match="Trust-C"):
            StageRegistry(stages=(stage,), stage_overrides={"worker.claim": True})

    def test_unknown_and_non_overrideable_stage_overrides_fail_closed(self) -> None:
        with pytest.raises(ValueError, match="unknown stage"):
            StageRegistry(stage_overrides={"does.not.exist": False})
        with pytest.raises(ValueError, match="does not allow"):
            StageRegistry(stage_overrides={"policy": False})


class TestResultNameRegistry:
    """Result-name resolution is explicit and fail-closed."""

    def test_unknown_result_name_is_rejected(self) -> None:
        with pytest.raises(ValueError, match="unknown LayerResult name"):
            StageRegistry().canonical_stage_id_for_result_name("unregistered")

    @pytest.mark.parametrize("stage_id", ["", "   "])
    def test_empty_or_whitespace_stage_id_is_rejected_at_construction(
        self,
        stage_id: str,
    ) -> None:
        with pytest.raises(ValueError, match="stage id must not be empty"):
            StageRegistry(
                stages=(
                    StageDefinition(
                        stage_id=stage_id,
                        layer=1,
                        severity=Severity.BLOCKING,
                        applies_to=frozenset((StoryType.IMPLEMENTATION,)),
                    ),
                )
            )

    @pytest.mark.parametrize("result_name", ["", "   "])
    def test_empty_or_whitespace_layer_result_name_is_rejected_at_construction(
        self,
        result_name: str,
    ) -> None:
        with pytest.raises(ValueError, match="layer result name.*must not be empty"):
            StageRegistry(
                stages=(
                    StageDefinition(
                        stage_id="configured_stage",
                        layer=1,
                        severity=Severity.BLOCKING,
                        applies_to=frozenset((StoryType.IMPLEMENTATION,)),
                        layer_result_name=result_name,
                    ),
                )
            )

    def test_aggregate_and_stage_claim_cannot_be_ambiguous(self) -> None:
        with pytest.raises(ValueError, match="ambiguous LayerResult names"):
            StageRegistry(
                aggregate_result_stage_ids={"qa_review": "aggregate.qa_review"},
                aggregate_result_producers={},
            )

    def test_two_stage_definitions_cannot_claim_the_same_result_name(self) -> None:
        stage_a = StageDefinition(
            stage_id="stage_a",
            layer=2,
            severity=Severity.BLOCKING,
            applies_to=frozenset((StoryType.IMPLEMENTATION,)),
            layer_result_name="shared_result",
        )
        stage_b = StageDefinition(
            stage_id="stage_b",
            layer=2,
            severity=Severity.BLOCKING,
            applies_to=frozenset((StoryType.IMPLEMENTATION,)),
            layer_result_name="shared_result",
        )

        with pytest.raises(ValueError, match=r"shared_result.*stage_a.*stage_b"):
            StageRegistry(stages=(stage_a, stage_b))
