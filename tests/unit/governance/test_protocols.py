"""Tests for governance protocols: GuardVerdict, ViolationType."""

from __future__ import annotations

import pytest

from agentkit.governance.protocols import GuardVerdict, ViolationType


class TestViolationType:
    """ViolationType enum coverage."""

    def test_all_values_exist(self) -> None:
        expected = {
            "branch_violation",
            "scope_violation",
            "artifact_tampering",
            "unauthorized_operation",
            "integrity_failure",
            "policy_violation",
        }
        assert {v.value for v in ViolationType} == expected

    def test_is_str_enum(self) -> None:
        assert isinstance(ViolationType.BRANCH_VIOLATION, str)
        assert ViolationType.BRANCH_VIOLATION == "branch_violation"


class TestGuardVerdict:
    """GuardVerdict construction and immutability."""

    def test_allow_verdict(self) -> None:
        v = GuardVerdict.ALLOW("test_guard")
        assert v.allowed is True
        assert v.guard_name == "test_guard"
        assert v.violation_type is None
        assert v.message is None
        assert v.detail is None

    def test_block_verdict(self) -> None:
        v = GuardVerdict.BLOCK(
            "test_guard",
            ViolationType.BRANCH_VIOLATION,
            "You shall not pass",
            detail={"key": "value"},
        )
        assert v.allowed is False
        assert v.guard_name == "test_guard"
        assert v.violation_type == ViolationType.BRANCH_VIOLATION
        assert v.message == "You shall not pass"
        assert v.detail == {"key": "value"}

    def test_block_verdict_without_detail(self) -> None:
        v = GuardVerdict.BLOCK(
            "g", ViolationType.SCOPE_VIOLATION, "blocked",
        )
        assert v.detail is None

    def test_frozen_enforcement(self) -> None:
        v = GuardVerdict.ALLOW("g")
        with pytest.raises(AttributeError):
            v.allowed = False  # type: ignore[misc]

    def test_frozen_guard_name(self) -> None:
        v = GuardVerdict.ALLOW("g")
        with pytest.raises(AttributeError):
            v.guard_name = "other"  # type: ignore[misc]
