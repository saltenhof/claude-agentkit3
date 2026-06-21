"""Closure bounded context (BC 7).

Owns the Closure phase handler and the multi-repo closure saga. The
phase handler is registered on PipelineEngine's PhaseHandlerRegistry by
the orchestrator that wires the run.
"""

from __future__ import annotations

from agentkit.backend.closure.execution_report.records import ExecutionReport
from agentkit.backend.closure.execution_report.writer import write_execution_report
from agentkit.backend.closure.gates import (
    FindingResolutionVerdict,
    evaluate_finding_resolution_gate,
)
from agentkit.backend.closure.merge_sequence import (
    BuildTestOutcome,
    BuildTestPort,
    IntegratedCandidate,
    MergeBlockResult,
    MergeBlockStatus,
    PreMergeScanPort,
    SanityGatePort,
    SanityOutcome,
    ScanOutcome,
    run_pre_merge_and_merge_block,
)
from agentkit.backend.closure.multi_repo_saga import (
    ClosureRepo,
    GitBackend,
    GitCommandResult,
    MultiRepoSagaResult,
    SagaStage,
    SagaStageResult,
    SubprocessGitBackend,
    local_ff_merge_with_rollback,
    pre_merge_check,
    push_main,
    push_story_branches,
    run_multi_repo_closure,
    teardown_worktrees,
)
from agentkit.backend.closure.phase import (
    ClosureConfig,
    ClosurePhaseHandler,
    ClosureProgressStore,
    ClosureVerdict,
)
from agentkit.backend.closure.post_merge_finalization.finalization import (
    DocFidelityFeedbackPort,
    FinalizationResult,
    GuardDeactivationPort,
    PostflightCheck,
    VectorDbSyncPort,
    run_post_merge_finalization,
    run_postflight_checks,
)
from agentkit.backend.closure.post_merge_finalization.records import StoryMetricsRecord

__all__ = [
    "BuildTestOutcome",
    "BuildTestPort",
    "ClosureConfig",
    "ClosurePhaseHandler",
    "ClosureProgressStore",
    "ClosureRepo",
    "ClosureVerdict",
    "DocFidelityFeedbackPort",
    "IntegratedCandidate",
    "ExecutionReport",
    "FinalizationResult",
    "FindingResolutionVerdict",
    "GitBackend",
    "GitCommandResult",
    "GuardDeactivationPort",
    "MergeBlockResult",
    "MergeBlockStatus",
    "MultiRepoSagaResult",
    "PostflightCheck",
    "PreMergeScanPort",
    "SagaStage",
    "SagaStageResult",
    "SanityGatePort",
    "SanityOutcome",
    "ScanOutcome",
    "SubprocessGitBackend",
    "VectorDbSyncPort",
    "evaluate_finding_resolution_gate",
    "local_ff_merge_with_rollback",
    "pre_merge_check",
    "push_main",
    "push_story_branches",
    "run_multi_repo_closure",
    "run_post_merge_finalization",
    "run_postflight_checks",
    "run_pre_merge_and_merge_block",
    "StoryMetricsRecord",
    "teardown_worktrees",
    "write_execution_report",
]
