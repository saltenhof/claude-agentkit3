"""Closure bounded context (BC 7).

Owns the Closure phase handler and the multi-repo closure saga. The
phase handler is registered on PipelineEngine's PhaseHandlerRegistry by
the orchestrator that wires the run.
"""

from __future__ import annotations

from agentkit.closure.execution_report.records import ExecutionReport
from agentkit.closure.execution_report.writer import write_execution_report
from agentkit.closure.multi_repo_saga import (
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
from agentkit.closure.phase import ClosureConfig, ClosurePhaseHandler
from agentkit.closure.post_merge_finalization.records import StoryMetricsRecord

__all__ = [
    "ClosureConfig",
    "ClosurePhaseHandler",
    "ClosureRepo",
    "ExecutionReport",
    "GitBackend",
    "GitCommandResult",
    "MultiRepoSagaResult",
    "SagaStage",
    "SagaStageResult",
    "SubprocessGitBackend",
    "local_ff_merge_with_rollback",
    "pre_merge_check",
    "push_main",
    "push_story_branches",
    "run_multi_repo_closure",
    "StoryMetricsRecord",
    "teardown_worktrees",
    "write_execution_report",
]
