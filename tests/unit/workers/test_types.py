"""Unit tests for agentkit.workers.types."""

from __future__ import annotations

from agentkit.workers.types import SpawnReason


class TestSpawnReason:
    """Tests for the SpawnReason enum."""

    def test_all_values(self) -> None:
        assert set(SpawnReason) == {
            SpawnReason.INITIAL,
            SpawnReason.PAUSED_RETRY,
            SpawnReason.REMEDIATION,
        }

    def test_string_values(self) -> None:
        assert SpawnReason.INITIAL == "initial"
        assert SpawnReason.PAUSED_RETRY == "paused_retry"
        assert SpawnReason.REMEDIATION == "remediation"

    def test_is_str_subclass(self) -> None:
        assert isinstance(SpawnReason.INITIAL, str)

    def test_constructable_from_string(self) -> None:
        assert SpawnReason("initial") is SpawnReason.INITIAL
        assert SpawnReason("paused_retry") is SpawnReason.PAUSED_RETRY
        assert SpawnReason("remediation") is SpawnReason.REMEDIATION
