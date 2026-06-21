"""Multi-repo closure saga.

AK2 reference: ``T:/codebase/claude-agentkit/agentkit/worktree/merge.py``
(``merge_story_multi_repo`` with ``pre_merge_sha`` rollback).
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass, field
from enum import StrEnum
from typing import TYPE_CHECKING, Protocol

from agentkit.backend.exceptions import WorktreeError
from agentkit.backend.pipeline_engine.phase_executor import (
    ClosureProgress,
    MultiRepoClosureState,
)
from agentkit.backend.utils.git import remove_worktree

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence
    from pathlib import Path


class SagaStage(StrEnum):
    """Named stages of the multi-repo closure saga."""

    PRE_MERGE_CHECK = "pre_merge_check"
    PUSH_STORY_BRANCHES = "push_story_branches"
    LOCAL_FF_MERGE = "local_ff_merge"
    PUSH_MAIN = "push_main"
    TEARDOWN = "teardown"


@dataclass(frozen=True)
class ClosureRepo:
    """One participating repository in closure."""

    name: str
    repo_root: Path
    worktree_path: Path | None = None

    @property
    def command_cwd(self) -> Path:
        """Return the path used for git commands."""

        return self.worktree_path or self.repo_root


@dataclass(frozen=True)
class GitCommandResult:
    """Minimal git command result consumed by the saga."""

    returncode: int
    stdout: str = ""
    stderr: str = ""

    @property
    def ok(self) -> bool:
        """Return whether the command succeeded."""

        return self.returncode == 0


class GitBackend(Protocol):
    """Git side-effect port for the closure saga."""

    def run(self, repo: ClosureRepo, *args: str) -> GitCommandResult:
        """Run one git command in a participating repository."""

    def remove_worktree(self, repo: ClosureRepo) -> None:
        """Remove one repo's story worktree idempotently."""


class SubprocessGitBackend:
    """Git backend using subprocess and ``git worktree remove``."""

    def run(self, repo: ClosureRepo, *args: str) -> GitCommandResult:
        result = subprocess.run(
            ["git", "-C", str(repo.command_cwd), *args],
            capture_output=True,
            text=True,
        )
        return GitCommandResult(
            returncode=result.returncode,
            stdout=result.stdout,
            stderr=result.stderr,
        )

    def remove_worktree(self, repo: ClosureRepo) -> None:
        if repo.worktree_path is None:
            return
        remove_worktree(repo.repo_root, repo.worktree_path)


@dataclass(frozen=True)
class SagaStageResult:
    """Result of one saga stage."""

    stage: SagaStage
    success: bool
    progress: ClosureProgress
    multi_repo: MultiRepoClosureState
    failed_repos: list[str] = field(default_factory=list)
    rolled_back_repos: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    pre_merge_shas: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class MultiRepoSagaResult:
    """Overall result of running all closure saga stages."""

    success: bool
    progress: ClosureProgress
    multi_repo: MultiRepoClosureState
    stages: list[SagaStageResult]
    errors: list[str] = field(default_factory=list)


def pre_merge_check(
    repos: Sequence[ClosureRepo],
    story_id: str,
    *,
    base: str = "main",
    backend: GitBackend | None = None,
) -> list[str]:
    """Return repos whose story branch is not ff-mergeable to origin/base."""

    git = backend or SubprocessGitBackend()
    failed: list[str] = []
    story_branch = _story_branch(story_id)
    origin_base = f"origin/{base}"

    for repo in repos:
        commands = (
            ("fetch", "origin", base),
            ("rev-parse", "--verify", story_branch),
            ("merge-base", "--is-ancestor", origin_base, story_branch),
        )
        if any(not git.run(repo, *command).ok for command in commands):
            failed.append(repo.name)
    return failed


def push_story_branches(
    repos: Sequence[ClosureRepo],
    story_id: str,
    *,
    progress: ClosureProgress | None = None,
    multi_repo: MultiRepoClosureState | None = None,
    backend: GitBackend | None = None,
) -> SagaStageResult:
    """Push all story branches, stopping on the first failed repo."""

    git = backend or SubprocessGitBackend()
    pushed: list[str] = []
    story_branch = _story_branch(story_id)
    state = multi_repo or MultiRepoClosureState()
    current_progress = _ensure_integrity(progress)

    for repo in repos:
        result = git.run(repo, "push", "origin", story_branch)
        if not result.ok:
            failed_state = state.model_copy(
                update={"pushed_repos": pushed, "failed_repo": repo.name},
            )
            return SagaStageResult(
                stage=SagaStage.PUSH_STORY_BRANCHES,
                success=False,
                progress=current_progress,
                multi_repo=failed_state,
                failed_repos=[repo.name],
                errors=[_command_error(repo, "push story branch", result)],
            )
        pushed.append(repo.name)

    passed_progress = current_progress.model_copy(
        update={"story_branch_pushed": True},
    )
    passed_state = state.model_copy(update={"pushed_repos": pushed})
    return SagaStageResult(
        stage=SagaStage.PUSH_STORY_BRANCHES,
        success=True,
        progress=passed_progress,
        multi_repo=passed_state,
    )


def local_ff_merge_with_rollback(
    repos: Sequence[ClosureRepo],
    story_id: str,
    *,
    base: str = "main",
    progress: ClosureProgress | None = None,
    multi_repo: MultiRepoClosureState | None = None,
    backend: GitBackend | None = None,
) -> SagaStageResult:
    """Fast-forward all repos locally, rolling back prior repos on failure."""

    git = backend or SubprocessGitBackend()
    state = multi_repo or MultiRepoClosureState()
    current_progress = _ensure_story_branch_pushed(progress)
    story_branch = _story_branch(story_id)
    merged: list[str] = []
    pre_merge_shas: dict[str, str] = {}

    for repo in repos:
        stage_error = _prepare_target_branch(git, repo, base)
        if stage_error is not None:
            return _merge_failure_result(
                repos,
                merged=merged,
                failed_repo=repo,
                error=stage_error,
                pre_merge_shas=pre_merge_shas,
                progress=current_progress,
                state=state,
                backend=git,
                base=base,
            )

        sha = git.run(repo, "rev-parse", "HEAD")
        if not sha.ok or not sha.stdout.strip():
            return _merge_failure_result(
                repos,
                merged=merged,
                failed_repo=repo,
                error=_command_error(repo, "capture pre_merge_sha", sha),
                pre_merge_shas=pre_merge_shas,
                progress=current_progress,
                state=state,
                backend=git,
                base=base,
            )
        pre_merge_shas[repo.name] = sha.stdout.strip()

        merge = git.run(repo, "merge", "--ff-only", story_branch)
        if not merge.ok:
            return _merge_failure_result(
                repos,
                merged=merged,
                failed_repo=repo,
                error=_command_error(repo, "ff merge story branch", merge),
                pre_merge_shas=pre_merge_shas,
                progress=current_progress,
                state=state,
                backend=git,
                base=base,
            )
        merged.append(repo.name)

    passed_state = state.model_copy(update={"merged_repos": merged})
    return SagaStageResult(
        stage=SagaStage.LOCAL_FF_MERGE,
        success=True,
        progress=current_progress,
        multi_repo=passed_state,
        pre_merge_shas=pre_merge_shas,
    )


def push_main(
    repos: Sequence[ClosureRepo],
    *,
    pre_merge_shas: Mapping[str, str],
    base: str = "main",
    progress: ClosureProgress | None = None,
    multi_repo: MultiRepoClosureState | None = None,
    backend: GitBackend | None = None,
) -> SagaStageResult:
    """Push all target branches, recording partial-push state on failure."""

    git = backend or SubprocessGitBackend()
    state = multi_repo or MultiRepoClosureState()
    current_progress = _ensure_story_branch_pushed(progress)
    pushed: list[str] = []

    for index, repo in enumerate(repos):
        result = git.run(repo, "push", "origin", base)
        if result.ok:
            pushed.append(repo.name)
            continue

        remaining = [candidate.name for candidate in repos[index:]]
        rollback = _rollback_repos(
            repos,
            repo_names=remaining,
            pre_merge_shas=pre_merge_shas,
            backend=git,
            base=base,
        )
        failed_state = state.model_copy(
            update={
                "pushed_repos": pushed,
                "merged_repos": pushed,
                "rolled_back_repos": rollback.rolled_back,
                "failed_repo": repo.name,
            },
        )
        errors = [_command_error(repo, "push main", result), *rollback.errors]
        return SagaStageResult(
            stage=SagaStage.PUSH_MAIN,
            success=False,
            progress=current_progress,
            multi_repo=failed_state,
            failed_repos=[repo.name],
            rolled_back_repos=rollback.rolled_back,
            errors=errors,
            pre_merge_shas=dict(pre_merge_shas),
        )

    passed_state = state.model_copy(update={"pushed_repos": pushed})
    return SagaStageResult(
        stage=SagaStage.PUSH_MAIN,
        success=True,
        progress=current_progress,
        multi_repo=passed_state,
        pre_merge_shas=dict(pre_merge_shas),
    )


def teardown_worktrees(
    repos: Sequence[ClosureRepo],
    story_id: str,
    *,
    backend: GitBackend | None = None,
) -> None:
    """Remove all story worktrees idempotently."""

    del story_id
    git = backend or SubprocessGitBackend()
    for repo in repos:
        git.remove_worktree(repo)


def run_multi_repo_closure(
    repos: Sequence[ClosureRepo],
    story_id: str,
    *,
    base: str = "main",
    backend: GitBackend | None = None,
) -> MultiRepoSagaResult:
    """Run the full five-stage multi-repo closure saga."""

    git = backend or SubprocessGitBackend()
    progress = ClosureProgress(integrity_passed=True)
    state = MultiRepoClosureState()
    stages: list[SagaStageResult] = []

    failed = pre_merge_check(repos, story_id, base=base, backend=git)
    state = state.model_copy(
        update={
            "pre_merge_check_passed": [
                repo.name for repo in repos if repo.name not in failed
            ],
            "failed_repo": failed[0] if failed else None,
        },
    )
    pre_check_result = SagaStageResult(
        stage=SagaStage.PRE_MERGE_CHECK,
        success=not failed,
        progress=progress,
        multi_repo=state,
        failed_repos=failed,
        errors=[f"pre-merge check failed for {repo}" for repo in failed],
    )
    stages.append(pre_check_result)
    if failed:
        return MultiRepoSagaResult(
            success=False,
            progress=progress,
            multi_repo=state,
            stages=stages,
            errors=pre_check_result.errors,
        )

    push_result = push_story_branches(
        repos,
        story_id,
        progress=progress,
        multi_repo=state,
        backend=git,
    )
    stages.append(push_result)
    progress = push_result.progress
    state = push_result.multi_repo
    if not push_result.success:
        return _failed_saga(progress, state, stages)

    merge_result = local_ff_merge_with_rollback(
        repos,
        story_id,
        base=base,
        progress=progress,
        multi_repo=state,
        backend=git,
    )
    stages.append(merge_result)
    progress = merge_result.progress
    state = merge_result.multi_repo
    if not merge_result.success:
        return _failed_saga(progress, state, stages)

    push_main_result = push_main(
        repos,
        pre_merge_shas=merge_result.pre_merge_shas,
        base=base,
        progress=progress,
        multi_repo=state,
        backend=git,
    )
    stages.append(push_main_result)
    progress = push_main_result.progress
    state = push_main_result.multi_repo
    if not push_main_result.success:
        return _failed_saga(progress, state, stages)

    try:
        teardown_worktrees(repos, story_id, backend=git)
    except WorktreeError as exc:
        teardown_result = SagaStageResult(
            stage=SagaStage.TEARDOWN,
            success=False,
            progress=progress,
            multi_repo=state,
            errors=[str(exc)],
            pre_merge_shas=merge_result.pre_merge_shas,
        )
        stages.append(teardown_result)
        return _failed_saga(progress, state, stages)

    progress = progress.model_copy(update={"merge_done": True})
    teardown_result = SagaStageResult(
        stage=SagaStage.TEARDOWN,
        success=True,
        progress=progress,
        multi_repo=state,
        pre_merge_shas=merge_result.pre_merge_shas,
    )
    stages.append(teardown_result)
    return MultiRepoSagaResult(
        success=True,
        progress=progress,
        multi_repo=state,
        stages=stages,
    )


@dataclass(frozen=True)
class _RollbackResult:
    rolled_back: list[str]
    errors: list[str]


def _story_branch(story_id: str) -> str:
    return f"story/{story_id}"


def _ensure_integrity(progress: ClosureProgress | None) -> ClosureProgress:
    current = progress or ClosureProgress(integrity_passed=True)
    if current.integrity_passed:
        return current
    return current.model_copy(update={"integrity_passed": True})


def _ensure_story_branch_pushed(progress: ClosureProgress | None) -> ClosureProgress:
    current = _ensure_integrity(progress)
    if current.story_branch_pushed:
        return current
    return current.model_copy(update={"story_branch_pushed": True})


def _prepare_target_branch(
    backend: GitBackend,
    repo: ClosureRepo,
    base: str,
) -> str | None:
    checkout = backend.run(repo, "checkout", base)
    if not checkout.ok:
        return _command_error(repo, f"checkout {base}", checkout)
    pull = backend.run(repo, "pull", "--ff-only", "origin", base)
    if not pull.ok:
        return _command_error(repo, f"pull origin {base}", pull)
    return None


def _merge_failure_result(
    repos: Sequence[ClosureRepo],
    *,
    merged: Sequence[str],
    failed_repo: ClosureRepo,
    error: str,
    pre_merge_shas: Mapping[str, str],
    progress: ClosureProgress,
    state: MultiRepoClosureState,
    backend: GitBackend,
    base: str,
) -> SagaStageResult:
    rollback = _rollback_repos(
        repos,
        repo_names=merged,
        pre_merge_shas=pre_merge_shas,
        backend=backend,
        base=base,
    )
    remaining_merged = [
        repo_name for repo_name in merged if repo_name not in rollback.rolled_back
    ]
    failed_state = state.model_copy(
        update={
            "merged_repos": remaining_merged,
            "rolled_back_repos": rollback.rolled_back,
            "failed_repo": failed_repo.name,
        },
    )
    return SagaStageResult(
        stage=SagaStage.LOCAL_FF_MERGE,
        success=False,
        progress=progress,
        multi_repo=failed_state,
        failed_repos=[failed_repo.name],
        rolled_back_repos=rollback.rolled_back,
        errors=[error, *rollback.errors],
        pre_merge_shas=dict(pre_merge_shas),
    )


def _rollback_repos(
    repos: Sequence[ClosureRepo],
    *,
    repo_names: Sequence[str],
    pre_merge_shas: Mapping[str, str],
    backend: GitBackend,
    base: str,
) -> _RollbackResult:
    repo_name_set = set(repo_names)
    rolled_back: list[str] = []
    errors: list[str] = []
    for repo in repos:
        if repo.name not in repo_name_set:
            continue
        pre_merge_sha = pre_merge_shas.get(repo.name)
        if not pre_merge_sha:
            errors.append(f"[{repo.name}] pre_merge_sha unavailable")
            continue
        checkout = backend.run(repo, "checkout", base)
        if not checkout.ok:
            errors.append(_command_error(repo, f"rollback checkout {base}", checkout))
            continue
        reset = backend.run(repo, "reset", "--hard", pre_merge_sha)
        if not reset.ok:
            errors.append(_command_error(repo, "rollback reset", reset))
            continue
        rolled_back.append(repo.name)
    return _RollbackResult(rolled_back=rolled_back, errors=errors)


def _failed_saga(
    progress: ClosureProgress,
    state: MultiRepoClosureState,
    stages: Sequence[SagaStageResult],
) -> MultiRepoSagaResult:
    errors: list[str] = []
    for stage in stages:
        errors.extend(stage.errors)
    return MultiRepoSagaResult(
        success=False,
        progress=progress,
        multi_repo=state,
        stages=list(stages),
        errors=errors,
    )


def _command_error(repo: ClosureRepo, action: str, result: GitCommandResult) -> str:
    detail = result.stderr.strip() or result.stdout.strip() or "no command output"
    return f"[{repo.name}] {action} failed: {detail}"


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
