"""Typed contracts for the analytics RefreshWorker (FK-62 §62.3).

The trigger enum, the dirty-set carrier, the affected-period carrier for the
reset purge, and the typed sync result. All identifiers/enum values are English
(ARCH-55). These are A-bloodtype carriers (no I/O).
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict

_MODEL_CONFIG = ConfigDict(frozen=True, extra="forbid")


class RefreshTrigger(StrEnum):
    """The three event-driven refresh triggers (FK-62 §62.3.1).

    Closed set — there is no string-literal trigger anywhere (story §2.1.1,
    TYPISIERT STATT STRINGS). Each value maps one FK-62 §62.3.1 trigger:

    - ``CLOSURE``: primary trigger, fired at the end of the Closure phase
      (``refresh_analytics`` adapts to this trigger).
    - ``DASHBOARD``: catch-up trigger, fired at ``agentkit dashboard`` start.
    - ``RESET``: purge/rebuild trigger of a full Story-Reset
      (``purge_story_analytics``).
    """

    CLOSURE = "closure"
    DASHBOARD = "dashboard"
    RESET = "reset"


class SyncStatus(StrEnum):
    """Outcome status of one ``sync_analytics`` call (FK-62 §62.3.2)."""

    UP_TO_DATE = "up_to_date"
    SYNCED = "synced"


class SyncResult(BaseModel):
    """Typed result of one ``sync_analytics`` call (FK-62 §62.3.2).

    ``UP_TO_DATE`` is the idempotent no-op outcome (watermark already consumed);
    ``SYNCED`` carries the processed-event count and the advanced watermark.
    """

    model_config = _MODEL_CONFIG

    status: SyncStatus
    trigger: RefreshTrigger
    events_processed: int = 0
    watermark: str | None = None


class AffectedPeriods(BaseModel):
    """The period rollups a reset purge must recompute (FK-62 §62.3.3).

    Each set carries the typed period keys of the four period-grained fact tables
    that the reset of one story touches. Empty sets mean "no period of this grain
    is affected" (the purge still deletes the ``fact_story`` row and drains the
    story's guard counters).
    """

    model_config = _MODEL_CONFIG

    guard_weeks: frozenset[tuple[str, str, str]] = frozenset()
    pool_weeks: frozenset[tuple[str, str, str]] = frozenset()
    pipeline_weeks: frozenset[tuple[str, str]] = frozenset()
    corpus_months: frozenset[tuple[str, str]] = frozenset()


__all__ = [
    "AffectedPeriods",
    "RefreshTrigger",
    "SyncResult",
    "SyncStatus",
]
