"""Tests for the exploration ENTWURF producer registration (verdrahtung).

Proves the producer is registered both by the dedicated init-hook AND by the
productive ``build_producer_registry`` composition-root path — so the ENTWURF
artifact write surface works in production, not only in a locally-seeded test
registry (AG3-045 AC7; built != wired).
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from agentkit.artifacts import (
    ArtifactEnvelope,
    EnvelopeStatus,
    EnvelopeValidator,
    Producer,
    ProducerId,
    ProducerRegistry,
    ProducerType,
)
from agentkit.artifacts.errors import ProducerNotRegisteredError
from agentkit.bootstrap.composition_root import build_producer_registry
from agentkit.core_types import ArtifactClass
from agentkit.exploration.register import (
    EXPLORATION_ENTWURF_PRODUCER,
    register_exploration_producers,
)

_TS = datetime(2026, 6, 5, 10, 30, tzinfo=UTC)


def _change_frame_envelope() -> ArtifactEnvelope:
    return ArtifactEnvelope(
        schema_version="3.0",
        story_id="AG3-045",
        run_id="run-1",
        stage="exploration-drafting",
        attempt=1,
        producer=Producer(
            type=ProducerType.WORKER,
            name=EXPLORATION_ENTWURF_PRODUCER,
            id=ProducerId("exploration-worker-run-1"),
        ),
        started_at=_TS,
        finished_at=_TS,
        status=EnvelopeStatus.PASS,
        artifact_class=ArtifactClass.ENTWURF,
    )


def test_init_hook_registers_change_frame_worker() -> None:
    registry = ProducerRegistry()
    register_exploration_producers(registry)
    assert registry.known_producers(ArtifactClass.ENTWURF) == {
        EXPLORATION_ENTWURF_PRODUCER
    }
    # The registered envelope validates.
    EnvelopeValidator(registry).validate(_change_frame_envelope())


def test_empty_registry_rejects_change_frame_fail_closed() -> None:
    with pytest.raises(ProducerNotRegisteredError):
        EnvelopeValidator(ProducerRegistry()).validate(_change_frame_envelope())


def test_composition_root_registry_includes_exploration() -> None:
    """Productive wiring: build_producer_registry registers the ENTWURF producer."""
    registry = build_producer_registry()
    assert EXPLORATION_ENTWURF_PRODUCER in registry.known_producers(
        ArtifactClass.ENTWURF
    )
    EnvelopeValidator(registry).validate(_change_frame_envelope())
