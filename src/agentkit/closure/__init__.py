"""Closure boundary module."""

from __future__ import annotations

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

__all__ = [
    "ClosureRepo",
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
    "teardown_worktrees",
]
