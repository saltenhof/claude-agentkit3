"""State-backend repository implementation for planning configuration."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from agentkit.backend.execution_planning.repository import ParallelizationConfigRepository
from agentkit.backend.state_backend.execution_planning_store import (
    load_parallelization_config,
    save_parallelization_config,
)

if TYPE_CHECKING:
    from agentkit.backend.execution_planning.entities import ParallelizationConfig


class StateBackendParallelizationConfigRepository(
    ParallelizationConfigRepository,
):
    """Persist parallelization configs through the execution-planning store."""

    def __init__(self, store_dir: Path | None = None) -> None:
        self._store_dir = store_dir or Path.cwd()

    def get(self, project_key: str) -> ParallelizationConfig | None:
        return load_parallelization_config(project_key, self._store_dir)

    def upsert(self, config: ParallelizationConfig) -> None:
        save_parallelization_config(config, self._store_dir)
