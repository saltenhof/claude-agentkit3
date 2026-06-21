"""Unit-Tests fuer Severity (AG3-021 §2.1.9.1)."""

from __future__ import annotations

import pytest

from agentkit.backend.core_types import Severity


def test_each_value_constructable() -> None:
    assert Severity("BLOCKING") is Severity.BLOCKING
    assert Severity("MAJOR") is Severity.MAJOR
    assert Severity("MINOR") is Severity.MINOR


def test_iteration_is_deterministic() -> None:
    """Iteration liefert die Werte in der dokumentierten Reihenfolge."""
    assert list(Severity) == [
        Severity.BLOCKING,
        Severity.MAJOR,
        Severity.MINOR,
    ]


def test_str_enum_invariants() -> None:
    assert Severity.BLOCKING.value == "BLOCKING"
    assert isinstance(Severity.BLOCKING, str)
    assert Severity.BLOCKING == "BLOCKING"


def test_unknown_value_raises_value_error() -> None:
    """Alte v2-Werte sind ungueltig (fail-closed)."""
    for legacy in ("CRITICAL", "HIGH", "MEDIUM", "LOW", "INFO"):
        with pytest.raises(ValueError):
            Severity(legacy)


def test_lower_case_value_raises() -> None:
    """Severity-Wire-Werte sind upper-case; lower-case ist ungueltig."""
    for raw in ("blocking", "major", "minor"):
        with pytest.raises(ValueError):
            Severity(raw)
