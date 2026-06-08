"""Unit tests for OverrideType."""

from __future__ import annotations

import pytest

from agentkit.core_types import OverrideType


def test_override_type_value_range() -> None:
    assert [member.value for member in OverrideType] == [
        "skip_node",
        "force_gate_pass",
        "force_gate_fail",
        "jump_to",
        "truncate_flow",
        "freeze_retries",
    ]


def test_override_type_wire_values_construct_members() -> None:
    for member in OverrideType:
        assert OverrideType(member.value) is member
        assert isinstance(member, str)


def test_unknown_override_type_rejected() -> None:
    for raw in ("resume", "SKIP_NODE", "force_pass", ""):
        with pytest.raises(ValueError):
            OverrideType(raw)
