"""Static compatibility exports for telemetry projection repositories."""

from __future__ import annotations

from agentkit.backend.state_backend.store.telemetry_projection_repositories import (
    FacadePhaseStateProjectionRepository as FacadePhaseStateProjectionRepository,
)
from agentkit.backend.state_backend.store.telemetry_projection_repositories import (
    FacadeQACheckOutcomesRepository as FacadeQACheckOutcomesRepository,
)
from agentkit.backend.state_backend.store.telemetry_projection_repositories import (
    FacadeQAFindingsRepository as FacadeQAFindingsRepository,
)
from agentkit.backend.state_backend.store.telemetry_projection_repositories import (
    FacadeQALayerBatchWriter as FacadeQALayerBatchWriter,
)
from agentkit.backend.state_backend.store.telemetry_projection_repositories import (
    FacadeQAStageResultsRepository as FacadeQAStageResultsRepository,
)
from agentkit.backend.state_backend.store.telemetry_projection_repositories import (
    FacadeRiskWindowRepository as FacadeRiskWindowRepository,
)
from agentkit.backend.state_backend.store.telemetry_projection_repositories import (
    FacadeStoryMetricsRepository as FacadeStoryMetricsRepository,
)
from agentkit.backend.state_backend.store.telemetry_projection_repositories import (
    GuardCounterPurgePort as GuardCounterPurgePort,
)
from agentkit.backend.state_backend.store.telemetry_projection_repositories import (
    PhaseStateProjectionRepository as PhaseStateProjectionRepository,
)
from agentkit.backend.state_backend.store.telemetry_projection_repositories import (
    ProjectionRepositories as ProjectionRepositories,
)
from agentkit.backend.state_backend.store.telemetry_projection_repositories import (
    QACheckOutcomesRepository as QACheckOutcomesRepository,
)
from agentkit.backend.state_backend.store.telemetry_projection_repositories import (
    QAFindingsRepository as QAFindingsRepository,
)
from agentkit.backend.state_backend.store.telemetry_projection_repositories import (
    QALayerBatchWriter as QALayerBatchWriter,
)
from agentkit.backend.state_backend.store.telemetry_projection_repositories import (
    QAStageResultsRepository as QAStageResultsRepository,
)
from agentkit.backend.state_backend.store.telemetry_projection_repositories import (
    RiskWindowRepository as RiskWindowRepository,
)
from agentkit.backend.state_backend.store.telemetry_projection_repositories import (
    StateBackendGuardCounterPurgeAdapter as StateBackendGuardCounterPurgeAdapter,
)
from agentkit.backend.state_backend.store.telemetry_projection_repositories import (
    StoryMetricsRepository as StoryMetricsRepository,
)
from agentkit.backend.state_backend.store.telemetry_projection_repositories import (
    _is_postgres as _is_postgres,
)
from agentkit.backend.state_backend.store.telemetry_projection_repositories import (
    _postgres_connect as _postgres_connect,
)
from agentkit.backend.state_backend.store.telemetry_projection_repositories import (
    _sqlite_connect as _sqlite_connect,
)
from agentkit.backend.state_backend.store.telemetry_projection_repositories import (
    _sqlite_connect_qa as _sqlite_connect_qa,
)
from agentkit.backend.state_backend.store.telemetry_projection_repositories import (
    build_projection_repositories as build_projection_repositories,
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
