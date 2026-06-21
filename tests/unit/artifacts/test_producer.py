"""Unit-Tests fuer Producer, ProducerType, ProducerId (AG3-022 §2.1.3)."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from agentkit.backend.artifacts.producer import Producer, ProducerId, ProducerType


class TestProducerType:
    """AK4: ProducerType ist StrEnum mit WORKER, LLM_REVIEWER, DETERMINISTIC."""

    def test_all_three_values_exist(self) -> None:
        assert ProducerType.WORKER == "WORKER"
        assert ProducerType.LLM_REVIEWER == "LLM_REVIEWER"
        assert ProducerType.DETERMINISTIC == "DETERMINISTIC"

    def test_exactly_three_members(self) -> None:
        assert len(ProducerType) == 3

    def test_is_str(self) -> None:
        assert isinstance(ProducerType.WORKER, str)

    def test_invalid_value_rejected(self) -> None:
        with pytest.raises(ValueError):
            ProducerType("UNKNOWN")


class TestProducerId:
    """AK4: ProducerId ist NewType von str."""

    def test_newtype_is_str(self) -> None:
        pid = ProducerId("my-producer-42")
        assert isinstance(pid, str)
        assert pid == "my-producer-42"


class TestProducer:
    """AK4: Producer-Pflichtfelder und optionale version."""

    def _make_producer(
        self,
        *,
        producer_type: ProducerType = ProducerType.DETERMINISTIC,
        name: str = "test-producer",
        pid: str = "inst-001",
        version: str | None = None,
    ) -> Producer:
        return Producer(
            type=producer_type,
            name=name,
            id=ProducerId(pid),
            version=version,
        )

    def test_minimal_producer(self) -> None:
        p = self._make_producer()
        assert p.type == ProducerType.DETERMINISTIC
        assert p.name == "test-producer"
        assert p.id == "inst-001"
        assert p.version is None

    def test_with_version(self) -> None:
        p = self._make_producer(version="1.2.3")
        assert p.version == "1.2.3"

    def test_all_producer_types(self) -> None:
        for pt in ProducerType:
            p = self._make_producer(producer_type=pt)
            assert p.type == pt

    def test_frozen(self) -> None:
        p = self._make_producer()
        with pytest.raises(ValidationError):
            p.name = "other"  # type: ignore[misc]

    def test_extra_fields_forbidden(self) -> None:
        with pytest.raises(ValidationError):
            Producer.model_validate(
                {
                    "type": ProducerType.WORKER,
                    "name": "x",
                    "id": ProducerId("y"),
                    "unknown_field": "z",
                }
            )

    def test_missing_name_rejected(self) -> None:
        with pytest.raises(ValidationError):
            Producer.model_validate(
                {
                    "type": ProducerType.WORKER,
                    "id": ProducerId("y"),
                }
            )
