"""Pipeline robustness tests for transition graphs.

For EVERY story-type workflow, verifies that:
- All valid transitions are present.
- All invalid transitions are NOT present.
Uses ``workflow.get_transitions_from(phase)`` to check allowed targets.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from agentkit.process.language.definitions import (
    BUGFIX_WORKFLOW,
    CONCEPT_WORKFLOW,
    IMPLEMENTATION_WORKFLOW,
    RESEARCH_WORKFLOW,
)

if TYPE_CHECKING:
    from agentkit.process.language.model import WorkflowDefinition


def _get_transition_targets(wf: WorkflowDefinition, source: str) -> set[str]:
    """Get all target phase names reachable from a source via transitions."""
    return {t.target for t in wf.get_transitions_from(source)}


def _get_all_transition_pairs(wf: WorkflowDefinition) -> set[tuple[str, str]]:
    """Get all (source, target) pairs defined in the workflow."""
    return {(t.source, t.target) for t in wf.transitions}


# ---------------------------------------------------------------------------
# Implementation Workflow
# ---------------------------------------------------------------------------


class TestImplementationTransitions:
    """Transition tests for the implementation workflow."""

    @pytest.mark.parametrize(
        ("source", "target"),
        [
            ("setup", "exploration"),
            ("setup", "implementation"),
            ("exploration", "implementation"),
            ("implementation", "closure"),
        ],
    )
    def test_valid_transition_exists(
        self,
        source: str,
        target: str,
    ) -> None:
        """Each valid transition is defined in the implementation workflow."""
        targets = _get_transition_targets(IMPLEMENTATION_WORKFLOW, source)
        assert target in targets, (
            f"Expected transition {source} -> {target} but found "
            f"targets: {targets}"
        )

    @pytest.mark.parametrize(
        ("source", "target"),
        [
            ("setup", "closure"),
            ("setup", "verify"),
            ("exploration", "closure"),
            ("exploration", "verify"),
            ("implementation", "verify"),
            ("implementation", "exploration"),
            ("implementation", "setup"),
            ("verify", "setup"),
            ("verify", "implementation"),
            ("verify", "closure"),
            ("verify", "exploration"),
            ("closure", "setup"),
            ("closure", "implementation"),
            ("closure", "verify"),
            ("closure", "exploration"),
        ],
    )
    def test_invalid_transition_not_present(
        self,
        source: str,
        target: str,
    ) -> None:
        """Each invalid transition is NOT defined in the implementation workflow."""
        targets = _get_transition_targets(IMPLEMENTATION_WORKFLOW, source)
        assert target not in targets, (
            f"Unexpected transition {source} -> {target} found in workflow"
        )

    def test_no_verify_transitions(self) -> None:
        """Implementation workflow has no verify top-level transitions."""
        all_pairs = _get_all_transition_pairs(IMPLEMENTATION_WORKFLOW)
        for source, target in all_pairs:
            assert source != "verify"
            assert target != "verify"

    def test_implementation_to_closure_has_guard(self) -> None:
        """The implementation->closure transition has a guard function."""
        transitions = IMPLEMENTATION_WORKFLOW.get_transitions_from("implementation")
        to_closure = [t for t in transitions if t.target == "closure"]
        assert len(to_closure) == 1
        assert to_closure[0].guard is not None

    def test_setup_to_exploration_has_exploration_guard(self) -> None:
        """The setup->exploration transition has mode_is_exploration guard."""
        transitions = IMPLEMENTATION_WORKFLOW.get_transitions_from("setup")
        to_exploration = [t for t in transitions if t.target == "exploration"]
        assert len(to_exploration) == 1
        guard_name = getattr(to_exploration[0].guard, "guard_name", None)
        assert guard_name == "mode_is_exploration"

    def test_setup_to_implementation_has_not_exploration_guard(self) -> None:
        """The setup->implementation transition has mode_is_not_exploration guard."""
        transitions = IMPLEMENTATION_WORKFLOW.get_transitions_from("setup")
        to_impl = [t for t in transitions if t.target == "implementation"]
        assert len(to_impl) == 1
        guard_name = getattr(to_impl[0].guard, "guard_name", None)
        assert guard_name == "mode_is_not_exploration"

    def test_total_transition_count(self) -> None:
        """Implementation workflow has exactly 4 transitions."""
        assert len(IMPLEMENTATION_WORKFLOW.transitions) == 4


# ---------------------------------------------------------------------------
# Bugfix Workflow
# ---------------------------------------------------------------------------


class TestBugfixTransitions:
    """Transition tests for the bugfix workflow (AG3-057: exploration now included).

    A bugfix can route into Exploration mode when one of the four triggers fires
    (FK-23 §23.1 / AG3-057).  The workflow therefore mirrors the implementation
    workflow's routing structure: setup can go to either exploration or
    implementation depending on execution_route.
    """

    @pytest.mark.parametrize(
        ("source", "target"),
        [
            # EXECUTION-route: setup → implementation (direct)
            ("setup", "implementation"),
            # EXPLORATION-route: setup → exploration → implementation → closure
            ("setup", "exploration"),
            ("exploration", "implementation"),
            ("implementation", "closure"),
        ],
    )
    def test_valid_transition_exists(
        self,
        source: str,
        target: str,
    ) -> None:
        """Each valid transition is defined in the bugfix workflow (AG3-057)."""
        targets = _get_transition_targets(BUGFIX_WORKFLOW, source)
        assert target in targets

    @pytest.mark.parametrize(
        ("source", "target"),
        [
            ("setup", "closure"),
            ("setup", "verify"),
            ("implementation", "verify"),
            ("implementation", "setup"),
            ("verify", "setup"),
            ("verify", "implementation"),
            ("verify", "closure"),
            ("closure", "setup"),
            ("closure", "implementation"),
            ("closure", "verify"),
        ],
    )
    def test_invalid_transition_not_present(
        self,
        source: str,
        target: str,
    ) -> None:
        """Each invalid transition is NOT defined in the bugfix workflow."""
        targets = _get_transition_targets(BUGFIX_WORKFLOW, source)
        assert target not in targets

    def test_exploration_transitions_present(self) -> None:
        """Bugfix workflow now carries exploration transitions (AG3-057, FK-23 §23.1)."""
        all_pairs = _get_all_transition_pairs(BUGFIX_WORKFLOW)
        exploration_as_target = [p for p in all_pairs if p[1] == "exploration"]
        exploration_as_source = [p for p in all_pairs if p[0] == "exploration"]
        assert len(exploration_as_target) == 1, (
            "setup→exploration transition must be present"
        )
        assert len(exploration_as_source) == 1, (
            "exploration→implementation transition must be present"
        )

    def test_total_transition_count(self) -> None:
        """Bugfix workflow has exactly 4 transitions (AG3-057: mirrors impl workflow)."""
        assert len(BUGFIX_WORKFLOW.transitions) == 4


# ---------------------------------------------------------------------------
# Concept Workflow
# ---------------------------------------------------------------------------


class TestConceptTransitions:
    """Transition tests for the concept workflow."""

    @pytest.mark.parametrize(
        ("source", "target"),
        [
            ("setup", "implementation"),
            ("implementation", "closure"),
        ],
    )
    def test_valid_transition_exists(
        self,
        source: str,
        target: str,
    ) -> None:
        """Each valid transition is defined in the concept workflow."""
        targets = _get_transition_targets(CONCEPT_WORKFLOW, source)
        assert target in targets

    @pytest.mark.parametrize(
        ("source", "target"),
        [
            ("setup", "closure"),
            ("setup", "verify"),
            ("implementation", "verify"),
            ("implementation", "setup"),
            ("verify", "setup"),
            ("verify", "implementation"),
            ("verify", "closure"),
            ("closure", "setup"),
            ("closure", "implementation"),
            ("closure", "verify"),
        ],
    )
    def test_invalid_transition_not_present(
        self,
        source: str,
        target: str,
    ) -> None:
        """Each invalid transition is NOT defined in the concept workflow."""
        targets = _get_transition_targets(CONCEPT_WORKFLOW, source)
        assert target not in targets

    def test_no_remediation_loop(self) -> None:
        """Concept workflow has no verify->implementation remediation loop."""
        targets = _get_transition_targets(CONCEPT_WORKFLOW, "verify")
        assert "implementation" not in targets

    def test_total_transition_count(self) -> None:
        """Concept workflow has exactly 2 transitions."""
        assert len(CONCEPT_WORKFLOW.transitions) == 2


# ---------------------------------------------------------------------------
# Research Workflow
# ---------------------------------------------------------------------------


class TestResearchTransitions:
    """Transition tests for the research workflow."""

    @pytest.mark.parametrize(
        ("source", "target"),
        [
            ("setup", "implementation"),
            ("implementation", "closure"),
        ],
    )
    def test_valid_transition_exists(
        self,
        source: str,
        target: str,
    ) -> None:
        """Each valid transition is defined in the research workflow."""
        targets = _get_transition_targets(RESEARCH_WORKFLOW, source)
        assert target in targets

    @pytest.mark.parametrize(
        ("source", "target"),
        [
            ("setup", "closure"),
            ("implementation", "setup"),
            ("closure", "setup"),
            ("closure", "implementation"),
        ],
    )
    def test_invalid_transition_not_present(
        self,
        source: str,
        target: str,
    ) -> None:
        """Each invalid transition is NOT defined in the research workflow."""
        targets = _get_transition_targets(RESEARCH_WORKFLOW, source)
        assert target not in targets

    def test_no_verify_transitions(self) -> None:
        """Research workflow has no transitions involving verify."""
        all_pairs = _get_all_transition_pairs(RESEARCH_WORKFLOW)
        for source, target in all_pairs:
            assert source != "verify"
            assert target != "verify"

    def test_total_transition_count(self) -> None:
        """Research workflow has exactly 2 transitions."""
        assert len(RESEARCH_WORKFLOW.transitions) == 2
