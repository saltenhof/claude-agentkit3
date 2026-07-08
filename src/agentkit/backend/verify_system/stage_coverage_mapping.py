"""Stage coverage mapping derives policy-layer coverage from produced QA stage results."""

from __future__ import annotations

from typing import TYPE_CHECKING

from agentkit.backend.verify_system.routing import QALayerKind
from agentkit.backend.verify_system.stage_registry.registry import StageRegistry
from agentkit.backend.verify_system.stage_registry.stages import StageKind

if TYPE_CHECKING:
    from agentkit.backend.verify_system.protocols import LayerResult


def _max_layer_reached(layer_results: list[LayerResult]) -> int:
    """Derive the highest QA layer that produced a result (FK-33 §33.7.2)."""
    from agentkit.backend.story_context_manager.types import ImplementationContract
    from agentkit.backend.verify_system.stage_registry.registry import (
        is_integration_stabilization_stage,
    )

    registry = StageRegistry()
    reached: list[int] = []
    for stage_id in _produced_stage_ids(layer_results, registry):
        contract = (
            ImplementationContract.INTEGRATION_STABILIZATION
            if is_integration_stabilization_stage(stage_id)
            else None
        )
        stage = registry.stage_for_id(stage_id, implementation_contract=contract)
        if stage is not None:
            reached.append(stage.layer)
    return max(reached) if reached else 1


def _traversed_layers(layer_kinds: tuple[QALayerKind, ...]) -> frozenset[int]:
    """Return the EXACT set of QA layer numbers the route planned (FK-33 §33.7.2).

    Maps the routed :class:`QALayerKind` tuple to the layer numbers whose stages
    the policy engine should expect. The route is not always contiguous: the
    Exploration context runs Layer 2 + Layer 4 and SKIPS Layer 1, so its set is
    ``{2, 4}`` -- a Layer-1 stage is therefore not expected (and not reported
    missing) on that path.
    """
    registry = StageRegistry()
    return frozenset(_layer_number_for_kind(kind, registry) for kind in layer_kinds)


def _produced_stage_ids(
    layer_results: list[LayerResult],
    registry: StageRegistry,
) -> set[str]:
    """Return produced stage IDs from result names and registry metadata."""
    produced: set[str] = set()
    for result in layer_results:
        metadata_stage_ids = result.metadata.get("stage_ids")
        if isinstance(metadata_stage_ids, (list, tuple, set, frozenset)):
            produced.update(str(stage_id) for stage_id in metadata_stage_ids)
        for stage in registry.stages:
            if result.layer == stage.stage_id or result.layer == _legacy_result_name(stage.stage_id):
                produced.add(stage.stage_id)
    return produced


def _legacy_result_name(stage_id: str) -> str:
    """Return the legacy LayerResult name for a stage ID."""
    if stage_id.endswith("_impl"):
        return stage_id.removesuffix("_impl")
    return stage_id


def _layer_number_for_kind(kind: QALayerKind, registry: StageRegistry) -> int:
    """Resolve a routed QA kind to its layer via the stage registry."""
    if kind is QALayerKind.STRUCTURAL:
        stage = registry.stage_for_id("artifact.protocol")
    elif kind is QALayerKind.SONARQUBE_GATE:
        stage = registry.stage_for_id("sonarqube_gate")
    elif kind is QALayerKind.LLM_EVALUATOR:
        stage = next((s for s in registry.stages if s.kind is StageKind.LLM_EVALUATION), None)
    elif kind is QALayerKind.ADVERSARIAL:
        stage = registry.stage_for_id("adversarial")
    else:
        stage = registry.stage_for_id("policy")
    if stage is None:  # pragma: no cover - canonical registry invariant
        msg = f"cannot resolve layer for routed QA kind {kind!r}"
        raise ValueError(msg)
    return stage.layer
