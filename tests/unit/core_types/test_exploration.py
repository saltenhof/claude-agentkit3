"""Unit-Tests fuer ExplorationGateStatus (AG3-021 §2.1.9.1)."""

from __future__ import annotations

import pytest

from agentkit.core_types import ExplorationGateStatus


def test_each_value_constructable() -> None:
    assert ExplorationGateStatus("pending") is ExplorationGateStatus.PENDING
    assert (
        ExplorationGateStatus("approved")
        is ExplorationGateStatus.APPROVED
    )
    assert (
        ExplorationGateStatus("rejected")
        is ExplorationGateStatus.REJECTED
    )


def test_iteration_is_deterministic() -> None:
    assert list(ExplorationGateStatus) == [
        ExplorationGateStatus.PENDING,
        ExplorationGateStatus.APPROVED,
        ExplorationGateStatus.REJECTED,
    ]


def test_str_enum_invariants() -> None:
    """Wire-Werte sind lowercase (FK-23 §23.5.0)."""
    assert ExplorationGateStatus.PENDING.value == "pending"
    assert isinstance(ExplorationGateStatus.PENDING, str)


def test_upper_case_rejected() -> None:
    """Konzept fixiert lowercase; UPPER_CASE ist kein gueltiger Wert."""
    for raw in ("PENDING", "APPROVED", "REJECTED"):
        with pytest.raises(ValueError):
            ExplorationGateStatus(raw)


def test_legacy_v2_values_rejected() -> None:
    """Alte v2-String-Literale entfallen (vgl. FK-23 §23.5.0 Codex-Note)."""
    for legacy in (
        "doc_compliance_passed",
        "design_review_passed",
        "design_review_failed",
        "approved_for_implementation",
    ):
        with pytest.raises(ValueError):
            ExplorationGateStatus(legacy)
