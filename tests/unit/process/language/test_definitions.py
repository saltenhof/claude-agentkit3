"""Unit tests for concrete workflow definitions."""

from __future__ import annotations

import pytest

from agentkit.process.language.definitions import (
    BUGFIX_WORKFLOW,
    CONCEPT_WORKFLOW,
    IMPLEMENTATION_WORKFLOW,
    RESEARCH_WORKFLOW,
    resolve_workflow,
)
from agentkit.process.language.validators import WorkflowValidator
from agentkit.story_context_manager.types import StoryType


class TestWorkflowsBuildSuccessfully:
    """All four workflows build without errors."""

    def test_implementation_workflow_builds(self) -> None:
        """Implementation workflow is a valid WorkflowDefinition."""
        assert IMPLEMENTATION_WORKFLOW.name == "implementation"

    def test_bugfix_workflow_builds(self) -> None:
        """Bugfix workflow is a valid WorkflowDefinition."""
        assert BUGFIX_WORKFLOW.name == "bugfix"

    def test_concept_workflow_builds(self) -> None:
        """Concept workflow is a valid WorkflowDefinition."""
        assert CONCEPT_WORKFLOW.name == "concept"

    def test_research_workflow_builds(self) -> None:
        """Research workflow is a valid WorkflowDefinition."""
        assert RESEARCH_WORKFLOW.name == "research"


class TestWorkflowsPassValidation:
    """All four workflows pass WorkflowValidator.validate()."""

    def test_implementation_workflow_valid(self) -> None:
        """Implementation workflow passes all validation checks."""
        errors = WorkflowValidator.validate(IMPLEMENTATION_WORKFLOW)
        assert errors == [], [e.message for e in errors]

    def test_bugfix_workflow_valid(self) -> None:
        """Bugfix workflow passes all validation checks."""
        errors = WorkflowValidator.validate(BUGFIX_WORKFLOW)
        assert errors == [], [e.message for e in errors]

    def test_concept_workflow_valid(self) -> None:
        """Concept workflow passes all validation checks."""
        errors = WorkflowValidator.validate(CONCEPT_WORKFLOW)
        assert errors == [], [e.message for e in errors]

    def test_research_workflow_valid(self) -> None:
        """Research workflow passes all validation checks."""
        errors = WorkflowValidator.validate(RESEARCH_WORKFLOW)
        assert errors == [], [e.message for e in errors]


class TestWorkflowPhases:
    """Tests for correct phase composition of each workflow."""

    def test_implementation_has_five_phases(self) -> None:
        """Implementation workflow has exactly 5 phases."""
        assert IMPLEMENTATION_WORKFLOW.phase_names == (
            "setup",
            "exploration",
            "implementation",
            "verify",
            "closure",
        )

    def test_bugfix_has_four_phases_no_exploration(self) -> None:
        """Bugfix workflow has 4 phases without exploration."""
        assert BUGFIX_WORKFLOW.phase_names == (
            "setup",
            "implementation",
            "verify",
            "closure",
        )
        assert "exploration" not in BUGFIX_WORKFLOW.phase_names

    def test_concept_has_four_phases(self) -> None:
        """Concept workflow has 4 phases."""
        assert CONCEPT_WORKFLOW.phase_names == (
            "setup",
            "implementation",
            "verify",
            "closure",
        )

    def test_research_has_three_phases_no_verify(self) -> None:
        """Research workflow has 3 phases without verify."""
        assert RESEARCH_WORKFLOW.phase_names == (
            "setup",
            "implementation",
            "closure",
        )
        assert "verify" not in RESEARCH_WORKFLOW.phase_names


class TestResolveWorkflow:
    """Tests for the resolve_workflow() function."""

    @pytest.mark.parametrize(
        ("story_type", "expected_name"),
        [
            (StoryType.IMPLEMENTATION, "implementation"),
            (StoryType.BUGFIX, "bugfix"),
            (StoryType.CONCEPT, "concept"),
            (StoryType.RESEARCH, "research"),
        ],
    )
    def test_resolve_returns_correct_workflow(
        self,
        story_type: StoryType,
        expected_name: str,
    ) -> None:
        """resolve_workflow returns the matching workflow for each story type."""
        wf = resolve_workflow(story_type)
        assert wf.name == expected_name

    def test_resolve_workflow_invalid_type_raises(self) -> None:
        """resolve_workflow with an unknown story type raises WorkflowError."""
        from agentkit.exceptions import WorkflowError

        with pytest.raises(WorkflowError):
            resolve_workflow("invalid_type")  # type: ignore[arg-type]


class TestImplementationWorkflowDetails:
    """Detailed tests for implementation workflow structure."""

    def test_setup_has_preflight_guard(self) -> None:
        """Setup phase has the preflight_passed guard."""
        setup = IMPLEMENTATION_WORKFLOW.get_phase("setup")
        assert setup is not None
        assert len(setup.guards) == 1
        guard_name = getattr(setup.guards[0], "guard_name", None)
        assert guard_name == "preflight_passed"

    def test_exploration_has_yield_points(self) -> None:
        """Exploration phase has yield points for design review."""
        exploration = IMPLEMENTATION_WORKFLOW.get_phase("exploration")
        assert exploration is not None
        assert len(exploration.yield_points) >= 2

        statuses = {yp.status for yp in exploration.yield_points}
        assert "awaiting_design_review" in statuses
        assert "awaiting_design_challenge" in statuses

    def test_verify_has_max_remediation_rounds(self) -> None:
        """Verify phase has max_remediation_rounds set."""
        verify = IMPLEMENTATION_WORKFLOW.get_phase("verify")
        assert verify is not None
        assert verify.max_remediation_rounds == 3

    def test_closure_has_substates(self) -> None:
        """Closure phase has substates defined."""
        closure = IMPLEMENTATION_WORKFLOW.get_phase("closure")
        assert closure is not None
        assert len(closure.substates) > 0
        assert "merging" in closure.substates

    def test_exploration_to_implementation_has_gate_guard(self) -> None:
        """exploration->implementation transition has gate guard."""
        transitions = IMPLEMENTATION_WORKFLOW.get_transitions_from("exploration")
        assert len(transitions) == 1
        tr = transitions[0]
        assert tr.source == "exploration"
        assert tr.target == "implementation"
        assert tr.guard is not None
        guard_name = getattr(tr.guard, "guard_name", None)
        assert guard_name == "exploration_gate_approved"
