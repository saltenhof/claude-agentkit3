"""Unit-Tests fuer ClosureVerdict und MergePolicy (AG3-021 §2.1.9.1)."""

from __future__ import annotations

import pytest

from agentkit.backend.core_types import ClosureVerdict, MergePolicy


class TestClosureVerdict:
    def test_each_value_constructable(self) -> None:
        assert ClosureVerdict("COMPLETED") is ClosureVerdict.COMPLETED
        assert ClosureVerdict("ESCALATED") is ClosureVerdict.ESCALATED

    def test_iteration_is_deterministic(self) -> None:
        assert list(ClosureVerdict) == [
            ClosureVerdict.COMPLETED,
            ClosureVerdict.ESCALATED,
        ]

    def test_str_enum_invariants(self) -> None:
        assert ClosureVerdict.COMPLETED.value == "COMPLETED"
        assert isinstance(ClosureVerdict.COMPLETED, str)

    def test_unknown_value_rejected(self) -> None:
        for raw in ("completed", "FAILED", "PASS", ""):
            with pytest.raises(ValueError):
                ClosureVerdict(raw)


class TestMergePolicy:
    def test_each_value_constructable(self) -> None:
        assert MergePolicy("ff_only") is MergePolicy.FF_ONLY
        assert MergePolicy("no_ff") is MergePolicy.NO_FF

    def test_iteration_is_deterministic(self) -> None:
        assert list(MergePolicy) == [MergePolicy.FF_ONLY, MergePolicy.NO_FF]

    def test_str_enum_invariants(self) -> None:
        assert MergePolicy.FF_ONLY.value == "ff_only"
        assert isinstance(MergePolicy.FF_ONLY, str)

    def test_unknown_value_rejected(self) -> None:
        """Squash/rebase sind nicht erlaubt (FK-29 §29.1.5)."""
        for raw in ("squash", "rebase", "force_push", "FF_ONLY"):
            with pytest.raises(ValueError):
                MergePolicy(raw)
