"""CcagPermissionRuntime — lernfaehige Permission-Schicht fuer Tool-Calls.

Top surface: ``evaluate(hook_event: HookEvent) -> CcagDecision``.

This module implements FK-42 §42.1 (Architektur) and §42.2.5 (modus-scharfe
Entscheidung).  It is NOT part of the GuardSystem — it is a separate Sub
within the ``governance-and-guards`` BC (PROJECT_STRUCTURE.md §ccag_permission_runtime).

Evaluation order (FK-42 §42.2.1 / F-42-015):
    1. Block rules  → ``block_by_rule``
    2. Allow rules  → ``allow``
    3. No match:
       - ``story_execution`` mode → ``unknown_permission`` + PermissionRequest created
       - ``ai_augmented`` / ``interactive_agent`` mode → ``unknown_permission``
         (caller may show host prompt dialog)

CCAG is the LAST PreToolUse hook in the chain (FK-42 §42.5.2, F-42-030).
Hard Guards (BranchGuard, ScopeGuard, ArtifactGuard) run before CCAG and
have absolute priority.  CCAG only evaluates calls that passed all guards.

Operating modes (FK-42 §42.2.5):
    - ``story_execution``: autonomous pipeline execution.
      No host-prompt dialog possible.  Unknown → ``unknown_permission`` + request.
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
import uuid
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import TYPE_CHECKING, Literal

from agentkit.governance.ccag.requests import (
    DEFAULT_TTL_SECONDS,
    PermissionRequest,
    PermissionRequestStore,
)
from agentkit.governance.ccag.rules import (
    CcagRuleSet,
    load_rules,
    rule_matches,
)

if TYPE_CHECKING:
    from agentkit.governance.ccag.leases import PermissionLeaseStore
    from agentkit.governance.guard_evaluation import HookEvent
    from agentkit.governance.principal_capabilities import CapabilityHull

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
        permission_request: Created ``PermissionRequest`` when kind is
            ``unknown_permission`` in ``story_execution`` mode.
        detail: Structured detail dict for audit logging.
    """

    kind: CcagDecisionKind
    matched_rule_id: str | None = None
    reason: str = ""
    permission_request: PermissionRequest | None = None
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
        permission_request: PermissionRequest | None = None,
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

OperatingMode = Literal["story_execution", "ai_augmented", "interactive_agent"]

_STORY_EXECUTION: OperatingMode = "story_execution"
_AI_AUGMENTED: OperatingMode = "ai_augmented"
_INTERACTIVE_AGENT: OperatingMode = "interactive_agent"

_KNOWN_MODES: frozenset[str] = frozenset(
    {_STORY_EXECUTION, _AI_AUGMENTED, _INTERACTIVE_AGENT}
)


def _extract_operating_mode(event: HookEvent) -> OperatingMode:
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
    - In ``story_execution`` mode, creates a PermissionRequest for unknown
      permissions instead of asking the human interactively.
    - In ``ai_augmented`` / ``interactive_agent`` mode, returns
      ``unknown_permission`` so the adapter can show a host dialog.

    Args:
        rules_dir: Path to the CCAG rules directory.
            Defaults to ``.agentkit/ccag/rules/`` relative to CWD.
        lease_store: Pre-built :class:`PermissionLeaseStore`.  When
            ``None``, leases are not checked (no lease support).
        request_store: Pre-built :class:`PermissionRequestStore`.  When
            ``None``, requests are created but not persisted.
        request_db_path: Path to the SQLite DB for permission requests.
            Used only when ``request_store`` is ``None``.  Defaults to a
            file next to the rules directory.
    """

    def __init__(
        self,
        *,
        rules_dir: Path | str | None = None,
        lease_store: PermissionLeaseStore | None = None,
        request_store: PermissionRequestStore | None = None,
        request_db_path: Path | None = None,
        request_ttl_s: int = DEFAULT_TTL_SECONDS,
    ) -> None:
        self._rules_dir = Path(rules_dir) if rules_dir is not None else None
        self._lease_store = lease_store
        self._request_store = request_store
        self._request_db_path = request_db_path
        # FK-93 §93.5a / AG3-086: the permission-request TTL is the typed config
        # value (``permissions.request_ttl_s``, default 1800). Injected as a plain
        # int by the runner edge; the runtime never imports config.
        self._request_ttl_s = request_ttl_s

    def _get_request_store(self) -> PermissionRequestStore:
        """Return or lazily create the PermissionRequestStore."""
        if self._request_store is not None:
            return self._request_store
        # Lazy default: sibling DB next to rules dir
        if self._request_db_path is not None:
            db_path = self._request_db_path
        elif self._rules_dir is not None:
            db_path = self._rules_dir.parent / "ccag_requests.db"
        else:
            db_path = Path.cwd() / ".agentkit" / "ccag" / "ccag_requests.db"
        self._request_store = PermissionRequestStore(db_path)
        return self._request_store

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
        operating_mode: OperatingMode,
        hook_event: HookEvent,
    ) -> CcagDecision:
        """Handle the no-match case per operating mode (FK-42 §42.2.5).

        In ``story_execution`` mode: create a PermissionRequest in the
        state-backend (blocks the call deterministically).
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
            req = self._create_permission_request(
                tool_name=tool_name,
                tool_input=tool_input,
                hook_event=hook_event,
            )
            return CcagDecision.unknown(
                tool_name=tool_name,
                operating_mode=operating_mode,
                permission_request=req,
            )

        # ai_augmented / interactive_agent: no request created, caller
        # is responsible for showing a host prompt dialog
        return CcagDecision.unknown(
            tool_name=tool_name,
            operating_mode=operating_mode,
        )

    def open_permission_request(self, hook_event: HookEvent) -> PermissionRequest:
        """Open + persist a permission request for an unknown permission.

        FK-55 §55.6.1 / formal ``principal-capabilities.command.open-permission-
        request``: in ``story_execution`` mode a tool call may never hang on a
        native host prompt — the hook blocks and emits an auditable
        ``permission_request_opened`` instead. This is the surface the capability
        runner calls when its locally-derived execution mode is
        ``story_execution`` and the operation is an UNKNOWN_PERMISSION (or an
        UNRESOLVED non-actionable event inside a run). Request ownership stays
        here (the single owner of permission requests), not in the runner.

        Args:
            hook_event: The harness-neutral hook event whose permission is open.

        Returns:
            The created + persisted :class:`PermissionRequest`.
        """
        return self._create_permission_request(
            tool_name=self._tool_name_from_event(hook_event),
            tool_input=dict(hook_event.operation_args),
            hook_event=hook_event,
        )

    def _create_permission_request(
        self,
        *,
        tool_name: str,
        tool_input: dict[str, object],
        hook_event: HookEvent,
    ) -> PermissionRequest:
        """Create and persist a PermissionRequest in the state-backend.

        Args:
            tool_name: The tool name.
            tool_input: The tool input dict.
            hook_event: The original hook event for context.

        Returns:
            The created :class:`PermissionRequest`.
        """
        fingerprint = " ".join(f"{k}:{v}" for k, v in tool_input.items())
        request_id = str(uuid.uuid4())
        store = self._get_request_store()
        return store.create(
            request_id=request_id,
            tool_name=tool_name,
            tool_input_fingerprint=fingerprint[:512],  # truncate for storage
            story_id=str(hook_event.session_id or ""),
            run_id=str(hook_event.session_id or ""),
            operating_mode="story_execution",
            ttl_seconds=self._request_ttl_s,
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
    "CcagPermissionRuntime",
    "OperatingMode",
    "_STORY_EXECUTION",
    "_AI_AUGMENTED",
    "_INTERACTIVE_AGENT",
]
