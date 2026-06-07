"""TelemetryContract: formal telemetry-completeness rules (FK-68 §68.4/68.9/68.10).

Formal-rules repository designed to be consumed by the Integrity-Gate (Dim
"telemetry compliance", FK-68 §68.10): it checks whether a run's telemetry is
concept-conformant and complete. The rules read the canonical
``execution_events`` stream (FK-68 §68.4 evaluates proofs against that stream,
NOT an FK-69 read-model) via an injected ``ExecutionEventReader``.

Scope (AG3-037): this module is the consumable *surface* — the rules, the
preflight sentinel and the payload validator are fully functional and tested.
The actual Integrity-Gate Dim 8 wiring (FK-68 §68.10) and the active production
emitters are an explicit follow-up story (story §2.2), each with its own blast
radius into ``governance/integrity_gate`` and the owning BCs.

Rules (story §2.1.1):
- ``check_agent_start_end_pairing`` — exactly-one ``agent_start`` paired with
  exactly-one ``agent_end`` (FK-68 §68.4 crash detection).
- ``check_review_compliant_coverage`` — every required reviewer role produced a
  ``review_request`` AND ``review_compliant`` count strictly equals
  ``review_request`` count (FK-68 §68.4: "Jeder review_request muss ein
  review_compliant haben" — strict, no overcount).
- ``check_preflight_compliant_balance`` — preflight stream fail-closed rule
  (FK-68 §68.9.3 / §68.10.2); delegated to the preflight sentinel. On violation
  the injected emitter persists a ``preflight_compliance_violation`` event.
- ``check_llm_call_role_coverage`` — for every configured role→pool mapping
  (``llm_roles``) there is at least one ``llm_call`` whose payload carries the
  associated ``pool`` value (FK-68 §68.4: checked against the configured pool,
  not a self-reported role).

This module imports only from ``agentkit.core_types`` and ``agentkit.telemetry``
(AC8 import boundary).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from pydantic import BaseModel, ConfigDict

from agentkit.telemetry.contract.preflight_sentinel import PreflightSentinel
from agentkit.telemetry.contract.results import (
    ContractRuleResult,
    ContractStatus,
    TelemetryScope,
    rule_fail,
    rule_pass,
)
from agentkit.telemetry.events import EventType

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping

    from agentkit.telemetry.contract.ports import ExecutionEventReader
    from agentkit.telemetry.contract.records import ExecutionEventRecord
    from agentkit.telemetry.emitters import EventEmitter


class ContractCheckResult(BaseModel):
    """Aggregate of all telemetry-contract rule results for a run.

    Attributes:
        run_id: The run that was checked.
        rule_results: One ``ContractRuleResult`` per rule, in evaluation order.
    """

    model_config = ConfigDict(frozen=True)

    run_id: str
    rule_results: tuple[ContractRuleResult, ...]

    @property
    def passed(self) -> bool:
        """Return ``True`` iff every rule passed (fail-closed aggregate)."""
        return all(r.status is ContractStatus.PASS for r in self.rule_results)

    @property
    def failures(self) -> tuple[ContractRuleResult, ...]:
        """Return the failing rule results (empty when fully compliant)."""
        return tuple(r for r in self.rule_results if r.status is ContractStatus.FAIL)


# Rule IDs (FK-68 references — single source of truth for the rule_id strings).
_RULE_AGENT_PAIRING = "FK-68 §68.4.1"
_RULE_REVIEW_COVERAGE = "FK-68 §68.4.2"
_RULE_LLM_ROLE_COVERAGE = "FK-68 §68.4.3"
#: Fail-closed guard: the run under check must match the bound authoritative
#: scope, so a persisted preflight violation is attributed correctly.
_RULE_PREFLIGHT_SCOPE = "FK-68 §68.9.4"


class TelemetryContract:
    """Formal telemetry-completeness rules for one run (FK-68 §68.4/68.9/68.10).

    Args:
        event_reader: Run-scoped reader over the canonical ``execution_events``
            stream (FK-68 §68.4 evaluates against this stream). The Integrity-
            Gate wires the ``ProjectionAccessor``-side reader adapter here.
        emitter: Telemetry emitter used to persist a
            ``preflight_compliance_violation`` event when the preflight rule is
            violated (FK-68 §68.9.3). Required on the production entrypoint so an
            imbalance is never silently suppressed (NO ERROR BYPASSING). Tests
            that exercise the rule in isolation may pass a ``MemoryEmitter``.
        scope: Authoritative run scope (project/story/run) this contract
            instance checks (FK-68 §68.9 / FK-33 §33.3.2). It is the single
            source of truth for attributing a persisted
            ``preflight_compliance_violation`` — crucially when the event stream
            is EMPTY (no preflight at all), where there is no event to derive the
            scope from and the storage path would otherwise drop the audit event.
    """

    def __init__(
        self,
        event_reader: ExecutionEventReader,
        emitter: EventEmitter,
        scope: TelemetryScope,
    ) -> None:
        self._reader = event_reader
        self._emitter = emitter
        self._scope = scope
        self._sentinel = PreflightSentinel()

    def check_agent_start_end_pairing(self, run_id: str) -> ContractRuleResult:
        """Verify exactly one ``agent_start`` is paired with one ``agent_end``.

        FK-68 §68.4 crash-detection: a worker must have started AND ended
        regularly. A missing/unbalanced pair is a FAIL (crash or never started).

        Args:
            run_id: The run to check.

        Returns:
            The rule result.
        """
        events = self._reader.read_run_events(run_id)
        starts = _count(events, EventType.AGENT_START)
        ends = _count(events, EventType.AGENT_END)
        if starts == 1 and ends == 1:
            return rule_pass(
                _RULE_AGENT_PAIRING,
                "agent_start/agent_end paired exactly once",
            )
        return rule_fail(
            _RULE_AGENT_PAIRING,
            f"agent_start/agent_end pairing broken: "
            f"agent_start={starts}, agent_end={ends} (expected 1/1)",
        )

    def check_review_compliant_coverage(
        self, run_id: str, required_roles: set[str]
    ) -> ContractRuleResult:
        """Verify review compliance per required reviewer role (FK-68 §68.4).

        Every required reviewer role must have produced at least one
        ``review_request``, and the run's ``review_compliant`` count must equal
        the ``review_request`` count exactly. FK-68 §68.4 mandates "Jeder
        review_request muss ein review_compliant haben" — a strict one-to-one
        pairing. An overcount (extra/malformed ``review_compliant`` events) is a
        violation, not a pass (NO ERROR BYPASSING): the count must match, not
        merely meet a lower bound.

        Args:
            run_id: The run to check.
            required_roles: The configured mandatory reviewer roles.

        Returns:
            The rule result.
        """
        events = self._reader.read_run_events(run_id)
        requests = _by_type(events, EventType.REVIEW_REQUEST)
        compliant_count = _count(events, EventType.REVIEW_COMPLIANT)
        present_roles = _roles(requests)
        missing_roles = sorted(required_roles - present_roles)
        if missing_roles:
            return rule_fail(
                _RULE_REVIEW_COVERAGE,
                f"review_request missing for required role(s): "
                f"{', '.join(missing_roles)}",
            )
        if compliant_count != len(requests):
            return rule_fail(
                _RULE_REVIEW_COVERAGE,
                f"review_compliant ({compliant_count}) must equal "
                f"review_request ({len(requests)}) exactly (FK-68 §68.4)",
            )
        return rule_pass(
            _RULE_REVIEW_COVERAGE,
            f"all required reviewer roles covered; review_compliant "
            f"({compliant_count}) == review_request ({len(requests)})",
        )

    def check_preflight_compliant_balance(self, run_id: str) -> ContractRuleResult:
        """Verify the preflight-stream fail-closed rule (FK-68 §68.9.3 / §68.10.2).

        Delegates to the preflight sentinel: ``preflight_request >= 1`` and
        ``preflight_response == preflight_compliant == preflight_request``. On
        violation the sentinel returns a FAIL with ``rule_id="FK-68 §68.9.2"``
        and the injected emitter persists a ``preflight_compliance_violation``
        event (FK-68 §68.9.3 — no silent suppression on the production path).

        Args:
            run_id: The run to check. MUST match the authoritative scope bound
                at construction (fail-closed: a mismatched run would persist the
                violation under the wrong scope).

        Returns:
            The rule result from the preflight sentinel.
        """
        if run_id != self._scope.run_id:
            return rule_fail(
                _RULE_PREFLIGHT_SCOPE,
                f"run_id {run_id!r} does not match the contract's authoritative "
                f"scope run_id {self._scope.run_id!r} (FK-68 §68.9 / FK-33 "
                "§33.3.2: the violation must be attributed to the bound run)",
            )
        events = self._reader.read_run_events(run_id)
        return self._sentinel.check_balance(
            events, emitter=self._emitter, scope=self._scope
        )

    def check_llm_call_role_coverage(
        self, run_id: str, required_role_pools: Mapping[str, str]
    ) -> ContractRuleResult:
        """Verify each configured role has an ``llm_call`` with its pool (FK-68 §68.4).

        FK-68 §68.4: "Das Integrity-Gate liest ``llm_roles`` aus der
        Pipeline-Config und prüft, ob für jede konfigurierte Rolle mindestens
        ein ``llm_call``-Event mit dem zugeordneten ``pool``-Wert in der
        Telemetrie vorliegt." The check is therefore against the configured
        role→pool contract: an ``llm_call`` must carry ``payload["pool"]`` equal
        to the pool the role is mapped to. A self-reported ``payload["role"]``
        alone is NOT accepted (NO ERROR BYPASSING) — the pool is authoritative.

        Args:
            run_id: The run to check.
            required_role_pools: Mapping of configured mandatory role to its
                assigned pool (the relevant slice of ``llm_roles``).

        Returns:
            The rule result.
        """
        events = self._reader.read_run_events(run_id)
        calls = _by_type(events, EventType.LLM_CALL)
        present_pools = _pools(calls)
        missing = sorted(
            f"{role}->{pool}"
            for role, pool in required_role_pools.items()
            if pool not in present_pools
        )
        if missing:
            return rule_fail(
                _RULE_LLM_ROLE_COVERAGE,
                f"llm_call missing for required role->pool: {', '.join(missing)}",
            )
        return rule_pass(
            _RULE_LLM_ROLE_COVERAGE,
            f"all required LLM role->pool pairs covered "
            f"({len(required_role_pools)} role(s))",
        )

    def check_all(
        self,
        run_id: str,
        required_review_roles: set[str],
        required_llm_role_pools: Mapping[str, str],
    ) -> ContractCheckResult:
        """Run every contract rule and aggregate the results.

        Args:
            run_id: The run to check.
            required_review_roles: Configured mandatory reviewer roles.
            required_llm_role_pools: Configured mandatory LLM role→pool mapping
                (the relevant slice of ``llm_roles``); each pool must be backed
                by an ``llm_call`` carrying that pool (FK-68 §68.4).

        Returns:
            The aggregate ``ContractCheckResult``.
        """
        return ContractCheckResult(
            run_id=run_id,
            rule_results=(
                self.check_agent_start_end_pairing(run_id),
                self.check_review_compliant_coverage(run_id, required_review_roles),
                self.check_preflight_compliant_balance(run_id),
                self.check_llm_call_role_coverage(run_id, required_llm_role_pools),
            ),
        )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _by_type(
    events: Iterable[ExecutionEventRecord], event_type: EventType
) -> list[ExecutionEventRecord]:
    return [e for e in events if e.event_type == event_type.value]


def _count(events: Iterable[ExecutionEventRecord], event_type: EventType) -> int:
    return sum(1 for e in events if e.event_type == event_type.value)


def _roles(events: Iterable[ExecutionEventRecord]) -> set[str]:
    roles: set[str] = set()
    for event in events:
        role = event.payload.get("role")
        if isinstance(role, str):
            roles.add(role)
    return roles


def _pools(events: Iterable[ExecutionEventRecord]) -> set[str]:
    pools: set[str] = set()
    for event in events:
        pool = event.payload.get("pool")
        if isinstance(pool, str):
            pools.add(pool)
    return pools


__all__ = [
    "ContractCheckResult",
    "ContractRuleResult",
    "ContractStatus",
    "TelemetryContract",
]
