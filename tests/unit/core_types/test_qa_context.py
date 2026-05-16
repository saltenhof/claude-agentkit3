"""Unit-Tests fuer QaContext (AG3-021 §2.1.9.1)."""

from __future__ import annotations

import pytest

from agentkit.core_types import QaContext


def test_each_value_constructable() -> None:
    assert QaContext("IMPLEMENTATION_INITIAL") is QaContext.IMPLEMENTATION_INITIAL
    assert (
        QaContext("IMPLEMENTATION_REMEDIATION")
        is QaContext.IMPLEMENTATION_REMEDIATION
    )
    assert QaContext("EXPLORATION_INITIAL") is QaContext.EXPLORATION_INITIAL
    assert (
        QaContext("EXPLORATION_REMEDIATION")
        is QaContext.EXPLORATION_REMEDIATION
    )


def test_iteration_is_deterministic() -> None:
    assert list(QaContext) == [
        QaContext.IMPLEMENTATION_INITIAL,
        QaContext.IMPLEMENTATION_REMEDIATION,
        QaContext.EXPLORATION_INITIAL,
        QaContext.EXPLORATION_REMEDIATION,
    ]


def test_str_enum_invariants() -> None:
    assert QaContext.IMPLEMENTATION_INITIAL.value == "IMPLEMENTATION_INITIAL"
    assert isinstance(QaContext.IMPLEMENTATION_INITIAL, str)


def test_legacy_values_rejected() -> None:
    """v2-VerifyContext-Werte sind in QaContext nicht mehr enthalten."""
    for legacy in ("POST_IMPLEMENTATION", "POST_REMEDIATION"):
        with pytest.raises(ValueError):
            QaContext(legacy)
