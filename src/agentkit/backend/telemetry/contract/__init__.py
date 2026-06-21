"""Telemetry contract boundary module.

Re-exports the FK-68 §68.4/68.9/68.10 telemetry-contract surface: the formal
rules repository (``TelemetryContract``), the preflight-stream sentinel, the
shared rule-result models and the run-scoped event-reader port.

AC8 import boundary: this package imports only from ``agentkit.backend.core_types``,
``agentkit.backend.telemetry`` and ``agentkit.backend.artifacts``.
"""

from __future__ import annotations

from agentkit.backend.telemetry.contract.ports import ExecutionEventReader
from agentkit.backend.telemetry.contract.preflight_sentinel import (
    PREFLIGHT_BALANCE_RULE_ID,
    PreflightSentinel,
)
from agentkit.backend.telemetry.contract.results import (
    ContractRuleResult,
    ContractStatus,
    TelemetryScope,
)
from agentkit.backend.telemetry.contract.telemetry_contract import (
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
