"""Unit-Tests fuer AttemptOutcome und FailureCause (AG3-021 §2.1.9.1)."""

from __future__ import annotations

import pytest

from agentkit.backend.core_types import AttemptOutcome, FailureCause


class TestAttemptOutcome:
    def test_each_value_constructable(self) -> None:
        for name in ("COMPLETED", "FAILED", "ESCALATED", "SKIPPED", "YIELDED", "BLOCKED"):
            assert AttemptOutcome(name).name == name

    def test_iteration_is_deterministic(self) -> None:
        assert list(AttemptOutcome) == [
            AttemptOutcome.COMPLETED,
            AttemptOutcome.FAILED,
            AttemptOutcome.ESCALATED,
            AttemptOutcome.SKIPPED,
            AttemptOutcome.YIELDED,
            AttemptOutcome.BLOCKED,
        ]

    def test_str_enum_invariants(self) -> None:
        assert AttemptOutcome.COMPLETED.value == "COMPLETED"
        assert isinstance(AttemptOutcome.COMPLETED, str)

    def test_unknown_value_rejected(self) -> None:
        for raw in ("completed", "DONE", "passed", ""):
            with pytest.raises(ValueError):
                AttemptOutcome(raw)


class TestFailureCause:
    _EXPECTED_NAMES = (
        "GUARD_REJECTED",
        "STRUCTURAL_CHECK_FAIL",
        "SEMANTIC_REVIEW_FAIL",
        "ADVERSARIAL_FINDING",
        "POLICY_FAIL",
        "WORKER_BLOCKED",
        "INTEGRITY_FAIL",
        "MERGE_FAIL",
        "PREFLIGHT_FAIL",
        "MAX_ROUNDS_EXCEEDED",
        "TIMEOUT",
        "GUARD_FAILED",
        "HANDLER_EXCEPTION",
        "PRECONDITION_FAILED",
        "HANDLER_REPORTED_FAILED",
        "HANDLER_REPORTED_ESCALATED",
    )

    def test_each_value_constructable(self) -> None:
        for name in self._EXPECTED_NAMES:
            member = FailureCause(name)
            assert member.value == name

    def test_iteration_is_deterministic(self) -> None:
        assert [member.name for member in FailureCause] == list(self._EXPECTED_NAMES)

    def test_sixteen_values(self) -> None:
        assert len(FailureCause) == 16

    def test_unknown_value_rejected(self) -> None:
        for raw in ("foo", "merge_fail", "OTHER", ""):
            with pytest.raises(ValueError):
                FailureCause(raw)
