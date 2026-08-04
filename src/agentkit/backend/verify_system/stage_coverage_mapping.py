"""Stage coverage mapping derives policy-layer coverage from produced QA stage results."""

from __future__ import annotations

from agentkit.backend.verify_system.routing import QALayerKind
from agentkit.backend.verify_system.stage_registry.registry import StageRegistry
from agentkit.backend.verify_system.stage_registry.stages import StageKind


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
