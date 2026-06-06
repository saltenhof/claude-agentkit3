"""Telemetry harness hooks (FK-68 §68.3.1) -- the reference implementation.

Seven hooks observe agent actions and emit canonical telemetry events; two of
them (:class:`ReviewGuard`, :class:`BudgetEventEmitter`) additionally carry a
governance :class:`~agentkit.governance.protocols.GuardVerdict` (double role,
FK-68 §68.3.1 / AG3-036 §2.1.5/§2.1.6).

AC10 import boundary (reconciled AG3-036 FIX-4): this package imports from the
governance BC ONLY ``agentkit.governance.protocols`` (the canonical home of
``GuardVerdict`` / ``ViolationType``) — plus ``agentkit.core_types`` and
``agentkit.telemetry``. The hooks react to a SELF-CONTAINED ``HookContext``
(``telemetry.hooks.base``), NOT ``guard_evaluation.HookEvent``. It does NOT
import config / story-context / installer / guard_evaluation BCs; values such as
``story_type``, required reviewer roles and the web-call limit are injected as
plain values.
"""

from __future__ import annotations

from agentkit.telemetry.hooks.agent_lifecycle_hook import AgentLifecycleHook
from agentkit.telemetry.hooks.base import (
    EmittingHook,
    HookContext,
    HookResult,
    HookTrigger,
    TelemetryHook,
)
from agentkit.telemetry.hooks.budget_event_emitter import BudgetEventEmitter
from agentkit.telemetry.hooks.commit_hook import CommitHook
from agentkit.telemetry.hooks.divergence_hook import DivergenceHook
from agentkit.telemetry.hooks.drift_check_hook import DriftCheckHook
from agentkit.telemetry.hooks.review_guard import ReviewGuard
from agentkit.telemetry.hooks.review_sentinel_hook import ReviewSentinelHook

__all__ = [
    "AgentLifecycleHook",
    "BudgetEventEmitter",
    "CommitHook",
    "DivergenceHook",
    "DriftCheckHook",
    "EmittingHook",
    "HookContext",
    "HookResult",
    "HookTrigger",
    "ReviewGuard",
    "ReviewSentinelHook",
    "TelemetryHook",
]
