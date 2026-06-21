"""Shared result models for telemetry-contract rules (FK-68 §68.4/68.9/68.10).

Extracted into a leaf module so both ``telemetry_contract`` and
``preflight_sentinel`` can depend on the result types without a circular import.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict


class ContractStatus(StrEnum):
    """Outcome of a single telemetry-contract rule.

    Attributes:
        PASS: The rule holds — no action required.
        FAIL: The rule is violated — fail-closed for the Integrity-Gate.
    """

    PASS = "PASS"
    FAIL = "FAIL"


class ContractRuleResult(BaseModel):
    """Result of one telemetry-contract rule.

    Attributes:
        rule_id: Canonical FK reference of the rule (e.g. ``FK-68 §68.4.1``).
        status: ``PASS`` or ``FAIL``.
        detail: Human-readable explanation (always populated).
    """

    model_config = ConfigDict(frozen=True)

    rule_id: str
    status: ContractStatus
    detail: str


class TelemetryScope(BaseModel):
    """Authoritative run scope a telemetry-contract check is bound to.

    FK-68 §68.9 / FK-33 §33.3.2: a ``preflight_compliance_violation`` (and any
    audit fact a rule must persist) carries the authoritative
    ``project_key``/``story_id``/``run_id`` of the run under check — NOT a value
    re-derived from the event stream. The stream may be empty (the most critical
    preflight case: no preflight at all), in which case there is no ``events[0]``
    to read scope from; persisting from a guessed ``story_id="unknown"`` /
    ``run_id=None`` is silently dropped by the storage path (project/run scope
    missing). Binding the authoritative scope at construction closes that gap
    (NO ERROR BYPASSING: the violation is always auditable, even empty-stream).

    Attributes:
        project_key: Authoritative FK-68 project scope key.
        story_id: Authoritative story under check.
        run_id: Authoritative run under check.
    """

    model_config = ConfigDict(frozen=True)

    project_key: str
    story_id: str
    run_id: str


def rule_pass(rule_id: str, detail: str) -> ContractRuleResult:
    """Build a passing ``ContractRuleResult``."""
    return ContractRuleResult(rule_id=rule_id, status=ContractStatus.PASS, detail=detail)


def rule_fail(rule_id: str, detail: str) -> ContractRuleResult:
    """Build a failing ``ContractRuleResult``."""
    return ContractRuleResult(rule_id=rule_id, status=ContractStatus.FAIL, detail=detail)


__all__ = [
    "ContractRuleResult",
    "ContractStatus",
    "TelemetryScope",
    "rule_fail",
    "rule_pass",
]
