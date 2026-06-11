"""Consumer-owned runtime read port for the RefreshWorker (FK-62 §62.6.1).

The RefreshWorker reads the runtime schema ONLY through this consumer-owned
Protocol — never with a direct ``runtime.*`` DB connection (FK-62 §62.6.1 hard
rule). The concrete adapter (wired in the composition root) backs this Protocol
with ``telemetry.ProjectionAccessor`` / ``Telemetry.read_projection`` (events,
read-models, FC-mirror tables). This mirrors the AC8 boundary already used by the
``FactRepository`` Protocol: the aggregation module depends on the Protocol, not
on ``state_backend.store``.

The port returns the typed delta events the worker classifies into dirty sets
(FK-62 §62.3.4) and the fully recomputed fact rows for each dirty slice (FK-62
§62.3.5: each slice is recomputed COMPLETELY from the runtime schema, never
incrementally carried over). Keeping the per-slice recompute behind the port is
what lets the worker stay free of a runtime DB connection while owning the
deterministic dirty-set derivation, the cursor/watermark mechanics, the atomic
write orchestration and the guard-counter drain.

Reset purge (FK-62 §62.3.3): the worker consumes the REAL AG3-081/FK-69 reset
surface — ``ProjectionAccessor.purge_run(project_key, story_id, run_id)`` — through
``purge_run_read_models`` on this same port. There is NO second purge abstraction:
the run-scoped FK-69 read-model purge (and the story's guard-counter scratchpad,
which ``purge_run`` already drains, AG3-081/FK-61 §61.4.3 Trigger 4) is owned by
``telemetry-and-events``; the worker only invokes it and recomputes the affected
analytics period rollups.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from datetime import datetime

    from agentkit.kpi_analytics.fact_store.models import (
        FactCorpusPeriod,
        FactGuardPeriod,
        FactPipelinePeriod,
        FactPoolPeriod,
        FactStory,
    )


@dataclass(frozen=True)
class DeltaEvent:
    """One runtime delta event, projected for dirty-set derivation (FK-62 §62.3.4).

    A thin read-only carrier over the canonical ``execution_events`` row. Only the
    fields the worker needs to derive dirty sets are exposed: the monotonic
    ``event_id`` cursor key, the owning ``story_id``, the ``event_type`` (matched
    against the FK-62 §62.3.4 source classes) and ``occurred_at`` (bucketed into
    the weekly period key). ``pool_key`` is the optional LLM role/pool the event
    belongs to (set on ``llm_call``/``review_*`` events).
    """

    event_id: str
    story_id: str
    event_type: str
    occurred_at: datetime
    pool_key: str | None = None
    guard_key: str | None = None
    payload: dict[str, object] = field(default_factory=dict)


@runtime_checkable
class AnalyticsSourcePort(Protocol):
    """Runtime read port for the RefreshWorker (FK-62 §62.6.1).

    All reads of the runtime schema (events, read-models, FC mirror tables) go
    through this port. The concrete adapter wraps ``ProjectionAccessor`` /
    ``Telemetry.read_projection``; the worker holds NO runtime DB connection.
    """

    def get_watermark(self, project_key: str) -> str | None:
        """Return the highest ``execution_events.event_id`` for ``project_key``.

        The watermark is the consistent upper bound of the sync run (FK-62
        §62.3.2 step 3). ``None`` means the project has no events yet.
        """
        ...

    def read_delta_events(
        self,
        project_key: str,
        *,
        after_event_id: str | None,
        through_event_id: str,
    ) -> list[DeltaEvent]:
        """Return the delta events ``after_event_id < event_id <= through_event_id``.

        FK-62 §62.3.2 step 4. ``after_event_id`` is the persisted cursor
        (exclusive); ``None`` reads from the beginning. The list is ordered by the
        monotonic ``event_id``.
        """
        ...

    def recompute_fact_story(
        self, project_key: str, story_id: str
    ) -> FactStory | None:
        """Recompute the ``fact_story`` row for ``story_id`` (FK-62 §62.3.5).

        Reads the story's runtime read-models (``story_metrics`` etc.) and
        computes all columns fresh. ``None`` means the story has no materializable
        fact yet (e.g. an open story with no metrics) — the worker then skips its
        upsert rather than writing a hollow row.
        """
        ...

    def get_story_closed_at(
        self, project_key: str, story_id: str
    ) -> datetime | None:
        """Return the closure instant of ``story_id`` from its runtime metrics.

        FK-62 §62.3.4: the hint story's ``dirty_pipeline_weeks`` entry is
        ``week_start(closed_at)`` of the just-closed story — NOT ``week_start(now)``.
        The worker reads this through the port (it holds no runtime DB connection)
        and threads it into the dirty-set derivation. ``None`` means the story has
        no recorded closure instant yet, in which case the worker falls back to the
        sync instant.
        """
        ...

    def recompute_fact_pool_period(
        self, project_key: str, pool_key: str, week_start: str
    ) -> FactPoolPeriod:
        """Recompute the ``fact_pool_period`` slice for one pool-week (FK-62 §62.3.5)."""
        ...

    def recompute_fact_pipeline_period(
        self, project_key: str, week_start: str
    ) -> FactPipelinePeriod:
        """Recompute the ``fact_pipeline_period`` slice for one week (FK-62 §62.3.5)."""
        ...

    def recompute_fact_corpus_period(
        self, project_key: str, month_start: str
    ) -> FactCorpusPeriod:
        """Recompute the ``fact_corpus_period`` slice for one month (FK-62 §62.3.5).

        FK-62 §62.3.4 corpus special case: ``fc_incidents``/``fc_patterns`` carry
        no event cursor, so the current month is fully recomputed every sync.
        """
        ...

    def recompute_fact_guard_period(
        self, project_key: str, guard_key: str, week_start: str
    ) -> FactGuardPeriod:
        """Recompute the ``fact_guard_period`` slice for one guard-week (FK-62 §62.3.5).

        Reads the ``integrity_violation`` events of the week for ``guard_key``. The
        scratchpad counter contribution is added by the worker from the drained
        ``guard_invocation_counters`` rows (FK-62 §62.2.6), so the runtime side
        only contributes the event-derived invocation/violation counts.
        """
        ...

    def purge_run_read_models(
        self, project_key: str, story_id: str, run_id: str
    ) -> int:
        """Purge the run-bound FK-69 read models of a reset story (FK-62 §62.3.3).

        Consumes the REAL AG3-081/FK-69 reset surface
        ``ProjectionAccessor.purge_run(project_key, story_id, run_id)`` (FK-69
        §69.10.1: a full reset is ``run_id``-scoped, NOT merely ``story_id``-scoped —
        later query-time filtering is forbidden). The concrete adapter delegates to
        that accessor method; AG3-082 only INVOKES it (story §2.2 — AG3-081 owns the
        purge, including the story's guard-counter scratchpad drain it already
        performs, AG3-081/FK-61 §61.4.3 Trigger 4). Returns the number of run-bound
        FK-69 read-model rows removed.
        """
        ...


__all__ = [
    "AnalyticsSourcePort",
    "DeltaEvent",
]
