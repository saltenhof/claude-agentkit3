"""Unit-Tests fuer FailureCategory und IncidentStatus (AG3-021 §2.1.9.1, AG3-028 KONFLIKT-1)."""

from __future__ import annotations

import pytest

from agentkit.backend.core_types import FailureCategory, IncidentStatus


class TestFailureCategory:
    _EXPECTED_VALUES = (
        "scope_drift",
        "architecture_violation",
        "evidence_fabrication",
        "hallucination",
        "test_omission",
        "assertion_weakness",
        "unsafe_refactor",
        "policy_violation",
        "tool_misuse",
        "state_desync",
        "requirements_miss",
        "review_evasion",
    )

    def test_each_value_constructable(self) -> None:
        for raw in self._EXPECTED_VALUES:
            assert FailureCategory(raw).value == raw

    def test_iteration_is_deterministic(self) -> None:
        assert [member.value for member in FailureCategory] == list(self._EXPECTED_VALUES)

    def test_str_enum_invariants(self) -> None:
        assert FailureCategory.SCOPE_DRIFT.value == "scope_drift"
        assert isinstance(FailureCategory.SCOPE_DRIFT, str)

    def test_twelve_values(self) -> None:
        assert len(FailureCategory) == 12

    def test_legacy_values_rejected(self) -> None:
        """Frueher zirkulierende v2-Werte entfallen mit AG3-021."""
        for legacy in (
            "instruction_neglect",
            "bar_raising_failure",
            "test_framework_gap",
            "import_structure_drift",
            "concept_violation",
            "doc_fidelity_drift",
            "are_gate_fail",
            "guard_breach",
            "worker_runaway",
            "environmental_failure",
            "other",
        ):
            with pytest.raises(ValueError):
                FailureCategory(legacy)


class TestIncidentStatus:
    """AG3-028 KONFLIKT-1: IncidentStatus ersetzt PromotionStatus (4 Werte)."""

    _EXPECTED_VALUES = (
        "observed",
        "promoted",
        "closed_one_off",
        "archived",
    )

    def test_each_value_constructable(self) -> None:
        for raw in self._EXPECTED_VALUES:
            assert IncidentStatus(raw).value == raw

    def test_iteration_is_deterministic(self) -> None:
        assert [member.value for member in IncidentStatus] == list(self._EXPECTED_VALUES)

    def test_str_enum_invariants(self) -> None:
        assert IncidentStatus.OBSERVED.value == "observed"
        assert isinstance(IncidentStatus.OBSERVED, str)

    def test_four_values(self) -> None:
        assert len(IncidentStatus) == 4

    def test_legacy_promotion_status_values_rejected(self) -> None:
        """Die alten PromotionStatus-Werte sind kein IncidentStatus mehr."""
        for legacy in ("monitoring", "draft", "approved", "active", "tuned", "retired"):
            with pytest.raises(ValueError):
                IncidentStatus(legacy)
