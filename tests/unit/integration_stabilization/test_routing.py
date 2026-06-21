"""Unit tests for integration_stabilization routing extension (AC8)."""

from __future__ import annotations

from agentkit.backend.integration_stabilization.models import (
    IntegrationScopeManifest,
    ManifestApprovalRecord,
    StabilizationBudgetCaps,
)
from agentkit.backend.integration_stabilization.routing import (
    decide_integration_stabilization_routing,
    is_integration_stabilization_contract,
)
from agentkit.backend.story_context_manager.models import StoryContext
from agentkit.backend.story_context_manager.routing_rules import (
    get_phases_for_story,
    is_execution_routing_blocked,
    should_run_exploration,
)
from agentkit.backend.story_context_manager.types import ImplementationContract, StoryType


def _approval() -> ManifestApprovalRecord:
    m = IntegrationScopeManifest(
        version=1,
        project_key="PROJ",
        story_id="PROJ-42",
        implementation_contract="integration_stabilization",
        target_seams=("src/api/",),
        allowed_repos_paths=("worktrees/main/",),
        integration_targets=("e2e_login",),
        allowed_contract_changes=(),
        stabilization_budget=StabilizationBudgetCaps(
            max_loops=5, max_new_surfaces=3,
            max_contract_changes=2, max_regressions_per_cycle=2,
        ),
    )
    return ManifestApprovalRecord(
        project_key=m.project_key,
        story_id=m.story_id,
        run_id="run-001",
        manifest_version=m.version,
        manifest_hash=m.content_hash,
    )


def _context(
    contract: ImplementationContract | None = ImplementationContract.INTEGRATION_STABILIZATION,
) -> StoryContext:
    from agentkit.backend.story_context_manager.types import StoryMode
    return StoryContext(
        project_key="PROJ",
        story_id="PROJ-42",
        story_type=StoryType.IMPLEMENTATION,
        implementation_contract=contract,
        execution_route=StoryMode.EXPLORATION,
    )


class TestIsIntegrationStabilizationContract:
    def test_returns_true_for_integration_stabilization(self) -> None:
        assert is_integration_stabilization_contract(
            ImplementationContract.INTEGRATION_STABILIZATION
        )

    def test_returns_false_for_standard(self) -> None:
        assert not is_integration_stabilization_contract(ImplementationContract.STANDARD)

    def test_returns_false_for_none(self) -> None:
        assert not is_integration_stabilization_contract(None)


class TestDecideIntegrationStabilizationRouting:
    """decide_integration_stabilization_routing tests."""

    def test_without_approval_must_run_exploration_and_blocks_execution(self) -> None:
        decision = decide_integration_stabilization_routing(approval_record=None)
        assert decision.must_run_exploration is True
        assert decision.execution_blocked is True
        assert decision.block_reason

    def test_with_approval_must_run_exploration_and_does_not_block(self) -> None:
        decision = decide_integration_stabilization_routing(
            approval_record=_approval()
        )
        assert decision.must_run_exploration is True
        assert decision.execution_blocked is False


class TestRoutingRulesExtension:
    """AC8: routing_rules reads implementation_contract."""

    def test_integration_stabilization_keeps_exploration_phase(self) -> None:
        ctx = _context(contract=ImplementationContract.INTEGRATION_STABILIZATION)
        phases = get_phases_for_story(ctx)
        assert "exploration" in phases

    def test_standard_story_with_execution_route_skips_exploration(self) -> None:
        from agentkit.backend.story_context_manager.types import StoryMode
        ctx = StoryContext(
            project_key="PROJ",
            story_id="PROJ-42",
            story_type=StoryType.IMPLEMENTATION,
            implementation_contract=ImplementationContract.STANDARD,
            execution_route=StoryMode.EXECUTION,
        )
        phases = get_phases_for_story(ctx)
        assert "exploration" not in phases

    def test_should_run_exploration_true_for_integration_stabilization(self) -> None:
        ctx = _context(contract=ImplementationContract.INTEGRATION_STABILIZATION)
        assert should_run_exploration(ctx) is True

    def test_is_execution_routing_blocked_true_for_integration_stabilization(self) -> None:
        """AC8: execution-routing is blocked for integration_stabilization."""
        ctx = _context(contract=ImplementationContract.INTEGRATION_STABILIZATION)
        assert is_execution_routing_blocked(ctx) is True

    def test_is_execution_routing_blocked_false_for_standard(self) -> None:
        ctx = _context(contract=ImplementationContract.STANDARD)
        assert is_execution_routing_blocked(ctx) is False

    def test_is_execution_routing_blocked_false_for_none_contract(self) -> None:
        ctx = _context(contract=None)
        assert is_execution_routing_blocked(ctx) is False
