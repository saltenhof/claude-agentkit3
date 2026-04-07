"""Unit tests for workflow graph validation."""

from __future__ import annotations

from agentkit.pipeline.workflow.model import (
    HookPoints,
    PhaseDefinition,
    TransitionRule,
    WorkflowDefinition,
    YieldPoint,
)
from agentkit.pipeline.workflow.validators import ValidationError, WorkflowValidator


class TestWorkflowValidatorValid:
    """Tests that valid workflows pass validation."""

    def test_valid_minimal_workflow_no_errors(self) -> None:
        """A valid 2-phase workflow produces no validation errors."""
        wf = WorkflowDefinition(
            name="valid",
            phases=(
                PhaseDefinition(name="start"),
                PhaseDefinition(name="end"),
            ),
            transitions=(
                TransitionRule(source="start", target="end"),
            ),
            hooks=HookPoints(),
        )

        errors = WorkflowValidator.validate(wf)
        assert errors == []

    def test_valid_three_phase_chain(self) -> None:
        """A valid 3-phase chain produces no validation errors."""
        wf = WorkflowDefinition(
            name="chain",
            phases=(
                PhaseDefinition(name="a"),
                PhaseDefinition(name="b"),
                PhaseDefinition(name="c"),
            ),
            transitions=(
                TransitionRule(source="a", target="b"),
                TransitionRule(source="b", target="c"),
            ),
            hooks=HookPoints(),
        )

        errors = WorkflowValidator.validate(wf)
        assert errors == []

    def test_valid_workflow_with_yield_points(self) -> None:
        """A workflow with properly configured yield points passes."""
        wf = WorkflowDefinition(
            name="yield_ok",
            phases=(
                PhaseDefinition(
                    name="start",
                    yield_points=(
                        YieldPoint(
                            status="waiting",
                            resume_triggers=("trigger_a",),
                        ),
                    ),
                ),
                PhaseDefinition(name="end"),
            ),
            transitions=(
                TransitionRule(source="start", target="end"),
            ),
            hooks=HookPoints(),
        )

        errors = WorkflowValidator.validate(wf)
        assert errors == []


class TestWorkflowValidatorErrors:
    """Tests that invalid workflows produce appropriate errors."""

    def test_unreachable_phase_produces_error(self) -> None:
        """A phase not reachable from the first phase triggers an error."""
        wf = WorkflowDefinition(
            name="unreachable",
            phases=(
                PhaseDefinition(name="start"),
                PhaseDefinition(name="island"),
                PhaseDefinition(name="end"),
            ),
            transitions=(
                TransitionRule(source="start", target="end"),
            ),
            hooks=HookPoints(),
        )

        errors = WorkflowValidator.validate(wf)
        messages = [e.message for e in errors]
        assert any("island" in m and "not reachable" in m for m in messages)

    def test_transition_to_unknown_phase_produces_error(self) -> None:
        """A transition referencing a non-existent phase triggers an error."""
        wf = WorkflowDefinition(
            name="bad_target",
            phases=(
                PhaseDefinition(name="start"),
                PhaseDefinition(name="end"),
            ),
            transitions=(
                TransitionRule(source="start", target="ghost"),
            ),
            hooks=HookPoints(),
        )

        errors = WorkflowValidator.validate(wf)
        messages = [e.message for e in errors]
        assert any("ghost" in m for m in messages)

    def test_transition_from_unknown_phase_produces_error(self) -> None:
        """A transition with unknown source triggers an error."""
        wf = WorkflowDefinition(
            name="bad_source",
            phases=(
                PhaseDefinition(name="start"),
                PhaseDefinition(name="end"),
            ),
            transitions=(
                TransitionRule(source="phantom", target="end"),
            ),
            hooks=HookPoints(),
        )

        errors = WorkflowValidator.validate(wf)
        messages = [e.message for e in errors]
        assert any("phantom" in m for m in messages)

    def test_yield_point_without_resume_triggers_produces_error(self) -> None:
        """A YieldPoint with no resume_triggers triggers a validation error."""
        wf = WorkflowDefinition(
            name="bad_yield",
            phases=(
                PhaseDefinition(
                    name="start",
                    yield_points=(
                        YieldPoint(status="stuck"),
                    ),
                ),
                PhaseDefinition(name="end"),
            ),
            transitions=(
                TransitionRule(source="start", target="end"),
            ),
            hooks=HookPoints(),
        )

        errors = WorkflowValidator.validate(wf)
        messages = [e.message for e in errors]
        assert any("stuck" in m and "resume trigger" in m for m in messages)

    def test_no_transition_to_last_phase_produces_error(self) -> None:
        """No transition to the last phase triggers a validation error."""
        wf = WorkflowDefinition(
            name="no_end",
            phases=(
                PhaseDefinition(name="start"),
                PhaseDefinition(name="middle"),
                PhaseDefinition(name="end"),
            ),
            transitions=(
                TransitionRule(source="start", target="middle"),
                # Missing: middle -> end
            ),
            hooks=HookPoints(),
        )

        errors = WorkflowValidator.validate(wf)
        messages = [e.message for e in errors]
        assert any("end" in m and "No transition" in m for m in messages)

    def test_disconnected_middle_phase_produces_error(self) -> None:
        """A middle phase with no transitions produces an error."""
        wf = WorkflowDefinition(
            name="disconnected",
            phases=(
                PhaseDefinition(name="start"),
                PhaseDefinition(name="orphan"),
                PhaseDefinition(name="end"),
            ),
            transitions=(
                TransitionRule(source="start", target="end"),
            ),
            hooks=HookPoints(),
        )

        errors = WorkflowValidator.validate(wf)
        messages = [e.message for e in errors]
        # 'orphan' should appear as unreachable AND/OR disconnected
        assert any("orphan" in m for m in messages)

    def test_validation_error_severity_is_error(self) -> None:
        """ValidationError defaults to severity 'error'."""
        ve = ValidationError(message="test")
        assert ve.severity == "error"

    def test_empty_workflow_produces_error(self) -> None:
        """A workflow with no phases produces a validation error."""
        wf = WorkflowDefinition(name="empty")

        errors = WorkflowValidator.validate(wf)
        assert len(errors) > 0
        assert any("no phases" in e.message for e in errors)
