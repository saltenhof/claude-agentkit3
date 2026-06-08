"""EventNormalizer: reduces ExecutionEventRecords to NormalizedEvents.

FK-68 §68.8.0 sensor layer: maps each risk-relevant ``ExecutionEventRecord`` to
a coarse ``RiskCategory`` and persists the resulting ``NormalizedEvent`` into the
rolling risk window via an injected ``RiskWindowWriter`` (the
``ProjectionAccessor``). Non-risk-relevant events normalize to ``None`` and are
not written.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from agentkit.core_types import Severity
from agentkit.telemetry.events import EventType
from agentkit.telemetry.risk_window.normalized_event import (
    NormalizedEvent,
    RiskCategory,
)

if TYPE_CHECKING:
    from agentkit.telemetry.contract.records import ExecutionEventRecord
    from agentkit.telemetry.risk_window.ports import RiskWindowWriter


# ---------------------------------------------------------------------------
# EventType -> RiskCategory mapping (FK-68 §68.8, story AC5)
# ---------------------------------------------------------------------------
#
# Only risk-relevant event types appear here. Everything else normalizes to
# ``None`` (not written to the window). The mapping is an explicit table rather
# than a string/flag cascade (WORKFLOW- UND STATE-DISZIPLIN).

_RISK_CATEGORY_BY_EVENT: dict[EventType, RiskCategory] = {
    # Worker / flow lifecycle -> OPERATIONAL
    EventType.AGENT_START: RiskCategory.OPERATIONAL,
    EventType.AGENT_END: RiskCategory.OPERATIONAL,
    # Guard violation + review divergence -> INTEGRITY (trust erosion)
    EventType.INTEGRITY_VIOLATION: RiskCategory.INTEGRITY,
    EventType.REVIEW_DIVERGENCE: RiskCategory.INTEGRITY,
    EventType.REVIEW_GUARD_INTERVENTION: RiskCategory.INTEGRITY,
    # Resource budget -> BUDGET (web access budget, FK-68 §68.4 budget row)
    EventType.WEB_CALL: RiskCategory.BUDGET,
}

# Severity assigned per risk category at normalization time. The governance
# observer (out of scope) accumulates these; integrity guard violations are the
# hard signal, lifecycle/budget are softer.
_SEVERITY_BY_CATEGORY: dict[RiskCategory, Severity] = {
    RiskCategory.SECURITY: Severity.BLOCKING,
    RiskCategory.INTEGRITY: Severity.MAJOR,
    RiskCategory.OPERATIONAL: Severity.MINOR,
    RiskCategory.BUDGET: Severity.MINOR,
}

# Payload keys preserved in the excerpt (small, JSON-safe context for audit).
_EXCERPT_KEYS: tuple[str, ...] = (
    "guard",
    "detail",
    "stage",
    "reviewer_a",
    "reviewer_b",
    "divergent",
    "quorum_triggered",
    "final_verdict",
    "pool",
    "role",
    "subagent_type",
)


class EventNormalizer:
    """Normalizes execution events into the FK-68 §68.8 risk window.

    Args:
        risk_window_writer: Optional write boundary (the ``ProjectionAccessor``).
            When provided, :meth:`normalize_and_record` persists each produced
            ``NormalizedEvent``. When ``None``, only pure normalization is
            available (:meth:`normalize`).
    """

    def __init__(self, risk_window_writer: RiskWindowWriter | None = None) -> None:
        self._writer = risk_window_writer

    def normalize(self, record: ExecutionEventRecord) -> NormalizedEvent | None:
        """Map one execution event to a ``NormalizedEvent`` or ``None``.

        Args:
            record: The canonical execution event to normalize.

        Returns:
            A ``NormalizedEvent`` when the source event is risk-relevant, else
            ``None`` (the event carries no governance risk signal).
        """
        try:
            event_type = EventType(record.event_type)
        except ValueError:
            # Unknown / non-catalogue event types carry no risk mapping.
            return None
        category = _RISK_CATEGORY_BY_EVENT.get(event_type)
        if category is None:
            return None
        return NormalizedEvent(
            event_id=record.event_id,
            story_id=record.story_id,
            run_id=record.run_id,
            risk_category=category,
            severity=_SEVERITY_BY_CATEGORY[category],
            observed_at=record.occurred_at,
            source_event_type=event_type,
            payload_excerpt=_excerpt(record.payload),
        )

    def normalize_and_record(
        self, record: ExecutionEventRecord
    ) -> NormalizedEvent | None:
        """Normalize ``record`` and, if risk-relevant, write it to the window.

        Args:
            record: The canonical execution event to normalize and persist.

        Returns:
            The persisted ``NormalizedEvent``, or ``None`` if not risk-relevant.

        Raises:
            RuntimeError: If a risk-relevant event is produced but no
                ``RiskWindowWriter`` was injected (FAIL-CLOSED: a write-site
                without a sink would silently drop governance signals).
        """
        normalized = self.normalize(record)
        if normalized is None:
            return None
        if self._writer is None:
            raise RuntimeError(
                "EventNormalizer.normalize_and_record requires a RiskWindowWriter; "
                "a risk-relevant event would otherwise be silently dropped "
                "(FK-68 §68.8, FAIL-CLOSED)."
            )
        self._writer.record_risk_window_event(normalized)
        return normalized


def _excerpt(payload: dict[str, Any]) -> dict[str, Any]:
    """Return a small JSON-safe excerpt of ``payload`` for audit context."""
    return {key: payload[key] for key in _EXCERPT_KEYS if key in payload}


__all__ = ["EventNormalizer"]
