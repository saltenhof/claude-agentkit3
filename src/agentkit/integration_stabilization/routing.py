"""Exploration-mandatory routing for integration_stabilization (FK-05 §5.6).

AC8: For ``implementation_contract = integration_stabilization`` the setup
routing FORCES exploration and FORBIDS routing to execution without an
approved manifest.

This module owns the typed routing decision for the integration-stabilization
special path. It is consumed by ``routing_rules.py`` alongside the standard
routing logic (no second routing system — it extends the existing routing
rules functions).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from agentkit.story_context_manager.types import ImplementationContract

if TYPE_CHECKING:
    from agentkit.integration_stabilization.models import ManifestApprovalRecord

__all__ = [
    "IntegrationStabilizationRoutingDecision",
    "decide_integration_stabilization_routing",
    "is_integration_stabilization_contract",
]


@dataclass(frozen=True)
class IntegrationStabilizationRoutingDecision:
    """Routing decision for integration_stabilization stories (FK-05 §5.6).

    Attributes:
        must_run_exploration: True iff exploration is mandatory (always True
            for integration_stabilization before manifest approval).
        execution_blocked: True iff execution-routing is blocked (no approved
            manifest present).
        block_reason: Human-readable reason for an execution block.
    """

    must_run_exploration: bool
    execution_blocked: bool
    block_reason: str = ""


def is_integration_stabilization_contract(
    implementation_contract: ImplementationContract | None,
) -> bool:
    """Return True iff the contract is integration_stabilization.

    Args:
        implementation_contract: The story's implementation contract field.

    Returns:
        True iff ``implementation_contract == INTEGRATION_STABILIZATION``.
    """
    return implementation_contract is ImplementationContract.INTEGRATION_STABILIZATION


def decide_integration_stabilization_routing(
    *,
    approval_record: ManifestApprovalRecord | None,
) -> IntegrationStabilizationRoutingDecision:
    """Decide routing for an integration_stabilization story (FK-05 §5.6).

    Rules:
    - Exploration is ALWAYS mandatory for integration_stabilization.
    - Execution-routing is BLOCKED until a manifest is approved.

    Args:
        approval_record: The current approval record, or ``None`` if not yet
            approved.

    Returns:
        An ``IntegrationStabilizationRoutingDecision`` describing the
        forced-exploration and (optional) execution block.
    """
    if approval_record is None:
        return IntegrationStabilizationRoutingDecision(
            must_run_exploration=True,
            execution_blocked=True,
            block_reason=(
                "integration_stabilization requires an approved "
                "IntegrationScopeManifest before execution-routing is allowed "
                "(FK-05 §5.6, invariant: "
                "integration_contract_requires_exploration_first)."
            ),
        )
    # Manifest approved: exploration still mandatory (FK-05 §5.6 says exploration
    # is always required; it runs first and produces the manifest), but execution
    # is no longer blocked post-approval.
    return IntegrationStabilizationRoutingDecision(
        must_run_exploration=True,
        execution_blocked=False,
    )
