"""Runtime ports the risk-window sensor layer depends on (telemetry-internal).

The ``EventNormalizer`` writes ``NormalizedEvent``s into the FK-68 §68.8 rolling
window. The concrete persistence is injected through ``RiskWindowWriter`` so the
``risk_window`` module stays free of state-backend imports (AC8 import boundary:
only ``core_types`` / ``telemetry`` / ``artifacts``).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from agentkit.telemetry.risk_window.normalized_event import NormalizedEvent


@runtime_checkable
class RiskWindowWriter(Protocol):
    """Write boundary for the FK-68 §68.8 governance risk window.

    The canonical adapter is the ``ProjectionAccessor`` (FK-68 §68.8.0: the
    sensor layer writes ``NormalizedEvent``s via the accessor). Injected as a
    Protocol so the risk-window module imports no concrete DB implementation.
    """

    def record_risk_window_event(self, event: NormalizedEvent) -> None:
        """Persist one normalized event into the rolling risk window.

        Args:
            event: The normalized event to append (append-only).
        """
        ...


__all__ = ["RiskWindowWriter"]
