"""Unit-Tests fuer ArtifactEnvelope und ENVELOPE_SCHEMA_VERSION (AG3-022 §2.1.2)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from agentkit.artifacts.envelope import ENVELOPE_SCHEMA_VERSION, ArtifactEnvelope
from agentkit.artifacts.producer import Producer, ProducerId, ProducerType
from agentkit.core_types import ArtifactClass, EnvelopeStatus


def _make_producer(name: str = "test-worker") -> Producer:
    return Producer(
        type=ProducerType.WORKER,
        name=name,
        id=ProducerId("inst-001"),
    )


def _now() -> datetime:
    return datetime.now(tz=UTC)


class TestEnvelopeSchemaVersion:
    """AK3, AK9: ENVELOPE_SCHEMA_VERSION == '3.0'."""

    def test_schema_version_constant(self) -> None:
        assert ENVELOPE_SCHEMA_VERSION == "3.0"

    def test_envelope_schema_version_literal(self) -> None:
        start = _now()
        env = ArtifactEnvelope(
            schema_version="3.0",
            story_id="AG3-022",
            run_id="r1",
            stage="impl",
            attempt=1,
            producer=_make_producer(),
            started_at=start,
            finished_at=start,
            status=EnvelopeStatus.PASS,
            artifact_class=ArtifactClass.QA,
        )
        assert env.schema_version == "3.0"

    def test_wrong_schema_version_rejected(self) -> None:
        start = _now()
        with pytest.raises(ValidationError):
            ArtifactEnvelope.model_validate(
                {
                    "schema_version": "4.0",
                    "story_id": "AG3-022",
                    "run_id": "r1",
                    "stage": "impl",
                    "attempt": 1,
                    "producer": {
                        "type": "WORKER",
                        "name": "test-worker",
                        "id": "inst-001",
                    },
                    "started_at": start,
                    "finished_at": start,
                    "status": "PASS",
                    "artifact_class": "qa",
                }
            )


class TestArtifactEnvelopeRequiredFields:
    """AK2: Pflichtfelder vorhanden und Pydantic erzwingt sie."""

    def _base_kwargs(self) -> dict[object, object]:
        start = _now()
        return {
            "schema_version": "3.0",
            "story_id": "AG3-022",
            "run_id": "run-001",
            "stage": "impl",
            "attempt": 1,
            "producer": _make_producer(),
            "started_at": start,
            "finished_at": start,
            "status": EnvelopeStatus.PASS,
            "artifact_class": ArtifactClass.QA,
        }

    def test_valid_envelope_created(self) -> None:
        env = ArtifactEnvelope(**self._base_kwargs())  # type: ignore[arg-type]
        assert env.story_id == "AG3-022"

    def test_payload_optional(self) -> None:
        env = ArtifactEnvelope(**self._base_kwargs())  # type: ignore[arg-type]
        assert env.payload is None

    def test_payload_with_data(self) -> None:
        kwargs = self._base_kwargs()
        kwargs["payload"] = {"key": "value", "num": 42}
        env = ArtifactEnvelope(**kwargs)  # type: ignore[arg-type]
        assert env.payload == {"key": "value", "num": 42}

    def test_frozen(self) -> None:
        env = ArtifactEnvelope(**self._base_kwargs())  # type: ignore[arg-type]
        with pytest.raises(ValidationError):
            env.story_id = "OTHER-1"  # type: ignore[misc]

    def test_extra_field_forbidden(self) -> None:
        kwargs = self._base_kwargs()
        kwargs["unknown"] = "value"
        with pytest.raises(ValidationError):
            ArtifactEnvelope.model_validate(kwargs)


class TestStoryIdValidator:
    """AK2: story_id Pattern ^[A-Z][A-Z0-9]+-\\d+$."""

    def _make_env(self, story_id: str) -> ArtifactEnvelope:
        start = _now()
        return ArtifactEnvelope(
            schema_version="3.0",
            story_id=story_id,
            run_id="r1",
            stage="impl",
            attempt=1,
            producer=_make_producer(),
            started_at=start,
            finished_at=start,
            status=EnvelopeStatus.PASS,
            artifact_class=ArtifactClass.QA,
        )

    def test_valid_story_ids(self) -> None:
        for sid in ("AG3-022", "AK3-042", "AB-1", "XY-999"):
            env = self._make_env(sid)
            assert env.story_id == sid

    def test_lowercase_prefix_rejected(self) -> None:
        with pytest.raises(ValidationError):
            self._make_env("ag3-022")

    def test_no_number_rejected(self) -> None:
        with pytest.raises(ValidationError):
            self._make_env("AG3-")

    def test_only_numbers_rejected(self) -> None:
        with pytest.raises(ValidationError):
            self._make_env("123-456")

    def test_space_rejected(self) -> None:
        with pytest.raises(ValidationError):
            self._make_env("AG 3-022")


class TestAttemptValidator:
    """AK2: attempt >= 1."""

    def _make_env(self, attempt: int) -> ArtifactEnvelope:
        start = _now()
        return ArtifactEnvelope(
            schema_version="3.0",
            story_id="AG3-022",
            run_id="r1",
            stage="impl",
            attempt=attempt,
            producer=_make_producer(),
            started_at=start,
            finished_at=start,
            status=EnvelopeStatus.PASS,
            artifact_class=ArtifactClass.QA,
        )

    def test_attempt_one_valid(self) -> None:
        env = self._make_env(1)
        assert env.attempt == 1

    def test_attempt_higher_valid(self) -> None:
        env = self._make_env(5)
        assert env.attempt == 5

    def test_attempt_zero_rejected(self) -> None:
        with pytest.raises(ValidationError):
            self._make_env(0)

    def test_attempt_negative_rejected(self) -> None:
        with pytest.raises(ValidationError):
            self._make_env(-1)


class TestTimestampValidator:
    """AK2: finished_at >= started_at."""

    def test_equal_timestamps_valid(self) -> None:
        start = _now()
        env = ArtifactEnvelope(
            schema_version="3.0",
            story_id="AG3-022",
            run_id="r1",
            stage="impl",
            attempt=1,
            producer=_make_producer(),
            started_at=start,
            finished_at=start,
            status=EnvelopeStatus.PASS,
            artifact_class=ArtifactClass.QA,
        )
        assert env.finished_at == env.started_at

    def test_finished_before_started_rejected(self) -> None:
        start = _now()
        finished = start - timedelta(seconds=1)
        with pytest.raises(ValidationError):
            ArtifactEnvelope(
                schema_version="3.0",
                story_id="AG3-022",
                run_id="r1",
                stage="impl",
                attempt=1,
                producer=_make_producer(),
                started_at=start,
                finished_at=finished,
                status=EnvelopeStatus.PASS,
                artifact_class=ArtifactClass.QA,
            )

    def test_finished_after_started_valid(self) -> None:
        start = _now()
        finished = start + timedelta(minutes=5)
        env = ArtifactEnvelope(
            schema_version="3.0",
            story_id="AG3-022",
            run_id="r1",
            stage="impl",
            attempt=1,
            producer=_make_producer(),
            started_at=start,
            finished_at=finished,
            status=EnvelopeStatus.PASS,
            artifact_class=ArtifactClass.QA,
        )
        assert env.finished_at > env.started_at


class TestEnvelopeSerde:
    """AK2: Pydantic-konforme Serialisierung."""

    def test_model_dump_roundtrip(self) -> None:
        start = _now()
        env = ArtifactEnvelope(
            schema_version="3.0",
            story_id="AG3-022",
            run_id="r1",
            stage="impl",
            attempt=1,
            producer=_make_producer(),
            started_at=start,
            finished_at=start,
            status=EnvelopeStatus.PASS,
            artifact_class=ArtifactClass.QA,
            payload={"result": "ok"},
        )
        data = env.model_dump()
        assert data["schema_version"] == "3.0"
        assert data["story_id"] == "AG3-022"
        assert data["artifact_class"] == "qa"
        assert data["status"] == "PASS"
