"""Unit tests for stability_gate stage registration (AC5)."""

from __future__ import annotations

from agentkit.story_context_manager.types import StoryType
from agentkit.verify_system.stage_registry.data import (
    ALL_STAGES,
    STANDARD_STAGES,
)
from agentkit.verify_system.stage_registry.registry import StageRegistry
from agentkit.verify_system.stage_registry.stages import StageKind, StageOverridePolicy


class TestStabilityGateRegistration:
    """AC5: stability_gate is a registered Verify-Stage in the AG3-064 registry."""

    def test_stability_gate_in_integration_stabilization_stages(self) -> None:
        ids = {s.stage_id for s in ALL_STAGES}
        assert "stability_gate" in ids

    def test_stability_gate_not_in_standard_stages(self) -> None:
        """stability_gate only applies to integration_stabilization contract."""
        ids = {s.stage_id for s in STANDARD_STAGES}
        assert "stability_gate" not in ids

    def test_stability_gate_layer_4(self) -> None:
        stage = next(
            s for s in ALL_STAGES if s.stage_id == "stability_gate"
        )
        assert stage.layer == 4

    def test_stability_gate_kind_is_policy(self) -> None:
        stage = next(
            s for s in ALL_STAGES if s.stage_id == "stability_gate"
        )
        assert stage.kind == StageKind.POLICY

    def test_stability_gate_override_policy_none(self) -> None:
        stage = next(
            s for s in ALL_STAGES if s.stage_id == "stability_gate"
        )
        assert stage.override_policy == StageOverridePolicy.NONE

    def test_stability_gate_applies_to_implementation(self) -> None:
        stage = next(
            s for s in ALL_STAGES if s.stage_id == "stability_gate"
        )
        assert StoryType.IMPLEMENTATION in stage.applies_to

    def test_stability_gate_is_blocking(self) -> None:
        from agentkit.core_types import Severity
        stage = next(
            s for s in ALL_STAGES if s.stage_id == "stability_gate"
        )
        assert stage.severity == Severity.BLOCKING


class TestFourFK37NamedChecksRegistration:
    """AC12: four FK-37 §37.1.3 checks are individually registered."""

    def test_declared_surfaces_only_registered(self) -> None:
        ids = {s.stage_id for s in ALL_STAGES}
        assert "integration.declared_surfaces_only" in ids

    def test_stabilization_budget_not_exhausted_registered(self) -> None:
        ids = {s.stage_id for s in ALL_STAGES}
        assert "integration.stabilization_budget_not_exhausted" in ids

    def test_integration_target_matrix_passed_registered(self) -> None:
        ids = {s.stage_id for s in ALL_STAGES}
        assert "integration.integration_target_matrix_passed" in ids

    def test_manifest_approval_required_registered(self) -> None:
        ids = {s.stage_id for s in ALL_STAGES}
        assert "integration.manifest_approval_required" in ids

    def test_binding_integrity_registered(self) -> None:
        ids = {s.stage_id for s in ALL_STAGES}
        assert "integration.binding_integrity" in ids

    def test_declared_surfaces_only_is_layer_1(self) -> None:
        stage = next(
            s for s in ALL_STAGES
            if s.stage_id == "integration.declared_surfaces_only"
        )
        assert stage.layer == 1

    def test_integration_target_matrix_passed_is_layer_4(self) -> None:
        stage = next(
            s for s in ALL_STAGES
            if s.stage_id == "integration.integration_target_matrix_passed"
        )
        assert stage.layer == 4

    def test_no_duplicate_stage_ids_in_integration_stages(self) -> None:
        ids = [s.stage_id for s in ALL_STAGES]
        assert len(ids) == len(set(ids))

    def test_registry_accepts_integration_stabilization_stages(self) -> None:
        """AG3-064 StageRegistry can be constructed with IS stages."""
        from agentkit.story_context_manager.types import ImplementationContract

        registry = StageRegistry(stages=ALL_STAGES)
        # The IS stage is visible ONLY under the IS contract (MAJOR H leak fix).
        stage = registry.stage_for_id(
            "stability_gate",
            implementation_contract=ImplementationContract.INTEGRATION_STABILIZATION,
        )
        assert stage is not None
        assert stage.stage_id == "stability_gate"

    def test_stages_for_returns_stability_gate_for_implementation(self) -> None:
        from agentkit.story_context_manager.types import ImplementationContract

        registry = StageRegistry(stages=ALL_STAGES)
        stages = registry.stages_for(
            StoryType.IMPLEMENTATION,
            implementation_contract=ImplementationContract.INTEGRATION_STABILIZATION,
        )
        stage_ids = [s.stage_id for s in stages]
        assert "stability_gate" in stage_ids

    def test_stability_gate_not_returned_for_bugfix(self) -> None:
        registry = StageRegistry(stages=ALL_STAGES)
        stages = registry.stages_for(StoryType.BUGFIX)
        stage_ids = [s.stage_id for s in stages]
        assert "stability_gate" not in stage_ids


class TestStageForIdNoRegressionLeak:
    """MAJOR H: stage_for_id() must NOT leak IS stages without the IS contract.

    The default registry holds the ONE canonical catalogue (ALL_STAGES). A
    stage_for_id lookup for an IS stage with no contract (or STANDARD) must
    return None — otherwise the IS stages leak into the shared-surface
    standard plan (a behaviour change for standard stories). These tests fail
    if the contract filter in stage_for_id is reverted.
    """

    def test_stage_for_id_hides_stability_gate_without_contract(self) -> None:
        registry = StageRegistry(stages=ALL_STAGES)
        assert registry.stage_for_id("stability_gate") is None

    def test_stage_for_id_hides_is_stage_for_standard_contract(self) -> None:
        from agentkit.story_context_manager.types import ImplementationContract

        registry = StageRegistry(stages=ALL_STAGES)
        assert (
            registry.stage_for_id(
                "integration.declared_surfaces_only",
                implementation_contract=ImplementationContract.STANDARD,
            )
            is None
        )

    def test_stage_for_id_reveals_is_stage_for_is_contract(self) -> None:
        from agentkit.story_context_manager.types import ImplementationContract

        registry = StageRegistry(stages=ALL_STAGES)
        stage = registry.stage_for_id(
            "integration.declared_surfaces_only",
            implementation_contract=ImplementationContract.INTEGRATION_STABILIZATION,
        )
        assert stage is not None

    def test_stage_for_id_still_finds_standard_stage_without_contract(self) -> None:
        """Standard stages remain visible without a contract (no regression)."""
        registry = StageRegistry(stages=ALL_STAGES)
        assert registry.stage_for_id("artifact.protocol") is not None
        assert registry.stage_for_id("policy") is not None
