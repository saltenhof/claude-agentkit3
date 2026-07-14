"""CcagPermissionRuntime — learnable permission layer for tool calls.

Top surface: ``evaluate(hook_event: HookEvent) -> CcagDecision``.

This module implements FK-42 §42.1 (architecture) and §42.2.5 (mode-sharp
decision).  It is NOT part of the GuardSystem — it is a separate Sub
within the ``governance-and-guards`` BC (PROJECT_STRUCTURE.md §ccag_permission_runtime).

Evaluation order (FK-42 §42.2.1 / F-42-015):
    1. Block rules  → ``block_by_rule``
    2. Allow rules  → ``allow``
    3. No match:
       - ``story_execution`` mode → ``unknown_permission``; runner opens centrally
       - ``ai_augmented`` / ``interactive_agent`` mode → ``unknown_permission``
         (caller may show host prompt dialog)

CCAG is the LAST PreToolUse hook in the chain (FK-42 §42.5.2, F-42-030).
Hard Guards (BranchGuard, ScopeGuard, ArtifactGuard) run before CCAG and
have absolute priority.  CCAG only evaluates calls that passed all guards.

Operating modes (FK-42 §42.2.5):
    - ``story_execution``: autonomous pipeline execution.
      No host-prompt dialog possible. Unknown is opened centrally by the runner.
    - ``ai_augmented``:   human is present and supervising.
      Unknown → ``unknown_permission`` (caller shows dialog).
    - ``interactive_agent``: interactive session.
      Unknown → ``unknown_permission`` (caller shows dialog).

Fail-CLOSED clause (AG3-086 / FK-42 §42.2.4, NO ERROR BYPASSING): CCAG requires a
pre-computed capability hull. A missing hull AND any unexpected evaluation error
both produce a fail-closed ``block_by_rule`` — NEVER a global allow. The previous
fail-OPEN (Exception -> allow) was a security defect and is removed. CCAG remains
a comfort layer within the already-permitted capability zone; the hard Guards are
the last line of defence, but CCAG itself must not silently permit.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import TYPE_CHECKING, Literal

from agentkit.backend.governance.ccag.rules import (
    CcagRuleSet,
    load_rules,
    rule_matches,
)

if TYPE_CHECKING:
    from agentkit.backend.governance.ccag.permission_records import PermissionRequestRecord
    from agentkit.backend.governance.guard_evaluation import HookEvent
    from agentkit.backend.governance.principal_capabilities import CapabilityHull

_logger = logging.getLogger(__name__)

#: Synthetic rule id surfaced when CCAG is invoked without a capability hull
#: (FK-42 §42.2.4 fail-closed BLOCK).
_MISSING_HULL_RULE_ID = "FK-42-42.2.4-missing-hull"

#: Synthetic rule id surfaced when CCAG evaluation raises unexpectedly
#: (fail-closed BLOCK — NO ERROR BYPASSING).
_EVALUATION_ERROR_RULE_ID = "FK-42-ccag-evaluation-error"

# ---------------------------------------------------------------------------
# Decision model
# ---------------------------------------------------------------------------


class CcagDecisionKind(StrEnum):
    """Possible outcomes of a CCAG evaluation (FK-42 §42.2)."""

    ALLOW = "allow"
    BLOCK_BY_RULE = "block_by_rule"
    UNKNOWN_PERMISSION = "unknown_permission"


@dataclass(frozen=True)
class CcagDecision:
    """Result of a CCAG rule evaluation.

    Attributes:
        kind: One of ``allow``, ``block_by_rule``, ``unknown_permission``.
        matched_rule_id: Rule ID that produced the decision (``None`` for unknown).
        reason: Human-readable explanation.
        permission_request: Reserved compatibility field. Central creation is
            backend-owned, so runtime evaluation leaves it ``None``.
        detail: Structured detail dict for audit logging.
    """

    kind: CcagDecisionKind
    matched_rule_id: str | None = None
    reason: str = ""
    permission_request: PermissionRequestRecord | None = None
    detail: dict[str, object] = field(default_factory=dict)

    @property
    def allowed(self) -> bool:
        """Return True when the decision permits the tool call."""
        return self.kind == CcagDecisionKind.ALLOW

    @classmethod
    def allow(cls, rule_id: str, reason: str = "") -> CcagDecision:
        """Factory: produce an allow decision.

        Args:
            rule_id: The matching rule's ID.
            reason: Human-readable explanation.

        Returns:
            A ``CcagDecision`` with kind ``allow``.
        """
        return cls(
            kind=CcagDecisionKind.ALLOW,
            matched_rule_id=rule_id,
            reason=reason or f"Allowed by CCAG rule {rule_id!r}",
        )

    @classmethod
    def block(cls, rule_id: str, reason: str = "") -> CcagDecision:
        """Factory: produce a block_by_rule decision.

        Args:
            rule_id: The matching rule's ID.
            reason: Human-readable explanation.

        Returns:
            A ``CcagDecision`` with kind ``block_by_rule``.
        """
        return cls(
            kind=CcagDecisionKind.BLOCK_BY_RULE,
            matched_rule_id=rule_id,
            reason=reason or f"Blocked by CCAG deny rule {rule_id!r}",
        )

    @classmethod
    def unknown(
        cls,
        tool_name: str,
        operating_mode: str,
        permission_request: PermissionRequestRecord | None = None,
    ) -> CcagDecision:
        """Factory: produce an unknown_permission decision.

        Args:
            tool_name: The tool name whose permission is unknown.
            operating_mode: The current operating mode.
            permission_request: Created request (story_execution mode only).

        Returns:
            A ``CcagDecision`` with kind ``unknown_permission``.
        """
        reason = (
            f"No CCAG rule matches {tool_name!r} in mode {operating_mode!r}"
        )
        return cls(
            kind=CcagDecisionKind.UNKNOWN_PERMISSION,
            reason=reason,
            permission_request=permission_request,
            detail={
                "tool_name": tool_name,
                "operating_mode": operating_mode,
                "has_permission_request": permission_request is not None,
            },
        )


# ---------------------------------------------------------------------------
# Operating mode extraction
# ---------------------------------------------------------------------------

#: HookEvent field that carries operating mode (added if absent).
_OPERATING_MODE_FIELD = "operating_mode"

# CCAG's permission-decision axis is DELIBERATELY a DIFFERENT axis from the FK-56
# operating-mode literal (``story_context_manager.operating_mode_resolver.OperatingMode``
# = ``ai_augmented``/``story_execution``/``binding_invalid``). Per FK-42 §42.2.5 +
# FK-56 §56.4 CCAG keys its no-match decision on whether a synchronous host-prompt
# is admissible, which is a property of the PRINCIPAL (FK-56 §56.4: the
# ``ai_augmented`` mode's main-agent principal IS the ``interactive_agent``, a
# distinct capability class from the ``orchestrator``). It therefore has NO
# ``binding_invalid`` (binding validity is the hard guards' job, not CCAG's) and
# instead distinguishes ``interactive_agent``. Conflating the two literals would
# build a SECOND, conflicting operating-mode truth (FIX-THE-MODEL: forbidden), so
# this axis carries its own name and is NOT the SSOT ``OperatingMode``.
CcagDecisionMode = Literal["story_execution", "ai_augmented", "interactive_agent"]

_STORY_EXECUTION: CcagDecisionMode = "story_execution"
_AI_AUGMENTED: CcagDecisionMode = "ai_augmented"
_INTERACTIVE_AGENT: CcagDecisionMode = "interactive_agent"

_KNOWN_MODES: frozenset[str] = frozenset(
    {_STORY_EXECUTION, _AI_AUGMENTED, _INTERACTIVE_AGENT}
)


def _extract_operating_mode(event: HookEvent) -> CcagDecisionMode:
    """Extract the operating mode from a HookEvent.

    HookEvent is frozen (Pydantic) and does not currently carry
    ``operating_mode`` as a typed field.  We read it from
    ``operation_args`` or fall back to ``"ai_augmented"`` (safest
    default: unknown mode should not block the operator).

    In ``story_execution`` mode the hook is called during autonomous
    pipeline runs where no human can answer a dialog.

    Args:
        event: The harness-neutral hook event.

    Returns:
        One of the recognised operating modes.
    """
    mode_raw = str(event.operation_args.get(_OPERATING_MODE_FIELD, "")).strip()
    if mode_raw in _KNOWN_MODES:
        return mode_raw  # type: ignore[return-value]
    # Fallback: if operating_mode not set, use ai_augmented (permissive default)
    return _AI_AUGMENTED


# ---------------------------------------------------------------------------
# CcagPermissionRuntime
# ---------------------------------------------------------------------------


class CcagPermissionRuntime:
    """Learnable permission layer for tool calls (FK-42 §42.1).

    This is the top-level surface of the CCAG sub-component.  It:
    - Loads CCAG rules from YAML files on every call (no cache).
    - Evaluates block rules first, then allow rules.
    - In ``story_execution`` mode, returns unknown for central request creation
      permissions instead of asking the human interactively.
    - In ``ai_augmented`` / ``interactive_agent`` mode, returns
      ``unknown_permission`` so the adapter can show a host dialog.

    Args:
        rules_dir: Path to the CCAG rules directory.
            Defaults to ``.agentkit/ccag/rules/`` relative to CWD.
        Permission persistence is deliberately absent from this evaluator.
        The hook runner opens canonical requests through the injected REST edge.
    """

    def __init__(
        self,
        *,
        rules_dir: Path | str | None = None,
    ) -> None:
        self._rules_dir = Path(rules_dir) if rules_dir is not None else None

    def evaluate(
        self,
        hook_event: HookEvent,
        *,
        capability_hull: CapabilityHull | None = None,
    ) -> CcagDecision:
        """Evaluate CCAG rules for a tool invocation event.

        Top surface used by the hook dispatcher (FK-42 §42.1).

        FK-42 §42.2.4 (AG3-086, FAIL-CLOSED): CCAG may run ONLY after the
        capability hull has been pre-computed (``principal_type`` / ``path_class``
        / ``operation_class`` + the hard matrix and freeze verdicts). When
        ``capability_hull`` is ``None`` the CCAG call is INADMISSIBLE and produces
        a fail-closed BLOCK — NEVER a global allow. The previous fail-OPEN
        behaviour (Exception -> allow) is REMOVED: any unexpected evaluation error
        is mapped to a fail-closed BLOCK (NO ERROR BYPASSING).

        Algorithm (FK-42 §42.2):
        1. Extract tool_name and tool_input from the event.
        2. Load rules (fresh from disk, no cache).
        3. Evaluate block rules first (fail-closed).
        4. Evaluate allow rules.
        5. No match → mode-specific handling (§42.2.5).

        Args:
            hook_event: The harness-neutral :class:`HookEvent`.
            capability_hull: The pre-computed capability hull (FK-42 §42.2.4).
                ``None`` makes the call inadmissible -> fail-closed BLOCK.

        Returns:
            A :class:`CcagDecision` with kind ``allow``, ``block_by_rule``,
            or ``unknown_permission``.
        """
        if capability_hull is None:
            # FK-42 §42.2.4: no hull -> CCAG is inadmissible. Fail-closed BLOCK
            # (never a global allow). The capability layer is the precondition;
            # without it CCAG cannot reason about the already-permitted zone.
            _logger.error(
                "CCAG invoked WITHOUT a pre-computed capability hull for %r — "
                "fail-closed BLOCK (FK-42 §42.2.4)",
                hook_event.operation,
            )
            return CcagDecision(
                kind=CcagDecisionKind.BLOCK_BY_RULE,
                matched_rule_id=_MISSING_HULL_RULE_ID,
                reason=(
                    "CCAG evaluation is inadmissible without a pre-computed "
                    "capability hull (FK-42 §42.2.4) — fail-closed"
                ),
                detail={"fail_closed": True, "reason": "missing_capability_hull"},
            )
        try:
            return self._evaluate_internal(hook_event)
        except Exception:  # noqa: BLE001
            # FAIL-CLOSED (AG3-086 / NO ERROR BYPASSING): an unexpected error must
            # NOT be waved through as an allow. CCAG is a comfort layer, but a
            # broken CCAG must block, not silently permit (the previous fail-OPEN
            # was a security defect).
            _logger.exception(
                "CCAG evaluation failed unexpectedly — fail-closed BLOCK for %r",
                hook_event.operation,
            )
            return CcagDecision(
                kind=CcagDecisionKind.BLOCK_BY_RULE,
                matched_rule_id=_EVALUATION_ERROR_RULE_ID,
                reason="CCAG evaluation error — fail-closed",
                detail={"fail_closed": True, "reason": "ccag_evaluation_error"},
            )

    def _evaluate_internal(self, hook_event: HookEvent) -> CcagDecision:
        """Core evaluation logic (not wrapped in fail-open).

        Args:
            hook_event: The harness-neutral hook event.

        Returns:
            A :class:`CcagDecision`.
        """
        tool_name = self._tool_name_from_event(hook_event)
        tool_input = dict(hook_event.operation_args)
        is_subagent = hook_event.principal_kind == "subagent"
        operating_mode = _extract_operating_mode(hook_event)

        rule_set: CcagRuleSet = load_rules(
            is_subagent=is_subagent,
            rules_dir=self._rules_dir,
        )

        # 1. Block rules first (highest priority)
        for rule in rule_set.blocks:
            if rule_matches(rule, tool_name, tool_input):
                return CcagDecision.block(
                    rule.rule_id,
                    rule.description or f"Blocked by CCAG deny rule {rule.rule_id!r}",
                )

        # 2. Allow rules
        for rule in rule_set.allows:
            if rule_matches(rule, tool_name, tool_input):
                return CcagDecision.allow(
                    rule.rule_id,
                    rule.description or f"Allowed by CCAG rule {rule.rule_id!r}",
                )

        # 3. No rule matched — mode-specific handling (FK-42 §42.2.5)
        return self._handle_unknown(
            tool_name=tool_name,
            tool_input=tool_input,
            operating_mode=operating_mode,
            hook_event=hook_event,
        )

    def _handle_unknown(
        self,
        *,
        tool_name: str,
        tool_input: dict[str, object],
        operating_mode: CcagDecisionMode,
        hook_event: HookEvent,
    ) -> CcagDecision:
        """Handle the no-match case per operating mode (FK-42 §42.2.5).

        In ``story_execution`` mode: return a fail-closed unknown decision; the
        runner opens the canonical request through backend REST.
        In other modes: return ``unknown_permission`` so the adapter may
        present a host dialog.

        Args:
            tool_name: The tool name.
            tool_input: The tool input dict.
            operating_mode: The current operating mode.
            hook_event: The original hook event (for context).

        Returns:
            A ``CcagDecision`` with kind ``unknown_permission``.
        """
        if operating_mode == _STORY_EXECUTION:
            return CcagDecision.unknown(
                tool_name=tool_name, operating_mode=operating_mode
            )

        # ai_augmented / interactive_agent: no request created, caller
        # is responsible for showing a host prompt dialog
        return CcagDecision.unknown(
            tool_name=tool_name,
            operating_mode=operating_mode,
        )

    @staticmethod
    def _tool_name_from_event(event: HookEvent) -> str:
        """Derive a canonical tool name from the harness-neutral event.

        The HookEvent uses ``operation`` (e.g. ``"bash_command"``) rather than
        the harness-specific tool name (e.g. ``"Bash"``).  We map back to the
        canonical Claude Code tool name so CCAG rules written against tool names
        like ``"Bash"`` work correctly.

        Args:
            event: The harness-neutral hook event.

        Returns:
            The canonical tool name string.
        """
        _op_to_tool: dict[str, str] = {
            "bash_command": "Bash",
            "file_write": "Write",
            "file_edit": "Edit",
            "file_read": "Read",
        }
        # Prefer explicit tool_name in operation_args if present
        explicit = event.operation_args.get("tool_name")
        if isinstance(explicit, str) and explicit:
            return explicit
        return _op_to_tool.get(event.operation, event.operation)


__all__ = [
    "CcagDecision",
    "CcagDecisionKind",
    "CcagDecisionMode",
    "CcagPermissionRuntime",
    "_AI_AUGMENTED",
    "_INTERACTIVE_AGENT",
    "_STORY_EXECUTION",
]
