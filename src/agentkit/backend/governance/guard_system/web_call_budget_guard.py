"""WebCallBudgetGuard — the single blocking owner of the web-call budget.

FK-30 §30.5.1a / FK-68 §68.6.0 mandate a STRICT split:

- Telemetry writes the ``web_call`` counter event OBSERVATIONALLY
  (:class:`~agentkit.backend.telemetry.hooks.budget_event_emitter.BudgetEventEmitter`,
  PostToolUse).
- Governance makes the BLOCKING decision here. ``WebCallBudgetGuard`` reads the
  existing web-call counter (projection of ``EventType.WEB_CALL``) and decides
  fail-closed; it writes NO ``web_call`` counter event (that stays with the
  emitter). On a block it emits its OWN governance audit — an
  ``integrity_violation`` with ``guard="web_call_budget_guard"`` and ``detail``,
  WITHOUT ``stage`` (the ``stage`` field is prompt-integrity-specific, FK-61
  §61.12.2 / FK-68 §68.2; FK-68 §68.3.1 lists the guard hooks as
  ``integrity_violation`` emitters on a block / exit 2; FK-30 §30.7.3).

Behaviour (FK-30 §30.5.1a, FAIL-CLOSED):

- Non-web tool -> allow (no budget applies).
- UNRESOLVED story type on a web call (backend fault OR missing record) ->
  fail-closed BLOCK (``story_type_unresolved``) + ``integrity_violation``. An
  active web call whose story type cannot be confirmed is an inconsistent state;
  it must NOT be downgraded to "not research" (AG3-086 migrates the previous
  emitter-owned fail-closed branch here, unchanged in behaviour).
- RESOLVED non-research story -> allow (the hard limit applies only to research
  stories, FK-30 §30.5.1a / FK-68 §68.6.1).
- RESOLVED research story, count below the warning threshold -> allow.
- RESOLVED research story, warning <= count < hard limit -> allow + WARNING
  (SEVERITY-SEMANTIK: a warning is an action item with deferring effect).
- RESOLVED research story, count >= hard limit -> BLOCK + ``integrity_violation``.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING

from agentkit.backend.governance.protocols import GuardVerdict, ViolationType
from agentkit.backend.telemetry.events import Event, EventType

if TYPE_CHECKING:
    from agentkit.backend.telemetry.emitters import EventEmitter

#: Story type that activates the web-call budget (FK-30 §30.5.1a / FK-68 §68.6.1).
_RESEARCH_STORY_TYPE = "research"

#: Default hard limit for research web calls (``telemetry.web_call_limit``).
_DEFAULT_WEB_CALL_LIMIT = 200

#: Default warning threshold for research web calls (``telemetry.web_call_warning``).
_DEFAULT_WEB_CALL_WARNING = 180

#: Tool names that count as a web call (FK-68 §68.6.1).
_WEB_TOOLS = frozenset({"WebFetch", "WebSearch"})

#: Guard identifier surfaced on the verdict and in the ``integrity_violation``
#: ``guard`` field (FK-30 §30.5.1a wortgleich).
GUARD_NAME = "web_call_budget_guard"


class BudgetSeverity(StrEnum):
    """Severity of a :class:`WebCallBudgetDecision` (CLAUDE.md SEVERITY-SEMANTIK)."""

    PASS = "pass"
    WARNING = "warning"
    ERROR = "error"


@dataclass(frozen=True)
class WebCallBudgetObservation:
    """Typed harness-neutral input for :meth:`WebCallBudgetGuard.evaluate`.

    Attributes:
        story_id: Active story identifier (counter projection key).
        run_id: Active run identifier (audit correlation).
        project_key: Owning project key (audit correlation).
        tool: The observed tool name (e.g. ``"WebFetch"``).
        story_type: The authoritative story-type string; only meaningful when
            ``story_type_resolved`` is ``True``.
        story_type_resolved: Whether the authoritative story type was RESOLVED
            (store read + record found). ``False`` is the UNRESOLVED state
            (backend fault OR missing record) the guard fail-closes on.
        phase: Pipeline phase name, when known (carried onto the audit event).
    """

    story_id: str
    run_id: str
    project_key: str
    tool: str
    story_type: str = ""
    story_type_resolved: bool = True
    phase: str | None = None


@dataclass(frozen=True)
class WebCallBudgetDecision:
    """Outcome of a :meth:`WebCallBudgetGuard.evaluate` call.

    Attributes:
        verdict: The blocking / allowing :class:`GuardVerdict`.
        severity: PASS / WARNING / ERROR (SEVERITY-SEMANTIK). WARNING signals an
            allow at/above the warning threshold that must be mirrored.
        audit_events: The ``integrity_violation`` audit events to persist (empty
            on allow; never the observational ``web_call`` counter event).
        web_call_count: The projected web-call count INCLUDING the current
            attempt (``0`` when the tool is not a web call).
    """

    verdict: GuardVerdict
    severity: BudgetSeverity
    audit_events: tuple[Event, ...] = ()
    web_call_count: int = 0


class WebCallBudgetGuard:
    """The single blocking owner of the research web-call budget (FK-30 §30.5.1a).

    Reads the existing web-call counter via the canonical
    :class:`~agentkit.backend.telemetry.emitters.EventEmitter` projection and decides
    fail-closed. It writes NO ``web_call`` counter event (telemetry owns that);
    on a block it emits its own ``integrity_violation`` governance audit.

    Args:
        emitter: Telemetry emitter used to (a) project the prior ``web_call``
            counter and (b) persist the ``integrity_violation`` block audit. The
            same canonical emitter the observational
            :class:`~agentkit.backend.telemetry.hooks.budget_event_emitter.BudgetEventEmitter`
            writes through (single counter truth — no second source).
        web_call_limit: Hard limit for research web calls
            (``telemetry.web_call_limit``, default 200). Injected as a plain
            value (no config import inside the guard).
        web_call_warning: Warning threshold (``telemetry.web_call_warning``,
            default 180). Must be below ``web_call_limit``.
    """

    name = GUARD_NAME

    def __init__(
        self,
        emitter: EventEmitter,
        *,
        web_call_limit: int = _DEFAULT_WEB_CALL_LIMIT,
        web_call_warning: int = _DEFAULT_WEB_CALL_WARNING,
    ) -> None:
        self._emitter = emitter
        self._web_call_limit = web_call_limit
        self._web_call_warning = web_call_warning

    def evaluate(self, observation: WebCallBudgetObservation) -> WebCallBudgetDecision:
        """Decide whether a web call is within budget (FK-30 §30.5.1a).

        Args:
            observation: The harness-neutral budget observation.

        Returns:
            A :class:`WebCallBudgetDecision` carrying the verdict, severity and
            any ``integrity_violation`` audit events. The decision NEVER carries
            the observational ``web_call`` counter event.
        """
        if observation.tool not in _WEB_TOOLS:
            return WebCallBudgetDecision(
                verdict=GuardVerdict.allow(self.name),
                severity=BudgetSeverity.PASS,
            )

        if not observation.story_type_resolved:
            # Migrated fail-closed branch (was emitter-owned): an UNRESOLVED story
            # type on an active web call is an inconsistent state. We cannot
            # confirm the story is non-research / within budget, so we DENY rather
            # than downgrade an empty story_type to "not research".
            detail = (
                "story_type_unresolved: cannot confirm the active story is "
                "non-research or within budget (backend fault or missing record)"
            )
            verdict = GuardVerdict.block(
                self.name,
                ViolationType.POLICY_VIOLATION,
                detail,
                detail={"story_id": observation.story_id, "tool": observation.tool},
            )
            return WebCallBudgetDecision(
                verdict=verdict,
                severity=BudgetSeverity.ERROR,
                audit_events=(self._integrity_violation(observation, detail),),
            )

        if observation.story_type != _RESEARCH_STORY_TYPE:
            # FK-30 §30.5.1a: the hard limit applies ONLY to RESOLVED research
            # stories. A non-research story is never budget-blocked.
            return WebCallBudgetDecision(
                verdict=GuardVerdict.allow(self.name),
                severity=BudgetSeverity.PASS,
            )

        try:
            prior_calls = len(
                self._emitter.query(observation.story_id, EventType.WEB_CALL)
            )
        except Exception as exc:  # noqa: BLE001 -- enforcement read must fail CLOSED (AC5 / §2.1.4)
            # AG3-129: the web-call counter is read via REST. A core-unreachable /
            # rejected read is NOT "zero events" -- an unverifiable counter is an
            # inconsistent state on an active research web call, so we DENY (never
            # a fail-open allow, never a direct-DB fallback).
            detail = (
                "web_call_counter_unavailable: cannot read the canonical web-call "
                f"counter fail-closed ({exc})"
            )
            verdict = GuardVerdict.block(
                self.name,
                ViolationType.POLICY_VIOLATION,
                detail,
                detail={"story_id": observation.story_id, "tool": observation.tool},
            )
            return WebCallBudgetDecision(
                verdict=verdict,
                severity=BudgetSeverity.ERROR,
                audit_events=(self._integrity_violation(observation, detail),),
            )
        # The current attempt is the (prior_calls + 1)-th web call.
        current_count = prior_calls + 1

        if current_count >= self._web_call_limit:
            detail = (
                f"web_call_budget_exceeded: {current_count} >= "
                f"{self._web_call_limit}"
            )
            verdict = GuardVerdict.block(
                self.name,
                ViolationType.POLICY_VIOLATION,
                detail,
                detail={
                    "story_id": observation.story_id,
                    "web_call_count": current_count,
                    "web_call_limit": self._web_call_limit,
                },
            )
            return WebCallBudgetDecision(
                verdict=verdict,
                severity=BudgetSeverity.ERROR,
                audit_events=(self._integrity_violation(observation, detail),),
                web_call_count=current_count,
            )

        if current_count >= self._web_call_warning:
            # SEVERITY-SEMANTIK: allow, but flag a WARNING for mirroring. No
            # block, no integrity_violation (that is reserved for exit-2 blocks).
            return WebCallBudgetDecision(
                verdict=GuardVerdict.allow(self.name),
                severity=BudgetSeverity.WARNING,
                web_call_count=current_count,
            )

        return WebCallBudgetDecision(
            verdict=GuardVerdict.allow(self.name),
            severity=BudgetSeverity.PASS,
            web_call_count=current_count,
        )

    def evaluate_and_emit(
        self, observation: WebCallBudgetObservation
    ) -> WebCallBudgetDecision:
        """Evaluate and persist any ``integrity_violation`` audit events.

        Args:
            observation: The harness-neutral budget observation.

        Returns:
            The :class:`WebCallBudgetDecision`. Its ``audit_events`` have already
            been emitted through the canonical telemetry emitter.
        """
        decision = self.evaluate(observation)
        for event in decision.audit_events:
            self._emitter.emit(event)
        return decision

    def _integrity_violation(
        self, observation: WebCallBudgetObservation, detail: str
    ) -> Event:
        """Build the ``integrity_violation`` block audit (FK-68 §68.3.1).

        The payload carries ``guard``/``detail`` (mandatory for every
        ``integrity_violation``) and NO ``stage`` (prompt-integrity-specific,
        FK-61 §61.12.2). This is NOT the observational ``web_call`` counter event
        (that stays with the emitter, FK-30 §30.5.1a).
        """
        return Event(
            story_id=observation.story_id,
            event_type=EventType.INTEGRITY_VIOLATION,
            project_key=observation.project_key,
            run_id=observation.run_id,
            phase=observation.phase,
            source_component=self.name,
            severity="error",
            payload={"guard": self.name, "detail": detail},
        )


__all__ = [
    "GUARD_NAME",
    "BudgetSeverity",
    "WebCallBudgetDecision",
    "WebCallBudgetGuard",
    "WebCallBudgetObservation",
]
