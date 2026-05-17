"""Unit-Tests fuer ArtifactManager (AG3-023 §2.1.1).

Deckt write/read/exists + fail-closed Validierungssemantik ab. Verwendet
einen In-Memory-FakeRepository (kein Mock — vollwertige Test-Impl), damit
das Manager-Verhalten ohne State-Backend pruefbar ist.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from agentkit.artifacts import (
    ArtifactEnvelope,
    ArtifactManager,
    ArtifactNotFoundError,
    ArtifactReference,
    ArtifactRepository,
    EnvelopeFieldError,
    EnvelopeValidator,
    Producer,
    ProducerId,
    ProducerNotRegisteredError,
    ProducerRegistry,
    ProducerType,
)
from agentkit.core_types import ArtifactClass, EnvelopeStatus


class _InMemoryRepository:
    """In-Memory-ArtifactRepository fuer Unit-Tests (kein Mock)."""

    def __init__(self) -> None:
        self._store: dict[str, ArtifactEnvelope] = {}

    def write_envelope(self, envelope: ArtifactEnvelope) -> ArtifactReference:
        key = (
            f"{envelope.artifact_class}|{envelope.story_id}|"
            f"{envelope.run_id}|{envelope.stage}|{envelope.attempt}"
        )
        self._store[key] = envelope
        return ArtifactReference(
            artifact_class=envelope.artifact_class,
            story_id=envelope.story_id,
            run_id=envelope.run_id,
            record_key=key,
        )

    def read_envelope(self, reference: ArtifactReference) -> ArtifactEnvelope | None:
        return self._store.get(reference.record_key)

    def find_latest_envelope(
        self,
        *,
        story_id: str,
        run_id: str | None,
        artifact_class: ArtifactClass,
        stage: str,
    ) -> ArtifactEnvelope | None:
        matches = [
            e for e in self._store.values()
            if e.story_id == story_id
            and (run_id is None or e.run_id == run_id)
            and e.artifact_class == artifact_class
            and e.stage == stage
        ]
        if not matches:
            return None
        return max(matches, key=lambda e: e.attempt)

    def exists_envelope(self, reference: ArtifactReference) -> bool:
        return reference.record_key in self._store


def _now() -> datetime:
    return datetime.now(tz=UTC)


def _make_registry() -> ProducerRegistry:
    registry = ProducerRegistry()
    registry.register(
        ArtifactClass.QA, "qa-structural", ProducerType.DETERMINISTIC,
    )
    return registry


def _make_envelope(*, status: EnvelopeStatus = EnvelopeStatus.PASS) -> ArtifactEnvelope:
    start = _now()
    return ArtifactEnvelope(
        schema_version="3.0",
        story_id="AG3-023",
        run_id="run-001",
        stage="impl",
        attempt=1,
        producer=Producer(
            type=ProducerType.DETERMINISTIC,
            name="qa-structural",
            id=ProducerId("inst-001"),
        ),
        started_at=start,
        finished_at=start,
        status=status,
        artifact_class=ArtifactClass.QA,
    )


def _make_manager() -> ArtifactManager:
    registry = _make_registry()
    validator = EnvelopeValidator(registry)
    repository: ArtifactRepository = _InMemoryRepository()
    return ArtifactManager(repository, validator)


class TestArtifactManagerWriteHappyPath:
    def test_write_returns_reference(self) -> None:
        manager = _make_manager()
        envelope = _make_envelope()
        reference = manager.write(envelope)
        assert isinstance(reference, ArtifactReference)
        assert reference.artifact_class is ArtifactClass.QA
        assert reference.story_id == "AG3-023"

    def test_write_then_read_roundtrip(self) -> None:
        manager = _make_manager()
        envelope = _make_envelope()
        reference = manager.write(envelope)
        loaded = manager.read(reference)
        assert loaded == envelope

    def test_exists_after_write(self) -> None:
        manager = _make_manager()
        envelope = _make_envelope()
        reference = manager.write(envelope)
        assert manager.exists(reference) is True


class TestArtifactManagerFailClosed:
    def test_write_unknown_producer_rejected(self) -> None:
        manager = _make_manager()
        # Producer-Name ``unknown`` ist nicht registriert.
        start = _now()
        bad_envelope = ArtifactEnvelope(
            schema_version="3.0",
            story_id="AG3-023",
            run_id="r1",
            stage="impl",
            attempt=1,
            producer=Producer(
                type=ProducerType.DETERMINISTIC,
                name="unknown",
                id=ProducerId("inst-x"),
            ),
            started_at=start,
            finished_at=start,
            status=EnvelopeStatus.PASS,
            artifact_class=ArtifactClass.QA,
        )
        with pytest.raises(ProducerNotRegisteredError):
            manager.write(bad_envelope)

    def test_write_status_class_mismatch_rejected(self) -> None:
        # TELEMETRY erlaubt kein WARN (AG3-022 §2.1.6.1).
        registry = ProducerRegistry()
        registry.register(
            ArtifactClass.TELEMETRY, "telemetry-writer", ProducerType.DETERMINISTIC,
        )
        manager = ArtifactManager(_InMemoryRepository(), EnvelopeValidator(registry))
        start = _now()
        bad_envelope = ArtifactEnvelope(
            schema_version="3.0",
            story_id="AG3-023",
            run_id="r1",
            stage="impl",
            attempt=1,
            producer=Producer(
                type=ProducerType.DETERMINISTIC,
                name="telemetry-writer",
                id=ProducerId("inst-x"),
            ),
            started_at=start,
            finished_at=start,
            status=EnvelopeStatus.WARN,
            artifact_class=ArtifactClass.TELEMETRY,
        )
        with pytest.raises(EnvelopeFieldError):
            manager.write(bad_envelope)

    def test_read_missing_raises_not_found(self) -> None:
        manager = _make_manager()
        # Reference auf ein nie geschriebenes Artefakt.
        ghost = ArtifactReference(
            artifact_class=ArtifactClass.QA,
            story_id="AG3-023",
            run_id="ghost",
            record_key="qa|AG3-023|ghost|impl|1",
        )
        with pytest.raises(ArtifactNotFoundError):
            manager.read(ghost)

    def test_exists_missing_returns_false(self) -> None:
        manager = _make_manager()
        ghost = ArtifactReference(
            artifact_class=ArtifactClass.QA,
            story_id="AG3-023",
            run_id="ghost",
            record_key="qa|AG3-023|ghost|impl|1",
        )
        assert manager.exists(ghost) is False
