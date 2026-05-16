"""Contract-Tests fuer StateBackendArtifactRepository (Postgres-Backend).

AG3-023 §2.1.7 — Roundtrip-Tests gegen echtes Postgres.
Wird geskippt, wenn kein Docker oder kein Postgres-Setup verfuegbar.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from pathlib import Path

from agentkit.artifacts.envelope import ArtifactEnvelope
from agentkit.artifacts.producer import Producer, ProducerId, ProducerType
from agentkit.artifacts.reference import ArtifactReference
from agentkit.core_types import ArtifactClass, EnvelopeStatus
from agentkit.state_backend.store.artifact_repository import StateBackendArtifactRepository

pytest_plugins = ("tests.fixtures.postgres_backend",)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _now() -> datetime:
    return datetime.now(tz=UTC)


def _make_envelope(
    *,
    story_id: str = "AG3-023",
    run_id: str = "run-pg-001",
    stage: str = "impl",
    attempt: int = 1,
    producer_name: str = "verify-system.layer-1-structural",
    producer_type: ProducerType = ProducerType.DETERMINISTIC,
    status: EnvelopeStatus = EnvelopeStatus.PASS,
    artifact_class: ArtifactClass = ArtifactClass.QA,
    payload: dict[str, object] | None = None,
) -> ArtifactEnvelope:
    start = _now()
    return ArtifactEnvelope(
        schema_version="3.0",
        story_id=story_id,
        run_id=run_id,
        stage=stage,
        attempt=attempt,
        producer=Producer(
            type=producer_type,
            name=producer_name,
            id=ProducerId("inst-pg-001"),
        ),
        started_at=start,
        finished_at=start,
        status=status,
        artifact_class=artifact_class,
        payload=payload,
    )


# ---------------------------------------------------------------------------
# Contract tests
# ---------------------------------------------------------------------------


@pytest.mark.contract
def test_postgres_artifact_roundtrip(
    tmp_path: Path,
    postgres_backend_env: object,
) -> None:
    """write -> read Roundtrip gegen echtes Postgres."""
    repo = StateBackendArtifactRepository(store_dir=tmp_path)
    env = _make_envelope()
    ref = repo.write_envelope(env)
    loaded = repo.read_envelope(ref)
    assert loaded is not None
    assert loaded.story_id == env.story_id
    assert loaded.run_id == env.run_id
    assert loaded.artifact_class is env.artifact_class
    assert loaded.status is env.status
    assert loaded.started_at.tzinfo is not None
    assert loaded.finished_at.tzinfo is not None


@pytest.mark.contract
def test_postgres_artifact_exists(
    tmp_path: Path,
    postgres_backend_env: object,
) -> None:
    """exists_envelope korrekt nach write und fuer missing."""
    repo = StateBackendArtifactRepository(store_dir=tmp_path)
    env = _make_envelope(run_id="run-pg-exists")
    ref = repo.write_envelope(env)
    assert repo.exists_envelope(ref) is True

    ghost = ArtifactReference(
        artifact_class=ArtifactClass.QA,
        story_id="AG3-023",
        run_id="ghost-pg",
        record_key="AG3-023|ghost-pg|impl|1|qa|verify-system.layer-1-structural",
    )
    assert repo.exists_envelope(ghost) is False


@pytest.mark.contract
def test_postgres_artifact_double_write_idempotent(
    tmp_path: Path,
    postgres_backend_env: object,
) -> None:
    """Zweiter write mit gleichen Feldern darf keinen Fehler werfen."""
    repo = StateBackendArtifactRepository(store_dir=tmp_path)
    env = _make_envelope(run_id="run-pg-dupe")
    ref1 = repo.write_envelope(env)
    ref2 = repo.write_envelope(env)
    assert ref1.record_key == ref2.record_key


@pytest.mark.contract
def test_postgres_all_artifact_classes(
    tmp_path: Path,
    postgres_backend_env: object,
) -> None:
    """Alle acht ArtifactClass-Wire-Werte koennen persistiert und gelesen werden."""
    repo = StateBackendArtifactRepository(store_dir=tmp_path)
    all_classes = [
        (ArtifactClass.WORKER, ProducerType.WORKER),
        (ArtifactClass.QA, ProducerType.DETERMINISTIC),
        (ArtifactClass.PIPELINE, ProducerType.DETERMINISTIC),
        (ArtifactClass.TELEMETRY, ProducerType.DETERMINISTIC),
        (ArtifactClass.GOVERNANCE, ProducerType.DETERMINISTIC),
        (ArtifactClass.ENTWURF, ProducerType.WORKER),
        (ArtifactClass.HANDOVER, ProducerType.WORKER),
        (ArtifactClass.ADVERSARIAL_TEST_SANDBOX, ProducerType.LLM_REVIEWER),
    ]
    for artifact_class, producer_type in all_classes:
        env = _make_envelope(
            artifact_class=artifact_class,
            producer_type=producer_type,
            producer_name=f"producer-{artifact_class.value}",
            run_id=f"run-pg-{artifact_class.value}",
        )
        ref = repo.write_envelope(env)
        loaded = repo.read_envelope(ref)
        assert loaded is not None, f"read returned None for {artifact_class}"
        assert loaded.artifact_class is artifact_class
