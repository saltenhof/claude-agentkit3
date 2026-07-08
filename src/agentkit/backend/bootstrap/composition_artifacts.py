"""Artifact and producer-registry composition builders."""

from __future__ import annotations

from typing import TYPE_CHECKING

from agentkit.backend.artifacts import ArtifactManager, EnvelopeValidator, ProducerRegistry
from agentkit.backend.exploration.register import register_exploration_producers
from agentkit.backend.implementation.register import register_implementation_producers
from agentkit.backend.prompt_runtime.register import register_prompt_runtime_producers
from agentkit.backend.requirements_coverage.register import register_requirements_coverage_producers
from agentkit.backend.state_backend.store.artifact_repository import StateBackendArtifactRepository
from agentkit.backend.verify_system.register import register_verify_producers

if TYPE_CHECKING:
    from pathlib import Path


def build_producer_registry() -> ProducerRegistry:
    """Create a fresh ``ProducerRegistry`` and call all known BC init hooks.

    Current state: ``register_exploration_producers`` (AG3-045,
    ``ArtifactClass.ENTWURF``), ``register_implementation_producers`` (AG3-044,
    ``ArtifactClass.HANDOVER``), ``register_verify_producers`` (AG3-023 +
    AG3-044 ``ArtifactClass.ADVERSARIAL_TEST_SANDBOX``) and
    ``register_prompt_runtime_producers`` (AG3-015, FK-44 §44.6 --
    ``ArtifactClass.PROMPT_AUDIT``) are wired. Further BC-init hooks
    (telemetry, governance, closure ...) are added analogously in their
    follow-up stories.

    Returns:
        A ``ProducerRegistry`` with all producers known today.

    Notes:
        The order of the init hooks is deterministic (BC-alphabetical or
        capability order). Every hook is idempotent.
    """
    from agentkit.backend.exploration.review.register import (
        register_exploration_review_producers,
    )

    registry = ProducerRegistry()
    register_exploration_producers(registry)
    register_exploration_review_producers(registry)
    register_implementation_producers(registry)
    register_prompt_runtime_producers(registry)
    register_requirements_coverage_producers(registry)
    register_verify_producers(registry)
    return registry


def build_artifact_manager(store_dir: Path) -> ArtifactManager:
    """Create a fully wired ``ArtifactManager``.

    Composition root for the artifact write/read path: binds the
    producer registry, the envelope validator and the StateBackend
    repository together. Consumer BCs (e.g. ``verify_system.artifacts``)
    receive the manager via DI and do not know the repository
    implementation.

    Args:
        store_dir: Base directory of the state backend (SQLite stores
            under ``store_dir/.agentkit/...``; Postgres ignores the
            path).

    Returns:
        ``ArtifactManager`` with all verify producers registered.
    """
    registry = build_producer_registry()
    validator = EnvelopeValidator(registry)
    repository = StateBackendArtifactRepository(store_dir)
    return ArtifactManager(repository, validator)
