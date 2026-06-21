"""Risk-window sensor layer (FK-68 §68.8) for governance observation.

Schema-owner: telemetry-and-events. Normalizes execution events into compact
``NormalizedEvent`` records and writes them into the rolling risk window via the
``ProjectionAccessor`` (the scoring/adjudication lives in governance-and-guards
and is out of scope here).
"""

from __future__ import annotations

from agentkit.backend.telemetry.risk_window.normalized_event import (
    NormalizedEvent,
    RiskCategory,
)
from agentkit.backend.telemetry.risk_window.normalizer import EventNormalizer
from agentkit.backend.telemetry.risk_window.ports import RiskWindowWriter

__all__ = [
    "EventNormalizer",
    "NormalizedEvent",
    "RiskCategory",
    "RiskWindowWriter",
]
