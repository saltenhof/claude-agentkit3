"""FactRepository persistence Protocol (FK-62 §62.3, story AG3-038 §2.1.2).

This Protocol is the consumer-owned persistence port for the FactStore. It lives
in the ``kpi_analytics.fact_store`` package (not in ``state_backend.store``) so
the FactStore depends ONLY on this Protocol and never imports the
``state_backend.store`` facade — the AC8 architecture-conformance boundary.

The productive SQLite/Postgres implementation lives in
``agentkit.state_backend.store.fact_repository`` and is wired in the composition
root, mirroring the proven ``ProjectRegistrationRepository`` pattern
(``installer.repository`` Protocol + ``state_backend.store`` adapter).

Fail-closed contract (story §7): a read against a missing fact table propagates
the underlying database error — a missing table is NEVER a silent empty result.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from collections.abc import Sequence
    from contextlib import AbstractContextManager
    from datetime import datetime

    from agentkit.kpi_analytics.fact_store.models import (
        FactCorpusPeriod,
        FactGuardPeriod,
        FactPipelinePeriod,
        FactPoolPeriod,
        FactStory,
        GuardInvocationCounter,
        PeriodFilter,
        SyncState,
    )


@runtime_checkable
class FactRepository(Protocol):
    """Persistence port for the analytics fact tables and ``sync_state``.

    Read methods return the rows for ``project_key`` (optionally bounded by a
    half-open ``PeriodFilter``); upsert methods insert-or-replace a single fact
    row on its natural primary key (idempotent re-write, no duplicate).
    """

    # -- reads --------------------------------------------------------------

    def list_fact_stories(
        self, project_key: str, period: PeriodFilter | None = None
    ) -> list[FactStory]:
        """Return ``fact_story`` rows for ``project_key`` (period bounds ``closed_at``)."""
        ...

    def list_fact_guards(
        self, project_key: str, period: PeriodFilter
    ) -> list[FactGuardPeriod]:
        """Return ``fact_guard_period`` rows for ``project_key`` within ``period``."""
        ...

    def list_fact_pool(
        self, project_key: str, period: PeriodFilter
    ) -> list[FactPoolPeriod]:
        """Return ``fact_pool_period`` rows for ``project_key`` within ``period``."""
        ...

    def list_fact_pipeline(
        self, project_key: str, period: PeriodFilter
    ) -> list[FactPipelinePeriod]:
        """Return ``fact_pipeline_period`` rows for ``project_key`` within ``period``."""
        ...

    def list_fact_corpus(
        self, project_key: str, period: PeriodFilter
    ) -> list[FactCorpusPeriod]:
        """Return ``fact_corpus_period`` rows for ``project_key`` within ``period``."""
        ...

    def get_sync_state(self, project_key: str, key: str) -> SyncState | None:
        """Return the ``sync_state`` cursor for ``(project_key, key)``, or ``None``.

        Project-scoped per FK-62 §62.2.7 (no global refresh pointer).
        """
        ...

    # -- upserts ------------------------------------------------------------

    def upsert_fact_story(self, fact: FactStory) -> None:
        """Insert-or-replace one ``fact_story`` row on ``(project_key, story_id)``."""
        ...

    def upsert_fact_guard(self, fact: FactGuardPeriod) -> None:
        """Insert-or-replace one ``fact_guard_period`` row on its PK."""
        ...

    def upsert_fact_pool(self, fact: FactPoolPeriod) -> None:
        """Insert-or-replace one ``fact_pool_period`` row on its PK."""
        ...

    def upsert_fact_pipeline(self, fact: FactPipelinePeriod) -> None:
        """Insert-or-replace one ``fact_pipeline_period`` row on its PK."""
        ...

    def upsert_fact_corpus(self, fact: FactCorpusPeriod) -> None:
        """Insert-or-replace one ``fact_corpus_period`` row on its PK."""
        ...

    def upsert_sync_state(self, state: SyncState) -> None:
        """Insert-or-replace one ``sync_state`` cursor row on ``(project_key, key)``."""
        ...

    # -- atomic write session (FK-62 §62.3.2/§62.3.3, story §2.1.7) ----------

    def begin_write_session(self) -> AbstractContextManager[FactWriteSession]:
        """Open ONE atomic write session over the analytics tables (FK-62 §62.3.2).

        The session holds a single backend connection/transaction. ALL writes of a
        ``sync_analytics`` call (slice replaces + ``fact_story`` upserts + the
        guard-counter drain + the cursor update) and of a ``purge_story_analytics``
        call run inside it. On clean ``with``-exit the transaction COMMITs; on any
        exception it ROLLs BACK (FK-62 §62.3.2/§62.3.7: no partial commit, the next
        run re-processes the same delta idempotently). The aggregation logic owns
        NO DB connection of its own — it only drives this session (FK-62 §62.6.2).
        """
        ...


@runtime_checkable
class FactWriteSession(Protocol):
    """One atomic transaction over the analytics tables (FK-62 §62.3.2/§62.3.3).

    Bound to a single connection opened by ``FactRepository.begin_write_session``.
    The ``replace_<table>_period`` ports are the FK-62 §62.3.2 DELETE+INSERT slice
    rewrites: every dirty period key in ``keys`` is deleted, then ``rows`` are
    inserted — so a slice that recomputes to no row ends up empty (FK-62 §62.2.8:
    fully reset runs disappear from the fact tables). The guard-counter drain
    methods run in the SAME transaction so the ``fact_guard_period`` write and the
    scratchpad delete commit atomically (FK-62 §62.2.6).
    """

    def upsert_fact_story(self, fact: FactStory) -> None:
        """Insert-or-replace one ``fact_story`` row (idempotent on its PK)."""
        ...

    def delete_fact_story(self, project_key: str, story_id: str) -> int:
        """Delete the ``fact_story`` row of ``(project_key, story_id)``; return rows."""
        ...

    def replace_guard_period(
        self,
        keys: Sequence[tuple[str, str, datetime]],
        rows: list[FactGuardPeriod],
    ) -> None:
        """DELETE the ``(project_key, guard_key, period_start)`` slices, then INSERT ``rows``.

        The ``period_start`` key element is the SAME ``datetime`` the recomputed
        rows carry, so the DELETE matches the stored row regardless of backend
        timestamp encoding.
        """
        ...

    def replace_pool_period(
        self,
        keys: Sequence[tuple[str, str, datetime]],
        rows: list[FactPoolPeriod],
    ) -> None:
        """DELETE the ``(project_key, pool_key, period_start)`` slices, then INSERT ``rows``."""
        ...

    def replace_pipeline_period(
        self,
        keys: Sequence[tuple[str, datetime]],
        rows: list[FactPipelinePeriod],
    ) -> None:
        """DELETE the ``(project_key, period_start)`` slices, then INSERT ``rows``."""
        ...

    def replace_corpus_period(
        self,
        keys: Sequence[tuple[str, datetime]],
        rows: list[FactCorpusPeriod],
    ) -> None:
        """DELETE the ``(project_key, period_start)`` slices, then INSERT ``rows``."""
        ...

    def update_sync_cursor(self, state: SyncState) -> None:
        """Upsert the ``sync_state`` cursor row (FK-62 §62.3.2 step: last write)."""
        ...

    def read_guard_counters_for_story(
        self, project_key: str, story_id: str
    ) -> list[GuardInvocationCounter]:
        """Read the story's ``guard_invocation_counters`` rows (in-session)."""
        ...

    def delete_guard_counters_for_story(
        self, project_key: str, story_id: str
    ) -> int:
        """Delete the story's ``guard_invocation_counters`` rows (in-session); return rows."""
        ...


@runtime_checkable
class GuardCounterRepository(Protocol):
    """Persistence port for the ``guard_invocation_counters`` scratchpad.

    FK-61 §61.4.3 / FK-62 §62.2.6: the lightweight hot-path scratchpad written by
    the guard hooks (one UPSERT per guard call) and drained by the four flush
    triggers (Closure, Week-Rollover, Housekeeping, full Story-Reset). The actual
    drain into ``fact_guard_period`` is the (follow-up) RefreshWorker (AG3-082);
    this port owns the UPSERT and the run-scoped read/delete the flush triggers
    consume.

    Fail-closed: a read against a missing table propagates the backend error — a
    missing table is NEVER a silent empty result.
    """

    def upsert_invocation(
        self,
        *,
        project_key: str,
        story_id: str,
        guard_key: str,
        week_start: str,
        blocked: bool,
        updated_at: datetime,
    ) -> None:
        """UPSERT one guard invocation (``invocations += 1``; ``blocks += 1`` on block).

        FK-61 §61.4.3 verbatim: ``ON CONFLICT(project_key, story_id, guard_key,
        week_start) DO UPDATE SET invocations = invocations + 1, blocks = blocks +
        EXCLUDED.blocks``. Idempotent only at the row-create level; each call
        increments the running counters.
        """
        ...

    def read_counters_for_story(
        self, project_key: str, story_id: str
    ) -> list[GuardInvocationCounter]:
        """Return all counter rows for ``(project_key, story_id)`` (every week)."""
        ...

    def read_counters_for_story_before_week(
        self, project_key: str, story_id: str, week_start: str
    ) -> list[GuardInvocationCounter]:
        """Return counter rows of older weeks (``week_start < week_start``)."""
        ...

    def read_counters_stale(self, cutoff: datetime) -> list[GuardInvocationCounter]:
        """Return counter rows whose ``updated_at`` is strictly older than ``cutoff``."""
        ...

    def delete_counters_for_story(self, project_key: str, story_id: str) -> int:
        """Delete every counter row for ``(project_key, story_id)``; return the count."""
        ...

    def delete_counters_for_story_before_week(
        self, project_key: str, story_id: str, week_start: str
    ) -> int:
        """Delete older-week counter rows (``week_start < week_start``); return the count."""
        ...

    def delete_counters_stale(self, cutoff: datetime) -> int:
        """Delete counter rows older than ``cutoff``; return the deleted count."""
        ...


__all__ = [
    "FactRepository",
    "FactWriteSession",
    "GuardCounterRepository",
]
