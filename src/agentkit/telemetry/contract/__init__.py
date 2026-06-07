"""Telemetry contract boundary module.

Re-exports the FK-68 §68.4/68.9/68.10 telemetry-contract surface: the formal
rules repository (``TelemetryContract``), the preflight-stream sentinel, the
shared rule-result models and the run-scoped event-reader port.

AC8 import boundary: this package imports only from ``agentkit.core_types``,
``agentkit.telemetry`` and ``agentkit.artifacts``.
"""

from __future__ import annotations

from agentkit.telemetry.contract.ports import ExecutionEventReader
from agentkit.telemetry.contract.preflight_sentinel import (
    PREFLIGHT_BALANCE_RULE_ID,
    PreflightSentinel,
)
from agentkit.telemetry.contract.results import (
    ContractRuleResult,
    ContractStatus,
    TelemetryScope,
)
from agentkit.telemetry.contract.telemetry_contract import (
    ContractCheckResult,
    TelemetryContract,
)

__all__ = [
    "PREFLIGHT_BALANCE_RULE_ID",
    "ContractCheckResult",
    "ContractRuleResult",
    "ContractStatus",
    "ExecutionEventReader",
    "PreflightSentinel",
    "TelemetryContract",
    "TelemetryScope",
]
