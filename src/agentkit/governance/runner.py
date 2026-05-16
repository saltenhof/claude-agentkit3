"""Guard runner -- evaluates all registered guards for an operation.

Orchestration only (ARCH-12). Business logic lives in individual guards.
The runner is fail-closed: if any guard blocks, the operation is blocked.
All guards run even if earlier ones block, so that complete violation
information is collected.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from agentkit.governance.protocols import GuardVerdict, ViolationType

if TYPE_CHECKING:
    from agentkit.governance.guard_evaluation import HookEvent
    from agentkit.governance.protocols import GovernanceGuard

type HookDecision = GuardVerdict

PRE_HOOK_IDS = frozenset(
    {
        "branch_guard",
        "orchestrator_guard",
        "story_creation_guard",
        "integrity_guard",
        "qa_agent_guard",
        "adversarial_guard",
        "self_protection_guard",
        "health_monitor",
        "ccag_gatekeeper",
    }
)
POST_HOOK_IDS = frozenset(
    {
        "telemetry",
        "review_guard",
        "budget",
        "health_monitor",
    }
)
SUPPORTED_PHASES = frozenset({"pre", "post"})
SUPPORTED_HOOK_IDS = frozenset(PRE_HOOK_IDS | POST_HOOK_IDS)


@dataclass(frozen=True)
class HookWrapperArgs:
    """Validated hook-wrapper command-line selector."""

    phase: str
    hook_id: str


class GuardRunner:
    """Runs all registered guards for an operation.

    Fail-closed semantics: if **any** guard blocks, the operation is
    blocked.  All guards are evaluated even when earlier ones already
    blocked, so that complete violation information is available.

    An empty runner (no guards registered) allows everything -- there
    are no rules to violate.
    """

    def __init__(
        self, guards: list[GovernanceGuard] | None = None,
    ) -> None:
        self._guards: list[GovernanceGuard] = list(guards) if guards else []

    def register(self, guard: GovernanceGuard) -> None:
        """Add a guard to the evaluation pipeline.

        Args:
            guard: A ``GovernanceGuard`` implementation to register.
        """
        self._guards.append(guard)

    def evaluate(
        self, operation: str, context: dict[str, object],
    ) -> list[GuardVerdict]:
        """Evaluate all guards. Returns list of all verdicts.

        Even if the first guard blocks, all remaining guards still run
        (to collect complete violation information).

        Args:
            operation: The operation type being attempted.
            context: Operation-specific context dict.

        Returns:
            List of ``GuardVerdict`` instances, one per registered guard.
        """
        return [g.evaluate(operation, context) for g in self._guards]

    def is_allowed(
        self, operation: str, context: dict[str, object],
    ) -> tuple[bool, list[GuardVerdict]]:
        """Check if an operation is allowed.

        Convenience wrapper around :meth:`evaluate` that also returns a
        boolean summary.

        Args:
            operation: The operation type being attempted.
            context: Operation-specific context dict.

        Returns:
            A ``(allowed, verdicts)`` tuple where ``allowed`` is ``True``
            only if every guard returned ``ALLOW``.
        """
        verdicts = self.evaluate(operation, context)
        allowed = all(v.allowed for v in verdicts)
        return allowed, verdicts


class Governance:
    """Harness-neutral governance top surface."""

    @staticmethod
    def run_hook(
        hook_id: str,
        event: HookEvent,
        *,
        phase: str = "pre",
        project_root: Path | None = None,
    ) -> HookDecision:
        """Dispatch a named hook against the harness-neutral event model."""
        return run_hook(
            hook_id,
            event,
            phase=phase,
            project_root=project_root,
        )


def parse_hook_wrapper_args(
    argv: list[str],
    *,
    command_name: str,
) -> HookWrapperArgs:
    """Validate ``agentkit-hook-{harness} {phase} {hook_id}`` arguments."""
    if len(argv) != 2:
        raise ValueError(f"Usage: {command_name} {{pre|post}} {{hook_id}}")
    phase, hook_id = argv
    verdict = validate_hook_selector(phase=phase, hook_id=hook_id)
    if verdict is not None:
        raise ValueError(verdict.message or "Invalid hook selector")
    return HookWrapperArgs(phase=phase, hook_id=hook_id)


def validate_hook_selector(*, phase: str, hook_id: str) -> GuardVerdict | None:
    """Return a fail-closed verdict when a hook selector is invalid."""
    if phase not in SUPPORTED_PHASES:
        return GuardVerdict.block(
            "hook_dispatcher",
            ViolationType.POLICY_VIOLATION,
            f"Unknown hook phase {phase!r}; expected one of {sorted(SUPPORTED_PHASES)}",
            detail={"phase": phase, "hook_id": hook_id},
        )
    if hook_id not in _hook_ids_for_phase(phase):
        return GuardVerdict.block(
            "hook_dispatcher",
            ViolationType.POLICY_VIOLATION,
            f"Unknown hook id {hook_id!r} for phase {phase!r}",
            detail={
                "phase": phase,
                "hook_id": hook_id,
                "supported_hook_ids": sorted(_hook_ids_for_phase(phase)),
            },
        )
    return None


def run_hook(
    hook_id: str,
    event: HookEvent,
    *,
    phase: str = "pre",
    project_root: Path | None = None,
) -> HookDecision:
    """Run a named governance hook, fail-closed on unknown selectors.

    For ``phase="pre"`` and ``hook_id="ccag_gatekeeper"``, delegates to
    :class:`~agentkit.governance.ccag.runtime.CcagPermissionRuntime` which
    implements FK-42 §42.1.  All other pre-hooks are dispatched to the
    general :func:`~agentkit.governance.guard_evaluation.evaluate_pre_tool_use`
    guard evaluation chain.

    Args:
        hook_id: The registered hook identifier (see PRE_HOOK_IDS / POST_HOOK_IDS).
        event: Harness-neutral hook event.
        phase: ``"pre"`` or ``"post"``.
        project_root: Project root for guard context resolution.

    Returns:
        A :class:`~agentkit.governance.protocols.GuardVerdict`.
    """
    invalid = validate_hook_selector(phase=phase, hook_id=hook_id)
    if invalid is not None:
        return invalid
    if phase == "post":
        return GuardVerdict.allow(hook_id)

    # CCAG is the last PreToolUse hook — dispatched separately (FK-42 §42.5.2)
    if hook_id == "ccag_gatekeeper":
        return _run_ccag_hook(event)

    from agentkit.governance.guard_evaluation import evaluate_pre_tool_use

    return evaluate_pre_tool_use(event, project_root=project_root or Path.cwd())


def _run_ccag_hook(event: HookEvent) -> HookDecision:
    """Dispatch to CcagPermissionRuntime and translate decision to GuardVerdict.

    The CCAG runtime returns a :class:`~agentkit.governance.ccag.runtime.CcagDecision`
    which we map to the :class:`~agentkit.governance.protocols.GuardVerdict`
    type used by the hook chain.

    Translation:
        ``allow``              → ``GuardVerdict.allow("ccag_gatekeeper")``
        ``unknown_permission`` → ``GuardVerdict.allow("ccag_gatekeeper")``
            (unknown → adapter decides; in story_execution the request is
             persisted and the CLI exits 2 via the standalone path)
        ``block_by_rule``      → ``GuardVerdict.block("ccag_gatekeeper", ...)``

    Args:
        event: Harness-neutral hook event.

    Returns:
        A :class:`~agentkit.governance.protocols.GuardVerdict`.
    """
    from agentkit.governance.ccag.runtime import CcagDecisionKind, CcagPermissionRuntime

    runtime = CcagPermissionRuntime()
    decision = runtime.evaluate(event)

    if decision.kind == CcagDecisionKind.BLOCK_BY_RULE:
        return GuardVerdict.block(
            "ccag_gatekeeper",
            ViolationType.UNAUTHORIZED_OPERATION,
            decision.reason or "Blocked by CCAG deny rule",
            detail={
                "ccag_decision": decision.kind.value,
                "matched_rule_id": decision.matched_rule_id,
            },
        )

    # allow or unknown_permission → allow at the GuardVerdict level
    # For unknown_permission in story_execution, the PermissionRequest was
    # already created by CcagPermissionRuntime._handle_unknown(); the CLI
    # entry points can inspect the decision.kind for exit code decisions.
    return GuardVerdict.allow("ccag_gatekeeper")


def _hook_ids_for_phase(phase: str) -> frozenset[str]:
    if phase == "pre":
        return PRE_HOOK_IDS
    if phase == "post":
        return POST_HOOK_IDS
    return frozenset()


__all__ = [
    "Governance",
    "GuardRunner",
    "HookDecision",
    "HookWrapperArgs",
    "POST_HOOK_IDS",
    "PRE_HOOK_IDS",
    "SUPPORTED_HOOK_IDS",
    "SUPPORTED_PHASES",
    "parse_hook_wrapper_args",
    "run_hook",
    "validate_hook_selector",
]
