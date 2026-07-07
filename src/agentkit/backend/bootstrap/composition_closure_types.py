"""Closure and merge type dependencies for the composition root."""

from __future__ import annotations

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
from agentkit.backend.verify_system.structural.system_evidence import (
    ChangeEvidence,
    PushVerificationPort,
)

__all__ = [
    "ChangeEvidence",
    "ClosurePhaseHandler",
    "ClosureProgressStore",
    "CodeBackendPort",
    "DocFidelityFeedbackPort",
    "GuardCounterFlushPort",
    "GuardDeactivationPort",
    "MergeApplicability",
    "ModeLockReleasePort",
    "PreMergeScanPort",
    "PushVerificationPort",
    "RepoGitBackend",
    "RepoRunners",
    "SanityGatePort",
    "TelemetryEvidencePort",
    "VectorDbSyncPort",
]
