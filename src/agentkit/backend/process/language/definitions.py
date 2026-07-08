"""Concrete workflow definitions for the four story types."""

from __future__ import annotations

from typing import TYPE_CHECKING

from agentkit.backend.exceptions import WorkflowError
from agentkit.backend.process.language.builder import Workflow
from agentkit.backend.process.language.gates import (
    ExplorationGateStage,
    ExplorationGateStageSpec,
)
from agentkit.backend.process.language.guards import (
    GuardResult,
    exploration_gate_approved,
    guard,
    implementation_completed,
    mode_is_exploration,
    preflight_passed,
)
from agentkit.backend.story_context_manager.types import StoryMode, StoryType

if TYPE_CHECKING:
    from agentkit.backend.pipeline_engine.phase_executor import PhaseState
    from agentkit.backend.process.language.model import WorkflowDefinition
    from agentkit.backend.story_context_manager.models import StoryContext


@guard(
    "mode_is_not_exploration",
    description="Checks that the story routes setup directly to implementation.",
    reads=frozenset({"execution_route", "mode", "implementation_contract"}),
)
def _mode_is_not_exploration(
    ctx: StoryContext,
    state: PhaseState,
) -> GuardResult:
    # AG3-069 (FK-05 §5.6, AC8): an integration_stabilization story ALWAYS routes
    # setup -> exploration first; the direct setup -> implementation transition is
    # FAIL-CLOSED blocked. Exploration is mandatory; execution is only reachable
    # via the exploration gate AFTER the manifest is approved (see
    # exploration_gate_approved + the IS manifest guard). Consumed from the typed
    # routing predicate (no second routing truth, routing_rules.py).
    from agentkit.backend.story_context_manager.routing_rules import (
        is_execution_routing_blocked,
    )

    if is_execution_routing_blocked(ctx):
        return GuardResult.FAIL(
            reason=(
                "integration_stabilization mandates exploration before "
                "implementation; the direct setup -> implementation transition "
                "is blocked (FK-05 §5.6, AC8)."
            ),
        )

    # AG3-018 (FK-24 §24.3.4): a fast story ALWAYS routes setup -> implementation
    # (Exploration=OUT), regardless of execution_route. The fast/standard mode
    # axis is decoupled from execution_route (FK-24 §24.3.3).
    from agentkit.backend.story_context_manager.story_model import WireStoryMode

    if ctx.mode is WireStoryMode.FAST:
        return GuardResult.PASS()
    if ctx.execution_route != StoryMode.EXPLORATION:
        return GuardResult.PASS()
    return GuardResult.FAIL(
        reason=(
            "Story execution route is EXPLORATION: "
            f"execution_route={ctx.execution_route!r}"
        ),
    )


@guard(
    "exploration_gate_approved_with_is_manifest",
    description=(
        "Exploration gate approved AND (for integration_stabilization) an "
        "approved + bound manifest exists."
    ),
    reads=frozenset({"phase", "status", "payload", "implementation_contract"}),
)
def _exploration_gate_approved_with_is_manifest(
    ctx: StoryContext,
    state: PhaseState,
) -> GuardResult:
    """Gate the exploration -> implementation transition (AG3-069 AC8).

    First the standard exploration-gate-approved guard must PASS. Then, for an
    integration_stabilization story, an APPROVED + BOUND IntegrationScopeManifest
    MUST exist before execution/implementation is reachable (FK-05 §5.5.1/§5.6).
    A missing/unbound manifest fails-closed: the transition to implementation is
    blocked, exploration stays the active phase (no productive integration work
    without an approved manifest). Standard stories are unaffected — the IS check
    is gated on the contract.
    """
    base = exploration_gate_approved(ctx, state)
    if not base.passed:
        return base

    from agentkit.backend.story_context_manager.types import ImplementationContract

    if (
        ctx.implementation_contract
        is not ImplementationContract.INTEGRATION_STABILIZATION
    ):
        return base  # Standard story: standard gate decision is authoritative.

    return _is_manifest_approved_and_bound(ctx)


def _is_manifest_approved_and_bound(ctx: StoryContext) -> GuardResult:
    """Return PASS iff an approved + bound IS manifest exists for ``ctx``.

    Fail-closed: an unresolvable story directory, a missing manifest/approval, or
    a binding-integrity failure all block the transition to implementation
    (FK-05 §5.5.1/§5.5.4/§5.6, AC2/AC8).
    """
    if ctx.project_root is None:
        return GuardResult.FAIL(
            reason=(
                "integration_stabilization: cannot resolve the story directory "
                "to verify manifest approval; execution is blocked fail-closed "
                "(FK-05 §5.6, AC8)."
            ),
        )

    from agentkit.backend.installer.paths import story_dir as _story_dir
    from agentkit.backend.integration_stabilization.preconditions import (
        check_approval_present,
        check_binding_integrity,
    )
    from agentkit.backend.integration_stabilization.state import (
        load_integration_manifest,
        load_manifest_approval,
    )
    from agentkit.backend.state_backend.runtime_scope_resolver import (
        resolve_runtime_scope,
    )

    s_dir = _story_dir(ctx.project_root, ctx.story_id)
    manifest = load_integration_manifest(s_dir)
    approval = load_manifest_approval(s_dir)
    if manifest is None or not check_approval_present(approval).approved:
        return GuardResult.FAIL(
            reason=(
                "integration_stabilization: no approved IntegrationScopeManifest; "
                "the exploration -> implementation transition is blocked until the "
                "manifest is approved (FK-05 §5.5.1/§5.6, AC8)."
            ),
        )
    assert approval is not None  # noqa: S101 -- guaranteed by check above
    try:
        run_id = resolve_runtime_scope(s_dir).run_id or approval.run_id
    except Exception:  # noqa: BLE001 -- unresolvable scope falls back to the record run
        run_id = approval.run_id
    binding = check_binding_integrity(manifest, approval, current_run_id=run_id)
    if not binding.binding_valid:
        return GuardResult.FAIL(
            reason=(
                "integration_stabilization: manifest-approval binding invalid "
                f"({binding.reason}); execution blocked fail-closed (FK-05 §5.5.4)."
            ),
        )
    return GuardResult.PASS()


def _build_implementation_workflow() -> WorkflowDefinition:
    return (
        Workflow("implementation")
        .phase("setup")
        .guard(preflight_passed)
        # AG3-145 Teilschritt C (FK-91 §91.1b, FK-10 §10.2.4a): setup PAUSES
        # fail-closed while it awaits the edge preflight_probe / worktree_report
        # (edge-commissioned provisioning). Mirrors the exploration design-review
        # yield so the engine can resume the PAUSED setup phase.
        .yield_to(
            "edge_provisioning",
            on="awaiting_edge_provisioning",
            resume_triggers=["edge_report_received"],
        )
        .phase("exploration")
        .yield_to(
            "design_review",
            on="awaiting_design_review",
            resume_triggers=["design_approved", "design_rejected"],
            required_artifacts=["design_artifact"],
            # FK-23 §23.5.2: Stage 2a design-review is a required gate stage; a
            # FAIL rolls the change-frame back to an editable draft (FK-25
            # §25.4.2) for the next remediation round (AG3-046).
            gate_stage=ExplorationGateStageSpec(
                stage_id=ExplorationGateStage.DESIGN_REVIEW,
                yield_point="design_review",
                required=True,
                rollback_on_fail=True,
            ),
        )
        .yield_to(
            "design_challenge",
            on="awaiting_design_challenge",
            resume_triggers=["challenge_resolved"],
            # FK-23 §23.5.3: Stage 2b design-challenge is the OPTIONAL third
            # stage (mandate-gated; activation deferred to AG3-047). It does not
            # roll the change-frame back by itself.
            gate_stage=ExplorationGateStageSpec(
                stage_id=ExplorationGateStage.DESIGN_CHALLENGE,
                yield_point="design_challenge",
                required=False,
                rollback_on_fail=False,
            ),
        )
        .phase("implementation")
        .max_remediation_rounds(3)
        .phase("closure")
        .substates(["merging", "cleanup", "reporting"])
        .transition("setup", "exploration", guard=mode_is_exploration)
        .transition("setup", "implementation", guard=_mode_is_not_exploration)
        .transition(
            "exploration",
            "implementation",
            guard=_exploration_gate_approved_with_is_manifest,
        )
        .transition("implementation", "closure", guard=implementation_completed)
        .hooks(
            pre_transition=["log_transition"],
            post_transition=["emit_telemetry"],
            on_yield=["notify_yield"],
            on_escalate=["notify_escalation"],
        )
        .build()
    )


def _build_bugfix_workflow() -> WorkflowDefinition:
    """Build the workflow definition for bugfix stories.

    AG3-057 (FK-23 §23.1): a bugfix can run in Exploration mode when one of
    the four triggers fires.  The workflow therefore mirrors the implementation
    workflow: setup can route to exploration OR directly to implementation
    depending on ``execution_route``.  The routing is determined by the same
    ``mode_is_exploration`` / ``_mode_is_not_exploration`` guards used by the
    implementation workflow; ``routing_rules.get_phases_for_story`` will then
    remove the ``exploration`` phase for EXECUTION-mode bugfixes (same
    mechanism as for implementation stories — no separate code path needed).
    """
    return (
        Workflow("bugfix")
        .phase("setup")
        .guard(preflight_passed)
        # AG3-145 Teilschritt C (FK-91 §91.1b, FK-10 §10.2.4a): setup PAUSES
        # fail-closed while it awaits the edge preflight_probe / worktree_report
        # (edge-commissioned provisioning). Mirrors the exploration design-review
        # yield so the engine can resume the PAUSED setup phase.
        .yield_to(
            "edge_provisioning",
            on="awaiting_edge_provisioning",
            resume_triggers=["edge_report_received"],
        )
        .phase("exploration")
        .yield_to(
            "design_review",
            on="awaiting_design_review",
            resume_triggers=["design_approved", "design_rejected"],
            required_artifacts=["design_artifact"],
            # FK-23 §23.5.2: Stage 2a design-review is a required gate stage.
            gate_stage=ExplorationGateStageSpec(
                stage_id=ExplorationGateStage.DESIGN_REVIEW,
                yield_point="design_review",
                required=True,
                rollback_on_fail=True,
            ),
        )
        .yield_to(
            "design_challenge",
            on="awaiting_design_challenge",
            resume_triggers=["challenge_resolved"],
            # FK-23 §23.5.3: Stage 2b design-challenge is optional.
            gate_stage=ExplorationGateStageSpec(
                stage_id=ExplorationGateStage.DESIGN_CHALLENGE,
                yield_point="design_challenge",
                required=False,
                rollback_on_fail=False,
            ),
        )
        .phase("implementation")
        .max_remediation_rounds(3)
        .phase("closure")
        .substates(["merging", "cleanup", "reporting"])
        .transition("setup", "exploration", guard=mode_is_exploration)
        .transition("setup", "implementation", guard=_mode_is_not_exploration)
        .transition("exploration", "implementation", guard=exploration_gate_approved)
        .transition("implementation", "closure", guard=implementation_completed)
        .hooks(
            pre_transition=["log_transition"],
            post_transition=["emit_telemetry"],
            on_yield=["notify_yield"],
            on_escalate=["notify_escalation"],
        )
        .build()
    )


def _build_concept_workflow() -> WorkflowDefinition:
    return (
        Workflow("concept")
        .phase("setup")
        .guard(preflight_passed)
        # AG3-145 Teilschritt C: setup PAUSES fail-closed awaiting the edge
        # preflight_probe / worktree_report (edge-commissioned provisioning).
        .yield_to(
            "edge_provisioning",
            on="awaiting_edge_provisioning",
            resume_triggers=["edge_report_received"],
        )
        .phase("implementation")
        .phase("closure")
        .transition("setup", "implementation")
        .transition("implementation", "closure")
        .hooks(
            pre_transition=["log_transition"],
            post_transition=["emit_telemetry"],
        )
        .build()
    )


def _build_research_workflow() -> WorkflowDefinition:
    return (
        Workflow("research")
        .phase("setup")
        .guard(preflight_passed)
        # AG3-145 Teilschritt C: setup PAUSES fail-closed awaiting the edge
        # preflight_probe / worktree_report (edge-commissioned provisioning).
        .yield_to(
            "edge_provisioning",
            on="awaiting_edge_provisioning",
            resume_triggers=["edge_report_received"],
        )
        .phase("implementation")
        .phase("closure")
        .transition("setup", "implementation")
        .transition("implementation", "closure")
        .hooks(
            pre_transition=["log_transition"],
            post_transition=["emit_telemetry"],
        )
        .build()
    )


IMPLEMENTATION_WORKFLOW = _build_implementation_workflow()
BUGFIX_WORKFLOW = _build_bugfix_workflow()
CONCEPT_WORKFLOW = _build_concept_workflow()
RESEARCH_WORKFLOW = _build_research_workflow()

_WORKFLOW_MAP: dict[StoryType, WorkflowDefinition] = {
    StoryType.IMPLEMENTATION: IMPLEMENTATION_WORKFLOW,
    StoryType.BUGFIX: BUGFIX_WORKFLOW,
    StoryType.CONCEPT: CONCEPT_WORKFLOW,
    StoryType.RESEARCH: RESEARCH_WORKFLOW,
}


def resolve_workflow(story_type: StoryType) -> WorkflowDefinition:
    """Return the workflow definition for a given story type."""

    workflow = _WORKFLOW_MAP.get(story_type)
    if workflow is None:
        raise WorkflowError(
            f"No workflow registered for story type: {story_type!r}",
            detail={"story_type": str(story_type)},
        )
    return workflow
