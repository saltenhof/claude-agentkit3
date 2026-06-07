"""NormalizedEvent + RiskCategory for the FK-68 §68.8 governance risk window.

The Risk-Window is the FK-68 §68.8 sensor-layer read-model owned by
telemetry-and-events: ``ExecutionEventRecord``s are reduced to a small set of
risk dimensions (``RiskCategory``) and persisted into a rolling window that the
(out-of-scope) ``GovernanceObserver`` later scores (FK-68 §68.8.0).

Schema-owner: telemetry-and-events (FK-68 §68.8.0). This module imports only
from ``agentkit.core_types`` and ``agentkit.telemetry`` (AC8 import boundary).
"""

from __future__ import annotations

from datetime import datetime  # noqa: TC003 -- Pydantic needs the runtime type
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from agentkit.core_types import Severity
from agentkit.telemetry.events import EventType


class RiskCategory(StrEnum):
    """Coarse governance risk dimension a normalized event maps onto.

    FK-68 §68.8 reduces the full ``EventType`` catalogue to a handful of risk
    dimensions the governance observer accumulates over its rolling window.

    Attributes:
        SECURITY: Secret/credential or governance-file class signals.
        INTEGRITY: Guard violations and review divergence (trust erosion).
        OPERATIONAL: Worker lifecycle and flow-runtime signals.
        BUDGET: Resource-budget signals (e.g. web-call budget in research).
    """

    SECURITY = "security"
    INTEGRITY = "integrity"
    OPERATIONAL = "operational"
    BUDGET = "budget"


class NormalizedEvent(BaseModel):
    """Normalized form of an ``ExecutionEventRecord`` for the risk window.

    Reduces the variety of ``EventType`` to a small set of risk dimensions so
    the governance observer can accumulate a rolling risk score without coupling
    to every concrete event type (FK-68 §68.8.1).

    Attributes:
        event_id: The source ``ExecutionEventRecord.event_id`` (correlation).
        story_id: Story the event belongs to.
        run_id: Run the event belongs to.
        risk_category: Coarse risk dimension this event maps onto.
        severity: Finding severity on the canonical ``Severity`` triad.
        observed_at: Business instant the source event occurred at.
        source_event_type: The originating ``EventType``.
        payload_excerpt: A small, JSON-safe excerpt of the source payload kept
            for human/audit context (NOT the full payload).
    """

    model_config = ConfigDict(frozen=True)

    event_id: str
    story_id: str
    run_id: str
    risk_category: RiskCategory
    severity: Severity
    observed_at: datetime
    source_event_type: EventType
    payload_excerpt: dict[str, Any] = Field(default_factory=dict)


__all__ = ["NormalizedEvent", "RiskCategory"]
