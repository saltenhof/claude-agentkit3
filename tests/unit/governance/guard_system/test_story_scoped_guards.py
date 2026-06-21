"""Baseline vs story-scoped guard taxonomy tests (AG3-018 DELTA-B, AC5).

FK-24 §24.3.4 Mode-Profil + ``formal.operating-modes.invariants``:

* ``story_mode_fast_disables_story_scoped_guards_only`` -- fast disables ONLY the
  story-scoped guards + lock-records;
* ``baseline_guards_apply_in_all_modes`` -- the baseline guards stay active in
  EVERY mode including fast (AC5).
"""

from __future__ import annotations

from agentkit.backend.governance.guard_system.story_scoped_guards import (
    BASELINE_GUARD_IDS,
    STORY_SCOPED_GUARD_IDS,
    should_activate_story_scoped_guards,
    should_create_story_lock_records,
)
from agentkit.backend.story_context_manager.models import StoryContext
from agentkit.backend.story_context_manager.story_model import WireStoryMode
from agentkit.backend.story_context_manager.types import StoryMode, StoryType


def _ctx(*, mode: WireStoryMode) -> StoryContext:
    return StoryContext(
        project_key="proj",
        story_id="AG3-018",
        story_type=StoryType.IMPLEMENTATION,
        execution_route=StoryMode.EXECUTION,
        mode=mode,
    )


def test_fast_disables_story_scoped_guards() -> None:
    assert should_activate_story_scoped_guards(_ctx(mode=WireStoryMode.FAST)) is False


def test_fast_creates_no_story_lock_records() -> None:
    assert should_create_story_lock_records(_ctx(mode=WireStoryMode.FAST)) is False


def test_standard_activates_story_scoped_guards() -> None:
    ctx = _ctx(mode=WireStoryMode.STANDARD)
    assert should_activate_story_scoped_guards(ctx) is True
    assert should_create_story_lock_records(ctx) is True


def test_baseline_and_story_scoped_taxonomy_are_disjoint() -> None:
    # The two sets must not overlap: a guard is either baseline or story-scoped.
    assert BASELINE_GUARD_IDS.isdisjoint(STORY_SCOPED_GUARD_IDS)


def test_baseline_guards_cover_the_mandated_set() -> None:
    # AC5 / baseline_guards_apply_in_all_modes: destructive-git (branch_guard) +
    # self-protection, secrets protection and CCAG are all baseline (fast too).
    assert "self_protection" in BASELINE_GUARD_IDS
    assert "secrets_protection" in BASELINE_GUARD_IDS
    assert "ccag_gatekeeper" in BASELINE_GUARD_IDS


def test_branch_guard_is_baseline_not_story_scoped() -> None:
    # FIX-7(a) (FK-30 §30.5.1/:556 + baseline_guards_apply_in_all_modes):
    # branch_guard is the DESTRUCTIVE-GIT protection -> BASELINE; it must stay
    # active in fast and must NEVER be classified story-scoped.
    assert "branch_guard" in BASELINE_GUARD_IDS
    assert "branch_guard" not in STORY_SCOPED_GUARD_IDS


def test_story_scoped_set_holds_the_run_scoped_guards() -> None:
    # The scope-overlap / artifact / orchestrator guards are story-scoped (fast=OUT).
    assert "scope_guard" in STORY_SCOPED_GUARD_IDS
    assert "qa_agent_guard" in STORY_SCOPED_GUARD_IDS
    assert "orchestrator_guard" in STORY_SCOPED_GUARD_IDS
    # Baseline guards are NOT in the story-scoped (deactivatable) set.
    assert "self_protection" not in STORY_SCOPED_GUARD_IDS
    assert "ccag_gatekeeper" not in STORY_SCOPED_GUARD_IDS
