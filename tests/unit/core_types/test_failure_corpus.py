"""Unit-Tests fuer FailureCategory und PromotionStatus (AG3-021 §2.1.9.1)."""

from __future__ import annotations

import pytest

from agentkit.core_types import FailureCategory, PromotionStatus


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


class TestPromotionStatus:
    _EXPECTED_VALUES = (
        "monitoring",
        "draft",
        "approved",
        "active",
        "tuned",
        "retired",
        "rejected",
    )

    def test_each_value_constructable(self) -> None:
        for raw in self._EXPECTED_VALUES:
            assert PromotionStatus(raw).value == raw

    def test_iteration_is_deterministic(self) -> None:
        assert [member.value for member in PromotionStatus] == list(self._EXPECTED_VALUES)

    def test_str_enum_invariants(self) -> None:
        assert PromotionStatus.MONITORING.value == "monitoring"
        assert isinstance(PromotionStatus.MONITORING, str)

    def test_seven_values(self) -> None:
        assert len(PromotionStatus) == 7

    def test_legacy_v2_values_rejected(self) -> None:
        """Werteliste OBSERVED/PROPOSED/CONFIRMED/IMPLEMENTED entfaellt."""
        for legacy in ("observed", "proposed", "confirmed", "implemented"):
            with pytest.raises(ValueError):
                PromotionStatus(legacy)
