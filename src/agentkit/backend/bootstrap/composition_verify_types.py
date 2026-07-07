"""Governance and verification type dependencies for the composition root."""

from __future__ import annotations

from agentkit.backend.control_plane.push_verification import PushBarrierEvidencePort
from agentkit.backend.governance.integrity_gate import IntegrityGate
from agentkit.backend.governance.integrity_gate.dim9_sonar import SonarDimensionPort
from agentkit.backend.governance.repository import SetupContextRepository
from agentkit.backend.governance.setup_preflight_gate.edge_provisioning import (
    EdgeProvisioningCoordinator,
)
from agentkit.backend.governance.setup_preflight_gate.phase import SetupPhaseHandler
from agentkit.backend.requirements_coverage.contract import CoverageVerdict
from agentkit.backend.requirements_coverage.top import (
    RequirementsCoverage as RequirementsCoverageProto,
)
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
from agentkit.backend.verify_system.system import VerifySystem

__all__ = [
    "AreGateProvider",
    "ArtifactInvalidationEvent",
    "ArtifactInvalidationSink",
    "BuildTestEvidence",
    "BuildTestEvidencePort",
    "BuildTestPort",
    "CoverageVerdict",
    "EdgeProvisioningCoordinator",
    "IntegrityGate",
    "LlmClient",
    "PushBarrierEvidencePort",
    "QaCyclePushBarrierGate",
    "ReportedHeadEvidence",
    "RequirementsCoverageProto",
    "ReviewCompletionEvent",
    "ReviewCompletionSink",
    "SetupContextRepository",
    "SetupPhaseHandler",
    "SonarDimensionPort",
    "SonarGateInputPort",
    "VerifySystem",
]
