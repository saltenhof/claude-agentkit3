"""Unit tests for the 3-state applicability resolution (FK-33 §33.6.5).

Covers AC5: APPLICABLE / NOT_APPLICABLE_UNAVAILABLE / NOT_APPLICABLE_FAST
+ the airtight absent != unreachable distinction.
"""

from __future__ import annotations

import pytest

from agentkit.story_context_manager.types import StoryType
from agentkit.verify_system.sonarqube_gate import (
    SonarApplicability,
    resolve_applicability,
)


class TestApplicabilityResolution:
    def test_applicable_when_available_nonfast_codeproducing(self) -> None:
        result = resolve_applicability(
            available=True, fast=False, story_type=StoryType.IMPLEMENTATION
        )
        assert result is SonarApplicability.APPLICABLE

    def test_applicable_for_bugfix(self) -> None:
        result = resolve_applicability(
            available=True, fast=False, story_type=StoryType.BUGFIX
        )
        assert result is SonarApplicability.APPLICABLE

    def test_unavailable_when_available_false(self) -> None:
        """available:false -> NOT_APPLICABLE_UNAVAILABLE (SKIP, not fail-closed)."""
        result = resolve_applicability(
            available=False, fast=False, story_type=StoryType.IMPLEMENTATION
        )
        assert result is SonarApplicability.NOT_APPLICABLE_UNAVAILABLE

    def test_fast_mode_drops_gate_even_if_available(self) -> None:
        """fast=True -> NOT_APPLICABLE_FAST regardless of availability.

        ``fast`` is the SEPARATE fast/standard axis (FK-24 §24.3.3), not an
        ``execution_route`` value.
        """
        result = resolve_applicability(
            available=True, fast=True, story_type=StoryType.IMPLEMENTATION
        )
        assert result is SonarApplicability.NOT_APPLICABLE_FAST

    @pytest.mark.parametrize("story_type", [StoryType.CONCEPT, StoryType.RESEARCH])
    def test_non_codeproducing_is_not_applicable(self, story_type: StoryType) -> None:
        result = resolve_applicability(
            available=True, fast=False, story_type=story_type
        )
        assert result is SonarApplicability.NOT_APPLICABLE_UNAVAILABLE

    def test_absent_is_not_the_same_as_unreachable(self) -> None:
        """Airtight: available:false is a deliberate SKIP; an available:true
        server that is later unreachable stays APPLICABLE (fail-closed is the
        gate's job, not applicability's)."""
        absent = resolve_applicability(
            available=False, fast=False, story_type=StoryType.IMPLEMENTATION
        )
        configured = resolve_applicability(
            available=True, fast=False, story_type=StoryType.IMPLEMENTATION
        )
        assert absent is SonarApplicability.NOT_APPLICABLE_UNAVAILABLE
        assert configured is SonarApplicability.APPLICABLE
