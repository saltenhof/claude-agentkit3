"""Baseline vs story-scoped guard taxonomy + fast-mode activation decision.

FK-24 §24.3.4 Mode-Profil (``Setup -> Guard-Aktivierung = OUT (Baseline-Guards
bleiben)``) and ``formal.operating-modes.invariants``:

* ``baseline_guards_apply_in_all_modes`` -- the BASELINE guards stay active in
  EVERY operating mode, including fast: destructive-git protection, secrets
  protection, self-protection and CCAG (FK-30 §30.5.4 / §42).
* ``story_mode_fast_disables_story_scoped_guards_only`` -- ``mode == fast``
  deactivates ONLY the STORY-SCOPED guards (the per-story branch/scope-overlap/
  artifact/lock-record guards activated for a governing run) and creates NO
  story lock-records; the baseline guards are untouched.

This module owns the typed taxonomy (so the sets are not a string cascade) and
the single decision function :func:`should_activate_story_scoped_guards`. The
guard-activation path (and the story lock-record creation) consults this decision
so a fast story routes around story-scoped activation while baseline enforcement
(``governance.runner._run_capability_enforcement`` /
``_run_self_protection_guard`` / ``_run_ccag_hook``) keeps running unconditionally
for ALL modes -- those are NOT gated by this decision.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from agentkit.story_context_manager.story_model import WireStoryMode

if TYPE_CHECKING:
    from agentkit.story_context_manager.models import StoryContext

#: BASELINE guards -- active in ALL modes (fast included),
#: ``baseline_guards_apply_in_all_modes``. Hook ids mirror
#: ``governance.runner.PRE_HOOK_IDS`` (the always-on enforcement surface).
#:
#: FIX-7(a) (FK-30 §30.5.1/30_...:556 + ``baseline_guards_apply_in_all_modes``):
#: ``branch_guard`` is the DESTRUCTIVE-GIT protection (force-push, hard-reset,
#: push/rebase on main) -- a BASELINE guard that must stay active in EVERY mode,
#: fast included. It was previously mis-classified story-scoped; that contradicted
#: both FK-30 and the real enforcement seam (``guard_evaluation._guards_for_state``
#: ALWAYS adds ``BranchGuard()``, unconditionally on operating mode). A baseline
#: guard must NEVER be classified story-scoped.
BASELINE_GUARD_IDS: frozenset[str] = frozenset(
    {
        "branch_guard",  # FK-30 §30.5.4/§31.1 destructive-git protection (BASELINE)
        "self_protection",  # FK-30 §30.5.3 governance self-protection
        "secrets_protection",  # FK-30 secrets protection (path-class SECRET)
        "ccag_gatekeeper",  # FK-42 CCAG permission runtime
        "story_creation_guard",  # FK-31 §31.5 always-on story-creation guard
    }
)

#: STORY-SCOPED guards -- activated per governing story run and DEACTIVATED in
#: ``mode == fast`` (the run-scoped scope-overlap/artifact/orchestrator guards
#: that the real enforcement seam gates on ``operating_mode == story_execution``).
#: Strictly per FK-31: these are the per-story-binding guards, NOT the baseline
#: destructive-git protection.
STORY_SCOPED_GUARD_IDS: frozenset[str] = frozenset(
    {
        "orchestrator_guard",  # FK-30 §31.2 orchestrator-scope guard (per run)
        "qa_agent_guard",  # FK-31 §31.4 QA-artifact protection (per-story lock)
        "adversarial_guard",  # FK-27 §31.6 adversarial-sandbox guard (per run)
        "scope_guard",  # FK-31 §31.1 story scope-overlap guard (per run)
    }
)


def is_fast(ctx: StoryContext) -> bool:
    """Whether the story runs in fast mode (FK-24 §24.3.3, decoupled axis).

    Args:
        ctx: The run :class:`StoryContext`.

    Returns:
        ``True`` iff ``ctx.mode is WireStoryMode.FAST``.
    """
    return ctx.mode is WireStoryMode.FAST


def should_activate_story_scoped_guards(ctx: StoryContext) -> bool:
    """Whether the story-scoped guards + lock-records should be activated.

    FK-24 §24.3.4 (``Guard-Aktivierung = OUT`` for fast) +
    ``story_mode_fast_disables_story_scoped_guards_only``: a fast story does NOT
    activate the story-scoped guards and creates NO story lock-records; every
    other mode does. The BASELINE guards are independent of this decision and
    stay active in all modes.

    Args:
        ctx: The run :class:`StoryContext`.

    Returns:
        ``False`` for ``mode == fast``; ``True`` otherwise.
    """
    return not is_fast(ctx)


def should_create_story_lock_records(ctx: StoryContext) -> bool:
    """Whether story lock-records should be created at story start.

    Story lock-records are part of the story-scoped activation (FK-22 §22.7 /
    FK-24 §24.3.4): created for a standard governing run, NOT created for a fast
    story ("Lock-Records werden nicht angelegt"). Mirrors
    :func:`should_activate_story_scoped_guards`.

    Args:
        ctx: The run :class:`StoryContext`.

    Returns:
        ``False`` for ``mode == fast``; ``True`` otherwise.
    """
    return not is_fast(ctx)


__all__ = [
    "BASELINE_GUARD_IDS",
    "STORY_SCOPED_GUARD_IDS",
    "is_fast",
    "should_activate_story_scoped_guards",
    "should_create_story_lock_records",
]
