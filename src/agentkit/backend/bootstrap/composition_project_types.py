"""Project, planning, telemetry and pipeline type dependencies."""

from __future__ import annotations

from collections.abc import Callable

from agentkit.backend.config.models import ConformanceConfig, RepositoryConfig
from agentkit.backend.control_plane.takeover_approval_repository import TakeoverApprovalReadSource
from agentkit.backend.execution_planning.persistence.accessor import PlanningProjectionAccessor
from agentkit.backend.failure_corpus import FailureCorpus
from agentkit.backend.kpi_analytics import KpiAnalytics
from agentkit.backend.kpi_analytics.dashboard import DashboardService
from agentkit.backend.pipeline_engine.engine import PipelineEngine
from agentkit.backend.pipeline_engine.lifecycle import HandlerResult, PhaseHandlerRegistry
from agentkit.backend.pipeline_engine.phase_envelope.envelope import PhaseEnvelope
from agentkit.backend.pipeline_engine.phase_envelope.store import PhaseEnvelopeStore
from agentkit.backend.project_management.read_model_routes import ReadModelRoutes
from agentkit.backend.project_management.repository import ProjectRepository
from agentkit.backend.skills import Skills
from agentkit.backend.state_backend.store.planning_story_dependency_repository import (
    PlanningWritePathStoryDependencyRepository,
)
from agentkit.backend.state_backend.store.runtime_execution_purge import (
    RuntimeExecutionPurgePort,
    RuntimeExecutionResidueProbe,
)
from agentkit.backend.story import StoryService
from agentkit.backend.story_context_manager.models import StoryContext
from agentkit.backend.story_context_manager.story_model import ChangeImpact
from agentkit.backend.story_context_manager.types import StoryType
from agentkit.backend.story_split.service import SplitSourceState, StorySplitRequest
from agentkit.backend.task_management.http.routes import TaskManagementRoutes
from agentkit.backend.telemetry.emitters import EventEmitter
from agentkit.backend.telemetry.projection_accessor import ProjectionAccessor
from agentkit.backend.telemetry.repository import ProjectTelemetryEventSource
from agentkit.integration_clients.multi_llm_hub.client import HubClientProtocol

__all__ = [
    "Callable",
    "ChangeImpact",
    "ConformanceConfig",
    "DashboardService",
    "EventEmitter",
    "FailureCorpus",
    "HandlerResult",
    "HubClientProtocol",
    "KpiAnalytics",
    "PhaseEnvelope",
    "PhaseEnvelopeStore",
    "PhaseHandlerRegistry",
    "PipelineEngine",
    "PlanningProjectionAccessor",
    "PlanningWritePathStoryDependencyRepository",
    "ProjectRepository",
    "ProjectTelemetryEventSource",
    "ProjectionAccessor",
    "ReadModelRoutes",
    "RepositoryConfig",
    "RuntimeExecutionPurgePort",
    "RuntimeExecutionResidueProbe",
    "Skills",
    "SplitSourceState",
    "StoryContext",
    "StoryService",
    "StorySplitRequest",
    "StoryType",
    "TaskManagementRoutes",
    "TakeoverApprovalReadSource",
]
