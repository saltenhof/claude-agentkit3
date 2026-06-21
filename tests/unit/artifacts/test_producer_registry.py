"""Unit-Tests fuer ProducerRegistry und LLM-Status-Mapping (AG3-022 §2.1.5)."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from agentkit.backend.artifacts.envelope import ArtifactEnvelope
from agentkit.backend.artifacts.errors import LlmStatusMappingError, ProducerNotRegisteredError
from agentkit.backend.artifacts.producer import Producer, ProducerId, ProducerType
from agentkit.backend.artifacts.producer_registry import ProducerRegistry
from agentkit.backend.core_types import ArtifactClass, EnvelopeStatus


def _now() -> datetime:
    return datetime.now(tz=UTC)


def _make_envelope(
    artifact_class: ArtifactClass,
    producer_name: str,
    status: EnvelopeStatus = EnvelopeStatus.PASS,
) -> ArtifactEnvelope:
    start = _now()
    return ArtifactEnvelope(
        schema_version="3.0",
        story_id="AG3-022",
        run_id="run-001",
        stage="impl",
        attempt=1,
        producer=Producer(
            type=ProducerType.DETERMINISTIC,
            name=producer_name,
            id=ProducerId("inst-001"),
        ),
        started_at=start,
        finished_at=start,
        status=status,
        artifact_class=artifact_class,
    )


class TestProducerRegistryClassSeed:
    """AK6, AK12: Alle ArtifactClass-Werte sind per Default geseeded."""

    def test_all_artifact_classes_in_registry(self) -> None:
        registry = ProducerRegistry()
        for ac in ArtifactClass:
            # known_producers gibt leeres Set zurueck, wirft aber keinen Fehler
            assert registry.known_producers(ac) == set()

    def test_all_classes_seeded(self) -> None:
        registry = ProducerRegistry()
        # Alle Klassen sind bekannt (kein KeyError); AG3-015: inkl. prompt_audit.
        for ac in ArtifactClass:
            registry.known_producers(ac)


class TestProducerRegistryRegister:
    """AK6: register() fuegt Producer korrekt hinzu."""

    def test_register_single_producer(self) -> None:
        registry = ProducerRegistry()
        registry.register(ArtifactClass.QA, "qa-structural", ProducerType.DETERMINISTIC)
        assert "qa-structural" in registry.known_producers(ArtifactClass.QA)

    def test_register_multiple_producers(self) -> None:
        registry = ProducerRegistry()
        registry.register(ArtifactClass.QA, "producer-a", ProducerType.DETERMINISTIC)
        registry.register(ArtifactClass.QA, "producer-b", ProducerType.LLM_REVIEWER)
        known = registry.known_producers(ArtifactClass.QA)
        assert "producer-a" in known
        assert "producer-b" in known

    def test_register_different_classes_independent(self) -> None:
        registry = ProducerRegistry()
        registry.register(ArtifactClass.QA, "qa-producer", ProducerType.DETERMINISTIC)
        registry.register(ArtifactClass.WORKER, "worker-producer", ProducerType.WORKER)
        assert "qa-producer" not in registry.known_producers(ArtifactClass.WORKER)
        assert "worker-producer" not in registry.known_producers(ArtifactClass.QA)


class TestProducerRegistryValidate:
    """AK6: validate() ist fail-closed bei unbekannten Producern."""

    def test_registered_producer_passes(self) -> None:
        registry = ProducerRegistry()
        registry.register(ArtifactClass.QA, "test-fixture-producer", ProducerType.DETERMINISTIC)
        envelope = _make_envelope(ArtifactClass.QA, "test-fixture-producer")
        registry.validate(envelope)  # kein Fehler

    def test_unregistered_producer_raises(self) -> None:
        registry = ProducerRegistry()
        envelope = _make_envelope(ArtifactClass.QA, "unknown-producer")
        with pytest.raises(ProducerNotRegisteredError):
            registry.validate(envelope)

    def test_producer_for_wrong_class_raises(self) -> None:
        registry = ProducerRegistry()
        registry.register(ArtifactClass.WORKER, "worker-prod", ProducerType.WORKER)
        # Registriert fuer WORKER, aber Envelope ist QA
        envelope = _make_envelope(ArtifactClass.QA, "worker-prod")
        with pytest.raises(ProducerNotRegisteredError):
            registry.validate(envelope)

    def test_empty_registry_always_fails(self) -> None:
        registry = ProducerRegistry()
        for ac in ArtifactClass:
            envelope = _make_envelope(ac, "any-producer")
            with pytest.raises(ProducerNotRegisteredError):
                registry.validate(envelope)


class TestLlmStatusMapping:
    """AK7, AK12: map_llm_status_to_envelope_status - exaktes FK-71-Mapping."""

    def test_pass_maps_to_pass(self) -> None:
        registry = ProducerRegistry()
        assert registry.map_llm_status_to_envelope_status("PASS") == EnvelopeStatus.PASS

    def test_pass_with_concerns_maps_to_warn(self) -> None:
        """AK7: PASS_WITH_CONCERNS -> WARN (Wire-String nur im LLM-Layer)."""
        registry = ProducerRegistry()
        assert registry.map_llm_status_to_envelope_status("PASS_WITH_CONCERNS") == EnvelopeStatus.WARN

    def test_fail_maps_to_fail(self) -> None:
        registry = ProducerRegistry()
        assert registry.map_llm_status_to_envelope_status("FAIL") == EnvelopeStatus.FAIL

    def test_error_maps_to_error(self) -> None:
        registry = ProducerRegistry()
        assert registry.map_llm_status_to_envelope_status("ERROR") == EnvelopeStatus.ERROR

    def test_timeout_maps_to_error(self) -> None:
        """AK7: TIMEOUT ist Infrastruktur-Fehler -> ERROR."""
        registry = ProducerRegistry()
        assert registry.map_llm_status_to_envelope_status("TIMEOUT") == EnvelopeStatus.ERROR

    def test_unknown_status_raises(self) -> None:
        """AK7: Fail-closed bei unbekanntem LLM-Status."""
        registry = ProducerRegistry()
        with pytest.raises(LlmStatusMappingError):
            registry.map_llm_status_to_envelope_status("PASS_WITH_WARNINGS")

    def test_empty_string_raises(self) -> None:
        registry = ProducerRegistry()
        with pytest.raises(LlmStatusMappingError):
            registry.map_llm_status_to_envelope_status("")

    def test_lowercase_raises(self) -> None:
        """Wire-Strings sind uppercase; lowercase ist ungueltig."""
        registry = ProducerRegistry()
        with pytest.raises(LlmStatusMappingError):
            registry.map_llm_status_to_envelope_status("pass")

    def test_pass_with_concerns_not_envelope_status(self) -> None:
        """AK7: PASS_WITH_CONCERNS existiert nicht als EnvelopeStatus."""
        with pytest.raises(ValueError):
            EnvelopeStatus("PASS_WITH_CONCERNS")


# ---------------------------------------------------------------------------
# Regressions-Tests: Codex-Finding ERROR — Typ-Drift muss fail-closed sein
# ---------------------------------------------------------------------------


class TestProducerTypeMismatch:
    """Codex-Finding ERROR: gleicher Name + abweichender ProducerType abgelehnt."""

    def test_same_name_drift_to_llm_rejected(self) -> None:
        from agentkit.backend.artifacts.errors import ProducerTypeMismatchError

        registry = ProducerRegistry()
        registry.register(ArtifactClass.QA, "qa-structural", ProducerType.DETERMINISTIC)
        envelope = ArtifactEnvelope(
            schema_version="3.0",
            story_id="AG3-022",
            run_id="run-001",
            stage="impl",
            attempt=1,
            producer=Producer(
                type=ProducerType.LLM_REVIEWER,
                name="qa-structural",
                id=ProducerId("inst-001"),
            ),
            started_at=_now(),
            finished_at=_now(),
            status=EnvelopeStatus.PASS,
            artifact_class=ArtifactClass.QA,
        )
        with pytest.raises(ProducerTypeMismatchError):
            registry.validate(envelope)

    def test_same_name_drift_to_worker_rejected(self) -> None:
        from agentkit.backend.artifacts.errors import ProducerTypeMismatchError

        registry = ProducerRegistry()
        registry.register(ArtifactClass.WORKER, "impl-worker", ProducerType.WORKER)
        envelope = ArtifactEnvelope(
            schema_version="3.0",
            story_id="AG3-022",
            run_id="run-001",
            stage="impl",
            attempt=1,
            producer=Producer(
                type=ProducerType.DETERMINISTIC,
                name="impl-worker",
                id=ProducerId("inst-001"),
            ),
            started_at=_now(),
            finished_at=_now(),
            status=EnvelopeStatus.PASS,
            artifact_class=ArtifactClass.WORKER,
        )
        with pytest.raises(ProducerTypeMismatchError):
            registry.validate(envelope)

    def test_matching_type_passes(self) -> None:
        registry = ProducerRegistry()
        registry.register(ArtifactClass.QA, "qa-structural", ProducerType.DETERMINISTIC)
        envelope = ArtifactEnvelope(
            schema_version="3.0",
            story_id="AG3-022",
            run_id="run-001",
            stage="impl",
            attempt=1,
            producer=Producer(
                type=ProducerType.DETERMINISTIC,
                name="qa-structural",
                id=ProducerId("inst-001"),
            ),
            started_at=_now(),
            finished_at=_now(),
            status=EnvelopeStatus.PASS,
            artifact_class=ArtifactClass.QA,
        )
        registry.validate(envelope)  # darf NICHT werfen
