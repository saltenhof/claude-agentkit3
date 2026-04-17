"""Recovery and rehydration contracts for workflow state.

Defines how workflow state fields are recovered after a crash or
restart. Each field has a priority list of sources and a required
flag. If a required field cannot be recovered from any source,
it is a hard error -- no silent fallbacks to guessed values.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any


class FieldSource(StrEnum):
    """Source from which a field value can be recovered during rehydration.

    Attributes:
        EXPLICIT_PARAM: Value passed as an explicit function parameter.
        CONTEXT_JSON: Value read from the persisted context.json.
        LAST_SNAPSHOT: Value read from the last phase snapshot.
        DEFAULT: A hardcoded default value.
    """

    EXPLICIT_PARAM = "explicit_param"
    CONTEXT_JSON = "context_json"
    LAST_SNAPSHOT = "last_snapshot"
    DEFAULT = "default"


@dataclass(frozen=True)
class RehydrationRule:
    """Rule for recovering a single field during state rehydration.

    The ``source_priority`` tuple defines the order in which sources
    are tried. If ``required`` is ``True`` and no source yields a value,
    rehydration MUST fail with a hard error.

    Args:
        field_name: Name of the field to recover (e.g. "mode", "story_type").
        source_priority: Ordered tuple of sources to try.
        default_value: Default value to use if ``FieldSource.DEFAULT`` is
            in the priority list and all higher-priority sources fail.
        required: If ``True``, failure to recover is a hard error.
    """

    field_name: str
    source_priority: tuple[FieldSource, ...]
    default_value: Any = None
    required: bool = True


@dataclass(frozen=True)
class RecoveryContract:
    """Contract defining rehydration rules for all recoverable fields.

    Args:
        rules: Tuple of rehydration rules, one per recoverable field.
    """

    rules: tuple[RehydrationRule, ...]

    def get_rule(self, field_name: str) -> RehydrationRule | None:
        """Look up a rehydration rule by field name.

        Args:
            field_name: The field name to search for.

        Returns:
            The matching ``RehydrationRule``, or ``None`` if not found.
        """
        for rule in self.rules:
            if rule.field_name == field_name:
                return rule
        return None

    @property
    def required_fields(self) -> tuple[str, ...]:
        """Return names of all required fields.

        Returns:
            Tuple of field names that are marked as required.
        """
        return tuple(r.field_name for r in self.rules if r.required)


DEFAULT_RECOVERY_CONTRACT: RecoveryContract = RecoveryContract(
    rules=(
        RehydrationRule(
            field_name="mode",
            source_priority=(
                FieldSource.EXPLICIT_PARAM,
                FieldSource.CONTEXT_JSON,
            ),
            required=True,
        ),
        RehydrationRule(
            field_name="story_type",
            source_priority=(
                FieldSource.EXPLICIT_PARAM,
                FieldSource.CONTEXT_JSON,
            ),
            required=True,
        ),
        RehydrationRule(
            field_name="phase",
            source_priority=(
                FieldSource.EXPLICIT_PARAM,
                FieldSource.CONTEXT_JSON,
                FieldSource.LAST_SNAPSHOT,
            ),
            required=True,
        ),
        RehydrationRule(
            field_name="status",
            source_priority=(
                FieldSource.EXPLICIT_PARAM,
                FieldSource.CONTEXT_JSON,
                FieldSource.LAST_SNAPSHOT,
                FieldSource.DEFAULT,
            ),
            default_value="pending",
            required=False,
        ),
    ),
)
"""Default recovery contract with rules for core pipeline fields.

- ``mode``: Required, no default -- must come from explicit param or context.json.
- ``story_type``: Required, no default -- must come from explicit param or context.json.
- ``phase``: Required, can fall back to last snapshot.
- ``status``: Not required, defaults to "pending" if all sources fail.
"""
