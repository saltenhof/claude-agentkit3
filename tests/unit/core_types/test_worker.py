"""Unit-Tests fuer BlockingCategory und SpawnReason (AG3-021 §2.1.9.1)."""

from __future__ import annotations

import pytest

from agentkit.backend.core_types import BlockingCategory, SpawnReason


class TestBlockingCategory:
    def test_each_value_constructable(self) -> None:
        for raw in (
            "POLICY_CONFLICT",
            "ENVIRONMENTAL",
            "FIXABLE_LOCAL",
            "FIXABLE_CODE",
        ):
            assert BlockingCategory(raw).value == raw

    def test_iteration_is_deterministic(self) -> None:
        assert list(BlockingCategory) == [
            BlockingCategory.POLICY_CONFLICT,
            BlockingCategory.ENVIRONMENTAL,
            BlockingCategory.FIXABLE_LOCAL,
            BlockingCategory.FIXABLE_CODE,
        ]

    def test_str_enum_invariants(self) -> None:
        assert BlockingCategory.POLICY_CONFLICT.value == "POLICY_CONFLICT"
        assert isinstance(BlockingCategory.POLICY_CONFLICT, str)

    def test_four_values(self) -> None:
        assert len(BlockingCategory) == 4

    def test_lower_case_rejected(self) -> None:
        """Wire-Werte sind upper-case (FK-26 §26.8.2 Glossar)."""
        for raw in ("policy_conflict", "environmental"):
            with pytest.raises(ValueError):
                BlockingCategory(raw)


class TestSpawnReason:
    def test_each_value_constructable(self) -> None:
        assert SpawnReason("initial") is SpawnReason.INITIAL
        assert SpawnReason("paused_retry") is SpawnReason.PAUSED_RETRY
        assert SpawnReason("remediation") is SpawnReason.REMEDIATION

    def test_iteration_is_deterministic(self) -> None:
        assert list(SpawnReason) == [
            SpawnReason.INITIAL,
            SpawnReason.PAUSED_RETRY,
            SpawnReason.REMEDIATION,
        ]

    def test_str_enum_invariants(self) -> None:
        assert SpawnReason.INITIAL.value == "initial"
        assert isinstance(SpawnReason.INITIAL, str)

    def test_three_values(self) -> None:
        assert len(SpawnReason) == 3

    def test_upper_case_rejected(self) -> None:
        """Wire-Werte sind lowercase (AG3-021 §2.1.1.1)."""
        for raw in ("INITIAL", "PAUSED_RETRY", "REMEDIATION"):
            with pytest.raises(ValueError):
                SpawnReason(raw)

    def test_unknown_value_rejected(self) -> None:
        for raw in ("manual", "retry", "fix"):
            with pytest.raises(ValueError):
                SpawnReason(raw)
