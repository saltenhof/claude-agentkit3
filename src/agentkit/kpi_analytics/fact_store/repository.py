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
    from agentkit.kpi_analytics.fact_store.models import (
        FactCorpusPeriod,
        FactGuardPeriod,
        FactPipelinePeriod,
        FactPoolPeriod,
        FactStory,
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
        """Return ``fact_story`` rows for ``project_key`` (period bounds ``completed_at``)."""
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


__all__ = ["FactRepository"]
