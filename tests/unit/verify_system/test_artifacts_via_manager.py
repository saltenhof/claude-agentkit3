"""Migration-Roundtrip-Test: ArtifactManager + StateBackendArtifactRepository.

AG3-023 §2.1.7 — Migration-Roundtrip:
- Instantiiert ArtifactManager mit StateBackendArtifactRepository + ProducerRegistry
- Registriert verify_system-Producer via register_verify_producers
- Schreibt Envelopes per ArtifactManager.write
- Liest via ArtifactManager.read und verifiziert alle Pflichtfelder
  (schema_version, story_id, run_id, stage, attempt, started_at UTC,
  finished_at UTC, status, artifact_class)
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from pathlib import Path

from agentkit.artifacts import (
    ArtifactEnvelope,
    ArtifactManager,
    EnvelopeValidator,
    Producer,
    ProducerId,
    ProducerRegistry,
    ProducerType,
)
from agentkit.core_types import ArtifactClass, EnvelopeStatus
from agentkit.state_backend.store.artifact_repository import StateBackendArtifactRepository
from agentkit.verify_system.register import register_verify_producers

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def verify_registry() -> ProducerRegistry:
    """ProducerRegistry mit allen vier verify-system-Producern."""
    registry = ProducerRegistry()
    register_verify_producers(registry)
    return registry


@pytest.fixture()
def artifact_manager(
    tmp_path: Path,
    verify_registry: ProducerRegistry,
    monkeypatch: pytest.MonkeyPatch,
) -> ArtifactManager:
    """ArtifactManager mit SQLite-Repository und verify-system-Producern."""
    monkeypatch.setenv("AGENTKIT_STATE_BACKEND", "sqlite")
    monkeypatch.setenv("AGENTKIT_ALLOW_SQLITE", "1")
    repository = StateBackendArtifactRepository(store_dir=tmp_path)
    validator = EnvelopeValidator(verify_registry)
    return ArtifactManager(repository=repository, validator=validator)


def _now() -> datetime:
    return datetime.now(tz=UTC)


def _make_qa_envelope(
    *,
    producer_name: str = "verify-system.layer-1-structural",
    producer_type: ProducerType = ProducerType.DETERMINISTIC,
    run_id: str = "run-roundtrip-001",
    attempt: int = 1,
) -> ArtifactEnvelope:
    start = _now()
    return ArtifactEnvelope(
        schema_version="3.0",
        story_id="AG3-023",
        run_id=run_id,
        stage="impl",
        attempt=attempt,
        producer=Producer(
            type=producer_type,
            name=producer_name,
            id=ProducerId("inst-roundtrip-001"),
        ),
        started_at=start,
        finished_at=start,
        status=EnvelopeStatus.PASS,
        artifact_class=ArtifactClass.QA,
    )


# ---------------------------------------------------------------------------
# Migration-Roundtrip-Tests
# ---------------------------------------------------------------------------


class TestMigrationRoundtrip:
    def test_write_and_read_qa_envelope_via_manager(
        self, artifact_manager: ArtifactManager
    ) -> None:
        """ArtifactManager.write -> read preserviert alle Pflichtfelder."""
        env = _make_qa_envelope()
        ref = artifact_manager.write(env)
        loaded = artifact_manager.read(ref)

        # Alle Pflichtfelder verifiziert
        assert loaded.schema_version == "3.0"
        assert loaded.story_id == "AG3-023"
        assert loaded.run_id == "run-roundtrip-001"
        assert loaded.stage == "impl"
        assert loaded.attempt == 1
        assert loaded.status is EnvelopeStatus.PASS
        assert loaded.artifact_class is ArtifactClass.QA

        # UTC tz-awareness muss erhalten bleiben
        started_offset = loaded.started_at.utcoffset()
        finished_offset = loaded.finished_at.utcoffset()
        assert started_offset is not None
        assert finished_offset is not None
        assert started_offset.total_seconds() == 0
        assert finished_offset.total_seconds() == 0

    def test_four_layer_verify_system_roundtrip(
        self, artifact_manager: ArtifactManager
    ) -> None:
        """Vier Layer-Producer koennen Envelopes schreiben; alle per read lesbar."""
        layers = [
            ("verify-system.layer-1-structural", ProducerType.DETERMINISTIC),
            ("verify-system.layer-2-llm", ProducerType.LLM_REVIEWER),
            ("verify-system.layer-3-adversarial", ProducerType.LLM_REVIEWER),
            ("verify-system.layer-4-policy", ProducerType.DETERMINISTIC),
        ]
        refs = []
        for producer_name, producer_type in layers:
            env = _make_qa_envelope(
                producer_name=producer_name,
                producer_type=producer_type,
                run_id=f"run-{producer_name}",
            )
            ref = artifact_manager.write(env)
            refs.append((ref, producer_name))

        for ref, producer_name in refs:
            loaded = artifact_manager.read(ref)
            assert loaded.producer.name == producer_name
            assert loaded.artifact_class is ArtifactClass.QA
            assert loaded.started_at.tzinfo is not None

    def test_manager_exists_true_after_write(
        self, artifact_manager: ArtifactManager
    ) -> None:
        env = _make_qa_envelope()
        ref = artifact_manager.write(env)
        assert artifact_manager.exists(ref) is True

    def test_manager_roundtrip_with_payload(
        self, artifact_manager: ArtifactManager
    ) -> None:
        """Payload wird unveraendert durch den Roundtrip erhalten."""
        payload = {"checks": 7, "findings": [{"id": "f1", "severity": "BLOCKING"}]}
        env = ArtifactEnvelope(
            schema_version="3.0",
            story_id="AG3-023",
            run_id="run-payload-001",
            stage="impl",
            attempt=1,
            producer=Producer(
                type=ProducerType.DETERMINISTIC,
                name="verify-system.layer-1-structural",
                id=ProducerId("inst-payload"),
            ),
            started_at=_now(),
            finished_at=_now(),
            status=EnvelopeStatus.FAIL,
            artifact_class=ArtifactClass.QA,
            payload=payload,
        )
        ref = artifact_manager.write(env)
        loaded = artifact_manager.read(ref)
        assert loaded.payload == payload

    def test_multiple_attempts_are_all_readable(
        self, artifact_manager: ArtifactManager
    ) -> None:
        """Verschiedene attempt-Nummern sind alle lesbar (keine Ueberschreibung)."""
        refs = []
        for attempt in range(1, 4):
            env = _make_qa_envelope(attempt=attempt, run_id="run-attempts")
            ref = artifact_manager.write(env)
            refs.append((ref, attempt))

        for ref, attempt in refs:
            loaded = artifact_manager.read(ref)
            assert loaded.attempt == attempt

    def test_registry_idempotent_re_registration(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Doppelte register_verify_producers-Ausfuehrung wirft keinen Fehler."""
        monkeypatch.setenv("AGENTKIT_STATE_BACKEND", "sqlite")
        monkeypatch.setenv("AGENTKIT_ALLOW_SQLITE", "1")
        registry = ProducerRegistry()
        register_verify_producers(registry)
        register_verify_producers(registry)  # idempotent
        # AG3-026 Re-Review: 7 Producer (Layer 2 split in 3 + alter
        # layer-2-llm fuer Backward-Compat) + AG3-052 qa-sonarqube-gate = 8.
        assert len(registry.known_producers(ArtifactClass.QA)) == 8  # noqa: PLR2004
