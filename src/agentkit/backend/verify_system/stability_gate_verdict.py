"""Integration-stabilization stability verdict production adds the required closure gate result."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from agentkit.backend.verify_system.contract import VerifyContextBundle
    from agentkit.backend.verify_system.protocols import LayerResult
    from agentkit.backend.verify_system.system import VerifySystem


def _maybe_produce_is_stability_gate(
    system: VerifySystem,
    *,
    ctx: VerifyContextBundle,
    story_id: str,
    story_ctx: object | None,
    layer_results: list[LayerResult],
) -> None:
    """Produce the stability_gate Layer-4 result for IS stories (AG3-069, AC5/AC12).

    No-op for standard stories (the contract gate). For
    integration_stabilization it runs the REAL stability_gate producer over the
    actually-touched surfaces (from the QA change-evidence port), appends the
    produced Layer-4 :class:`LayerResult` to ``layer_results`` (so the
    PolicyEngine aggregation consumes it and the registry-bound missing-stage
    check is satisfied), persists the gate verdict and emits the telemetry event.

    Args:
        system: The owning ``VerifySystem``.
        ctx: The run-time context bundle (run_id + story_dir).
        story_id: The story display id.
        story_ctx: The resolved ``StoryContext`` (or ``None``).
        layer_results: Mutable accumulator the produced gate result is appended to.
    """
    from agentkit.backend.story_context_manager.models import StoryContext
    from agentkit.backend.story_context_manager.types import ImplementationContract

    if not (
        isinstance(story_ctx, StoryContext)
        and story_ctx.implementation_contract
        is ImplementationContract.INTEGRATION_STABILIZATION
    ):
        return

    from agentkit.backend.integration_stabilization.stability_gate_producer import (
        produce_stability_gate_layer_result,
    )

    evidence = system.implementation_change_evidence_port.collect(ctx.story_dir)
    touched_paths = tuple(evidence.changed_files) if evidence.available else ()

    result = produce_stability_gate_layer_result(
        story_dir=ctx.story_dir,
        run_id=ctx.run_id,
        touched_paths=touched_paths,
        emitter=system.conformance_emitter,
        story_id=story_id,
        project_key=story_ctx.project_key,
    )
    layer_results.append(result)
