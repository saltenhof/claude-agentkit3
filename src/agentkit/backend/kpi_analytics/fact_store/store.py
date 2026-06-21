"""FactStore — the T-driver onto the analytics fact tables (FK-62 §62.3).

The FactStore is a thin, honest facade over a :class:`FactRepository`. It reads
and writes the five fact tables (``fact_story``, ``fact_guard_period``,
``fact_pool_period``, ``fact_pipeline_period``, ``fact_corpus_period``) and the
``sync_state`` cursor, projecting rows to/from the frozen Pydantic models.

AC8 import boundary: this module imports ONLY the consumer-owned
``FactRepository`` Protocol and the fact models — never the
``state_backend.store`` facade. The concrete backend adapter is injected at
construction time by the composition root.

Fail-closed (story §7): the FactStore adds NO empty-result fallback. Whatever the
repository raises (e.g. a missing table) propagates unchanged.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from contextlib import AbstractContextManager

    from agentkit.backend.kpi_analytics.fact_store.models import (
        FactCorpusPeriod,
        FactGuardPeriod,
        FactPipelinePeriod,
        FactPoolPeriod,
        FactStory,
        PeriodFilter,
        SyncState,
    )
    from agentkit.backend.kpi_analytics.fact_store.repository import (
        FactRepository,
        FactWriteSession,
    )


class FactStore:
    """Read/write driver onto the analytics fact tables and ``sync_state``.

    Args:
        repository: The persistence port (SQLite/Postgres adapter) injected by
            the composition root. Held as a ``FactRepository`` — the FactStore
            knows nothing about the concrete backend.
    """

    def __init__(self, repository: FactRepository) -> None:
        self._repository = repository

    # -- reads --------------------------------------------------------------

    def list_fact_stories(
        self, project_key: str, period: PeriodFilter | None = None
    ) -> list[FactStory]:
        """Return ``fact_story`` rows for ``project_key`` (optional period bound)."""
        return self._repository.list_fact_stories(project_key, period)

    def list_fact_guards(
        self, project_key: str, period: PeriodFilter
    ) -> list[FactGuardPeriod]:
        """Return ``fact_guard_period`` rows for ``project_key`` within ``period``."""
        return self._repository.list_fact_guards(project_key, period)

    def list_fact_pool(
        self, project_key: str, period: PeriodFilter
    ) -> list[FactPoolPeriod]:
        """Return ``fact_pool_period`` rows for ``project_key`` within ``period``."""
        return self._repository.list_fact_pool(project_key, period)

    def list_fact_pipeline(
        self, project_key: str, period: PeriodFilter
    ) -> list[FactPipelinePeriod]:
        """Return ``fact_pipeline_period`` rows for ``project_key`` within ``period``."""
        return self._repository.list_fact_pipeline(project_key, period)

    def list_fact_corpus(
        self, project_key: str, period: PeriodFilter
    ) -> list[FactCorpusPeriod]:
        """Return ``fact_corpus_period`` rows for ``project_key`` within ``period``."""
        return self._repository.list_fact_corpus(project_key, period)

    def get_sync_state(self, project_key: str, key: str) -> SyncState | None:
        """Return the ``sync_state`` cursor for ``(project_key, key)``, or ``None``.

        Project-scoped per FK-62 §62.2.7 (no global refresh pointer).
        """
        return self._repository.get_sync_state(project_key, key)

    # -- upserts ------------------------------------------------------------

    def upsert_fact_story(self, fact: FactStory) -> None:
        """Insert-or-replace one ``fact_story`` row (idempotent on its PK)."""
        self._repository.upsert_fact_story(fact)

    def upsert_fact_guard(self, fact: FactGuardPeriod) -> None:
        """Insert-or-replace one ``fact_guard_period`` row (idempotent on its PK)."""
        self._repository.upsert_fact_guard(fact)

    def upsert_fact_pool(self, fact: FactPoolPeriod) -> None:
        """Insert-or-replace one ``fact_pool_period`` row (idempotent on its PK)."""
        self._repository.upsert_fact_pool(fact)

    def upsert_fact_pipeline(self, fact: FactPipelinePeriod) -> None:
        """Insert-or-replace one ``fact_pipeline_period`` row (idempotent on its PK)."""
        self._repository.upsert_fact_pipeline(fact)

    def upsert_fact_corpus(self, fact: FactCorpusPeriod) -> None:
        """Insert-or-replace one ``fact_corpus_period`` row (idempotent on its PK)."""
        self._repository.upsert_fact_corpus(fact)

    def upsert_sync_state(self, state: SyncState) -> None:
        """Insert-or-replace one ``sync_state`` cursor row (idempotent on PK)."""
        self._repository.upsert_sync_state(state)

    # -- atomic write session (FK-62 §62.3.2/§62.3.3) -----------------------

    def begin_write_session(self) -> AbstractContextManager[FactWriteSession]:
        """Open ONE atomic write session over the analytics tables (FK-62 §62.3.2).

        The RefreshWorker drives all of a ``sync_analytics`` / ``purge_story_analytics``
        call through this single transaction (slice replaces + ``fact_story``
        writes + guard-counter drain + cursor update). Commit on clean exit,
        rollback on any exception — no partial commit (FK-62 §62.3.2/§62.3.7).
        The FactStore is still the ONLY write path into ``analytics.*`` (FK-62
        §62.6.2): the session just bundles those writes atomically.
        """
        return self._repository.begin_write_session()


__all__ = ["FactStore"]
