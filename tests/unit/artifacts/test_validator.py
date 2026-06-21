"""Unit-Tests fuer EnvelopeValidator — Negativpfade fail-closed (AG3-022 §2.1.6)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from agentkit.backend.artifacts.envelope import ArtifactEnvelope
from agentkit.backend.artifacts.errors import (
    EnvelopeFieldError,
    ProducerNotRegisteredError,
)
from agentkit.backend.artifacts.producer import Producer, ProducerId, ProducerType
from agentkit.backend.artifacts.producer_registry import ProducerRegistry
from agentkit.backend.artifacts.validator import EnvelopeValidator
from agentkit.backend.core_types import ArtifactClass, EnvelopeStatus


def _now() -> datetime:
    return datetime.now(tz=UTC)


def _make_registry(
    artifact_class: ArtifactClass = ArtifactClass.QA,
    producer_name: str = "test-producer",
    producer_type: ProducerType = ProducerType.DETERMINISTIC,
) -> ProducerRegistry:
    registry = ProducerRegistry()
    registry.register(artifact_class, producer_name, producer_type)
    return registry


def _make_envelope(
    artifact_class: ArtifactClass = ArtifactClass.QA,
    status: EnvelopeStatus = EnvelopeStatus.PASS,
    producer_name: str = "test-producer",
    producer_type: ProducerType = ProducerType.DETERMINISTIC,
) -> ArtifactEnvelope:
    start = _now()
    return ArtifactEnvelope(
        schema_version="3.0",
        story_id="AG3-022",
        run_id="run-001",
        stage="impl",
        attempt=1,
        producer=Producer(
            type=producer_type,
            name=producer_name,
            id=ProducerId("inst-001"),
        ),
        started_at=start,
        finished_at=start,
        status=status,
        artifact_class=artifact_class,
    )


class TestEnvelopeValidatorStep2ProducerNotRegistered:
    """AK8, Schritt 2: fail-closed bei unregistriertem Producer."""

    def test_registered_producer_passes(self) -> None:
        registry = _make_registry(ArtifactClass.QA, "qa-structural")
        validator = EnvelopeValidator(registry)
        envelope = _make_envelope(ArtifactClass.QA, EnvelopeStatus.PASS, "qa-structural")
        validator.validate(envelope)  # kein Fehler

    def test_unregistered_producer_raises(self) -> None:
        registry = ProducerRegistry()  # leer
        validator = EnvelopeValidator(registry)
        envelope = _make_envelope(ArtifactClass.QA, EnvelopeStatus.PASS, "unknown")
        with pytest.raises(ProducerNotRegisteredError):
            validator.validate(envelope)

    def test_producer_not_registered_for_wrong_class(self) -> None:
        registry = _make_registry(ArtifactClass.WORKER, "worker-prod")
        validator = EnvelopeValidator(registry)
        # Envelope ist QA, aber Producer nur fuer WORKER registriert
        envelope = _make_envelope(ArtifactClass.QA, EnvelopeStatus.PASS, "worker-prod")
        with pytest.raises(ProducerNotRegisteredError):
            validator.validate(envelope)


class TestEnvelopeValidatorStep4Matrix:
    """AK8, Schritt 4: status-vs-artifact_class-Matrix Verletzungen."""

    def test_telemetry_warn_rejected(self) -> None:
        """TELEMETRY erlaubt kein WARN (Matrix §2.1.6.1)."""
        registry = _make_registry(ArtifactClass.TELEMETRY, "telemetry-writer")
        validator = EnvelopeValidator(registry)
        envelope = _make_envelope(ArtifactClass.TELEMETRY, EnvelopeStatus.WARN, "telemetry-writer")
        with pytest.raises(EnvelopeFieldError):
            validator.validate(envelope)

    def test_telemetry_fail_rejected(self) -> None:
        """TELEMETRY erlaubt kein FAIL (Matrix §2.1.6.1)."""
        registry = _make_registry(ArtifactClass.TELEMETRY, "telemetry-writer")
        validator = EnvelopeValidator(registry)
        envelope = _make_envelope(ArtifactClass.TELEMETRY, EnvelopeStatus.FAIL, "telemetry-writer")
        with pytest.raises(EnvelopeFieldError):
            validator.validate(envelope)

    def test_telemetry_pass_accepted(self) -> None:
        """TELEMETRY erlaubt PASS."""
        registry = _make_registry(ArtifactClass.TELEMETRY, "telemetry-writer")
        validator = EnvelopeValidator(registry)
        envelope = _make_envelope(ArtifactClass.TELEMETRY, EnvelopeStatus.PASS, "telemetry-writer")
        validator.validate(envelope)  # kein Fehler

    def test_telemetry_error_accepted(self) -> None:
        """TELEMETRY erlaubt ERROR."""
        registry = _make_registry(ArtifactClass.TELEMETRY, "telemetry-writer")
        validator = EnvelopeValidator(registry)
        envelope = _make_envelope(ArtifactClass.TELEMETRY, EnvelopeStatus.ERROR, "telemetry-writer")
        validator.validate(envelope)  # kein Fehler

    def test_entwurf_warn_rejected(self) -> None:
        """ENTWURF erlaubt kein WARN (Matrix §2.1.6.1)."""
        registry = _make_registry(ArtifactClass.ENTWURF, "exploration-worker")
        validator = EnvelopeValidator(registry)
        envelope = _make_envelope(ArtifactClass.ENTWURF, EnvelopeStatus.WARN, "exploration-worker")
        with pytest.raises(EnvelopeFieldError):
            validator.validate(envelope)

    def test_entwurf_pass_accepted(self) -> None:
        """ENTWURF erlaubt PASS."""
        registry = _make_registry(ArtifactClass.ENTWURF, "exploration-worker")
        validator = EnvelopeValidator(registry)
        envelope = _make_envelope(ArtifactClass.ENTWURF, EnvelopeStatus.PASS, "exploration-worker")
        validator.validate(envelope)  # kein Fehler

    def test_qa_all_statuses_accepted(self) -> None:
        """QA erlaubt alle vier Status."""
        for status in EnvelopeStatus:
            registry = _make_registry(ArtifactClass.QA, "qa-producer")
            validator = EnvelopeValidator(registry)
            envelope = _make_envelope(ArtifactClass.QA, status, "qa-producer")
            validator.validate(envelope)  # kein Fehler

    def test_worker_all_statuses_accepted(self) -> None:
        """WORKER erlaubt alle vier Status."""
        for status in EnvelopeStatus:
            registry = _make_registry(ArtifactClass.WORKER, "worker-prod", ProducerType.WORKER)
            validator = EnvelopeValidator(registry)
            envelope = _make_envelope(
                ArtifactClass.WORKER, status, "worker-prod", ProducerType.WORKER,
            )
            validator.validate(envelope)  # kein Fehler


class TestEnvelopeValidatorStep3Attempt:
    """AK8, Schritt 3: attempt >= 1 (redundant fail-closed)."""

    def test_attempt_one_valid(self) -> None:
        """Attempt=1 passiert den Validator."""
        registry = _make_registry()
        validator = EnvelopeValidator(registry)
        envelope = _make_envelope()
        assert envelope.attempt == 1
        validator.validate(envelope)  # kein Fehler

    def test_pydantic_blocks_attempt_zero(self) -> None:
        """Pydantic blockt attempt=0 bereits; der Validator sieht kein
        ungueltigesEnvelope (Schritt 1 greift vor Schritt 3)."""
        start = _now()
        with pytest.raises(ValidationError):
            ArtifactEnvelope(
                schema_version="3.0",
                story_id="AG3-022",
                run_id="r1",
                stage="impl",
                attempt=0,
                producer=Producer(
                    type=ProducerType.DETERMINISTIC,
                    name="p",
                    id=ProducerId("i"),
                ),
                started_at=start,
                finished_at=start,
                status=EnvelopeStatus.PASS,
                artifact_class=ArtifactClass.QA,
            )


class TestEnvelopeValidatorStep5Timestamps:
    """AK8, Schritt 5: finished_at >= started_at (redundant fail-closed)."""

    def test_pydantic_blocks_reversed_timestamps(self) -> None:
        """Pydantic blockt umgekehrte Timestamps bereits (Schritt 1 greift)."""
        start = _now()
        with pytest.raises(ValidationError):
            ArtifactEnvelope(
                schema_version="3.0",
                story_id="AG3-022",
                run_id="r1",
                stage="impl",
                attempt=1,
                producer=Producer(
                    type=ProducerType.DETERMINISTIC,
                    name="p",
                    id=ProducerId("i"),
                ),
                started_at=start,
                finished_at=start - timedelta(seconds=1),
                status=EnvelopeStatus.PASS,
                artifact_class=ArtifactClass.QA,
            )

    def test_equal_timestamps_valid(self) -> None:
        registry = _make_registry()
        validator = EnvelopeValidator(registry)
        envelope = _make_envelope()
        validator.validate(envelope)  # kein Fehler


class TestEnvelopeValidatorAllClassesMatrix:
    """AK8: Matrix fuer alle ArtifactClass-Werte vollstaendig geprueft."""

    def test_pipeline_all_statuses_accepted(self) -> None:
        for status in EnvelopeStatus:
            registry = _make_registry(ArtifactClass.PIPELINE, "pipeline-runner")
            validator = EnvelopeValidator(registry)
            envelope = _make_envelope(ArtifactClass.PIPELINE, status, "pipeline-runner")
            validator.validate(envelope)

    def test_governance_all_statuses_accepted(self) -> None:
        for status in EnvelopeStatus:
            registry = _make_registry(ArtifactClass.GOVERNANCE, "integrity-gate")
            validator = EnvelopeValidator(registry)
            envelope = _make_envelope(ArtifactClass.GOVERNANCE, status, "integrity-gate")
            validator.validate(envelope)

    def test_handover_all_statuses_accepted(self) -> None:
        for status in EnvelopeStatus:
            registry = _make_registry(ArtifactClass.HANDOVER, "handover-writer", ProducerType.WORKER)
            validator = EnvelopeValidator(registry)
            envelope = _make_envelope(
                ArtifactClass.HANDOVER, status, "handover-writer", ProducerType.WORKER,
            )
            validator.validate(envelope)

    def test_adversarial_all_statuses_accepted(self) -> None:
        for status in EnvelopeStatus:
            registry = _make_registry(
                ArtifactClass.ADVERSARIAL_TEST_SANDBOX, "adversarial-runner"
            )
            validator = EnvelopeValidator(registry)
            envelope = _make_envelope(
                ArtifactClass.ADVERSARIAL_TEST_SANDBOX, status, "adversarial-runner"
            )
            validator.validate(envelope)
