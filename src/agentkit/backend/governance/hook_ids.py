"""Supported governance hook identifiers and phases."""

from __future__ import annotations

PRE_HOOK_IDS = frozenset(
    {
        # FK-30 §30.5.1 guard-hook identifiers (wortgleich) + ccag_gatekeeper
        "branch_guard",
        "orchestrator_guard",
        "integrity",
        "qa_agent_guard",
        "adversarial_guard",
        "self_protection",
        "story_creation_guard",
        # AG3-086 (FK-30 §30.5.1a): the ``budget`` guard-hook blocks PreToolUse
        # via the single block owner WebCallBudgetGuard (governance). The previous
        # ``budget_event_emitter`` PreToolUse block double role (AG3-036 §2.1.6)
        # is REMOVED — the emitter is observational PostToolUse only.
        "budget",
        "skill_usage_check",
        # AG3-086 (FK-31 §31.7): the prompt-integrity guard blocks PreToolUse on
        # every ``Agent`` sub-agent spawn (escape / schema / template).
        "prompt_integrity",
        "health_monitor",
        "ccag_gatekeeper",
        # AG3-036 (FK-68 §68.3.1) FIX-1: the ``review_guard`` double-role telemetry
        # hook enforces at PreToolUse so a DENY blocks BEFORE the commit runs
        # (§2.1.5). A PostToolUse DENY cannot stop an action that already ran.
        "review_guard",
        # AG3-147: observational PRE snapshot for mechanical commit invalidation.
        "commit_hook",
    }
)


POST_HOOK_IDS = frozenset(
    {
        "telemetry",
        # AG3-086 (FK-30 §30.5.2): the observational ``web_call`` counter
        # (BudgetEventEmitter) emits at PostToolUse Web. The blocking decision is
        # the PreToolUse ``budget`` guard's (WebCallBudgetGuard).
        "budget",
        "health_monitor",
        # AG3-147: observational POST delta check and ``increment_commit`` emit.
        "commit_hook",
    }
)


SUPPORTED_PHASES = frozenset({"pre", "post"})


SUPPORTED_HOOK_IDS = frozenset(PRE_HOOK_IDS | POST_HOOK_IDS)
