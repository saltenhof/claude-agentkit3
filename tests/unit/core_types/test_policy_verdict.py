"""Unit-Tests fuer PolicyVerdict (AG3-021 §2.1.9.1)."""

from __future__ import annotations

import pytest

from agentkit.backend.core_types import PolicyVerdict


def test_each_value_constructable() -> None:
    assert PolicyVerdict("PASS") is PolicyVerdict.PASS
    assert PolicyVerdict("FAIL") is PolicyVerdict.FAIL


def test_iteration_is_deterministic() -> None:
    assert list(PolicyVerdict) == [PolicyVerdict.PASS, PolicyVerdict.FAIL]


def test_str_enum_invariants() -> None:
    assert PolicyVerdict.PASS.value == "PASS"
    assert isinstance(PolicyVerdict.PASS, str)


def test_pass_with_warnings_rejected() -> None:
    """PASS_WITH_WARNINGS war alter v2-Wert; in PolicyVerdict ENTFERNT."""
    with pytest.raises(ValueError):
        PolicyVerdict("PASS_WITH_WARNINGS")


def test_pass_with_concerns_rejected() -> None:
    """PASS_WITH_CONCERNS gehoert zu LLM-Check-Status (AG3-022), nicht
    zu PolicyVerdict."""
    with pytest.raises(ValueError):
        PolicyVerdict("PASS_WITH_CONCERNS")
