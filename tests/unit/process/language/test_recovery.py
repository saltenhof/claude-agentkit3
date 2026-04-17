"""Unit tests for recovery and rehydration contracts."""

from __future__ import annotations

import dataclasses

import pytest

from agentkit.process.language.recovery import (
    DEFAULT_RECOVERY_CONTRACT,
    FieldSource,
    RecoveryContract,
    RehydrationRule,
)


class TestFieldSource:
    """Tests for FieldSource enum."""

    def test_values(self) -> None:
        assert FieldSource.EXPLICIT_PARAM == "explicit_param"
        assert FieldSource.CONTEXT_JSON == "context_json"
        assert FieldSource.LAST_SNAPSHOT == "last_snapshot"
        assert FieldSource.DEFAULT == "default"

    def test_is_str(self) -> None:
        assert isinstance(FieldSource.EXPLICIT_PARAM, str)


class TestRehydrationRule:
    """Tests for RehydrationRule frozen dataclass."""

    def test_minimal_construction(self) -> None:
        rule = RehydrationRule(
            field_name="mode",
            source_priority=(FieldSource.EXPLICIT_PARAM,),
        )
        assert rule.field_name == "mode"
        assert rule.source_priority == (FieldSource.EXPLICIT_PARAM,)
        assert rule.default_value is None
        assert rule.required is True

    def test_full_construction(self) -> None:
        rule = RehydrationRule(
            field_name="status",
            source_priority=(
                FieldSource.EXPLICIT_PARAM,
                FieldSource.CONTEXT_JSON,
                FieldSource.DEFAULT,
            ),
            default_value="pending",
            required=False,
        )
        assert rule.field_name == "status"
        assert len(rule.source_priority) == 3
        assert rule.default_value == "pending"
        assert rule.required is False

    def test_frozen(self) -> None:
        rule = RehydrationRule(
            field_name="mode",
            source_priority=(FieldSource.EXPLICIT_PARAM,),
        )
        with pytest.raises(dataclasses.FrozenInstanceError):
            rule.field_name = "other"  # type: ignore[misc]

    def test_required_defaults_to_true(self) -> None:
        rule = RehydrationRule(
            field_name="x",
            source_priority=(FieldSource.EXPLICIT_PARAM,),
        )
        assert rule.required is True


class TestRecoveryContract:
    """Tests for RecoveryContract frozen dataclass."""

    def test_construction(self) -> None:
        rule1 = RehydrationRule(
            field_name="a",
            source_priority=(FieldSource.EXPLICIT_PARAM,),
        )
        rule2 = RehydrationRule(
            field_name="b",
            source_priority=(FieldSource.CONTEXT_JSON,),
            required=False,
        )
        contract = RecoveryContract(rules=(rule1, rule2))
        assert len(contract.rules) == 2

    def test_get_rule_found(self) -> None:
        rule = RehydrationRule(
            field_name="mode",
            source_priority=(FieldSource.EXPLICIT_PARAM,),
        )
        contract = RecoveryContract(rules=(rule,))
        found = contract.get_rule("mode")
        assert found is not None
        assert found.field_name == "mode"

    def test_get_rule_not_found(self) -> None:
        contract = RecoveryContract(rules=())
        assert contract.get_rule("nonexistent") is None

    def test_required_fields(self) -> None:
        rule_req = RehydrationRule(
            field_name="mode",
            source_priority=(FieldSource.EXPLICIT_PARAM,),
            required=True,
        )
        rule_opt = RehydrationRule(
            field_name="status",
            source_priority=(FieldSource.DEFAULT,),
            required=False,
        )
        contract = RecoveryContract(rules=(rule_req, rule_opt))
        assert contract.required_fields == ("mode",)

    def test_frozen(self) -> None:
        contract = RecoveryContract(rules=())
        with pytest.raises(dataclasses.FrozenInstanceError):
            contract.rules = ()  # type: ignore[misc]


class TestDefaultRecoveryContract:
    """Tests for the DEFAULT_RECOVERY_CONTRACT."""

    def test_mode_rule(self) -> None:
        rule = DEFAULT_RECOVERY_CONTRACT.get_rule("mode")
        assert rule is not None
        assert rule.required is True
        assert rule.default_value is None
        assert FieldSource.EXPLICIT_PARAM in rule.source_priority
        assert FieldSource.CONTEXT_JSON in rule.source_priority

    def test_story_type_rule(self) -> None:
        rule = DEFAULT_RECOVERY_CONTRACT.get_rule("story_type")
        assert rule is not None
        assert rule.required is True
        assert rule.default_value is None

    def test_phase_rule(self) -> None:
        rule = DEFAULT_RECOVERY_CONTRACT.get_rule("phase")
        assert rule is not None
        assert rule.required is True
        assert FieldSource.LAST_SNAPSHOT in rule.source_priority

    def test_status_rule(self) -> None:
        rule = DEFAULT_RECOVERY_CONTRACT.get_rule("status")
        assert rule is not None
        assert rule.required is False
        assert rule.default_value == "pending"
        assert FieldSource.DEFAULT in rule.source_priority

    def test_required_fields_are_mode_story_type_phase(self) -> None:
        required = DEFAULT_RECOVERY_CONTRACT.required_fields
        assert "mode" in required
        assert "story_type" in required
        assert "phase" in required
        assert "status" not in required

    def test_mode_has_no_default(self) -> None:
        """Mode without a source is a hard error -- no silent fallback."""
        rule = DEFAULT_RECOVERY_CONTRACT.get_rule("mode")
        assert rule is not None
        assert rule.required is True
        assert rule.default_value is None
        assert FieldSource.DEFAULT not in rule.source_priority

    def test_story_type_has_no_default(self) -> None:
        """Story type without a source is a hard error -- no silent fallback."""
        rule = DEFAULT_RECOVERY_CONTRACT.get_rule("story_type")
        assert rule is not None
        assert rule.required is True
        assert rule.default_value is None
        assert FieldSource.DEFAULT not in rule.source_priority
