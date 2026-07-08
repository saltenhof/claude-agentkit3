"""Telemetry-owned ProjectionAccessor repository adapters."""

from __future__ import annotations

from agentkit.backend.state_backend.store.telemetry_projection_repository_common import (
    GuardCounterPurgePort as GuardCounterPurgePort,
)
from agentkit.backend.state_backend.store.telemetry_projection_repository_common import (
    PhaseStateProjectionRepository as PhaseStateProjectionRepository,
)
from agentkit.backend.state_backend.store.telemetry_projection_repository_common import (
    ProjectionRepositories as ProjectionRepositories,
)
from agentkit.backend.state_backend.store.telemetry_projection_repository_common import (
    QACheckOutcomesRepository as QACheckOutcomesRepository,
)
from agentkit.backend.state_backend.store.telemetry_projection_repository_common import (
    QAFindingsRepository as QAFindingsRepository,
)
from agentkit.backend.state_backend.store.telemetry_projection_repository_common import (
    QALayerBatchWriter as QALayerBatchWriter,
)
from agentkit.backend.state_backend.store.telemetry_projection_repository_common import (
    QAStageResultsRepository as QAStageResultsRepository,
)
from agentkit.backend.state_backend.store.telemetry_projection_repository_common import (
    RiskWindowRepository as RiskWindowRepository,
)
from agentkit.backend.state_backend.store.telemetry_projection_repository_common import (
    StoryMetricsRepository as StoryMetricsRepository,
)
from agentkit.backend.state_backend.store.telemetry_projection_repository_common import (
    _is_postgres as _is_postgres,
)
from agentkit.backend.state_backend.store.telemetry_projection_repository_common import (
    _postgres_connect as _postgres_connect,
)
from agentkit.backend.state_backend.store.telemetry_projection_repository_common import (
    _sqlite_connect as _sqlite_connect,
)
from agentkit.backend.state_backend.store.telemetry_projection_repository_common import (
    _sqlite_connect_qa as _sqlite_connect_qa,
)
from agentkit.backend.state_backend.store.telemetry_projection_repository_misc import (
    FacadePhaseStateProjectionRepository as FacadePhaseStateProjectionRepository,
)
from agentkit.backend.state_backend.store.telemetry_projection_repository_misc import (
    FacadeRiskWindowRepository as FacadeRiskWindowRepository,
)
from agentkit.backend.state_backend.store.telemetry_projection_repository_misc import (
    FacadeStoryMetricsRepository as FacadeStoryMetricsRepository,
)
from agentkit.backend.state_backend.store.telemetry_projection_repository_misc import (
    StateBackendGuardCounterPurgeAdapter as StateBackendGuardCounterPurgeAdapter,
)
from agentkit.backend.state_backend.store.telemetry_projection_repository_misc import (
    build_projection_repositories as build_projection_repositories,
)
from agentkit.backend.state_backend.store.telemetry_projection_repository_qa import (
    FacadeQACheckOutcomesRepository as FacadeQACheckOutcomesRepository,
)
from agentkit.backend.state_backend.store.telemetry_projection_repository_qa import (
    FacadeQAFindingsRepository as FacadeQAFindingsRepository,
)
from agentkit.backend.state_backend.store.telemetry_projection_repository_qa import (
    FacadeQALayerBatchWriter as FacadeQALayerBatchWriter,
)
from agentkit.backend.state_backend.store.telemetry_projection_repository_qa import (
    FacadeQAStageResultsRepository as FacadeQAStageResultsRepository,
)

__all__ = [
    "FacadePhaseStateProjectionRepository",
    "FacadeQACheckOutcomesRepository",
    "FacadeQAFindingsRepository",
    "FacadeQALayerBatchWriter",
    "FacadeQAStageResultsRepository",
    "FacadeRiskWindowRepository",
    "FacadeStoryMetricsRepository",
    "GuardCounterPurgePort",
    "PhaseStateProjectionRepository",
    "StateBackendGuardCounterPurgeAdapter",
    "ProjectionRepositories",
    "QACheckOutcomesRepository",
    "QAFindingsRepository",
    "QALayerBatchWriter",
    "QAStageResultsRepository",
    "RiskWindowRepository",
    "StoryMetricsRepository",
    "_is_postgres",
    "_postgres_connect",
    "_sqlite_connect",
    "_sqlite_connect_qa",
    "build_projection_repositories",
]
