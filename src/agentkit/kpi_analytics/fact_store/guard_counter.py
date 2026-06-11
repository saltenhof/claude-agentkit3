"""Guard-invocation counter hot-path + flush triggers (FK-61 §61.4.3, AG3-081).

The ``guard_invocation_counters`` scratchpad is the lightweight volume KPI numerator
for the guard violation rate (FK-61 §61.4.2/§61.4.3): every guard-hook invocation
performs ONE UPSERT (``invocations += 1``; ``blocks += 1`` on a BLOCK), keyed by
``(project_key, story_id, guard_key, week_start)``. The audit trail stays intact —
``integrity_violation`` events are still written to ``execution_events`` (FK-61
§61.4.3); the counter only replaces the high-volume KPI numerator.

This module owns the counter SERVICE (the week-start convention, the hot-path
record and the four FK-61 §61.4.3 flush triggers). The actual drain into
``fact_guard_period`` is the (follow-up) RefreshWorker (AG3-082); a flush here is a
deterministic DRAIN — it reads the matching counter rows and deletes them,
returning the drained rows so the RefreshWorker can re-aggregate them.

AC8 import boundary: this module imports ONLY the consumer-owned
``GuardCounterRepository`` Protocol and the counter model — never the
``state_backend.store`` facade. The concrete adapter is injected.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from agentkit.kpi_analytics.fact_store.models import GuardInvocationCounter
    from agentkit.kpi_analytics.fact_store.repository import GuardCounterRepository

#: FK-61 §61.4.3 Housekeeping trigger: counters older than 24h without an update
#: are flushed (covers aborted / escalated stories).
HOUSEKEEPING_MAX_AGE = timedelta(hours=24)


def week_start_for(instant: datetime) -> str:
    """Return the ISO date string of the Monday that starts ``instant``'s week.

    FK-61 §61.4.3 / FK-62 §62.2.6: the counter key carries a weekly bucket so the
    Week-Rollover flush can drain older weeks and the weekly violation rate can be
    aggregated. The bucket is the UTC Monday (``YYYY-MM-DD``) of the instant's ISO
    week — a deterministic, timezone-normalised key (no locale dependence).

    Args:
        instant: The instant to bucket (naive instants are treated as UTC).

    Returns:
        The ``YYYY-MM-DD`` Monday-start of the instant's ISO week.
    """
    if instant.tzinfo is None:
        instant = instant.replace(tzinfo=UTC)
    utc_instant = instant.astimezone(UTC)
    monday = utc_instant.date() - timedelta(days=utc_instant.weekday())
    return monday.isoformat()


class GuardCounterService:
    """Hot-path UPSERT + the four FK-61 §61.4.3 flush triggers.

    Args:
        repository: The injected ``GuardCounterRepository`` persistence port
            (SQLite/Postgres adapter wired by the composition root / runner edge).
    """

    def __init__(self, repository: GuardCounterRepository) -> None:
        self._repo = repository

    # ------------------------------------------------------------------
    # Hot path (FK-61 §61.4.3: every guard-hook performs ONE UPSERT at the end)
    # ------------------------------------------------------------------

    def record_invocation(
        self,
        *,
        project_key: str,
        story_id: str,
        guard_key: str,
        blocked: bool,
        now: datetime | None = None,
    ) -> None:
        """Record ONE guard invocation (``invocations += 1``; ``blocks += 1`` on block).

        FK-61 §61.4.3 hot path: a single UPSERT keyed by the weekly bucket of
        ``now``. Latency ~0.05-0.1ms; 5-10 rows/story (not 5000 events).

        Args:
            project_key: Owning project scope key.
            story_id: The story the guard ran for.
            guard_key: The guard identity (derived from the hook id at the runner
                edge).
            blocked: Whether the guard's verdict was a BLOCK (the violation-rate
                numerator).
            now: The invocation instant (defaults to ``datetime.now(UTC)``).
        """
        instant = now or datetime.now(UTC)
        self._repo.upsert_invocation(
            project_key=project_key,
            story_id=story_id,
            guard_key=guard_key,
            week_start=week_start_for(instant),
            blocked=blocked,
            updated_at=instant,
        )

    # ------------------------------------------------------------------
    # Flush triggers (FK-61 §61.4.3, Z. 219-229) — four deterministic drains
    # ------------------------------------------------------------------

    def flush_on_closure(
        self, project_key: str, story_id: str
    ) -> list[GuardInvocationCounter]:
        """Trigger 1 — Closure: drain ALL counter rows of the closing story.

        FK-61 §61.4.3: at Closure ``sync_analytics`` reads the counters, writes
        ``fact_guard_period`` and deletes the story's counters. The
        ``fact_guard_period`` write is AG3-082; here the drain reads + deletes the
        rows deterministically and returns them for that follow-up aggregation.
        """
        return self._drain_story(project_key, story_id)

    def flush_week_rollover(
        self, project_key: str, story_id: str, *, now: datetime | None = None
    ) -> list[GuardInvocationCounter]:
        """Trigger 2 — Week-Rollover: drain the story's OLDER-week counter rows.

        FK-61 §61.4.3: when a hook detects a new week, older weekly buckets of the
        SAME story may be flushed. Drains every row whose ``week_start`` is before
        the current week (the current week stays live for further increments).
        """
        instant = now or datetime.now(UTC)
        current_week = week_start_for(instant)
        rows = self._repo.read_counters_for_story_before_week(
            project_key, story_id, current_week
        )
        self._repo.delete_counters_for_story_before_week(
            project_key, story_id, current_week
        )
        return rows

    def flush_housekeeping(
        self, *, now: datetime | None = None
    ) -> list[GuardInvocationCounter]:
        """Trigger 3 — Housekeeping: drain counters older than 24h without update.

        FK-61 §61.4.3: counters older than 24h without an update are flushed (for
        aborted / escalating stories that never reached Closure). Drains every row
        whose ``updated_at`` is strictly older than ``now - 24h``.

        Operationally wired at the PostToolUse health-monitor tick (the periodic
        maintenance path; ``governance.runner._sweep_stale_guard_counters``) — the
        cross-story stale sweep the escalation-detecting subsystem owns.
        """
        cutoff = (now or datetime.now(UTC)) - HOUSEKEEPING_MAX_AGE
        rows = self._repo.read_counters_stale(cutoff)
        self._repo.delete_counters_stale(cutoff)
        return rows

    def flush_on_story_reset(
        self, project_key: str, story_id: str
    ) -> list[GuardInvocationCounter]:
        """Trigger 4 — full Story-Reset: purge ALL counter rows of the reset story.

        FK-61 §61.4.3 (Trigger 4): a full reset purges the story's counters; their
        already-aggregated ``fact_guard_period`` contributions must be re-computed
        (the recompute is AG3-082). Here the rows are read (so the reset path can
        prove they existed) and deleted — no counter row survives the reset.

        Operationally wired into the ONE reset path
        (``ProjectionAccessor.purge_run`` via the ``GuardCounterPurgePort`` adapter
        ``StateBackendGuardCounterPurgeAdapter``): a real full Story-Reset that
        calls ``purge_run`` drains these counters as part of that single path (no
        parallel purge service).
        """
        return self._drain_story(project_key, story_id)

    # ------------------------------------------------------------------
    # internal
    # ------------------------------------------------------------------

    def _drain_story(
        self, project_key: str, story_id: str
    ) -> list[GuardInvocationCounter]:
        rows = self._repo.read_counters_for_story(project_key, story_id)
        self._repo.delete_counters_for_story(project_key, story_id)
        return rows


__all__ = [
    "HOUSEKEEPING_MAX_AGE",
    "GuardCounterService",
    "week_start_for",
]
