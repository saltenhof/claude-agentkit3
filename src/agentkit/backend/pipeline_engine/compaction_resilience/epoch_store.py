"""Narrow epoch-store port consumed by compaction-resilience hooks."""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from pathlib import Path


class CompactionEpochRepository(Protocol):
    """Atomic story-scoped compaction epoch store."""

    def read_epoch(self, project_key: str, story_id: str) -> int:
        """Return the current epoch for ``(project_key, story_id)``."""
        ...

    def increment_epoch(self, project_key: str, story_id: str) -> int:
        """Atomically increment and return the epoch for ``(project_key, story_id)``."""
        ...


def build_epoch_repository(store_dir: Path | None = None) -> CompactionEpochRepository:
    """Build the productive state-backend epoch repository."""
    from agentkit.backend.state_backend.store.compaction_epoch_repository import (
        StateBackendCompactionEpochRepository,
    )

    return StateBackendCompactionEpochRepository(store_dir=store_dir)


__all__ = ["CompactionEpochRepository", "build_epoch_repository"]
