"""Unit-Tests fuer StorySize und StoryMode (AG3-021 §2.1.9.1)."""

from __future__ import annotations

import pytest

from agentkit.backend.core_types import StoryMode, StorySize


class TestStorySize:
    def test_each_value_constructable(self) -> None:
        for raw in ("XS", "S", "M", "L", "XL"):
            assert StorySize(raw).value == raw

    def test_iteration_is_deterministic(self) -> None:
        assert list(StorySize) == [
            StorySize.XS,
            StorySize.S,
            StorySize.M,
            StorySize.L,
            StorySize.XL,
        ]

    def test_str_enum_invariants(self) -> None:
        assert StorySize.XS.value == "XS"
        assert isinstance(StorySize.XS, str)

    def test_five_values(self) -> None:
        assert len(StorySize) == 5

    def test_xxl_rejected(self) -> None:
        """XXL ist kein Konzept-Wert (DK-10 §10.4)."""
        with pytest.raises(ValueError):
            StorySize("XXL")

    def test_legacy_lower_case_rejected(self) -> None:
        """Alte v2-Werte small/medium/large/epic entfallen."""
        for legacy in ("small", "medium", "large", "epic"):
            with pytest.raises(ValueError):
                StorySize(legacy)


class TestStoryMode:
    def test_each_value_constructable(self) -> None:
        assert StoryMode("execution") is StoryMode.EXECUTION
        assert StoryMode("exploration") is StoryMode.EXPLORATION

    def test_fast_is_not_an_execution_route_value(self) -> None:
        """FK-24 §24.3.2/§24.3.3: ``fast`` is a SEPARATE axis (WireStoryMode),
        never an ``execution_route``/``StoryMode`` value."""
        import pytest

        with pytest.raises(ValueError, match="fast"):
            StoryMode("fast")

    def test_iteration_is_deterministic(self) -> None:
        assert list(StoryMode) == [
            StoryMode.EXECUTION,
            StoryMode.EXPLORATION,
        ]

    def test_str_enum_invariants(self) -> None:
        assert StoryMode.EXECUTION.value == "execution"
        assert isinstance(StoryMode.EXECUTION, str)

    def test_two_values(self) -> None:
        """FK-24 §24.3.2: ``execution_route`` carries execution/exploration only;
        the fast/standard axis is SEPARATE (WireStoryMode)."""
        assert len(StoryMode) == 2

    def test_not_applicable_rejected(self) -> None:
        """NOT_APPLICABLE faellt mit AG3-021 weg; execution_route bleibt
        bei nicht-implementierenden Storys None."""
        with pytest.raises(ValueError):
            StoryMode("not_applicable")
        with pytest.raises(ValueError):
            StoryMode("NOT_APPLICABLE")

    def test_upper_case_rejected(self) -> None:
        """StoryMode-Wire-Werte sind lowercase (FK-24 §24.3.2)."""
        for raw in ("EXECUTION", "EXPLORATION", "FAST"):
            with pytest.raises(ValueError):
                StoryMode(raw)
