"""Tests that all expected symbols are importable from the workflow package."""

from __future__ import annotations

import pytest


class TestPublicAPI:
    """All expected symbols are importable from agentkit.pipeline.workflow."""

    @pytest.mark.parametrize(
        "symbol",
        [
            # model
            "WorkflowDefinition",
            "PhaseDefinition",
            "TransitionRule",
            "YieldPoint",
            "HookPoints",
            "Precondition",
            # guards
            "GuardResult",
            "GuardFn",
            "guard",
            "preflight_passed",
            "exploration_gate_approved",
            "verify_completed",
            "mode_is_exploration",
            # gates
            "Gate",
            "GateStage",
            # builder
            "WorkflowBuilder",
            "Workflow",
            # validators
            "WorkflowValidator",
            "ValidationError",
            # definitions
            "resolve_workflow",
            "IMPLEMENTATION_WORKFLOW",
            "BUGFIX_WORKFLOW",
            "CONCEPT_WORKFLOW",
            "RESEARCH_WORKFLOW",
            # recovery
            "RecoveryContract",
            "RehydrationRule",
            "FieldSource",
            "DEFAULT_RECOVERY_CONTRACT",
        ],
    )
    def test_symbol_importable(self, symbol: str) -> None:
        """Each expected symbol is importable from the workflow package."""
        import agentkit.pipeline.workflow as wf_mod

        assert hasattr(wf_mod, symbol), (
            f"Symbol {symbol!r} not found in agentkit.pipeline.workflow"
        )

    def test_all_exports_listed(self) -> None:
        """__all__ contains all expected symbols."""
        import agentkit.pipeline.workflow as wf_mod

        expected = {
            "WorkflowDefinition",
            "PhaseDefinition",
            "TransitionRule",
            "YieldPoint",
            "HookPoints",
            "Precondition",
            "GuardResult",
            "GuardFn",
            "guard",
            "preflight_passed",
            "exploration_gate_approved",
            "verify_completed",
            "mode_is_exploration",
            "Gate",
            "GateStage",
            "WorkflowBuilder",
            "Workflow",
            "WorkflowValidator",
            "ValidationError",
            "resolve_workflow",
            "IMPLEMENTATION_WORKFLOW",
            "BUGFIX_WORKFLOW",
            "CONCEPT_WORKFLOW",
            "RESEARCH_WORKFLOW",
            "RecoveryContract",
            "RehydrationRule",
            "FieldSource",
            "DEFAULT_RECOVERY_CONTRACT",
        }
        actual = set(wf_mod.__all__)
        missing = expected - actual
        assert not missing, f"Missing from __all__: {missing}"
