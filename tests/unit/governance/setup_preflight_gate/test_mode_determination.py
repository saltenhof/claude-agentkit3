"""Unit tests for deterministic 4-trigger mode determination (AG3-057).

Tests the full trigger matrix, VektorDB-conflict precedence, fail-closed
behavior for missing/unknown fields, concept-path sandbox guard, and the
non-implementing story-type gate.

All tests are isolated pure-logic tests: no I/O beyond filesystem path
existence checks (which use tmp_path fixtures).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from agentkit.governance.setup_preflight_gate.mode_determination import (
    _has_valid_concept_paths,
    determine_mode,
)
from agentkit.story_context_manager.models import StoryContext
from agentkit.story_context_manager.story_model import ChangeImpact, ConceptQuality
from agentkit.story_context_manager.types import StoryMode, StoryType

if TYPE_CHECKING:
    from pathlib import Path


# ---------------------------------------------------------------------------
# Helper: build a StoryContext with controllable trigger inputs
# ---------------------------------------------------------------------------

def _ctx(
    *,
    story_type: StoryType = StoryType.IMPLEMENTATION,
    vectordb_conflict_resolved: bool = False,
    concept_paths: tuple[str, ...] = ("concept/valid.md",),
    change_impact: ChangeImpact | None = ChangeImpact.LOCAL,
    new_structures: bool = False,
    concept_quality: ConceptQuality | None = ConceptQuality.HIGH,
    project_root: Path | None = None,
) -> StoryContext:
    """Build a ``StoryContext`` with specific trigger-input values for testing.

    All trigger-neutral defaults are set so that individual tests can flip
    exactly one trigger at a time.
    """
    return StoryContext(
        project_key="test-project",
        story_id="AG3-999",
        story_type=story_type,
        execution_route=(
            StoryMode.EXPLORATION
            if story_type in (StoryType.IMPLEMENTATION, StoryType.BUGFIX)
            else None
        ),
        vectordb_conflict_resolved=vectordb_conflict_resolved,
        concept_paths=concept_paths,
        change_impact=change_impact,
        new_structures=new_structures,
        concept_quality=concept_quality,
        project_root=project_root,
    )


# ---------------------------------------------------------------------------
# AK1: determine_mode returns StoryMode | None with correct signature
# ---------------------------------------------------------------------------


class TestDetermineModeSmokeAndType:
    """Smoke: function exists, returns StoryMode | None."""

    def test_returns_exploration_for_implementation_default(
        self, tmp_path: Path
    ) -> None:
        """With no triggers active (all neutral), returns EXECUTION."""
        concept_file = tmp_path / "concept" / "valid.md"
        concept_file.parent.mkdir(parents=True)
        concept_file.write_text("# concept", encoding="utf-8")

        ctx = _ctx(
            project_root=tmp_path,
            concept_paths=(str(concept_file),),
        )
        result = determine_mode(ctx, project_root=tmp_path)
        assert result is StoryMode.EXECUTION

    def test_returns_none_for_concept_type(self) -> None:
        """Concept story → None (FK-24 §24.3.2, no trigger evaluation)."""
        # Concept allowed_modes = (None,) so execution_route must be None
        ctx = StoryContext(
            project_key="test-project",
            story_id="AG3-999",
            story_type=StoryType.CONCEPT,
            execution_route=None,
        )
        result = determine_mode(ctx)
        assert result is None

    def test_returns_none_for_research_type(self) -> None:
        """Research story → None (FK-24 §24.3.2, no trigger evaluation)."""
        ctx = StoryContext(
            project_key="test-project",
            story_id="AG3-999",
            story_type=StoryType.RESEARCH,
            execution_route=None,
        )
        result = determine_mode(ctx)
        assert result is None

    def test_bugfix_type_is_implementing(self, tmp_path: Path) -> None:
        """Bugfix story participates in mode determination (FK-23 §23.1)."""
        concept_file = tmp_path / "concept.md"
        concept_file.write_text("# c", encoding="utf-8")
        ctx = StoryContext(
            project_key="test-project",
            story_id="AG3-999",
            story_type=StoryType.BUGFIX,
            execution_route=StoryMode.EXECUTION,
            concept_paths=(str(concept_file),),
            change_impact=ChangeImpact.LOCAL,
            concept_quality=ConceptQuality.HIGH,
        )
        result = determine_mode(ctx, project_root=tmp_path)
        # No trigger active → Execution
        assert result is StoryMode.EXECUTION


# ---------------------------------------------------------------------------
# AK2: Each trigger fires independently
# ---------------------------------------------------------------------------


class TestTrigger1ConceptPaths:
    """Trigger 1: empty / absent concept_paths → Exploration + WARNING."""

    def test_empty_concept_paths_fires_trigger_1(self, tmp_path: Path) -> None:
        """concept_paths=() → Trigger 1 → Exploration."""
        ctx = _ctx(concept_paths=(), project_root=tmp_path)
        assert determine_mode(ctx, project_root=tmp_path) is StoryMode.EXPLORATION

    def test_whitespace_only_path_fires_trigger_1(self, tmp_path: Path) -> None:
        """concept_paths with only whitespace-strings → Trigger 1 → Exploration."""
        ctx = _ctx(concept_paths=("   ", ""), project_root=tmp_path)
        assert determine_mode(ctx, project_root=tmp_path) is StoryMode.EXPLORATION

    def test_nonexistent_path_fires_trigger_1(self, tmp_path: Path) -> None:
        """Non-existent concept path → Trigger 1 → Exploration."""
        ctx = _ctx(
            concept_paths=(str(tmp_path / "does_not_exist.md"),),
            project_root=tmp_path,
        )
        assert determine_mode(ctx, project_root=tmp_path) is StoryMode.EXPLORATION

    def test_existing_path_in_root_does_not_fire(self, tmp_path: Path) -> None:
        """Valid existing path inside project_root → Trigger 1 does NOT fire."""
        concept_file = tmp_path / "concept.md"
        concept_file.write_text("# valid", encoding="utf-8")
        ctx = _ctx(
            concept_paths=(str(concept_file),),
            project_root=tmp_path,
        )
        assert determine_mode(ctx, project_root=tmp_path) is StoryMode.EXECUTION

    def test_path_outside_project_root_fires_trigger_1(self, tmp_path: Path) -> None:
        """Path outside project_root (sandbox violation) → Trigger 1 → Exploration."""
        outside = tmp_path.parent / "outside.md"
        outside.write_text("# outside", encoding="utf-8")
        sandbox = tmp_path / "sandbox"
        sandbox.mkdir()
        ctx = _ctx(
            concept_paths=(str(outside),),
            project_root=sandbox,
        )
        assert determine_mode(ctx, project_root=sandbox) is StoryMode.EXPLORATION


class TestTrigger2ChangeImpact:
    """Trigger 2: change_impact == ARCHITECTURE_IMPACT → Exploration + INFO."""

    def test_architecture_impact_fires_trigger_2(self, tmp_path: Path) -> None:
        """change_impact=ARCHITECTURE_IMPACT → Trigger 2 → Exploration."""
        concept_file = tmp_path / "c.md"
        concept_file.write_text("# c", encoding="utf-8")
        ctx = _ctx(
            concept_paths=(str(concept_file),),
            change_impact=ChangeImpact.ARCHITECTURE_IMPACT,
            project_root=tmp_path,
        )
        assert determine_mode(ctx, project_root=tmp_path) is StoryMode.EXPLORATION

    @pytest.mark.parametrize(
        "impact",
        [ChangeImpact.LOCAL, ChangeImpact.COMPONENT, ChangeImpact.CROSS_COMPONENT],
    )
    def test_non_architecture_impact_does_not_fire(
        self, tmp_path: Path, impact: ChangeImpact
    ) -> None:
        """Non-ARCHITECTURE_IMPACT change_impact values do not fire Trigger 2."""
        concept_file = tmp_path / "c.md"
        concept_file.write_text("# c", encoding="utf-8")
        ctx = _ctx(
            concept_paths=(str(concept_file),),
            change_impact=impact,
            project_root=tmp_path,
        )
        assert determine_mode(ctx, project_root=tmp_path) is StoryMode.EXECUTION


class TestTrigger3NewStructures:
    """Trigger 3: new_structures=True → Exploration + INFO."""

    def test_new_structures_true_fires_trigger_3(self, tmp_path: Path) -> None:
        """new_structures=True → Trigger 3 → Exploration."""
        concept_file = tmp_path / "c.md"
        concept_file.write_text("# c", encoding="utf-8")
        ctx = _ctx(
            concept_paths=(str(concept_file),),
            new_structures=True,
            project_root=tmp_path,
        )
        assert determine_mode(ctx, project_root=tmp_path) is StoryMode.EXPLORATION

    def test_new_structures_false_does_not_fire(self, tmp_path: Path) -> None:
        """new_structures=False → Trigger 3 does NOT fire."""
        concept_file = tmp_path / "c.md"
        concept_file.write_text("# c", encoding="utf-8")
        ctx = _ctx(
            concept_paths=(str(concept_file),),
            new_structures=False,
            project_root=tmp_path,
        )
        assert determine_mode(ctx, project_root=tmp_path) is StoryMode.EXECUTION


class TestTrigger4ConceptQuality:
    """Trigger 4: concept_quality == LOW → Exploration + INFO."""

    def test_low_concept_quality_fires_trigger_4(self, tmp_path: Path) -> None:
        """concept_quality=LOW → Trigger 4 → Exploration."""
        concept_file = tmp_path / "c.md"
        concept_file.write_text("# c", encoding="utf-8")
        ctx = _ctx(
            concept_paths=(str(concept_file),),
            concept_quality=ConceptQuality.LOW,
            project_root=tmp_path,
        )
        assert determine_mode(ctx, project_root=tmp_path) is StoryMode.EXPLORATION

    @pytest.mark.parametrize(
        "quality",
        [ConceptQuality.HIGH, ConceptQuality.MEDIUM],
    )
    def test_non_low_concept_quality_does_not_fire(
        self, tmp_path: Path, quality: ConceptQuality
    ) -> None:
        """HIGH / MEDIUM concept_quality values do not fire Trigger 4."""
        concept_file = tmp_path / "c.md"
        concept_file.write_text("# c", encoding="utf-8")
        ctx = _ctx(
            concept_paths=(str(concept_file),),
            concept_quality=quality,
            project_root=tmp_path,
        )
        assert determine_mode(ctx, project_root=tmp_path) is StoryMode.EXECUTION


# ---------------------------------------------------------------------------
# AK3: VektorDB-conflict precedence (before trigger evaluation)
# ---------------------------------------------------------------------------


class TestVektorDBConflictPrecedence:
    """VektorDB-conflict forces Exploration BEFORE any trigger check (AK3)."""

    def test_vectordb_conflict_alone_forces_exploration(self, tmp_path: Path) -> None:
        """vectordb_conflict_resolved=True → Exploration (all other triggers neutral)."""
        concept_file = tmp_path / "c.md"
        concept_file.write_text("# c", encoding="utf-8")
        ctx = _ctx(
            vectordb_conflict_resolved=True,
            concept_paths=(str(concept_file),),
            change_impact=ChangeImpact.LOCAL,
            new_structures=False,
            concept_quality=ConceptQuality.HIGH,
            project_root=tmp_path,
        )
        assert determine_mode(ctx, project_root=tmp_path) is StoryMode.EXPLORATION

    def test_vectordb_conflict_precedes_triggers(self, tmp_path: Path) -> None:
        """Even with all triggers neutral, VektorDB-conflict forces Exploration."""
        concept_file = tmp_path / "c.md"
        concept_file.write_text("# valid", encoding="utf-8")
        ctx = _ctx(
            vectordb_conflict_resolved=True,
            concept_paths=(str(concept_file),),
            change_impact=ChangeImpact.LOCAL,
            new_structures=False,
            concept_quality=ConceptQuality.MEDIUM,
            project_root=tmp_path,
        )
        assert determine_mode(ctx, project_root=tmp_path) is StoryMode.EXPLORATION


# ---------------------------------------------------------------------------
# AK4: Fail-closed for missing/unresolvable fields
# ---------------------------------------------------------------------------


class TestFailClosedMissingFields:
    """Fail-closed behavior: None field values → Exploration + WARNING (AK4)."""

    def test_none_change_impact_fail_closed(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        """change_impact=None (unresolvable) → Exploration + WARNING (fail-closed).

        ERROR-5 fix: assert the WARNING log record is actually emitted so that
        the fail-closed branch cannot silently succeed without the diagnostic.
        """
        import logging

        concept_file = tmp_path / "c.md"
        concept_file.write_text("# c", encoding="utf-8")
        ctx = _ctx(
            concept_paths=(str(concept_file),),
            change_impact=None,
            project_root=tmp_path,
        )
        with caplog.at_level(logging.WARNING, logger="agentkit.governance.setup_preflight_gate.mode_determination"):
            result = determine_mode(ctx, project_root=tmp_path)

        assert result is StoryMode.EXPLORATION
        warning_messages = [r.message for r in caplog.records if r.levelno >= logging.WARNING]
        assert any(
            "change_impact is None" in msg for msg in warning_messages
        ), f"Expected WARNING about 'change_impact is None', got: {warning_messages}"

    def test_none_concept_quality_fail_closed(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        """concept_quality=None (unresolvable) → Exploration + WARNING (fail-closed).

        ERROR-5 fix: assert the WARNING log record is actually emitted so that
        the fail-closed branch cannot silently succeed without the diagnostic.
        """
        import logging

        concept_file = tmp_path / "c.md"
        concept_file.write_text("# c", encoding="utf-8")
        ctx = _ctx(
            concept_paths=(str(concept_file),),
            change_impact=ChangeImpact.LOCAL,
            concept_quality=None,
            project_root=tmp_path,
        )
        with caplog.at_level(logging.WARNING, logger="agentkit.governance.setup_preflight_gate.mode_determination"):
            result = determine_mode(ctx, project_root=tmp_path)

        assert result is StoryMode.EXPLORATION
        warning_messages = [r.message for r in caplog.records if r.levelno >= logging.WARNING]
        assert any(
            "concept_quality is None" in msg for msg in warning_messages
        ), f"Expected WARNING about 'concept_quality is None', got: {warning_messages}"

    def test_trigger_1_emits_warning_on_empty_concept_paths(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Trigger 1 (no valid concept paths) emits a WARNING log record.

        ERROR-5 fix: assert the WARNING is emitted, not just that the return
        value is EXPLORATION (the test would pass even if the log was silently
        suppressed without this assertion).
        """
        import logging

        ctx = _ctx(concept_paths=(), project_root=tmp_path)
        with caplog.at_level(logging.WARNING, logger="agentkit.governance.setup_preflight_gate.mode_determination"):
            result = determine_mode(ctx, project_root=tmp_path)

        assert result is StoryMode.EXPLORATION
        warning_messages = [r.message for r in caplog.records if r.levelno >= logging.WARNING]
        assert any(
            "no valid concept reference" in msg or "concept" in msg.lower()
            for msg in warning_messages
        ), f"Expected WARNING about concept paths (Trigger 1), got: {warning_messages}"

    def test_project_root_none_emits_cwd_fallback_warning(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """project_root=None causes CWD fallback and emits a WARNING (AK5).

        ERROR-5 fix: assert the fallback WARNING from _has_valid_concept_paths
        is observable, not just the bool return.
        """
        import logging

        with caplog.at_level(logging.WARNING, logger="agentkit.governance.setup_preflight_gate.mode_determination"):
            from agentkit.governance.setup_preflight_gate.mode_determination import (
                _has_valid_concept_paths,
            )
            result = _has_valid_concept_paths(("nonexistent_ag3057_test.md",), project_root=None)

        assert isinstance(result, bool)
        warning_messages = [r.message for r in caplog.records if r.levelno >= logging.WARNING]
        assert any(
            "project_root is None" in msg or "CWD" in msg or "cwd" in msg.lower()
            for msg in warning_messages
        ), f"Expected WARNING about project_root=None CWD fallback, got: {warning_messages}"

    def test_new_structures_absent_default_false_no_trigger(
        self, tmp_path: Path
    ) -> None:
        """new_structures=False (default) does NOT trigger Exploration.

        The fail-closed default is False: absence of the field means "no new
        structures", which does not fire Trigger 3.  This is deterministic
        (not an uncontrolled fallback).
        """
        concept_file = tmp_path / "c.md"
        concept_file.write_text("# c", encoding="utf-8")
        ctx = _ctx(
            concept_paths=(str(concept_file),),
            new_structures=False,  # explicit default
            project_root=tmp_path,
        )
        assert determine_mode(ctx, project_root=tmp_path) is StoryMode.EXECUTION

    def test_all_triggers_neutral_no_conflict_gives_execution(
        self, tmp_path: Path
    ) -> None:
        """Default path (all triggers neutral, no conflict) → Execution."""
        concept_file = tmp_path / "c.md"
        concept_file.write_text("# c", encoding="utf-8")
        ctx = _ctx(
            concept_paths=(str(concept_file),),
            change_impact=ChangeImpact.LOCAL,
            new_structures=False,
            concept_quality=ConceptQuality.MEDIUM,
            vectordb_conflict_resolved=False,
            project_root=tmp_path,
        )
        assert determine_mode(ctx, project_root=tmp_path) is StoryMode.EXECUTION


# ---------------------------------------------------------------------------
# AK5: _has_valid_concept_paths sandbox guard
# ---------------------------------------------------------------------------


class TestHasValidConceptPaths:
    """Unit tests for ``_has_valid_concept_paths`` (AK5)."""

    def test_empty_tuple_is_invalid(self, tmp_path: Path) -> None:
        assert _has_valid_concept_paths((), project_root=tmp_path) is False

    def test_existing_file_inside_root_is_valid(self, tmp_path: Path) -> None:
        f = tmp_path / "doc.md"
        f.write_text("# doc", encoding="utf-8")
        assert _has_valid_concept_paths((str(f),), project_root=tmp_path) is True

    def test_nonexistent_file_is_invalid(self, tmp_path: Path) -> None:
        assert (
            _has_valid_concept_paths(
                (str(tmp_path / "missing.md"),), project_root=tmp_path
            )
            is False
        )

    def test_empty_string_is_invalid(self, tmp_path: Path) -> None:
        assert _has_valid_concept_paths(("",), project_root=tmp_path) is False

    def test_whitespace_string_is_invalid(self, tmp_path: Path) -> None:
        assert _has_valid_concept_paths(("   ",), project_root=tmp_path) is False

    def test_path_outside_root_is_invalid(self, tmp_path: Path) -> None:
        """Path outside project_root is a sandbox violation — invalid."""
        sandbox = tmp_path / "proj"
        sandbox.mkdir()
        outside = tmp_path / "outside.md"
        outside.write_text("# outside", encoding="utf-8")
        assert (
            _has_valid_concept_paths((str(outside),), project_root=sandbox) is False
        )

    def test_relative_path_anchored_to_root(self, tmp_path: Path) -> None:
        """Relative paths are anchored to project_root."""
        concept_dir = tmp_path / "concept"
        concept_dir.mkdir()
        (concept_dir / "doc.md").write_text("# c", encoding="utf-8")
        assert (
            _has_valid_concept_paths(
                ("concept/doc.md",), project_root=tmp_path
            )
            is True
        )

    def test_none_project_root_falls_back_to_cwd(self, tmp_path: Path) -> None:
        """project_root=None causes CWD-fallback and WARNING.

        We only check that the function does not crash and returns a bool.
        """
        result = _has_valid_concept_paths(("nonexistent_test_path.md",), project_root=None)
        assert isinstance(result, bool)

    def test_at_least_one_valid_path_in_mixed_tuple(self, tmp_path: Path) -> None:
        """Mixed tuple: one invalid + one valid → valid overall."""
        valid = tmp_path / "ok.md"
        valid.write_text("# ok", encoding="utf-8")
        assert (
            _has_valid_concept_paths(
                ("missing.md", str(valid)), project_root=tmp_path
            )
            is True
        )


# ---------------------------------------------------------------------------
# AK6: concept/research story returns None (no trigger evaluation)
# ---------------------------------------------------------------------------


class TestNonImplementingTypes:
    """AK6: concept / research → None without trigger evaluation (FK-24 §24.3.2)."""

    def test_concept_returns_none_without_trigger_evaluation(self) -> None:
        """Concept story returns None; no triggers are evaluated."""
        ctx = StoryContext(
            project_key="test-project",
            story_id="AG3-999",
            story_type=StoryType.CONCEPT,
            execution_route=None,
            # All triggers would fire if evaluated — but they must not be.
            vectordb_conflict_resolved=True,
            concept_paths=(),
            change_impact=None,
            new_structures=True,
            concept_quality=None,
        )
        assert determine_mode(ctx) is None

    def test_research_returns_none_without_trigger_evaluation(self) -> None:
        """Research story returns None; no triggers are evaluated."""
        ctx = StoryContext(
            project_key="test-project",
            story_id="AG3-999",
            story_type=StoryType.RESEARCH,
            execution_route=None,
            vectordb_conflict_resolved=True,
            concept_paths=(),
            change_impact=None,
            new_structures=True,
            concept_quality=None,
        )
        assert determine_mode(ctx) is None


# ---------------------------------------------------------------------------
# AK7b: Bugfix exploration routing through the machinery
# ---------------------------------------------------------------------------


class TestBugfixExplorationRouting:
    """AK7b: bugfix + EXPLORATION route drives the right phase list (FK-23 §23.1)."""

    def test_bugfix_trigger_fires_exploration_route(self, tmp_path: Path) -> None:
        """A bugfix with concept_quality=LOW gets execution_route=EXPLORATION."""
        concept_file = tmp_path / "c.md"
        concept_file.write_text("# c", encoding="utf-8")
        ctx = StoryContext(
            project_key="test-project",
            story_id="BUG-001",
            story_type=StoryType.BUGFIX,
            execution_route=StoryMode.EXPLORATION,  # as set by determine_mode
            concept_paths=(str(concept_file),),
            change_impact=ChangeImpact.LOCAL,
            new_structures=False,
            concept_quality=ConceptQuality.LOW,
        )
        result = determine_mode(ctx, project_root=tmp_path)
        assert result is StoryMode.EXPLORATION

    def test_bugfix_no_trigger_gives_execution_route(self, tmp_path: Path) -> None:
        """A bugfix with no trigger active gets execution_route=EXECUTION."""
        concept_file = tmp_path / "c.md"
        concept_file.write_text("# c", encoding="utf-8")
        ctx = StoryContext(
            project_key="test-project",
            story_id="BUG-002",
            story_type=StoryType.BUGFIX,
            execution_route=StoryMode.EXECUTION,
            concept_paths=(str(concept_file),),
            change_impact=ChangeImpact.LOCAL,
            new_structures=False,
            concept_quality=ConceptQuality.HIGH,
        )
        result = determine_mode(ctx, project_root=tmp_path)
        assert result is StoryMode.EXECUTION

    def test_bugfix_execution_phases_exclude_exploration(self) -> None:
        """EXECUTION-route bugfix phase list excludes exploration (routing_rules)."""
        from agentkit.story_context_manager.models import StoryContext
        from agentkit.story_context_manager.routing_rules import get_phases_for_story

        ctx = StoryContext(
            project_key="test-project",
            story_id="BUG-003",
            story_type=StoryType.BUGFIX,
            execution_route=StoryMode.EXECUTION,
        )
        phases = get_phases_for_story(ctx)
        assert "exploration" not in phases
        assert phases == ["setup", "implementation", "closure"]

    def test_bugfix_exploration_phases_include_exploration(self) -> None:
        """EXPLORATION-route bugfix phase list includes exploration (routing_rules)."""
        from agentkit.story_context_manager.models import StoryContext
        from agentkit.story_context_manager.routing_rules import get_phases_for_story

        ctx = StoryContext(
            project_key="test-project",
            story_id="BUG-004",
            story_type=StoryType.BUGFIX,
            execution_route=StoryMode.EXPLORATION,
        )
        phases = get_phases_for_story(ctx)
        assert "exploration" in phases
        assert phases == ["setup", "exploration", "implementation", "closure"]
