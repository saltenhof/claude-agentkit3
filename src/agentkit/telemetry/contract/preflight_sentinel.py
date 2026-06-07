"""Preflight-telemetry-stream sentinel (FK-68 §68.9).

The preflight stream is an independent telemetry stream that runs parallel to
the review stream (FK-68 §68.9.1). It carries its own counter set and MUST NOT
disturb the review invariants (FK-68 §68.10.1).

This sentinel implements the FK-68 §68.9.3 / §68.10.2 fail-closed rule:

    count(preflight_request) >= 1
    AND count(preflight_response) == count(preflight_request)
    AND count(preflight_compliant) == count(preflight_request)

Preflight is mandatory (FK-68 §68.9.3). An empty preflight stream is therefore a
violation (FK-68 failure code ``PREFLIGHT_MISSING``), NOT a pass. A count
mismatch is a violation (FK-68 failure code ``PREFLIGHT_NOT_COMPLIANT``). On any
violation the rule FAILs with ``rule_id="FK-68 §68.9.2"`` and produces a
``preflight_compliance_violation`` event so the violation is itself auditable.

Imports only from ``agentkit.telemetry`` (AC8 import boundary).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from agentkit.telemetry.contract.results import (
    ContractRuleResult,
    TelemetryScope,
    rule_fail,
    rule_pass,
)
from agentkit.telemetry.events import Event, EventType

if TYPE_CHECKING:
    from collections.abc import Iterable

    from agentkit.telemetry.contract.records import ExecutionEventRecord
    from agentkit.telemetry.emitters import EventEmitter

#: Canonical FK-68 §68.9.2 rule id for the preflight balance constraint.
PREFLIGHT_BALANCE_RULE_ID = "FK-68 §68.9.2"

#: FK-68 §68.9.3 failure code: preflight is mandatory but no request was found.
PREFLIGHT_MISSING = "PREFLIGHT_MISSING"

#: FK-68 §68.9.3 failure code: preflight request/response/compliant unbalanced.
PREFLIGHT_NOT_COMPLIANT = "PREFLIGHT_NOT_COMPLIANT"


class PreflightSentinel:
    """Isolated preflight-stream compliance check (FK-68 §68.9.3 / §68.10.2).

    The sentinel operates ONLY on the preflight counter set and never touches
    the review-stream invariants (FK-68 §68.10.1: preflight is not a review).

    Preflight is mandatory and fail-closed (FK-68 §68.9.3): a run with no
    preflight request fails (``PREFLIGHT_MISSING``), and a run whose response or
    compliant counts diverge from its request count fails
    (``PREFLIGHT_NOT_COMPLIANT``).
    """

    def check_balance(
        self,
        events: Iterable[ExecutionEventRecord],
        *,
        emitter: EventEmitter | None = None,
        scope: TelemetryScope | None = None,
    ) -> ContractRuleResult:
        """Verify the FK-68 §68.9.3 / §68.10.2 preflight rule (fail-closed).

        Requires ``preflight_request >= 1`` and
        ``preflight_response == preflight_compliant == preflight_request``. On
        any violation the rule FAILs and — when an emitter is supplied — a
        ``preflight_compliance_violation`` event is emitted so the violation is
        auditable in the canonical stream.

        Args:
            events: The run's execution events (preflight + others).
            emitter: Optional telemetry emitter. When provided and the rule is
                violated, a ``preflight_compliance_violation`` event is emitted
                for the offending story.
            scope: Authoritative run scope (project/story/run) the violation is
                attributed to (FK-68 §68.9 / FK-33 §33.3.2). MUST be supplied on
                the production path so the violation is persisted even when the
                stream is EMPTY — the most critical case (no preflight at all),
                where there is no ``events[0]`` to derive scope from and the
                storage path would otherwise drop the audit event (project/run
                scope missing). Without a scope (isolated unit tests) the event
                is attributed best-effort from the stream.

        Returns:
            A ``ContractRuleResult`` with ``rule_id="FK-68 §68.9.2"``.
        """
        materialized = list(events)
        requests = _count(materialized, EventType.PREFLIGHT_REQUEST)
        responses = _count(materialized, EventType.PREFLIGHT_RESPONSE)
        compliant = _count(materialized, EventType.PREFLIGHT_COMPLIANT)

        failure_code = _evaluate(requests, responses, compliant)
        if failure_code is None:
            return rule_pass(
                PREFLIGHT_BALANCE_RULE_ID,
                f"preflight compliant: preflight_request={requests}, "
                f"preflight_response={responses}, preflight_compliant={compliant}",
            )

        if emitter is not None:
            self._emit_violation(
                materialized,
                requests,
                responses,
                compliant,
                failure_code,
                emitter,
                scope,
            )
        return rule_fail(
            PREFLIGHT_BALANCE_RULE_ID,
            f"{failure_code}: preflight_request={requests}, "
            f"preflight_response={responses}, preflight_compliant={compliant} "
            f"(require request>=1 and response==compliant==request)",
        )

    @staticmethod
    def _emit_violation(
        events: list[ExecutionEventRecord],
        requests: int,
        responses: int,
        compliant: int,
        failure_code: str,
        emitter: EventEmitter,
        scope: TelemetryScope | None,
    ) -> None:
        """Emit a ``preflight_compliance_violation`` event for the violation.

        The authoritative ``scope`` (when supplied) is the single source of
        truth for the violation's ``project_key``/``story_id``/``run_id`` so the
        event is persisted even on an empty stream (FK-68 §68.9). Only when no
        scope is bound (isolated unit tests) does the sentinel fall back to the
        first event's attribution.
        """
        if scope is not None:
            project_key: str | None = scope.project_key
            story_id = scope.story_id
            run_id: str | None = scope.run_id
        else:
            project_key = events[0].project_key if events else None
            story_id = events[0].story_id if events else "unknown"
            run_id = events[0].run_id if events else None
        emitter.emit(
            Event(
                story_id=story_id,
                event_type=EventType.PREFLIGHT_COMPLIANCE_VIOLATION,
                source_component="preflight_sentinel",
                severity="error",
                project_key=project_key,
                run_id=run_id,
                payload={
                    "preflight_request": requests,
                    "preflight_response": responses,
                    "preflight_compliant": compliant,
                    "failure_code": failure_code,
                    "rule_id": PREFLIGHT_BALANCE_RULE_ID,
                },
            )
        )


def _evaluate(requests: int, responses: int, compliant: int) -> str | None:
    """Return the FK-68 §68.9.3 failure code, or ``None`` when compliant."""
    if requests == 0:
        return PREFLIGHT_MISSING
    if responses != requests or compliant != requests:
        return PREFLIGHT_NOT_COMPLIANT
    return None


def _count(events: Iterable[ExecutionEventRecord], event_type: EventType) -> int:
    return sum(1 for e in events if e.event_type == event_type.value)


__all__ = [
    "PREFLIGHT_BALANCE_RULE_ID",
    "PREFLIGHT_MISSING",
    "PREFLIGHT_NOT_COMPLIANT",
    "PreflightSentinel",
]
