"""Type-only dependencies for the composition root."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime

from agentkit.backend.closure.gates import TelemetryEvidencePort
from agentkit.backend.closure.merge_sequence import (
    MergeApplicability,
    PreMergeScanPort,
    RepoRunners,
    SanityGatePort,
)
from agentkit.backend.closure.multi_repo_saga import GitBackend as RepoGitBackend
from agentkit.backend.closure.phase import (
    ClosurePhaseHandler,
    ClosureProgressStore,
    GuardCounterFlushPort,
    ModeLockReleasePort,
)
from agentkit.backend.closure.post_merge_finalization.finalization import (
    DocFidelityFeedbackPort,
    GuardDeactivationPort,
    VectorDbSyncPort,
)
from agentkit.backend.code_backend.provider_port import CodeBackendPort
from agentkit.backend.config.models import ConformanceConfig, RepositoryConfig
from agentkit.backend.control_plane.push_verification import PushBarrierEvidencePort
from agentkit.backend.execution_planning.persistence.accessor import PlanningProjectionAccessor
from agentkit.backend.exploration.change_frame import ChangeFrame
from agentkit.backend.exploration.drafting import ExplorationDrafting
from agentkit.backend.exploration.mandate.fine_design import (
    FineDesignEvaluator,
    FineDesignRoundOutcome,
)
from agentkit.backend.exploration.phase import ExplorationPhaseHandler
from agentkit.backend.exploration.review import ExplorationReview
from agentkit.backend.failure_corpus import FailureCorpus
from agentkit.backend.governance.integrity_gate import IntegrityGate
from agentkit.backend.governance.integrity_gate.dim9_sonar import SonarDimensionPort
from agentkit.backend.governance.repository import SetupContextRepository
from agentkit.backend.governance.setup_preflight_gate.edge_provisioning import (
    EdgeProvisioningCoordinator,
)
from agentkit.backend.governance.setup_preflight_gate.phase import SetupPhaseHandler
from agentkit.backend.kpi_analytics import KpiAnalytics
from agentkit.backend.kpi_analytics.dashboard import DashboardService
from agentkit.backend.pipeline_engine.engine import PipelineEngine
from agentkit.backend.pipeline_engine.lifecycle import HandlerResult, PhaseHandlerRegistry
from agentkit.backend.pipeline_engine.phase_envelope.envelope import PhaseEnvelope
from agentkit.backend.pipeline_engine.phase_envelope.store import PhaseEnvelopeStore
from agentkit.backend.project_management.read_model_routes import ReadModelRoutes
from agentkit.backend.project_management.repository import ProjectRepository
from agentkit.backend.requirements_coverage.contract import CoverageVerdict
from agentkit.backend.requirements_coverage.top import (
    RequirementsCoverage as RequirementsCoverageProto,
)
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
from agentkit.backend.verify_system.llm_evaluator.llm_client import LlmClient
from agentkit.backend.verify_system.pre_merge_runner.contract import BuildTestPort
from agentkit.backend.verify_system.qa_cycle.fingerprint import ReportedHeadEvidence
from agentkit.backend.verify_system.qa_cycle.invalidation import (
    ArtifactInvalidationEvent,
    ArtifactInvalidationSink,
)
from agentkit.backend.verify_system.qa_cycle.lifecycle import QaCyclePushBarrierGate
from agentkit.backend.verify_system.review_completion import (
    ReviewCompletionEvent,
    ReviewCompletionSink,
)
from agentkit.backend.verify_system.sonarqube_gate.port import SonarGateInputPort
from agentkit.backend.verify_system.structural.checker import AreGateProvider
from agentkit.backend.verify_system.structural.checks import (
    BuildTestEvidence,
    BuildTestEvidencePort,
)
from agentkit.backend.verify_system.structural.system_evidence import (
    ChangeEvidence,
    PushVerificationPort,
)
from agentkit.backend.verify_system.system import VerifySystem
from agentkit.integration_clients.multi_llm_hub.client import HubClientProtocol

__all__ = [
    "AreGateProvider",
    "ArtifactInvalidationEvent",
    "ArtifactInvalidationSink",
    "BuildTestEvidence",
    "BuildTestEvidencePort",
    "BuildTestPort",
    "Callable",
    "ChangeEvidence",
    "ChangeFrame",
    "ChangeImpact",
    "ClosurePhaseHandler",
    "ClosureProgressStore",
    "CodeBackendPort",
    "ConformanceConfig",
    "CoverageVerdict",
    "DashboardService",
    "DocFidelityFeedbackPort",
    "EdgeProvisioningCoordinator",
    "EventEmitter",
    "ExplorationDrafting",
    "ExplorationPhaseHandler",
    "ExplorationReview",
    "FailureCorpus",
    "FineDesignEvaluator",
    "FineDesignRoundOutcome",
    "GuardCounterFlushPort",
    "GuardDeactivationPort",
    "HandlerResult",
    "HubClientProtocol",
    "IntegrityGate",
    "KpiAnalytics",
    "LlmClient",
    "MergeApplicability",
    "ModeLockReleasePort",
    "PhaseEnvelope",
    "PhaseEnvelopeStore",
    "PhaseHandlerRegistry",
    "PipelineEngine",
    "PlanningProjectionAccessor",
    "PlanningWritePathStoryDependencyRepository",
    "PreMergeScanPort",
    "ProjectRepository",
    "ProjectTelemetryEventSource",
    "ProjectionAccessor",
    "PushBarrierEvidencePort",
    "PushVerificationPort",
    "QaCyclePushBarrierGate",
    "ReadModelRoutes",
    "ReportedHeadEvidence",
    "RepoGitBackend",
    "RepoRunners",
    "RepositoryConfig",
    "RequirementsCoverageProto",
    "ReviewCompletionEvent",
    "ReviewCompletionSink",
    "RuntimeExecutionPurgePort",
    "RuntimeExecutionResidueProbe",
    "SanityGatePort",
    "SetupContextRepository",
    "SetupPhaseHandler",
    "Skills",
    "SonarDimensionPort",
    "SonarGateInputPort",
    "SplitSourceState",
    "StoryContext",
    "StoryService",
    "StorySplitRequest",
    "StoryType",
    "TaskManagementRoutes",
    "TelemetryEvidencePort",
    "VectorDbSyncPort",
    "VerifySystem",
    "datetime",
]
