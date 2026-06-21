"""Init hook for requirements-coverage artifact producers."""

from __future__ import annotations

from typing import TYPE_CHECKING, Final

from agentkit.backend.artifacts import ProducerType
from agentkit.backend.core_types import ArtifactClass

if TYPE_CHECKING:
    from agentkit.backend.artifacts import ProducerRegistry

ARE_CONTEXT_LOADER_PRODUCER: Final[str] = "qa-are-context-loader"
ARE_GATE_PRODUCER: Final[str] = "qa-are-gate"
ARE_BUNDLE_STAGE: Final[str] = "are_bundle"
ARE_GATE_STAGE: Final[str] = "are_gate"


def register_requirements_coverage_producers(registry: ProducerRegistry) -> None:
    """Register deterministic ARE QA artifact producers."""

    registry.register(
        ArtifactClass.QA,
        ARE_CONTEXT_LOADER_PRODUCER,
        ProducerType.DETERMINISTIC,
    )
    registry.register(ArtifactClass.QA, ARE_GATE_PRODUCER, ProducerType.DETERMINISTIC)


__all__ = [
    "ARE_BUNDLE_STAGE",
    "ARE_CONTEXT_LOADER_PRODUCER",
    "ARE_GATE_PRODUCER",
    "ARE_GATE_STAGE",
    "register_requirements_coverage_producers",
]
