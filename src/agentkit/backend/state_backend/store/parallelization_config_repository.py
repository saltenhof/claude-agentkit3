"""State-backend repository implementation for planning configuration."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from agentkit.backend.execution_planning.repository import ParallelizationConfigRepository
from agentkit.backend.state_backend.store import facade

if TYPE_CHECKING:
    from agentkit.backend.execution_planning.entities import ParallelizationConfig


class StateBackendParallelizationConfigRepository(
    ParallelizationConfigRepository,
):
    """Persist parallelization configs through the state-backend facade."""

    def __init__(self, store_dir: Path | None = None) -> None:
        self._store_dir = store_dir or Path.cwd()

    def get(self, project_key: str) -> ParallelizationConfig | None:
        return facade.load_parallelization_config(project_key, self._store_dir)

    def upsert(self, config: ParallelizationConfig) -> None:
        facade.save_parallelization_config(config, self._store_dir)
