"""Tests for template selection logic.

``spawn_reason`` ist seit AG3-021 ein typisiertes ``SpawnReason``-Enum.
"""

from __future__ import annotations

import pytest

from agentkit.core_types import SpawnReason
from agentkit.prompt_runtime.selectors import select_template_name
from agentkit.story_context_manager.types import StoryMode, StoryType


class TestSelectTemplateName:
    """Tests for select_template_name()."""

    def test_implementation_type(self) -> None:
        """IMPLEMENTATION story type maps to worker-implementation."""
        result = select_template_name(StoryType.IMPLEMENTATION)
        assert result == "worker-implementation"

    def test_bugfix_type(self) -> None:
        """BUGFIX story type maps to worker-bugfix."""
        result = select_template_name(StoryType.BUGFIX)
        assert result == "worker-bugfix"

    def test_concept_type(self) -> None:
        """CONCEPT story type maps to worker-concept."""
        result = select_template_name(StoryType.CONCEPT)
        assert result == "worker-concept"

    def test_research_type(self) -> None:
        """RESEARCH story type maps to worker-research."""
        result = select_template_name(StoryType.RESEARCH)
        assert result == "worker-research"

    def test_exploration_mode_overrides_story_type(self) -> None:
        """EXPLORATION mode selects worker-exploration."""
        result = select_template_name(
            StoryType.IMPLEMENTATION,
            execution_route=StoryMode.EXPLORATION,
        )
        assert result == "worker-exploration"

    def test_remediation_overrides_everything(self) -> None:
        """spawn_reason=REMEDIATION always selects remediation."""
        result = select_template_name(
            StoryType.IMPLEMENTATION,
            spawn_reason=SpawnReason.REMEDIATION,
        )
        assert result == "worker-remediation"

    def test_remediation_overrides_exploration(self) -> None:
        """Remediation has priority over exploration mode."""
        result = select_template_name(
            StoryType.IMPLEMENTATION,
            execution_route=StoryMode.EXPLORATION,
            spawn_reason=SpawnReason.REMEDIATION,
        )
        assert result == "worker-remediation"

    def test_execution_mode_uses_type_mapping(self) -> None:
        """EXECUTION mode falls through to type mapping."""
        result = select_template_name(
            StoryType.BUGFIX,
            execution_route=StoryMode.EXECUTION,
        )
        assert result == "worker-bugfix"

    def test_none_mode_uses_type_mapping(self) -> None:
        """None mode falls through to the standard type mapping."""
        result = select_template_name(
            StoryType.CONCEPT,
            execution_route=None,
        )
        assert result == "worker-concept"

    def test_legacy_mode_alias_still_works(self) -> None:
        """The historic mode parameter remains a compatibility alias."""
        result = select_template_name(
            StoryType.IMPLEMENTATION,
            execution_route=StoryMode.EXPLORATION,
        )
        assert result == "worker-exploration"

    def test_paused_retry_spawn_reason_uses_type_mapping(self) -> None:
        """PAUSED_RETRY non-remediation spawn_reason uses the type mapping."""
        result = select_template_name(
            StoryType.RESEARCH,
            spawn_reason=SpawnReason.PAUSED_RETRY,
        )
        assert result == "worker-research"

    def test_remediation_enum_routes_to_remediation_template(self) -> None:
        """SpawnReason.REMEDIATION (Enum) routet auf worker-remediation."""
        result = select_template_name(
            StoryType.IMPLEMENTATION,
            spawn_reason=SpawnReason.REMEDIATION,
        )
        assert result == "worker-remediation"

    @pytest.mark.parametrize(
        "bad_value",
        ["remediation", "paused_retry", "initial", "", "REMEDIATION", 0, None],
    )
    def test_non_enum_spawn_reason_raises_type_error(self, bad_value: object) -> None:
        """SpawnReason ist seit AG3-021 typisiert; Laufzeitstrings sind tabu.

        Fail-closed-Guard im Selector lehnt freie Strings ab, damit
        ``spawn_reason="remediation"`` nicht still auf ``worker-implementation``
        routet (AG3-021 §AC11).
        """
        with pytest.raises(TypeError, match="SpawnReason"):
            select_template_name(
                StoryType.IMPLEMENTATION,
                spawn_reason=bad_value,  # type: ignore[arg-type]
            )

    def test_all_story_types_have_template(self) -> None:
        """Every StoryType member must produce a valid template name."""
        for st in StoryType:
            name = select_template_name(st)
            assert isinstance(name, str)
            assert len(name) > 0
