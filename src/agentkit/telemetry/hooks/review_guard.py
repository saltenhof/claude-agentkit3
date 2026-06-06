"""ReviewGuard: double-role hook + guard enforcing mandatory reviewer coverage.

FK-68 §68.3.1: ReviewGuard is the canonical double-role surface -- it is both a
telemetry hook (emitting ``review_guard_intervention``) AND a governance guard
(returning a :class:`~agentkit.governance.protocols.GuardVerdict`). The story
(AG3-036 §2.1.5) mandates this double role as concept-conformant.

Behaviour (FAIL-CLOSED, AG3-036 AC5):
- On a PreToolUse ``git commit`` it checks that every mandatory reviewer role has
  a ``review_compliant`` event since the last ``increment_commit``.
- If any required role is missing -> ``GuardVerdict.DENY`` with
  ``message="review_not_compliant: missing roles ..."`` AND a
  ``review_guard_intervention`` event.
- If all roles are covered -> ``GuardVerdict.allow`` and no intervention event.

``required_roles`` is injected (constructor), NOT read from a config BC: the AC10
import boundary forbids the telemetry hooks from importing config / pipeline_config.
The composition root / runner passes the configured roles in. Empty
``required_roles`` means "no mandatory reviewer coverage configured" -> allow.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from agentkit.governance.protocols import GuardVerdict, ViolationType
from agentkit.telemetry.events import Event, EventType
from agentkit.telemetry.hooks.base import (
    EmittingHook,
    HookContext,
    HookResult,
    HookTrigger,
)
from agentkit.telemetry.hooks.commit_hook import _GIT_COMMIT_PATTERN

if TYPE_CHECKING:
    from agentkit.telemetry.emitters import EventEmitter


class ReviewGuard(EmittingHook):
    """Enforces mandatory reviewer coverage per increment (FK-68 §68.3.1)."""

    name = "review_guard"

    def __init__(
        self,
        emitter: EventEmitter,
        *,
        required_roles: tuple[str, ...],
    ) -> None:
        """Initialise with the emitter and the mandatory reviewer roles.

        Args:
            emitter: Telemetry emitter for persistence and querying review
                events (FK-68 §68.3.4 / §68.3.5).
            required_roles: The reviewer roles that MUST be covered per
                increment (``pipeline_config.review.required_roles``), injected
                as plain values to honour the AC10 import boundary.
        """
        super().__init__(emitter)
        self._required_roles = tuple(required_roles)

    def evaluate(self, context: HookContext) -> HookResult:
        """Decide on the commit and emit an intervention event on a violation.

        Args:
            context: The harness-neutral observation.

        Returns:
            A :class:`HookResult`. When the commit is denied, ``verdict`` is a
            DENY and ``events`` carries the ``review_guard_intervention`` event;
            otherwise ``verdict`` is an allow and no event is emitted.
        """
        if not self._is_pre_commit(context):
            return HookResult.skipped()

        missing = self._missing_roles(context)
        if not missing:
            return HookResult(
                triggered=True,
                verdict=GuardVerdict.allow(self.name),
            )

        missing_csv = ", ".join(missing)
        reason = f"review_not_compliant: missing roles {missing_csv}"
        verdict = GuardVerdict.block(
            self.name,
            ViolationType.POLICY_VIOLATION,
            reason,
            detail={
                "missing_roles": list(missing),
                "required_roles": list(self._required_roles),
                "story_id": context.story_id,
            },
        )
        event = Event(
            story_id=context.story_id,
            event_type=EventType.REVIEW_GUARD_INTERVENTION,
            project_key=context.project_key,
            run_id=context.run_id,
            phase=context.phase,
            source_component=self.name,
            severity="error",
            payload={
                "story_id": context.story_id,
                "run_id": context.run_id,
                "missing_roles": list(missing),
                "required_roles": list(self._required_roles),
                "reason": reason,
            },
        )
        return HookResult.emitting((event,), verdict=verdict)

    @staticmethod
    def _is_pre_commit(context: HookContext) -> bool:
        return (
            context.trigger is HookTrigger.PRE_TOOL_USE
            and context.tool == "Bash"
            and bool(_GIT_COMMIT_PATTERN.search(context.command))
        )

    def _missing_roles(self, context: HookContext) -> tuple[str, ...]:
        """Return the required roles lacking a ``review_compliant`` since last commit.

        Reads the canonical execution events (FK-68 §68.3.5) for this story:
        finds the timestamp of the latest ``increment_commit`` and collects the
        reviewer roles whose ``review_compliant`` event occurred after it.

        Args:
            context: The observation identifying the story.

        Returns:
            The mandatory roles that are NOT covered (empty when all covered).
        """
        if not self._required_roles:
            return ()

        commits = self._emitter.query(
            context.story_id, EventType.INCREMENT_COMMIT
        )
        last_commit_ts = max((c.timestamp for c in commits), default=None)

        compliant = self._emitter.query(
            context.story_id, EventType.REVIEW_COMPLIANT
        )
        covered_roles = {
            role
            for event in compliant
            if (last_commit_ts is None or event.timestamp > last_commit_ts)
            and (role := _reviewer_role(event))
        }
        return tuple(
            role for role in self._required_roles if role not in covered_roles
        )


def _reviewer_role(event: Event) -> str:
    """Extract the reviewer role from a ``review_compliant`` event payload.

    Args:
        event: A ``review_compliant`` event.

    Returns:
        The reviewer-role string, or ``""`` when absent.
    """
    role = event.payload.get("reviewer_role")
    return role if isinstance(role, str) else ""


__all__ = ["ReviewGuard"]
