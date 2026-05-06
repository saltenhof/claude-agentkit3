from __future__ import annotations

from pathlib import Path

from agentkit.closure.multi_repo_saga import (
    ClosureRepo,
    GitCommandResult,
    SagaStage,
    run_multi_repo_closure,
    teardown_worktrees,
)


class ScriptedGitBackend:
    def __init__(
        self,
        failures: set[tuple[str, tuple[str, ...]]] | None = None,
    ) -> None:
        self.failures = failures or set()
        self.commands: list[tuple[str, tuple[str, ...]]] = []
        self.removed: list[str] = []

    def run(self, repo: ClosureRepo, *args: str) -> GitCommandResult:
        command = (repo.name, args)
        self.commands.append(command)
        if command in self.failures:
            return GitCommandResult(returncode=1, stderr=f"scripted failure: {args}")
        if args == ("rev-parse", "HEAD"):
            return GitCommandResult(returncode=0, stdout=f"{repo.name}-pre\n")
        return GitCommandResult(returncode=0, stdout="ok\n")

    def remove_worktree(self, repo: ClosureRepo) -> None:
        self.removed.append(repo.name)


def _repo(name: str) -> ClosureRepo:
    return ClosureRepo(
        name=name,
        repo_root=Path(f"/repos/{name}"),
        worktree_path=Path(f"/worktrees/{name}"),
    )


def _repos(*names: str) -> list[ClosureRepo]:
    return [_repo(name) for name in names]


def _commands_matching(
    backend: ScriptedGitBackend,
    *expected_args: str,
) -> list[str]:
    return [
        repo_name
        for repo_name, args in backend.commands
        if args == expected_args
    ]


def test_multi_repo_saga_happy_path_two_repos() -> None:
    backend = ScriptedGitBackend()
    result = run_multi_repo_closure(_repos("api", "web"), "AG3-009", backend=backend)

    assert result.success is True
    assert [stage.stage for stage in result.stages] == [
        SagaStage.PRE_MERGE_CHECK,
        SagaStage.PUSH_STORY_BRANCHES,
        SagaStage.LOCAL_FF_MERGE,
        SagaStage.PUSH_MAIN,
        SagaStage.TEARDOWN,
    ]
    assert result.progress.story_branch_pushed is True
    assert result.progress.merge_done is True
    assert result.multi_repo.pre_merge_check_passed == ["api", "web"]
    assert result.multi_repo.pushed_repos == ["api", "web"]
    assert result.multi_repo.merged_repos == ["api", "web"]
    assert result.multi_repo.failed_repo is None
    assert backend.removed == ["api", "web"]


def test_pre_merge_check_failure_blocks_push_and_merge() -> None:
    backend = ScriptedGitBackend(
        {
            (
                "web",
                ("merge-base", "--is-ancestor", "origin/main", "story/AG3-009"),
            )
        }
    )

    result = run_multi_repo_closure(_repos("api", "web"), "AG3-009", backend=backend)

    assert result.success is False
    assert [stage.stage for stage in result.stages] == [SagaStage.PRE_MERGE_CHECK]
    assert result.progress.story_branch_pushed is False
    assert result.progress.merge_done is False
    assert result.multi_repo.pre_merge_check_passed == ["api"]
    assert result.multi_repo.failed_repo == "web"
    assert _commands_matching(backend, "push", "origin", "story/AG3-009") == []
    assert _commands_matching(backend, "merge", "--ff-only", "story/AG3-009") == []


def test_story_branch_push_failure_records_partial_branch_push() -> None:
    backend = ScriptedGitBackend(
        {("web", ("push", "origin", "story/AG3-009"))}
    )

    result = run_multi_repo_closure(_repos("api", "web"), "AG3-009", backend=backend)

    assert result.success is False
    assert result.stages[-1].stage == SagaStage.PUSH_STORY_BRANCHES
    assert result.progress.story_branch_pushed is False
    assert result.multi_repo.pushed_repos == ["api"]
    assert result.multi_repo.failed_repo == "web"
    assert _commands_matching(backend, "merge", "--ff-only", "story/AG3-009") == []


def test_merge_failure_rolls_back_previously_merged_repos() -> None:
    backend = ScriptedGitBackend(
        {("web", ("merge", "--ff-only", "story/AG3-009"))}
    )

    result = run_multi_repo_closure(_repos("api", "web"), "AG3-009", backend=backend)

    assert result.success is False
    assert result.stages[-1].stage == SagaStage.LOCAL_FF_MERGE
    assert result.progress.story_branch_pushed is True
    assert result.progress.merge_done is False
    assert result.multi_repo.failed_repo == "web"
    assert result.multi_repo.rolled_back_repos == ["api"]
    assert result.multi_repo.merged_repos == []
    assert ("api", ("reset", "--hard", "api-pre")) in backend.commands


def test_main_push_failure_records_partial_push_and_rolls_back_remaining() -> None:
    backend = ScriptedGitBackend({("web", ("push", "origin", "main"))})

    result = run_multi_repo_closure(
        _repos("api", "web", "ui"),
        "AG3-009",
        backend=backend,
    )

    assert result.success is False
    assert result.stages[-1].stage == SagaStage.PUSH_MAIN
    assert result.progress.story_branch_pushed is True
    assert result.progress.merge_done is False
    assert result.multi_repo.failed_repo == "web"
    assert result.multi_repo.pushed_repos == ["api"]
    assert result.multi_repo.rolled_back_repos == ["web", "ui"]
    assert ("api", ("reset", "--hard", "api-pre")) not in backend.commands
    assert ("web", ("reset", "--hard", "web-pre")) in backend.commands
    assert ("ui", ("reset", "--hard", "ui-pre")) in backend.commands


def test_teardown_worktrees_is_idempotent() -> None:
    backend = ScriptedGitBackend()
    repos = _repos("api", "web")

    teardown_worktrees(repos, "AG3-009", backend=backend)
    teardown_worktrees(repos, "AG3-009", backend=backend)

    assert backend.removed == ["api", "web", "api", "web"]


def test_single_repo_runs_through_same_saga() -> None:
    backend = ScriptedGitBackend()

    result = run_multi_repo_closure(_repos("api"), "AG3-009", backend=backend)

    assert result.success is True
    assert result.progress.merge_done is True
    assert result.multi_repo.pre_merge_check_passed == ["api"]
    assert result.multi_repo.pushed_repos == ["api"]
    assert result.multi_repo.merged_repos == ["api"]
